"""Per-fault time-to-action -- PS section C, "predictive diagnostics".

WHAT THIS ANSWERS THAT THE OTHER TWO RUL MODELS DO NOT
------------------------------------------------------
``rul_physics`` and ``rul_lstm`` both answer "how long has this ENGINE got",
which is one number for the whole machine. Section C asks for something
narrower and, for a maintainer, more useful:

    "The system should transition from conventional threshold-based monitoring
     to intelligent PREDICTIVE diagnostics. The detection/prediction of
     following parameters are required: [the eight fault modes]"

Detection says a fault is present. Prediction says WHEN IT WILL MATTER. A
maintenance planner holding "cooling degradation detected" cannot schedule
anything; holding "the cooling residual reaches its fault threshold in about
14 flight hours" can.

WHY IT EXTRAPOLATES A MEASURED INDICATOR, NOT AN ML SEVERITY SCORE
------------------------------------------------------------------
The obvious implementation is to take the Tier-3 severity head, fit a slope and
extrapolate. It is the wrong one, for a reason worth stating: that severity is
a learned scalar with no units and no calibrated relationship to any threshold
anybody acts on. Extrapolating it produces a number that cannot be checked
against anything.

Every one of the eight modes already has a PHYSICAL indicator in
``configs/thresholds.yaml`` with a DEGRADED level and a FAULT level -- the same
thresholds Tier-1 uses to raise the alert. Cooling degrades on the CHT residual
from 4 degC to 10 degC; lubrication on the oil-pressure residual against the
as-new twin from -5 to -10 psi; vibration on the bearing defect order against
its envelope floor from 2x to 5x. Those are measured quantities in real units
with a published action point.

So the prediction is: **fit the indicator's trend, extrapolate to the fault
threshold, and report the flight hours.** The answer is then falsifiable -- the
indicator either does reach the threshold when predicted or it does not -- and
it is stated in the same units the maintenance manual uses.

WHAT IT REFUSES TO DO
---------------------
A trend fitted to noise extrapolates to nonsense with great confidence, and a
maintenance planner cannot tell the difference by looking. So this module
declines more often than it answers:

  * fewer than ``min_samples`` observations -> no estimate;
  * a slope smaller than the indicator's own scatter -> "not trending";
  * a slope moving AWAY from the threshold -> "improving", never a negative
    time dressed up as a large positive one;
  * an indicator that is already past its fault threshold -> "already there",
    which is a detection result, not a prediction.

Each estimate carries an interval derived from the fit's own residual scatter,
because PRD Part 4 s7.4a applies to every prediction this system makes, not
only to the engine-level RUL.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from common import config

# How many of the most recent RAW samples the level is judged on.
_RECENT = 15
# The level is an upper quantile of those samples for a rising indicator (the
# mirror for a falling one), not their median (ML-11). A fault present in 40 %
# of samples -- an intermittent misfire -- never moved a median across its
# threshold, while a single noisy sample in fifteen still cannot move this.
_LEVEL_Q = 0.8


@dataclass(frozen=True)
class Indicator:
    """The measured quantity a fault mode progresses along.

    ``degraded`` and ``fault`` are read from the threshold file by name, so a
    retuned threshold moves this prediction with it and the two cannot drift.
    ``rising`` is False where the indicator FALLS towards its fault level --
    the oil-pressure residual degrades downward towards -10 psi, and treating
    that as a rise would report a failing engine as improving.
    """

    name: str            # human-readable, appears in the advisory
    unit: str
    degraded_key: str
    fault_key: str
    rising: bool = True
    # Scatter of the indicator on a healthy engine, in its own units. A slope
    # below this over the window is not a trend.
    noise: float = 0.0


# One indicator per PS fault mode. Chosen as the quantity whose threshold pair
# the Tier-1 rules already act on, so "time until this crosses" is time until
# the system itself would raise the fault.
INDICATORS: dict[str, Indicator] = {
    "cooling_degradation": Indicator(
        "cylinder-head residual", "C",
        "cht_residual_degraded_C", "cht_residual_fault_C", True, noise=1.2),
    # Measured oil pressure minus the as-new twin at the same operating point
    # (PS1-03, RT-06). The oil/rpm CORRELATION this replaced cannot separate a
    # healthy engine from a sick one on a 915 iS: above ~3500 rpm the pressure
    # relief valve holds oil pressure nearly flat against rpm, so a healthy
    # engine correlates weakly by design -- measured 0.67 in climb and 0.84
    # taxiing against a 0.85 fault line -- and a clean flight was filed as
    # "lubrication LIMIT REACHED". The residual is what the twin exists for.
    "lubrication_issue": Indicator(
        "oil pressure departure from the as-new twin", "psi",
        "oil_pressure_residual_degraded_psi", "oil_pressure_residual_fault_psi",
        False, noise=1.0),
    "injector_abnormal": Indicator(
        "EGT spread", "C",
        "egt_spread_degraded", "egt_spread_fault", True, noise=6.0),
    # COV of IMEP needs an in-cylinder pressure transducer, and a UAV
    # installation carries none, so on this aircraft that indicator could never
    # be fed and the mode sat at "no data" on every flight. The config's other
    # method for the same mode IS measurable: scatter of exhaust temperature
    # about the twin's prediction (egt_sigma_unstable_C / egt_sigma_severe_C).
    # The residual, not raw EGT, so a throttle change is not read as instability.
    "combustion_instability": Indicator(
        "EGT scatter about the twin", "C",
        "egt_sigma_unstable_C", "egt_sigma_severe_C", True, noise=2.0),
    # The value fed is the strongest bearing-defect order relative to the
    # envelope floor, so it is judged on the ENVELOPE limits, not the FFT-peak
    # ones that were keyed here for a different quantity (SAF-13).
    "abnormal_vibration": Indicator(
        "bearing defect order / envelope floor", "x",
        "envelope_degraded_x", "envelope_fault_x", True, noise=0.25),
    "overheating_trend": Indicator(
        # Thermal MARGIN: the distance left to the certified limit, so it falls
        # towards trouble. The config gives only the degraded level, and the
        # fault level is margin exhausted -- zero -- which is the certificate's
        # own limit rather than a number invented here.
        "thermal margin", "C",
        "thermal_margin_degraded_C", None, False, noise=1.5),
    # Share of cruise samples in which one cylinder's EGT sits well below the
    # other three (config Method B). A persistence measure of a cold cylinder,
    # not a per-power-stroke misfire count, and named for what it is (SAF-12).
    "misfire": Indicator(
        "cold-cylinder share of cruise samples", "%",
        None, "rate_alert_percent", True, noise=0.4),
    # An instrument's estimated OFFSET from the as-new twin, as a fraction of
    # the channel's full scale, and only where a second source blames the
    # instrument (layer4_core/sensor_bias.py). It was the residual VARIANCE
    # ratio, which measures scatter: a transducer reading steadily low is not
    # noisy, so drift was invisible here and was scored as engine wear instead
    # (audit 15 Sep, P0-4). The bands are the ones the configuration already
    # held for exactly this quantity.
    "sensor_drift": Indicator(
        "instrument offset against the twin", "of full scale",
        "bias_drift_fraction_fs", "bias_fault_fraction_fs", True, noise=0.002),
}


@dataclass
class FaultForecast:
    """When one fault mode reaches the point that requires action."""

    mode: str
    indicator: str
    value: float | None = None
    threshold: float | None = None
    unit: str = ""
    rate_per_hour: float | None = None
    hours_to_action: float | None = None
    lower_hours: float | None = None
    upper_hours: float | None = None
    status: str = "no data"      # trending | not trending | improving | reached
    reason: str = ""

    @property
    def reportable(self) -> bool:
        return self.hours_to_action is not None

    def as_dict(self) -> dict:
        def r(v, n=2):
            return None if v is None else round(float(v), n)

        return {
            "mode": self.mode,
            "indicator": self.indicator,
            "value": r(self.value),
            "threshold": r(self.threshold),
            "unit": self.unit,
            "rate_per_hour": r(self.rate_per_hour, 4),
            "hours_to_action": r(self.hours_to_action, 1),
            "lower_hours": r(self.lower_hours, 1),
            "upper_hours": r(self.upper_hours, 1),
            "status": self.status,
            "reason": self.reason,
            "reportable": self.reportable,
        }


class FaultRul:
    """Tracks each fault's indicator and forecasts when it needs action."""

    def __init__(self, *, window: int = 240, min_samples: int = 30,
                 bucket_h: float = 1.0 / 60.0, max_age_h: float = 0.5) -> None:
        self.cfg = config.load_thresholds()["faults"]
        self.window = window
        # Below this there is not enough of a lever arm to fit a slope that
        # means anything, however tempting the arithmetic.
        self.min_samples = min_samples
        # TREND history holds one point per `bucket_h` of flight time -- the
        # mean of the raw samples inside it (ML-03). Fed raw at the live 0.5 s
        # tick, a 240-sample window spanned two MINUTES: a genuine 0.5 degC/h
        # trend was invisible, and anything that did pass the slope test was a
        # transient projected hours ahead. 240 one-minute points span four
        # flight hours.
        self.bucket_h = float(bucket_h)
        # A reading older than this, in flight hours, is not a current reading
        # (SAF-09). The last cruise value used to be reported -- and acted on
        # by the advisory -- indefinitely after the indicator stopped arriving.
        self.max_age_h = float(max_age_h)
        self._hist: dict[str, deque] = {
            m: deque(maxlen=window) for m in INDICATORS
        }
        self._recent: dict[str, deque] = {
            m: deque(maxlen=_RECENT) for m in INDICATORS
        }
        self._bucket: dict[str, list[float]] = {}   # mode -> [t0, sum_t, sum_v, n]
        self._now = float("-inf")

    # ------------------------------------------------------------------
    def _threshold(self, mode: str, key: str | None, default: float) -> float:
        if key is None:
            return default
        return float(self.cfg[mode][key])

    def observe(self, flight_hours: float, values: dict[str, float | None]) -> None:
        """Record this frame's indicator value for each mode that has one.

        Called every tick whether or not any value is present, so the clock
        that ages a reading keeps running while its indicator is silent.
        """
        h = float(flight_hours)
        self._now = max(self._now, h)
        for mode, v in values.items():
            if mode not in self._hist or v is None:
                continue
            v = float(v)
            if not np.isfinite(v):
                continue
            self._recent[mode].append((h, v))
            b = self._bucket.get(mode)
            if b is not None and h - b[0] >= self.bucket_h:
                self._hist[mode].append((b[1] / b[3], b[2] / b[3]))
                b = None
            if b is None:
                self._bucket[mode] = [h, h, v, 1]
            else:
                b[1] += h
                b[2] += v
                b[3] += 1

    def restart(self, modes: list[str] | tuple[str, ...]) -> None:
        """Forget the trend of each named mode, after the work that fixes it.

        A trend fitted across a repair joins two different engines: the slope
        runs from the worn part to the new one and forecasts nothing about
        either. Modes the work did not touch keep their history.
        """
        for mode in modes:
            if mode in self._hist:
                self._hist[mode].clear()
                self._recent[mode].clear()
                self._bucket.pop(mode, None)

    def _points(self, mode: str) -> list[tuple[float, float]]:
        """Closed trend points plus the bucket still filling."""
        pts = list(self._hist[mode])
        b = self._bucket.get(mode)
        if b is not None:
            pts.append((b[1] / b[3], b[2] / b[3]))
        return pts[-self.window:]

    # ------------------------------------------------------------------
    def forecast(self, mode: str) -> FaultForecast:
        """Flight hours until this mode's indicator reaches its fault level."""
        ind = INDICATORS.get(mode)
        if ind is None:
            return FaultForecast(mode=mode, indicator="", status="no data",
                                 reason="no indicator defined for this mode")

        f = FaultForecast(mode=mode, indicator=ind.name, unit=ind.unit)
        # Margin exhausted is zero: the certificate's own limit, not a number
        # invented here.
        f.threshold = self._threshold(mode, ind.fault_key, 0.0)

        recent = self._recent[mode]
        if not recent:
            f.status = "no data"
            f.reason = (f"0 of {self.min_samples} samples needed "
                        f"before a trend can be fitted")
            return f
        age = self._now - recent[-1][0]
        if age > self.max_age_h:
            f.status = "no data"
            f.reason = (f"last {ind.name} reading is {age:.2f} flight h old "
                        f"(limit {self.max_age_h:.2f} h) -- not a current value")
            return f
        if len(recent) < min(_RECENT, self.min_samples):
            f.status = "no data"
            f.reason = (f"{len(recent)} of {self.min_samples} samples needed "
                        f"before a trend can be fitted")
            return f

        # The level judged against the threshold is a quantile of the most
        # recent RAW samples, not the newest one alone: one noisy sample used
        # to be enough to report "reached". An upper quantile rather than the
        # median, so a fault present in a sizeable share of samples still
        # registers (ML-11).
        rv = np.array([v for _, v in recent], dtype=float)
        f.value = float(np.quantile(rv, _LEVEL_Q if ind.rising else 1.0 - _LEVEL_Q))
        hist = self._points(mode)

        # Already past the action point. That is a DETECTION result, and
        # reporting "0 hours" as though it were a forecast would let a planner
        # read a present exceedance as a future one.
        past = (f.value >= f.threshold) if ind.rising else (f.value <= f.threshold)
        if past:
            f.status = "reached"
            f.reason = (f"{ind.name} is already at its action threshold "
                        f"({f.value:.2f} against {f.threshold:.2f} {ind.unit})".strip())
            return f

        if len(hist) < self.min_samples:
            f.status = "no data"
            f.reason = (f"{len(hist)} of {self.min_samples} samples needed "
                        f"before a trend can be fitted")
            return f
        t = np.array([h for h, _ in hist], dtype=float)
        y = np.array([v for _, v in hist], dtype=float)

        span = float(t[-1] - t[0])
        if span <= 1e-6:
            f.status = "no data"
            f.reason = "no elapsed flight time across the window"
            return f

        # Least squares on (flight hours, indicator). Linear deliberately: the
        # window is short, and a higher-order fit extrapolated past its data is
        # how a forecast acquires confident nonsense.
        slope, intercept = np.polyfit(t, y, 1)
        f.rate_per_hour = float(slope)
        resid = y - (slope * t + intercept)
        scatter = float(np.std(resid))

        # A slope is only a trend if it moves the indicator further than its
        # own scatter across the window observed.
        if abs(slope) * span < max(ind.noise, scatter):
            f.status = "not trending"
            f.reason = (f"{ind.name} is flat within its own scatter "
                        f"(+/-{max(ind.noise, scatter):.2f} {ind.unit})".strip())
            return f

        towards = (slope > 0) if ind.rising else (slope < 0)
        if not towards:
            f.status = "improving"
            f.reason = f"{ind.name} is moving away from its action threshold"
            return f

        hours = (f.threshold - f.value) / slope
        if hours <= 0:
            f.status = "reached"
            f.reason = f"{ind.name} is at its action threshold"
            return f
        f.hours_to_action = float(hours)
        f.status = "trending"

        # Interval from the fit's own scatter: how much sooner or later the
        # crossing falls if the indicator sits one standard deviation either
        # side of the line. s7.4a -- a prediction without an interval is not a
        # prediction, and that applies to every prediction this system makes.
        lo = (f.threshold - (f.value + scatter)) / slope
        hi = (f.threshold - (f.value - scatter)) / slope
        f.lower_hours = float(max(0.0, min(lo, hi)))
        f.upper_hours = float(max(lo, hi))
        f.reason = (
            f"{ind.name} at {f.value:.2f} {ind.unit}".strip()
            + f", moving {slope:+.3f} {ind.unit}/h".strip()
            + f" towards {f.threshold:.2f}"
        )
        return f

    def all_forecasts(self) -> list[dict]:
        """Every mode, worst first. Modes with no estimate sort last."""
        out = [self.forecast(m) for m in INDICATORS]
        out.sort(key=lambda f: (f.hours_to_action is None,
                                f.hours_to_action if f.hours_to_action else 0.0))
        return [f.as_dict() for f in out]

    def soonest(self) -> FaultForecast | None:
        """The fault that needs action first, if any is forecastable."""
        best = None
        for m in INDICATORS:
            f = self.forecast(m)
            if not f.reportable:
                continue
            if best is None or f.hours_to_action < best.hours_to_action:
                best = f
        return best


__all__ = ["INDICATORS", "FaultForecast", "FaultRul", "Indicator"]
