"""Score the health estimator against ground truth -- PRD Part 2 s9.

Run:  python scripts/eval_health.py

The estimator sees only what a sensor could have measured. ``chi_true`` comes
from the simulator's internal degradation state, which no instrument on the
aircraft can observe. That gap is what makes the score meaningful rather than
circular.

Two forms are compared: the absolute-threshold indices as PRD s9.2 specifies
them, and the residual form. If operating-point normalisation matters, it
shows up here.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from common import config                 # noqa: E402
from layer3_ai import features as feat    # noqa: E402
from layer3_ai import health as hl        # noqa: E402


def load_test() -> pd.DataFrame:
    d = config.data_dir() / "synthetic"
    manifest = json.loads((d / "manifest.json").read_text())
    assign = feat.stratified_engine_split(manifest)
    full = pd.concat(
        [pd.read_parquet(d / f"{s}.parquet") for s in ("train", "val", "test")],
        ignore_index=True,
    )
    full["split"] = full["engine_id"].map(assign)
    return feat.baseline_residuals(full[full["split"] == "test"].reset_index(drop=True))


def run(df: pd.DataFrame, use_residuals: bool, smoothed: bool = False) -> np.ndarray:
    """Per-engine so the windowed indices see a continuous history."""
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
        est = hl.HealthEstimator(use_residuals=use_residuals)
        sub = df.iloc[pos]
        recs = sub[cols].to_dict("records")
        # The residual is measured minus predicted, so the prediction the
        # ratio-based indices need is recovered by subtraction.
        oilp = sub["oil_pressure"].to_numpy()
        roil = sub["res_oil_pressure"].to_numpy()
        fuel = sub["fuel_flow"].to_numpy()
        rfuel = sub["res_fuel_flow"].to_numpy()
        egt = sub["egt_max"].to_numpy()
        regt = sub["res_egt"].to_numpy()
        hours = sub["flight_hours"].to_numpy()
        for i, rec in enumerate(recs):
            rec["oil_pressure_predicted"] = oilp[i] - roil[i]
            rec["fuel_flow_predicted"] = fuel[i] - rfuel[i]
            rec["egt_predicted"] = egt[i] - regt[i]
            chi = est.update(rec).chi
            # PRD Part 2 s9.4 Method 1: decisions are taken on the smoothed
            # index, not the raw per-sample value. A single sample of CHI is
            # dominated by sensor noise; alpha = 0.1 is deliberately slow.
            sm = est.track(chi, float(hours[i]))
            out[pos[i]] = sm["chi_ema"] if smoothed else chi
    return out


def main() -> None:
    started = time.time()
    df = load_test()
    truth = df["chi_true"].to_numpy()
    healthy = feat.healthy_mask(df)
    print(f"test rows {len(df):,} across {df.engine_id.nunique()} engines")
    print(f"truth CHI: min {truth.min():.3f}  median {np.median(truth):.3f}  "
          f"max {truth.max():.3f}")
    print(f"genuinely healthy rows: {int(healthy.sum()):,}")
    print()

    rows = []
    for label, use_res, sm in (
        ("PRD s9.2 absolute thresholds", False, False),
        ("residual-normalised", True, False),
        ("residual + EMA smoothing (s9.4)", True, True),
    ):
        chi = run(df, use_res, sm)
        mae = float(np.mean(np.abs(chi - truth)))
        bias = float(np.mean(chi - truth))
        corr = float(np.corrcoef(chi, truth)[0, 1])
        # The number that matters operationally: how often does it call a
        # genuinely healthy engine degraded?
        false_degraded = float(np.mean(chi[healthy] < 0.80))
        false_fault = float(np.mean(chi[healthy] < 0.70))
        print(f"--- {label} ---")
        print(f"  MAE vs truth        {mae:.3f}")
        print(f"  bias (est - truth)  {bias:+.3f}")
        print(f"  correlation         {corr:+.3f}")
        print(f"  healthy engines called DEGRADED (CHI<0.80): {100*false_degraded:5.1f}%")
        print(f"  healthy engines called POOR/worse (CHI<0.70): {100*false_fault:5.1f}%")
        print()
        rows.append((label, mae, corr, false_degraded))

    a, b, c = rows
    print("=" * 66)
    print(f"  MAE                 {a[1]:.3f} -> {b[1]:.3f} -> {c[1]:.3f}")
    print(f"  correlation         {a[2]:+.3f} -> {b[2]:+.3f} -> {c[2]:+.3f}")
    print(f"  healthy mislabelled  {100*a[3]:.1f}% -> {100*b[3]:.1f}% "
          f"-> {100*c[3]:.1f}%")
    print("=" * 66)
    print("  (absolute -> residual-normalised -> plus the smoothing the PRD")
    print("   already specifies for decisions in s9.4)")
    print(f"total {time.time()-started:.0f}s")


if __name__ == "__main__":
    main()
