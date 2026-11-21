"""What a proposed mission costs the ENGINE, leg by leg.

Every other part of this system watches an engine that is already flying. This
answers the question asked before it flies: given this route, at these
altitudes, on a day this hot -- can this engine do it, what will it cost, and
which component is the limit?

WHY THIS IS NOT A FUEL CALCULATOR
---------------------------------
A flight planner can already tell you the fuel. What it cannot tell you is that
the third leg puts the wastegate hard against its stop for forty minutes, so
the engine has no reserve left for a go-around; or that the same sortie flown
at 18,000 ft in a 42 degC ambient consumes 1.4 times the engine life it would
at 10,000 ft in ISA. Those come out of the physics model and the wear model,
and nothing in a threshold-based system has access to them.

WHAT IS COMPUTED, AND FROM WHERE
--------------------------------
Each leg is flown through the SAME mean-value engine model the twin runs
(`mvem.step`), at the ambient the ISA plus deviation gives for that altitude.
Nothing here re-implements engine behaviour; it drives the existing model and
integrates what comes out:

    fuel            from EngineOutputs.fuel_flow_lph, integrated over leg time
    engine hours    clock hours -- the honest denominator for the next figure
    life consumed   the WEAR model advanced over the leg at that operating
                    point (degradation.DegradationModel), so a hot high-power
                    leg costs more life than a cool cruise. This is the number
                    that is not available anywhere else, and it is a model
                    output rather than a coefficient invented here.
    authority       minutes with the wastegate or the cooling flap against its
                    stop, where the engine is holding the condition with
                    nothing left in hand

ASSUMPTIONS, STATED RATHER THAN BURIED
--------------------------------------
Turning distance into time needs AIRFRAME numbers, and this repository models
an engine. Ground speed is taken as the commanded true airspeed with no wind,
and the throttle for a leg is the setting that holds that airspeed under the
engine definition's propeller law. Both are declared in `RouteAssumptions` and
reported back with the answer, so a reader can see what was assumed instead of
inferring it. A wind model and a drag polar belong to the airframe team.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field

from common import config
from layer2_physics import atmosphere as atm

EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class Waypoint:
    """A point the aircraft is asked to reach."""

    name: str
    lat_deg: float
    lon_deg: float
    altitude_ft: float = 15000.0


@dataclass(frozen=True)
class RouteAssumptions:
    """Everything this calculation had to assume, in one place.

    Returned with the result. An assumption a reader cannot see is one they
    cannot disagree with.
    """

    true_airspeed_kmh: float = 175.0
    isa_deviation_c: float = 0.0
    humidity_pct: float = 30.0
    usable_fuel_l: float = 120.0
    wind: str = "no wind modelled"
    note: str = (
        "ground speed equals true airspeed; no wind, no drag polar. "
        "Airframe numbers, not engine numbers."
    )


def great_circle_km(a: Waypoint, b: Waypoint) -> float:
    """Distance over the ground between two waypoints."""
    p1, p2 = math.radians(a.lat_deg), math.radians(b.lat_deg)
    dp = p2 - p1
    dl = math.radians(b.lon_deg - a.lon_deg)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


@dataclass
class LegCost:
    """What one leg between two waypoints costs."""

    frm: str
    to: str
    distance_km: float
    altitude_ft: float
    oat_c: float
    hours: float
    fuel_l: float
    life_hours: float
    mean_power_kw: float
    mean_cht_c: float
    wastegate_saturated_min: float
    cooling_flap_saturated_min: float

    def as_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


@dataclass
class RouteCost:
    """The whole sortie, and the four numbers that decide it."""

    legs: list[LegCost] = field(default_factory=list)
    distance_km: float = 0.0
    hours: float = 0.0
    fuel_l: float = 0.0
    usable_fuel_l: float = 0.0
    life_hours: float = 0.0
    life_ratio: float = 1.0
    limiting_component: str = ""
    limiting_margin: float = 1.0
    wastegate_saturated_min: float = 0.0
    cooling_flap_saturated_min: float = 0.0
    feasible: bool = True
    reasons: list[str] = field(default_factory=list)
    # The ground under the route, and what it demands of the aircraft. A
    # planner that cannot see terrain will happily route a leg at 12,000 ft
    # across ground that stands at 19,900, and nothing on screen will object.
    terrain: dict = field(default_factory=dict)
    # The altitude this ENGINE can still hold cruise power at. Terrain fixes
    # the altitude a route requires; this says whether it is available.
    ceiling_ft: float = 0.0
    assumptions: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {k: (round(v, 4) if isinstance(v, float) else v)
             for k, v in asdict(self).items() if k != "legs"}
        d["legs"] = [leg.as_dict() for leg in self.legs]
        return d


# The condition a "nominal engine hour" means, for the life figure below.
# Mid-altitude cruise on a standard day: the operating point the TBO interval
# is written against. Life cost is expressed RELATIVE to this, because
# "this sortie costs 5.6 engine-hours" is a sentence an operator can act on and
# "combustion efficiency fell 0.00031" is not.
_REFERENCE_ALTITUDE_FT = 10000.0
# The cruise setting the as-new engine's required power is taken at.
CRUISE_THROTTLE_PCT = 75.0

# How long the assessment stands aside for the live twin. See _fly_leg.
_YIELD_S = 0.030


def set_yield_s(seconds: float) -> None:
    """How long to stand aside for the live twin between steps.

    Zero when the assessment is running in a process of its own, where there
    is no twin in this interpreter to stand aside for. See
    `flight_sim.set_yield_s`, which says the same thing about the same problem.
    """
    global _YIELD_S
    _YIELD_S = max(0.0, float(seconds))
_REFERENCE_ISA_DEV_C = 0.0


def _wear_scalar(factors) -> float:
    """One number for how worn the engine is, for differencing.

    The sum of what each pathway has lost from new. Summed rather than taking
    the worst, because a leg that wears three pathways a little is not free
    just because none of them is the worst one yet.
    """
    d = factors.as_dict()
    keys = ("cooling_efficiency", "oil_quality", "combustion_efficiency",
            "injector_condition", "bearing_condition", "turbocharger_condition")
    return sum(max(0.0, 1.0 - float(d.get(k, 1.0))) for k in keys)


def _fly_leg(model, deg, *, hours: float, ambient, throttle_pct: float,
             dt_s: float = 60.0):
    """Fly one leg through the real engine model and integrate what comes out.

    `dt_s` of 60 seconds is a compromise measured rather than guessed: against
    a 30 s step the totals move by well under a percent, and a route assessment
    has to answer while an operator is still looking at it. A route is a PLAN;
    resolving it finer than the plan itself is false precision.
    """
    steps = max(1, int(round(hours * 3600.0 / dt_s)))
    fuel_l = power_sum = cht_sum = 0.0
    wg_sat_s = flap_sat_s = 0.0
    for i in range(steps):
        # LET THE TWIN RUN.
        #
        # This is tens of seconds of CPU-bound Python in the same process as a
        # real-time twin, and one thread holding the GIL starves the other.
        # Measured on the console while a route was being assessed: the twin's
        # own tick p95 went to 2,715 ms, against 80 ms idle. An operator
        # planning tomorrow's sortie must not degrade the monitoring of the
        # engine flying now.
        #
        # sleep(0) DOES NOT DO THIS, and was tried first. It yields only if
        # another thread is already runnable at that instant, so the twin's
        # tick p95 stayed at 3,238 ms against 103 ms idle -- measured on the
        # twin's own pipeline counters, not on a probe thread that sleeps and
        # therefore releases the interpreter by definition. That earlier
        # measurement showed 2.70 ms and was measuring itself.
        #
        # A real sleep releases the interpreter for a definite interval, and it
        # has to be long enough to be USEFUL: a twin tick needs about 70 ms of
        # contiguous CPU, so 2 ms slivers are no use to it. Measured on the
        # twin's own counters against a 95 ms idle p95:
        #
        #     sleep(0), every 20 steps ....... 3,238 ms
        #     2 ms,     every 5 steps ........ 2,387 ms
        #     30 ms,    every 5 steps ...........926 ms
        #     30 ms,    every 2 steps ...........596 ms   <- here
        #
        # Each step roughly halves the spike and adds about eight seconds to an
        # assessment that takes fifty. NOT ELIMINATED: 596 ms against 95 ms
        # idle still means the occasional late tick while a route is being
        # planned, because a single model step plus the model construction the
        # throttle bisection repeats hold the interpreter for that long between
        # yields. Removing it properly means running the assessment in another
        # PROCESS, where there is no shared interpreter to contend for. That is
        # the right fix and it is not this one.
        #
        # The trade taken here is deliberate: the engine flying now outranks
        # the sortie being planned for tomorrow.
        if i % 2 == 0:
            time.sleep(_YIELD_S)
        out = model.step(dt_s, throttle_pct=throttle_pct, ambient=ambient)
        fuel_l += out.fuel_flow_lph * (dt_s / 3600.0)
        power_sum += out.power_kw
        cht = max(out.cht_c) if out.cht_c else 0.0
        cht_sum += cht
        # AUTHORITY, WHICH IS THE POINT.
        # A control against its stop is holding the condition with nothing in
        # hand. It is not an exceedance and no limit monitor will report it,
        # and it is the difference between an engine that can answer a
        # go-around and one that cannot.
        if getattr(out.turbo_state, "wastegate_fraction", 0.0) >= 0.98:
            wg_sat_s += dt_s
        if getattr(out, "cooling_flap_fraction", 0.0) >= 0.98:
            flap_sat_s += dt_s
        deg.advance(dt_hours=dt_s / 3600.0,
                    oil_temp_c=out.oil_temperature_c, cht_max_c=cht)
    return {
        "fuel_l": fuel_l,
        "mean_power_kw": power_sum / steps,
        "mean_cht_c": cht_sum / steps,
        "wastegate_saturated_min": wg_sat_s / 60.0,
        "cooling_flap_saturated_min": flap_sat_s / 60.0,
    }


def assess_route(waypoints: list[Waypoint],
                 assumptions: RouteAssumptions | None = None,
                 engine_key: str = "rotax_915is",
                 factors=None) -> RouteCost:
    """Can this engine fly this route, what does it cost, and what is the limit?

    The engine flown here is AS-NEW. This is the cost of the mission to a
    healthy engine of this type; what a particular worn engine has left is the
    twin's job, and comparing the two is what makes the reachable area shrink
    as an engine ages.
    """
    from layer2_physics import mvem
    from layer2_physics.degradation import DegradationEngine

    a = assumptions or RouteAssumptions()
    eng = config.load_engine(engine_key)
    cost = RouteCost(usable_fuel_l=a.usable_fuel_l, assumptions=asdict(a))

    if len(waypoints) < 2:
        cost.feasible = False
        cost.reasons.append("a route needs at least two waypoints")
        return cost

    model = mvem.build(engine_key)
    # STARTED AND WARM, BECAUSE A ROUTE IS FLOWN BY A RUNNING ENGINE.
    #
    # `mvem.build` hands back a dead engine -- crankshaft stopped, heads at
    # 20 degC, no oil pressure -- and the first leg was being flown by starting
    # it. On a temperate day the model got away with it. Above roughly ISA+31
    # it did not: from rest the speed integration collapsed to its 1 rad/s
    # floor and stayed there, so the engine made no power at all and
    # `practical_ceiling_ft` bisected its way to a 4,000 ft ceiling for a
    # turbocharged engine that holds sea-level power to 15,000 ft.
    #
    # The live twin's simulator warms its model (engine_sim.py) and so does
    # every physics test. Only the planning path did not.
    model.initialise_warm(
        atm.ambient_at(waypoints[0].altitude_ft,
                       isa_deviation_c=a.isa_deviation_c,
                       humidity_pct=a.humidity_pct,
                       airspeed_kmh=a.true_airspeed_kmh))
    deg = DegradationEngine(engine=eng)
    wear_before = _wear_scalar(deg.factors)

    for frm, to in zip(waypoints, waypoints[1:], strict=False):
        km = great_circle_km(frm, to)
        hours = km / max(a.true_airspeed_kmh, 1e-6)
        amb = atm.ambient_at(to.altitude_ft, isa_deviation_c=a.isa_deviation_c,
                             humidity_pct=a.humidity_pct,
                             airspeed_kmh=a.true_airspeed_kmh)
        w0 = _wear_scalar(deg.factors)
        # Cruise power. Held constant per leg because a route is a PLAN, not a
        # flown profile: modelling a throttle schedule the pilot has not
        # chosen yet would be precision this input cannot support.
        flown = _fly_leg(model, deg, hours=hours, ambient=amb, throttle_pct=75.0)
        leg = LegCost(
            frm=frm.name, to=to.name, distance_km=km,
            altitude_ft=to.altitude_ft, oat_c=amb.oat_c, hours=hours,
            fuel_l=flown["fuel_l"], life_hours=0.0,
            mean_power_kw=flown["mean_power_kw"],
            mean_cht_c=flown["mean_cht_c"],
            wastegate_saturated_min=flown["wastegate_saturated_min"],
            cooling_flap_saturated_min=flown["cooling_flap_saturated_min"],
        )
        leg._wear = _wear_scalar(deg.factors) - w0   # type: ignore[attr-defined]
        cost.legs.append(leg)
        cost.distance_km += km
        cost.hours += hours
        cost.fuel_l += flown["fuel_l"]
        cost.wastegate_saturated_min += flown["wastegate_saturated_min"]
        cost.cooling_flap_saturated_min += flown["cooling_flap_saturated_min"]

    wear = _wear_scalar(deg.factors) - wear_before
    cost.life_ratio = _life_ratio(engine_key, wear, cost.hours, a)
    cost.life_hours = cost.hours * cost.life_ratio
    for leg in cost.legs:
        leg.life_hours = leg.hours * cost.life_ratio

    worst, margin = deg.factors.worst()
    cost.limiting_component = worst
    cost.limiting_margin = float(margin)

    # --- the ground, and whether the engine can get over it ---------------
    from layer4_core import terrain as terr

    cost.terrain = terr.assess_route(waypoints)
    if cost.terrain.get("available"):
        need = float(cost.terrain["required_altitude_ft"])
        cost.ceiling_ft = practical_ceiling_ft(factors, a, engine_key)
        if not cost.terrain["clears"]:
            cost.feasible = False
            cost.reasons.append(
                f"terrain: {', '.join(cost.terrain['blocked_legs'])} planned below "
                f"the {need:.0f} ft this route needs "
                f"({cost.terrain['clearance_ft']:.0f} ft over "
                f"{cost.terrain['highest_terrain_ft']:.0f} ft of ground)")
        if need > cost.ceiling_ft:
            cost.feasible = False
            cost.reasons.append(
                f"the terrain needs {need:.0f} ft and this engine holds cruise "
                f"power only to {cost.ceiling_ft:.0f} ft today")

    if cost.fuel_l > a.usable_fuel_l:
        cost.feasible = False
        cost.reasons.append(
            f"needs {cost.fuel_l:.0f} L against {a.usable_fuel_l:.0f} L usable")
    if cost.wastegate_saturated_min > 0:
        cost.reasons.append(
            f"wastegate against its stop for {cost.wastegate_saturated_min:.0f} min "
            "- no boost reserve there")
    if cost.cooling_flap_saturated_min > 0:
        cost.reasons.append(
            f"cooling flap fully open for {cost.cooling_flap_saturated_min:.0f} min "
            "- no cooling reserve there")
    if not cost.reasons:
        cost.reasons.append("within the engine's capability with reserve in hand")
    return cost


def _life_ratio(engine_key: str, wear: float, hours: float,
                a: RouteAssumptions) -> float:
    """How many engine-hours of life one clock hour of this sortie costs.

    Measured, not assumed: the same wear model is run for the same duration at
    the reference condition, and the two are divided. A sortie flown hot and
    high comes out above 1.0 because the pathways it drives -- oil breakdown
    with temperature, deposits with combustion temperature -- run faster there.
    """
    from layer2_physics import mvem
    from layer2_physics.degradation import DegradationEngine

    if hours <= 0 or wear <= 0:
        return 1.0
    # THE REFERENCE IS FLOWN FOR THE WHOLE SORTIE, NOT A WINDOW AND SCALED.
    #
    # Scaling a half-hour reference up to the sortie length was tried and is
    # wrong: wear is not linear in time. The warm-up transient wears at a
    # different rate from settled cruise, so a short reference is dominated by
    # it and scaling that rate up overstates the reference. Measured, the trick
    # moved the answer from 1.00x to 0.665x -- a third of the life cost, lost
    # to an optimisation. It halves the runtime and changes the number, which
    # makes it the wrong trade for a figure someone plans a sortie on.
    ref_hours = hours
    ref_model = mvem.build(engine_key)
    ref_deg = DegradationEngine(engine=config.load_engine(engine_key))
    before = _wear_scalar(ref_deg.factors)
    amb = atm.ambient_at(_REFERENCE_ALTITUDE_FT,
                         isa_deviation_c=_REFERENCE_ISA_DEV_C,
                         humidity_pct=a.humidity_pct,
                         airspeed_kmh=a.true_airspeed_kmh)
    # Warm, exactly as the flown engine above is. The life ratio is the flown
    # wear DIVIDED by this reference wear, so an unstarted reference would not
    # merely be wrong, it would be wrong in a way that scales every life figure
    # the console prints.
    ref_model.initialise_warm(amb)
    _fly_leg(ref_model, ref_deg, hours=ref_hours, ambient=amb, throttle_pct=75.0)
    ref_wear = (_wear_scalar(ref_deg.factors) - before) * (hours / ref_hours)
    return float(wear / ref_wear) if ref_wear > 0 else 1.0


@dataclass
class Envelope:
    """How far this engine can go, now, against how far it could when new.

    The number a commander actually feels. An engine does not announce that it
    has degraded; it announces it by not being able to reach somewhere it used
    to reach, usually on the day that matters.
    """

    radius_km: float = 0.0
    radius_new_km: float = 0.0
    endurance_h: float = 0.0
    endurance_new_h: float = 0.0
    fuel_flow_lph: float = 0.0
    fuel_flow_new_lph: float = 0.0
    lost_km: float = 0.0
    lost_pct: float = 0.0
    altitude_ft: float = 15000.0
    # False when the engine cannot make the cruise power at ANY throttle. The
    # radius is then zero because it cannot hold the condition, not because it
    # runs out of fuel.
    holds_cruise: bool = True
    required_kw: float = 0.0
    assumptions: dict = field(default_factory=dict)
    basis: str = ""

    def as_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


def _cruise_fuel_lph(engine_key: str, factors, altitude_ft: float,
                     a: RouteAssumptions, settle_h: float = 0.25,
                     measure_h: float = 0.25,
                     required_kw: float | None = None,
                     decide_only: bool = False) -> tuple[float, float, bool]:
    """Steady cruise fuel flow for an engine in this condition.

    Flown, not looked up: the model is warmed for `settle_h` and the burn is
    measured over the next `measure_h`, so the warm-up transient is excluded
    from a rate that is then applied to hours of cruise.

    HOLD POWER, NOT THROTTLE -- THE FIRST VERSION HELD THROTTLE AND WAS WRONG.
    ------------------------------------------------------------------------
    Flown at a fixed 75 % throttle, a degraded engine burned LESS fuel than an
    as-new one (30 L/h against 32) and therefore came out with a LARGER radius:
    365 km of reach gained by wearing the engine out. The error is that at
    fixed throttle a worn engine is not doing the same job -- it is making less
    power and flying slower.

    An aircraft holds its airspeed, so the airframe demands a POWER and the
    engine must produce it. `required_kw` is what the as-new engine makes at
    cruise throttle; a worn engine opens the throttle until it matches, and
    burns more doing so. If it cannot reach that power at full throttle it
    cannot hold the cruise at all, which is reported rather than papered over
    by quietly flying slower.
    """
    from layer2_physics import mvem
    from layer2_physics.degradation import DegradationEngine

    amb = atm.ambient_at(altitude_ft, isa_deviation_c=a.isa_deviation_c,
                         humidity_pct=a.humidity_pct,
                         airspeed_kmh=a.true_airspeed_kmh)

    def fly(throttle: float) -> dict:
        model = mvem.build(engine_key)
        if factors is not None:
            model.degradation = factors
        # Warm before the settle. This is the function `practical_ceiling_ft`
        # bisects through, so a model that will not run on a hot day here is a
        # ceiling that collapses on a hot day for no physical reason.
        model.initialise_warm(amb)
        throwaway = DegradationEngine(engine=config.load_engine(engine_key))
        _fly_leg(model, throwaway, hours=settle_h, ambient=amb,
                 throttle_pct=throttle)
        out = _fly_leg(model, throwaway, hours=measure_h, ambient=amb,
                       throttle_pct=throttle)
        return {"lph": out["fuel_l"] / measure_h, "kw": out["mean_power_kw"]}

    if required_kw is None:
        r = fly(CRUISE_THROTTLE_PCT)
        return r["lph"], r["kw"], True

    # Bisect the throttle for the power the airframe needs. Eight steps put it
    # inside a quarter of a percent of travel, which is finer than any
    # installation holds it.
    lo, hi = 20.0, 100.0
    best = fly(hi)
    if best["kw"] < required_kw:
        # Cannot hold this cruise at all, at any throttle.
        return best["lph"], best["kw"], False
    if decide_only:
        # THE CALLER ONLY WANTED THE YES/NO, SO STOP HAVING ANSWERED IT.
        #
        # `practical_ceiling_ft` bisects altitude and reads nothing from this
        # function but the third value -- whether the engine can make the
        # required power there. Deciding that takes ONE run at full throttle:
        # if the most the engine can make is enough, it holds. The eight runs
        # below find the throttle that makes exactly that power, which is what
        # the FUEL figure needs and the ceiling does not.
        #
        # Measured: it was doing all nine on each of eight altitude probes, so
        # seven eighths of a ceiling was a fuel figure computed and discarded.
        # A hot-day route assessment took over six minutes from the console and
        # the button looked hung. The ceiling it returns is identical.
        return best["lph"], best["kw"], True
    for _ in range(8):
        mid = (lo + hi) / 2.0
        r = fly(mid)
        if r["kw"] >= required_kw:
            hi, best = mid, r
        else:
            lo = mid
    return best["lph"], best["kw"], True


def reach_envelope(factors=None, assumptions: RouteAssumptions | None = None,
                   engine_key: str = "rotax_915is",
                   altitude_ft: float = 15000.0) -> Envelope:
    """The out-and-back radius this engine can still manage, and what it lost.

    WHY A RADIUS AND NOT A ROUTE. A route answers "can it do this one". A
    radius answers "what can it still do at all", which is the question a
    degraded engine actually changes the answer to -- and it is the difference
    between the two circles, drawn on the same plan view, that shows what
    predictive maintenance is FOR in one picture.

    HOW IT IS COMPUTED, AND THE ASSUMPTION IN IT. Steady cruise burn is
    measured for each engine and the usable fuel divided by it. That is a
    straight-line extrapolation of a constant-cruise rate: it does not model
    climb, descent, reserve, diversion or wind, and it is stated here rather
    than implied. Half of the resulting endurance is the out-and-back radius.
    """
    a = assumptions or RouteAssumptions()
    # What the airframe needs to hold this cruise: the power an as-new engine
    # makes at the cruise setting. The worn engine is then asked for the same.
    lph_new, required_kw, _ = _cruise_fuel_lph(engine_key, None, altitude_ft, a)
    if factors is None:
        lph_now, holds = lph_new, True
    else:
        lph_now, _kw, holds = _cruise_fuel_lph(
            engine_key, factors, altitude_ft, a, required_kw=required_kw)

    def radius(lph: float) -> tuple[float, float]:
        hours = a.usable_fuel_l / max(lph, 1e-6)
        return hours, hours * a.true_airspeed_kmh / 2.0

    end_new, r_new = radius(lph_new)
    end_now, r_now = (radius(lph_now) if holds else (0.0, 0.0))
    return Envelope(
        holds_cruise=holds, required_kw=required_kw,
        radius_km=r_now, radius_new_km=r_new,
        endurance_h=end_now, endurance_new_h=end_new,
        fuel_flow_lph=lph_now, fuel_flow_new_lph=lph_new,
        lost_km=max(0.0, r_new - r_now),
        lost_pct=100.0 * max(0.0, r_new - r_now) / max(r_new, 1e-6),
        altitude_ft=altitude_ft, assumptions=asdict(a),
        basis=("steady cruise at this altitude, usable fuel divided by measured "
               "burn; no climb, descent, reserve, diversion or wind"),
    )


def practical_ceiling_ft(factors=None, assumptions: RouteAssumptions | None = None,
                         engine_key: str = "rotax_915is",
                         lo_ft: float = 4000.0, hi_ft: float = 26000.0,
                         required_kw: float | None = None) -> float:
    """The highest altitude this engine can still hold cruise power at, today.

    THE QUESTION NO CHART ANSWERS. Terrain fixes the altitude a route REQUIRES.
    Whether that altitude is AVAILABLE is an engine question, and the answer
    moves: a turbocharged engine loses ceiling as its turbocharger wears, and
    loses more of it on a hot day, when the air it is compressing is already
    thin and already warm.

    Defined as the altitude at which the engine can no longer make the power
    the airframe needs for cruise -- the same power the reach envelope holds
    constant -- rather than a certificated service ceiling, which is a property
    of the type and does not change as an engine ages.
    """
    a = assumptions or RouteAssumptions()
    if required_kw is None:
        # THE CALLER USUALLY ALREADY HAS THIS. `flight_sim.simulate` measures
        # the airframe's level-flight demand before it builds the profile and
        # then asks for the ceiling, so computing it again here flew the
        # reference sortie twice on every request for no different answer. It
        # is still computed when nobody passes it, so the function stands alone.
        _lph, required_kw, _ = _cruise_fuel_lph(
            engine_key, None, _REFERENCE_ALTITUDE_FT, a,
            settle_h=0.08, measure_h=0.08)

    def holds(alt: float) -> bool:
        # A SHORTER FLIGHT THAN THE FUEL FIGURE NEEDS.
        #
        # This asks one yes/no question -- can the engine make the required
        # power here -- and power settles in well under a minute, where a fuel
        # RATE needs the thermal states steady. At the full window a ceiling
        # took 69 to 179 seconds and made the route assessment unusable; at
        # 0.08 h of settle it is a few seconds and the altitude it returns is
        # the same to the nearest hundred feet, which is the resolution the
        # bisection reports anyway.
        _l, _k, ok = _cruise_fuel_lph(engine_key, factors, alt, a,
                                      settle_h=0.08, measure_h=0.08,
                                      required_kw=required_kw,
                                      decide_only=True)
        return ok

    if not holds(lo_ft):
        return lo_ft
    if holds(hi_ft):
        return hi_ft
    for _ in range(6):
        mid = (lo_ft + hi_ft) / 2.0
        if holds(mid):
            lo_ft = mid
        else:
            hi_ft = mid
    return round(lo_ft, -2)
