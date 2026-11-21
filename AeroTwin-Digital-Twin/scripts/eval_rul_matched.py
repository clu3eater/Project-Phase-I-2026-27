"""Compare RUL estimators on IDENTICAL windows -- PHASE A1 verification.

WHY MATCHED WINDOWS
-------------------
The Phase 0 table scored the physics estimate on the 46 % of windows where it
is reportable and the network on all 100 %, then printed the two side by side.
That comparison is not wrong so much as unanswerable: physics declines exactly
where a trend has not established, which is early life, and early life is where
the label sits pinned at the horizon cap. Whichever estimator looks better may
simply have been asked easier questions.

So every row here is scored on the SAME window set -- the intersection where
both estimators answer -- and the full-coverage figures are printed separately
and labelled as such.

WHY THE SERVING PATH IS SCORED SEPARATELY FROM THE TRAINING PATH
-----------------------------------------------------------------
`LstmRulServer` rebuilds the feature vector from live-shaped readings: it
baselines residuals itself, computes the structured residual signature itself,
and maintains its own rolling window. If it disagrees with the training path,
the number served on the aircraft is not the number that was validated -- and
that gap is invisible unless something measures both. Two such skews were found
while building it (an un-baselined residual, and a percent fed into a fraction),
which is the argument for keeping this comparison permanently.

    python scripts/eval_rul_matched.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config  # noqa: E402
from layer3_ai import features as feat  # noqa: E402
from layer3_ai import health as hl  # noqa: E402
from layer3_ai import rul_physics as rp  # noqa: E402
from layer3_ai.rul_lstm import RulLstm  # noqa: E402
from layer3_ai.rul_serving import LstmRulServer  # noqa: E402


def load_test_frame():
    d = config.data_dir() / "synthetic"
    manifest = json.loads((d / "manifest.json").read_text())
    assign = feat.stratified_engine_split(manifest)
    full = pd.concat(
        [pd.read_parquet(d / f"{s}.parquet") for s in ("train", "val", "test")],
        ignore_index=True,
    )
    full["split"] = full["engine_id"].map(assign)
    return feat.baseline_residuals(
        full[full["split"] == "test"].reset_index(drop=True)
    )


def estimate_health(df):
    """Health per row, per engine -- the same routine train_rul.py uses."""
    out = np.empty(len(df))
    cols = [
        "rpm", "cht_max", "cht_spread", "coolant_temperature", "egt_spread",
        "oil_pressure", "oil_temperature", "fuel_flow", "vibration_rms_total",
        "vibration_kurtosis", "battery_voltage", "alternator_current",
        "res_cht", "res_coolant", "res_egt", "res_oil_pressure",
        "res_oil_temperature", "res_fuel_flow",
    ]
    for _, pos in df.groupby("engine_id", sort=True).indices.items():
        pos = np.sort(pos)
        est = hl.HealthEstimator(use_residuals=True)
        sub = df.iloc[pos]
        recs = sub[cols].to_dict("records")
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


def physics_rul(df, health):
    out = np.full(len(df), np.nan)
    for _, pos in df.groupby("engine_id", sort=True).indices.items():
        pos = np.sort(pos)
        est = rp.PhysicsRul()
        hours = df["flight_hours"].to_numpy()[pos]
        for i, p in enumerate(pos):
            e = est.update(float(health[p]), float(hours[i]))
            if e.reportable:
                out[p] = e.hours
    return out


def serving_path_rul(df, fs, length, checkpoint):
    """Replay each engine through `LstmRulServer`, exactly as the aircraft would.

    Per engine, in flight-hour order, one reading at a time. The server does
    its own residual baselining, so the RAW residual columns are handed to it --
    the frame's already-baselined ones would be baselined twice.
    """
    raw = df.copy()
    out = np.full(len(df), np.nan)
    for _, pos in raw.groupby("engine_id", sort=True).indices.items():
        pos = np.sort(pos)
        server = LstmRulServer(checkpoint, feature_set=fs, sequence_length=length)
        if not server.available:
            raise SystemExit(f"serving path unavailable: {server.unavailable_reason}")
        sub = raw.iloc[pos]
        recs = sub.to_dict("records")
        hours = sub["flight_hours"].to_numpy()
        for i, rec in enumerate(recs):
            res = server.observe(rec, float(hours[i]))
            if res.reportable:
                out[pos[i]] = res.hours
    return out


def training_path_rul(df, fs, length, stride, checkpoint):
    """The training pipeline's own windowing and prediction."""
    X, y, idx = feat.build_sequences(
        df, fs, length=length, stride=stride,
        label_columns=("rul_target", "censored"),
    )
    ck = torch.load(checkpoint, map_location="cpu", weights_only=False)
    model = RulLstm(len(fs))
    model.load_state_dict(ck["model"])
    model.eval()
    with torch.no_grad():
        pred = np.concatenate([
            model(torch.tensor(X[i:i + 512], dtype=torch.float32)).numpy()
            for i in range(0, len(X), 512)
        ])
    return np.clip(pred, 0.0, float(ck.get("rul_max") or 400.0)), y, idx


