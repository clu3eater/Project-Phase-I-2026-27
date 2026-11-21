"""Serve the trained RUL network in production -- PHASE A1.

WHY THIS EXISTS
---------------
The LSTM was trained, scored, saved to `data/models/rul_lstm.pt` -- and never
loaded by anything. `layer4_core/live.py` constructed only `PhysicsRul` and
served `source="physics"` unconditionally. Measured on the same held-out
engines (seed 0, `docs/RUL_IMPROVEMENT_LOG.md` Phase 0):

    physics extrapolation   RMSE 162.5   R2 -0.396   NASA 468,974
    LSTM (data-driven)      RMSE 113.9   R2 +0.327   NASA   2,252

An R2 below zero means the served estimator was worse than reporting the fleet
mean. So this module changes no model and no feature: it makes the better of
two estimators that already existed reachable from the aircraft.

THE TRAIN/SERVE SKEW THIS HAD TO SOLVE FIRST
--------------------------------------------
Training does not feed the network raw residuals. `features.baseline_residuals`
subtracts each engine's OWN median residual over its first 60 flight hours,
because build scatter gives every engine a constant offset -- measured at -25 to
+1 psi on oil pressure across the fleet with no fault present anywhere. What
carries health information is the CHANGE from where that engine started.

The twin already holds `Residual.mean_delta`, and it is the WRONG quantity to
serve with: it is a running mean over the whole life, so as an engine degrades
the mean follows it and `delta - mean_delta` tends back to zero -- cancelling
the exact signal the model is being asked to read. `ResidualBaseline` below
therefore freezes an EARLY-LIFE median and stops updating it, which is what
training did.

THE INTERVAL
------------
The checkpoint now carries the split-conformal multiplier `train_rul.py` fits
on validation, so the bound served here is the one that was MEASURED rather
than a Gaussian assumption: on this model the 95 % MC-dropout interval covered
the truth 18 % of the time before calibration. Serving reproduces the
calibration exactly -- the same Monte-Carlo dropout passes, the same multiplier
-- and a checkpoint without one serves no interval at all, which the twin then
refuses to show a bare number for.

No new features, no architecture change, no retraining, and `PhysicsRul` stays
exactly where it was -- this module can only add a source, never remove one.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from layer3_ai import features as feat

_log = logging.getLogger(__name__)

# Flight hours of early life over which the residual baseline is formed, then
# frozen. Matches `features.baseline_residuals(hours=60.0)` exactly; a serving
# baseline formed over a different window is a different feature.
BASELINE_HOURS = 60.0

# Minimum samples before a baseline is trusted at all, mirroring the batch
# version's fallback when an engine has fewer than 20 early rows.
BASELINE_MIN_SAMPLES = 20

# Residual channels that carry a build offset. Includes manifold pressure --
# it is not one of the 23 model inputs but it DOES feed the three structured
# residual features, so it must be baselined on the same terms as the rest.
BASELINED_RESIDUALS = (
    "res_cht", "res_coolant", "res_egt", "res_oil_pressure",
    "res_oil_temperature", "res_fuel_flow", "res_manifold_pressure",
)


@dataclass
class ServedRul:
    """One serving decision, with why it came out that way."""

    hours: float | None = None
    source: str = "none"          # "lstm" | "physics_fallback" | "none"
    reason: str = ""
    samples: int = 0
    baseline_frozen: bool = False
    # Left None deliberately -- see the module docstring.
    lower_hours: float | None = None
    upper_hours: float | None = None

    @property
    def reportable(self) -> bool:
        return self.hours is not None

    def as_dict(self) -> dict:
        return {
            "hours": None if self.hours is None else round(self.hours, 1),
            "source": self.source,
            "reason": self.reason,
            "samples": self.samples,
            "baseline_frozen": self.baseline_frozen,
        }


class ResidualBaseline:
    """Each engine's early-life residual median, frozen once it is established.

    Frozen rather than running, for the reason in the module docstring: a
    baseline that keeps tracking the engine subtracts the degradation it exists
    to reveal.

    Before the freeze the median of whatever has been seen is used, so the
    estimator degrades gracefully from installation instead of refusing to
    report for the first sixty flight hours. `frozen` says which regime a given
    reading came from, and the caller passes it on rather than hiding it.

    `settle_samples` freezes it earlier, once that many samples are in. What
    the reference removes is a BUILD offset, present from the first minute; left
    open for sixty hours the median followed anything that happened in them, so
    a fault arriving on a young engine was learned as its normal and vanished
    from every residual downstream. Training's batch version (the whole first
    sixty hours) is unchanged; on a healthy engine the two agree to within
    noise, and on one that degrades early the live residual is the larger --
    the conservative side.
    """

    def __init__(
        self,
        hours: float = BASELINE_HOURS,
        min_samples: int = BASELINE_MIN_SAMPLES,
        channels: tuple[str, ...] = BASELINED_RESIDUALS,
        settle_samples: int | None = None,
    ) -> None:
        self.hours = float(hours)
        self.min_samples = int(min_samples)
        self.settle_samples = None if settle_samples is None else int(settle_samples)
        self.channels = tuple(channels)
        self._early: dict[str, list[float]] = {c: [] for c in self.channels}
        self._median: dict[str, float] = {}
        self.frozen = False

    def observe(self, residuals: dict, flight_hours: float, *, learn: bool = True) -> dict:
        """Return the baselined residuals for this sample.

        `learn=False` applies the reference without adding the sample to it.
        The reference stands in for the whole-life median training used, which
        is dominated by cruise; formed from the climb it is a different number:
        measured, a healthy engine's EGT residual was +5.8 degC in the climb and
        +15.9 in cruise, the reference froze in the climb at 6.2, and every
        healthy cruise sample then read +9.8 degC -- which the Tier-3 network
        called an anomaly 72 % of the time (DEV-254).
        """
        if not self.frozen and learn:
            for c in self.channels:
                v = residuals.get(c)
                if v is not None and np.isfinite(v):
                    self._early[c].append(float(v))
            # MAX, not min, across channels. A channel that never reports --
            # manifold pressure on an airframe without that transducer -- has
            # zero samples for ever, and requiring every channel to reach the
            # threshold would mean the baseline never froze at all and the
            # engine ran on a provisional one for its whole life. A channel
            # with too little data simply gets no offset (`_base` returns 0.0),
            # which is the honest treatment of "no build offset observed".
            enough = max((len(v) for v in self._early.values()), default=0)
            settled = self.settle_samples is not None and enough >= self.settle_samples
            if settled or (flight_hours >= self.hours and enough >= self.min_samples):
                self._freeze()

        out = {}
        for c in self.channels:
            v = residuals.get(c)
            if v is None or not np.isfinite(v):
                out[c] = None
                continue
            out[c] = float(v) - self._base(c)
        return out

    @property
    def ready(self) -> bool:
        """Is there an engine reference at all yet?

        Until the first stretch of level flight there is none, and every
        residual is the raw one -- not what the models were trained on, where
        residuals are always taken from the engine's own reference (DEV-254).
        """
        return self.frozen or max((len(v) for v in self._early.values()), default=0) >= self.min_samples

    def offset(self, channel: str) -> float:
        """This engine's build offset on one residual channel (0 until known)."""
        return self._base(channel)

    def _base(self, channel: str) -> float:
        if channel in self._median:
            return self._median[channel]
        seen = self._early.get(channel) or []
        if len(seen) < 3:
            # Too little to form any baseline; subtracting a one-sample
            # "median" would just inject that sample's noise into every
            # later reading.
            return 0.0
        return float(np.median(seen))

    def _freeze(self) -> None:
        for c in self.channels:
            seen = self._early[c]
            if seen:
                self._median[c] = float(np.median(seen))
        self.frozen = True
        self._early = {c: [] for c in self.channels}
        _log.info("residual baseline frozen", extra={"samples_rule": self.settle_samples})


