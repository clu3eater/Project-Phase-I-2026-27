"""The digital twin's state -- PRD Part 1 sections 6.1 and 6.2.

This is the thing the problem statement actually asks for in section A: "a
virtual engine model synchronized with live engine data". The physics model and
the live telemetry both existed before this module; what was missing was the
record that joins them and the step that keeps it current.

FOUR STATE CATEGORIES
---------------------
PRD Part 1 section 6.2 defines three; the physics model contributes a fourth.

  REPORTED    what the engine's sensors actually said, after validation
  DESIRED     what the operator or mission plan asked for
  SIMULATED   what the physics model says the engine SHOULD be doing
  PREDICTED   what the AI layer expects to happen next (health, RUL, faults)

WHY THE RESIDUAL IS THE POINT
-----------------------------
REPORTED minus SIMULATED is the residual, and it is the whole reason this
system exists. A cooling passage silting up crosses no threshold for hundreds
of hours -- but the gap between measured and predicted cylinder head
temperature starts widening from the first hour. Threshold monitoring is blind
to that. A twin is not.

So residuals are first-class here: computed on every sync, tracked with a
running mean, and exposed as the primary input to the AI layer. Everything else
in this module exists to make the residual trustworthy.

VALIDITY IS CARRIED THROUGH, NOT DISCARDED
------------------------------------------
The ingest layer knows whether each channel is VALID, STALE, INVALID, MISSING
or SUSPECT. That information survives into the twin: a residual computed from a
stale measurement is marked unusable rather than being quietly averaged in with
good data. PRD Part 4 section 7.2 -- remove, never substitute.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common import config
from layer1_edge.can_ingest import Telemetry, ValueState
from layer2_physics.atmosphere import ambient_at

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------


class Strict(BaseModel):
    """Base model. Rejects unknown fields.

    PRD Part 0 section 0.11: "Pydantic validates all twin-state I/O; invalid
    data is rejected + logged." A typo in a field name must fail loudly rather
    than silently creating a field nobody reads.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Measurement(Strict):
    """One value plus everything known about whether to believe it."""

    value: float | None = None
    state: str = ValueState.MISSING.value
    age_s: float | None = None
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.state in (ValueState.VALID.value, ValueState.SUSPECT.value)

    @classmethod
    def from_channel(cls, tel: Telemetry, name: str) -> Measurement:
        ch = tel.channels.get(name)
        if ch is None:
            return cls()
        return cls(
            value=ch.value,
            state=str(ch.state),
            age_s=None if math.isinf(ch.age_s) else round(ch.age_s, 3),
            reason=ch.reason,
        )


class PerCylinder(Strict):
    """Four cylinders plus the spread, which is what most detectors key on."""

    cyl_1: Measurement = Field(default_factory=Measurement)
    cyl_2: Measurement = Field(default_factory=Measurement)
    cyl_3: Measurement = Field(default_factory=Measurement)
    cyl_4: Measurement = Field(default_factory=Measurement)
    spread: float | None = None

    def values(self) -> list[float]:
        return [
            m.value
            for m in (self.cyl_1, self.cyl_2, self.cyl_3, self.cyl_4)
            if m.usable and m.value is not None
        ]

    def recompute_spread(self) -> None:
        vals = self.values()
        self.spread = (max(vals) - min(vals)) if len(vals) >= 2 else None

    @classmethod
    def from_channels(cls, tel: Telemetry, prefix: str) -> PerCylinder:
        obj = cls(**{f"cyl_{i}": Measurement.from_channel(tel, f"{prefix}_{i}") for i in (1, 2, 3, 4)})
        obj.recompute_spread()
        return obj


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TwinMetadata(Strict):
    """Identity and life record. PRD Part 1 section 6.1."""

    twin_id: str
    aircraft_id: str = ""
    engine_type: str = "ROTAX_915IS"
    engine_key: str = "rotax_915is"
    serial_number: str = ""
    installation_date: datetime | None = None
    total_flight_hours: float = 0.0
    total_cycles: int = 0
    last_maintenance_date: datetime | None = None
    lifecycle: Literal["CREATED", "ACTIVE", "MAINTENANCE", "DECOMMISSIONED"] = "CREATED"

    # Time between overhaul is BOTH an hours limit and a calendar limit --
    # "1200 h or 15 years, whichever comes first" (MML-915 i section 05-10-00).
    # An engine that flies rarely still ages, so remaining life must respect
    # both. See docs/PRD_DEVIATIONS.md DEV-26.
    tbo_hours: float = 1200.0
    tbo_calendar_years: float = 15.0
    # Time between overhaul is counted from the last overhaul, not from new:
    # an overhauled engine has its TBO ahead of it again while its total time
    # keeps accumulating. Both are zero-based on an engine never overhauled.
    hours_at_last_overhaul: float = 0.0
    last_overhaul_date: datetime | None = None

    @property
    def hours_since_overhaul(self) -> float:
        return max(0.0, self.total_flight_hours - self.hours_at_last_overhaul)

    @property
    def tbo_hours_remaining(self) -> float:
        return max(0.0, self.tbo_hours - self.hours_since_overhaul)

    def tbo_years_remaining(self, now: datetime | None = None) -> float | None:
        start = self.last_overhaul_date or self.installation_date
        if start is None:
            return None
        now = now or datetime.now(UTC)
        elapsed_years = (now - start).days / 365.25
        return max(0.0, self.tbo_calendar_years - elapsed_years)

    def tbo_remaining_hours_effective(
        self, now: datetime | None = None, hours_per_year: float = 300.0
    ) -> float:
        """Remaining life in hours, limited by whichever clock runs out first.

        The calendar limit is converted to hours using an assumed utilisation
        so the two can be compared. Reporting only the hours figure would
        overstate the life of a low-utilisation airframe.
        """
        by_hours = self.tbo_hours_remaining
        by_years = self.tbo_years_remaining(now)
        if by_years is None:
            return by_hours
        return min(by_hours, by_years * hours_per_year)


# ---------------------------------------------------------------------------
# Reported state -- what the engine said
# ---------------------------------------------------------------------------


