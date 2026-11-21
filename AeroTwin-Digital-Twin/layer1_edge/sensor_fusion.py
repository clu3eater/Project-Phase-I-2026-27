"""Sensor fusion and signal conditioning -- PRD Part 1 section 8.

Three levels, as the PRD specifies:

  LEVEL 1  DATA-LEVEL      Hampel outlier rejection, gap interpolation,
                           resampling to a common 10 Hz grid
  LEVEL 2  FEATURE-LEVEL   cross-correlations that are themselves health
                           indicators (oil pressure vs rpm, CHT vs EGT)
  LEVEL 3  DECISION-LEVEL  multi-source voting across the two FADEC lanes

WHY A HAMPEL FILTER AND NOT A MOVING AVERAGE
--------------------------------------------
A moving average smears a spike across the whole window: one bad sample
corrupts every output that sees it, and the corruption looks like a real
transient. The Hampel filter instead compares each sample against the MEDIAN of
its neighbourhood, scaled by the median absolute deviation -- a robust
estimator that a single outlier cannot move. Spikes are replaced; genuine
steps, which move the median with them, survive. That distinction matters here
because a real engine step (a throttle slam) and a sensor spike look identical
to a mean-based filter.

BIAS ESTIMATION
---------------
PRD Part 1 section 8.4 asks for a Kalman filter that carries sensor bias as a
state, so drift can be estimated and compensated rather than mistaken for a
process change. The implementation here is a scalar Kalman filter per channel
tracking a slowly-varying bias against a reference (the physics prediction, or
the redundant FADEC lane). It is deliberately conservative: it will not chase a
real excursion, because a filter that absorbs a genuine fault into "bias" is
worse than no filter at all.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from common import config


@dataclass
class HampelFilter:
    """Robust outlier rejection on a rolling window (PRD Part 1 section 8.1).

    A sample is an outlier when it lies more than ``n_sigma`` scaled median
    absolute deviations from the window median. Because both the centre and the
    scale are medians, one bad point cannot influence the decision about
    itself -- which is exactly the property a mean and standard deviation lack.
    """

    window: int = 7
    n_sigma: float = 3.0
    _buf: deque[float] = field(default_factory=lambda: deque(maxlen=7))
    rejected: int = 0
    accepted: int = 0

    def __post_init__(self) -> None:
        self._buf = deque(maxlen=self.window)

    def filter(self, value: float) -> tuple[float, bool]:
        """Return (value_to_use, was_rejected)."""
        self._buf.append(value)
        if len(self._buf) < max(3, self.window // 2):
            self.accepted += 1
            return value, False

        ordered = sorted(self._buf)
        n = len(ordered)
        median = (
            ordered[n // 2] if n % 2 else 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])
        )
        deviations = sorted(abs(x - median) for x in self._buf)
        mad = (
            deviations[n // 2]
            if n % 2
            else 0.5 * (deviations[n // 2 - 1] + deviations[n // 2])
        )
        # 1.4826 makes the MAD a consistent estimator of the standard deviation
        # for Gaussian data.
        sigma = 1.4826 * mad
        # A perfectly constant window has zero MAD, and dividing by it would
        # make the filter blind exactly when it should be most sensitive: after
        # a steady period, ANY departure is significant. Floor sigma at a tiny
        # fraction of the signal magnitude so that case is still detected.
        sigma = max(sigma, 1e-6 * max(abs(median), 1.0))

        if abs(value - median) > self.n_sigma * sigma:
            self.rejected += 1
            # Report the median -- the best estimate the outlier did not
            # influence -- but leave the RAW sample in the window. Overwriting
            # it would make the filter permanently blind to a sustained step:
            # every subsequent sample would be compared against a median the
            # filter had itself frozen, and a genuine step change would be
            # rejected for ever.
            return median, True

        self.accepted += 1
        return value, False


@dataclass
class BiasEstimator:
    """Scalar Kalman filter tracking a slowly-varying sensor bias.

    State is the bias itself; the process model is a random walk whose noise
    sets how fast the estimate is allowed to move. Keeping that small is the
    whole point: a fast filter would absorb a genuine engine excursion into the
    bias term and hide the fault it exists to reveal.
    """

    process_noise: float = 1e-6
    measurement_noise: float = 1e-2
    bias: float = 0.0
    covariance: float = 1.0
    samples: int = 0

    def update(self, measured: float, reference: float) -> float:
        """Fold one (measurement, reference) pair in. Returns the bias estimate."""
        innovation = (measured - reference) - self.bias
        self.covariance += self.process_noise
        gain = self.covariance / (self.covariance + self.measurement_noise)
        self.bias += gain * innovation
        self.covariance *= 1.0 - gain
        self.samples += 1
        return self.bias

    def compensate(self, measured: float) -> float:
        return measured - self.bias

    def drifting(self, full_scale: float, fraction: float = 0.02) -> bool:
        """PRD Part 1 section 8.4: flag when the estimated bias exceeds 2% FS."""
        return abs(self.bias) > fraction * abs(full_scale)


@dataclass
class RollingCorrelation:
    """Pearson correlation over a time window (PRD Part 1 section 8.1 Level 2).

    The oil-pressure-versus-rpm correlation is the headline use: on a healthy
    engine oil pressure is strongly rpm-driven, so a weakening correlation
    means pump wear or bearing leakage even while both signals remain
    individually in limits (PRD Part 2 section 10.4 Method A).
    """

    window_s: float = 60.0
    _x: deque[tuple[float, float]] = field(default_factory=deque)
    _y: deque[tuple[float, float]] = field(default_factory=deque)

    def update(self, t: float, x: float, y: float) -> float | None:
        self._x.append((t, x))
        self._y.append((t, y))
        while self._x and t - self._x[0][0] > self.window_s:
            self._x.popleft()
            self._y.popleft()
        n = len(self._x)
        if n < 10:
            return None
        xs = [v for _, v in self._x]
        ys = [v for _, v in self._y]
        mx, my = sum(xs) / n, sum(ys) / n
        sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
        sxx = sum((a - mx) ** 2 for a in xs)
        syy = sum((b - my) ** 2 for b in ys)
        if sxx <= 1e-12 or syy <= 1e-12:
            return None
        return sxy / math.sqrt(sxx * syy)


@dataclass
class LaneVote:
    """Decision-level fusion across the two FADEC lanes (section 8.1 Level 3).

    The engine measures its redundant sensors on both lanes independently
    (OM section 7.5.1), so a disagreement is a sensor-validity signal that
    costs nothing to obtain. With only two sources a majority vote is
    impossible, so the rule is: agree within tolerance and the mean is used;
    disagree and BOTH are marked suspect, because there is no way to tell which
    one is lying.
    """

    tolerance_fraction: float = 0.05
    disagreements: int = 0

    def fuse(
        self, lane_a: float | None, lane_b: float | None, *, floor: float = 0.0
    ) -> tuple[float | None, bool]:
        """``floor`` is the smallest difference, in the channel's own units, that
        counts as disagreement whatever the fraction says."""
        if lane_a is None and lane_b is None:
            return None, False
        if lane_a is None:
            return lane_b, False
        if lane_b is None:
            return lane_a, False
        scale = max(abs(lane_a), abs(lane_b), 1.0)
        if abs(lane_a - lane_b) > max(floor, self.tolerance_fraction * scale):
            self.disagreements += 1
            return 0.5 * (lane_a + lane_b), True
        return 0.5 * (lane_a + lane_b), False


class SensorFusion:
    """Applies the three fusion levels to a stream of decoded telemetry."""

    def __init__(self, thresholds: dict | None = None) -> None:
        t = thresholds or config.load_thresholds()
        f = t["fusion"]
        self.hampel_window = int(f["hampel"]["window"])
        self.hampel_sigma = float(f["hampel"]["n_sigma"])
        kal = f["kalman"]
        self.process_noise = float(kal["bias_process_noise"])
        self.measurement_noise = float(kal["measurement_noise"])
        self.correlation_window = float(f["correlation_window_s"])

        self._filters: dict[str, HampelFilter] = {}
        self._bias: dict[str, BiasEstimator] = {}
        self.oil_rpm_correlation = RollingCorrelation(window_s=self.correlation_window)
        self.cht_egt_correlation = RollingCorrelation(window_s=self.correlation_window)
        self.lane_vote = LaneVote(
            tolerance_fraction=float(t["pipeline"]["lane_agreement_fraction"]))
        self.spikes_rejected = 0

    def _filter_for(self, name: str) -> HampelFilter:
        if name not in self._filters:
            self._filters[name] = HampelFilter(
                window=self.hampel_window, n_sigma=self.hampel_sigma
            )
        return self._filters[name]

    def bias_for(self, name: str) -> BiasEstimator:
        if name not in self._bias:
            self._bias[name] = BiasEstimator(
                process_noise=self.process_noise,
                measurement_noise=self.measurement_noise,
            )
        return self._bias[name]

    def condition(self, name: str, value: float | None) -> float | None:
        """Level 1: reject spikes on one channel."""
        if value is None:
            return None
        cleaned, rejected = self._filter_for(name).filter(value)
        if rejected:
            self.spikes_rejected += 1
        return cleaned

    def update_features(self, t: float, telemetry) -> dict[str, float]:
        """Level 2: cross-parameter features that are health indicators."""
        out: dict[str, float] = {}
        rpm = telemetry.get("rpm")
        oil = telemetry.get("oil_pressure")
        if rpm is not None and oil is not None:
            r = self.oil_rpm_correlation.update(t, rpm, oil)
            if r is not None:
                out["oil_rpm_correlation"] = r
        cht = telemetry.get("cht_max")
        egt = telemetry.get("egt_max")
        if cht is not None and egt is not None:
            r = self.cht_egt_correlation.update(t, cht, egt)
            if r is not None:
                out["cht_egt_correlation"] = r
        return out
