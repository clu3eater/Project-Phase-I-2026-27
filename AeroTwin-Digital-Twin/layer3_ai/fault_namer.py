"""Which fault is it? A per-fault classifier that sees the engine's history.

WHY THIS EXISTS
---------------
The Tier-3 network answers "is something wrong?" well (anomaly F1 0.95 on
unseen engines) and "which fault?" poorly: macro-F1 0.61. Its errors are not
mostly false labels on healthy engines. They are confusions BETWEEN faults
that look alike in a 30-second window: overheating trend drew 682 of its 768
wrong labels from other faults, injector 358 of 408, cooling 337 of 382.
Cooling loss, overheating and a drifting head probe all push the head
temperature up; what separates them is history and which channels move
together:
  * overheating builds over many flights, and head, coolant and oil rise
    together (airflow);
  * cooling loss widens the head-to-coolant gap while the coolant holds;
  * a drifting probe moves one channel while its physical neighbours do not.

This module computes those signatures -- strictly from the past and present,
never a later sample -- and names faults with one gradient-boosted classifier
per fault. For each fault, whether it uses the history features is decided on
VALIDATION engines (vibration, for one, does better without them).

Measured on engines never seen in training (DEV-253): macro-F1 0.61 -> 0.78.

ONE DEFINITION, TWO USES
------------------------
:class:`SortieHistory` is the live feature builder, and training replays each
engine's samples through the SAME class. A batch re-implementation for
training would be a second definition kept in step by hand -- the train/serve
skew this repository has already paid for once (rul_serving module docstring).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

# Channels whose level, scatter and trend carry fault identity.
CHANNELS: tuple[str, ...] = (
    "res_cht", "res_coolant", "res_egt", "res_oil_pressure", "res_oil_temperature",
    "res_fuel_flow", "cht_minus_coolant", "egt_spread", "cht_spread", "vibration_kurtosis",
)
EW_ALPHA = 0.3          # smoothing across previous sorties
# "Now" is the last minute, not the sortie so far. A training sortie is ~50
# one-second steady samples, so there "so far" and "now" are the same thing;
# a live sortie is an hour, and its so-far mean diluted a +9 psi lubrication
# fault injected mid-flight to +0.6 psi. A fixed window means the same in both.
RECENT = 60
# Below this many completed sorties there is no history to speak of, and a
# fault model that relies on it is served its sample-only twin instead.
MIN_HISTORY_SORTIES = 4
SLOPE_SORTIES = 8       # trend taken over this many previous sorties
SLOPE_MIN = 4
BACK_FROM, BACK_TO = 11, 20   # "then" window for the change feature
BACK_MIN = 3


def history_columns() -> list[str]:
    cols = []
    for c in CHANNELS:
        cols += [f"sm_{c}", f"sd_{c}", f"ew_{c}", f"d10_{c}", f"slope_{c}"]
    return cols + ["coh_thermal", "gap_vs_head", "iso_cht"]


@dataclass
class _Running:
    """One channel over the sortie: the whole-sortie mean (which becomes the
    sortie's entry in the history) and the last RECENT samples (for "now")."""

    n: int = 0
    mean: float = 0.0
    recent: deque = field(default_factory=lambda: deque(maxlen=RECENT))

    def add(self, x: float) -> None:
        self.n += 1
        self.mean += (x - self.mean) / self.n
        self.recent.append(x)

    @property
    def recent_mean(self) -> float:
        return float(np.mean(self.recent)) if self.recent else math.nan

    @property
    def recent_std(self) -> float:
        return float(np.std(self.recent, ddof=1)) if len(self.recent) >= 3 else math.nan


@dataclass
class SortieHistory:
    """One engine's per-sortie record, and the running state of this sortie.

    `observe` a sample, read `features()`, and `close_sortie()` when the
    sortie ends. Only completed sorties enter the history, so no feature ever
    contains a later part of the sortie it is computed in.
    """

    means: list[dict[str, float]] = field(default_factory=list)
    hours: list[float] = field(default_factory=list)
    _run: dict[str, _Running] = field(default_factory=dict)
    _start_h: float | None = None
    # Features of COMPLETED sorties change only when a sortie closes, so they
    # are computed once then, not on every sample.
    _past: dict[str, float] | None = None

    def observe(self, row: dict, flight_hours: float) -> None:
        if self._start_h is None:
            self._start_h = float(flight_hours)
        for c in CHANNELS:
            v = row.get(c)
            if v is not None and np.isfinite(v):
                self._run.setdefault(c, _Running()).add(float(v))

    def close_sortie(self) -> None:
        if not self._run:
            self._start_h = None
            return
        self.means.append({c: r.mean for c, r in self._run.items() if r.n})
        self.hours.append(self._start_h if self._start_h is not None else math.nan)
        self._run = {}
        self._start_h = None
        self._past = None

    # -- the features ------------------------------------------------------
    def _series(self, c: str) -> np.ndarray:
        return np.array([m.get(c, math.nan) for m in self.means], dtype=float)

    def features(self) -> dict[str, float]:
        if self._past is None:
            self._past = self._past_features()
        out = dict(self._past)
        for c in CHANNELS:
            r = self._run.get(c)
            out[f"sm_{c}"] = r.recent_mean if r and r.n else math.nan
            out[f"sd_{c}"] = r.recent_std if r else math.nan
        out["iso_cht"] = (abs(out["sm_res_cht"])
                          - 0.5 * (abs(out["sm_res_coolant"]) + abs(out["sm_res_egt"]) / 10.0)
                          if all(np.isfinite(out[k]) for k in ("sm_res_cht", "sm_res_coolant", "sm_res_egt"))
                          else math.nan)
        return out

    def _past_features(self) -> dict[str, float]:
        out: dict[str, float] = {}
        hrs = np.asarray(self.hours, dtype=float)
        for c in CHANNELS:
            v = self._series(c)
            # exponentially weighted mean of previous sorties
            e = math.nan
            for x in v:
                if np.isfinite(x):
                    e = x if not np.isfinite(e) else EW_ALPHA * x + (1 - EW_ALPHA) * e
            out[f"ew_{c}"] = e
            # last sortie against sorties 11-20 back
            if len(v) >= 1 and np.isfinite(v[-1]):
                back = v[-BACK_TO:-BACK_FROM + 1] if len(v) >= BACK_FROM else np.array([])
                back = back[np.isfinite(back)]
                out[f"d10_{c}"] = float(v[-1] - back.mean()) if len(back) >= BACK_MIN else math.nan
            else:
                out[f"d10_{c}"] = math.nan
            # trend per flight hour over the previous sorties
            vv, hh = v[-SLOPE_SORTIES:], hrs[-SLOPE_SORTIES:]
            ok = np.isfinite(vv) & np.isfinite(hh)
            if ok.sum() >= SLOPE_MIN and np.ptp(hh[ok]) > 0:
                out[f"slope_{c}"] = float(np.polyfit(hh[ok], vv[ok], 1)[0])
            else:
                out[f"slope_{c}"] = math.nan
        sgn = [np.sign(out[f"slope_{c}"]) for c in ("res_cht", "res_coolant", "res_oil_temperature")]
        out["coh_thermal"] = float(np.nansum(sgn)) if any(np.isfinite(sgn)) else math.nan
        out["gap_vs_head"] = (out["slope_cht_minus_coolant"] / (abs(out["slope_res_cht"]) + 1e-3)
                              if np.isfinite(out["slope_cht_minus_coolant"])
                              and np.isfinite(out["slope_res_cht"]) else math.nan)
        return out


class FaultNamer:
    """The trained per-fault classifiers, served one sample at a time."""

    def __init__(self, blob: dict) -> None:
        self.classes: list[str] = list(blob["classes"])
        self.models = blob["models"]
        self.choice: dict[str, str] = dict(blob["choice"])
        self.thresholds: dict[str, float] = {k: float(v) for k, v in blob["thresholds"].items()}
        self.base_columns: list[str] = list(blob["base_columns"])
        self.history_columns: list[str] = list(blob["history_columns"])
        self.report: dict = dict(blob.get("report", {}))
        # The sample-only twins of the history models, for young engines.
        self.sample_models = dict(blob.get("sample_models", {}))
        self.sample_thresholds = {k: float(v) for k, v in blob.get("sample_thresholds", {}).items()}
        self.min_history = int(blob.get("min_history_sorties", MIN_HISTORY_SORTIES))
        # Faults a young engine may be named with (measured on young engines).
        self.young_allowed = {k: bool(v) for k, v in blob.get("young_allowed", {}).items()}
        self.withheld: list[str] = []

    def _x(self, row: dict, hist: dict, with_history: bool) -> np.ndarray:
        vals = [row.get(c) for c in self.base_columns]
        if with_history:
            vals += [hist.get(c) for c in self.history_columns]
        return np.array([[math.nan if v is None else float(v) for v in vals]], dtype=float)

    def probabilities(self, row: dict, hist: dict, sorties_done: int | None = None
                      ) -> dict[str, float]:
        """Per-fault probability. A fault that uses history is served its
        sample-only model (with that model's own threshold, see `threshold`)
        until the engine has MIN_HISTORY_SORTIES completed sorties."""
        out = {}
        young = sorties_done is not None and sorties_done < self.min_history
        self.withheld = []
        for cls in self.classes:
            wants = self.choice.get(cls) == "history"
            if young and wants and cls not in self.sample_models:
                # No sample-only twin to serve: not judged, not "zero".
                self.withheld.append(cls)
                continue
            # No sample-only twin on file (an older model): serve the history
            # model with what history there is, never a mismatched input.
            use_hist = wants and (not young or cls not in self.sample_models)
            model = self.models[cls] if use_hist or not wants else self.sample_models[cls]
            x = self._x(row, hist, use_hist)
            out[cls] = float(model.predict_proba(x)[0, 1])
        self._young = young
        return out

    def threshold(self, cls: str) -> float:
        """The decision line for the model actually served last."""
        if (getattr(self, "_young", False) and self.choice.get(cls) == "history"
                and cls in self.sample_models):
            return self.sample_thresholds.get(cls, self.thresholds[cls])
        return self.thresholds[cls]

    def served_by_twin(self) -> list[str]:
        """History faults answered by their sample-only twin on this call --
        a young engine. The caller names these only when a detector agrees
        something is wrong (see layer4_core.live, DEV-254)."""
        if not getattr(self, "_young", False):
            return []
        return [c for c in self.classes
                if self.choice.get(c) == "history" and c in self.sample_models]

    def precision(self, cls: str) -> float:
        """Measured test precision of the model served last."""
        per = self.report.get("per_class", {}).get(cls, {})
        if (getattr(self, "_young", False) and self.choice.get(cls) == "history"
                and cls in self.sample_models):
            return float(per.get("young_test_precision", per.get("test_precision", 0.0)))
        return float(per.get("test_precision", 0.0))


__all__ = ["CHANNELS", "MIN_HISTORY_SORTIES", "RECENT", "FaultNamer", "SortieHistory",
           "history_columns"]
