"""Train and score the survival head -- P(fail within H hours).

The point estimate of remaining hours is near its causal ceiling (see
`layer3_ai/rul_survival.py` for the measurements that establish it). This trains
the reformulation that IS accurate, on the project's own engine-grouped splits,
and reports calibration rather than only discrimination.

    python scripts/train_survival.py
    python scripts/train_survival.py --seeds 0 1 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from common import config  # noqa: E402
from layer3_ai import features as feat  # noqa: E402
from layer3_ai import health as hl  # noqa: E402
from layer3_ai import rul_survival as rs  # noqa: E402
from layer3_ai import sortie_features as sf  # noqa: E402

HEALTH_COLUMNS = [
    "rpm", "cht_max", "cht_spread", "coolant_temperature", "egt_spread",
    "oil_pressure", "oil_temperature", "fuel_flow", "vibration_rms_total",
    "vibration_kurtosis", "battery_voltage", "alternator_current",
    "res_cht", "res_coolant", "res_egt", "res_oil_pressure",
    "res_oil_temperature", "res_fuel_flow",
]


def load_splits(data_dir=None) -> dict[str, pd.DataFrame]:
    """Load a fleet. `data_dir` selects which one.

    Hardcoded to data/synthetic until 2026-09-07, which quietly shipped two
    models trained on DIFFERENT fleets: train_rul.py had gained --data and was
    retrained on the wear-out fleet while this one kept using the uniform-onset
    one. The live twin served both at once, so its two answers to "how long has
    this engine got" came from two different worlds.
    """
    d = data_dir or (config.data_dir() / "synthetic")
    manifest = json.loads((d / "manifest.json").read_text())
    assign = feat.stratified_engine_split(manifest)
    full = pd.concat(
        [pd.read_parquet(d / f"{s}.parquet") for s in ("train", "val", "test")],
        ignore_index=True,
    )
    full["split"] = full["engine_id"].map(assign)
    return {
        s: feat.baseline_residuals(full[full["split"] == s].reset_index(drop=True))
        for s in ("train", "val", "test")
    }


def estimate_health(df: pd.DataFrame) -> np.ndarray:
    """Health per row, per engine -- the same routine train_rul.py uses."""
    out = np.empty(len(df))
    for _, pos in df.groupby("engine_id", sort=True).indices.items():
        pos = np.sort(pos)
        est = hl.HealthEstimator(use_residuals=True)
        sub = df.iloc[pos]
        recs = sub[HEALTH_COLUMNS].to_dict("records")
        oilp, roil = sub["oil_pressure"].to_numpy(), sub["res_oil_pressure"].to_numpy()
        fuel, rfuel = sub["fuel_flow"].to_numpy(), sub["res_fuel_flow"].to_numpy()
        egt, regt = sub["egt_max"].to_numpy(), sub["res_egt"].to_numpy()
        hours = sub["flight_hours"].to_numpy()
        for i, rec in enumerate(recs):
            rec["oil_pressure_predicted"] = oilp[i] - roil[i]
            rec["fuel_flow_predicted"] = fuel[i] - rfuel[i]
            rec["egt_predicted"] = egt[i] - regt[i]
            out[pos[i]] = est.track(est.update(rec).chi, float(hours[i]))["chi_ema"]
    return out


def reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    """Observed frequency against predicted probability.

    The table an AUC cannot give you: told 0.30, does failure actually follow
    about three times in ten? Reported as an artefact rather than summarised
    into one number, because the shape of the miscalibration is the useful part.
    """
    edges = np.linspace(0.0, 1.0, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1.0 else p <= 1.0)
        if m.sum() == 0:
            continue
        out.append({
            "bin": f"{lo:.1f}-{hi:.1f}",
            "n": int(m.sum()),
            "predicted": round(float(p[m].mean()), 4),
            "observed": round(float(y[m].mean()), 4),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=None,
                    help="fleet to train on (default data/synthetic). It must "
                         "match the fleet train_rul.py used, or the twin will "
                         "serve two models that learned different engines.")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--folds", type=int, default=0,
                    help="engine-grouped CV folds. THE variance that matters: "
                         "HistGradientBoosting is deterministic at this data "
                         "size (verified -- random_state changes nothing below "
                         "10,000 rows, where it stops subsampling for binning), "
                         "so a seed sweep measures nothing at all. What varies "
                         "is WHICH ENGINES are held out.")
    ap.add_argument("--out", type=Path,
                    default=Path("data/benchmarks/survival.json"))
    ap.add_argument("--checkpoint", type=Path,
                    default=Path("data/models/survival_head.pkl"),
                    help="write a servable head here for layer4_core to load")
    args = ap.parse_args()
    began = time.time()

    print("loading, estimating health, aggregating to sorties...")
    frames = load_splits(args.data)
    tables = {}
    for split, df in frames.items():
        df["health_est"] = estimate_health(df)
        tables[split] = sf.sortie_table(
            df, feat.extended(), health=df["health_est"].to_numpy()
        )
        print(f"  {split:<5} {len(tables[split]):>5,} sorties from "
              f"{tables[split]['engine_id'].nunique():>3} engines")

    base = [c for c in feat.extended().columns] + [sf.HEALTH_COLUMN]
    columns = sf.feature_columns(feat.extended().columns, health=True)
    columns = [c for c in columns if c in tables["train"].columns]
    print(f"  {len(columns)} features")

    # Censored engines carry a LOWER BOUND on RUL, so "failed within H" is
    # unknowable for them: the engine may have failed just after the record
    # ended. They are excluded from BOTH fitting and scoring rather than
    # labelled 0, which would teach the model that survivors are healthy.
    def usable(t):
        return t[t["censored"] < 0.5].reset_index(drop=True)

    tr, va, te = (usable(tables[s]) for s in ("train", "val", "test"))
    print(f"  uncensored: train {len(tr):,}  val {len(va):,}  test {len(te):,}")

    x_tr, x_va, x_te = (t[columns].to_numpy(dtype=float) for t in (tr, va, te))
    r_tr, r_va, r_te = (t["rul_hours"].to_numpy(dtype=float) for t in (tr, va, te))

    results = []
    for seed in args.seeds:
        # Both calibration paths, scored on the SAME held-out engines, because
        # the validation-set path left the top probability bin over-confident
        # (predicted 1.000, observed 0.872) and the fix has to be shown to work
        # rather than asserted.
        heads = {}
        heads["val-set calibration"] = rs.SurvivalHead(seed=seed)
        heads["val-set calibration"].fit(
            x_tr, r_tr, x_val=x_va, rul_val=r_va, columns=columns)

        # Out-of-fold uses train AND val engines for both fitting and
        # calibration -- still never calibrating a model on rows it saw.
        x_fit = np.vstack([x_tr, x_va])
        r_fit = np.concatenate([r_tr, r_va])
        g_fit = np.concatenate([tr["engine_id"].to_numpy(),
                                va["engine_id"].to_numpy()])
        heads["out-of-fold calibration"] = rs.SurvivalHead(seed=seed)
        heads["out-of-fold calibration"].fit_oof(
            x_fit, r_fit, g_fit, columns=columns)

        for name, head in heads.items():
            rep = head.evaluate(x_te, r_te)
            print()
            print("=" * 80)
            print(f"  SURVIVAL HEAD -- {name} -- held-out engines, seed {seed}")
            print("=" * 80)
            print(rs.format_report(rep))
            results.append({"seed": seed, "calibration": name,
                            "test": rep.as_dict()})

            probs = head.predict_proba(x_te)
            rel = {str(int(h)): reliability(probs[h], rs.labels_for(r_te, h))
                   for h in (12.0, 25.0, 50.0, 100.0) if h in probs}
            results[-1]["reliability"] = rel
            print()
            print("  CALIBRATION at 50 h -- predicted vs actually observed")
            print(f"  {'bin':<12}{'n':>7}{'predicted':>12}{'observed':>11}"
                  f"{'gap':>9}")
            for row in rel.get("50", []):
                gap = row["observed"] - row["predicted"]
                print(f"  {row['bin']:<12}{row['n']:>7,}"
                      f"{row['predicted']:>12.3f}{row['observed']:>11.3f}"
                      f"{gap:>+9.3f}")

    if args.folds >= 3:
        from sklearn.model_selection import GroupKFold

        allt = pd.concat([tr, va, te], ignore_index=True)
        xa = allt[columns].to_numpy(dtype=float)
        ra = allt["rul_hours"].to_numpy(dtype=float)
        ga = allt["engine_id"].to_numpy()
        print()
        print("=" * 80)
        print(f"  ENGINE-GROUPED {args.folds}-FOLD -- the variance that matters")
        print("=" * 80)
        print(f"  {len(np.unique(ga))} uncensored engines, {len(allt):,} sorties")
        per_h: dict[float, list] = {h: [] for h in rs.HORIZONS}
        for fold, (i_tr, i_te) in enumerate(
            GroupKFold(n_splits=args.folds).split(xa, ra, ga)
        ):
            # Calibration needs engines the model did not train on, so the
            # training half is split again BY ENGINE rather than by row.
            eng_tr = np.unique(ga[i_tr])
            cal_eng = set(eng_tr[: max(2, len(eng_tr) // 4)].tolist())
            is_cal = np.array([g in cal_eng for g in ga[i_tr]])
            fit_i, cal_i = i_tr[~is_cal], i_tr[is_cal]
            head = rs.SurvivalHead(seed=0)
            head.fit(xa[fit_i], ra[fit_i],
                     x_val=xa[cal_i], rul_val=ra[cal_i], columns=columns)
            for h in head.evaluate(xa[i_te], ra[i_te]).horizons:
                if not np.isnan(h.auc):
                    per_h[h.horizon_h].append((h.auc, h.brier_skill))
        print(f"  {'horizon':<10}{'AUC mean':>10}{'sd':>8}{'min':>8}"
              f"{'skill mean':>12}{'sd':>8}  folds")
        fold_summary = {}
        for h, vals in per_h.items():
            if not vals:
                continue
            aucs = np.array([v[0] for v in vals])
            sk = np.array([v[1] for v in vals if not np.isnan(v[1])])
            print(f"  {h:<10.0f}{aucs.mean():>10.3f}{aucs.std():>8.3f}"
                  f"{aucs.min():>8.3f}{sk.mean():>12.3f}{sk.std():>8.3f}"
                  f"  {len(aucs)}")
            fold_summary[str(int(h))] = {
                "auc_mean": round(float(aucs.mean()), 4),
                "auc_sd": round(float(aucs.std()), 4),
                "auc_min": round(float(aucs.min()), 4),
                "brier_skill_mean": round(float(sk.mean()), 4),
                "brier_skill_sd": round(float(sk.std()), 4),
                "folds": len(aucs),
            }
        results.append({"grouped_cv": fold_summary, "folds": args.folds})

    if len(args.seeds) > 1:
        print()
        print("  ACROSS SEEDS (test AUC) -- expected to be identical; see --folds")
        for h in rs.HORIZONS:
            vals = [
                x for x in (
                    next((d["auc"] for d in r["test"]["horizons"]
                          if abs(d["horizon_h"] - h) < 1e-9), None)
                    for r in results
                ) if x is not None
            ]
            if vals:
                print(f"    {h:>5.0f} h   mean {np.mean(vals):.3f}  "
                      f"sd {np.std(vals):.3f}")

    # A servable checkpoint, fitted on TRAIN and calibrated on VAL -- the same
    # split the reported scores come from, so what ships is what was measured.
    # Test is not touched. Until this existed the head lived only inside the
    # process that trained it, and the strongest result in the project could
    # not be produced by anything running.
    if args.checkpoint is not None:
        serve = rs.SurvivalHead(seed=0)
        serve.fit(x_tr, r_tr, x_val=x_va, rul_val=r_va, columns=columns)
        serve.save(args.checkpoint, features=columns)
        print(f"  wrote servable checkpoint {args.checkpoint} "
              f"({len(columns)} features)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {"features": columns, "seeds": args.seeds, "results": results},
        indent=2), encoding="utf-8")
    print(f"\n  wrote {args.out}")
    print(f"  {time.time() - began:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
