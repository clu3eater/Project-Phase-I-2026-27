"""The shadow engine -- an as-new twin running alongside the real one.

This is the half of "virtual engine model synchronized with live engine data"
(problem statement section A) that the physics layer alone does not provide.
``layer2_physics`` can simulate an engine; it cannot by itself tell you whether
the engine on the aircraft is behaving like it should. That comparison needs a
SECOND model -- one that is deliberately kept healthy -- driven by the same
operating point as the real engine. The gap between them is the residual, and
the residual is what detects degradation hundreds of hours before any threshold
is crossed.

THE MISTAKE THIS MODULE EXISTS TO AVOID
---------------------------------------
The obvious implementation -- reuse the simulator's own outputs as the
"prediction" -- produces a residual of exactly zero, always, because the same
degraded model generated both sides. It looks like a working digital twin and
detects nothing. The shadow must therefore be a separate instance whose
degradation factors are pinned as-new and never advanced.

WHAT DRIVES IT, AND WHAT MUST NOT
---------------------------------
The shadow is driven only by quantities that describe the OPERATING POINT:

    throttle, rpm, altitude, outside air temperature, airspeed

Every one of these is a command or an environmental condition. None of them is
an engine response to degradation. Feeding back a measured engine RESPONSE --
cylinder head temperature above all -- would let the shadow track the failing
engine, and the residual would quietly collapse toward zero exactly as the
fault grew. That is the classic way a model-based monitor blinds itself, so the
rule here is absolute: responses are compared, never consumed.

WHY RPM IS AN INPUT AND NOT A RESIDUAL
--------------------------------------
Locking the shadow to the measured rpm makes it answer a sharp question: "at
THIS speed, throttle and altitude, what should the temperatures, pressures and
flows be?" Left free, the shadow's speed would drift a few hundred rpm from the
real engine's -- propeller load, governor behaviour, transient history -- and
that operating-point mismatch alone would swamp the thermal signal it exists to
measure. Speed is directly threshold-monitored by the rule engine anyway
(``layer1_edge.edge_rules``), so nothing is lost by treating it as an input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from common import config
from layer1_edge.can_ingest import Telemetry
from layer2_physics import mvem
from layer2_physics.atmosphere import Ambient, air_density, ambient_at
from layer2_physics.degradation import DegradationFactors

# Below this speed the engine is not in a steady operating regime and the
# thermal model has no meaningful answer, so residuals are not published.
_MIN_RUNNING_RPM = 1200.0


@dataclass
class ShadowStatus:
    """Why the shadow's output is or is not trustworthy this step."""

    running: bool = False
    initialised: bool = False
    steps: int = 0
    skipped_no_rpm: int = 0
    skipped_no_inputs: int = 0
    last_reason: str = ""

    @property
    def usable(self) -> bool:
        return self.running and self.initialised


class ShadowModel:
    """An as-new mean-value model kept in step with the live engine.

    Usage is one :meth:`update` per telemetry frame. It returns the predicted
    engine state, or ``None`` when the operating point is not one the model can
    speak to -- during a start, on the ground, or when the driving channels
    themselves failed validation. Returning ``None`` rather than a stale answer
    is deliberate: a residual computed against an out-of-date prediction is
    worse than no residual, because it looks like data.
    """

    def __init__(self, engine_key: str = "rotax_915is") -> None:
        self.engine_key = engine_key
        self.engine = config.load_engine(engine_key)
        self.model = mvem.MeanValueEngineModel(
            engine=self.engine,
            engine_key=engine_key,
            # Pinned as-new and never advanced. ``as_new`` rather than a bare
            # constructor because bearing clearance is an absolute dimension
            # that defaults to zero -- which the oil-pressure model reads as a
            # seized bearing (docs/PRD_DEVIATIONS.md, bearing-clearance defect).
            degradation=DegradationFactors.as_new(self.engine),
        )
        self.status = ShadowStatus()
        self.last_output: mvem.EngineOutputs | None = None
        self._humidity = 40.0

    # ------------------------------------------------------------------
    def _ambient(self, tel: Telemetry) -> Ambient | None:
        alt = tel.get("altitude_ft")
        oat = tel.get("oat")
        if alt is None or oat is None:
            return None
        # A missing airspeed is not a stationary aircraft: taken as zero it
        # removed ram-air cooling and predicted a hotter engine than the one
        # flying, which hides a real overheat in the residual.
        spd = tel.get("airspeed_kmh")
        if spd is None:
            return None
        amb = ambient_at(alt, humidity_pct=self._humidity, airspeed_kmh=spd)
        # Measured OAT replaces the standard-atmosphere value outright. An ISA
        # deviation is a forecast; the aircraft has a thermometer.
        rho = air_density(amb.pressure_pa, oat + 273.15, self._humidity)
        return replace(amb, oat_c=oat, density_kg_m3=rho)

    def _initialise_thermal(self, tel: Telemetry) -> None:
        """Seed the thermal states from the first good frame.

        Thermal states otherwise start at standard ambient and take several
        minutes of simulated time to settle, during which every temperature
        residual is dominated by the shadow's own warm-up rather than by engine
        health. Seeding once from measurement removes that transient.

        This is the ONLY place a measured engine response enters the shadow,
        and it happens exactly once. After initialisation the shadow evolves on
        its own; if it kept re-seeding it would track the real engine and the
        residual would vanish as the fault grew.
        """
        cht = tel.get("cht_max")
        coolant = tel.get("coolant_temperature")
        oil = tel.get("oil_temperature")
        if cht is not None:
            self.model.t_cht[:] = cht + 273.15
        if coolant is not None:
            self.model.t_coolant = coolant + 273.15
        if oil is not None:
            self.model.t_oil = oil + 273.15
        self.status.initialised = True

    # ------------------------------------------------------------------
    def update(self, tel: Telemetry, dt: float) -> mvem.EngineOutputs | None:
        """Advance the shadow one step against the live operating point."""
        if dt <= 0.0:
            return self.last_output

        rpm = tel.get("rpm")
        throttle = tel.get("throttle_pct")
        amb = self._ambient(tel)

        if rpm is None or rpm < _MIN_RUNNING_RPM:
            self.status.running = False
            self.status.skipped_no_rpm += 1
            self.status.last_reason = "engine not running or rpm unavailable"
            self.last_output = None
            return None
        if throttle is None or amb is None:
            self.status.running = False
            self.status.skipped_no_inputs += 1
            self.status.last_reason = "throttle or air data unavailable"
            self.last_output = None
            return None

        self.status.running = True
        self.status.last_reason = ""
        if not self.status.initialised:
            self._initialise_thermal(tel)

        # Lock the operating point to the measured speed (see module docstring).
        self.model.omega = rpm * 2.0 * math.pi / 60.0

        out = self.model.step(dt, throttle_pct=throttle, ambient=amb)
        self.status.steps += 1
        self.last_output = out
        return out

    def reset(self) -> None:
        """Return to an uninitialised as-new shadow, e.g. for a new mission."""
        self.model.degradation = DegradationFactors.as_new(self.engine)
        self.status = ShadowStatus()
        self.last_output = None
