# -*- coding: utf-8 -*-
"""Test the survival method on REAL piston-engine flights.

Everything this project measures about its own engine is measured on data it
generated. That is permitted -- the problem statement asks for a simulator as a
deliverable and accepts "simulated or real engine datasets" -- but it means no
accuracy figure from our own fleet says anything about a real engine. The one
outside benchmark until now was C-MAPSS, which is a SIMULATED TURBOFAN: not
real, and not a piston engine. Its fault modes are HPC and fan degradation.
There are no cylinders in it.

NGAFID is the closest real thing that exists. Searching a survey of 110 public
degradation datasets across 43 applications turns up no MALE UAV powerplant and
no aero piston engine at all; "aircraft engine" appears five times and every
one is a turbofan. NGAFID is real recorded flight data from Cessna 172s --
four-cylinder piston engines -- with real unplanned maintenance events:

    28,935 flights, 31,177 flight hours, 2,111 maintenance events,
    36 maintenance issue types, 23 sensors at 1 Hz

Six of the eight parameters the problem statement names are present and real:
RPM, cylinder head temperature (four cylinders), exhaust gas temperature (four),
oil pressure, oil temperature, fuel flow, and battery/alternator volts and amps.
Vibration and injection timing are not recorded, so nothing here tests the
order-analysis path.

THE PROTOCOL IS THE PUBLISHED ONE, NOT ONE OF OUR OWN
-----------------------------------------------------
Taken from Yang and Desell, "Predictive Maintenance for General Aviation Using
Convolutional Transformers" (AAAI 2022), so the number produced here is
comparable to something rather than only to itself:

  task     binary. Class 1 = flights BEFORE an unplanned maintenance event,
           class 0 = flights AFTER it. Parts about to fail against parts just
           replaced.
  split    BY TAIL NUMBER. Validation aircraft never appear in training. The
           same discipline as our engine-grouped splits and for the same
           reason: split by flight and the model recognises the aeroplane.
  metric   ROC-AUC and PR-AUC, threshold-independent, because the classes are
           imbalanced and accuracy would move with the threshold.
  scope    PER MAINTENANCE ISSUE, not all issues pooled. This one is easy to
           get wrong -- pooling every issue type produces a number that
           compares to nothing published.

Published scores on this exact task, as the bar to be read against:

    Conv-MHSA        ROC-AUC 0.826 (intake gasket) / 0.775 (rocker cover)
    Conv-LSTM        ROC-AUC 0.70 - 0.74

The authors report that established time-series classifiers "face great
difficulty" here and tend to overfit, so a modest score is the expected
outcome and a very high one would be a reason to look for leakage rather than
to celebrate.

WHAT THIS DOES AND DOES NOT SHOW
--------------------------------
It tests the METHOD, not the shipped model. The weights trained on our
simulated Rotax fleet are not used and could not be: different engine,
different sensors, different failure modes. What transfers is the approach --
aggregate a flight to level and spread, fit a calibrated classifier, split by
AIRCRAFT so the model cannot recognise a tail number instead of learning
degradation.

So a good score here says "this method works on real piston engines with real
faults". It does not say "our model is accurate on a MALE UAV engine", and no
publicly available data can say that.

    python scripts/benchmark_ngafid.py --explore     # print the structure
    python scripts/benchmark_ngafid.py
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

from layer3_ai import rul_survival as rs  # noqa: E402

DATA = REPO / "data" / "benchmarks" / "ngafid" / "2days"

# Column order of the (timesteps x 23) array, taken from stats.csv rather than
# assumed. Each flight is stored as a bare numpy array with no column names, so
# getting this order wrong would silently train on the wrong channels.
COLUMNS = [
    "volt1", "volt2", "amp1", "amp2", "FQtyL", "FQtyR", "E1 FFlow",
    "E1 OilT", "E1 OilP", "E1 RPM", "E1 CHT1", "E1 CHT2", "E1 CHT3",
    "E1 CHT4", "E1 EGT1", "E1 EGT2", "E1 EGT3", "E1 EGT4", "OAT",
    "IAS", "VSpd", "NormAc", "AltMSL",
]

# The two the paper reports, so the numbers here read against something.
PUBLISHED = {
    "intake gasket leak/damage": 0.826,
    "rocker cover leak/loose/damage": 0.775,
}


def flight_features(arr: np.ndarray) -> np.ndarray:
    """One flight to level and spread per channel -- the twin's two views.

    ddof=1 to match pandas and `layer3_ai/sortie_features`, so a spread here
    means what a spread means everywhere else in this project.

    NaN is left as NaN rather than filled. Whole channels are absent on some
    airframes -- flight 1 records no volt2 and no CHT2-4 at all -- and filling
    those with a zero or a fleet mean would assert a reading the aircraft never
    took. Both boosters accept NaN natively and learn a split for it.
    """
    a = arr.astype(np.float64)
    with np.errstate(invalid="ignore"):
        level = np.nanmean(a, axis=0)
        spread = np.nanstd(a, axis=0, ddof=1) if len(a) > 1 else np.zeros(a.shape[1])
    return np.concatenate([level, spread])


def build(root: Path, issue: str, cap: int = 0):
    head = pd.read_csv(root / "flight_header.csv")
    head = head[head["label"] == issue].reset_index(drop=True)
    if cap:
        # Sample ACROSS folds, not the first N rows. The header is ordered, so
        # head(N) drew entirely from fold 0 and left that fold with no training
        # rows at all -- the booster failed with "Labels variable is empty",
        # which is a clearer error than the quiet one this would otherwise be.
        head = (head.groupby("fold", group_keys=False)
                    .apply(lambda g: g.head(max(2, cap // 5)))
                    .reset_index(drop=True))
    data = pd.read_pickle(root / "flight_data.pkl")

    x, y, fold = [], [], []
    for _, r in head.iterrows():
        arr = data.get(r["Master Index"])
        if arr is None or len(arr) < 2:
            continue
        x.append(flight_features(np.asarray(arr)))
        # Class 1 is BEFORE maintenance -- the part about to fail. Same
        # direction as the paper, so a score is comparable to its numbers.
        y.append(int(r["before_after"]))
        fold.append(int(r["fold"]))
    names = COLUMNS + [f"sd_{c}" for c in COLUMNS]
    return np.vstack(x), np.array(y), np.array(fold), names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=DATA)
    ap.add_argument("--issue", default=None,
                    help="maintenance issue to score; default runs both the "
                         "paper reports")
    ap.add_argument("--cap", type=int, default=0,
                    help="cap flights for a quick pass; 0 uses all")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path,
                    default=REPO / "data" / "benchmarks" / "ngafid.json")
    args = ap.parse_args()

    if not (args.root / "flight_header.csv").exists():
        raise SystemExit(f"{args.root} not found -- extract 2days.tar.gz from "
                         f"zenodo record 6624956 there first")

    from sklearn.metrics import average_precision_score, roc_auc_score

    began = time.time()
    issues = [args.issue] if args.issue else list(PUBLISHED)
    results = []

    for issue in issues:
        x, y, fold, names = build(args.root, issue, args.cap)
        print()
        print(issue)
        print(f"  {len(x):,} flights, {int(y.sum()):,} before maintenance, "
              f"{len(names)} features, {len(np.unique(fold))} folds")

        aucs, aps = [], []
        for f in sorted(np.unique(fold)):
            te = fold == f
            clf, backend = rs._make_classifier(args.seed, 300)
            clf.fit(x[~te], y[~te])
            p = clf.predict_proba(x[te])[:, 1]
            aucs.append(roc_auc_score(y[te], p))
            aps.append(average_precision_score(y[te], p))
            print(f"    fold {f}  ROC-AUC {aucs[-1]:.3f}   PR-AUC {aps[-1]:.3f}"
                  f"   ({int(te.sum())} held out)")

        auc, sd = float(np.mean(aucs)), float(np.std(aucs))
        pub = PUBLISHED.get(issue)
        print(f"  MEAN     ROC-AUC {auc:.3f} +/- {sd:.3f}   "
              f"PR-AUC {np.mean(aps):.3f}")
        if pub:
            print(f"  published Conv-MHSA {pub:.3f}   "
                  f"Conv-LSTM baselines 0.70-0.74")
        results.append({
            "issue": issue, "flights": int(len(x)),
            "positives": int(y.sum()), "backend": backend,
            "roc_auc_mean": round(auc, 4), "roc_auc_sd": round(sd, 4),
            "roc_auc_folds": [round(float(a), 4) for a in aucs],
            "pr_auc_mean": round(float(np.mean(aps)), 4),
            "published_conv_mhsa": pub,
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {"dataset": "NGAFID 2days", "protocol": "published 5-fold, "
         "class 1 = before maintenance, ROC-AUC/PR-AUC",
         "seed": args.seed, "results": results}, indent=2), encoding="utf-8")
    print()
    print(f"  wrote {args.out}")
    print(f"  {time.time() - began:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
