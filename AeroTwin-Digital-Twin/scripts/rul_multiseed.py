"""RUL evaluated over several seeds, because a single run is not a result.

WHY THIS EXISTS
---------------
The RUL model was, until recently, constructed BEFORE torch was seeded --
``model = RulLstm(...)`` ran a line earlier than ``torch.manual_seed()`` inside
the trainer -- so every run began from different initial weights and the seed
governed only the batch order.

The cost was measured once the bug was fixed: across three seeds on identical
data and code, test RMSE moved 117.2 / 124.4 / 126.6 h, R2 moved 0.167 / 0.196
/ 0.287, and the NASA score moved 478 / 690 / 3,108 -- a factor of 6.5.

That is the noise floor. Several conclusions this project had drawn sat inside
it, including a 117.7 -> 95.4 h "improvement" attributed to a feature change.
A single-run RUL comparison below roughly 10 h of RMSE is not interpretable,
and the NASA score is not interpretable from a single run at all.

So: every reported RUL figure is a mean and a standard deviation over N seeds,
and the spread is printed beside it rather than hidden.

    python scripts/rul_multiseed.py --seeds 3
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent

# Lines the child prints that we want to collect.
ROW = re.compile(
    r"^\s{2}(LSTM \(data-driven\)|physics extrapolation|FUSED \(s12\.5\))\s+"
    r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(-?[\d.]+)\s+([\d.e+]+)\s+(\d+)%"
)
COVER = re.compile(r"interval coverage on held-out engines:\s*([\d.]+)%")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--epochs", type=int, default=60)
    args = ap.parse_args()

    rows: dict[str, list[list[float]]] = {}
    covers: list[float] = []

    for seed in range(args.seeds):
        print(f"--- seed {seed} ---", flush=True)
        out = subprocess.run(
            [sys.executable, "-u", str(REPO / "scripts" / "train_rul.py"),
             "--seed", str(seed), "--epochs", str(args.epochs)],
            cwd=REPO, capture_output=True, text=True,
        )
        if out.returncode != 0:
            print(out.stdout[-2000:])
            print(out.stderr[-2000:])
            return 1
        for line in out.stdout.splitlines():
            m = ROW.match(line)
            if m:
                rows.setdefault(m.group(1), []).append(
                    [float(m.group(i)) for i in (2, 3, 4, 5, 6, 7)]
                )
            c = COVER.search(line)
            if c:
                covers.append(float(c.group(1)))

    print()
    print("=" * 78)
    print(f"  RUL OVER {args.seeds} SEEDS  (mean +/- sd)")
    print("=" * 78)
    print(f"  {'estimator':<24}{'RMSE':>16}{'R2':>16}{'late %':>14}")
    for name, vals in rows.items():
        a = np.asarray(vals)
        print(f"  {name:<24}"
              f"{a[:, 0].mean():>9.1f} +/-{a[:, 0].std():>4.1f}"
              f"{a[:, 3].mean():>9.3f} +/-{a[:, 3].std():>5.3f}"
              f"{a[:, 5].mean():>8.0f} +/-{a[:, 5].std():>4.0f}")
    if covers:
        c = np.asarray(covers)
        print(f"\n  interval coverage       {c.mean():>9.1f} +/-{c.std():>4.1f} %"
              f"   (nominal 95 %, calibrated on validation)")

    # The NASA score is reported as a RANGE, never a mean: it is exponential in
    # the error, so one bad window dominates it and a mean across seeds would
    # imply a stability the metric does not have.
    for name, vals in rows.items():
        a = np.asarray(vals)
        print(f"  NASA {name:<20}{a[:, 4].min():>12.0f} to {a[:, 4].max():<12.0f}"
              f" (range, not mean -- exponential metric)")

    print()
    print("  A single-run RUL difference smaller than about 10 h of RMSE is")
    print("  inside this noise and must not be reported as an improvement.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