class LstmRulServer:
    """Rolling-window inference for the trained RUL network.

    Holds the last `sequence_length` normalised feature vectors and runs the
    checkpoint over them. Refuses to serve rather than guess: a missing
    checkpoint, a torch that will not import, or a feature order that disagrees
    with the one recorded in the checkpoint all leave `available` False and the
    caller on its existing physics path.
    """

    def __init__(
        self,
        checkpoint: Path | str | None = None,
        *,
        feature_set=None,
        sequence_length: int = 30,
        baseline_hours: float = BASELINE_HOURS,
        baseline_settle_samples: int | None = None,
    ) -> None:
        self.fs = feature_set if feature_set is not None else feat.extended()
        self.sequence_length = int(sequence_length)
        self.baseline = ResidualBaseline(
            hours=baseline_hours, settle_samples=baseline_settle_samples)
        self._window: deque[np.ndarray] = deque(maxlen=self.sequence_length)
        self._model = None
        self.rul_max: float | None = None
        self.unavailable_reason = ""
        self.conformal_q: float | None = None
        self.interval_coverage: float | None = None
        # Passes for the dropout interval. 30 is what the multiplier was
        # calibrated with in train_rul.py; a different count is a different
        # spread and the multiplier would no longer fit it.
        self.interval_passes = 30
        # How many successive predictions the served figure is taken over.
        # At the twin's 2 Hz tick this is about a minute of evidence, which is
        # short against a quantity measured in hundreds of hours and long
        # enough to average the pass-to-pass noise away.
        self.filter_samples = 120
        # A HISTORY OF ESTIMATES, BECAUSE ONE INFERENCE IS NOT AN ESTIMATE.
        #
        # Every tick ran a fresh forward pass and served whatever came out.
        # Measured on a healthy engine with the health index steady at 0.965:
        # 110 h, 133 h, 127 h, 105 h, 162 h, 250 h, 266 h, 314 h ... over
        # twenty seconds. Three-fold swings, twice a second, about a quantity
        # that moves over hundreds of hours.
        #
        # An operator does not want an independent guess every half second.
        # They want the best estimate given everything seen so far, and the
        # network provides many looks at the same slowly-moving quantity, so
        # the median of the recent ones is a strictly better estimator than
        # the latest one -- and it is robust to the occasional wild pass in a
        # way a mean is not.
        #
        # This is USING MORE DATA, not smoothing a number until it looks calm.
        # What it removes is the sampling noise between passes. What it does
        # NOT remove, and must not, is the model's own error: see
        # `_interval` for why the published interval stays wide.
        self._recent: deque[float] = deque(maxlen=self.filter_samples)
        self._load(checkpoint)

    # -- loading ------------------------------------------------------------

    def _default_checkpoint(self) -> Path:
        from common import config
        return Path(config.data_dir()) / "models" / "rul_lstm.pt"

    def _load(self, checkpoint: Path | str | None) -> None:
        path = Path(checkpoint) if checkpoint else self._default_checkpoint()
        if not path.exists():
            self.unavailable_reason = f"no checkpoint at {path}"
            _log.info("RUL network not served: %s", self.unavailable_reason)
            return
        try:
            import torch

            from layer3_ai.rul_lstm import RulLstm
        except Exception as exc:  # noqa: BLE001 - reported, not handled
            self.unavailable_reason = f"torch unavailable: {exc}"
            _log.info("RUL network not served: %s", self.unavailable_reason)
            return

        try:
            ck = torch.load(path, map_location="cpu", weights_only=False)
            trained_on = list(ck.get("features") or [])
            expected = list(self.fs.columns)
            # THE CHECK THAT MATTERS. A network fed the right number of
            # features in the wrong ORDER produces confident nonsense and
            # nothing downstream can tell. The checkpoint records the order it
            # was trained on, so this is verifiable rather than assumed.
            if trained_on and trained_on != expected:
                raise ValueError(
                    "feature contract mismatch between checkpoint and serving "
                    f"path: checkpoint has {len(trained_on)} columns, serving "
                    f"has {len(expected)}; first difference at "
                    f"{_first_difference(trained_on, expected)}"
                )
            model = RulLstm(len(expected))
            model.load_state_dict(ck["model"] if "model" in ck else ck)
            # eval() disables dropout. Training left it on deliberately for MC
            # sampling; a point estimate must not be one random draw.
            model.eval()
            self._model = model
            self.rul_max = (float(ck["rul_max"]) if ck.get("rul_max") is not None
                            else None)
            self.conformal_q = (float(ck["conformal_q"])
                                if ck.get("conformal_q") is not None else None)
            self.interval_coverage = (float(ck["interval_coverage"])
                                      if ck.get("interval_coverage") is not None else None)
            _log.info("RUL network loaded from %s (%d features, rul_max %s)",
                      path, len(expected), self.rul_max)
        except Exception as exc:  # noqa: BLE001 - reported, not handled
            self.unavailable_reason = f"checkpoint unusable: {exc}"
            self._model = None
            _log.warning("RUL network not served: %s", self.unavailable_reason)

    @property
    def available(self) -> bool:
        return self._model is not None

    @property
    def warm(self) -> bool:
        return len(self._window) >= self.sequence_length

    # -- inference ----------------------------------------------------------

    def observe(self, values: dict, flight_hours: float, *,
                learn_reference: bool = True) -> ServedRul:
        """Add one sample and return an estimate if there is one to give.

        `values` is the raw live reading keyed by DATASET column name --
        including un-baselined `res_*`. Baselining and the structured residual
        signature are applied here so the caller cannot forget them.
        """
        if not self.available:
            self.last_row = None
            return ServedRul(source="none", reason=self.unavailable_reason)

        row = dict(values)
        row.update(self.baseline.observe(values, flight_hours, learn=learn_reference))
        row.update(feat.structured_residuals_one(row))
        # Kept for any other consumer that needs the SAME inputs this network
        # is given -- currently the survival head, whose feature set shares
        # every one of these channels. Rebuilding them alongside would mean two
        # definitions of "baselined residual" that must be kept in step by
        # hand, and the baseline is stateful, so calling observe() twice per
        # tick would advance it twice and corrupt this path as well.
        self.last_row: dict | None = row
        self._window.append(feat.build_one(row, self.fs))

        if not self.warm:
            return ServedRul(
                source="none",
                reason=(f"warming up: {len(self._window)} of "
                        f"{self.sequence_length} samples"),
                samples=len(self._window),
                baseline_frozen=self.baseline.frozen,
            )

        import torch

        x = torch.tensor(
            np.stack(self._window)[None, :, :].astype(np.float32)
        )
        with torch.no_grad():
            hours = float(self._model(x).item())
        # A negative remaining life is not conservative, it is meaningless --
        # the same clamp `rul_lstm.predict` applies.
        hours = max(hours, 0.0)
        if self.rul_max is not None:
            hours = min(hours, self.rul_max)

        lower = upper = None
        if self.conformal_q is not None:
            # The SAME procedure the multiplier was calibrated against: dropout
            # left on, the spread across passes taken as the model's own
            # uncertainty, and the measured multiplier applied to it.
            from layer3_ai.rul_lstm import predict_with_interval

            _mean, lo, hi = predict_with_interval(
                self._model, x.numpy(), passes=self.interval_passes,
                q=self.conformal_q)
            lower, upper = float(lo[0]), float(hi[0])
            if self.rul_max is not None:
                lower, upper = min(lower, self.rul_max), min(upper, self.rul_max)

        # --- the served figure, over the recent history -------------------
        self._recent.append(hours)
        served_hours = float(np.median(self._recent))

        # THE INTERVAL IS RECENTRED, NOT NARROWED.
        #
        # `lower`/`upper` come from MC dropout across 30 passes times a
        # conformal multiplier calibrated on held-out engines. That half-width
        # encodes the model's MEASURED ERROR -- RUL RMSE 102 h against the
        # 25 h target of PRD Part 2 s12.3, reported in docs/PRD_DEVIATIONS.md
        # rather than tuned away.
        #
        # Averaging successive predictions removes the noise BETWEEN passes. It
        # does not remove the model's bias, so it cannot honestly shrink that
        # half-width -- an interval of +/- 10 h from an estimator with RMSE
        # 102 h would be a claim the evidence does not support, and a narrow
        # wrong interval is far more dangerous than a wide right one. It is
        # carried across to the filtered centre unchanged.
        #
        # What DOES improve is that the bounds stop moving: they used to swing
        # with every pass, so the operator saw the interval itself jitter.
        if lower is not None and upper is not None:
            half_lo = max(hours - lower, 0.0)
            half_hi = max(upper - hours, 0.0)
            lower = max(served_hours - half_lo, 0.0)
            upper = served_hours + half_hi
            if self.rul_max is not None:
                lower = min(lower, self.rul_max)
                upper = min(upper, self.rul_max)

        return ServedRul(
            hours=served_hours,
            lower_hours=lower,
            upper_hours=upper,
            source="lstm",
            reason=("estimated from the trained network"
                    if self.baseline.frozen
                    else "estimated; residual baseline still forming"),
            samples=len(self._window),
            baseline_frozen=self.baseline.frozen,
        )

    def reset(self) -> None:
        """Forget the window. A new engine is not a continuation of the last."""
        self._window.clear()


def _first_difference(a: list, b: list) -> str:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"index {i}: checkpoint {x!r} vs serving {y!r}"
    return f"index {min(len(a), len(b))}: one list is a prefix of the other"


__all__ = [
    "BASELINE_HOURS",
    "BASELINED_RESIDUALS",
    "LstmRulServer",
    "ResidualBaseline",
    "ServedRul",
]
