"""Train and evaluate remaining-useful-life estimation -- PRD Part 2 s12.

Run:  python scripts/train_rul.py [--quick]

Three estimates are scored on the same held-out engines: the physics
extrapolation, the LSTM, and the s12.5 confidence-weighted fusion of the two.

Censored engines (those that reached TBO without failing) are KEPT in training
and EXCLUDED from scoring. Their recorded RUL is a lower bound, not a value, so
they train through a survival hinge that penalises only under-prediction, and
they are left out of the metrics because a metric needs a known truth.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from common import config                 # noqa: E402
from layer3_ai import features as feat    # noqa: E402
from layer3_ai import health as hl        # noqa: E402
from layer3_ai import rul_lstm as rl      # noqa: E402
from layer3_ai import rul_physics as rp   # noqa: E402


def load_splits(data_dir=None) -> dict[str, pd.DataFrame]:
    """Load a fleet. `data_dir` selects which one.

    It exists so the model can be trained on the wear-out fleet
    (`data/synthetic_hazard`) and the uniform-onset one with the same code.
    The ceiling was measured on both; comparing a model across them is only
    meaningful if nothing else about the run differs.
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
    """Health per row, per engine, exactly as the fielded system would."""
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


def physics_rul(df: pd.DataFrame, health: np.ndarray) -> np.ndarray:
    """Physics RUL per row. NaN where the trend is not yet established."""
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, default=None,
                    help="write the acceptance metrics here as JSON, so a run "
                         "can be compared with another one afterwards")
    ap.add_argument("--data", type=Path, default=None,
                    help="fleet to train on (default data/synthetic); point "
                         "it at data/synthetic_hazard for the wear-out fleet")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0,
                    help="seeds weight initialisation AND training")
    args = ap.parse_args()
    if args.quick:
        args.epochs, args.stride = 10, 10

    started = time.time()
    fs = feat.extended()
    tcfg = config.load_thresholds()
    length = int(tcfg["detectors"]["tier3"]["sequence_length"])
    rul_max = float(tcfg["rul"]["prediction_horizon_hours"])
    targets = tcfg["rul"]["targets"]

    print("loading, estimating health, windowing...")
    frames = load_splits(args.data)
    seqs = {}
    for split in ("train", "val", "test"):
        df = frames[split]
        df["health_est"] = estimate_health(df)
        df["rul_target"] = rp.piecewise_rul_target(
            df["rul_hours"].to_numpy(), df["chi_true"].to_numpy(), rul_max=rul_max
        )
        X, y, idx = feat.build_sequences(
            df, fs, length=length, stride=args.stride,
            label_columns=("rul_target", "censored"),
        )
        # CENSORED ENGINES ARE KEPT FOR TRAINING, EXCLUDED FROM SCORING.
        #
        # They were dropped entirely -- 39.9 % of windows. The survival
        # literature is explicit that discarding right-censored units costs
        # both efficiency and unbiasedness, and the bias is not random here:
        # censoring removes the healthy, long-lived engines and leaves a
        # training set of engines that failed early. The predicted consequence
        # is over-estimation of failure risk (under-prediction of life), and
        # that is exactly the -123.7 h bias measured on the at-cap band.
        #
        # So a censored window now trains against its LOWER BOUND through the
        # hinge in rul_loss, and is still excluded from the reported metrics,
        # because a metric needs a known truth and a bound is not one.
        cens = (y[:, 1] >= 0.5)
        keep = ~cens
        eng = df["engine_id"].to_numpy()[idx][keep]
        # Flight hour of the window's LAST sample. Carried so the prognostics
        # metrics -- prognostic horizon, alpha-lambda, relative accuracy,
        # convergence -- can reconstruct a per-engine TRAJECTORY. Without it
        # `rul_metrics` silently omits them and the run reports RMSE alone,
        # which DEV-178 established cannot see the failure that matters.
        hrs = df["flight_hours"].to_numpy()[idx][keep]
        seqs[split] = {"X": X, "y": y[:, 0], "c": cens.astype(float),
                       "X_obs": X[keep], "y_obs": y[keep, 0],
                       "idx": idx[keep], "engine": eng, "hours": hrs, "df": df}
        print(f"  {split:<5} {len(X):>6,} windows "
              f"({int(cens.sum()):>6,} censored, kept for training via the "
              f"survival hinge) -> {int(keep.sum()):>6,} scoreable")
    print()

    print("training the LSTM...")
    # SEED BEFORE CONSTRUCTION, not after.
    #
    # train_rul() seeds torch at its top, but the model is built HERE, one line
    # earlier -- so the seed governed only the batch shuffling and the initial
    # weights were drawn from whatever state torch happened to be in. Every run
    # therefore started from a different network.
    #
    # Measured cost: the LSTM's test RMSE moved 111.1 -> 124.5 h between two
    # runs whose only deliberate change was to the PHYSICS scoring, which
    # cannot touch the LSTM at all. That swing is larger than several of the
    # differences this project has been drawing conclusions from.
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    model = rl.RulLstm(len(fs))
    rep = rl.train_rul(
        model, seqs["train"]["X"], seqs["train"]["y"],
        seqs["val"]["X"], seqs["val"]["y"],
        seqs["train"]["c"], seqs["val"]["c"],
        epochs=args.epochs, patience=15, seed=args.seed,
    )
    print(f"  {rep.epochs} epochs in {rep.seconds:.0f}s, best epoch {rep.best_epoch}, "
          f"val loss {rep.best_val_loss:.4f}"
          f"{'  (early stop)' if rep.stopped_early else ''}")
    c_data = rl.confidence_from_val_loss(rep.best_val_loss)
    print(f"  data-driven confidence (s12.5) = 1/(1+val_loss) = {c_data:.3f}")

    # ---------------- evaluate on held-out engines ----------------
    te = seqs["test"]
    df_te = te["df"]
    truth = te["y_obs"]

    # The interval multiplier is fitted on VALIDATION -- data the model did not
    # train on and the test set never sees. Fitting it on test would make the
    # reported coverage a description of the test set rather than a prediction
    # about the fleet, which is the same error as tuning a threshold there.
    q = rl.conformal_q(model, seqs["val"]["X_obs"], seqs["val"]["y_obs"],
                       alpha=0.05)
    print(f"  conformal interval multiplier (95%, fitted on validation) = {q:.2f}"
          f"   [Gaussian assumption would use 1.96]")

    pred_data, lo_data, hi_data = rl.predict_with_interval(model, te["X_obs"], q=q)
    phys_all = physics_rul(df_te, df_te["health_est"].to_numpy())
    pred_phys = phys_all[te["idx"]]
    # THE SAME PIECEWISE TRANSFORM THE TARGET GETS.
    #
    # The target is min(raw RUL, prediction_horizon) and the LSTM is trained on
    # it, so the LSTM cannot predict above the horizon. The physics
    # extrapolation was scored against that target UNCAPPED -- it was being
    # marked against a quantity it had never been asked to predict.
    #
    # Measured: 17.7 % of physics predictions exceeded the 400 h cap (max
    # 1,037 h) and contributed 42.1 % of the total squared error. Capping them
    # the same way moved the physics estimator from RMSE 168.3 / R2 -0.371 --
    # worse than predicting the mean -- to RMSE 134.4 / R2 +0.126.
    #
    # Applied through piecewise_rul_target rather than a bare minimum() so the
    # two sides use ONE definition and cannot drift apart again.
    pred_phys = rp.piecewise_rul_target(pred_phys, rul_max=rul_max)
    have_phys = np.isfinite(pred_phys)

    print("\n" + "=" * 70)
    print("REMAINING USEFUL LIFE, ENGINES NEVER SEEN IN TRAINING")
    print("=" * 70)
    print(f"{len(truth):,} windows from {df_te.engine_id.nunique()} engines; "
          f"physics estimate available on {100*have_phys.mean():.0f}% of them")
    print()

    eng = te["engine"]
    hrs = te["hours"]
    rows = []
    rows.append(("LSTM (data-driven)",
                 rp.rul_metrics(pred_data, truth, unit=eng, t_h=hrs,
                                horizon_hours=rul_max)))
    if have_phys.any():
        rows.append(("physics extrapolation",
                     rp.rul_metrics(pred_phys[have_phys], truth[have_phys],
                                    unit=eng[have_phys], t_h=hrs[have_phys],
                                    horizon_hours=rul_max)))

    # PHYSICS CONFIDENCE, EARNED RATHER THAN ASSERTED.
    #
    # This was a hardcoded 0.8 against the data estimator's earned
    # 1/(1+val_loss) = 0.545, so the weaker estimator took 59 % of the weight
    # on every window -- and the s12.5 average came out WORSE than its own best
    # component (DEV-96). Adding the disagreement gate halved that gap without
    # closing it, because the constant was still there underneath.
    #
    # The physics confidence is now measured the same way the data confidence
    # is: from its own error on VALIDATION, scored by the same
    # 1/(1+loss) form. An estimator that extrapolates badly then earns a low
    # weight instead of asserting a high one.
    val = seqs["val"]
    v_health = val["df"]["health_est"].to_numpy()
    v_phys = rp.piecewise_rul_target(
        physics_rul(val["df"], v_health)[val["idx"]], rul_max=rul_max
    )
    v_ok = np.isfinite(v_phys)
    if v_ok.any():
        v_mse = float(np.mean(((v_phys[v_ok] - val["y_obs"][v_ok]) / 100.0) ** 2))
        c_phys = rl.confidence_from_val_loss(v_mse)
    else:
        c_phys = 0.0
    print(f"  physics confidence, earned on validation the same way = {c_phys:.3f}"
          f"   [was a hardcoded 0.800]")

    # s12.5 fusion, row by row so each carries its own physics confidence.
    fused = np.empty(len(truth))
    for i in range(len(truth)):
        if not have_phys[i]:
            fused[i] = pred_data[i]
            continue
        est = rp.RulEstimate(
            hours=float(pred_phys[i]), lower_hours=float(pred_phys[i]) * 0.7,
            upper_hours=float(pred_phys[i]) * 1.6, estimator_confidence=c_phys,
        )
        f = rl.fuse_rul(float(pred_data[i]), est, data_confidence=c_data,
                        data_lower=float(lo_data[i]), data_upper=float(hi_data[i]))
        fused[i] = f.hours if f.hours is not None else pred_data[i]
    rows.append(("FUSED (s12.5)",
                 rp.rul_metrics(fused, truth, unit=eng, t_h=hrs,
                                horizon_hours=rul_max)))

    cover = float(np.mean((truth >= lo_data) & (truth <= hi_data)))
    print(f"  interval coverage on held-out engines: {100*cover:.1f}% "
          f"(nominal 95%), mean width {np.mean(hi_data - lo_data):.1f} h, "
          f"mean |error| {np.mean(np.abs(pred_data - truth)):.1f} h")
    print()

    hdr = f"  {'estimator':<24}{'RMSE':>8}{'MAE':>8}{'MAPE':>8}{'R2':>8}{'NASA':>11}{'late':>8}"
    print(hdr)
    for name, m in rows:
        print(f"  {name:<24}{m['rmse']:>8.1f}{m['mae']:>8.1f}"
              f"{m['mape']:>8.2f}{m['r2']:>8.3f}{m['nasa_score']:>11.1f}"
              f"{100*m['late_fraction']:>7.0f}%")

    # ---- BELOW-CAP BREAKDOWN (Stage 1.1) -------------------------------
    #
    # 51.9 % of test windows sit exactly at the horizon cap, where the target
    # is a constant and carries no information. Scoring there measures how well
    # the model reproduces a constant, not how well it predicts remaining life.
    # The band BELOW the cap is the one an operator acts on, so it is reported
    # separately -- neither figure alone is honest.
    below = truth < rul_max - 1e-6
    print()
    print("  RMSE split by whether the target is informative")
    print(f"  {'band':<34}{'windows':>9}{'RMSE':>9}{'bias':>9}{'late':>8}")
    for label, mask in (
        ("below the cap (informative)", below),
        (f"at the {rul_max:.0f} h cap (constant)", ~below),
        ("all windows", np.ones(len(truth), dtype=bool)),
    ):
        if mask.sum() < 10:
            continue
        e = pred_data[mask] - truth[mask]
        print(f"  {label:<34}{int(mask.sum()):>9}"
              f"{np.sqrt((e ** 2).mean()):>9.1f}{e.mean():>+9.1f}"
              f"{float((e > 0).mean()):>8.2f}")

    # ---- FUSION ACCEPTANCE (Stage 1.5) ---------------------------------
    #
    # "fused RMSE < LSTM RMSE" is the WRONG criterion for a deliberately
    # conservative estimator. The s12.5 gate exists to trade accuracy for
    # safety, and measurement says it does exactly that: it costs about 15 h of
    # RMSE and buys a lower late-prediction rate. Judging it on RMSE alone
    # would condemn it for doing its job.
    #
    # So: the fusion must REDUCE the late rate, and must not cost more RMSE
    # than the seed-to-seed noise floor allows.
    NOISE_FLOOR_H = 9.4      # measured across three seeds, identical data
    l_m = rp.rul_metrics(pred_data, truth, unit=eng, t_h=hrs, horizon_hours=rul_max)
    f_m = rp.rul_metrics(fused, truth, unit=eng, t_h=hrs, horizon_hours=rul_max)
    late_better = f_m["late_fraction"] < l_m["late_fraction"]
    rmse_ok = f_m["rmse"] <= l_m["rmse"] + 1.5 * NOISE_FLOOR_H
    print()
    print("  Fusion acceptance (conservatism, not accuracy):")
    print(f"    late rate    fused {f_m['late_fraction']:.3f} vs LSTM "
          f"{l_m['late_fraction']:.3f}    "
          f"{'PASS' if late_better else 'FAIL'}")
    print(f"    RMSE cost    fused {f_m['rmse']:.1f} vs LSTM {l_m['rmse']:.1f} h,"
          f" budget {1.5 * NOISE_FLOOR_H:.1f} h    "
          f"{'PASS' if rmse_ok else 'FAIL'}")

    print("\n" + "-" * 70)
    print("Acceptance criteria -- DEV-186. Every one carries its provenance;")
    print("see configs/thresholds.yaml for the source of each number.")
    best = min(rows, key=lambda r: r[1]["rmse"])
    m = best[1]
    print(f"  (best by RMSE: {best[0]})")

    pm = m.get("prognostic")
    sigma = float(m.get("target_sigma", 0.0))
    checks = []

    # SELF-BENCHMARK: the worst this same architecture achieved across the four
    # C-MAPSS subsets. Attainable by construction -- it has already been done.
    if pm is not None:
        checks += [
            ("alpha-lambda", pm["alpha_lambda"], float(targets["alpha_lambda"]),
             ">", "C-MAPSS worst"),
            ("relative accuracy", pm["relative_accuracy"],
             float(targets["relative_accuracy"]), ">", "C-MAPSS worst"),
        ]
    if sigma > 0:
        checks.append(("RMSE / sigma", m["rmse"] / sigma,
                       float(targets["rmse_sigma_ratio"]), "<", "C-MAPSS worst"))

    # Sanity bounds, not gates. See the notes beside each in the config.
    checks += [
        ("NASA score", m["nasa_score"], float(targets["nasa_score"]), "<",
         "range only (DEV-103)"),
        ("late fraction", m["late_fraction"], float(targets["late_fraction"]),
         "<", "ceiling, not a gate"),
    ]

    print(f"  {'metric':<22}{'measured':>10}{'target':>11}  {'':<8}provenance")
    for label, got, want, comp, why in checks:
        ok = got > want if comp == ">" else got < want
        print(f"  {label:<22}{got:>10.3f}{comp + format(want, '.2f'):>11}  "
              f"{'MET' if ok else 'NOT MET':<8}{why}")

    if pm is not None:
        # REPORTED, NOT GATED. An earlier draft set 100 h here on operational
        # reasoning; measuring the same code on C-MAPSS returned horizons of
        # 0.0-6.5 for a method within 1.09x of world state of the art. Saxena's
        # "and STAYS inside the cone" rule is near-binary against any noisy
        # estimator, so a gate would have been a second unreachable target
        # invented exactly like the 25 h one.
        print(f"  {'prognostic horizon':<22}{pm['prognostic_horizon_h']:>10.1f}"
              f"{'--':>11}  {'REPORTED':<8}not a gate; see config")
        print(f"  {'convergence':<22}{pm['convergence']:>10.1f}"
              f"{'--':>11}  {'REPORTED':<8}lower is better")
    else:
        print("  (prognostics metrics absent -- per-engine trajectories were "
              "not supplied to the evaluator)")

    if args.report is not None:
        # A run that only prints its results cannot be compared with another
        # one afterwards. The old-fleet and wear-out-fleet runs had to be set
        # side by side to say whether the simulator change helped the MODEL --
        # and the first attempt at that failed because the numbers existed
        # only in scrollback. The fleet is recorded with them, because the
        # same metric on two fleets is two different measurements.
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "fleet": str(args.data) if args.data else "data/synthetic",
            "seed": args.seed,
            "epochs": args.epochs,
            "best_estimator": best[0],
            "windows": int(m.get("n", 0)),
            "target_sigma": sigma,
            "metrics": {label: round(float(got), 4)
                        for label, got, _, _, _ in checks},
            "prognostic": (
                {k: (round(float(v), 4) if isinstance(v, (int, float)) else v)
                 for k, v in pm.items()} if pm else None),
        }, indent=2), encoding="utf-8")
        print(f"  wrote {args.report}")

    print("-" * 70)
    print("alpha-lambda and relative accuracy are read BEFORE RMSE. RMSE")
    print("averages an engine's whole life, and most of these labels sit at the")
    print("horizon cap (DEV-102), so it reports largely how flat the fixture")
    print("was. The prognostics metrics ask the question that decides an")
    print("airframe: near the end, is it right?")
    print("No international standard sets any of these numbers -- ISO 13381,")
    print("ISO 13374 and SAE ARP6883/6887 define metrics and process only. The")
    print("bar here is what THIS architecture achieves on NASA C-MAPSS.")
    print(f"\ntotal {time.time()-started:.0f}s")

    out = config.data_dir() / "models"
    out.mkdir(parents=True, exist_ok=True)
    # The conformal multiplier goes WITH the weights. It was fitted here, used
    # to report coverage here, and then thrown away, so serving had no
    # calibrated bound and the twin had to withhold the network's figure
    # entirely (PRD Part 4 s7.4a forbids a bare remaining life). An interval
    # measured and then discarded is worse than one never measured: the work
    # was done and the operator still got nothing.
    torch.save({"model": model.state_dict(), "features": list(fs.columns),
                "rul_max": rul_max, "val_loss": rep.best_val_loss,
                "conformal_q": float(q), "conformal_alpha": 0.05,
                "interval_coverage": float(cover)},
               out / "rul_lstm.pt")
    print(f"saved -> {out / 'rul_lstm.pt'}")


if __name__ == "__main__":
    main()
