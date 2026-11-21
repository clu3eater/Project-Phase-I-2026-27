"""Degradation pathways and fault injection -- PRD Part 1 section 5.2, 5.3.

Six physical degradation mechanisms, each with a rate law, an effect on the
physics model, and a maintenance threshold. Plus a fault-injection API used by
the synthetic data generator (PRD Part 0 section 0.5) and by the scripted demo
(PRD Part 0 section 0.9).

DESIGN POINT -- why degradation lives here and not in the AI layer.
The AI layer must *estimate* these factors from sensor data. If the estimator
and the ground truth shared code, every metric would be circular. This module
is the ground-truth generator: it is used by the simulator and by the training
data generator, and it is NOT imported by anything in ``layer3_ai`` except the
offline evaluation script that compares estimates against truth.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum

import numpy as np


class Pathway(StrEnum):
    """The six degradation pathways of PRD Part 1 section 5.2."""

    COOLING = "cooling"
    OIL_THERMAL = "oil_thermal"
    COMBUSTION_DEPOSITS = "combustion_deposits"
    INJECTOR_FOULING = "injector_fouling"
    BEARING_WEAR = "bearing_wear"
    TURBOCHARGER = "turbocharger"


class FaultMode(StrEnum):
    """The eight faults the problem statement requires (PRD Part 2 section 10)."""

    MISFIRE = "misfire"
    INJECTOR_ABNORMAL = "injector_abnormal"
    COOLING_DEGRADATION = "cooling_degradation"
    LUBRICATION_ISSUE = "lubrication_issue"
    SENSOR_DRIFT = "sensor_drift"
    COMBUSTION_INSTABILITY = "combustion_instability"
    OVERHEATING_TREND = "overheating_trend"
    ABNORMAL_VIBRATION = "abnormal_vibration"


FAULT_CLASS_ORDER: tuple[FaultMode, ...] = (
    FaultMode.MISFIRE,
    FaultMode.INJECTOR_ABNORMAL,
    FaultMode.COOLING_DEGRADATION,
    FaultMode.LUBRICATION_ISSUE,
    FaultMode.SENSOR_DRIFT,
    FaultMode.COMBUSTION_INSTABILITY,
    FaultMode.OVERHEATING_TREND,
    FaultMode.ABNORMAL_VIBRATION,
)


@dataclass
class DegradationFactors:
    """Health of each degrading subsystem: 1.0 = new, lower = degraded.

    These are exactly the ``degradation_factors`` of the twin's predicted state
    (PRD Part 1 section 6.1), which is why the field names match the schema.
    """

    cooling_efficiency: float = 1.0
    oil_quality: float = 1.0
    combustion_efficiency: float = 1.0
    injector_condition: float = 1.0
    bearing_condition: float = 1.0
    turbocharger_condition: float = 1.0

    # Heat rejection from the coolant loop to ambient air -- a BLOCKED
    # RADIATOR or lost cooling airflow, as distinct from ``cooling_efficiency``
    # which is the head-to-coolant path inside the engine.
    #
    # The two produce different signatures and that is the entire point of
    # keeping them apart. Scale in the jacket raises CHT while the thermostat
    # holds coolant temperature steady, so CHT-minus-coolant widens. A blocked
    # radiator raises the whole loop, so CHT and coolant rise TOGETHER and the
    # difference between them barely moves. Without this second factor the two
    # faults are physically identical and no classifier can separate them.
    cooling_airflow: float = 1.0

    # Battery state of health. Closes gap G4: without it the electrical index
    # had to renormalise its two remaining terms, handing every engine a free
    # 0.2, and PRD Part 2 s9.2 P8's third term was unimplementable.
    battery_health: float = 1.0

    # Derived / auxiliary physical quantities the physics model consumes.
    oil_viscosity_ratio: float = 1.0  # mu(t)/mu_0
    # Absolute internal resistance in ohms. Like bearing clearance this is a
    # dimension rather than a 0-1 score, so it is seeded from the engine
    # configuration rather than defaulting to a meaningless zero.
    battery_internal_resistance_ohm: float = 0.0
    bearing_clearance_mm: float = 0.0  # absolute, set from the engine config
    injector_flow_variance: float = 0.0  # sigma^2 of per-cylinder fuel split

    @classmethod
    def as_new(cls, engine: dict) -> DegradationFactors:
        """As-new factors for a specific engine.

        Bearing clearance is an ABSOLUTE dimension, so unlike the other fields
        it has no meaningful "1.0 = new" default -- it must come from the engine
        definition. Constructing a bare ``DegradationFactors()`` leaves it at
        0.0, which the oil-pressure model reads as a seized-tight bearing and
        which pinned modelled oil pressure at the relief valve.
        """
        return cls(
            bearing_clearance_mm=float(
                engine["degradation"]["bearing_wear"]["design_clearance_mm"]
            )
        )

    def as_dict(self) -> dict[str, float]:
        return asdict(self)

    def worst(self) -> tuple[str, float]:
        """The most degraded subsystem -- drives the maintenance advisory."""
        keys = (
            "cooling_efficiency",
            "oil_quality",
            "combustion_efficiency",
            "injector_condition",
            "bearing_condition",
            "turbocharger_condition",
        )
        k = min(keys, key=lambda x: getattr(self, x))
        return k, getattr(self, k)


@dataclass
class InjectedFault:
    """A fault scheduled to appear at a point in the engine's life.

    ``onset_hours`` is when it starts; ``severity`` is the final magnitude in
    [0, 1]; ``ramp_hours`` is how long it takes to reach that magnitude (0 for
    a step fault such as a failed spark plug, large for a wear-out).
    """

    mode: FaultMode
    onset_hours: float
    severity: float
    ramp_hours: float = 10.0
    cylinder: int | None = None  # 1-based; None = affects all cylinders
    active: bool = True
    # SENSOR_DRIFT only: which instrument is drifting, and in which direction.
    #
    # A transducer fault afflicts ONE instrument, and which one varies. Fixing
    # the affected channels made the class both artificially easy and
    # systematically confusable: every sensor-drift instance raised CHT by the
    # same 9 degC, so the class collided head-on with cooling_degradation --
    # measured, 84 % of the cooling head's false positives were sensor-drift
    # windows, and cooling collapsed to 0.112 F1.
    channel: str | None = None
    drift_sign: float = 1.0

    def magnitude_at(self, hours: float) -> float:
        """Current severity, 0 before onset, ramping to ``severity``."""
        if not self.active or hours < self.onset_hours:
            return 0.0
        if self.ramp_hours <= 0.0:
            return self.severity
        frac = min(1.0, (hours - self.onset_hours) / self.ramp_hours)
        return self.severity * frac


# How much each fault ACCELERATES the wear pathway it acts on, per unit of
# fault magnitude. A fault is not just a step change in a health factor: a
# fouling cooling jacket keeps fouling, and a failing bearing keeps wearing.
#
# Without this the clamps in _apply_faults were the only effect a fault had,
# and a clamp cannot end an engine's life -- measured, a severity-1.0 fault
# left the composite health index at 0.77-0.89 against a 0.60 maintenance
# threshold, so EVERY failure in a synthetic fleet came from baseline wear near
# TBO and the injected faults were decorative. See docs/PRD_DEVIATIONS.md
# DEV-45.
_FAULT_ACCELERATION: dict[FaultMode, dict[Pathway, float]] = {
    FaultMode.COOLING_DEGRADATION: {Pathway.COOLING: 7.0},
    # A small COOLING contribution only: the mode's primary effect is the
    # cooling_airflow clamp in _apply_faults, which raises the WHOLE loop and
    # is what separates it from COOLING_DEGRADATION. Sharing the cooling
    # pathway at equal weight made the two indistinguishable.
    FaultMode.OVERHEATING_TREND: {Pathway.COOLING: 1.5},
    # Degraded oil does not only score badly, it wears the bearings it is
    # supposed to protect.
    FaultMode.LUBRICATION_ISSUE: {Pathway.OIL_THERMAL: 5.0, Pathway.BEARING_WEAR: 3.0},
    FaultMode.INJECTOR_ABNORMAL: {Pathway.INJECTOR_FOULING: 9.0},
    FaultMode.ABNORMAL_VIBRATION: {Pathway.BEARING_WEAR: 9.0},
    # Incomplete combustion is precisely what forms chamber deposits, so these
    # two carry a high multiplier on that pathway rather than a token one.
    FaultMode.COMBUSTION_INSTABILITY: {Pathway.COMBUSTION_DEPOSITS: 12.0},
    # A misfiring cylinder also washes raw fuel past the rings, and fuel
    # dilution of the oil is a well-known consequence -- so misfire attacks the
    # lubricant as well as the chamber.
    # Deliberately NOT coupled to INJECTOR_FOULING. It was, and that made
    # misfire and injector_abnormal share their dominant degradation signature:
    # measured, the classifier scored misfire 0.905 F1 while injector_abnormal
    # collapsed to 0.190, because it was calling one the other. Misfire has its
    # own distinguishing signature already -- a single cylinder's EGT dropping
    # 28 % with an rpm droop (engine_sim.py) -- and it does not need to borrow
    # the injector pathway to be detectable.
    FaultMode.MISFIRE: {
        Pathway.COMBUSTION_DEPOSITS: 10.0,
        Pathway.OIL_THERMAL: 4.0,
    },
}


# ==============================================================================
# FAULT ONSET: A WEAR-OUT HAZARD, NOT A COIN FLIP
#
# THE DEFECT THIS REPLACES
# ------------------------
# Onset was `rng.uniform(15.0, 400.0)` -- drawn once, before the engine ever
# ran, INDEPENDENT of its condition. A pristine engine and a badly worn one were
# equally likely to develop a fault in the next hour.
#
# In reliability terms that is a CONSTANT hazard: Weibull with shape beta = 1,
# the flat middle of the bathtub curve, which describes RANDOM failures --
# debris, lightning, a manufacturing escape. Wear-out is the rising right-hand
# region, beta > 1, where hazard grows with accumulated damage. Published shape
# parameters put rolling-element bearings and abrasive wear at beta 1.5-2.5,
# material fatigue at 2-4, corrosion at 3-5. None of them is 1.
#
# WHY IT MATTERS BEYOND REALISM
# -----------------------------
# The problem statement asks the system to move past monitoring that "indicates
# failures only after abnormality has already occurred", and to deliver
# "predicting probable failures BEFORE occurrence" from "failure/degradation
# logic", while demonstrating "reliability engineering".
#
# If onset is independent of condition then no observation of the engine can
# anticipate it, and prediction-before-occurrence is impossible BY CONSTRUCTION
# -- not because a model is weak. Measured on the old generator: an oracle given
# the simulator's own hidden wear state AND every future fault still could not
# beat 0.75 sigma on RUL, and the sensor models sat at 0.80. The ceiling was the
# fault schedule, not the estimator.
#
# There was also a one-way causality: `_FAULT_ACCELERATION` lets a fault
# accelerate wear, but wear did not raise the probability of a fault. On a real
# engine that is a loop.
#
# THE MODEL
# ---------
# Cox proportional hazards with the degradation state as a time-varying
# covariate -- the standard formulation for condition-based reliability, in
# which degradation "does not directly lead to system failures, but increases
# the hazard rate":
#
#     h(t) = h0 * exp(gamma * d(t))
#
# `d(t)` is accumulated damage in [0, 1] on the pathway the mode acts through
# (`_FAULT_ACCELERATION`), so a bearing fault becomes likelier on a worn
# bearing and an injector fault on a fouled injector. Over a sortie of length
# dt the onset probability is `1 - exp(-h*dt)`.
#
# WHAT IS DELIBERATELY LEFT AT beta = 1
# -------------------------------------
# SENSOR_DRIFT. A transducer failing is an ELECTRONIC event, not mechanical
# wear-out, and a constant hazard is the correct model for it. Making every
# mode condition-dependent would be the same error in the opposite direction.
# ==============================================================================

# Hazard ratio between a fully-damaged pathway and an as-new one. exp(gamma).
# 20x is a strong but unexceptional covariate effect in the condition-based
# reliability literature, and it is the one number here chosen for its size
# rather than derived -- recorded as such rather than presented as physics.
FAULT_HAZARD_RATIO = 20.0

# Baseline hazard per flight hour for an as-new pathway. Calibrated so that the
# EXPRESSED fraction of dealt faults over a typical 600 h life stays close to
# the old generator's, and only their TIMING moves: what changes is when a
# fault arrives relative to condition, not how many arrive.
#
# 0.004 is the measured answer, not a guess. Swept over 10 engines against the
# old uniform-onset fleet, which fails 90 % with a 465 h median life:
#
#     h0 = 0.004   90 % failed   median life 531 h   median onset  99 h
#     h0 = 0.008   90 % failed   median life 356 h   median onset  39 h
#     h0 = 0.015   90 % failed   median life 356 h   median onset  32 h
#
# All three hold the 90 % failure rate, which is what the calibration is for --
# it fixes the overall failure statistics so the only thing that changes
# between the two fleets is WHEN a fault arrives relative to condition. 0.004
# is chosen because it also keeps median life closest to the old fleet.
#
# The value it replaces, 0.002, predates the sweep and was never one of the
# tested settings: the calibration answered the question and the answer had not
# been written back. It went unnoticed because the sweep that chose it was the
# same run that exposed DEV-201, where this constant was wired to nothing.
FAULT_BASE_HAZARD_PER_HOUR = 0.004

# Modes whose onset is genuinely random rather than wear-driven.
CONSTANT_HAZARD_MODES = frozenset({FaultMode.SENSOR_DRIFT})

# Ramp time, in flight hours, by the PHYSICAL MECHANISM of each mode. The old
# generator drew one log-uniform 0.5-300 h span -- a 600:1 range -- for all
# eight, which says a failed ignition coil and a coking injector progress
# alike. They do not.
FAULT_RAMP_HOURS: dict[FaultMode, tuple[float, float]] = {
    # An ignition coil or plug fails; the cylinder stops firing. Near-step.
    FaultMode.MISFIRE: (0.5, 8.0),
    # Deposit build-up on the pintle. Gradual fouling over hundreds of hours.
    FaultMode.INJECTOR_ABNORMAL: (40.0, 250.0),
    # Scale and fouling in the coolant jacket. Slower still.
    FaultMode.COOLING_DEGRADATION: (60.0, 300.0),
    # Spans a developing leak and slow contamination, so it keeps a wide range
    # -- but a narrower one than "anything at all".
    FaultMode.LUBRICATION_ISSUE: (10.0, 120.0),
    # A transducer drifts out of calibration gradually.
    FaultMode.SENSOR_DRIFT: (50.0, 300.0),
    # Mixture and ignition quality wander over tens of hours.
    FaultMode.COMBUSTION_INSTABILITY: (20.0, 150.0),
    # Named a TREND. Modelling it as a step contradicts the mode itself.
    FaultMode.OVERHEATING_TREND: (80.0, 350.0),
    # Bearing spall propagation, from first detectable damage to failure.
    FaultMode.ABNORMAL_VIBRATION: (20.0, 150.0),
}

# Damage on the pathway a mode acts through. `1 - factor` for a 0-1 health
# score, so 0.0 is as-new and 1.0 is destroyed.
_PATHWAY_FACTOR: dict[Pathway, str] = {
    Pathway.COOLING: "cooling_efficiency",
    Pathway.OIL_THERMAL: "oil_quality",
    Pathway.COMBUSTION_DEPOSITS: "combustion_efficiency",
    Pathway.INJECTOR_FOULING: "injector_condition",
    Pathway.BEARING_WEAR: "bearing_condition",
    Pathway.TURBOCHARGER: "turbocharger_condition",
}


def pathway_damage(factors: "DegradationFactors", mode: FaultMode) -> float:
    """Accumulated damage in [0, 1] on the pathway `mode` acts through.

    The covariate of the hazard model. Uses the pathway the mode ALREADY
    accelerates in `_FAULT_ACCELERATION`, so the coupling runs both ways
    through one table rather than two that could disagree; where a mode names
    several, the one it drives hardest is the precursor.
    """
    paths = _FAULT_ACCELERATION.get(mode)
    if not paths:
        return 0.0
    pathway = max(paths, key=paths.get)
    field = _PATHWAY_FACTOR.get(pathway)
    if field is None:
        return 0.0
    value = float(getattr(factors, field, 1.0))
    # combustion_efficiency is floored at 0.80 in the model, so its raw value
    # never spans 0-1; normalise over the range it can actually cross, the same
    # correction DEV-45 made for the health index.
    if field == "combustion_efficiency":
        return float(np.clip((0.98 - value) / (0.98 - 0.80), 0.0, 1.0))
    return float(np.clip(1.0 - value, 0.0, 1.0))


def onset_probability(
    damage: float,
    dt_hours: float,
    *,
    mode: FaultMode | None = None,
    base_hazard: float | None = None,
    hazard_ratio: float | None = None,
) -> float:
    """P(a pending fault starts during the next `dt_hours`).

    `h = h0 * exp(gamma * damage)` integrated over the interval. Returns the
    constant-hazard result for modes in `CONSTANT_HAZARD_MODES`, whose failure
    is electronic rather than mechanical.
    """
    # RESOLVED AT CALL TIME, not bound as a default argument.
    #
    # `def f(h=FAULT_BASE_HAZARD_PER_HOUR)` captures the value ONCE, when the
    # module is imported, so reassigning the module constant afterwards changes
    # nothing -- the knob looks tunable and is inert. Found by a calibration
    # sweep that returned byte-identical fleets for three different hazard
    # values, which is impossible unless the value is never read.
    if base_hazard is None:
        base_hazard = FAULT_BASE_HAZARD_PER_HOUR
    if hazard_ratio is None:
        hazard_ratio = FAULT_HAZARD_RATIO

    if dt_hours <= 0.0:
        return 0.0
    if mode is not None and mode in CONSTANT_HAZARD_MODES:
        h = base_hazard
    else:
        gamma = math.log(max(hazard_ratio, 1.0 + 1e-9))
        h = base_hazard * math.exp(gamma * float(np.clip(damage, 0.0, 1.0)))
    return float(1.0 - math.exp(-h * float(dt_hours)))


@dataclass
class DegradationEngine:
    """Advances the six pathways over engine life and applies injected faults.

    Usage::

        deg = DegradationEngine(engine_config)
        deg.inject(InjectedFault(FaultMode.COOLING_DEGRADATION, 120.0, 0.8, 40.0))
        deg.advance(dt_hours=0.1, oil_temp_c=98.0, env_multipliers={"cooling": 1.5})
        factors = deg.factors
    """

    engine: dict
    hours: float = 0.0
    rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng(0))
    factors: DegradationFactors = field(default_factory=DegradationFactors)
    faults: list[InjectedFault] = field(default_factory=list)
    # Per-engine manufacturing spread on degradation rates. PRD Part 0
    # section 0.5 requires randomised physics parameters per engine so that a
    # network cannot memorise one trajectory.
    rate_scale: dict[str, float] = field(default_factory=dict)
    # Scheduled maintenance actually performed on this engine.
    oil_changes: int = 0
    hours_since_oil_change: float = 0.0

    def __post_init__(self) -> None:
        cfg = self.engine["degradation"]
        if not self.rate_scale:
            self.rate_scale = {p.value: 1.0 for p in Pathway}
        self.factors.bearing_clearance_mm = float(cfg["bearing_wear"]["design_clearance_mm"])
        self._clearance_0 = self.factors.bearing_clearance_mm
        self._r_batt_0 = float(
            self.engine["electrical"]["battery_internal_resistance_new_ohm"]
        )
        self.factors.battery_internal_resistance_ohm = self._r_batt_0

    # -- setup ---------------------------------------------------------------

    def randomise_rates(self, spread: float = 0.35) -> None:
        """Apply a per-engine manufacturing spread to every degradation rate.

        Log-normal so that rates stay positive and the spread is multiplicative
        (a 35 % spread means some engines degrade 1.35x faster, others 0.74x).
        """
        for p in Pathway:
            self.rate_scale[p.value] = float(math.exp(self.rng.normal(0.0, spread)))

    def inject(self, fault: InjectedFault) -> None:
        self.faults.append(fault)

    def arm_pending_faults(self, hours: float, dt_hours: float) -> list[FaultMode]:
        """Decide whether any PENDING fault starts, given the engine's damage.

        A fault carrying `onset_hours = inf` has been dealt to this engine but
        not yet scheduled: the generator no longer picks a time in advance.
        Each interval it is offered a draw against the wear-out hazard of the
        pathway it acts through, so a worn engine develops faults sooner than a
        healthy one -- which is what makes "predict failures BEFORE occurrence"
        possible at all, and what the old constant-hazard schedule forbade.

        Returns the modes that fired, for the caller to log. Faults that
        already have a finite onset are left alone, so an explicitly scheduled
        fault -- a test, a demo, a replayed incident -- still behaves exactly as
        it was written.
        """
        fired = []
        for fault in self.faults:
            if not fault.active or math.isfinite(fault.onset_hours):
                continue
            damage = pathway_damage(self.factors, fault.mode)
            p = onset_probability(damage, dt_hours, mode=fault.mode)
            if self.rng.random() < p:
                fault.onset_hours = float(hours)
                fired.append(fault.mode)
        return fired

    def pending_faults(self) -> list[InjectedFault]:
        """Dealt but not yet started -- awaiting the hazard draw."""
        return [f for f in self.faults
                if f.active and not math.isfinite(f.onset_hours)]

    def clear_faults(self) -> None:
        self.faults.clear()

    def active_faults(self) -> list[tuple[FaultMode, float, int | None]]:
        """(mode, magnitude, cylinder) for every currently-expressed fault."""
        out = []
        for f in self.faults:
            mag = f.magnitude_at(self.hours)
            if mag > 0.0:
                out.append((f.mode, mag, f.cylinder))
        return out

    def fault_label_vector(self) -> np.ndarray:
        """Ground-truth multi-label vector over FAULT_CLASS_ORDER."""
        v = np.zeros(len(FAULT_CLASS_ORDER), dtype=float)
        for mode, mag, _ in self.active_faults():
            v[FAULT_CLASS_ORDER.index(mode)] = mag
        return v

    # -- time advance ---------------------------------------------------------

    def advance(
        self,
        dt_hours: float,
        *,
        oil_temp_c: float = 95.0,
        cht_max_c: float = 175.0,
        env_multipliers: dict[str, float] | None = None,
    ) -> DegradationFactors:
        """Advance all six pathways by ``dt_hours`` of operation.

        Wear rates are not constant: they depend on how hard the engine is
        being worked. Oil breakdown is Arrhenius-like in oil temperature,
        deposit formation rises with combustion temperature, and the
        environmental profile supplies a further multiplier (salt, heat, cold).
        """
        if dt_hours <= 0.0:
            return self.factors

        cfg = self.engine["degradation"]
        env = env_multipliers or {}
        self.hours += dt_hours
        self.hours_since_oil_change += dt_hours

        accel = self._fault_acceleration()

        def rate(pathway: Pathway, base: float) -> float:
            return (
                base
                * self.rate_scale.get(pathway.value, 1.0)
                * env.get(pathway.value, 1.0)
                * accel.get(pathway, 1.0)
            )

        # --- 1. Cooling system efficiency (scale build-up, pump wear) --------
        #     eta_cool(t) = eta_cool_0 * (1 - alpha * t)
        # Scale deposition accelerates with metal temperature.
        alpha = rate(Pathway.COOLING, float(cfg["cooling"]["rate_per_flight_hour"]))
        cht_ref = float(cfg["cooling"].get("reference_cht_C", 105.0))
        thermal_accel = 1.0 + 0.010 * max(0.0, cht_max_c - cht_ref)
        self.factors.cooling_efficiency = max(
            0.30, self.factors.cooling_efficiency - alpha * thermal_accel * dt_hours
        )

        # --- 2. Oil thermal breakdown ---------------------------------------
        #     mu(t) = mu_0 * exp(beta * T_avg * t)
        beta = rate(Pathway.OIL_THERMAL, float(cfg["oil_thermal"]["beta_thermal_per_C_hr"]))
        # Reference the exponent to the nominal operating temperature so that an
        # engine run at its design point degrades at the configured rate and a
        # hot-running engine degrades faster.
        excess = max(0.0, oil_temp_c - 95.0)
        self.factors.oil_viscosity_ratio *= math.exp(
            beta * (1.0 + 0.05 * excess) * dt_hours
        )
        vis_limit = float(cfg["oil_thermal"]["viscosity_increase_limit"])
        vis_increase = self.factors.oil_viscosity_ratio - 1.0
        self.factors.oil_quality = float(np.clip(1.0 - vis_increase / vis_limit, 0.0, 1.0))

        # --- 3. Combustion chamber deposits ---------------------------------
        gamma = rate(
            Pathway.COMBUSTION_DEPOSITS, float(cfg["combustion_deposits"]["rate_per_flight_hour"])
        )
        eta0 = float(self.engine["thermodynamics"]["combustion"]["efficiency_new"])
        self.factors.combustion_efficiency = max(
            0.80, self.factors.combustion_efficiency - gamma * dt_hours / eta0
        )

        # --- 4. Injector / carburettor fouling -------------------------------
        #     sigma^2(t) = sigma^2_0 + delta * t
        delta = rate(
            Pathway.INJECTOR_FOULING, float(cfg["injector_fouling"]["variance_rate_per_hour"])
        )
        self.factors.injector_flow_variance += delta * dt_hours
        cv_limit = float(cfg["injector_fouling"]["cv_maintenance_threshold"])
        # Convert variance in (L/hr)^2 to a coefficient of variation about a
        # nominal 10 L/hr cruise flow, then to a 0-1 condition index.
        cv = math.sqrt(max(self.factors.injector_flow_variance, 0.0)) / 10.0
        self.factors.injector_condition = float(np.clip(1.0 - cv / cv_limit, 0.0, 1.0))

        # --- 5. Bearing wear -------------------------------------------------
        #     C(t) = C_0 + kappa * t
        kappa = rate(
            Pathway.BEARING_WEAR, float(cfg["bearing_wear"]["clearance_rate_mm_per_hour"])
        )
        self.factors.bearing_clearance_mm += kappa * dt_hours
        mult = float(cfg["bearing_wear"]["maintenance_multiple"])
        growth = (self.factors.bearing_clearance_mm - self._clearance_0) / self._clearance_0
        self.factors.bearing_condition = float(np.clip(1.0 - growth / (mult - 1.0), 0.0, 1.0))

        # --- 5b. Battery ageing ----------------------------------------------
        # A lead-acid or Li-ion pack ages on TWO clocks, and both matter: cycles
        # (each start-stop draws a large current) and calendar time, which is
        # why a battery left on a shelf still dies. Internal resistance is the
        # quantity that actually rises, and it is what an aircraft can measure.
        batt = cfg.get("battery", {})
        per_cycle = float(batt.get("resistance_rise_per_cycle", 2.0e-5))
        per_hour = float(batt.get("resistance_rise_per_hour", 1.5e-6))
        eol_multiple = float(batt.get("end_of_life_resistance_multiple", 2.0))
        # Cycles are counted by the twin; here the hours clock advances and the
        # cycle contribution arrives through record_start_cycle().
        self.factors.battery_internal_resistance_ohm += per_hour * dt_hours
        growth = (
            self.factors.battery_internal_resistance_ohm - self._r_batt_0
        ) / max(self._r_batt_0, 1e-12)
        self.factors.battery_health = float(
            np.clip(1.0 - growth / max(eol_multiple - 1.0, 1e-9), 0.0, 1.0)
        )
        del per_cycle

        # --- 6. Turbocharger efficiency --------------------------------------
        lam = rate(Pathway.TURBOCHARGER, float(cfg["turbocharger"]["rate_per_flight_hour"]))
        self.factors.turbocharger_condition = max(
            0.40, self.factors.turbocharger_condition - lam * dt_hours
        )

        self._service_oil(cfg)

        # --- injected faults override / accelerate the natural pathways ------
        # Deliberately AFTER the oil change: a scheduled service restores the
        # oil, but it does not repair the thing that is contaminating it. A
        # lubrication fault therefore survives the change, which is exactly the
        # signature that separates a real fault from oil that is merely due.
        self._apply_faults()
        return self.factors

    def _service_oil(self, cfg: dict) -> None:
        """Scheduled oil and filter change [MML 05-20-00].

        Oil is a CONSUMABLE, not a life-limited part. Modelling its viscosity
        rise without ever changing it made oil the life-limiting item on every
        engine at around 220 h -- a fifth of TBO -- and the resulting synthetic
        fleet would have taught a network that engines die of dirty oil.

        Only the natural accumulation is reset. Bearing wear already caused by
        running on degraded oil is permanent, as it is on a real engine.
        """
        interval = float(cfg["oil_thermal"].get("change_interval_hours", 0.0))
        if interval <= 0.0 or self.hours_since_oil_change < interval:
            return
        self.hours_since_oil_change = 0.0
        self.oil_changes += 1
        self.factors.oil_viscosity_ratio = 1.0
        self.factors.oil_quality = 1.0

    def record_start_cycle(self) -> None:
        """One engine start. The largest single current draw a battery sees.

        Called by the twin's cycle counter rather than inferred here, so there
        is one definition of what a start-stop cycle is.
        """
        cfg = self.engine["degradation"].get("battery", {})
        self.factors.battery_internal_resistance_ohm += float(
            cfg.get("resistance_rise_per_cycle", 2.0e-5)
        )

    def _fault_acceleration(self) -> dict[Pathway, float]:
        """Wear-rate multiplier per pathway from every currently-active fault.

        Contributions add, so two faults attacking the same pathway compound
        rather than the stronger one simply winning.
        """
        out: dict[Pathway, float] = {}
        for mode, mag, _cyl in self.active_faults():
            for pathway, gain in _FAULT_ACCELERATION.get(mode, {}).items():
                out[pathway] = out.get(pathway, 1.0) + gain * mag
        return out

    def _apply_faults(self) -> None:
        """Map injected faults onto the degradation factors.

        A fault is not a separate universe from wear: a cooling-degradation
        fault *is* an accelerated cooling pathway. Modelling it this way means
        the estimator sees a physically consistent picture rather than an
        artificial signal stapled onto healthy data.
        """
        for f in self.faults:
            mag = f.magnitude_at(self.hours)
            if mag <= 0.0:
                continue
            if f.mode is FaultMode.COOLING_DEGRADATION:
                self.factors.cooling_efficiency = min(
                    self.factors.cooling_efficiency, 1.0 - 0.55 * mag
                )
            elif f.mode is FaultMode.LUBRICATION_ISSUE:
                self.factors.oil_quality = min(self.factors.oil_quality, 1.0 - 0.70 * mag)
                self.factors.oil_viscosity_ratio = max(
                    self.factors.oil_viscosity_ratio, 1.0 + 0.35 * mag
                )
            elif f.mode is FaultMode.INJECTOR_ABNORMAL:
                # Damage the DEPOSIT, not the index read off it. Injector
                # condition is recomputed from injector_flow_variance on every
                # step, so a clamp here vanished the moment the fault was
                # cleared and a fouled engine healed itself -- measured 0.33 to
                # 0.98 in a single step, and the console's remaining life rose
                # with it. Fouling does not un-foul. The variance the condition
                # is derived from is raised instead, and it only ever grows;
                # cleaning the injectors (A3) is what resets it.
                cv_limit = float(
                    self.engine["degradation"]["injector_fouling"]["cv_maintenance_threshold"])
                target = 1.0 - 0.75 * mag
                cv = cv_limit * (1.0 - target)
                self.factors.injector_flow_variance = max(
                    self.factors.injector_flow_variance, (cv * 10.0) ** 2
                )
                self.factors.injector_condition = min(
                    self.factors.injector_condition, target
                )
            elif f.mode is FaultMode.ABNORMAL_VIBRATION:
                self.factors.bearing_condition = min(
                    self.factors.bearing_condition, 1.0 - 0.65 * mag
                )
                self.factors.bearing_clearance_mm = max(
                    self.factors.bearing_clearance_mm,
                    self._clearance_0 * (1.0 + 1.0 * mag),
                )
            elif f.mode is FaultMode.COMBUSTION_INSTABILITY:
                self.factors.combustion_efficiency = min(
                    self.factors.combustion_efficiency, 1.0 - 0.10 * mag
                )
            elif f.mode is FaultMode.OVERHEATING_TREND:
                # Heat rejection to AIR is lost -- a blocked radiator or lost
                # cooling airflow. Distinct from COOLING_DEGRADATION above,
                # which attacks the head-to-coolant path inside the engine.
                #
                # This mode previously had NO implementation at all. The
                # comment here claimed engine_sim.py applied it; that file has
                # never contained a single reference to it, so one of the eight
                # fault modes the problem statement requires produced a label
                # and no physics. A classifier trained on it was being asked to
                # detect something that was not there. See DEV-53.
                # 0.75, not 0.60. At 0.60 the factor bottomed out at 0.46 --
                # above the 0.40 sub-index floor -- so a fully-blocked radiator
                # could never end an engine's life, and the mode had no RUL
                # signal to teach. A severely blocked radiator leaving a quarter
                # of design airflow is a realistic worst case.
                self.factors.cooling_airflow = min(
                    self.factors.cooling_airflow, 1.0 - 0.75 * mag
                )
            # MISFIRE and SENSOR_DRIFT act on the signal path rather than on
            # subsystem health: misfire in engine_sim.py where the per-cylinder
            # EGT and rpm droop are formed, sensor drift in the instrument
            # model. Neither belongs in a subsystem health factor.

    # -- maintenance -----------------------------------------------------------

    # The injected faults each action in thresholds.advisory.actions removes
    # when the work is done. A1 is an oil change and removes no fault: it
    # renews the oil and nothing that contaminates it (see _service_oil). A5
    # and A6 are INSPECTIONS, and put nothing right unless parts were replaced.
    MAINTENANCE_REMOVES = {
        "A1": (),
        "A2": (FaultMode.COOLING_DEGRADATION,),
        "A3": (FaultMode.INJECTOR_ABNORMAL,),
        "A4": (FaultMode.MISFIRE,),
        "A5": (FaultMode.ABNORMAL_VIBRATION,),
        "A6": (),
        "A7": FAULT_CLASS_ORDER,
    }
    INSPECTIONS = frozenset({"A5", "A6"})

    def perform_maintenance(self, action_id: str, *, repaired: bool = True) -> dict:
        """Apply a completed maintenance action to the engine's condition.

        Each job restores the pathway it physically renews and removes the
        faults it physically fixes, and nothing else: new spark plugs do not
        clean combustion deposits, and a cooling flush does not unblock a
        radiator. Wear already done elsewhere stays done, as on a real engine.
        Only faults that have started are removed; a fault dealt to the engine
        but not yet arrived is not prevented by replacing a part.

        Returns what was restored and which faults were removed, so the record
        of the work can say exactly that.
        """
        if action_id not in self.MAINTENANCE_REMOVES:
            raise ValueError(f"unknown maintenance action {action_id!r}")
        if action_id in self.INSPECTIONS and not repaired:
            return {"restored": [], "faults_removed": []}

        new = DegradationFactors.as_new(self.engine)
        restored: list[str] = []
        overhaul = action_id == "A7"
        if action_id == "A1" or overhaul:
            self.hours_since_oil_change = 0.0
            self.oil_changes += 1
            self.factors.oil_viscosity_ratio = new.oil_viscosity_ratio
            self.factors.oil_quality = new.oil_quality
            restored.append("oil_quality")
        if action_id == "A2" or overhaul:
            self.factors.cooling_efficiency = new.cooling_efficiency
            restored.append("cooling_efficiency")
        if action_id == "A3" or overhaul:
            self.factors.injector_flow_variance = new.injector_flow_variance
            self.factors.injector_condition = new.injector_condition
            restored.append("injector_condition")
        if action_id == "A5" or overhaul:
            self.factors.bearing_clearance_mm = self._clearance_0
            self.factors.bearing_condition = new.bearing_condition
            restored.append("bearing_condition")
        if action_id == "A6" or overhaul:
            self.factors.turbocharger_condition = new.turbocharger_condition
            restored.append("turbocharger_condition")
        if overhaul:
            self.factors.combustion_efficiency = new.combustion_efficiency
            self.factors.cooling_airflow = new.cooling_airflow
            restored += ["combustion_efficiency", "cooling_airflow"]

        remove = set(self.MAINTENANCE_REMOVES[action_id])
        removed: set[str] = set()
        for f in self.faults:
            started = math.isfinite(f.onset_hours) and f.onset_hours <= self.hours
            if f.active and started and f.mode in remove:
                f.active = False
                removed.add(str(f.mode))
        return {"restored": restored, "faults_removed": sorted(removed)}

    def maintenance_due(self) -> list[tuple[str, float, float]]:
        """(subsystem, current, threshold) for every factor past its limit."""
        cfg = self.engine["degradation"]
        checks = [
            (
                "cooling_efficiency",
                self.factors.cooling_efficiency,
                float(cfg["cooling"]["maintenance_threshold"]),
            ),
            (
                "combustion_efficiency",
                self.factors.combustion_efficiency,
                float(cfg["combustion_deposits"]["maintenance_threshold"]),
            ),
            ("oil_quality", self.factors.oil_quality, 0.0),
            ("injector_condition", self.factors.injector_condition, 0.0),
            ("bearing_condition", self.factors.bearing_condition, 0.0),
            (
                "turbocharger_condition",
                self.factors.turbocharger_condition,
                1.0 - float(cfg["turbocharger"]["boost_loss_threshold"]),
            ),
        ]
        return [(n, v, t) for n, v, t in checks if v <= t]

    def snapshot(self) -> DegradationFactors:
        return replace(self.factors)


# ---------------------------------------------------------------------------
# Stochastic fault scheduling for the synthetic data generator
# ---------------------------------------------------------------------------


def random_fault_schedule(
    rng: np.random.Generator,
    *,
    life_hours: float,
    n_cylinders: int = 4,
    max_faults: int = 3,
    p_no_fault: float = 0.15,
) -> list[InjectedFault]:
    """A randomised fault schedule for one virtual engine.

    PRD Part 0 section 0.5 requires stochastic faults at random times with
    random severities, so that the training set is not a single memorisable
    trajectory. A fraction of engines are left fault-free to give the detector
    genuine negatives across the whole life.
    """
    if rng.random() < p_no_fault:
        return []

    n = int(rng.integers(1, max_faults + 1))
    modes = list(FAULT_CLASS_ORDER)
    rng.shuffle(modes)
    out: list[InjectedFault] = []
    for mode in modes[:n]:
        onset = float(rng.uniform(0.15, 0.90) * life_hours)
        severity = float(rng.uniform(0.35, 1.0))
        # Step faults vs wear-out faults have very different ramps.
        if mode in (FaultMode.MISFIRE, FaultMode.SENSOR_DRIFT):
            ramp = float(rng.uniform(0.0, 5.0))
        else:
            ramp = float(rng.uniform(0.10, 0.45) * life_hours)
        cyl = int(rng.integers(1, n_cylinders + 1)) if rng.random() < 0.6 else None
        if mode in (
            FaultMode.COOLING_DEGRADATION,
            FaultMode.LUBRICATION_ISSUE,
            FaultMode.OVERHEATING_TREND,
        ):
            cyl = None  # these are engine-level, not per-cylinder
        out.append(
            InjectedFault(
                mode=mode,
                onset_hours=onset,
                severity=severity,
                ramp_hours=ramp,
                cylinder=cyl,
            )
        )
    return out
