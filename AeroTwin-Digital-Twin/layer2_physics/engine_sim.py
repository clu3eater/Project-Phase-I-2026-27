"""The virtual engine -- physics plus instrumentation.

WHERE THE DATA COMES FROM (read this before asking "is it real?")
-----------------------------------------------------------------
This project has no access to a physical engine, so every sample is generated
here. That is not a shortcut: the problem statement asks for a "Demonstration
using SIMULATED OR REAL engine datasets", and PRD Part 1 section 3.3 specifies a
"Virtual CAN Bus Development Environment ... for development and demonstration
without physical hardware".

What makes the synthetic data defensible is that it is NOT scripted. It is the
output of the 0-D mean-value engine model, the Cantera combustion model, the
turbocharger and intercooler model, the two-node thermal model and the ECU
model -- all anchored to twelve published figures from the engine's Type
Certificate Data Sheet and Operators Manual. The degradation and fault
behaviour comes from the six physical pathways of PRD Part 1 section 5.2.

This module adds the last layer: a real engine is not observed through perfect
sensors. PRD Part 0 section 0.5 is explicit that training on clean model output
is the trap to avoid --

    "Add realistic SENSOR NOISE, bias drift, and dropouts (not clean model
     output) ... Randomize physics parameters per engine (manufacturing
     spread) so the NN cannot memorize one trajectory."

So every signal here passes through a sensor model with white noise, slow bias
drift, quantisation to the resolution the CAN database actually carries, and
occasional dropouts. What leaves this module is what an instrument would have
seen, not what the physics computed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from common import config
from layer2_physics import mvem
from layer2_physics.atmosphere import Ambient, EnvCondition, ambient_for, profile
from layer2_physics.degradation import DegradationEngine, FaultMode, InjectedFault

# ---------------------------------------------------------------------------
# Sensor model
# ---------------------------------------------------------------------------


@dataclass
class SensorSpec:
    """Instrument characteristics for one measured channel.

    ``noise_sigma`` and ``drift_per_hour`` are expressed in engineering units.
    ``resolution`` matches what the CAN database can actually carry, so the
    quantisation the twin sees is the real bus quantisation and not an
    idealisation of it.
    """

    noise_sigma: float
    resolution: float
    drift_per_hour: float = 0.0
    dropout_probability: float = 0.0
    bias: float = 0.0
    drift: float = 0.0
    # First-order response of the transducer itself (review PHY-10). Without it
    # every reading followed the physics instantly: EGT is algebraic in the
    # model and moved 225 degC in one second, CHT 245 degC per minute -- rates
    # the trend and thermal-shock logic were then tuned against, and no probe
    # delivers. 0 means no lag.
    time_constant_s: float = 0.0
    _lag: dict = field(default_factory=dict, repr=False)
    # Instrument failures injected for validation, per key (see ``fail``).
    _failed: dict = field(default_factory=dict, repr=False)
    _held: dict = field(default_factory=dict, repr=False)
    _last: dict = field(default_factory=dict, repr=False)

    def observe(
        self, true_value: float, rng: np.random.Generator, *,
        dt: float | None = None, key: int = 0,
    ) -> float | None:
        """Return the instrument reading, or ``None`` for a dropped sample.

        ``key`` keeps the lag state of instruments sharing one specification
        apart -- the four head thermocouples, the four EGT probes. Without
        ``dt`` no lag is applied. The lag advances even on a dropped sample:
        the probe keeps responding whether or not its frame reaches the bus.
        """
        if self.time_constant_s > 0.0 and dt is not None and dt > 0.0:
            prev = self._lag.get(key, true_value)
            true_value = prev + (dt / (self.time_constant_s + dt)) * (true_value - prev)
            self._lag[key] = true_value
        failure = self._failed.get(key)
        if failure == "stuck":
            true_value = self._held.setdefault(key, true_value)
        if self.dropout_probability > 0.0 and rng.random() < self.dropout_probability:
            return None
        noisy = true_value + self.bias + self.drift
        if self.noise_sigma > 0.0:
            noisy += rng.normal(0.0, self.noise_sigma)
        if self.resolution > 0.0:
            noisy = round(noisy / self.resolution) * self.resolution
        # A frozen instrument still draws its noise sample, so no other reading
        # of the engine shifts; it just reports the last one again.
        if failure == "frozen" and key in self._last:
            return self._last[key]
        self._last[key] = float(noisy)
        return float(noisy)

    def age(self, hours: float, rng: np.random.Generator) -> None:
        """Advance the slow bias drift that every real transducer suffers."""
        if self.drift_per_hour != 0.0:
            self.drift += rng.normal(self.drift_per_hour, abs(self.drift_per_hour) * 0.3) * hours

    def fail(self, mode: str, key: int = 0) -> None:
        """Fail this instrument, for validation.

        "frozen": it repeats its last reading exactly (a latched converter, hung
        firmware). "stuck": it stops following the quantity but keeps its
        electrical noise (a seized or detached transducer).
        """
        if mode not in ("frozen", "stuck"):
            raise ValueError(f"unknown sensor failure {mode!r}")
        self._failed[key] = mode
        self._held.pop(key, None)

    def repair(self, key: int = 0) -> None:
        self._failed.pop(key, None)
        self._held.pop(key, None)


def _pulse(reading: float | None, true_value: float) -> float | None:
    """A pulse-counting instrument at rest reads zero, not noise about zero.

    The crank pickup and the fuel-flow turbine report a FREQUENCY. With the
    shaft or the fuel stopped there are no pulses to count, so the reading is
    exactly 0 -- where the analogue noise model would put a stopped engine at
    -3 rpm and fail it on the plausibility check.
    """
    if reading is None:
        return None
    return 0.0 if true_value <= 0.0 else reading


# Below this the oil pump is not turning (bar): a stopped engine.
OIL_AT_REST_BAR = 0.05


def _at_rest(reading: float | None, true_bar: float) -> float | None:
    """A gauge-pressure transducer with no pump behind it reads its zero.

    Its analogue noise about zero put a stopped engine at -0.3 to +0.7 psi,
    moving on every frame: an oil pressure that fluctuates, and goes negative,
    with the engine off. The engine monitor shows 0, as a panel gauge does.
    """
    if reading is None:
        return None
    return 0.0 if true_bar < OIL_AT_REST_BAR else reading


def _magnitude(reading: float | None) -> float | None:
    """An RMS reading: the size of the noise at rest, not its sign."""
    return None if reading is None else abs(reading)


# Instruments a drift fault can afflict, and the bias magnitude at full
# severity for each -- roughly the offset at which a reading becomes misleading
# rather than merely noisy, in that channel's own engineering units.
DRIFTABLE_CHANNELS: dict[str, float] = {
    "cht": 9.0,                   # degC
    "egt": 38.0,                  # degC
    "coolant_temperature": 6.5,   # degC
    "oil_temperature": 7.0,       # degC
    "oil_pressure": 0.55,         # bar
    "fuel_flow": 1.3,             # L/h
    "manifold_pressure": 0.09,    # bar
    "rpm": 55.0,                  # rpm
}


def _default_sensors() -> dict[str, SensorSpec]:
    """Instrument set matching the resolutions declared in the CAN database.

    Noise levels are representative of the sensor types named in PRD Part 1
    section 3.1: K-type thermocouples, piezoresistive pressure transducers, a
    turbine flow meter and a MEMS accelerometer.
    """
    # Time constants [MOD], representative of the transducer types: a sheathed
    # K-type EGT probe in exhaust flow responds in a few seconds, a head
    # thermocouple bonded into metal in about ten, immersed coolant and oil
    # sensors in between, and a manifold air sensor in about two (the charge
    # air's own thermal mass is modelled separately in turbo.solve).
    return {
        "rpm": SensorSpec(noise_sigma=4.0, resolution=1.0),
        "cht": SensorSpec(noise_sigma=0.6, resolution=0.1, drift_per_hour=0.004,
                          time_constant_s=10.0),
        "coolant_temperature": SensorSpec(noise_sigma=0.4, resolution=0.1, drift_per_hour=0.003,
                                          time_constant_s=4.0),
        "egt": SensorSpec(noise_sigma=3.5, resolution=0.5, drift_per_hour=0.02,
                          time_constant_s=3.0),
        # UNITS: this channel is observed in BAR, because that is what the
        # engine reports and what goes on the bus. The figures were originally
        # written in psi, which put 0.35 BAR (5 psi) of noise and a 1.45 psi
        # quantisation step on a steady idling engine -- enough to swing the
        # reading from 24 psi to -1 psi between consecutive samples and trip
        # the ingest layer's plausibility check. 0.024 bar is 0.35 psi.
        "oil_pressure": SensorSpec(
            noise_sigma=0.024, resolution=0.01, drift_per_hour=0.00014
        ),
        "oil_temperature": SensorSpec(noise_sigma=0.35, resolution=0.1, drift_per_hour=0.003,
                                      time_constant_s=5.0),
        "fuel_flow": SensorSpec(noise_sigma=0.12, resolution=0.01),
        "manifold_pressure": SensorSpec(noise_sigma=0.004, resolution=0.001),
        "manifold_air_temperature": SensorSpec(noise_sigma=0.4, resolution=0.1,
                                               time_constant_s=2.0),
        # FADEC lane B's own sensors for the quantities measured on BOTH lanes
        # [IM Rev.5 failure matrix: CPS, MAPS and MATS have an A and a B entry].
        # Same instrument type as lane A, separate noise. Lane B used to send a
        # copy of lane A's number, so the two lanes could never disagree.
        "rpm_lane_b": SensorSpec(noise_sigma=4.0, resolution=1.0),
        "manifold_pressure_lane_b": SensorSpec(noise_sigma=0.004, resolution=0.001),
        "manifold_air_temperature_lane_b": SensorSpec(noise_sigma=0.4, resolution=0.1,
                                                      time_constant_s=2.0),
        "fuel_pressure": SensorSpec(noise_sigma=0.02, resolution=0.01),
        "vibration_rms": SensorSpec(noise_sigma=0.05, resolution=0.01),
        "battery_voltage": SensorSpec(noise_sigma=0.03, resolution=0.01),
        "alternator_current": SensorSpec(noise_sigma=0.15, resolution=0.1),
        # A battery shunt is a low-value resistor: noisier than a Hall
        # sensor but with no offset drift, which is why it is the standard
        # way to measure pack current.
        "battery_current": SensorSpec(noise_sigma=0.20, resolution=0.1),
        "injection_timing": SensorSpec(noise_sigma=0.15, resolution=0.1),
        "ignition_timing": SensorSpec(noise_sigma=0.12, resolution=0.1),
        "injection_period": SensorSpec(noise_sigma=0.02, resolution=0.01),
    }


# ---------------------------------------------------------------------------
# What the instrumentation reports
# ---------------------------------------------------------------------------


@dataclass
class SensorFrame:
    """One instant of instrument readings, ready for CAN encoding.

    ``None`` means the sample was dropped -- the ingest layer must handle that
    as MISSING rather than substituting a value (PRD Part 4 section 7.1).
    """

    t_s: float
    flight_hours: float

    rpm: float | None
    cht_c: list[float | None]
    coolant_temperature_c: float | None
    egt_c: list[float | None]
    oil_pressure_bar: float | None
    oil_temperature_c: float | None
    fuel_flow_lph: float | None
    manifold_pressure_bar: float | None
    manifold_air_temp_c: float | None
    fuel_pressure_bar: float | None
    vibration_rms: list[float | None]
    vibration_kurtosis: float | None
    battery_voltage_v: float | None
    alternator_current_a: float | None
    battery_current_a: float | None
    injection_timing_deg: list[float | None]
    ignition_timing_deg: list[float | None]
    injection_timing_cmd_deg: float
    ignition_timing_cmd_deg: float
    injection_period_ms: float
    injector_duty: float
    knock_intensity: float
    knock_retard_deg: float

    # air data (from the vehicle management computer, not the engine EMS)
    altitude_ft: float
    oat_c: float
    airspeed_kmh: float
    humidity_pct: float
    flight_phase: int

    # ECU status
    throttle_pct: float
    wastegate_pct: float
    ecu_mode: int
    active_lane: int
    lane_a_health: int
    lane_b_health: int
    ecu_error_flags: int
    air_flow_g_per_min: float

    # FADEC lane B's own readings of the sensors fitted to both lanes, the two
    # warning lamps (0 OFF, 1 ON, 2 FLASHING) and which lanes are on the bus.
    # The airframe's cooling-air flap positions, percent of travel. These are
    # where a losing radiator shows FIRST: measured across 18 operating points,
    # a 30 % cooling-air loss moves the flap 31.8 sensor-sigmas and the coolant
    # temperature 4.0, because the flap is what holds the temperature.
    cooling_flap_pct: float = 0.0
    oil_flap_pct: float = 0.0
    rpm_lane_b: float | None = None
    manifold_pressure_bar_lane_b: float | None = None
    manifold_air_temp_c_lane_b: float | None = None
    warn_lamp_a: int = 0
    warn_lamp_b: int = 0
    lanes_transmitting: tuple[bool, bool] = (True, True)

    # ground truth -- for training labels and evaluation ONLY. This never
    # travels on the bus and must never reach a detector at inference time.
    truth: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# FADEC lanes
# ---------------------------------------------------------------------------

# Items whose failure on one lane this simulation represents completely on the
# bus [IM Rev.5 failure matrix]. A sensor failure withholds that lane's reading;
# a power or display-CAN failure silences that lane's node. The rest are refused
# rather than half-simulated: MATS shares one headerless frame with the other
# lane, and TPS, AAPTS, AAT, EGT, knock, coils and injectors change the engine's
# control in ways the engine model does not represent.
LANE_FAILURES_SUPPORTED = frozenset(
    {"CPS", "MAPS", "OPS", "OTS", "CTS", "ECU_POWER", "EMS_GROUND_PORT", "DISPLAY_CAN"})
_SILENCES_LANE = frozenset({"ECU_POWER", "EMS_GROUND_PORT", "DISPLAY_CAN"})
_LAMP_CODE = {"OFF": 0, "ON": 1, "FLASHING": 2}      # DBC WARN_LAMP value table
_LAMP_RANK = {0: 0, 2: 1, 1: 2}                       # OFF < FLASHING < ON
# Lanes still controlling the engine in each manufacturer system mode.
_MODE_CONTROL = {"Auto_AB": {"A", "B"}, "Auto_A": {"A"}, "Only_A": {"A"},
                 "Auto_B": {"B"}, "Only_B": {"B"}}
_ACTIVE_LANE = {frozenset({"A", "B"}): 3, frozenset({"A"}): 1, frozenset({"B"}): 2}


@dataclass(frozen=True)
class LaneStatus:
    """What the FADEC reports about its lanes, as the manufacturer's FMEA says."""

    active_lane: int = 3                     # DBC: 0 NONE 1 ONLY_A 2 ONLY_B 3 AUTO_AB
    health_a: int = 1
    health_b: int = 1
    lamp_a: int = 0                          # DBC: 0 OFF 1 ON 2 FLASHING
    lamp_b: int = 0
    flags: int = 0                           # ECU_ERROR_FLAGS bits 0, 8 and 9
    transmitting: tuple[bool, bool] = (True, True)
    failed_sensors: frozenset[tuple[str, str]] = frozenset()


