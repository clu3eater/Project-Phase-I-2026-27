"""Battery state of health -- PRD Part 2 section 9.2 Parameter 8, gap G4.

PRD Part 2 defines ``SOH_battery = f(cycle_count, internal_resistance,
voltage_under_load)``. Two of those three are directly observable on the bus;
the third is the one that has to be inferred, and inferring it is the whole
job.

WHY THIS CANNOT BE MEASURED CONTINUOUSLY
----------------------------------------
Internal resistance only reveals itself when the battery is actually supplying
current. Above the alternator's cut-in speed the generator carries the whole
load and the bus sits at the regulator setpoint, so the pack could be new or
nearly dead and the voltage would read the same. There is genuinely no
information in the signal at cruise.

So this estimator does not produce a number continuously. It waits for a
DISCHARGE EVENT -- engine start, or any low-rpm moment where demand exceeds
what the alternator can supply -- fits the battery's V-I line across that
event, and reports the resistance it implies. Between events it reports the
last estimate together with how long ago it was taken.

That is a real operational constraint rather than a limitation of this
implementation, and stating it is the point. A system that displayed a
continuously-updating battery SOH would be inventing precision it cannot have,
which is the same failure as an RUL with no interval or a health index that
tracks the throttle.

    V_terminal = V_open_circuit - I x R_internal

so a regression of terminal voltage against current has slope -R. It needs a
SPREAD of currents to be identifiable: several samples at one current fit a
line through a single point, which is why the estimator demands both a minimum
sample count and a minimum current range before it will answer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from common import config


@dataclass
class BatteryEstimate:
    """What is known about the pack, and how confidently."""

    soh: float | None = None
    internal_resistance_ohm: float | None = None
    open_circuit_v: float | None = None
    samples: int = 0
    current_span_a: float = 0.0
    hours_since_measured: float | None = None
    observable_now: bool = False
    reason: str = ""

    @property
    def reportable(self) -> bool:
        return self.soh is not None

    def as_dict(self) -> dict:
        return {
            "soh": round(self.soh, 4) if self.soh is not None else None,
            "internal_resistance_mohm": (
                round(self.internal_resistance_ohm * 1000.0, 3)
                if self.internal_resistance_ohm is not None else None
            ),
            "open_circuit_v": (
                round(self.open_circuit_v, 3) if self.open_circuit_v is not None else None
            ),
            "samples": self.samples,
            "current_span_a": round(self.current_span_a, 2),
            "hours_since_measured": (
                round(self.hours_since_measured, 3)
                if self.hours_since_measured is not None else None
            ),
            "observable_now": self.observable_now,
            "reason": self.reason,
        }


class BatteryHealth:
    """Estimates pack internal resistance from discharge events.

    Fed the bus voltage, the alternator current and the engine speed on every
    telemetry frame. It accumulates samples only while the battery is actually
    discharging, and refuses to answer until the samples span enough current to
    identify a slope.
    """

    # Below the alternator's cut-in the generator cannot carry the load and the
    # battery makes up the difference -- the only window in which the pack's
    # resistance is visible.
    CUT_IN_RPM = 1400.0
    MIN_SAMPLES = 12
    # A regression needs a spread of currents. Several samples at one current
    # fit a line through a single point and the slope is whatever noise says.
    MIN_CURRENT_SPAN_A = 1.5
    # WHAT COUNTS AS A DISCHARGE. The shunt reads with 0.20 A of noise
    # (engine_sim battery_current), and the threshold was 0.5 A -- 2.5 noise
    # widths -- so with the alternator carrying the load and the pack at 0 A,
    # about one sample in 160 still read as a discharge. Each such sample is
    # a point at the REGULATED bus voltage (28.9 V) beside a real discharge
    # line that starts at 26.9 V, and over a cruise enough of them filled the
    # 400-sample window to fit 164 mOhm to a 98 mOhm pack: 29 % state of
    # health, in red, on an engine with three flight hours. So a discharge now
    # needs a current five noise widths clear of zero AND a bus below nominal,
    # which the regulator never lets it be while it is carrying the load.
    DISCHARGE_MIN_A = 1.0

    def __init__(self, engine_key: str = "rotax_915is", *, window: int = 400) -> None:
        el = config.load_engine(engine_key)["electrical"]
        # The regression sees PACK resistance -- cells in series add. Comparing
        # a fitted pack resistance against a per-cell reference would report a
        # brand-new battery as eight times end-of-life.
        self.cells_series = float(el.get("battery_cells_series", 8))
        self.r_new = float(el["battery_internal_resistance_new_ohm"]) * self.cells_series
        self.v_nominal = float(el["nominal_bus_V"])
        deg = config.load_engine(engine_key)["degradation"].get("battery", {})
        self.eol_multiple = float(deg.get("end_of_life_resistance_multiple", 2.0))

        self._v: deque[float] = deque(maxlen=window)
        self._i: deque[float] = deque(maxlen=window)
        self._last: BatteryEstimate = BatteryEstimate(
            reason="no discharge event observed yet"
        )
        self._measured_at_hours: float | None = None
        self.events = 0

    # ------------------------------------------------------------------
    def update(
        self,
        *,
        bus_voltage: float | None,
        alternator_current: float | None,
        rpm: float | None,
        flight_hours: float = 0.0,
        battery_current: float | None = None,
    ) -> BatteryEstimate:
        """One telemetry frame in; the current best estimate out.

        ``battery_current`` comes from a shunt on the pack. It is required:
        alternator current during a discharge is pinned at whatever the
        generator can supply and says nothing about the battery, so without a
        shunt there is no signal to fit and the estimator will correctly never
        report a state of health.
        """
        discharging = (battery_current is not None
                       and battery_current > self.DISCHARGE_MIN_A
                       and bus_voltage is not None
                       and bus_voltage < self.v_nominal)
        observable = bool(discharging)

        if observable:
            self._v.append(float(bus_voltage))
            self._i.append(float(battery_current))
            est = self._fit(flight_hours)
        else:
            # Do NOT re-fit from a buffer of old samples. The window persists
            # between events, so re-fitting every frame produced a "fresh"
            # measurement from data collected hours earlier and reset the age
            # to zero -- defeating the staleness tracking that is the whole
            # point of reporting when the reading was taken.
            est = self._cached(flight_hours)
        est.observable_now = bool(observable)
        if not observable and est.soh is not None:
            est.reason = (
                "alternator is carrying the load; the pack reveals nothing "
                "about itself until it discharges again"
            )
        elif not observable and battery_current is None:
            est.reason = (
                "no battery shunt on this installation -- pack resistance "
                "cannot be inferred from alternator current alone"
            )
        self._last = est
        return est

    # ------------------------------------------------------------------
    def _cached(self, flight_hours: float) -> BatteryEstimate:
        """The last real measurement, with its age brought up to date."""
        out = BatteryEstimate(
            soh=self._last.soh,
            internal_resistance_ohm=self._last.internal_resistance_ohm,
            open_circuit_v=self._last.open_circuit_v,
            samples=self._last.samples,
            current_span_a=self._last.current_span_a,
            reason=self._last.reason,
        )
        if self._measured_at_hours is not None:
            out.hours_since_measured = max(0.0, flight_hours - self._measured_at_hours)
        return out

    def _fit(self, flight_hours: float) -> BatteryEstimate:
        n = len(self._v)
        if n < self.MIN_SAMPLES:
            out = BatteryEstimate(
                soh=self._last.soh,
                internal_resistance_ohm=self._last.internal_resistance_ohm,
                open_circuit_v=self._last.open_circuit_v,
                samples=n,
                reason=self._last.reason or "waiting for a discharge event",
            )
            if self._measured_at_hours is not None:
                out.hours_since_measured = max(0.0, flight_hours - self._measured_at_hours)
            return out

        v = np.asarray(self._v, dtype=float)
        i = np.asarray(self._i, dtype=float)
        span = float(i.max() - i.min())
        if span < self.MIN_CURRENT_SPAN_A:
            out = BatteryEstimate(
                soh=self._last.soh,
                internal_resistance_ohm=self._last.internal_resistance_ohm,
                open_circuit_v=self._last.open_circuit_v,
                samples=n,
                current_span_a=span,
                reason=(
                    f"discharge current spans only {span:.2f} A -- not enough "
                    f"variation to identify a slope"
                ),
            )
            if self._measured_at_hours is not None:
                out.hours_since_measured = max(0.0, flight_hours - self._measured_at_hours)
            return out

        # V = OCV - I*R, so the slope of V against I is -R.
        slope, intercept = np.polyfit(i, v, 1)
        r = float(-slope)
        if r <= 0:
            return BatteryEstimate(
                soh=self._last.soh, samples=n, current_span_a=span,
                reason="fitted resistance is non-physical; ignoring this window",
            )

        growth = (r - self.r_new) / max(self.r_new, 1e-12)
        soh = float(np.clip(1.0 - growth / max(self.eol_multiple - 1.0, 1e-9), 0.0, 1.0))

        self.events += 1
        self._measured_at_hours = flight_hours
        return BatteryEstimate(
            soh=soh,
            internal_resistance_ohm=r,
            open_circuit_v=float(intercept),
            samples=n,
            current_span_a=span,
            hours_since_measured=0.0,
            reason=f"fitted across {n} discharge samples spanning {span:.1f} A",
        )

    # ------------------------------------------------------------------
    def confidence(self) -> float:
        """How much to trust the last estimate.

        Falls with the age of the measurement. A battery reading taken two
        hundred flight hours ago is a historical fact, not a current one, and
        an operator should be told which they are looking at.
        """
        e = self._last
        if e.soh is None:
            return 0.0
        age = e.hours_since_measured
        if age is None:
            return 0.5
        # Half-confidence after 50 flight hours without a fresh measurement.
        return float(np.clip(1.0 / (1.0 + age / 50.0), 0.0, 1.0))


__all__ = ["BatteryEstimate", "BatteryHealth"]
