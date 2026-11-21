"""Does macro-F1 still improve with more ENGINES? READ-ONLY on data.

The whole case for regenerating a larger fleet rests on one assumption nobody
has tested: that Tier-3's macro-F1 is limited by the number of independent
engines, and that adding more would raise it. That is a claim about the shape
of a learning curve, and a learning curve can be measured.

Method: hold VALIDATION and TEST fixed, train on a growing subset of the
training engines, and score on the same held-out engines each time. If macro-F1
is still climbing at the full 60 engines, more engines will help and by roughly
how much can be read off the slope. If it has flattened, more engines will not
help and the binding constraint is somewhere else -- in which case a two-hour
regeneration would buy nothing.

Engines are dropped whole, never sampled by row, so each point is a genuine
reduction in independent realisations rather than in rows.

    python scripts/learning_curve.py --sizes 20,35,50,60 --seeds 2
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd
import torch

from common import config
from layer3_ai import features as feat
from layer3_ai import tier3_deep as t3

D = config.data_dir() / "synthetic"


def load():
    man = json.loads((D / "manifest.json").read_text())
    assign = feat.stratified_engine_split(man)
    full = pd.concat(
        [pd.read_parquet(D / f"{s}.parquet") for s in ("train", "val", "test")],
        ignore_index=True,
    )
    full["split"] = full["engine_id"].map(assign)
    return man, full


def subset_engines(man, full, n: int, seed: int) -> list[int]:
    """Pick n training engines, keeping every fault class represented.

    Dropping engines at random would sometimes drop a class entirely, and a
    curve whose points differ in which classes exist is not a curve.
    """
    tr = sorted(full.loc[full["split"] == "train", "engine_id"].unique().tolist())
    modes: dict[str, list[int]] = {}
    for e in tr:
        for f in man["engines"][str(e)].get("faults") or []:
            if f.get("expressed", True):
                modes.setdefault(f["mode"], []).append(e)
    rng = np.random.default_rng(seed)
    picked: list[int] = []
    # One engine per class first, so no class disappears.
    for m in sorted(modes):
        pool = [e for e in modes[m] if e not in picked]
        if pool:
            picked.append(int(rng.choice(pool)))
    rest = [e for e in tr if e not in picked]
    rng.shuffle(rest)
    picked += rest[: max(0, n - len(picked))]
    return sorted(picked[:n])


def run_point(full, engines, val, test, seed, epochs, stride):
    fs = feat.extended()
    length = int(config.load_thresholds()["detectors"]["tier3"]["sequence_length"])
    tr = feat.baseline_residuals(
        full[full["engine_id"].isin(engines)].reset_index(drop=True)
    )
    seqs = {}
    for name, df in (("train", tr), ("val", val), ("test", test)):
        X, y, idx = feat.build_sequences(
            df, fs, length=length, stride=stride,
            label_columns=feat.FAULT_LABEL_COLUMNS,
        )
        seqs[name] = (X, y, feat.healthy_mask(df)[idx])

    torch.manual_seed(seed)
    np.random.seed(seed)
    det = t3.Tier3Detector(fs)
    rep = t3.train_multitask(
        det.net, seqs["train"][0], seqs["train"][1],
        seqs["val"][0], seqs["val"][1],
        epochs=epochs, seed=seed,
    )
    with torch.no_grad():
        out = det.net(torch.tensor(seqs["test"][0], dtype=torch.float32))
    prob = torch.sigmoid(out["fault"]).numpy()
    # Thresholds tuned on TRAIN predictions, never on test.
    with torch.no_grad():
        ptr = torch.sigmoid(
            det.net(torch.tensor(seqs["train"][0], dtype=torch.float32))["fault"]
        ).numpy()
    thr = t3.tune_thresholds(ptr, seqs["train"][1])
    m = t3.multilabel_metrics(prob, seqs["test"][1], thr)
    return m["macro_f1"], m["per_class"], rep


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sizes", default="20,35,50,60")
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--stride", type=int, default=10)
    args = ap.parse_args()

    man, full = load()
    val = feat.baseline_residuals(
        full[full["split"] == "val"].reset_index(drop=True))
    test = feat.baseline_residuals(
        full[full["split"] == "test"].reset_index(drop=True))
    sizes = [int(s) for s in args.sizes.split(",")]

    print("=" * 74)
    print("  TIER-3 LEARNING CURVE IN ENGINES  (val and test held fixed)")
    print("=" * 74)
    print(f"  epochs {args.epochs}, stride {args.stride}, "
          f"{args.seeds} seed(s) per point")
    print(f"  val engines {val.engine_id.nunique()}, "
          f"test engines {test.engine_id.nunique()}")
    print()
    print(f"  {'train engines':>14}{'macro-F1':>12}{'sd':>8}{'per class':>12}")

    curve = []
    for n in sizes:
        f1s, pcs = [], []
        for s in range(args.seeds):
            eng = subset_engines(man, full, n, seed=s)
            f1, pc, rep = run_point(full, eng, val, test, s,
                                    args.epochs, args.stride)
            f1s.append(f1)
            pcs.append(pc)
        mean_f1 = float(np.mean(f1s))
        curve.append((n, mean_f1, float(np.std(f1s)), pcs))
        per_class_eng = n * 1.22 / 8.0
        print(f"  {n:>14}{mean_f1:>12.3f}{np.std(f1s):>8.3f}"
              f"{per_class_eng:>12.1f}")

    # Macro-F1 flattening can hide heterogeneous per-class behaviour: some
    # classes may still be improving while others have hit an observability
    # wall that no amount of extra data can move.
    print()
    print("  PER-CLASS F1 (mean over seeds) AT EACH FLEET SIZE")
    classes = sorted(curve[0][3][0].keys())
    head = "".join(f"{n:>9}" for n, *_ in curve)
    print(f"    {'class':<24}{head}{'delta':>9}")
    for c in classes:
        vals = [float(np.mean([pc[c]["f1"] for pc in pcs])) for *_, pcs in curve]
        row = "".join(f"{v:>9.3f}" for v in vals)
        print(f"    {c:<24}{row}{vals[-1]-vals[-2]:>+9.3f}")

    print()
    print("  SLOPE (macro-F1 per +10 training engines):")
    for i in range(1, len(curve)):
        n0, f0, *_ = curve[i - 1]
        n1, f1_, *_ = curve[i]
        print(f"    {n0:>3} -> {n1:>3} engines : {10*(f1_-f0)/(n1-n0):+.4f}")
    if len(curve) >= 2:
        n0, f0, *_ = curve[-2]
        n1, f1_, *_ = curve[-1]
        slope = (f1_ - f0) / max(n1 - n0, 1)
        for target in (105,):
            print(f"\n  Linear extrapolation of the LAST segment to {target} "
                  f"train engines: {f1_ + slope * (target - n1):.3f}")
        print("  (an upper bound -- learning curves flatten, they do not "
              "continue straight)")


if __name__ == "__main__":
    main()