# ---------------------------------------------------------------------------
# Flight profile
# ---------------------------------------------------------------------------


@dataclass
class FlightPhase:
    """One leg of a mission profile."""

    name: str
    duration_s: float
    throttle_pct: float
    altitude_ft: float
    airspeed_kmh: float
    phase_code: int
    # Off for the shutdown that ends a sortie: no fire, no fuel.
    ignition: bool = True
    # HELD past its duration until someone releases it (`release_hold`): the
    # engine running at the warm-up setting, waiting for the operator's
    # launch clearance, as a real aircraft waits at the holding point.
    hold: bool = False


# Flight phase codes match the CAN database's FLIGHT_PHASE value table.
PHASE_GROUND, PHASE_STARTUP, PHASE_TAXI, PHASE_TAKEOFF = 0, 1, 2, 3
PHASE_CLIMB, PHASE_CRUISE, PHASE_DESCENT, PHASE_LANDING = 4, 5, 6, 7


def isr_patrol_profile(cruise_hours: float = 1.0) -> list[FlightPhase]:
    """A short MALE ISR sortie: the demo mission.

    Compressed from the 18-24 h endurance sortie of PRD Part 3 section 18.1 so
    that a demonstration completes in reasonable time; the shape -- ground run,
    take-off, climb to a patrol altitude, long cruise, descent, landing -- is
    the same, and ``cruise_hours`` restores the real duration when needed.
    """
    return [
        # THE SORTIE BEGINS WITH A STOPPED ENGINE.
        #
        # The profile used to open on GROUND with the engine already idling and
        # already warm, so an operator who connected to the station never saw
        # the engine start -- every value was at its running figure from the
        # very first frame. PHASE_STARTUP has been in the CAN database's phase
        # table all along (value 1, between GROUND and TAXI) and nothing was
        # ever emitting it. Now the model is put on the starter cold and held
        # at an idle lever, and the speed, the oil pressure and every
        # temperature come up off ambient because the model computes them.
        FlightPhase("STARTUP", 40.0, 18.0, 0.0, 0.0, PHASE_STARTUP),
        FlightPhase("GROUND", 60.0, 12.0, 0.0, 0.0, PHASE_GROUND),
        FlightPhase("TAXI", 60.0, 20.0, 0.0, 20.0, PHASE_TAXI),
        FlightPhase("TAKEOFF", 45.0, 100.0, 500.0, 120.0, PHASE_TAKEOFF),
        # 80 %, not 92 %: under the old fixed-pitch law 92 % settled at 5608 rpm,
        # above the 5500 rpm max-continuous rating, for a ten-minute climb --
        # the alert that exposed it was correct; the profile was not. With the
        # governed propeller (DEV-227) the governor holds any part-throttle
        # lever at max continuous less its regulation band, 5480 rpm.
        FlightPhase("CLIMB", 600.0, 80.0, 15000.0, 175.0, PHASE_CLIMB),
        FlightPhase("CRUISE", cruise_hours * 3600.0, 68.0, 18000.0, 180.0, PHASE_CRUISE),
        FlightPhase("DESCENT", 480.0, 35.0, 3000.0, 190.0, PHASE_DESCENT),
        FlightPhase("LANDING", 120.0, 25.0, 0.0, 110.0, PHASE_LANDING),
        # THE SORTIE ENDS WITH THE ENGINE STOPPED.
        #
        # It used to end on LANDING, and the last phase is held: the aircraft
        # sat on the runway at 110 km/h with the engine at 2,500 rpm for as long
        # as the station ran -- two hours of "landing" was measured -- and the
        # flight never finished, so nothing was ever written to the trend
        # across flights. Now it rolls out, taxies in, idles to let the heads
        # and turbocharger cool before shutdown [OM], and is shut down: the
        # ignition goes off and the engine runs down on its own friction.
        FlightPhase("TAXI", 90.0, 18.0, 0.0, 20.0, PHASE_TAXI),
        FlightPhase("GROUND", 60.0, 12.0, 0.0, 0.0, PHASE_GROUND),
        FlightPhase("SHUTDOWN", 60.0, 0.0, 0.0, 0.0, PHASE_GROUND, ignition=False),
    ]


