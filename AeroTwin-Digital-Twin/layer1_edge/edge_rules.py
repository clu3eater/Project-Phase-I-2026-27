"""Tier-1 rule engine -- the fast, deterministic alerting path.

This is the layer that turns a measurement into a warning. Everything before it
produces numbers; nothing before it tells anybody anything.

WHY IT LIVES AT THE EDGE
------------------------
PRD Part 1 section 6.4 budgets <50 ms for the critical alert path, and states
that path runs ONBOARD using only the rule engine, bypassing the physics and
AI stages entirely. PRD Part 3 section 21.4 requires the edge node to keep
detecting and annunciating with the ground link down. So this module has no
dependency on the physics model, on any network, or on any trained artifact --
it needs only decoded telemetry and `configs/thresholds.yaml`.

RULE TYPES (PRD Part 2 section 11.1 Tier 1)
-------------------------------------------
    Threshold      parameter outside an absolute limit
    RateOfChange   parameter moving faster than is safe
    Persistence    parameter out of band continuously for a duration
    Correlation    a cross-parameter relationship violated
    FlightPhase    a value abnormal for the current phase of flight
    Deviation      measured minus commanded, for the FADEC-scheduled channels

ALERTING SEMANTICS (PRD Part 4 section 4, from MIL-STD-411F)
------------------------------------------------------------
Getting these right is what separates an alerting system from a colour-changing
dashboard:

  * five PRD levels mapped onto the standard's three urgency CATEGORIES
  * hysteresis, so an alert does not chatter on the limit
  * a 3-second MINIMUM DISPLAY TIME, so a transient that self-clears is still
    seen (411F 5.2.5.5)
  * warnings ordered above cautions above advisories (411F 5.2.5.2)
  * overflow, with an explicit count of what is not shown (411F 5.2.5.3)
  * master WARNING and master CAUTION annunciators that energise with any
    individual alert, reset independently, and re-arm (411F 5.1.3 / 5.1.4)
  * inhibit logic for ground and warm-up phases (411F 5.2.6.2)
  * legends <=24 characters, upper case, naming the subsystem and the condition
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

from common import config
from layer1_edge.can_ingest import Telemetry, ValueState


class AlertLevel(IntEnum):
    """The five levels of PRD Part 2 section 9.5."""

    GREEN = 1
    BLUE = 2
    YELLOW = 3
    ORANGE = 4
    RED = 5


class AlertCategory(StrEnum):
    """MIL-STD-411F urgency categories (PRD Part 4 section 4.1)."""

    NORMAL = "NORMAL"
    ADVISORY = "ADVISORY"
    CAUTION = "CAUTION"
    WARNING = "WARNING"


_LEVEL_CATEGORY = {
    AlertLevel.GREEN: AlertCategory.NORMAL,
    AlertLevel.BLUE: AlertCategory.ADVISORY,
    AlertLevel.YELLOW: AlertCategory.CAUTION,
    AlertLevel.ORANGE: AlertCategory.CAUTION,
    AlertLevel.RED: AlertCategory.WARNING,
}

# Flight phase codes, matching the CAN database's FLIGHT_PHASE value table.
PHASE_GROUND, PHASE_STARTUP, PHASE_TAXI, PHASE_TAKEOFF = 0, 1, 2, 3
PHASE_CLIMB, PHASE_CRUISE, PHASE_DESCENT, PHASE_LANDING = 4, 5, 6, 7
_ON_GROUND = {PHASE_GROUND, PHASE_STARTUP, PHASE_TAXI}


@dataclass
class Alert:
    """One active alert.

    ``legend`` obeys PRD Part 4 section 4.4: at most 24 characters, upper case,
    naming the subsystem and the condition, with the location where relevant.
    """

    rule_id: str
    legend: str
    level: AlertLevel
    parameter: str
    value: float | None
    limit: float | None
    advisory: str = ""
    fault_mode: str = ""
    first_seen: float = 0.0
    last_seen: float = 0.0
    min_display_until: float = 0.0
    acknowledged: bool = False
    inhibited: bool = False
    clear_pending: bool = False

    @property
    def category(self) -> AlertCategory:
        return _LEVEL_CATEGORY[self.level]

    @property
    def is_warning(self) -> bool:
        return self.category is AlertCategory.WARNING

    @property
    def is_caution(self) -> bool:
        return self.category is AlertCategory.CAUTION

    def age_s(self, now: float) -> float:
        return now - self.first_seen


@dataclass
class AlertState:
    """Everything an HMI needs to draw the alerting surface."""

    active: list[Alert] = field(default_factory=list)
    overflow: list[Alert] = field(default_factory=list)
    master_warning: bool = False
    master_caution: bool = False
    unacknowledged_warning: bool = False
    inhibits_active: bool = False
    evaluation_ms: float = 0.0

    @property
    def overflow_count(self) -> int:
        return len(self.overflow)

    def by_category(self, category: AlertCategory) -> list[Alert]:
        return [a for a in self.active if a.category is category]

    @property
    def highest_level(self) -> AlertLevel:
        return max((a.level for a in self.active), default=AlertLevel.GREEN)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@dataclass
class Rule:
    """Base rule. Subclasses implement ``evaluate``.

    ``priority`` follows PRD Part 2 section 11.1: higher is evaluated first and
    suppresses lower-priority rules on the same parameter, so a RED overspeed
    does not sit alongside a YELLOW overspeed for the same reading.
    """

    rule_id: str
    parameter: str
    level: AlertLevel
    legend: str
    advisory: str = ""
    fault_mode: str = ""
    priority: int = 5
    inhibit_on_ground: bool = False
    # An alert that fires when nothing is wrong trains the operator to ignore
    # the system. These three conditions cover the cases that actually occur.
    inhibit_below_rpm: float = 0.0
    inhibit_during_start: bool = False
    inhibit_during_transient: bool = False
    # Flight phases in which this rule is meaningless. Temperatures and
    # pressures legitimately TREND during take-off and climb -- that is the
    # engine doing its job, not a fault -- so a trend rule that fires there is
    # a nuisance by construction (MIL-STD-411F 4.1.1a).
    inhibit_in_phases: tuple[int, ...] = ()
    # Meaningful only while the shaft turns (RUNNING_ONLY below).
    needs_running: bool = False

    def evaluate(self, tel: Telemetry, derived: dict[str, float]) -> tuple[bool, float | None, float | None]:
        raise NotImplementedError


@dataclass
class ThresholdRule(Rule):
    """Parameter outside an absolute limit, with hysteresis on the way out."""

    limit: float = 0.0
    direction: str = "above"  # "above" | "below"
    hysteresis: float = 0.0
    _latched: bool = False

    def evaluate(self, tel, derived):
        value = tel.get(self.parameter)
        if value is None:
            value = derived.get(self.parameter)
        if value is None:
            # Losing the reading is not evidence the condition cleared. A
            # latched WARNING used to drop the moment its sensor went quiet --
            # oil pressure LOW became a caution-level SENSOR FAULT, and mission
            # planning softened from NO-GO to GO WITH LIMITS (SAF-08, CAN-12).
            # The latch holds until a VALID reading is back inside the
            # hysteresis band.
            return self._latched, None, self.limit

        if self.direction == "above":
            trip = value > self.limit
            clear = value < (self.limit - self.hysteresis)
        else:
            trip = value < self.limit
            clear = value > (self.limit + self.hysteresis)

        if trip:
            self._latched = True
        elif clear:
            self._latched = False
        return self._latched, value, self.limit


@dataclass
class RateRule(Rule):
    """Parameter TRENDING faster than the configured safe rate.

    The slope is fitted by least squares over the whole window, not taken as
    the difference between two endpoint samples.

    This matters more than it looks. The configured limits are trends over
    MINUTES -- PRD Part 2 section 10.4 calls -2.0 psi/min a lubrication fault,
    which is 0.033 psi/s. Differencing two consecutive samples 0.5 s apart on a
    signal carrying 0.35 psi of sensor noise yields apparent rates around
    1-3 psi/s: eighty times the threshold, from noise alone. An endpoint
    difference would therefore alarm continuously on a perfectly healthy
    engine.

    Least squares over a filled window suppresses that: the standard error of
    the fitted slope falls as sigma / (T * sqrt(n/12)), so a 60 s window of
    0.5 s samples reduces the noise-driven slope to well under the limit. The
    window must also be substantially FILLED before the rule is allowed to
    fire, otherwise the first two samples after an inhibit lifts reproduce the
    endpoint problem exactly.
    """

    max_rate: float = 0.0
    window_s: float = 5.0
    min_fill: float = 0.6  # fraction of the window that must be populated
    # The level below which a rise is not the condition the rule is about.
    # None: armed at any level.
    armed_at_or_above: float | None = None
    _history: list[tuple[float, float]] = field(default_factory=list)

    def evaluate(self, tel, derived):
        value = tel.get(self.parameter)
        if value is None:
            value = derived.get(self.parameter)
        if value is None:
            return False, None, self.max_rate
        now = tel.t_s
        self._history.append((now, value))
        self._history = [(t, v) for t, v in self._history if now - t <= self.window_s]

        if len(self._history) < 4:
            return False, None, self.max_rate
        span = self._history[-1][0] - self._history[0][0]
        if span < self.min_fill * self.window_s:
            return False, None, self.max_rate

        n = len(self._history)
        mean_t = sum(t for t, _ in self._history) / n
        mean_v = sum(v for _, v in self._history) / n
        sxx = sum((t - mean_t) ** 2 for t, _ in self._history)
        if sxx <= 1e-9:
            return False, None, self.max_rate
        sxy = sum((t - mean_t) * (v - mean_v) for t, v in self._history)
        slope = sxy / sxx
        if self.armed_at_or_above is not None and value < self.armed_at_or_above:
            return False, slope, self.max_rate
        return slope > self.max_rate, slope, self.max_rate


@dataclass
class PersistenceRule(Rule):
    """Out of band CONTINUOUSLY for a duration -- filters transients."""

    limit: float = 0.0
    direction: str = "above"
    duration_s: float = 60.0
    _since: float | None = None

    def evaluate(self, tel, derived):
        value = tel.get(self.parameter)
        if value is None:
            value = derived.get(self.parameter)
        if value is None:
            # A single dropout used to restart the persistence clock, and an
            # alert that had already fired cleared with it. Hold both: only a
            # valid in-band reading ends the excursion (CAN-12).
            if self._since is None:
                return False, None, self.limit
            return (tel.t_s - self._since) >= self.duration_s, None, self.limit
        out = value > self.limit if self.direction == "above" else value < self.limit
        if not out:
            self._since = None
            return False, value, self.limit
        if self._since is None:
            self._since = tel.t_s
        return (tel.t_s - self._since) >= self.duration_s, value, self.limit


@dataclass
class CorrelationRule(Rule):
    """A cross-parameter relationship that must hold.

    ``predicate`` receives the telemetry and derived values and returns True
    when the relationship is VIOLATED. This is how PRD Part 2 section 10.4
    Method A ("low oil pressure at high rpm") is expressed: neither parameter
    alone is out of limits, but together they are wrong.
    """

    predicate: Callable[[Telemetry, dict[str, float]], tuple[bool, float | None]] | None = None

    def evaluate(self, tel, derived):
        if self.predicate is None:
            return False, None, None
        tripped, value = self.predicate(tel, derived)
        return tripped, value, None


@dataclass
class DeviationRule(Rule):
    """Measured minus commanded, for the FADEC-scheduled channels.

    This is the rule that finally consumes the injection-timing deviation: the
    signal has existed since the ECU model was written, but until now nothing
    compared it against its limit (PRD Part 2 section 10.2 Method C).
    """

    limit: float = 0.0
    hysteresis: float = 0.0
    _latched: bool = False

    def evaluate(self, tel, derived):
        value = derived.get(self.parameter)
        if value is None:
            self._latched = False
            return False, None, self.limit
        if abs(value) > self.limit:
            self._latched = True
        elif abs(value) < (self.limit - self.hysteresis):
            self._latched = False
        return self._latched, value, self.limit


# ---------------------------------------------------------------------------
# Rule construction from configuration
# ---------------------------------------------------------------------------


def _p(params: dict, name: str, key: str, default: Any = None) -> Any:
    spec = params.get(name, {})
    return spec.get(key, default)


def build_rules(thresholds: dict | None = None, engine: dict | None = None) -> list[Rule]:
    """Assemble the rule set from configuration.

    Every limit comes from ``thresholds.yaml`` -- decision D6 forbids a magic
    number here. Adding a limit to the configuration adds a rule; there is no
    second place to edit.
    """
    t = thresholds or config.load_thresholds()
    engine = engine or config.load_engine()
    p = t["parameters"]
    faults = t["faults"]
    rules: list[Rule] = []

    def threshold(rid, param, level, legend, limit, direction, *, advisory="",
                  fault="", priority=5, hyst_key=None, inhibit=False,
                  min_rpm=0.0, no_start=False, no_transient=False):
        if limit is None:
            return
        rules.append(
            ThresholdRule(
                rule_id=rid, parameter=param, level=level, legend=legend,
                advisory=advisory, fault_mode=fault, priority=priority,
                inhibit_on_ground=inhibit, inhibit_below_rpm=min_rpm,
                inhibit_during_start=no_start, inhibit_during_transient=no_transient,
                limit=float(limit), direction=direction,
                hysteresis=float(_p(p, hyst_key or param, "hysteresis", 0.0)),
            )
        )

    # ---- thermal: coolant is this engine's CERTIFIED limit -----------------
    threshold("CLNT_CRIT", "coolant_temperature", AlertLevel.RED, "COOLANT TEMP HIGH",
              _p(p, "coolant_temperature", "critical_max"), "above", priority=9,
              advisory="Coolant over certified limit. Reduce power immediately.",
              fault="overheating_trend")
    threshold("CLNT_HIGH", "coolant_temperature", AlertLevel.ORANGE, "COOLANT TEMP HIGH",
              _p(p, "coolant_temperature", "alert_max"), "above", priority=6,
              advisory="Coolant approaching limit. Reduce power.",
              fault="overheating_trend")
    threshold("CHT_CRIT", "cht_max", AlertLevel.RED, "CHT HIGH",
              _p(p, "cht", "critical_max"), "above", priority=9, hyst_key="cht",
              advisory="Cylinder head over limit. Reduce power immediately.",
              fault="overheating_trend")
    threshold("CHT_HIGH", "cht_max", AlertLevel.ORANGE, "CHT HIGH",
              _p(p, "cht", "alert_max"), "above", priority=6, hyst_key="cht",
              advisory="Cylinder head temperature high. Monitor closely.",
              fault="overheating_trend")

    # ---- exhaust ------------------------------------------------------------
    threshold("EGT_CRIT", "egt_max", AlertLevel.RED, "EGT HIGH",
              _p(p, "egt", "critical_max"), "above", priority=9, hyst_key="egt",
              advisory="EGT over certified limit. Reduce power immediately.",
              fault="combustion_instability")
    threshold("EGT_HIGH", "egt_max", AlertLevel.ORANGE, "EGT HIGH",
              _p(p, "egt", "alert_max"), "above", priority=6, hyst_key="egt",
              advisory="EGT approaching limit.", fault="combustion_instability")
    threshold("EGT_SPLIT_CRIT", "egt_spread", AlertLevel.ORANGE, "EGT SPLIT HIGH",
              _p(p, "egt", "spread_critical"), "above", priority=6, hyst_key="egt",
              advisory="Cylinder-to-cylinder EGT split over the certified limit.",
              fault="injector_abnormal")
    threshold("EGT_SPLIT_HIGH", "egt_spread", AlertLevel.YELLOW, "EGT SPLIT HIGH",
              _p(p, "egt", "spread_alert"), "above", priority=4, hyst_key="egt",
              advisory="EGT split widening. Suspect injector imbalance.",
              fault="injector_abnormal")
    threshold("CHT_SPREAD", "cht_spread", AlertLevel.YELLOW, "CHT SPREAD HIGH",
              _p(p, "cht", "spread_alert"), "above", priority=4, hyst_key="cht",
              advisory="Cylinder head temperature spread widening.",
              fault="cooling_degradation")

    # ---- lubrication --------------------------------------------------------
    threshold("OILP_CRIT", "oil_pressure", AlertLevel.RED, "OIL PRESS LOW",
              _p(p, "oil_pressure", "critical_min"), "below", priority=10,
              no_start=True, min_rpm=float(_p(p, "rpm", "idle_min", 1800)),
              advisory="Oil pressure critically low. Bearing damage imminent.",
              fault="lubrication_issue")
    threshold("OILP_HIGH", "oil_pressure", AlertLevel.ORANGE, "OIL PRESS HIGH",
              _p(p, "oil_pressure", "critical_max"), "above", priority=6,
              advisory="Oil pressure above limit. Suspect relief valve.",
              fault="lubrication_issue")
    threshold("OILT_CRIT", "oil_temperature", AlertLevel.RED, "OIL TEMP HIGH",
              _p(p, "oil_temperature", "critical_max"), "above", priority=9,
              advisory="Oil over certified limit. Reduce power immediately.",
              fault="lubrication_issue")
    threshold("OILT_HIGH", "oil_temperature", AlertLevel.YELLOW, "OIL TEMP HIGH",
              _p(p, "oil_temperature", "alert_max"), "above", priority=4,
              advisory="Oil temperature high.", fault="lubrication_issue")
    threshold("OILT_LOW", "oil_temperature", AlertLevel.YELLOW, "OIL TEMP LOW",
              _p(p, "oil_temperature", "alert_min"), "below", priority=4,
              inhibit=True,
              advisory="Oil below take-off minimum. Continue warm-up.",
              fault="lubrication_issue")

    # ---- speed --------------------------------------------------------------
    threshold("RPM_CRIT", "rpm", AlertLevel.RED, "OVERSPEED",
              _p(p, "rpm", "critical_max"), "above", priority=10,
              advisory="Engine overspeed. Reduce power immediately.")
    # Above max continuous is CERTIFIED for a limited time: 5800 rpm is
    # permitted for 5 minutes (EASA TCDS E.121). An instantaneous threshold
    # cannot express a time-limited rating and fires on every take-off, so this
    # is a persistence rule using the certified allowance.
    rules.append(
        PersistenceRule(
            rule_id="RPM_HIGH", parameter="rpm", level=AlertLevel.YELLOW,
            legend="MAX CONT EXCEEDED", priority=4,
            advisory="Above max continuous beyond the certified time limit. Reduce power.",
            limit=float(_p(p, "rpm", "alert_max")), direction="above",
            duration_s=float(_p(p, "rpm", "takeoff_time_limit_s", 300.0)),
        )
    )

    # ---- boost / charge ------------------------------------------------------
    threshold("MAP_CRIT", "manifold_pressure", AlertLevel.RED, "OVERBOOST",
              _p(p, "manifold_pressure", "critical_max"), "above", priority=9,
              advisory="Manifold pressure over never-exceed. Reduce power.")
    threshold("MAT_HIGH", "manifold_air_temperature", AlertLevel.YELLOW, "MAT HIGH",
              _p(p, "manifold_air_temperature", "alert_max"), "above", priority=4,
              advisory="Manifold air over the rated-power limit; power is reduced.")

    # ---- fuel ----------------------------------------------------------------
    threshold("FUELP_LOW", "fuel_pressure", AlertLevel.ORANGE, "FUEL PRESS LOW",
              _p(p, "fuel_pressure", "alert_min"), "below", priority=7,
              no_start=True,
              advisory="Fuel rail pressure low. Check pumps.",
              fault="injector_abnormal")
    # Fuel flow is legitimately tiny at ground idle, so this only means
    # something once the engine is actually producing power.
    threshold("FUELF_LOW", "fuel_flow", AlertLevel.ORANGE, "FUEL FLOW LOW",
              _p(p, "fuel_flow", "critical_min"), "below", priority=7,
              min_rpm=2500.0, no_start=True,
              advisory="Fuel flow critically low. Suspect starvation.",
              fault="injector_abnormal")

    # ---- electrical ----------------------------------------------------------
    threshold("BUS_LOW", "battery_voltage", AlertLevel.ORANGE, "BUS VOLTS LOW",
              _p(p, "battery_voltage", "critical_min"), "below", priority=7,
              no_start=True, min_rpm=float(_p(p, "rpm", "idle_min", 1800)),
              advisory="Bus voltage low. Suspect generator failure.")
    threshold("BUS_HIGH", "battery_voltage", AlertLevel.YELLOW, "BUS VOLTS HIGH",
              _p(p, "battery_voltage", "alert_max"), "above", priority=4,
              advisory="Bus voltage high. Suspect regulator.")

    # ---- vibration -----------------------------------------------------------
    threshold("VIB_CRIT", "vibration_rms_total", AlertLevel.RED, "VIBRATION HIGH",
              _p(p, "vibration_rms", "critical_max"), "above", priority=9,
              hyst_key="vibration_rms",
              advisory="Vibration at structural-damage level. Land as soon as possible.",
              fault="abnormal_vibration")
    threshold("VIB_HIGH", "vibration_rms_total", AlertLevel.ORANGE, "VIBRATION HIGH",
              _p(p, "vibration_rms", "alert_max"), "above", priority=6,
              hyst_key="vibration_rms",
              advisory="Vibration above normal. Inspect before next flight.",
              fault="abnormal_vibration")
    threshold("VIB_KURT", "vibration_kurtosis", AlertLevel.YELLOW, "VIB IMPULSIVE",
              faults["abnormal_vibration"]["kurtosis_fault"], "above", priority=4,
              advisory="Impulsive vibration content. Suspect bearing damage.",
              fault="abnormal_vibration")

    # ---- FADEC-scheduled timing: the rules that consume the deviations -------
    inj = faults["injector_abnormal"]
    rules.append(
        DeviationRule(
            rule_id="INJ_DEV_FAULT", parameter="injection_timing_deviation_max",
            level=AlertLevel.ORANGE, legend="INJ TIMING DEV",
            advisory="Injection timing deviating from command. Inspect injectors.",
            fault_mode="injector_abnormal", priority=6,
            limit=float(inj["timing_deviation_fault_deg"]), hysteresis=0.5,
        )
    )
    rules.append(
        DeviationRule(
            rule_id="INJ_DEV_DEGRADED", parameter="injection_timing_deviation_max",
            level=AlertLevel.YELLOW, legend="INJ TIMING DEV",
            advisory="Injection timing drifting. Monitor injector condition.",
            fault_mode="injector_abnormal", priority=4,
            limit=float(inj["timing_deviation_degraded_deg"]), hysteresis=0.3,
        )
    )
    rules.append(
        DeviationRule(
            rule_id="IGN_DEV", parameter="ignition_timing_deviation_max",
            level=AlertLevel.YELLOW, legend="IGN TIMING DEV",
            advisory="Ignition timing deviating from command.",
            fault_mode="combustion_instability", priority=4,
            limit=float(_p(p, "ignition_timing", "deviation_critical", 5.0)),
            hysteresis=0.5,
        )
    )
    threshold("KNOCK_RETARD", "knock_retard", AlertLevel.YELLOW, "IGN RETARD HIGH",
              _p(p, "ignition_timing", "knock_retard_alert_deg"), "above", priority=4,
              hyst_key="ignition_timing",
              advisory="Knock-driven ignition retard rising. Check cooling and fuel grade.",
              fault="combustion_instability")
    threshold("INJ_DUTY", "injector_duty", AlertLevel.ORANGE, "INJECTOR DUTY HIGH",
              100.0 * float(_p(p, "injection_period", "duty_alert", 0.9)), "above",
              priority=6, hyst_key="injection_period",
              advisory="Injectors approaching saturation; fuel metering authority is limited.",
              fault="injector_abnormal")

    # ---- rate of change -------------------------------------------------------
    rules.append(
        RateRule(
            rule_id="CHT_RATE", parameter="cht_max", level=AlertLevel.ORANGE,
            legend="CHT RISING FAST", priority=7, fault_mode="overheating_trend",
            advisory="Rapid cylinder head temperature rise. Reduce power.",
            inhibit_during_transient=True, inhibit_during_start=True,
            inhibit_in_phases=(PHASE_GROUND, PHASE_STARTUP, PHASE_TAXI, PHASE_TAKEOFF, PHASE_CLIMB),
            max_rate=float(faults["overheating_trend"]["cht_slope_trending_C_per_min"]) / 60.0,
            window_s=30.0,
            # AN OVERHEATING TREND IS A RISE WHILE HOT. After the power
            # reduction at the top of descent the heads fall to ~40 degC, well
            # under their 80-120 degC normal band, and then warm back toward
            # it at up to 6 degC/min as the air thickens -- which raised "CHT
            # RISING FAST. Reduce power." on and off through every descent and
            # landing, and escalated the fused verdict to WARNING, on an engine
            # merely warming up. The rule arms at the bottom of the normal band.
            armed_at_or_above=float(_p(p, "cht", "normal_min", 80.0)),
        )
    )
    rules.append(
        RateRule(
            rule_id="OILP_RATE", parameter="oil_pressure", level=AlertLevel.ORANGE,
            legend="OIL PRESS FALLING", priority=8, fault_mode="lubrication_issue",
            advisory="Oil pressure falling rapidly. Prepare to shut down.",
            inhibit_during_transient=True, inhibit_during_start=True,
            inhibit_in_phases=(PHASE_GROUND, PHASE_STARTUP, PHASE_TAXI, PHASE_TAKEOFF, PHASE_CLIMB),
            max_rate=abs(float(faults["lubrication_issue"]["pressure_trend_fault_psi_per_min"])) / 60.0,
            window_s=60.0,
        )
    )

    # ---- persistence -----------------------------------------------------------
    rules.append(
        PersistenceRule(
            rule_id="CHT_SUSTAINED", parameter="cht_max", level=AlertLevel.YELLOW,
            legend="CHT HIGH SUSTAINED", priority=3, fault_mode="overheating_trend",
            advisory="Cylinder head above normal for an extended period.",
            limit=float(_p(p, "cht", "normal_max")), direction="above",
            duration_s=float(t["detectors"]["tier1"]["persistence_default_s"]),
        )
    )

    # ---- correlation ------------------------------------------------------------
    # PRD Part 2 section 10.4 Method A: neither parameter is out of limits on
    # its own, but low oil pressure AT HIGH RPM is a lubrication fault.
    low_speed_rpm = float(_p(p, "oil_pressure", "low_speed_rpm", 3500))
    high_speed_min = float(_p(p, "oil_pressure", "high_speed_min_psi", 29.0))

    def _oil_at_speed(tel: Telemetry, derived: dict[str, float]):
        rpm = tel.get("rpm")
        oil = tel.get("oil_pressure")
        if rpm is None or oil is None:
            return False, None
        return (rpm > low_speed_rpm and oil < high_speed_min), oil

    rules.append(
        CorrelationRule(
            rule_id="OILP_AT_SPEED", parameter="oil_pressure", level=AlertLevel.RED,
            legend="OIL PRESS LOW", priority=10, fault_mode="lubrication_issue",
            inhibit_during_start=True,
            advisory=(
                f"Oil pressure below {high_speed_min:.0f} psi above "
                f"{low_speed_rpm:.0f} rpm. Reduce power and land."
            ),
            predicate=_oil_at_speed,
        )
    )

    # THE ENGINE HAS STOPPED MAKING POWER while power is commanded. Without this
    # a fuel cut raised nothing louder than a caution: as the engine runs down
    # the oil-pressure rules are rightly inhibited below idle, and the one fact
    # that matters -- the engine has quit -- had no alert of its own. Every
    # aircraft has one. Power commanded (throttle at or above 25 %) with the
    # shaft below 1500 rpm, outside the start sequence.
    def _engine_failed(tel: Telemetry, derived: dict[str, float]):
        rpm = tel.get("rpm")
        thr = tel.get("throttle_pct")
        if rpm is None or thr is None or not derived.get("engine_was_running"):
            return False, None
        return (thr >= 25.0 and rpm < 1500.0), rpm

    rules.append(
        CorrelationRule(
            rule_id="ENGINE_FAIL", parameter="rpm", level=AlertLevel.RED,
            legend="ENGINE FAILURE", priority=11,
            advisory="Engine has stopped making power. Best glide; select a landing site.",
            predicate=_engine_failed,
        )
    )

    # A misfire shows as a cold cylinder against its siblings (PRD Part 2
    # section 10.1 Method B) -- an EGT split with one cylinder BELOW the others.
    def _misfire(tel: Telemetry, derived: dict[str, float]):
        egts = [tel.get(f"egt_{i}") for i in (1, 2, 3, 4)]
        egts = [e for e in egts if e is not None]
        rpm = tel.get("rpm")
        if len(egts) < 4 or rpm is None or rpm < 2000.0:
            return False, None
        mean = sum(egts) / len(egts)
        coldest = min(egts)
        drop = mean - coldest
        return drop > float(inj["egt_spread_fault"]) * 0.8, drop

    rules.append(
        CorrelationRule(
            rule_id="MISFIRE", parameter="egt_spread", level=AlertLevel.ORANGE,
            legend="MISFIRE SUSPECTED", priority=7, fault_mode="misfire",
            advisory="One cylinder markedly cooler than its siblings. Suspect misfire.",
            predicate=_misfire,
        )
    )

    # Sensor validity is itself alertable: a channel the ingest layer has
    # rejected must be annunciated, not silently absent (PRD Part 4 section 7).
    def _sensor_invalid(tel: Telemetry, derived: dict[str, float]):
        bad = [
            n for n, c in tel.channels.items()
            if c.state in (ValueState.INVALID, ValueState.SUSPECT)
        ]
        return bool(bad), float(len(bad))

    rules.append(
        CorrelationRule(
            rule_id="SENSOR_FAULT", parameter="sensor_validity", level=AlertLevel.YELLOW,
            legend="SENSOR FAULT", priority=5, fault_mode="sensor_drift",
            advisory="One or more channels failed validation. Affected values are removed.",
            predicate=_sensor_invalid,
        )
    )

    def _stale(tel: Telemetry, derived: dict[str, float]):
        stale = [n for n, c in tel.channels.items() if c.state is ValueState.STALE]
        return bool(stale), float(len(stale))

    rules.append(
        CorrelationRule(
            rule_id="DATA_STALE", parameter="sensor_validity", level=AlertLevel.ORANGE,
            legend="TELEMETRY STALE", priority=8, fault_mode="sensor_drift",
            advisory="Telemetry has stopped updating. Values shown are not current.",
            predicate=_stale,
        )
    )

    # The FADEC's report on itself (ECU_STATUS): lane health, the two warning
    # lamps and the error flags. Taken as the ECU reports it, never assumed: with
    # no report, or a stale one, these rules have nothing to say, and the status
    # channels the frame carries go STALE instead. Lamp meanings are the
    # manufacturer's [IM Rev.5 failure matrix]: ON is a lane no longer in
    # control, FLASHING a single-lane sensor lost with both lanes in control.
    lamp_on, lamp_flashing = 1, 2          # DBC WARN_LAMP value table

    def _ecu_report(tel: Telemetry):
        ecu = getattr(tel, "ecu", None)
        return None if ecu is None or ecu.stale else ecu

    for lane, other, bit in (("A", "B", 8), ("B", "A", 9)):
        def _lane_out(tel, derived, lane=lane, bit=bit):
            ecu = _ecu_report(tel)
            if ecu is None:
                return False, None
            health = ecu.lane_a_health if lane == "A" else ecu.lane_b_health
            lamp = ecu.warn_lamp_a if lane == "A" else ecu.warn_lamp_b
            out = bool(ecu.error_flags >> bit & 1) or health == 0 or lamp == lamp_on
            return out, float(lamp)

        def _lane_sensor(tel, derived, lane=lane, lane_out=_lane_out):
            ecu = _ecu_report(tel)
            if ecu is None:
                return False, None
            lamp = ecu.warn_lamp_a if lane == "A" else ecu.warn_lamp_b
            return lamp == lamp_flashing and not lane_out(tel, derived)[0], float(lamp)

        rules.append(
            CorrelationRule(
                rule_id=f"ECU_LANE_{lane}", parameter="ecu_status", level=AlertLevel.YELLOW,
                legend=f"ECU LANE {lane} FAULT", priority=6,
                advisory=(f"FADEC lane {lane} reports it is out of control (lane health, "
                          f"warning lamp {lane} or error flag). Lane {other} alone controls "
                          "the engine."),
                predicate=_lane_out,
            )
        )
        rules.append(
            CorrelationRule(
                rule_id=f"ECU_SENSOR_{lane}", parameter="ecu_status", level=AlertLevel.YELLOW,
                legend=f"ECU LANE {lane} SENSOR", priority=5,
                advisory=(f"Warning lamp {lane} flashing: a sensor on lane {lane} has failed. "
                          "Both lanes still control the engine."),
                predicate=_lane_sensor,
            )
        )

    # An instrument reading offset from the twin, where a second source
    # disagrees with it and the engine therefore cannot be the explanation
    # (audit 15 Sep, P0-4). An offset nothing can attribute is reported in the
    # snapshot and deliberately NOT annunciated as a sensor fault: on a single
    # sensor with no redundancy, a failing engine explains it just as well.
    drift_fraction = float(
        (thresholds or config.load_thresholds())["faults"]["sensor_drift"][
            "bias_drift_fraction_fs"])

    def _instrument_offset(tel: Telemetry, derived: dict[str, float]):
        seen = float(derived.get("instrument_offset_fraction_fs", 0.0))
        return seen > drift_fraction, seen

    rules.append(
        CorrelationRule(
            rule_id="SENSOR_BIAS", parameter="sensor_validity", level=AlertLevel.YELLOW,
            legend="SENSOR BIAS", priority=6, fault_mode="sensor_drift",
            advisory=("An instrument reads offset from the twin and its redundant source "
                      "does not share the offset, so the instrument is at fault rather "
                      "than the engine. Check it before trusting the reading."),
            predicate=_instrument_offset,
        )
    )

    def _redundancy(tel: Telemetry, derived: dict[str, float]):
        lost = [n for n, c in tel.channels.items() if getattr(c, "redundancy_lost", False)]
        return bool(lost), float(len(lost))

    rules.append(
        CorrelationRule(
            rule_id="SENSOR_REDUNDANCY", parameter="sensor_validity", level=AlertLevel.YELLOW,
            legend="SENSOR REDUNDANCY LOST", priority=5,
            advisory=("A sensor fitted to both FADEC lanes is reporting on one lane only. "
                      "The value shown is that lane's reading, with no cross-check."),
            predicate=_redundancy,
        )
    )

    for r in rules:
        if r.rule_id in RUNNING_ONLY:
            r.needs_running = True
    return rules


# RULES THAT DESCRIBE A RUNNING ENGINE. Vibration, the cylinder-to-cylinder
# splits, a misfire, the FADEC's timing deviations and the instrument-against-
# twin comparison all judge how the engine is RUNNING. With the shaft stopped
# their inputs are sensor noise about zero -- the kurtosis of an accelerometer
# at rest, the deviation of a timing nobody is scheduling, a twin comparison
# against an engine that is not making heat -- so they flickered on and off
# after shutdown, every return a NEW caution that re-lit the master and
# restarted the tone. Reported from use: "caution continuously runs after
# shutdown". Temperature limits are NOT here: a head that heat-soaks past its
# limit after shutdown is real and is still annunciated.
RUNNING_ONLY = frozenset({
    "EGT_SPLIT_CRIT", "EGT_SPLIT_HIGH", "CHT_SPREAD", "OILP_HIGH", "MAT_HIGH",
    "VIB_CRIT", "VIB_HIGH", "VIB_KURT", "INJ_DEV_FAULT", "INJ_DEV_DEGRADED",
    "IGN_DEV", "KNOCK_RETARD", "INJ_DUTY", "MISFIRE", "SENSOR_BIAS",
})
# Below this the engine is stopped or running down, not running.
STOPPED_RPM = 500.0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class RuleEngine:
    """Evaluates the rule set and maintains MIL-STD-411F alerting state."""

    def __init__(
        self,
        *,
        thresholds: dict | None = None,
        engine: dict | None = None,
        rules: list[Rule] | None = None,
    ) -> None:
        self.thresholds = thresholds or config.load_thresholds()
        self.engine = engine or config.load_engine()
        self.rules = rules if rules is not None else build_rules(self.thresholds, self.engine)

        alerting = self.thresholds["alerting"]
        self.min_display_s = float(alerting["min_display_seconds"])
        self.visible_depth = int(alerting["visible_stack_depth"])
        self.legend_max = int(alerting["legend_max_chars"])
        self.master_rearm = bool(alerting["master_reset_rearm"])
        inhibits = alerting.get("inhibits", {})
        self.warmup_oil_temp = float(inhibits.get("warmup_complete_oil_temp_C", 50.0))
        self.warning_inhibits_advisories = bool(
            inhibits.get("warning_inhibits_advisories", True)
        )
        self.start_settle_s = float(inhibits.get("engine_start_settle_s", 25.0))
        self.min_running_rpm = float(inhibits.get("min_running_rpm", 1800.0))
        self.throttle_transient_rate = float(
            inhibits.get("throttle_transient_pct_per_s", 6.0)
        )
        self.transient_settle_s = float(inhibits.get("transient_settle_s", 8.0))
        self._running_since: float | None = None
        # Has the engine been running and settled since power was last taken
        # off? The start inhibit cannot answer this: it resets whenever rpm
        # falls, so a stopped engine looks exactly like one being started.
        self._was_running = False
        self._last_throttle: tuple[float, float] | None = None
        self._transient_until: float = -1.0

        self._active: dict[str, Alert] = {}
        self._master_warning_reset_at: float = -1.0
        self._master_caution_reset_at: float = -1.0
        self.state = AlertState()

        for r in self.rules:
            if len(r.legend) > self.legend_max:
                raise ValueError(
                    f"rule {r.rule_id}: legend {r.legend!r} exceeds "
                    f"{self.legend_max} characters (PRD Part 4 section 4.4)"
                )

    # ------------------------------------------------------------------
    def _update_engine_context(self, tel: Telemetry) -> None:
        """Track how long the engine has been running and whether the operator
        is currently moving the throttle."""
        rpm = tel.get("rpm")
        if rpm is not None and rpm >= self.min_running_rpm:
            if self._running_since is None:
                self._running_since = tel.t_s
        else:
            self._running_since = None

        throttle = tel.get("throttle_pct")
        if self._settled(tel):
            self._was_running = True
        elif (throttle is not None and throttle < 10.0
                and (rpm is None or rpm < self.min_running_rpm)):
            # Power off and the shaft slow: a shutdown, not a failure.
            self._was_running = False
        if throttle is not None:
            if self._last_throttle is not None:
                t0, v0 = self._last_throttle
                dt = tel.t_s - t0
                if dt > 1e-6:
                    rate = abs(throttle - v0) / dt
                    if rate > self.throttle_transient_rate:
                        self._transient_until = tel.t_s + self.transient_settle_s
            self._last_throttle = (tel.t_s, throttle)

    @property
    def _in_start(self) -> bool:
        return self._running_since is None

    def _settled(self, tel: Telemetry) -> bool:
        if self._running_since is None:
            return False
        return (tel.t_s - self._running_since) >= self.start_settle_s

    def _inhibited(self, rule: Rule, tel: Telemetry) -> bool:
        """MIL-STD-411F 5.2.6.2 inhibit logic.

        Four conditions, each of which exists because without it the system
        raises alerts when nothing is wrong -- which 411F 4.1.1a forbids and
        which teaches an operator to ignore the panel:

          on ground + cold      cold-engine cautions during warm-up
          engine starting       oil pressure and fuel flow before they build
          below running speed   parameters that only mean something under load
          commanded transient   rate rules during a deliberate throttle change

        An inhibit the operator cannot see is a defect, so ``AlertState``
        reports whenever any of them is active.
        """
        if rule.inhibit_on_ground and tel.flight_phase in _ON_GROUND:
            oil = tel.get("oil_temperature")
            if oil is None or oil < self.warmup_oil_temp:
                return True

        if rule.inhibit_during_start and not self._settled(tel):
            return True

        if rule.inhibit_below_rpm > 0.0:
            rpm = tel.get("rpm")
            if rpm is None or rpm < rule.inhibit_below_rpm:
                return True

        if rule.inhibit_during_transient and tel.t_s < self._transient_until:
            return True

        if rule.inhibit_in_phases and tel.flight_phase in rule.inhibit_in_phases:
            return True

        if rule.needs_running:
            rpm = tel.get("rpm")
            if rpm is None or rpm < STOPPED_RPM:
                return True

        return False

    def evaluate(self, tel: Telemetry, derived: dict[str, float] | None = None) -> AlertState:
        """Run every rule once. Target latency <5 ms (PRD Part 2 section 11.1)."""
        started = time.perf_counter()
        derived = derived or {}
        now = tel.t_s
        self._update_engine_context(tel)
        derived = {**derived, "engine_was_running": 1.0 if self._was_running else 0.0}

        suppressed_params: dict[str, int] = {}
        inhibits_active = False

        # Highest priority first, so a lower-priority rule on the same
        # parameter is suppressed rather than duplicating the alert.
        for rule in sorted(self.rules, key=lambda r: -r.priority):
            if self._inhibited(rule, tel):
                inhibits_active = True
                # Clear any accumulated history. Otherwise a rate rule keeps the
                # transient in its window and fires the moment the inhibit
                # lifts, which defeats the purpose of having inhibited it.
                if isinstance(rule, RateRule):
                    rule._history.clear()
                elif isinstance(rule, PersistenceRule):
                    rule._since = None
                self._retire(rule.rule_id, now)
                continue

            tripped, value, limit = rule.evaluate(tel, derived)

            if tripped and suppressed_params.get(rule.parameter, -1) > rule.priority:
                tripped = False  # a more urgent rule already owns this parameter

            if tripped:
                suppressed_params[rule.parameter] = max(
                    suppressed_params.get(rule.parameter, 0), rule.priority
                )
                existing = self._active.get(rule.rule_id)
                if existing is None:
                    self._active[rule.rule_id] = Alert(
                        rule_id=rule.rule_id, legend=rule.legend, level=rule.level,
                        parameter=rule.parameter, value=value, limit=limit,
                        advisory=rule.advisory, fault_mode=rule.fault_mode,
                        first_seen=now, last_seen=now,
                        min_display_until=now + self.min_display_s,
                    )
                else:
                    # A held alert whose reading has gone keeps the last
                    # value it was raised on rather than showing none.
                    if value is not None:
                        existing.value = value
                    existing.last_seen = now
                    existing.clear_pending = False
            else:
                self._retire(rule.rule_id, now)

        self._prune(now)
        return self._assemble(now, inhibits_active, started)

    def _retire(self, rule_id: str, now: float) -> None:
        """Mark an alert for clearing, honouring the minimum display time."""
        alert = self._active.get(rule_id)
        if alert is None:
            return
        alert.clear_pending = True

    def _prune(self, now: float) -> None:
        """Remove cleared alerts once their minimum display time has elapsed.

        MIL-STD-411F 5.2.5.5: a warning or caution condition can exist for so
        short a time that the crew never sees it, so every such message is held
        for at least three seconds even after the condition has gone.
        """
        for rid, alert in list(self._active.items()):
            if not alert.clear_pending:
                continue
            if alert.category is AlertCategory.ADVISORY or now >= alert.min_display_until:
                del self._active[rid]

    def _assemble(self, now: float, inhibits_active: bool, started: float) -> AlertState:
        alerts = list(self._active.values())

        if self.warning_inhibits_advisories and any(a.is_warning for a in alerts):
            alerts = [a for a in alerts if a.category is not AlertCategory.ADVISORY]

        # MIL-STD-411F 5.2.5.2: warnings first, then cautions, then advisories;
        # most recent first within a category.
        order = {AlertCategory.WARNING: 0, AlertCategory.CAUTION: 1, AlertCategory.ADVISORY: 2}
        alerts.sort(key=lambda a: (order[a.category], -a.level, -a.first_seen))

        visible = alerts[: self.visible_depth]
        overflow = alerts[self.visible_depth :]

        warnings = [a for a in alerts if a.is_warning]
        cautions = [a for a in alerts if a.is_caution]

        # Master annunciators energise with any individual alert of their
        # category, and re-arm after reset so a NEW event lights them again
        # (411F 5.1.3.5 / 5.1.4.5 / 4.1.3.8).
        master_warning = any(
            a.first_seen > self._master_warning_reset_at for a in warnings
        )
        master_caution = any(
            a.first_seen > self._master_caution_reset_at for a in cautions
        )

        self.state = AlertState(
            active=visible,
            overflow=overflow,
            master_warning=master_warning,
            master_caution=master_caution,
            unacknowledged_warning=any(not a.acknowledged for a in warnings),
            inhibits_active=inhibits_active,
            evaluation_ms=(time.perf_counter() - started) * 1000.0,
        )
        return self.state

    # ------------------------------------------------------------------
    def reset_master_warning(self, now: float) -> None:
        """Push-to-reset. Extinguishes the master annunciator only.

        411F 5.1.3.5: the individual alert stays displayed. The system re-arms,
        so the next new warning lights it again.
        """
        self._master_warning_reset_at = now
        for a in self._active.values():
            if a.is_warning:
                a.acknowledged = True

    def reset_master_caution(self, now: float) -> None:
        self._master_caution_reset_at = now
        for a in self._active.values():
            if a.is_caution:
                a.acknowledged = True

    def acknowledge(self, rule_id: str) -> bool:
        alert = self._active.get(rule_id)
        if alert is None:
            return False
        alert.acknowledged = True
        return True

    def active_fault_modes(self) -> dict[str, AlertLevel]:
        """The highest alert level currently raised per problem-statement fault.

        This is the Tier-1 contribution to the fault vector that Tiers 2 and 3
        will later fuse (PRD Part 2 section 11.2).
        """
        out: dict[str, AlertLevel] = {}
        for a in self._active.values():
            if not a.fault_mode:
                continue
            if a.level > out.get(a.fault_mode, AlertLevel.GREEN):
                out[a.fault_mode] = a.level
        return out