class Environmental(Strict):
    oat_c: Measurement = Field(default_factory=Measurement)
    altitude_ft: Measurement = Field(default_factory=Measurement)
    airspeed_kmh: Measurement = Field(default_factory=Measurement)
    # PRD Part 1 section 6.1 lists ambient pressure. No pressure transducer is
    # published on the engine bus, so it is derived from the reported pressure
    # altitude via the standard atmosphere rather than left blank -- the
    # relationship is exact by definition, since pressure altitude IS a
    # pressure measurement expressed in feet.
    ambient_pressure_hpa: float | None = None
    humidity_pct: float | None = None
    flight_phase: int = 0


class Electrical(Strict):
    bus_voltage: Measurement = Field(default_factory=Measurement)
    alternator_current: Measurement = Field(default_factory=Measurement)
    # PRD Part 1 section 6.1 lists alternator voltage separately from battery
    # voltage. The 915 iS publishes ONE regulated DC bus voltage (OM section
    # 7.5.4) -- when the alternator is charging, bus voltage IS its regulated
    # output, and there is no second sensor. Kept as a distinct field so a
    # future installation with a separate transducer needs no schema change,
    # and left MISSING rather than mirrored from the bus, which would invent a
    # measurement that does not exist.
    alternator_voltage: Measurement = Field(default_factory=Measurement)
    battery_soh: float | None = None


class Vibration(Strict):
    rms_x: Measurement = Field(default_factory=Measurement)
    rms_y: Measurement = Field(default_factory=Measurement)
    rms_z: Measurement = Field(default_factory=Measurement)
    rms_total: float | None = None
    kurtosis: Measurement = Field(default_factory=Measurement)
    # PRD Part 1 section 6.1. Populated by the edge node's order analysis of the
    # 10 kHz waveform (engine_sim.vibration_waveform), which is not part of the
    # 10 Hz CAN telemetry -- so it stays None on a pure-telemetry path rather
    # than being back-computed from rpm, which would only restate the 1x order
    # the analysis is meant to discover.
    dominant_frequency_hz: float | None = None
    spectral_peaks: dict[str, float] = Field(default_factory=dict)


class TimingState(Strict):
    """Injection and ignition, commanded and measured.

    Deviation is what diagnoses an injector (PRD Part 2 section 10.2 Method C);
    neither the commanded nor the measured value means much alone.
    """

    injection_measured: PerCylinder = Field(default_factory=PerCylinder)
    ignition_measured: PerCylinder = Field(default_factory=PerCylinder)
    injection_commanded: Measurement = Field(default_factory=Measurement)
    ignition_commanded: Measurement = Field(default_factory=Measurement)
    injection_period_ms: Measurement = Field(default_factory=Measurement)
    injector_duty_pct: Measurement = Field(default_factory=Measurement)
    knock_retard_deg: Measurement = Field(default_factory=Measurement)
    injection_deviation_max: float | None = None
    ignition_deviation_max: float | None = None


class ReportedState(Strict):
    """What the sensors said, after validation. PRD Part 1 section 6.1."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    t_s: float = 0.0

    rpm: Measurement = Field(default_factory=Measurement)
    propeller_rpm: Measurement = Field(default_factory=Measurement)
    cht: PerCylinder = Field(default_factory=PerCylinder)
    cht_max: Measurement = Field(default_factory=Measurement)
    coolant_temperature: Measurement = Field(default_factory=Measurement)
    egt: PerCylinder = Field(default_factory=PerCylinder)
    egt_max: Measurement = Field(default_factory=Measurement)
    oil_pressure: Measurement = Field(default_factory=Measurement)
    oil_temperature: Measurement = Field(default_factory=Measurement)
    fuel_flow: Measurement = Field(default_factory=Measurement)
    fuel_pressure: Measurement = Field(default_factory=Measurement)
    manifold_pressure: Measurement = Field(default_factory=Measurement)
    manifold_air_temperature: Measurement = Field(default_factory=Measurement)
    throttle_pct: Measurement = Field(default_factory=Measurement)
    wastegate_pct: Measurement = Field(default_factory=Measurement)
    # The airframe's cooling-air flaps. This engine has no thermostat, so these
    # are what hold coolant and oil temperature -- and, like the wastegate,
    # what a losing radiator spends before any temperature moves.
    cooling_flap_pct: Measurement = Field(default_factory=Measurement)
    oil_flap_pct: Measurement = Field(default_factory=Measurement)
    air_flow_g_per_min: Measurement = Field(default_factory=Measurement)

    vibration: Vibration = Field(default_factory=Vibration)
    electrical: Electrical = Field(default_factory=Electrical)
    timing: TimingState = Field(default_factory=TimingState)
    environmental: Environmental = Field(default_factory=Environmental)

    # Data-quality summary, so a consumer can judge the whole frame at once.
    channels_total: int = 0
    channels_usable: int = 0
    channels_stale: int = 0
    channels_invalid: int = 0

    @property
    def data_quality(self) -> float:
        if self.channels_total == 0:
            return 0.0
        return self.channels_usable / self.channels_total


# ---------------------------------------------------------------------------
# Simulated state -- what the physics says
# ---------------------------------------------------------------------------


class SimulatedState(Strict):
    """The physics model's view. PRD Part 1 section 6.1 `simulated_state`."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cht_predicted: float | None = None
    coolant_predicted: float | None = None
    egt_predicted: float | None = None
    oil_pressure_predicted: float | None = None
    oil_temperature_predicted: float | None = None
    fuel_flow_predicted: float | None = None
    manifold_pressure_predicted: float | None = None
    bmep_predicted: float | None = None
    torque_predicted: float | None = None
    power_predicted_kw: float | None = None
    bsfc_predicted: float | None = None
    # PRD Part 1 section 6.1 `model_residual`: one number for "how well does the
    # model currently match the engine". Channels have different units, so the
    # raw residuals are normalised by their configured feature scales before
    # being combined -- an unnormalised RMSE over kelvin, psi and litres/hour
    # would simply report whichever channel has the largest units.
    model_residual: float | None = None
    physics_constraint_violations: int = 0
    model_available: bool = False
    # Where the physics is running beyond the manufacturer's performance table
    # (4500-5800 rpm, sea level to 22,999 ft, ISA-15 to ISA+30), in words.
    # There the model holds the nearest printed edge, so a prediction is an
    # approximation rather than the manual. Empty when every figure is backed
    # by it. See layer2_physics.om_table.outside_table.
    outside_manufacturer_data: list[str] = Field(default_factory=list)