# ---------------------------------------------------------------------------
# Profiles the ground station flies on an operator's command
# ---------------------------------------------------------------------------
#
# The demonstration profile above flies itself from the starter to shutdown.
# A squadron does not: the engine is started when the operator has the
# aircraft accepted and the checks done, it runs at the warm-up setting until
# the oil is legal and the operator gives launch clearance, and it can be
# recalled (RTB) or shut down on the ground at any point. These are those.

PARKED_PHASE = "PARKED"
HOLD_PHASE = "WARM-UP"


def parked_profile() -> list[FlightPhase]:
    """On the ground, engine stopped and cold, for as long as nobody starts it."""
    return [FlightPhase(PARKED_PHASE, 1.0e12, 0.0, 0.0, 0.0, PHASE_GROUND,
                        ignition=False)]


def _climb_s(altitude_ft: float) -> float:
    return max(180.0, altitude_ft / VirtualEngine.CLIMB_FT_PER_MIN * 60.0 + 60.0)


def _descent_s(altitude_ft: float) -> float:
    return max(180.0, (altitude_ft - 3000.0) / VirtualEngine.DESCENT_FT_PER_MIN * 60.0
               + 90.0)


def mission_profile(cruise_hours: float, cruise_altitude_ft: float = 18000.0,
                    cruise_throttle_pct: float = 68.0) -> list[FlightPhase]:
    """A tasked sortie: start, warm up and HOLD for launch, then fly the plan.

    The climb and descent are as long as the mission altitude needs at the
    airframe's climb and descent rates, so a 23,000 ft high-altitude task is
    not flown in the time a 12,000 ft transit takes.
    """
    alt = float(cruise_altitude_ft)
    return [
        FlightPhase("STARTUP", 40.0, 18.0, 0.0, 0.0, PHASE_STARTUP),
        # 22 %: a fast idle, as the manual's warm-up asks for, so the oil comes
        # up to the take-off minimum in minutes rather than at ground idle.
        FlightPhase(HOLD_PHASE, 90.0, 22.0, 0.0, 0.0, PHASE_GROUND, hold=True),
        FlightPhase("TAXI", 60.0, 20.0, 0.0, 20.0, PHASE_TAXI),
        FlightPhase("TAKEOFF", 45.0, 100.0, 500.0, 120.0, PHASE_TAKEOFF),
        FlightPhase("CLIMB", _climb_s(alt), 80.0, alt, 175.0, PHASE_CLIMB),
        FlightPhase("CRUISE", cruise_hours * 3600.0, float(cruise_throttle_pct),
                    alt, 180.0, PHASE_CRUISE),
        FlightPhase("DESCENT", _descent_s(alt), 35.0, 3000.0, 190.0, PHASE_DESCENT),
        FlightPhase("LANDING", 120.0, 25.0, 0.0, 110.0, PHASE_LANDING),
        FlightPhase("TAXI", 90.0, 18.0, 0.0, 20.0, PHASE_TAXI),
        FlightPhase("COOL-DOWN", 60.0, 12.0, 0.0, 0.0, PHASE_GROUND),
        FlightPhase("SHUTDOWN", 60.0, 0.0, 0.0, 0.0, PHASE_GROUND, ignition=False),
    ]


def ground_run_profile() -> list[FlightPhase]:
    """The engine ground run a maintainer does after work on the engine.

    Start, warm up, hold a run-up power long enough for the twin to assess the
    engine warm and loaded, idle to cool, shut down. On the ground there is no
    ram air, so the run-up is held for minutes, not for a cruise.
    """
    return [
        FlightPhase("STARTUP", 40.0, 18.0, 0.0, 0.0, PHASE_STARTUP),
        FlightPhase(HOLD_PHASE, 180.0, 25.0, 0.0, 0.0, PHASE_GROUND),
        # 45 % for two minutes. 62 % took the Rotax heads to 140 degC and the
        # diesel's oil to 162 degC with no ram air; 45 % peaks at 120 / 118,
        # inside every limit, and still loads the engine past the assessment
        # gate so the twin can judge it.
        FlightPhase("RUN-UP", 120.0, 45.0, 0.0, 0.0, PHASE_GROUND),
        FlightPhase("COOL-DOWN", 90.0, 12.0, 0.0, 0.0, PHASE_GROUND),
        FlightPhase("SHUTDOWN", 60.0, 0.0, 0.0, 0.0, PHASE_GROUND, ignition=False),
    ]


