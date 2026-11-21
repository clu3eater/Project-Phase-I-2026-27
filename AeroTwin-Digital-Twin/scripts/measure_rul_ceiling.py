"""The information ceiling on RUL: what a PERFECT state observer could do.

WHY THIS EXISTS
---------------
Every RUL target this project has carried was invented, and each was found
impossible only after somebody tried to hit it. The PRD's 25 h (DEV-102), a
100 h prognostic horizon (DEV-188), and then rmse_sigma_ratio 0.71 borrowed
from C-MAPSS (DEV-190). Three times, the same mistake: a number chosen from
reasoning or from another dataset, never from THIS one.

A target is only meaningful against what is achievable, so this measures that
directly. It predicts RUL from the ground-truth internal degradation state --
the `deg_*` columns and the true health indices, which are the simulator's own
hidden variables and which NO SENSOR CAN EVER OBSERVE. Any sensor-based
estimator is strictly worse informed, so this is an upper bound on all of them.

WHY GROUPED CROSS-VALIDATION
----------------------------
Split by ENGINE, never by row. Rows from one engine are near-duplicates of each
other, so a random split lets the model memorise an engine in training and
recognise it in test, and the "ceiling" then measures memorisation. Grouped by
engine it measures what generalises to an airframe never seen before, which is
the only thing an operator cares about.

WHY A GRADIENT BOOSTER AND NOT THE PROJECT'S LSTM
-------------------------------------------------
The question is how much INFORMATION the state carries, not how well a
particular architecture extracts it. A gradient booster on tabular state is a
strong, low-variance, assumption-light estimator, and using the LSTM here would
confound the ceiling with the LSTM's own limitations -- which is exactly the
confusion this script exists to remove.

WHAT A CEILING DOES AND DOES NOT LICENSE
-----------------------------------------
It licenses: "no model can beat this on this data, so a target above it is
unreachable." It does NOT license: "therefore our model is good." The gap
between the sensor model and this bound is the real headroom, and reporting
both is the point.

    python scripts/measure_rul_ceiling.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config  # noqa: E402
from layer3_ai import prognostic_metrics as pmx  # noqa: E402

# Folds for the grouped split. 5 over ~73 uncensored engines leaves roughly 15
# per held-out fold, which is the same order as the real test split.
N_FOLDS = 5


def oracle_columns(df: pd.DataFrame) -> list[str]:
    """The simulator's hidden state: everything a sensor cannot reach.

    These are precisely the columns `features.FORBIDDEN_PREFIXES` bans from
    ever becoming a model input. Using them HERE is the point -- the ceiling is
    defined by what perfect knowledge of them would buy.
    """
    return (
        [c for c in df.columns if c.startswith("deg_")]
        + [c for c in ("chi_true", "thi_true", "mhi_true", "comb_hi_true")
           if c in df.columns]
    )


def load_sortie_state(rul_max: float, data_dir: Path | None = None
                      ) -> pd.DataFrame:
    """One row per (engine, sortie): the true state at the end of that sortie.

    Aggregated to sortie level rather than left at 1 Hz because the prognostics
    metrics are TRAJECTORY metrics -- they ask how one engine's estimate behaves
    over its life -- and 50 near-identical samples from inside one sortie are
    one observation of that trajectory, not fifty.

    `data_dir` selects the fleet. It exists so the ceiling can be measured on
    the wear-out fleet and the uniform-onset fleet with the same code: the
    comparison is the whole point of the simulator change, and a ceiling
    measured by two different scripts would not be a comparison.
    """
    d = data_dir or (config.data_dir() / "synthetic")
    full = pd.concat(
        [pd.read_parquet(d / f"{s}.parquet") for s in ("train", "val", "test")],
        ignore_index=True,
    )
    cols = oracle_columns(full)
    agg = {c: "last" for c in cols}
    agg.update({"flight_hours": "max", "rul_hours": "last", "censored": "last"})
    g = (full.groupby(["engine_id", "sortie"], as_index=False)
              .agg(agg)
              .sort_values(["engine_id", "sortie"])
              .reset_index(drop=True))

    # Censored engines carry a LOWER BOUND, not a label. Scoring against one
    # measures how close the model came to a number that was never the answer.
    g = g[g["censored"] < 0.5].reset_index(drop=True)
    g["rul_target"] = np.minimum(g["rul_hours"].to_numpy(), rul_max)
    return g


def grouped_predictions(
    x: np.ndarray, y: np.ndarray, groups: np.ndarray, *, seed: int
) -> np.ndarray:
    """Out-of-fold predictions, split by engine."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.model_selection import GroupKFold

    out = np.zeros_like(y, dtype=float)
    for train_idx, test_idx in GroupKFold(n_splits=N_FOLDS).split(x, y, groups):
        model = HistGradientBoostingRegressor(max_iter=300, random_state=seed)
        model.fit(x[train_idx], y[train_idx])
        out[test_idx] = model.predict(x[test_idx])
    return out


