"""Is the first-passage interval better than the interval ASTRA serves? Measured.

The remaining-life interval on the console comes from `PhysicsRul`: the
uncertainty in the fitted rate, propagated through margin / rate. A competing
design, reviewed in another team's repository, models health as a drifting
random walk and takes the interval from its first-passage (inverse Gaussian)
distribution, which also carries the wandering health will do AFTER the
estimate is made. Better on paper is not better on this engine, so both run on
the SAME held-out engines, from the SAME health estimate, and are scored on the
SAME windows.

WHAT DECIDES IT
---------------
An interval is judged first on whether it keeps its promise -- a 95 % interval
must contain the truth about 95 % of the time -- and only then on width.
Under-coverage is the dangerous failure: the engine is flown on an interval
that was not true. Over-coverage only makes an interval too wide to plan with.
The candidate is adopted only if it covers within five points of nominal and
the served interval does not, or both do and the candidate is narrower. The
decision is taken on windows whose true remaining life is inside the
prediction horizon, because that is where a maintenance decision is made.
Whatever it says, the numbers are written down.

    python scripts/eval_rul_interval.py

Writes data/models/rul_interval_comparison.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import config  # noqa: E402
from eval_rul_matched import estimate_health, load_test_frame  # noqa: E402
from layer3_ai import rul_physics as rp  # noqa: E402

# How far below nominal coverage an interval may fall and still be keeping its
# promise, given a finite number of held-out engines.
TOLERANCE = 0.05


def run(make, df, health: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Point, lower and upper per row; NaN where the estimator declines."""
    n = len(df)
    pt, lo, hi = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    hours = df["flight_hours"].to_numpy()
    for _, pos in df.groupby("engine_id", sort=True).indices.items():
        est = make()
        for p in np.sort(pos):
            e = est.update(float(health[p]), float(hours[p]))
            if e.reportable:
                pt[p], lo[p], hi[p] = e.hours, e.lower_hours, e.upper_hours
    return pt, lo, hi


def score(pt, lo, hi, truth, mask, nominal: float) -> dict:
    if not mask.any():
        return {"windows": 0}
    t, p, low, up = truth[mask], pt[mask], lo[mask], hi[mask]
    return {
        "windows": int(mask.sum()),
        "coverage": round(float(((low <= t) & (t <= up)).mean()), 4),
        "nominal": nominal,
        "truth_below_interval": round(float((t < low).mean()), 4),
        "truth_above_interval": round(float((t > up).mean()), 4),
        "median_width_h": round(float(np.median(up - low)), 1),
        "rmse_h": round(float(np.sqrt(np.mean((p - t) ** 2))), 1),
        "late_fraction": round(float((p > t).mean()), 4),
    }


def verdict(served: dict, cand: dict, nominal: float) -> str:
    if not served.get("windows") or not cand.get("windows"):
        return "not decidable: no windows where both estimators answer"
    ok_served = served["coverage"] >= nominal - TOLERANCE
    ok_cand = cand["coverage"] >= nominal - TOLERANCE
    if ok_cand and (not ok_served or cand["median_width_h"] < served["median_width_h"]):
        return "adopt the first-passage interval"
    return "keep the served interval"


def main() -> int:
    began = time.time()
    tcfg = config.load_thresholds()
    nominal = float(tcfg["rul"]["confidence_level"])
    horizon = float(tcfg["rul"]["prediction_horizon_hours"])

    te = load_test_frame()
    health = estimate_health(te)
    truth = te["rul_hours"].to_numpy(dtype=float)
    known = np.isfinite(truth)
    if "censored" in te.columns:
        known &= te["censored"].to_numpy(dtype=float) < 0.5

    served = run(rp.PhysicsRul, te, health)
    cand = run(rp.WienerRul, te, health)
    both = known & np.isfinite(served[0]) & np.isfinite(cand[0])
    near = both & (truth <= horizon)

    def share(x: np.ndarray) -> float | None:
        return round(float(np.isfinite(x[known]).mean()), 4) if known.any() else None

    out = {
        "nominal_coverage": nominal,
        "horizon_h": horizon,
        "tolerance": TOLERANCE,
        "engines": int(te["engine_id"].nunique()),
        "answers_on": {"served": share(served[0]), "candidate": share(cand[0])},
        "matched_all": {"served": score(*served, truth, both, nominal),
                        "candidate": score(*cand, truth, both, nominal)},
        "matched_within_horizon": {"served": score(*served, truth, near, nominal),
                                   "candidate": score(*cand, truth, near, nominal)},
    }
    out["verdict"] = verdict(out["matched_within_horizon"]["served"],
                             out["matched_within_horizon"]["candidate"], nominal)
    out["elapsed_s"] = round(time.time() - began, 1)

    print("=" * 78)
    print("  REMAINING-LIFE INTERVAL: served (rate uncertainty) vs first passage")
    print("=" * 78)
    print(f"  {out['engines']} held-out engines; nominal {nominal:.0%}; horizon {horizon:.0f} h")
    for block in ("matched_all", "matched_within_horizon"):
        print(f"\n  {block}")
        for name in ("served", "candidate"):
            s = out[block][name]
            if not s.get("windows"):
                print(f"    {name:<10} no windows")
                continue
            print(f"    {name:<10} n={s['windows']:>7,}  coverage {s['coverage']:.3f}  "
                  f"below {s['truth_below_interval']:.3f}  above {s['truth_above_interval']:.3f}  "
                  f"median width {s['median_width_h']:.0f} h  RMSE {s['rmse_h']:.0f} h  "
                  f"late {s['late_fraction']:.3f}")
    print(f"\n  VERDICT: {out['verdict']}")

    dest = config.data_dir() / "models" / "rul_interval_comparison.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2))
    print(f"  written {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