def rapid_throttle_profile(cycles: int = 8) -> list[FlightPhase]:
    """PRD Part 3 section 18.1 CONDITION 4: repeated rapid throttle transitions."""
    phases = [FlightPhase("CLIMB", 300.0, 90.0, 12000.0, 170.0, PHASE_CLIMB)]
    for _ in range(cycles):
        phases.append(FlightPhase("SURGE", 40.0, 100.0, 12000.0, 180.0, PHASE_CRUISE))
        phases.append(FlightPhase("IDLE", 40.0, 20.0, 12000.0, 150.0, PHASE_CRUISE))
    return phases


# ---------------------------------------------------------------------------
# The virtual engine
# ---------------------------------------------------------------------------


@dataclass
class VirtualEngine:
    """A physics-driven engine with instrumentation, degradation and faults."""

    engine_key: str = "rotax_915is"
    seed: int = 0
    # How long the demo sortie cruises for. One hour is the realistic shape,
    # but the loop is COMPUTE-bound at roughly 15x real time whatever `speed`
    # asks for, so a one-hour cruise needs about six minutes of wall clock to
    # fly. Nobody runs a demonstration that long, which is why every report
    # stopped mid-climb with the charts cut off at the right-hand edge.
    cruise_hours: float = 1.0
    env_condition: EnvCondition = EnvCondition.STANDARD
    # A DIRECT ambient temperature, overriding the atmosphere model.
    #
    # "Hold 18,000 ft at 45 degC ambient" is a question about a temperature.
    # Expressing it as an ISA deviation would give a different answer at every
    # altitude, which is not what was asked -- so ``ambient_for`` takes it as an
    # override and recomputes density from it. None means the standard
    # atmosphere with the profile's own ISA deviation, which is the normal case.
    oat_override_c: float | None = None
    # Relative humidity override, percent; None keeps the condition's value.
    humidity_override_pct: float | None = None
    initial_flight_hours: float = 0.0

    rng: np.random.Generator = field(init=False)
    # Lane B's instruments draw from their own stream, so adding them changed no
    # existing reading of a seeded engine.
    rng_lane_b: np.random.Generator = field(init=False)
    lane_failures: set[tuple[str, str]] = field(init=False, default_factory=set)
    model: mvem.MeanValueEngineModel = field(init=False)
    degradation: DegradationEngine = field(init=False)
    sensors: dict[str, SensorSpec] = field(init=False)
    flight_hours: float = field(init=False, default=0.0)
    t_s: float = field(init=False, default=0.0)

    _engine: dict = field(init=False, repr=False)
    _phase_idx: int = field(init=False, default=0)
    _phase_t: float = field(init=False, default=0.0)
    _profile: list[FlightPhase] = field(init=False, default_factory=list)
    _throttle: float = field(init=False, default=20.0)
    _was_running: bool = field(init=False, default=False)
    # Fuel-rail regulator state (see _rail_pressure_bar).
    _rail_dev: float = field(init=False, default=0.0)
    _ff_prev: float | None = field(init=False, default=None)
    _ambient: Ambient = field(init=False, repr=False, default=None)  # type: ignore[assignment]
    # Where the aircraft actually is, which follows the profile's targets at
    # the rates an aircraft can fly -- see `_fly_toward`.
    _alt_ft: float = field(init=False, default=0.0)
    _spd_kmh: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.rng_lane_b = np.random.default_rng(np.random.SeedSequence(self.seed).spawn(1)[0])
        self._engine = config.load_engine(self.engine_key)
        self.flight_hours = self.initial_flight_hours

        self.model = mvem.build(self.engine_key)
        # Per-engine manufacturing spread: PRD Part 0 section 0.5 requires it so
        # that a network cannot memorise a single trajectory.
        self.model.set_manufacturing_spread(self.rng)

        self.degradation = DegradationEngine(engine=self._engine, rng=self.rng)
        self.degradation.randomise_rates()
        self.model.degradation = self.degradation.factors

        self.sensors = _default_sensors()
        self._profile = isr_patrol_profile(self.cruise_hours)
        self._ambient = self._ground_ambient()
        self._alt_ft = self._profile[0].altitude_ft if self._profile else 0.0
        self._spd_kmh = self._profile[0].airspeed_kmh if self._profile else 0.0
        # COLD AND STOPPED, because the profile now starts on the starter.
        self.model.initialise_cold(self._ambient)
        self._oil_takeoff_min_c = float(
            config.load_thresholds()["parameters"]["oil_temperature"]["takeoff_min"])
        self._warmup_held_s = 0.0

    def _ground_ambient(self) -> Ambient:
        """The air on the airfield, where the engine is started.

        Not the condition's DEFAULT altitude, which is the patrol altitude:
        on a standard 15 degC day the engine was being put on the starter at
        the -21 degC of 18,000 ft -- and on a restart, at whatever altitude the
        aircraft had last reached. Oil came up from -15 degC, the first minutes
        read as a sick engine, and the take-off went with the oil still cold.
        """
        first = self._profile[0] if self._profile else None
        return ambient_for(
            self.env_condition,
            altitude_ft=first.altitude_ft if first else 0.0,
            airspeed_kmh=first.airspeed_kmh if first else 0.0,
            oat_c=self.oat_override_c,
            humidity_pct=self.humidity_override_pct,
        )

    # -- setup ---------------------------------------------------------------

    def set_profile(self, phases: list[FlightPhase]) -> None:
        self._profile = phases
        self._phase_idx = 0
        self._phase_t = 0.0
        self._hold_released = False

    def release_hold(self) -> bool:
        """Let a held phase end (launch clearance). False if none is held."""
        if not self.current_phase().hold:
            return False
        self._hold_released = True
        return True

    def jump_to(self, name: str) -> bool:
        """Go straight to the next phase called ``name`` (recall, abort).

        The aircraft's altitude and speed are NOT jumped: the new phase's
        targets are flown toward at the airframe's rates, so a recall from the
        cruise is a descent, not a teleport to the runway.
        """
        for i in range(self._phase_idx + 1, len(self._profile)):
            if self._profile[i].name == name:
                self._phase_idx = i
                self._phase_t = 0.0
                self._hold_released = False
                return True
        return False

    def restart_sortie(self) -> None:
        """Put the aircraft back on the ground with the engine stopped.

        WHAT THIS DELIBERATELY DOES NOT TOUCH: the degradation state, the
        accumulated flight hours, or any wear. Those belong to the ENGINE and
        survive a sortie -- an engine does not become new because it was shut
        down and started again, and the health index, the degradation trend and
        the remaining-life estimate are all built on a history that must not be
        thrown away every time somebody connects to the station.

        What it does reset is the FLIGHT: back to the first phase, with the
        model put on the starter cold. So the next sortie is flown by the same
        worn engine, from the beginning.
        """
        self._phase_idx = 0
        self._phase_t = 0.0
        self._warmup_held_s = 0.0
        self._hold_released = False
        # On the airfield's air, not the air at wherever the last sortie was.
        self._ambient = self._ground_ambient()
        self._alt_ft = self._profile[0].altitude_ft if self._profile else 0.0
        self._spd_kmh = self._profile[0].airspeed_kmh if self._profile else 0.0
        self.model.initialise_cold(self._ambient)
        # The probes and the lever come back with the engine. A probe's lag
        # state is the temperature its element was at -- left alone, the oil
        # probe went on reading 102 degC and fell toward ambient at 12 degC/s
        # after the restart, which the ingest rightly called impossible.
        for spec in self.sensors.values():
            spec._lag.clear()
        self._throttle = self._profile[0].throttle_pct if self._profile else 0.0

    def inject(self, fault: InjectedFault) -> None:
        self.degradation.inject(fault)

    def fail_lane_item(self, item: str, lane: str) -> None:
        """Fail one FADEC item on one lane, with the consequences the manufacturer lists.

        The warning lamps, the system mode and which lanes still control the
        engine come from the engine's failure matrix [IM Rev.5], not from here.
        """
        rows = self._engine.get("failure_matrix", {}).get("items", [])
        if not any(r["item"] == item and str(r["lane"]) == lane for r in rows):
            raise ValueError(f"{item} on lane {lane} is not in the {self.engine_key} failure matrix")
        if item not in LANE_FAILURES_SUPPORTED:
            raise ValueError(f"a {item} failure is not simulated: its effect on the engine "
                             "or on the bus is not represented")
        self.lane_failures.add((item, lane))

    # SUDDEN FAILURES (mvem.MeanValueEngineModel.FAILURES): the engine stops
    # making power now, rather than wearing over hours.
    GLIDE_SINK_FT_PER_MIN = 600.0     # [MOD] a MALE airframe gliding at ~20:1
    GLIDE_KMH = 130.0
    # Down and stopped after a failure: the crew secures the engine -- throttle
    # closed, ignition and pumps off, the ENGINE FAILURE ground checklist --
    # after this long, and the sortie ends. Before, the profile flew on: the
    # throttle stayed at cruise over a dead engine on the ground, so ENGINE
    # FAILURE, and its tone, never cleared.
    SECURE_AFTER_S = 20.0

    def fail(self, name: str) -> None:
        if name not in self.model.FAILURES:
            raise ValueError(f"unknown failure {name!r}")
        failures = set(getattr(self.model, "failures", set()))
        failures.add(name)
        self.model.failures = failures

    def clear_failures(self) -> None:
        """Restore what was failed. A seized engine stays seized until an
        overhaul: bearings do not un-weld because the oil was topped up."""
        self.model.failures = set()
        self.model._oil_loss_s = 0.0
        self.model._dry_run_s = 0.0

    # When fuel stops, neither the flowmeter nor the rail steps to zero: the
    # injectors drain the rail and the meter's turbine spins down over about a
    # second, and a sealed rail keeps a residual pressure. Stepped to exactly
    # zero, the ingest's rate check rejected the flow as implausible and the
    # frozen-sensor check read the flat 0.00 bar as a dead transducer -- a
    # false TELEMETRY STALE on top of the real ENGINE FAILURE.
    FUEL_DRAIN_TAU_S = 1.0
    RAIL_RESIDUAL_BAR = 0.2

    def _starved_flow(self, actual_lph: float, dt: float | None) -> float:
        prev = getattr(self, "_flow_seen", actual_lph)
        if self.model.firing:
            self._flow_seen = actual_lph
            return actual_lph
        a = (dt or 0.1) / (self.FUEL_DRAIN_TAU_S + (dt or 0.1))
        self._flow_seen = prev + a * (actual_lph - prev)
        # The turbine stops: an exponential never reaches zero, and a meter
        # left "spinning" at 0.001 L/h put noise about zero -- negative flows
        # -- on a stopped engine's display.
        if self._flow_seen < 0.05:
            self._flow_seen = 0.0
        return self._flow_seen

    def _starved_rail(self, rail_bar: float, dt: float | None) -> float:
        """The rail bleeds down when fuel stops reaching it: fuel starvation,
        or the pumps switched off with the engine at shutdown (and before the
        start). With the pumps modelled as always on, a parked engine showed
        3 bar of fuel pressure for as long as the station was left running."""
        prev = getattr(self, "_rail_seen", rail_bar)
        pumps_off = not self.model.ignition
        if "fuel_starvation" not in getattr(self.model, "failures", ()) and not pumps_off:
            self._rail_seen = rail_bar
            return rail_bar
        a = (dt or 0.1) / (self.FUEL_DRAIN_TAU_S + (dt or 0.1))
        self._rail_seen = prev + a * (self.RAIL_RESIDUAL_BAR - prev)
        return self._rail_seen

    def _glide(self, dt: float) -> bool:
        """No power in the air: the aircraft comes down at its glide rate,
        whatever the profile wanted. A flight profile flown on at cruise
        altitude with the engine stopped was the other half of "the engine
        failed and nothing changed"."""
        if self.model.firing:
            self._down_s = 0.0
            return False
        if not getattr(self.model, "failures", None) and not getattr(self.model, "seized", False):
            return False   # a commanded shutdown, not a failure
        if self._alt_ft <= 0.0:
            # Down: roll to a stop where it landed -- the profile would take
            # it back up to the planned altitude -- and, once stopped, secure.
            a = dt / (self.AIRSPEED_TAU_S / 4.0 + dt)
            self._spd_kmh += a * (0.0 - self._spd_kmh)
            if self.model.omega < 10.0:          # rad/s: stopped
                self._down_s = getattr(self, "_down_s", 0.0) + dt
                if (self._down_s >= self.SECURE_AFTER_S
                        and self.current_phase().name != "SHUTDOWN"):
                    self.jump_to("SHUTDOWN")
            return True
        self._alt_ft = max(0.0, self._alt_ft - self.GLIDE_SINK_FT_PER_MIN / 60.0 * dt)
        a = dt / (self.AIRSPEED_TAU_S + dt)
        self._spd_kmh += a * (self.GLIDE_KMH - self._spd_kmh)
        return True

    def clear_lane_failures(self) -> None:
        self.lane_failures.clear()

    def fail_sensor(self, name: str, mode: str, key: int = 0) -> None:
        """Fail one instrument, "frozen" or "stuck"; ``key`` is the cylinder or axis."""
        self.sensors[name].fail(mode, key=key)

    def repair_sensor(self, name: str, key: int = 0) -> None:
        self.sensors[name].repair(key)

    def _lane_status(self) -> LaneStatus:
        if not self.lane_failures:
            return LaneStatus()
        rows = {(r["item"], str(r["lane"])): r for r in self._engine["failure_matrix"]["items"]}
        control = {"A", "B"}
        lamp = {"A": 0, "B": 0}
        flags = 0
        sensors: set[tuple[str, str]] = set()
        for key in self.lane_failures:
            row = rows[key]
            control &= _MODE_CONTROL[row["mode"]]
            for ln in ("A", "B"):
                code = _LAMP_CODE[row[f"lamp_{ln.lower()}"]]
                if _LAMP_RANK[code] > _LAMP_RANK[lamp[ln]]:
                    lamp[ln] = code
            if row["kind"] == "sensor":
                sensors.add(key)
                flags |= 1 << 0                       # SENSOR_FAULT
        if "A" not in control:
            flags |= 1 << 8                           # LANE_A_FAULT
        if "B" not in control:
            flags |= 1 << 9                           # LANE_B_FAULT
        silent = {ln for item, ln in self.lane_failures if item in _SILENCES_LANE}
        return LaneStatus(
            active_lane=_ACTIVE_LANE.get(frozenset(control), 0),
            health_a=int("A" in control), health_b=int("B" in control),
            lamp_a=lamp["A"], lamp_b=lamp["B"], flags=flags,
            transmitting=("A" not in silent, "B" not in silent),
            failed_sensors=frozenset(sensors),
        )

    def current_phase(self) -> FlightPhase:
        idx = min(self._phase_idx, len(self._profile) - 1)
        return self._profile[idx]

    @property
    def profile_complete(self) -> bool:
        # The last phase is HELD past its duration (the live console keeps the
        # engine on the ground after landing), so the index never passes the
        # end. `_phase_idx >= len(profile)` was therefore never true and a
        # caller waiting for the sortie to finish waited forever.
        last = len(self._profile) - 1
        return (self._phase_idx >= last
                and self._phase_t >= self._profile[last].duration_s)

    # -- stepping -------------------------------------------------------------

    def _electrical_load(self) -> float:
        """Bus load in amps, which is NOT constant on a real aircraft.

        A MALE UAV duty-cycles its ISR payload, its datalink transmits in
        bursts, and de-icing comes on and off. Modelling a fixed load looked
        harmless until the battery estimator needed it: internal resistance is
        recovered from the SLOPE of terminal voltage against current, and a
        constant current gives a regression through a single point. With the
        load pinned at 8 A the estimator correctly refused to report a state of
        health at all, for the whole life of the engine.

        Base avionics plus a slow payload duty cycle plus datalink bursts.
        """
        el = self._engine["electrical"]
        rated = float(el["alternator_rated_A"])
        base = 0.22 * rated                                   # avionics, EMS, pumps
        payload = 0.30 * rated * (0.5 + 0.5 * math.sin(self.t_s / 45.0))
        datalink = 0.12 * rated if (int(self.t_s) // 7) % 3 == 0 else 0.0
        return float(base + payload + datalink)

    # How fast the demonstration aircraft changes height and speed. A MALE
    # airframe on this engine climbs at around 1,000-1,500 ft/min and descends
    # a little faster; the airspeed settles with a time constant of tens of
    # seconds. [MOD] -- representative, not a particular airframe's figures.
    CLIMB_FT_PER_MIN = 1500.0
    DESCENT_FT_PER_MIN = 2000.0
    AIRSPEED_TAU_S = 20.0

    def _fly_toward(self, phase: FlightPhase, dt: float) -> None:
        """Move the aircraft toward the phase's altitude and speed at flyable rates.

        The profile gives each phase a TARGET. It used to be applied the
        instant the phase began, so the engine breathed 15,000 ft air a second
        after take-off, 3,000 ft air a second after the top of descent, and the
        landing roll began with the airspeed cut from 190 to 110 km/h in one
        step -- which is what raised CHT RISING FAST on every landing, as the
        cooling air vanished between two samples.
        """
        d = phase.altitude_ft - self._alt_ft
        rate = (self.CLIMB_FT_PER_MIN if d > 0 else self.DESCENT_FT_PER_MIN) / 60.0
        step = rate * dt
        self._alt_ft = (phase.altitude_ft if abs(d) <= step
                        else self._alt_ft + math.copysign(step, d))
        a = dt / (self.AIRSPEED_TAU_S + dt)
        self._spd_kmh += a * (phase.airspeed_kmh - self._spd_kmh)

    # The longest the warm-up is held for oil temperature, after which the
    # take-off goes ahead and OIL TEMP LOW says so. Only there so that a
    # condition the engine cannot warm up in does not hang the sortie.
    WARMUP_HOLD_MAX_S = 1200.0

    def _advance_profile(self, dt: float) -> FlightPhase:
        phase = self.current_phase()
        self._phase_t += dt
        if phase.hold and not getattr(self, "_hold_released", False):
            return phase
        if self._phase_t >= phase.duration_s and self._phase_idx < len(self._profile) - 1:
            # NO TAKE-OFF ON COLD OIL [OM s2.1: 50 degC minimum].
            #
            # The ground phases had fixed lengths, so the take-off was flown
            # at whatever the oil had reached by then -- 22 degC on a
            # standard day -- and every sortie raised OIL TEMP LOW on the
            # runway. A pilot holds the warm-up until the oil is legal; so
            # does this, at the warm-up's own throttle.
            nxt = self._profile[self._phase_idx + 1]
            oil_c = float(self.model.t_oil) - 273.15
            if (nxt.phase_code == PHASE_TAKEOFF
                    and oil_c < self._oil_takeoff_min_c
                    and self._warmup_held_s < self.WARMUP_HOLD_MAX_S):
                self._warmup_held_s += dt
                return phase
            self._phase_idx += 1
            self._phase_t = 0.0
            self._hold_released = False
            phase = self.current_phase()
        return phase

    def step(self, dt: float = 0.1) -> SensorFrame:
        """Advance the engine by ``dt`` seconds and return an instrument frame."""
        phase = self._advance_profile(dt)

        # Throttle follows the commanded setting with a servo lag, so the rapid
        # transition scenario produces real transients rather than steps.
        tau = 0.6
        alpha = dt / (tau + dt)
        self._throttle += alpha * (phase.throttle_pct - self._throttle)

        # Ambient follows where the aircraft IS, under the selected condition.
        # Engine failed in the air: the glide replaces the profile's flight
        # path -- flying toward the planned altitude would climb it back.
        if not self._glide(dt):
            self._fly_toward(phase, dt)
        self._ambient = ambient_for(
            self.env_condition,
            altitude_ft=self._alt_ft,
            airspeed_kmh=self._spd_kmh,
            oat_c=self.oat_override_c,
            humidity_pct=self.humidity_override_pct,
        )

        self.model.ignition = phase.ignition
        out = self.model.step(
            dt, throttle_pct=self._throttle, ambient=self._ambient,
            electrical_load_a=self._electrical_load(),
        )

        # Advance wear. Below a running threshold the engine is not accumulating
        # meaningful life, so ground idle does not age it like cruise does.
        dt_hours = dt / 3600.0
        # A start-stop cycle is the largest single current a battery ever
        # sees, so the degradation model has to be told when one happens.
        # Hysteresis, for the same reason the twin's counter uses it: rpm
        # hovers around any fixed line and a bare crossing would count a
        # cycle per noise excursion.
        if not self._was_running and out.rpm > 1500.0:
            self._was_running = True
            self.degradation.record_start_cycle()
        elif self._was_running and out.rpm < 500.0:
            self._was_running = False

        if out.rpm > 1200.0:
            self.flight_hours += dt_hours
            env_mult = profile(self.env_condition).degradation_multipliers
            self.degradation.advance(
                dt_hours,
                oil_temp_c=out.oil_temperature_c,
                cht_max_c=out.cht_max,
                env_multipliers=env_mult,
            )
            self.model.degradation = self.degradation.factors
            for spec in self.sensors.values():
                spec.age(dt_hours, self.rng)

        self.t_s += dt
        return self._observe(out, phase, dt)

    def fast_forward(self, hours: float, *, oil_temp_c: float, cht_max_c: float) -> None:
        """Age the engine by ``hours`` without simulating them.

        A run-to-failure dataset spans the 1200 h TBO. Simulating that second by
        second is 8.6 million steps per engine -- about 13 hours of compute for
        ONE engine, and PRD Part 0 section 0.5 asks for a hundred of them.

        Wear, though, does not need the fine time grid. The degradation
        pathways are integrated in flight HOURS and depend on the operating
        point only through oil and head temperature, both of which are
        essentially constant across a cruise leg. So the honest compression is:
        simulate a short window at full fidelity, then advance the wear clock
        across the rest of the sortie using the temperatures that window
        actually produced. Nothing is approximated that varies within a sortie;
        what is skipped is repeated simulation of a steady condition.

        Sensor ageing (bias drift) advances on the same clock, so a drifting
        sensor still drifts across the engine's life rather than only during
        the observed windows.
        """
        if hours <= 0.0:
            return
        self.flight_hours += hours
        env_mult = profile(self.env_condition).degradation_multipliers
        self.degradation.advance(
            hours,
            oil_temp_c=oil_temp_c,
            cht_max_c=cht_max_c,
            env_multipliers=env_mult,
        )
        self.model.degradation = self.degradation.factors
        for spec in self.sensors.values():
            spec.age(hours, self.rng)

    # -- instrumentation -------------------------------------------------------

    def _rail_pressure_bar(self, fuel_flow_lph: float, dt: float) -> float:
        """Fuel-rail pressure from a pump and a pressure regulator (review PHY-13).

        The rail was a constant plus noise, so the manual's own transient
        allowance -- 2.5-3.5 bar for up to 3 s after a power change, against a
        2.9-3.2 bar steady band [OM s2.1] -- could never be exercised, and a
        regulator problem could not be shown. A step in fuel demand now draws
        the rail down until the regulator catches it, then it recovers.
        Coefficients [MOD]: 0.015 bar per L/h/s of demand change, a 0.4 s
        regulator; a full-throttle slam dips the rail about 0.3 bar. Bounded to
        the published transient band.
        """
        fp = self._engine["fuel_properties"]
        lo, hi = (float(v) for v in fp["rail_pressure_bar"])
        t_lo, t_hi = (float(v) for v in fp.get("rail_pressure_transient_bar", [lo, hi]))
        nominal = 0.5 * (lo + hi)
        if self._ff_prev is None or dt <= 0.0:
            self._ff_prev = fuel_flow_lph
            return nominal + self._rail_dev
        demand_rate = (fuel_flow_lph - self._ff_prev) / dt
        self._ff_prev = fuel_flow_lph
        a = dt / (0.4 + dt)
        self._rail_dev += a * (-0.015 * demand_rate - self._rail_dev)
        return float(np.clip(nominal + self._rail_dev, t_lo, t_hi))

    def _observe(
        self, out: mvem.EngineOutputs, phase: FlightPhase, dt: float | None = None
    ) -> SensorFrame:
        s = self.sensors
        rng = self.rng
        active = {m: mag for m, mag, _ in self.degradation.active_faults()}

        # A sensor-drift fault is expressed HERE, in the instrument, not in the
        # physics -- that is exactly what makes it distinguishable from a real
        # process change (PRD Part 2 section 10.5).
        # SENSOR DRIFT -- one instrument disagreeing with the physics.
        #
        # Applied per fault, on the channel that fault names, and zeroed on
        # every drift-capable channel first.
        #
        # Zeroing first is what makes a cleared fault actually clear. Assigning
        # the bias only when the magnitude was non-zero left it at its last
        # value forever: clear_faults() empties the fault list but cannot reach
        # into the instrument, so a cleared sensor-drift fault left the engine
        # permanently mis-reading and the alert it raised never went away.
        #
        # Choosing the CHANNEL per fault is what makes the class honest. It
        # used to bias oil pressure and CHT together, always, by the same fixed
        # amounts. That made sensor drift trivially recognisable in one
        # direction and inseparable from a real cooling fault in the other:
        # every instance raised CHT by 9 degC, so it collided with
        # cooling_degradation, and 84 % of that class's false positives were
        # sensor-drift windows. A real transducer fault afflicts ONE instrument
        # and which one varies, so the class is now defined by "an instrument
        # disagrees with the physics" rather than by two specific channels.
        for spec in DRIFTABLE_CHANNELS:
            if spec in s:
                s[spec].bias = 0.0
        for f in self.degradation.faults:
            if f.mode is not FaultMode.SENSOR_DRIFT:
                continue
            mag = f.magnitude_at(self.degradation.hours)
            if mag <= 0.0:
                continue
            ch = f.channel if f.channel in DRIFTABLE_CHANNELS else "cht"
            s[ch].bias += f.drift_sign * DRIFTABLE_CHANNELS[ch] * mag

        # A misfire is expressed as a cold cylinder plus rough running.
        misfire_mag = active.get(FaultMode.MISFIRE, 0.0)
        egt_true = list(out.egt_c)
        rpm_true = out.rpm
        if misfire_mag > 0.0:
            cyl = 0
            egt_true[cyl] = egt_true[cyl] * (1.0 - 0.28 * misfire_mag)
            rpm_true -= 45.0 * misfire_mag * (1.0 + 0.4 * rng.standard_normal())

        # Combustion instability is rough running: cycle-to-cycle variation in
        # each cylinder's burn shows as scatter on EGT and on speed, growing as
        # burn quality falls (review PHY-12). The model's mean burn quality moves
        # the mean EGT; this is the scatter around it.
        inst = float(np.clip(
            (1.0 - self.degradation.factors.combustion_efficiency) / 0.10, 0.0, 1.5))
        if inst > 0.0:
            egt_true = [e + rng.normal(0.0, 15.0 * inst) for e in egt_true]
            rpm_true += rng.normal(0.0, 30.0 * inst)

        vib_rms = out.vibration_rms_m_s2
        if active.get(FaultMode.ABNORMAL_VIBRATION, 0.0) > 0.0:
            vib_rms *= 1.0 + 1.4 * active[FaultMode.ABNORMAL_VIBRATION]

        oil_p_bar = out.oil_pressure_psi / 14.5038

        # FADEC lane state. A failed sensor is still sampled -- it consumes its
        # noise draw, so no other reading shifts -- and then not reported, which
        # is what a lane does with a sensor it has declared failed.
        lanes = self._lane_status()
        rb = self.rng_lane_b

        def on(item: str, lane: str, reading: float | None) -> float | None:
            return None if (item, lane) in lanes.failed_sensors else reading

        # The flowmeter spins down with the rail when fuel stops (see _starved_flow).
        ff_seen = self._starved_flow(out.fuel_flow_lph, dt)
        return SensorFrame(
            t_s=self.t_s,
            flight_hours=self.flight_hours,
            rpm=on("CPS", "A", _pulse(s["rpm"].observe(rpm_true, rng), out.rpm)),
            cht_c=[s["cht"].observe(v, rng, dt=dt, key=i) for i, v in enumerate(out.cht_c)],
            coolant_temperature_c=on("CTS", "A", s["coolant_temperature"].observe(
                out.coolant_temperature_c, rng, dt=dt
            )),
            egt_c=[s["egt"].observe(v, rng, dt=dt, key=i) for i, v in enumerate(egt_true)],
            oil_pressure_bar=on("OPS", "B", _at_rest(
                s["oil_pressure"].observe(oil_p_bar, rng), oil_p_bar)),
            oil_temperature_c=on("OTS", "B", s["oil_temperature"].observe(
                out.oil_temperature_c, rng, dt=dt)),
            fuel_flow_lph=_pulse(s["fuel_flow"].observe(ff_seen, rng), ff_seen),
            manifold_pressure_bar=on("MAPS", "A", s["manifold_pressure"].observe(
                out.manifold_pressure_bar, rng
            )),
            manifold_air_temp_c=s["manifold_air_temperature"].observe(
                out.turbo_state.manifold_air_temp_k - 273.15, rng, dt=dt
            ),
            fuel_pressure_bar=s["fuel_pressure"].observe(
                self._starved_rail(self._rail_pressure_bar(out.fuel_flow_lph, dt or 0.0), dt), rng
            ),
            # An RMS is a magnitude: at rest the accelerometer reads its own
            # noise floor, never a negative number. Signed noise about zero
            # put -0.03 m/s2 on the bus, which the bus definition cannot carry,
            # so the frame was dropped every other tick and the stopped engine
            # raised TELEMETRY STALE.
            vibration_rms=[
                _magnitude(s["vibration_rms"].observe(vib_rms * f, rng, key=i))
                for i, f in enumerate((1.0, 0.82, 0.64))
            ],
            vibration_kurtosis=self._kurtosis(),
            battery_voltage_v=s["battery_voltage"].observe(out.battery_voltage_v, rng),
            alternator_current_a=s["alternator_current"].observe(
                out.alternator_current_a, rng
            ),
            battery_current_a=s["battery_current"].observe(out.battery_current_a, rng),
            injection_timing_deg=[
                s["injection_timing"].observe(v, rng, key=i)
                for i, v in enumerate(out.injection_timing_deg)
            ],
            ignition_timing_deg=[
                s["ignition_timing"].observe(v, rng, key=i)
                for i, v in enumerate(out.ignition_timing_deg)
            ],
            injection_timing_cmd_deg=out.injection_timing_commanded_deg,
            ignition_timing_cmd_deg=out.ignition_timing_commanded_deg,
            injection_period_ms=out.injection_period_ms,
            injector_duty=out.injector_duty_fraction,
            knock_intensity=out.knock_intensity,
            knock_retard_deg=out.knock_retard_deg,
            altitude_ft=self._ambient.altitude_ft,
            oat_c=self._ambient.oat_c,
            airspeed_kmh=self._ambient.airspeed_kmh,
            humidity_pct=self._ambient.humidity_pct,
            flight_phase=phase.phase_code,
            throttle_pct=self._throttle,
            wastegate_pct=100.0 * out.turbo_state.wastegate_fraction,
            ecu_mode=2 if out.rpm > 800.0 else 0,
            active_lane=lanes.active_lane,
            lane_a_health=lanes.health_a,
            lane_b_health=lanes.health_b,
            ecu_error_flags=self._error_flags(out) | lanes.flags,
            air_flow_g_per_min=out.air_mass_flow_kg_s * 60000.0,
            rpm_lane_b=on("CPS", "B", _pulse(s["rpm_lane_b"].observe(rpm_true, rb), out.rpm)),
            manifold_pressure_bar_lane_b=on("MAPS", "B", s["manifold_pressure_lane_b"].observe(
                out.manifold_pressure_bar, rb)),
            manifold_air_temp_c_lane_b=s["manifold_air_temperature_lane_b"].observe(
                out.turbo_state.manifold_air_temp_k - 273.15, rb, dt=dt),
            cooling_flap_pct=100.0 * float(out.cooling_flap_fraction),
            oil_flap_pct=100.0 * float(out.oil_flap_fraction),
            warn_lamp_a=lanes.lamp_a,
            warn_lamp_b=lanes.lamp_b,
            lanes_transmitting=lanes.transmitting,
            truth={
                "flight_hours": self.flight_hours,
                "degradation": self.degradation.factors.as_dict(),
                "fault_labels": self.degradation.fault_label_vector().tolist(),
                "power_kw": out.power_kw,
                "cht_true": list(out.cht_c),
                "coolant_true": out.coolant_temperature_c,
                "injection_deviation": out.injection_timing_deviation_deg,
            },
        )

    def _kurtosis(self) -> float:
        """Vibration kurtosis: 3 for a Gaussian signal, higher when impulsive.

        Bearing damage produces impulses, so kurtosis rises well before RMS
        does (PRD Part 2 section 10.8 Method C).
        """
        bearing = self.degradation.factors.bearing_condition
        return float(3.0 + 9.0 * (1.0 - bearing) ** 1.5 + 0.15 * self.rng.standard_normal())

    def _error_flags(self, out: mvem.EngineOutputs) -> int:
        """ECU error bitfield, matching the CAN database's documented layout."""
        flags = 0
        limits = self._engine["limits"]
        if out.knock_intensity > 0.6:
            flags |= 1 << 4
        if out.manifold_pressure_bar > float(
            self._engine["turbocharger"]["map_never_exceed_bar"]
        ):
            flags |= 1 << 3
        if out.coolant_temperature_c > float(limits["coolant_temperature_max_C"]):
            flags |= 1 << 14
        if out.oil_pressure_psi < 11.6:
            flags |= 1 << 15
        if (out.turbo_state.manifold_air_temp_k - 273.15) > float(
            self._engine["intake"]["manifold_air_temp_max_C"]
        ):
            flags |= 1 << 13
        return flags

    # -- vibration waveform ----------------------------------------------------

    def vibration_waveform(self, duration_s: float = 0.4, fs: float = 10000.0) -> np.ndarray:
        """Synthesise the raw tri-axial vibration signal.

        The 10 Hz RMS on the CAN bus cannot support the spectral detectors the
        problem statement asks for -- "vibration signatures" (section B) and
        "abnormal vibration patterns" (section C) require FFT, envelope and
        order analysis of an actual waveform. This generates one, with the
        diagnostic frequencies of PRD Part 2 sections 10.4 and 10.8:

          1x RPM             unbalance
          2x RPM             misalignment
          gear mesh          reduction gear wear
          BPFO / BPFI        bearing outer / inner race defects
          firing frequency   combustion forcing (2 events/rev on a 4-cyl 4-stroke)

        Bearing defects are modelled as an AMPLITUDE-MODULATED impulse train,
        which is why envelope (Hilbert) analysis recovers them -- the same
        reason it works on real machinery.
        """
        rpm = max(self.model.omega * 60.0 / (2.0 * math.pi), 600.0)
        f_shaft = rpm / 60.0
        n = int(duration_s * fs)
        t = np.arange(n) / fs

        vib = self._engine["vibration"]
        n_cyl = int(self._engine["geometry"]["cylinders"])
        base = float(vib["baseline_rms_m_per_s2"])

        bearing_health = self.degradation.factors.bearing_condition
        wear = 1.0 - bearing_health

        # Bearing defect frequencies (PRD Part 2 section 10.4 Method D).
        nb = float(vib["bearing"]["n_balls"])
        d = float(vib["bearing"]["ball_diameter_mm"])
        pd = float(vib["bearing"]["pitch_diameter_mm"])
        bpfo = (nb / 2.0) * f_shaft * (1.0 - d / pd)
        bpfi = (nb / 2.0) * f_shaft * (1.0 + d / pd)
        f_mesh = float(vib["reduction_gear_teeth"]) * f_shaft
        f_fire = f_shaft * n_cyl / 2.0  # four-stroke: two firings per rev on a 4-cyl

        sig = np.zeros(n)
        sig += 0.45 * base * np.sin(2 * np.pi * f_shaft * t)          # unbalance
        sig += 0.18 * base * np.sin(2 * np.pi * 2 * f_shaft * t)      # misalignment
        sig += 0.55 * base * np.sin(2 * np.pi * f_fire * t)           # combustion
        sig += 0.12 * base * (1.0 + 2.0 * wear) * np.sin(2 * np.pi * f_mesh * t)

        # Bearing impulses: a carrier at a resonance, amplitude-modulated at the
        # defect frequency. This is what envelope analysis is designed to find.
        if wear > 0.02:
            carrier = 2600.0
            for f_defect, gain in ((bpfo, 1.0), (bpfi, 0.6)):
                mod = 0.5 * (1.0 + np.sign(np.sin(2 * np.pi * f_defect * t)))
                decay = np.exp(-8.0 * (t * f_defect % 1.0))
                sig += 1.8 * base * wear * gain * mod * decay * np.sin(
                    2 * np.pi * carrier * t
                )

        sig += self.rng.normal(0.0, 0.12 * base, n)  # broadband floor
        return sig


def run_profile(
    veng: VirtualEngine, *, dt: float = 0.1, max_seconds: float | None = None
):
    """Iterate a virtual engine through its flight profile, yielding frames."""
    total = sum(p.duration_s for p in veng._profile)
    limit = min(total, max_seconds) if max_seconds else total
    steps = int(limit / dt)
    for _ in range(steps):
        yield veng.step(dt)


if __name__ == "__main__":  # pragma: no cover
    v = VirtualEngine(seed=7)
    v.inject(
        InjectedFault(
            mode=FaultMode.INJECTOR_ABNORMAL,
            onset_hours=0.05,
            severity=0.8,
            ramp_hours=0.10,
        )
    )
    print(f"{'t[s]':>7} {'phase':>9} {'rpm':>6} {'CHT':>6} {'clnt':>6} {'EGT':>7} "
          f"{'oilP':>6} {'fuel':>6} {'injdev':>7} {'inj_cond':>8}")
    for i, f in enumerate(run_profile(v, dt=0.5, max_seconds=900.0)):
        if i % 200:
            continue
        dev = max(abs(d) for d in f.truth["injection_deviation"])
        print(
            f"{f.t_s:7.1f} {v.current_phase().name:>9} {f.rpm:6.0f} "
            f"{max(x for x in f.cht_c if x is not None):6.1f} "
            f"{f.coolant_temperature_c:6.1f} "
            f"{max(x for x in f.egt_c if x is not None):7.1f} "
            f"{f.oil_pressure_bar:6.2f} {f.fuel_flow_lph:6.2f} {dev:7.2f} "
            f"{f.truth['degradation']['injector_condition']:8.3f}"
        )