class Residual(Strict):
    """Measured minus predicted, for one channel.

    ``usable`` is false when either side is missing or the measurement failed
    validation. A residual computed from a stale reading is not a small
    residual -- it is no residual at all, and treating it as data is how a
    monitoring system convinces itself an engine is healthy.
    """

    measured: float | None = None
    predicted: float | None = None
    delta: float | None = None
    mean_delta: float | None = None
    samples: int = 0
    usable: bool = False


class ResidualSet(Strict):
    """Every residual the twin tracks, plus a running mean of each."""

    cht: Residual = Field(default_factory=Residual)
    coolant: Residual = Field(default_factory=Residual)
    egt: Residual = Field(default_factory=Residual)
    oil_pressure: Residual = Field(default_factory=Residual)
    oil_temperature: Residual = Field(default_factory=Residual)
    fuel_flow: Residual = Field(default_factory=Residual)
    manifold_pressure: Residual = Field(default_factory=Residual)

    # The single most diagnostic derived quantity in the whole system: scale
    # build-up degrades the head-to-coolant path, so this delta widens while a
    # thermostatted coolant loop holds its own temperature steady
    # (PRD Part 2 section 10.3).
    cht_minus_coolant: float | None = None

    def usable_names(self) -> list[str]:
        return [
            n for n in ("cht", "coolant", "egt", "oil_pressure",
                        "oil_temperature", "fuel_flow", "manifold_pressure")
            if getattr(self, n).usable
        ]


# ---------------------------------------------------------------------------
# Predicted state -- what the AI layer expects
# ---------------------------------------------------------------------------


FAULT_KEYS = (
    "misfire",
    "injector_abnormal",
    "cooling_degradation",
    "lubrication_issue",
    "sensor_drift",
    "combustion_instability",
    "overheating_trend",
    "abnormal_vibration",
)


class HealthIndices(Strict):
    """PRD Part 2 section 9.3. Composite plus its four sub-indices."""

    composite: float | None = None
    thermal: float | None = None
    mechanical: float | None = None
    electrical: float | None = None
    combustion: float | None = None
    band: str = "UNKNOWN"

    @field_validator("composite", "thermal", "mechanical", "electrical", "combustion")
    @classmethod
    def _in_unit_range(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f"health index must be in [0, 1], got {v}")
        return v


class RemainingLife(Strict):
    """RUL with its interval. PRD Part 4 section 7.4a forbids a bare number."""

    hours: float | None = None
    # PRD Part 2 section 12: one cycle = one start-stop. Reported alongside
    # hours because a short-sortie fleet consumes cycle life far faster than
    # hours would suggest.
    cycles: int | None = None
    lower_hours: float | None = None
    upper_hours: float | None = None
    confidence: float = 0.95
    limited_by: str = ""
    # "data" and "fused" are the PRD's own vocabulary and are kept so nothing
    # already reading this field breaks. "lstm" and "physics_fallback" are
    # added by DEV-191: once the trained network is actually served, "which
    # estimator produced this number" and "did the better one decline to
    # answer" are different questions, and a single "physics" answered neither.
    # An operator seeing physics_fallback knows the figure is the weaker
    # estimate rather than the intended one.
    source: Literal[
        "none", "physics", "data", "fused", "lstm", "physics_fallback"
    ] = "none"

    @property
    def reportable(self) -> bool:
        """A remaining-life figure without an interval must not be displayed."""
        return (
            self.hours is not None
            and self.lower_hours is not None
            and self.upper_hours is not None
        )


class DegradationEstimate(Strict):
    """The six degradation factors of PRD Part 1 section 6.1. 1.0 = as-new.

    Field names match ``layer2_physics.degradation.DegradationFactors`` exactly
    so the estimator's output and the simulator's ground truth can be compared
    without a translation layer -- which is what makes the estimate scorable.
    """

    cooling_efficiency: float | None = None
    oil_quality: float | None = None
    combustion_efficiency: float | None = None
    injector_condition: float | None = None
    bearing_condition: float | None = None
    turbocharger_condition: float | None = None

    @field_validator("*")
    @classmethod
    def _in_unit_range(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 1.5):
            raise ValueError(f"degradation factor out of range: {v}")
        return v

    def worst(self) -> tuple[str, float] | None:
        """The most degraded subsystem -- what the advisory should name."""
        vals = {k: v for k, v in self.model_dump().items() if v is not None}
        return min(vals.items(), key=lambda kv: kv[1]) if vals else None


class MaintenanceAdvisory(Strict):
    """PRD Part 1 section 6.1 `maintenance_advisory`, PS section F.

    What the maintenance engineer is actually supposed to DO. An advisory with
    no ``recommended_action`` and no ``time_to_action`` is a status light, not
    an advisory, so both are carried explicitly.

    ``shap_explanation`` carries the EXACT share of the health shortfall
    attributable to each subsystem, filled by ``layer3_ai.explain``. It is not
    a SHAP approximation despite the field name (kept from PRD Part 1 s6.1):
    the composite index is a weighted sum of minima, so the decomposition is
    closed-form, and an approximation of a known quantity would be strictly
    worse. PRD Part 4 forbids presenting a maintenance recommendation the
    operator cannot interrogate, and this is what makes it interrogable.
    """

    severity: Literal[
        "INFO", "ADVISORY", "CAUTION", "WARNING", "EMERGENCY"
    ] = "INFO"
    message: str = ""
    recommended_action: str = ""
    time_to_action: str = ""
    shap_explanation: dict[str, float] = Field(default_factory=dict)
    fault_codes: list[str] = Field(default_factory=list)
    source: Literal["none", "rules", "model", "fused"] = "none"


