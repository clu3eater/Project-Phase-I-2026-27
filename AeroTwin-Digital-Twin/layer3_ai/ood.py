"""Is this sample like the data the models were trained on? (audit 15 Sep, P1-6)

A trained model answers every question it is asked, including questions about
engines, conditions and failures it has never seen. Nothing in this project
checked that, so a Tier-3 score carried the same authority at 25,000 ft on a
hot day with a fault the fleet never contained as it did in the middle of the
training set. The problem statement asks the AI layer for confidence
(section D); confidence that does not depend on whether the input is familiar
is not confidence.

WHAT IS MEASURED
----------------
Two things, both fitted on the HEALTHY TRAINING rows only and both stored with
the artifact so serving cannot drift from them:

  distance   Mahalanobis distance of the 23-feature vector from the training
             mean, which accounts for how the features vary TOGETHER -- an rpm
             and a manifold pressure that are each ordinary but never occur
             together are caught here and by no per-channel check;
  box        per-feature training minimum and maximum, kept because the
             distance alone says "unusual" without saying in what, and a
             maintainer needs the channel's name.

The threshold is an empirical quantile of the training distances, so it means
"this far out happened in 1 in N of the data the model learned from" rather
than a number chosen to look strict.

WHAT IT IS NOT
--------------
It does not say a reading is wrong. An engine legitimately flying a corner of
the envelope the fleet under-samples is out of distribution and perfectly
healthy. It says the MODELS are answering outside what they were shown, which
is a reason to weigh their answers differently and to say so on the screen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ARTIFACT = "ood.npz"
REPORT = "ood_report.json"


@dataclass
class OodVerdict:
    """One sample's standing against the training distribution."""

    distance: float
    threshold: float
    inside: bool
    outside_channels: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "distance": round(float(self.distance), 3),
            "threshold": round(float(self.threshold), 3),
            "inside": bool(self.inside),
            "outside_channels": list(self.outside_channels),
        }


class OodDetector:
    """Mahalanobis distance from the healthy training set, plus a feature box."""

    def __init__(self, columns: list[str], mean: np.ndarray, inv_cov: np.ndarray,
                 threshold: float, lo: np.ndarray, hi: np.ndarray,
                 quantile: float = 0.999) -> None:
        self.columns = list(columns)
        self.mean = np.asarray(mean, dtype=float)
        self.inv_cov = np.asarray(inv_cov, dtype=float)
        self.threshold = float(threshold)
        self.lo = np.asarray(lo, dtype=float)
        self.hi = np.asarray(hi, dtype=float)
        self.quantile = float(quantile)

    # ------------------------------------------------------------------
    @classmethod
    def fit(cls, x: np.ndarray, columns: list[str], *, quantile: float = 0.999,
            ridge: float = 1e-6) -> OodDetector:
        """Fit on healthy training rows. ``x`` is (samples, features)."""
        x = np.asarray(x, dtype=float)
        if len(x) < 100:
            raise ValueError(f"not enough rows to fit an OOD model: {len(x)}")
        mean = np.nanmean(x, axis=0)
        centred = np.nan_to_num(x - mean)
        cov = np.cov(centred, rowvar=False)
        # Ridge against a singular covariance: features built from one another
        # (a residual and its own rolling mean) are close to collinear, and an
        # exact inverse of that is numerical noise dressed as precision.
        cov = cov + np.eye(cov.shape[0]) * ridge * float(np.trace(cov)) / cov.shape[0]
        inv = np.linalg.pinv(cov)
        d = cls._distance(centred, inv)
        return cls(columns, mean, inv, float(np.quantile(d, quantile)),
                   np.nanmin(x, axis=0), np.nanmax(x, axis=0), quantile)

    @staticmethod
    def _distance(centred: np.ndarray, inv: np.ndarray) -> np.ndarray:
        return np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", centred, inv, centred), 0.0))

    # ------------------------------------------------------------------
    def verdict(self, vector: np.ndarray) -> OodVerdict:
        """One feature vector in, one verdict out."""
        v = np.asarray(vector, dtype=float).reshape(1, -1)
        d = float(self._distance(np.nan_to_num(v - self.mean), self.inv_cov)[0])
        outside = tuple(
            c for c, value, lo, hi in zip(self.columns, v[0], self.lo, self.hi, strict=True)
            if np.isfinite(value) and (value < lo or value > hi)
        )
        return OodVerdict(d, self.threshold, d <= self.threshold, outside)

    # ------------------------------------------------------------------
    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ARTIFACT
        np.savez(path, columns=np.array(self.columns), mean=self.mean,
                 inv_cov=self.inv_cov, threshold=self.threshold,
                 lo=self.lo, hi=self.hi, quantile=self.quantile)
        return path

    @classmethod
    def load(cls, directory: Path) -> OodDetector:
        z = np.load(directory / ARTIFACT, allow_pickle=False)
        return cls([str(c) for c in z["columns"]], z["mean"], z["inv_cov"],
                   float(z["threshold"]), z["lo"], z["hi"], float(z["quantile"]))

    def report(self) -> dict[str, Any]:
        return {
            "features": len(self.columns),
            "threshold": round(self.threshold, 3),
            "quantile": self.quantile,
        }


def write_report(directory: Path, payload: dict) -> Path:
    path = directory / REPORT
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
