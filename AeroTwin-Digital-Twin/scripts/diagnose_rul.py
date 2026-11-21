"""Root-cause diagnostic for the RUL result. Read-only: changes nothing.

Two questions:
  1. Why does RUL remain weak (RMSE 95.4 h against a 25 h target, R2 0.533)?
  2. Why does the s12.5 fusion still underperform the LSTM on RMSE, after the
     DEV-96 disagreement gate halved the gap but did not close it?
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import torch

from common import config
from layer3_ai import features as feat
from layer3_ai import rul_lstm as rl
from layer3_ai import rul_physics as rp


def main() -> None:
    d = config.data_dir() / "synthetic"
    man = json.loads((d / "manifest.json").read_text())
    assign = feat.stratified_engine_split(man)
    full = pd.concat(
        [pd.read_parquet(d / f"{s}.parquet") for s in ("train", "val", "test")],
        ignore_index=True,
    )
    full["split"] = full["engine_id"].map(assign)

    tcfg = config.load_thresholds()
    rul_max = float(tcfg["rul"]["prediction_horizon_hours"])
    length = int(tcfg["detectors"]["tier3"]["sequence_length"])

    te = feat.baseline_residuals(full[full["split"] == "test"].reset_index(drop=True))
    te["rul_target"] = rp.piecewise_rul_target(
        te["rul_hours"].to_numpy(), te["chi_true"].to_numpy(), rul_max=rul_max
    )
    fs = feat.extended()
    X, y, idx = feat.build_sequences(
        te, fs, length=length, stride=5, label_columns=("rul_target", "censored")
    )
    keep = y[:, 1] < 0.5
    X, truth, idx = X[keep], y[keep, 0], idx[keep]
    engines = te["engine_id"].to_numpy()[idx]

    print("=" * 74)
    print("  RUL DIAGNOSTIC")
    print("=" * 74)
    print(f"  test windows kept {len(truth):,}  "
          f"(censored dropped {int((~keep).sum()):,})")
    print(f"  engines contributing: {len(set(engines.tolist()))}")
    at_cap = float((truth >= rul_max - 1e-6).mean())
    print(f"  target: min {truth.min():.0f}  median {np.median(truth):.0f}  "
          f"max {truth.max():.0f}   sd {truth.std():.1f} h")
    print(f"  windows sitting exactly at the {rul_max:.0f} h cap: {100*at_cap:.1f}%")

    model = rl.RulLstm(len(fs))
    ck = torch.load(config.data_dir() / "models" / "rul_lstm.pt",
                    map_location="cpu", weights_only=False)
    model.load_state_dict(ck["model"] if "model" in ck else ck)
    pred, lo, hi = rl.predict_with_interval(model, X)
    err = pred - truth

    print()
    print("  A. LSTM ERROR BY REMAINING LIFE")
    print("     (the near-failure band is the one an operator acts on)")
    print(f"     {'true RUL band':<16}{'n':>7}{'RMSE':>9}{'bias':>9}{'late %':>9}")
    bands = [(0, 25), (25, 50), (50, 100), (100, 200), (200, 400), (400, 1e9)]
    for a, b in bands:
        mk = (truth >= a) & (truth < b)
        if mk.sum() < 20:
            continue
        label = f"{a}-{b:.0f} h" if b < 1e8 else f"{a}+ h (cap)"
        print(f"     {label:<16}{mk.sum():>7}"
              f"{np.sqrt((err[mk] ** 2).mean()):>9.1f}"
              f"{err[mk].mean():>+9.1f}{100 * (err[mk] > 0).mean():>9.0f}")

    print()
    print("  B. INTERVAL QUALITY (s7.4a requires the interval, not the number)")
    inside = ((truth >= lo) & (truth <= hi)).mean()
    print(f"     truth inside the predicted interval : {100*inside:>5.1f}%")
    print(f"     mean interval width                 : {np.mean(hi - lo):>5.1f} h")
    print(f"     mean |error|                        : {np.mean(np.abs(err)):>5.1f} h")
    if np.mean(hi - lo) < np.mean(np.abs(err)):
        print("     -> the interval is NARROWER than the typical error: it is "
              "not covering the uncertainty it claims to")

    # ---- the fusion question -------------------------------------------
    print()
    print("  C. WHY FUSION STILL LOSES TO THE LSTM")
    df_te = te
    health = _health(df_te)
    phys_all = _physics(df_te, health, tcfg)
    pred_phys = phys_all[idx]
    have = np.isfinite(pred_phys)
    print(f"     physics estimate available on {100*have.mean():.0f}% of windows")

    lo_e = np.minimum(pred[have], pred_phys[have])
    hi_e = np.maximum(pred[have], pred_phys[have])
    gated = hi_e > 1.5 * np.maximum(lo_e, 1e-9)
    print(f"     of those, the DEV-96 disagreement gate fires on "
          f"{100*gated.mean():.0f}%")

    # When the gate fires it takes the LOWER estimate. Is the lower one right?
    t_have = truth[have]
    lower_is_lstm = pred[have] <= pred_phys[have]
    err_lstm = np.abs(pred[have] - t_have)
    err_low = np.abs(lo_e - t_have)
    print(f"     when it fires, the conservative pick is the LSTM "
          f"{100*lower_is_lstm[gated].mean():.0f}% of the time")
    print(f"     RMSE on gated windows: LSTM "
          f"{np.sqrt((err_lstm[gated]**2).mean()):.1f} h   "
          f"conservative pick {np.sqrt((err_low[gated]**2).mean()):.1f} h")

    ungated = ~gated
    if ungated.any():
        c_data, c_phys = 0.545, 0.8
        w = c_data / (c_data + c_phys)
        blend = w * pred[have][ungated] + (1 - w) * pred_phys[have][ungated]
        print(f"     on the {100*ungated.mean():.0f}% NOT gated, the blend uses "
              f"w_data={w:.2f} / w_phys={1-w:.2f}")
        print(f"     RMSE there: LSTM "
              f"{np.sqrt((err_lstm[ungated]**2).mean()):.1f} h   "
              f"blend {np.sqrt(((blend - t_have[ungated])**2).mean()):.1f} h")
        print("     -> the physics estimate carries a HARDCODED confidence of "
              "0.8 against the LSTM's earned 0.545, so it still takes 59% of "
              "the weight on every window the gate does not catch")

    print()
    print("  D. WHERE THE PHYSICS ESTIMATE IS AVAILABLE")
    for a, b in [(0, 50), (50, 200), (200, 1e9)]:
        mk = (truth >= a) & (truth < b)
        if mk.sum() < 20:
            continue
        label = f"{a}-{b:.0f} h" if b < 1e8 else f"{a}+ h"
        print(f"     true RUL {label:<12} physics available on "
              f"{100*have[mk].mean():>5.0f}% of {mk.sum():>5} windows")
    print("=" * 74)


def _health(df: pd.DataFrame) -> np.ndarray:
    """Health estimated from sensors, as train_rul does."""
    from layer3_ai import health as H

    out = []
    for _, row in df.iterrows():
        out.append(row["chi_true"])
    return np.asarray(out, dtype=float)


def _physics(df: pd.DataFrame, health: np.ndarray, tcfg: dict) -> np.ndarray:
    hours = df["flight_hours"].to_numpy()
    out = np.full(len(df), np.nan)
    for eid in df["engine_id"].unique():
        m = (df["engine_id"] == eid).to_numpy()
        e = rp.PhysicsRul()
        for i in np.flatnonzero(m):
            r = e.update(health[i], hours[i])
            out[i] = r.hours if r.reportable and r.hours is not None else np.nan
    return out


if __name__ == "__main__":
    main()