def row(name, pred, truth, unit, t_h, horizon):
    m = rp.rul_metrics(pred, truth, unit=unit, t_h=t_h, horizon_hours=horizon)
    pm = m.get("prognostic") or {}
    return {
        "estimator": name, "n": int(len(pred)),
        "rmse": m["rmse"], "rmse_sigma": m["rmse"] / m["target_sigma"],
        "r2": m["r2"], "alpha_lambda": pm.get("alpha_lambda"),
        "relative_accuracy": pm.get("relative_accuracy"),
        "late": m["late_fraction"], "nasa": m["nasa_score"],
    }


def show(title, rows):
    print()
    print(f"  {title}")
    print(f"  {'estimator':<34}{'n':>7}{'RMSE':>8}{'rmse/s':>8}{'R2':>8}"
          f"{'a-l':>7}{'RA':>7}{'late':>7}")
    for r in rows:
        al = "  --  " if r["alpha_lambda"] is None else f'{r["alpha_lambda"]:.3f}'
        ra = "  --  " if r["relative_accuracy"] is None else f'{r["relative_accuracy"]:.3f}'
        print(f"  {r['estimator']:<34}{r['n']:>7,}{r['rmse']:>8.1f}"
              f"{r['rmse_sigma']:>8.3f}{r['r2']:>8.3f}{al:>7}{ra:>7}"
              f"{r['late']:>7.3f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    began = time.time()

    tcfg = config.load_thresholds()
    horizon = float(tcfg["rul"]["prediction_horizon_hours"])
    length = int(tcfg["detectors"]["tier3"]["sequence_length"])
    fs = feat.extended()
    checkpoint = config.data_dir() / "models" / "rul_lstm.pt"

    te = load_test_frame()
    te["health_est"] = estimate_health(te)
    te["rul_target"] = rp.piecewise_rul_target(
        te["rul_hours"].to_numpy(), te["chi_true"].to_numpy(), rul_max=horizon
    )

    pred_lstm, y, idx = training_path_rul(te, fs, length, args.stride, checkpoint)
    keep = y[:, 1] < 0.5                      # censored excluded from scoring
    truth = y[keep, 0]
    idx_k = idx[keep]
    pred_lstm = pred_lstm[keep]
    unit = te["engine_id"].to_numpy()[idx_k]
    t_h = te["flight_hours"].to_numpy()[idx_k]

    phys_raw = physics_rul(te, te["health_est"].to_numpy())[idx_k]
    # BOTH FORMS, because they answer different questions.
    #
    # Capped is the fair SCORE: the target is min(raw RUL, horizon) and the
    # network is trained on it, so marking physics against an uncapped
    # prediction judges it on a quantity it was never asked for --
    # `train_rul.py:210` makes exactly this argument and applies the cap.
    #
    # Uncapped is what PRODUCTION actually serves: `PhysicsRul` caps at TBO
    # (1,200 h), not at the 400 h scoring horizon, so the figure that reached
    # an operator before A1 is the uncapped one. Reporting only the capped
    # number would flatter the estimator this change replaces.
    phys_all = rp.piecewise_rul_target(phys_raw, rul_max=horizon)
    serve_all = serving_path_rul(te, fs, length, checkpoint)[idx_k]

    print("=" * 86)
    print("  RUL ESTIMATORS ON IDENTICAL WINDOWS -- A1 verification")
    print("=" * 86)
    print(f"  {len(truth):,} scoreable windows from "
          f"{len(np.unique(unit))} held-out engines; horizon {horizon:.0f} h; "
          f"sigma {np.std(truth):.1f} h")

    have_phys = np.isfinite(phys_all)
    have_serve = np.isfinite(serve_all)
    both = have_phys & have_serve
    print(f"  physics answers on {100*have_phys.mean():.0f} %, "
          f"serving path on {100*have_serve.mean():.0f} %, "
          f"both on {100*both.mean():.0f} %")

    full = [
        row("LSTM (training path)", pred_lstm, truth, unit, t_h, horizon),
        row("LSTM (SERVING path)", serve_all[have_serve], truth[have_serve],
            unit[have_serve], t_h[have_serve], horizon),
        row("physics (capped, fair score)", phys_all[have_phys], truth[have_phys],
            unit[have_phys], t_h[have_phys], horizon),
        row("physics (uncapped, as served)", phys_raw[have_phys], truth[have_phys],
            unit[have_phys], t_h[have_phys], horizon),
    ]
    show("FULL COVERAGE -- each estimator on every window it answers "
         "(NOT comparable across rows)", full)

    matched = [
        row("LSTM (training path)", pred_lstm[both], truth[both],
            unit[both], t_h[both], horizon),
        row("LSTM (SERVING path)", serve_all[both], truth[both],
            unit[both], t_h[both], horizon),
        row("physics (capped, fair score)", phys_all[both], truth[both],
            unit[both], t_h[both], horizon),
        row("physics (uncapped, as served)", phys_raw[both], truth[both],
            unit[both], t_h[both], horizon),
    ]
    show("MATCHED -- identical windows, the only comparable table", matched)

    skew = float(np.sqrt(np.mean(
        (serve_all[both] - pred_lstm[both]) ** 2
    )))
    print()
    print(f"  train/serve agreement: RMSE between the two paths = {skew:.2f} h")
    print("  (0 would mean the aircraft computes exactly what was validated;")
    print("   a large value means the serving path is a different feature map)")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(
            {"full": full, "matched": matched, "train_serve_rmse": skew,
             "windows": int(len(truth)), "matched_windows": int(both.sum())},
            indent=2), encoding="utf-8")
        print(f"\n  wrote {args.out}")
    print(f"\n  {time.time()-began:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
