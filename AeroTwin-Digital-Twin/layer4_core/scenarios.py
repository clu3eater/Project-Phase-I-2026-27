"""Scripted mission scenarios -- problem statement section E.

The PS asks the system to simulate "Engine behavior during" four named cases:

    High Altitude
    Endurance mission
    Hot-weather operation
    Rapid throttle transitions

The environments for these already existed in ``layer2_physics/atmosphere.py``
as ENV_PROFILES, and the physics could always be run in them. What did not
exist was a way to actually RUN one and get an answer -- so the capability was
present in the model and absent from the system, which is the same failure as
an API with no console behind it.

WHAT A SCENARIO RUN HAS TO ANSWER
---------------------------------
Not "what did the engine do", which is a trace, but "did the engine stay inside
its certificate, and what limited it". A scenario that produces a graph and no
verdict leaves the reader to do the analysis, and the reader is the person who
asked the question.

So each run reports, against the engine's own type-certificate limits:

  * the worst value reached on every limited parameter, and its margin;
  * any exceedance, named with the limit it broke;
  * what the LIMITING parameter was -- the one that came closest to its limit,
    which is the answer to "what stops this aircraft doing this mission".

WHY EACH SCENARIO IS SHAPED THE WAY IT IS
-----------------------------------------
High altitude tests the turbocharger against its critical altitude. The
certified rating is held to 15,000 ft; the manufacturer's performance table
shows boost held to about 17,000 ft and then tapering, so full-throttle power
at 5800 rpm is 102 kW at 19,000 ft and 89.5 kW at 23,000 ft. The profile climbs
to the 23,000 ft ceiling deliberately so the whole knee is flown.

Endurance is the MALE case and tests thermal soak, not peak load: hours at a
modest cruise setting where oil and coolant reach equilibrium rather than
transient peaks.

Hot weather attacks the cooling system, which on this engine is the binding
constraint -- ram air does the work, and on an ISA+25 day at low speed there is
less of it and it is hotter.

Rapid throttle transitions attack the turbocharger and the thermal gradients:
slam accelerations give the compressor no time to spool and drive the fastest
temperature excursions the engine ever sees.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from common import config
from layer2_physics.atmosphere import ENV_PROFILES, EnvCondition
from layer2_physics.engine_sim import (
    PHASE_CLIMB,
    PHASE_CRUISE,
    PHASE_DESCENT,
    PHASE_TAKEOFF,
    FlightPhase,
    VirtualEngine,
)


@dataclass
class ScenarioSpec:
    key: str
    name: str
    condition: EnvCondition
    phases: list[FlightPhase]
    question: str          # what this scenario is actually testing
    note: str = ""

    @property
    def duration_s(self) -> float:
        return sum(p.duration_s for p in self.phases)


def _high_altitude() -> ScenarioSpec:
    return ScenarioSpec(
        key="high_altitude",
        name="High altitude",
        condition=EnvCondition.HIGH_ALTITUDE,
        question=(
            "Above about 17,000 ft the turbocharger can no longer hold "
            "sea-level manifold pressure, and power tapers to about 86 % of "
            "the rating at the 23,000 ft ceiling. Where does it start to fall "
            "away, and does the engine stay in limits up there?"
        ),
        phases=[
            FlightPhase("CLIMB 10k", 240.0, 92.0, 10000.0, 165.0, PHASE_CLIMB),
            FlightPhase("CLIMB 18k", 300.0, 95.0, 18000.0, 170.0, PHASE_CLIMB),
            FlightPhase("CLIMB 23k", 300.0, 98.0, 23000.0, 175.0, PHASE_CLIMB),
            FlightPhase("CRUISE 23k", 420.0, 80.0, 23000.0, 180.0, PHASE_CRUISE),
        ],
    )


def _endurance() -> ScenarioSpec:
    return ScenarioSpec(
        key="endurance",
        name="Endurance mission",
        condition=EnvCondition.ENDURANCE,
        question=(
            "A MALE sortie is hours at a modest setting, so this tests THERMAL "
            "SOAK rather than peak load: do oil and coolant settle at a stable "
            "equilibrium, and how much margin is left when they do?"
        ),
        phases=[
            FlightPhase("CLIMB", 300.0, 88.0, 12000.0, 160.0, PHASE_CLIMB),
            FlightPhase("LOITER 1", 900.0, 55.0, 15000.0, 130.0, PHASE_CRUISE),
            FlightPhase("LOITER 2", 900.0, 52.0, 15000.0, 128.0, PHASE_CRUISE),
            FlightPhase("LOITER 3", 900.0, 55.0, 15000.0, 130.0, PHASE_CRUISE),
            FlightPhase("DESCENT", 240.0, 30.0, 5000.0, 150.0, PHASE_DESCENT),
        ],
    )


def _hot_weather() -> ScenarioSpec:
    return ScenarioSpec(
        key="hot_weather",
        name="Hot-weather operation",
        condition=EnvCondition.HOT_WEATHER,
        question=(
            "Cooling is this engine's binding constraint and ram air does the "
            "work. On a hot day at low airspeed there is less of it and it is "
            "hotter. Does coolant stay under its certified 120 C?"
        ),
        phases=[
            FlightPhase("TAKE-OFF", 180.0, 100.0, 1500.0, 120.0, PHASE_TAKEOFF),
            FlightPhase("CLIMB slow", 420.0, 95.0, 6000.0, 135.0, PHASE_CLIMB),
            FlightPhase("CRUISE low", 600.0, 78.0, 8000.0, 150.0, PHASE_CRUISE),
        ],
    )


def _rapid_throttle() -> ScenarioSpec:
    phases = [FlightPhase("STABILISE", 180.0, 60.0, 10000.0, 160.0, PHASE_CRUISE)]
    for i in range(6):
        phases.append(
            FlightPhase(f"SLAM OPEN {i+1}", 45.0, 100.0, 10000.0, 160.0,
                        PHASE_CRUISE)
        )
        phases.append(
            FlightPhase(f"SLAM SHUT {i+1}", 45.0, 25.0, 10000.0, 160.0,
                        PHASE_CRUISE)
        )
    return ScenarioSpec(
        key="rapid_throttle",
        name="Rapid throttle transitions",
        condition=EnvCondition.RAPID_THROTTLE,
        question=(
            "Slam accelerations give the turbocharger no time to spool and "
            "drive the fastest temperature gradients the engine ever sees. How "
            "far do EGT and CHT swing, and how quickly?"
        ),
        phases=phases,
    )


SCENARIOS = {
    s.key: s
    for s in (_high_altitude(), _endurance(), _hot_weather(), _rapid_throttle())
}


@dataclass
class ScenarioResult:
    key: str
    name: str
    condition: str
    question: str
    duration_s: float
    samples: list[dict] = field(default_factory=list)
    limits: list[dict] = field(default_factory=list)
    exceedances: list[str] = field(default_factory=list)
    limiting: str = ""
    limiting_margin_pct: float | None = None

    def as_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "condition": self.condition,
            "question": self.question, "duration_s": round(self.duration_s, 1),
            "samples": self.samples, "limits": self.limits,
            "exceedances": self.exceedances, "limiting": self.limiting,
            "limiting_margin_pct": (
                None if self.limiting_margin_pct is None
                else round(self.limiting_margin_pct, 1)
            ),
        }


def _fly(ve: VirtualEngine, res: ScenarioResult, lim: dict, engine_key: str,
         *, dt: float = 0.5, max_samples: int = 400) -> ScenarioResult:
    """Step the engine through its profile and judge it against the certificate.

    Shared by the four named scenarios and the custom environment, so a point an
    operator dials in is judged by IDENTICAL physics and identical limits to a
    published case. Two code paths here would eventually disagree, and the
    disagreement would be invisible -- both would look like results.
    """
    eng = config.load_engine(engine_key)
    n = int(res.duration_s / dt)
    keep_every = max(1, n // max_samples)
    rows: list[dict] = []
    peak = {"cht": -1e9, "coolant": -1e9, "egt": -1e9, "oil_t": -1e9,
            "oil_p_min": 1e9, "rpm": -1e9}

    for i in range(n):
        f = ve.step(dt)
        cht = max((v for v in f.cht_c if v is not None), default=None)
        egt = max((v for v in f.egt_c if v is not None), default=None)
        if cht is not None:
            peak["cht"] = max(peak["cht"], cht)
        if egt is not None:
            peak["egt"] = max(peak["egt"], egt)
        if f.coolant_temperature_c is not None:
            peak["coolant"] = max(peak["coolant"], f.coolant_temperature_c)
        if f.oil_temperature_c is not None:
            peak["oil_t"] = max(peak["oil_t"], f.oil_temperature_c)
        if f.oil_pressure_bar is not None and f.rpm and f.rpm > 3500:
            peak["oil_p_min"] = min(peak["oil_p_min"], f.oil_pressure_bar)
        if f.rpm is not None:
            peak["rpm"] = max(peak["rpm"], f.rpm)

        if i % keep_every == 0:
            rows.append({
                "t_s": round(f.t_s, 1),
                "phase": ve.current_phase().name,
                "altitude_ft": round(f.altitude_ft, 0),
                "oat_c": round(f.oat_c, 1),
                "throttle_pct": round(f.throttle_pct, 1),
                "rpm": None if f.rpm is None else round(f.rpm, 0),
                "cht_max": None if cht is None else round(cht, 1),
                "coolant": (None if f.coolant_temperature_c is None
                            else round(f.coolant_temperature_c, 1)),
                "egt_max": None if egt is None else round(egt, 0),
                "oil_temperature": (None if f.oil_temperature_c is None
                                    else round(f.oil_temperature_c, 1)),
                "oil_pressure_bar": (None if f.oil_pressure_bar is None
                                     else round(f.oil_pressure_bar, 2)),
                "manifold_pressure_bar": (
                    None if f.manifold_pressure_bar is None
                    else round(f.manifold_pressure_bar, 3)),
            })

    res.samples = rows

    # ---- judge against the certificate ---------------------------------
    thr = config.load_thresholds()["parameters"]
    checks = [
        ("coolant temperature", peak["coolant"],
         float(lim["coolant_temperature_max_C"]), "C", True),
        ("cylinder head temperature", peak["cht"],
         float(thr["cht"]["critical_max"]), "C", True),
        ("exhaust gas temperature", peak["egt"],
         float(lim["egt_max_C"]), "C", True),
        ("oil temperature", peak["oil_t"],
         float(lim["oil_temperature_C"][1]), "C", True),
        ("engine speed", peak["rpm"],
         float(eng["ratings"]["max_power_rpm"]), "rpm", True),
    ]
    if peak["oil_p_min"] < 1e8:
        checks.append(("oil pressure above 3500 rpm", peak["oil_p_min"],
                       float(lim["oil_pressure_above_3500rpm_bar"][0]),
                       "bar", False))

    worst_frac = -1e9
    for name, value, limit, unit, upper in checks:
        if value <= -1e8 or value >= 1e8:
            continue
        # Fraction of the limit used. For a MINIMUM limit the sense inverts.
        frac = (value / limit) if upper else (limit / max(value, 1e-9))
        margin_pct = 100.0 * (1.0 - frac)
        exceeded = value > limit if upper else value < limit
        res.limits.append({
            "name": name, "worst": round(float(value), 2),
            "limit": round(float(limit), 2), "unit": unit,
            "margin_pct": round(float(margin_pct), 1), "exceeded": bool(exceeded),
        })
        if exceeded:
            res.exceedances.append(
                f"{name} reached {value:.1f} {unit} against a "
                f"{'maximum' if upper else 'minimum'} of {limit:.1f} {unit}"
            )
        if frac > worst_frac:
            worst_frac, res.limiting = frac, name
            res.limiting_margin_pct = margin_pct

    return res


def run(key: str, *, engine_key: str = "rotax_915is", dt: float = 0.5,
        max_samples: int = 400) -> ScenarioResult:
    """Fly one named scenario and judge it against the type certificate."""
    if key not in SCENARIOS:
        raise KeyError(f"unknown scenario {key!r}; have {sorted(SCENARIOS)}")
    spec = SCENARIOS[key]
    lim = config.load_engine(engine_key)["limits"]

    ve = VirtualEngine(engine_key=engine_key, seed=11,
                       env_condition=spec.condition)
    ve.set_profile(spec.phases)

    res = ScenarioResult(
        key=spec.key, name=spec.name, condition=str(spec.condition),
        question=spec.question, duration_s=spec.duration_s,
    )
    return _fly(ve, res, lim, engine_key, dt=dt, max_samples=max_samples)


def run_custom(
    *,
    altitude_ft: float,
    oat_c: float | None = None,
    isa_deviation_c: float | None = None,
    humidity_pct: float | None = None,
    airspeed_kmh: float,
    throttle_pct: float,
    duration_s: float = 900.0,
    engine_key: str = "rotax_915is",
    dt: float = 0.5,
    max_samples: int = 300,
) -> ScenarioResult:
    """Hold ONE operator-chosen operating point and judge it.

    PS section E asks for "Environmental condition simulation", and the four
    named scenarios answer it only for four points. This answers it for any
    point: the operator sets altitude, ambient temperature and airspeed, and
    gets back the same verdict against the type certificate -- what the engine
    settles at, what limited it, and how much margin was left.

    A STEADY HOLD, NOT A PROFILE. The question this exists for is "can the
    engine sit here", and the answer is the equilibrium: a thermal transient
    dressed up as a scenario would report whatever the engine happened to be
    passing through. The hold is long enough for the thermal states to settle,
    which on this engine is several minutes.

    OAT IS AN OVERRIDE, NOT AN ISA DEVIATION. "Climb to 20,000 ft at 45 degC
    ambient" is a direct question about a temperature, and applying it as a
    deviation from the standard atmosphere would give a different number at
    every altitude -- which is not what was asked.
    """
    lim = config.load_engine(engine_key)["limits"]

    # An ISA deviation is turned into the equivalent OAT at this altitude, so
    # one override path serves both ways of asking (REP-08).
    if oat_c is None and isa_deviation_c is not None:
        from layer2_physics.atmosphere import ambient_at
        oat_c = ambient_at(float(altitude_ft),
                           isa_deviation_c=float(isa_deviation_c)).oat_c

    ve = VirtualEngine(engine_key=engine_key, seed=11,
                       env_condition=EnvCondition.STANDARD)
    if humidity_pct is not None:
        ve.humidity_override_pct = float(humidity_pct)
    ve.set_profile([
        FlightPhase("HOLD", float(duration_s), float(throttle_pct),
                    float(altitude_ft), float(airspeed_kmh), PHASE_CRUISE),
    ])
    if oat_c is not None:
        # The engine reads ambient from the atmosphere model; the override goes
        # in at the same place the what-if engine uses, so a custom point and a
        # named scenario are judged by identical physics.
        ve.oat_override_c = float(oat_c)

    res = ScenarioResult(
        key="custom", name="Custom environment", condition="CUSTOM",
        question=(
            f"Can the engine hold {throttle_pct:.0f} % throttle at "
            f"{altitude_ft:,.0f} ft and {airspeed_kmh:.0f} km/h"
            + (f" with a {oat_c:.0f} degC ambient" if oat_c is not None else "")
            + (f" at {humidity_pct:.0f} % humidity" if humidity_pct is not None else "")
            + ", and what limits it?"
        ),
        duration_s=float(duration_s),
    )
    _fly(ve, res, lim, engine_key, dt=dt, max_samples=max_samples)
    return res


# Measured wall-clock cost of each run on the reference machine, seconds.
# Not a guess: timed against the live API. The console shows it BEFORE the
# button is pressed, because a control that sits silent for fifty seconds is
# indistinguishable from one that is broken -- and the operator's next move is
# to press it again.
_MEASURED_COST_S = {
    "high_altitude": 20.0,
    "endurance": 48.0,
    "hot_weather": 18.0,
    "rapid_throttle": 12.0,
}


def index() -> list[dict]:
    return [
        {"key": s.key, "name": s.name, "condition": str(s.condition),
         "question": s.question, "duration_s": round(s.duration_s, 1),
         "phases": len(s.phases),
         # Roughly how long the physics takes to run, so the console can say so.
         "compute_s": _MEASURED_COST_S.get(s.key, 30.0)}
        for s in SCENARIOS.values()
    ]


__all__ = ["SCENARIOS", "ScenarioResult", "ScenarioSpec", "index", "run"]