def score(pred, y, groups, t_h, rul_max) -> dict:
    rmse = float(np.sqrt(np.mean((pred - y) ** 2)))
    sigma = float(np.std(y))
    trajectories = pmx.trajectories_from_frame(groups, t_h, pred, y)
    rep = pmx.evaluate(trajectories, informative_below_h=rul_max - 1e-6)
    return {
        "rmse": round(rmse, 3),
        "target_sigma": round(sigma, 3),
        "rmse_sigma_ratio": round(rmse / sigma, 4) if sigma > 0 else None,
        "alpha_lambda": rep.alpha_lambda,
        "relative_accuracy": rep.relative_accuracy,
        "prognostic_horizon_h": rep.prognostic_horizon_h,
        "convergence": rep.convergence,
        "late_fraction": rep.late_fraction,
        "scored_engines": rep.scored_engines,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=None,
                    help="write the ceiling as JSON here "
                         "(default data/benchmarks/rul_ceiling.json)")
    ap.add_argument("--data", type=Path, default=None,
                    help="fleet to measure (default data/synthetic); point it "
                         "at data/synthetic_hazard for the wear-out fleet")
    args = ap.parse_args()
    began = time.time()

    tcfg = config.load_thresholds()
    rul_max = float(tcfg["rul"]["prediction_horizon_hours"])

    g = load_sortie_state(rul_max, args.data)
    cols = oracle_columns(g)
    x = g[cols].to_numpy(dtype=float)
    y = g["rul_target"].to_numpy(dtype=float)
    groups = g["engine_id"].to_numpy()
    t_h = g["flight_hours"].to_numpy(dtype=float)

    print("=" * 78)
    print("  RUL INFORMATION CEILING -- perfect internal state, unseen engines")
    print("=" * 78)
    print(f"  {len(g):,} sortie rows   {len(np.unique(groups))} uncensored engines"
          f"   {len(cols)} oracle channels")
    print(f"  horizon cap {rul_max:.0f} h   target sigma {np.std(y):.1f} h")
    print(f"  rows pinned at the cap: "
          f"{100 * float((y >= rul_max - 1e-6).mean()):.1f} %")
    print()

    pred = grouped_predictions(x, y, groups, seed=args.seed)
    raw = score(pred, y, groups, t_h, rul_max)

    # Remaining life must decrease. Enforcing it costs nothing and is standard.
    mono = monotone_by_engine(pred, groups, t_h)
    with_mono = score(mono, y, groups, t_h, rul_max)

    print(f"  {'':<24}{'rmse/sigma':>12}{'alpha-lambda':>14}"
          f"{'rel accuracy':>14}{'RMSE h':>9}")
    for label, s in (("oracle", raw), ("oracle + monotone", with_mono)):
        print(f"  {label:<24}{s['rmse_sigma_ratio']:>12.3f}"
              f"{s['alpha_lambda']:>14.3f}{s['relative_accuracy']:>14.3f}"
              f"{s['rmse']:>9.1f}")

    print()
    print("  NO MODEL CAN BEAT THESE ON THIS DATA. A target above them is")
    print("  unreachable regardless of architecture, features or fleet size.")

    out_path = args.out or (config.data_dir() / "benchmarks" / "rul_ceiling.json")
    record = {
        "measured": time.strftime("%Y-%m-%d"),
        "seed": args.seed,
        "folds": N_FOLDS,
        "sortie_rows": int(len(g)),
        "engines": int(len(np.unique(groups))),
        "oracle_channels": cols,
        "horizon_hours": rul_max,
        "oracle": raw,
        "oracle_monotone": with_mono,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"\n  wrote {out_path}")
    print(f"  {time.time() - began:.0f}s")
    return 0


def monotone_by_engine(pred, groups, t_h):
    from layer3_ai.rul_physics import monotone_trajectory
    return monotone_trajectory(pred, groups, t_h)


if __name__ == "__main__":
    raise SystemExit(main())
