"""Does the physics-informed loss actually help? -- measured, not asserted.

Run:  python scripts/eval_pinn.py

Fits three models on the same split and scores all three on engines none of
them trained on:

    physics alone     the MVEM unaided, i.e. predicting no correction
    data-driven       the same network with the physics loss switched off
    hybrid            the same network with it switched on

The two networks differ ONLY in the physics weight, so any difference between
them is attributable to the loss and not to a different architecture,
initialisation or schedule.

If the hybrid does not win, this prints that it does not win.
"""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# The generator's own split, IMPORTED rather than copied. Written out here as
# range(1, 61) and range(81, 101), it silently became wrong the moment the
# fleet grew to 200 engines: half the training engines would have gone unused
# and engines 61-120 would have been treated as unseen while the generator
# considered them training data.
from layer2_physics.synth_data_gen import (  # noqa: E402
    SPLIT_TEST as TEST_ENGINES,
    SPLIT_TRAIN as TRAIN_ENGINES,
)
TARGET = "cht_max"          # the MEASURED temperature, in degC
# The physics model's own prediction is recovered from the residual the
# generator recorded: res_cht = measured - physics, so physics = measured - res.
RESIDUAL = "res_cht"


def _load(engines) -> tuple[np.ndarray, np.ndarray, list[int]]:
    import pandas as pd

    from layer3_ai import pinn

    rows, seen = [], []
    for e in engines:
        shard = REPO / "data" / "synthetic" / "_shards" / f"engine_{e:04d}.pkl"
        if not shard.exists():
            continue
        with open(shard, "rb") as fh:
            rows += pickle.load(fh)["rows"]
        seen.append(e)
    if not rows:
        return np.empty((0, len(pinn.INPUTS))), np.empty(0), []

    df = pd.DataFrame(rows)
    raw_inputs = [c for c in pinn.INPUTS if c != "cht_physics"]
    df = df.dropna(subset=raw_inputs + [TARGET, RESIDUAL])
    df["cht_physics"] = df[TARGET] - df[RESIDUAL]
    return (df[list(pinn.INPUTS)].to_numpy(dtype=np.float32),
            df[TARGET].to_numpy(dtype=np.float32), seen)


def main() -> int:
    from layer3_ai import pinn

    if not pinn.TORCH:
        print(pinn.UNAVAILABLE)
        return 1

    xtr, ytr, tr_seen = _load(TRAIN_ENGINES)
    xte, yte, te_seen = _load(TEST_ENGINES)
    if len(xtr) == 0 or len(xte) == 0:
        print("no fleet shards found; run the generator first")
        return 1

    # Standardise on TRAIN statistics only. Using the test set's own mean would
    # leak it into the fit and flatter every model equally, which is worse than
    # flattering one -- it would hide the comparison this script exists for.
    mu, sd = xtr.mean(0), xtr.std(0) + 1e-8
    xtr_n, xte_n = (xtr - mu) / sd, (xte - mu) / sd

    # Subsample the training rows: 60 engines is a few hundred thousand rows,
    # and the correction is a smooth low-dimensional function -- this is a
    # comparison between losses, not a race for the last decimal.
    rng = np.random.default_rng(0)
    idx = rng.choice(len(xtr_n), size=min(40000, len(xtr_n)), replace=False)

    print(f"train: {len(idx):,} rows from {len(tr_seen)} engines")
    print(f"test : {len(xte_n):,} rows from {len(te_seen)} engines, none fitted on")
    print()

    # The physics baseline is scored in degC from the UNSTANDARDISED column.
    r = pinn.compare(xtr_n[idx], ytr[idx], xte_n, yte,
                     xte[:, pinn.I_PHYSICS],
                     physics_weight=1.0, engines_test=te_seen)
    d = r.as_dict()

    print("  RMSE on held-out engines, degC of cylinder-head temperature")
    print(f"    physics alone    {d['physics_rmse']:8.4f}")
    print(f"    data-driven      {d['data_rmse']:8.4f}")
    print(f"    hybrid + physics {d['hybrid_rmse']:8.4f}")
    print()
    print(f"  physically impossible derivative sign, share of test points")
    print(f"    data-driven      {d['data_violations']:8.2%}")
    print(f"    hybrid + physics {d['hybrid_violations']:8.2%}")
    print()
    print(f"  WINNER: {d['winner']}")

    if d["winner"] != "hybrid":
        print("         The physics loss did not improve accuracy on this "
              "fleet. Reported rather than buried -- a physics-informed model "
              "that is not better is a result.")
    if d["hybrid_violations"] < d["data_violations"]:
        print(f"         The constraint did what it is for: impossible "
              f"derivatives fall from {d['data_violations']:.2%} to "
              f"{d['hybrid_violations']:.2%}. That is a soundness gain "
              f"independent of the RMSE.")

    out = REPO / "data" / "models" / "pinn_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, indent=2), encoding="utf-8")
    print(f"\n  report written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