class PredictedState(Strict):
    """PRD Part 1 section 6.1 `predicted_state`."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    health: HealthIndices = Field(default_factory=HealthIndices)
    rul: RemainingLife = Field(default_factory=RemainingLife)
    fault_probability: dict[str, float] = Field(
        default_factory=lambda: dict.fromkeys(FAULT_KEYS, 0.0)
    )
    degradation_factors: DegradationEstimate = Field(default_factory=DegradationEstimate)
    # Where the fault probabilities came from. "none" means nothing scored them
    # and the vector is zeros because no number was earned -- not because the
    # engine is known to be healthy.
    fault_probability_source: str = "none"
    # What the Tier-1 RULES saw, as alert levels. Evidence in its own right,
    # and kept as levels rather than converted into probabilities that no
    # measurement supports (audit 15 Sep, P1-1).
    rule_fault_levels: dict[str, int] = Field(default_factory=dict)
    # When model confidence drops below the configured floor the system falls
    # back to rules and must SAY so (PRD Part 4 section 7.4b).
    rule_based_fallback: bool = True
    model_confidence: float | None = None

    @field_validator("fault_probability")
    @classmethod
    def _known_faults(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = set(v) - set(FAULT_KEYS)
        if unknown:
            raise ValueError(f"unknown fault keys: {sorted(unknown)}")
        for k, p in v.items():
            if not (0.0 <= p <= 1.0):
                raise ValueError(f"fault probability {k}={p} outside [0, 1]")
        return v


class DesiredState(Strict):
    """What the operator or mission plan asked for. PRD Part 1 section 6.2."""

    target_throttle_pct: float | None = None
    target_rpm: float | None = None
    max_cht_c: float | None = None
    max_coolant_c: float | None = None
    mission_id: str = ""
    power_limit_reason: str = ""


class ActiveAlert(Strict):
    """One alert, carried in the twin so replay and reports can see it."""

    rule_id: str
    legend: str
    level: int
    category: str
    parameter: str
    value: float | None = None
    limit: float | None = None
    advisory: str = ""
    fault_mode: str = ""
    first_seen_s: float = 0.0
    acknowledged: bool = False


class AlertSummary(Strict):
    active: list[ActiveAlert] = Field(default_factory=list)
    overflow_count: int = 0
    master_warning: bool = False
    master_caution: bool = False
    inhibits_active: bool = False


class OperationalHistory(Strict):
    """PRD Part 1 section 6.1 `operational_history`. Life-to-date extremes."""

    mission_count: int = 0
    last_mission_id: str = ""
    # A thermal cycle is a cold-to-hot-to-cold excursion of the cylinder head.
    # It is counted separately from start-stop cycles because it is the
    # quantity that actually drives thermal fatigue: a hot restart consumes a
    # start-stop cycle but almost no thermal life.
    thermal_cycles: int = 0
    max_cht_recorded: float | None = None
    max_coolant_recorded: float | None = None
    max_egt_recorded: float | None = None
    max_vibration_recorded: float | None = None
    max_rpm_recorded: float | None = None
    hours_since_inspection: float = 0.0
    time_above_max_continuous_s: float = 0.0


# ---------------------------------------------------------------------------
# The twin
# ---------------------------------------------------------------------------


class TwinState(Strict):
    """Everything the twin knows about one engine at one instant."""

    schema_version: str = SCHEMA_VERSION
    metadata: TwinMetadata
    reported: ReportedState = Field(default_factory=ReportedState)
    desired: DesiredState = Field(default_factory=DesiredState)
    simulated: SimulatedState = Field(default_factory=SimulatedState)
    predicted: PredictedState = Field(default_factory=PredictedState)
    residuals: ResidualSet = Field(default_factory=ResidualSet)
    advisory: MaintenanceAdvisory = Field(default_factory=MaintenanceAdvisory)
    alerts: AlertSummary = Field(default_factory=AlertSummary)
    history: OperationalHistory = Field(default_factory=OperationalHistory)

    sync_count: int = 0
    last_sync_utc: datetime | None = None

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=False)

    def change_hash(self) -> str:
        """SHA-256 of the state, for the audit log.

        PRD Part 1 section 2.5 requires every state mutation to be logged with
        a UTC timestamp, a user and a change hash. This is that hash.
        """
        payload = self.model_dump(mode="json", exclude={"last_sync_utc", "sync_count"})
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()


# ---------------------------------------------------------------------------
# Synchronisation
# ---------------------------------------------------------------------------


def band_for_value(value: float, thresholds: dict) -> tuple[str, str]:
    """CHI band for any 0-1 index, using the configured band table.

    Shared so a sub-index is graded on exactly the same scale as the composite;
    a second table would drift from the first.
    """
    for b in thresholds["health"]["chi_bands"]:
        if value >= float(b["min"]):
            return str(b["label"]), str(b["action"])
    return "UNSAFE", "ground_immediately"


class TwinSynchroniser:
    """Keeps a ``TwinState`` current from telemetry, physics and alerts.

    One call to :meth:`sync` per telemetry frame. Each source is optional --
    the twin degrades gracefully rather than refusing to update:

      * telemetry only          reported state, no residuals
      * telemetry + physics     residuals become available
      * plus alerts             alert summary and fault contributions
      * plus AI                 health, RUL and fault probabilities
    """

    def __init__(self, state: TwinState, *, engine_key: str | None = None) -> None:
        self.state = state
        self.engine = config.load_engine(engine_key or state.metadata.engine_key)
        self.thresholds = config.load_thresholds()
        self.params = self.thresholds["parameters"]
        self._residual_sums: dict[str, float] = {}
        self._residual_counts: dict[str, int] = {}
        self._last_t: float | None = None
        # Cycle counting needs to remember which side of each hysteresis band
        # the engine was last seen on; counting on a bare threshold crossing
        # would add a cycle for every noise excursion around it.
        self._was_running = False
        self._thermally_hot = False
        # Whether the health indices describe a JUDGED condition. The live
        # loop judges the engine only warm, loaded and steady (live.py
        # `_assessable`); before the first such judgement the indices are the
        # operating point, not wear -- a stopped engine's alternator gives no
        # current, so its electrical index is low. Set by the live loop.
        self.health_assessed = True
        self._norm = self.thresholds["feature_norm"]
        self._sq_sum = 0.0
        self._sq_n = 0

    # -- reported ------------------------------------------------------------

    def _sync_reported(self, tel: Telemetry) -> None:
        r = self.state.reported
        r.timestamp = datetime.now(UTC)
        r.t_s = tel.t_s

        r.rpm = Measurement.from_channel(tel, "rpm")
        r.propeller_rpm = Measurement.from_channel(tel, "propeller_rpm")
        r.cht = PerCylinder.from_channels(tel, "cht")
        r.cht_max = Measurement.from_channel(tel, "cht_max")
        r.coolant_temperature = Measurement.from_channel(tel, "coolant_temperature")
        r.egt = PerCylinder.from_channels(tel, "egt")
        r.egt_max = Measurement.from_channel(tel, "egt_max")
        r.oil_pressure = Measurement.from_channel(tel, "oil_pressure")
        r.oil_temperature = Measurement.from_channel(tel, "oil_temperature")
        r.fuel_flow = Measurement.from_channel(tel, "fuel_flow")
        r.fuel_pressure = Measurement.from_channel(tel, "fuel_pressure")
        r.manifold_pressure = Measurement.from_channel(tel, "manifold_pressure")
        r.manifold_air_temperature = Measurement.from_channel(
            tel, "manifold_air_temperature"
        )
        r.throttle_pct = Measurement.from_channel(tel, "throttle_pct")
        r.wastegate_pct = Measurement.from_channel(tel, "wastegate_pct")
        r.cooling_flap_pct = Measurement.from_channel(tel, "cooling_flap_pct")
        r.oil_flap_pct = Measurement.from_channel(tel, "oil_flap_pct")
        r.air_flow_g_per_min = Measurement.from_channel(tel, "air_flow")

        v = r.vibration
        v.rms_x = Measurement.from_channel(tel, "vibration_rms_x")
        v.rms_y = Measurement.from_channel(tel, "vibration_rms_y")
        v.rms_z = Measurement.from_channel(tel, "vibration_rms_z")
        v.kurtosis = Measurement.from_channel(tel, "vibration_kurtosis")
        axes = [m.value for m in (v.rms_x, v.rms_y, v.rms_z) if m.usable and m.value is not None]
        v.rms_total = math.sqrt(sum(a * a for a in axes)) if axes else None

        e = r.electrical
        e.bus_voltage = Measurement.from_channel(tel, "battery_voltage")
        e.alternator_current = Measurement.from_channel(tel, "alternator_current")

        t = r.timing
        t.injection_measured = PerCylinder.from_channels(tel, "injection_timing")
        t.ignition_measured = PerCylinder.from_channels(tel, "ignition_timing")
        t.injection_commanded = Measurement.from_channel(tel, "injection_timing_cmd")
        t.ignition_commanded = Measurement.from_channel(tel, "ignition_timing_cmd")
        t.injection_period_ms = Measurement.from_channel(tel, "injection_period")
        t.injector_duty_pct = Measurement.from_channel(tel, "injector_duty")
        t.knock_retard_deg = Measurement.from_channel(tel, "knock_retard")

        env = r.environmental
        env.oat_c = Measurement.from_channel(tel, "oat")
        env.altitude_ft = Measurement.from_channel(tel, "altitude_ft")
        env.airspeed_kmh = Measurement.from_channel(tel, "airspeed_kmh")
        env.flight_phase = tel.flight_phase
        if env.altitude_ft.usable and env.altitude_ft.value is not None:
            env.ambient_pressure_hpa = ambient_at(env.altitude_ft.value).pressure_hpa
        else:
            env.ambient_pressure_hpa = None

        states = [c.state for c in tel.channels.values()]
        r.channels_total = len(states)
        r.channels_usable = sum(
            1 for s in states if s in (ValueState.VALID, ValueState.SUSPECT)
        )
        r.channels_stale = sum(1 for s in states if s is ValueState.STALE)
        r.channels_invalid = sum(1 for s in states if s is ValueState.INVALID)

    def _sync_timing_deviation(self, derived: dict[str, float]) -> None:
        t = self.state.reported.timing
        t.injection_deviation_max = derived.get("injection_timing_deviation_max")
        t.ignition_deviation_max = derived.get("ignition_timing_deviation_max")

    # -- simulated -----------------------------------------------------------

    def _sync_simulated(self, physics: Any) -> None:
        s = self.state.simulated
        s.timestamp = datetime.now(UTC)
        s.model_available = True
        s.cht_predicted = physics.cht_max
        s.coolant_predicted = physics.coolant_temperature_c
        s.egt_predicted = physics.egt_max
        s.oil_pressure_predicted = physics.oil_pressure_psi
        s.oil_temperature_predicted = physics.oil_temperature_c
        s.fuel_flow_predicted = physics.fuel_flow_lph
        s.manifold_pressure_predicted = physics.manifold_pressure_bar
        s.bmep_predicted = physics.bmep_bar
        s.torque_predicted = physics.torque_nm
        s.power_predicted_kw = physics.power_kw
        s.bsfc_predicted = physics.bsfc_g_per_kwh
        s.physics_constraint_violations = physics.physics_constraint_violations

    # -- residuals -----------------------------------------------------------

    def _residual(self, name: str, measured: Measurement, predicted: float | None) -> Residual:
        res = Residual(measured=measured.value, predicted=predicted)
        if not measured.usable or measured.value is None or predicted is None:
            # Deliberately NOT a zero residual. An unusable measurement means
            # we do not know the residual, which is different from knowing it
            # is small (PRD Part 4 section 7.2).
            res.usable = False
            return res
        res.delta = measured.value - predicted
        res.usable = True
        self._residual_sums[name] = self._residual_sums.get(name, 0.0) + res.delta
        self._residual_counts[name] = self._residual_counts.get(name, 0) + 1
        res.samples = self._residual_counts[name]
        res.mean_delta = self._residual_sums[name] / res.samples
        return res

    def _sync_residuals(self) -> None:
        r, s, out = self.state.reported, self.state.simulated, self.state.residuals
        if not s.model_available:
            self.state.residuals = ResidualSet()
            return
        out.cht = self._residual("cht", r.cht_max, s.cht_predicted)
        out.coolant = self._residual("coolant", r.coolant_temperature, s.coolant_predicted)
        out.egt = self._residual("egt", r.egt_max, s.egt_predicted)
        out.oil_pressure = self._residual("oil_p", r.oil_pressure, s.oil_pressure_predicted)
        out.oil_temperature = self._residual(
            "oil_t", r.oil_temperature, s.oil_temperature_predicted
        )
        out.fuel_flow = self._residual("fuel", r.fuel_flow, s.fuel_flow_predicted)
        out.manifold_pressure = self._residual(
            "map", r.manifold_pressure, s.manifold_pressure_predicted
        )

        if r.cht_max.usable and r.coolant_temperature.usable:
            if r.cht_max.value is not None and r.coolant_temperature.value is not None:
                out.cht_minus_coolant = r.cht_max.value - r.coolant_temperature.value
        else:
            out.cht_minus_coolant = None

        s.model_residual = self._model_residual(out)

    def _model_residual(self, res: ResidualSet) -> float | None:
        """One scalar for model-vs-engine agreement (PRD Part 1 section 6.1).

        Two decisions matter here.

        Each residual is divided by its configured feature scale before being
        combined. Without that, an RMSE over kelvin, psi and litres per hour
        just reports whichever channel has the biggest units, and a 0.5 L/h
        fuel error vanishes next to a 3 K temperature error.

        The value is accumulated ACROSS the mission rather than computed from
        the current frame alone. A single-sample "RMSE" is not an RMSE -- it is
        an instantaneous magnitude, and it is dominated by sensor noise. In
        testing it read LOWER under an injected injector fault than on a
        healthy engine purely because of where the last frame happened to fall,
        which is exactly the kind of number that looks authoritative and means
        nothing.
        """
        scale_key = {
            "cht": "cht_avg", "coolant": "cht_avg", "egt": "egt_avg",
            "oil_pressure": "oil_pressure", "oil_temperature": "oil_temperature",
            "fuel_flow": "fuel_flow",
        }
        terms = []
        for name, key in scale_key.items():
            r = getattr(res, name)
            if not r.usable or r.delta is None:
                continue
            scale = float(self._norm[key]["scale"])
            if scale > 0:
                terms.append((r.delta / scale) ** 2)
        if not terms:
            return None if self._sq_n == 0 else math.sqrt(self._sq_sum / self._sq_n)
        self._sq_sum += sum(terms) / len(terms)
        self._sq_n += 1
        return math.sqrt(self._sq_sum / self._sq_n)

    def _check_physics_constraints(self) -> None:
        """PRD Part 1 section 6.2: the predicted state must itself be possible.

        A model that has diverged will happily report a 400 C head. Catching it
        here means the twin says "prediction invalid" instead of publishing a
        confident absurdity, and it is the difference between a model failure
        that is noticed and one that quietly corrupts every downstream residual.
        """
        s = self.state.simulated
        if not s.model_available:
            return
        checks = (
            (s.cht_predicted, "cht"),
            (s.coolant_predicted, "coolant_temperature"),
            (s.egt_predicted, "egt"),
            (s.oil_pressure_predicted, "oil_pressure"),
            (s.oil_temperature_predicted, "oil_temperature"),
        )
        for value, key in checks:
            spec = self.params.get(key, {})
            band = spec.get("plausible_range") or spec.get("range")
            if value is None or not band:
                continue
            if not (float(band[0]) <= value <= float(band[1])):
                s.physics_constraint_violations += 1

    # -- alerts and history ---------------------------------------------------

    def _sync_alerts(self, alert_state: Any) -> None:
        a = self.state.alerts
        a.active = [
            ActiveAlert(
                rule_id=x.rule_id, legend=x.legend, level=int(x.level),
                category=str(x.category), parameter=x.parameter, value=x.value,
                limit=x.limit, advisory=x.advisory, fault_mode=x.fault_mode,
                first_seen_s=x.first_seen, acknowledged=x.acknowledged,
            )
            for x in alert_state.active
        ]
        a.overflow_count = alert_state.overflow_count
        a.master_warning = alert_state.master_warning
        a.master_caution = alert_state.master_caution
        a.inhibits_active = alert_state.inhibits_active

    # Alert level -> the five advisory severities of PRD Part 1 section 6.1.
    _SEVERITY = {1: "INFO", 2: "ADVISORY", 3: "CAUTION", 4: "WARNING", 5: "EMERGENCY"}

    # CHI band -> the severity that band alone justifies. The band table in
    # thresholds.yaml already carries the ACTION for each; this maps it to the
    # five advisory severities of PRD Part 1 section 6.1.
    _BAND_SEVERITY = {
        "EXCELLENT": ("INFO", 1), "GOOD": ("INFO", 1), "FAIR": ("ADVISORY", 2),
        "POOR": ("CAUTION", 3), "DEGRADED": ("CAUTION", 3),
        "CRITICAL": ("WARNING", 4), "UNSAFE": ("EMERGENCY", 5),
    }

    def _sync_advisory(self) -> None:
        """Derive the maintenance advisory (PRD Part 1 section 6.1, PS section F).

        Until Layer 3 exists this is driven by the rule engine, and it says so
        via ``source``. That matters: PRD Part 4 section 7.4b requires the
        system to declare when it is running on rules rather than models, so an
        engineer never mistakes a threshold trip for a learned prediction.

        The advisory names the ACTION and the TIMEFRAME, not just the fault.
        An advisory that reports "OIL PRESS LOW" and stops is a status light;
        what a maintenance engineer needs is what to do and by when.
        """
        alerts = self.state.alerts
        h = self.state.predicted.health
        band = h.band
        band_sev, band_rank = self._BAND_SEVERITY.get(band, ("INFO", 1))
        # NOT YET JUDGED, NOT GRADED. Measured: a parked engine after a
        # restart read EMERGENCY "ELECTRICAL subsystem UNSAFE -- ground the
        # aircraft" from an alternator that was simply not turning. Limits
        # still speak (the alert path below); health does not until it has
        # been assessed.
        if not self.health_assessed:
            band_sev, band_rank = "INFO", 1

        # A weighted average dilutes one destroyed subsystem behind three
        # healthy ones -- the same defect DEV-45 found at end-of-life, arriving
        # here instead. Measured: an engine with cooling efficiency at 0.53 and
        # a thermal sub-index of 0.63 still scored a composite of 0.806 = GOOD,
        # and the advisory said "no action required" while the head ran 12.7 K
        # hotter than an as-new engine would. The WORST subsystem is therefore
        # graded alongside the composite and the more severe of the two wins.
        subs = [v for v in (h.thermal, h.mechanical, h.electrical, h.combustion)
                if v is not None] if self.health_assessed else []
        if subs:
            worst_sub = min(subs)
            sub_band, _ = band_for_value(worst_sub, self.thresholds)
            sub_sev, sub_rank = self._BAND_SEVERITY.get(sub_band, ("INFO", 1))
            if sub_rank > band_rank:
                band_sev, band_rank, band = sub_sev, sub_rank, sub_band

        if not alerts.active:
            if band_rank <= 1:
                # MIL-STD-411F 4.1.1a: nothing to say when the engine is normal.
                self.state.advisory = MaintenanceAdvisory(
                    severity="INFO",
                    message="Normal operation. Continue monitoring.",
                    recommended_action="No action required.",
                    time_to_action=(
                        f"Next scheduled inspection at "
                        f"{self.state.metadata.tbo_hours_remaining:.0f} h remaining"
                    ),
                    source="rules",
                )
                return

            # Health has degraded with NO limit crossed. This is the case the
            # whole system exists for, and an advisory driven only by the rule
            # engine reports "Normal operation. No action required." while the
            # health index sits in a band whose configured action is "monitor
            # closely". Saying nothing here would discard the finding on the
            # last step before the operator -- the same defect the fusion layer
            # had (DEV-58), arriving through a different door.
            worst_name = ""
            if subs:
                names = {"thermal": h.thermal, "mechanical": h.mechanical,
                         "electrical": h.electrical, "combustion": h.combustion}
                worst_name = min(
                    (k for k, v in names.items() if v is not None),
                    key=lambda k: names[k],
                )
            self.state.advisory = MaintenanceAdvisory(
                severity=band_sev,
                message=(
                    f"{worst_name.upper()} subsystem {band} — degradation "
                    f"detected, no limit exceeded"
                    if worst_name else
                    f"Engine health {band} — degradation detected, no limit exceeded"
                ),
                recommended_action=self._band_action(band),
                time_to_action=self._band_timeframe(band_rank),
                source="rules",
            )
            return

        worst = max(alerts.active, key=lambda a: a.level)
        timeframe = {
            5: "Before next flight -- ground the aircraft",
            4: "Within 10 flight hours",
            3: "Within 50 flight hours",
        }.get(worst.level, "At next scheduled maintenance")

        # Whichever is worse: what a limit says, or what health says.
        alert_sev = self._SEVERITY.get(worst.level, "INFO")
        rank = {"INFO": 1, "ADVISORY": 2, "CAUTION": 3, "WARNING": 4, "EMERGENCY": 5}
        severity = alert_sev if rank[alert_sev] >= band_rank else band_sev

        adv = MaintenanceAdvisory(
            severity=severity,
            message=worst.legend,
            recommended_action=worst.advisory or "Investigate before next flight.",
            time_to_action=timeframe,
            # Fault codes are the rule ids: they are stable, greppable, and map
            # one-to-one onto the maintenance log written by edge_buffer.
            fault_codes=sorted({a.rule_id for a in alerts.active}),
            source="rules",
        )
        self.state.advisory = adv

    def _band_action(self, band: str) -> str:
        """The action the configured band table already prescribes.

        The band's ``instruction``, not its ``action``. The action is a machine
        token the advisory logic branches on -- "maintain_within_25h" -- and
        stripping its underscores does not make it English: the console was
        displaying "Recommended action: monitor" to an operator, which is a
        word, not an instruction they can carry out. The sentence lives on the
        band in the threshold file beside the token it translates.
        """
        for b in self.thresholds["health"]["chi_bands"]:
            if str(b["label"]) == band:
                if b.get("instruction"):
                    return str(b["instruction"])
                return str(b["action"]).replace("_", " ")
        return "Monitor."

    @staticmethod
    def _band_timeframe(rank: int) -> str:
        return {
            2: "Monitor closely; review at next inspection",
            3: "Within 25 flight hours",
            4: "Before next flight",
            5: "Ground the aircraft",
        }.get(rank, "At next scheduled maintenance")

    def refresh_advisory(self) -> None:
        """Recompute the advisory after predictions have been applied.

        Health arrives via :meth:`apply_predictions`, which runs AFTER
        :meth:`sync`, so the advisory computed during sync has not seen it yet.
        """
        self._sync_advisory()

    def _sync_history(self, dt_s: float) -> None:
        h, r = self.state.history, self.state.reported
        limits = self.thresholds["parameters"]

        def bump(attr: str, m: Measurement) -> None:
            if m.usable and m.value is not None:
                cur = getattr(h, attr)
                if cur is None or m.value > cur:
                    setattr(h, attr, m.value)

        bump("max_cht_recorded", r.cht_max)
        bump("max_coolant_recorded", r.coolant_temperature)
        bump("max_egt_recorded", r.egt_max)
        bump("max_rpm_recorded", r.rpm)
        if r.vibration.rms_total is not None:
            if h.max_vibration_recorded is None or r.vibration.rms_total > h.max_vibration_recorded:
                h.max_vibration_recorded = r.vibration.rms_total

        # Time spent above the max-continuous rating is a usage-monitoring
        # quantity in its own right: the take-off rating is time-limited, so
        # accumulating it matters for the maintenance record.
        max_cont = float(limits["rpm"]["normal_max"])
        if r.rpm.usable and r.rpm.value is not None and r.rpm.value > max_cont:
            h.time_above_max_continuous_s += dt_s

        if r.rpm.usable and r.rpm.value is not None and r.rpm.value > 1200.0:
            self.state.metadata.total_flight_hours += dt_s / 3600.0
            h.hours_since_inspection += dt_s / 3600.0

        self._count_cycles()

    def _count_cycles(self) -> None:
        """Start-stop and thermal cycles.

        PRD Part 2 section 12 defines one cycle as one start-stop. Both counts
        use a hysteresis band rather than a single threshold, because rpm and
        head temperature both hover around any fixed line and a bare crossing
        test would add a cycle for every noise excursion -- inflating consumed
        life on an engine that never actually stopped.

        Thermal cycles are counted separately from start-stop cycles because
        they measure different damage. A hot restart consumes a start-stop
        cycle while doing almost nothing to the head; a cold soak followed by
        a climb to take-off power is the one that fatigues it.
        """
        h, r = self.state.history, self.state.reported

        rpm = r.rpm.value if r.rpm.usable else None
        if rpm is not None:
            if not self._was_running and rpm > 1500.0:
                self._was_running = True
                self.state.metadata.total_cycles += 1
            elif self._was_running and rpm < 500.0:
                self._was_running = False

        cht = r.cht_max.value if r.cht_max.usable else None
        if cht is not None:
            if not self._thermally_hot and cht > 90.0:
                self._thermally_hot = True
                h.thermal_cycles += 1
            elif self._thermally_hot and cht < 50.0:
                self._thermally_hot = False

    # -- public --------------------------------------------------------------

    def sync(
        self,
        telemetry: Telemetry,
        *,
        derived: dict[str, float] | None = None,
        physics: Any | None = None,
        alerts: Any | None = None,
    ) -> TwinState:
        """Advance the twin by one telemetry frame."""
        dt_s = 0.0 if self._last_t is None else max(0.0, telemetry.t_s - self._last_t)
        self._last_t = telemetry.t_s

        self._sync_reported(telemetry)
        self._sync_timing_deviation(derived or {})
        if physics is not None:
            self._sync_simulated(physics)
        self._sync_residuals()
        if alerts is not None:
            self._sync_alerts(alerts)
            self._sync_advisory()
        self._check_physics_constraints()
        self._sync_history(dt_s)

        self.state.sync_count += 1
        self.state.last_sync_utc = datetime.now(UTC)
        if self.state.metadata.lifecycle == "CREATED":
            self.state.metadata.lifecycle = "ACTIVE"
        return self.state

    def apply_predictions(
        self,
        *,
        health: HealthIndices | None = None,
        rul: RemainingLife | None = None,
        fault_probability: dict[str, float] | None = None,
        degradation_factors: DegradationEstimate | dict[str, float] | None = None,
        model_confidence: float | None = None,
    ) -> None:
        """Fold in the AI layer's output.

        Separate from :meth:`sync` because the AI runs at a slower cadence than
        telemetry -- PRD Part 1 section 6.2 puts RUL at every 30 s and fault
        probabilities at every 5 s, against 10 Hz telemetry.
        """
        p = self.state.predicted
        p.timestamp = datetime.now(UTC)
        if health is not None:
            p.health = health
        if rul is not None:
            p.rul = rul
        if fault_probability is not None:
            p.fault_probability = {**dict.fromkeys(FAULT_KEYS, 0.0), **fault_probability}
        if degradation_factors is not None:
            p.degradation_factors = (
                degradation_factors
                if isinstance(degradation_factors, DegradationEstimate)
                # Extra keys are dropped rather than rejected: the simulator's
                # DegradationFactors carries three auxiliary physical
                # quantities (viscosity ratio, bearing clearance, injector
                # flow variance) that are inputs to the physics model, not
                # health factors, and the estimator may hand the whole struct.
                else DegradationEstimate(**{
                    k: v for k, v in degradation_factors.items()
                    if k in DegradationEstimate.model_fields
                })
            )
        if model_confidence is not None:
            p.model_confidence = model_confidence
            floor = float(self.thresholds["detectors"]["confidence_floor"])
            p.rule_based_fallback = model_confidence < floor

    def apply_fault_evidence(
        self,
        *,
        network: dict[str, float] | None,
        source: str,
        rule_levels: dict[str, Any] | None = None,
    ) -> None:
        """What each fault mode is believed to be, and on what evidence.

        The probabilities are the TRAINED fault head's own output. They used to
        be the rule level times 0.20 (audit 15 Sep, P1-1): a number with the
        shape of a probability and none of its meaning -- a YELLOW alert became
        0.60 whatever the evidence behind it, and nothing measured said 0.60 of
        anything. An operator reading 0.60 was reading arithmetic on an alert
        level.

        When no network is scoring there is no probability, and the source says
        so instead of a manufactured figure standing in for one. What the rules
        saw is kept beside it, as the alert levels they actually are.
        """
        p = self.state.predicted
        if network is None:
            p.fault_probability = dict.fromkeys(FAULT_KEYS, 0.0)
        else:
            p.fault_probability = {
                k: float(min(max(network.get(k, 0.0), 0.0), 1.0)) for k in FAULT_KEYS
            }
        p.fault_probability_source = source
        p.rule_fault_levels = {
            str(mode): int(level) for mode, level in (rule_levels or {}).items()
            if str(mode) in FAULT_KEYS
        }


def create_twin(
    twin_id: str,
    *,
    aircraft_id: str = "",
    engine_key: str = "rotax_915is",
    total_flight_hours: float = 0.0,
    installation_date: datetime | None = None,
) -> tuple[TwinState, TwinSynchroniser]:
    """Create a twin and its synchroniser for one engine.

    Engine identity, TBO and both TBO clocks come from the engine
    configuration, so registering a twin for a different engine needs no code
    change (PRD Part 1 section 2.4).
    """
    engine = config.load_engine(engine_key)
    ratings = engine["ratings"]
    state = TwinState(
        metadata=TwinMetadata(
            twin_id=twin_id,
            aircraft_id=aircraft_id,
            engine_type=str(engine["identity"]["engine_type"]),
            engine_key=engine_key,
            installation_date=installation_date,
            total_flight_hours=total_flight_hours,
            tbo_hours=float(ratings["tbo_hours"]),
            tbo_calendar_years=float(ratings.get("tbo_calendar_years", 15.0)),
        )
    )
    return state, TwinSynchroniser(state, engine_key=engine_key)
