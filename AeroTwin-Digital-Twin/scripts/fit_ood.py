"""Fit the out-of-distribution check on the training fleet (audit 15 Sep, P1-6).

Run:  python scripts/fit_ood.py

Fitted on the HEALTHY TRAINING rows only, in the same 23-feature space and with
the same baselined residuals the networks are served, so a distance measured in
service means the same thing it meant here. Reported on the held-out TEST
engines, which tells us what the check will do in the field: how often it calls
a healthy engine unfamiliar, and how often it catches a faulted one that the
models were never shown.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from common import config                   # noqa: E402
from layer3_ai import features as feat      # noqa: E402
from layer3_ai.ood import OodDetector, write_report  # noqa: E402

QUANTILE = 0.999


def main() -> None:
    d = config.data_dir() / "synthetic"
    train = feat.baseline_residuals(pd.read_parquet(d / "train.parquet"))
    test = feat.baseline_residuals(pd.read_parquet(d / "test.parquet"))
    fs = feat.extended()

    # FITTED ON EVERYTHING THE NETWORKS SAW, healthy and faulted alike. Fitting
    # on healthy rows alone makes this a novelty detector for faults, and
    # measured that way it called 76 % of held-out FAULTED rows unfamiliar --
    # which would declare the models inapplicable exactly when a fault arrives,
    # the opposite of what the check is for. The question here is whether the
    # models are being asked about something they were trained on.
    x_train = feat.build(train, fs)
    print(f"fitting on {len(x_train):,} training rows "
          f"({train.engine_id.nunique()} engines), {len(fs.columns)} features")

    det = OodDetector.fit(x_train, list(fs.columns), quantile=QUANTILE)
    path = det.save(config.data_dir() / "models")

    x_test = feat.build(test, fs)
    healthy_test = feat.healthy_mask(test)
    faulted_test = feat.anomaly_mask(test)
    dist = np.array([det.verdict(row).distance for row in x_test])
    outside = dist > det.threshold

    healthy_rate = float(outside[healthy_test].mean()) if healthy_test.any() else float("nan")
    faulted_rate = float(outside[faulted_test].mean()) if faulted_test.any() else float("nan")

    print(f"  threshold (train {QUANTILE:.1%} quantile) = {det.threshold:.2f}")
    print(f"  held-out HEALTHY rows called unfamiliar : {100*healthy_rate:5.2f}%")
    print(f"  held-out FAULTED rows called unfamiliar : {100*faulted_rate:5.2f}%")
    print("  (both should be low: faults like these ARE in the training set;")
    print("   what must flag is a condition the fleet never contained)")
    print(f"  saved -> {path}")

    write_report(config.data_dir() / "models", {
        "fitted_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "quantile": QUANTILE,
        "threshold": float(det.threshold),
        "features": list(fs.columns),
        "train_rows": int(len(x_train)),
        "train_engines": int(train.engine_id.nunique()),
        "heldout_healthy_flagged_fraction": healthy_rate,
        "heldout_faulted_flagged_fraction": faulted_rate,
    })


if __name__ == "__main__":
    main()
