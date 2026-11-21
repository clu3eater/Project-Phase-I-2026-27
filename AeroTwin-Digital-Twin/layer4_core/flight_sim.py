"""Fly a planned route, take-off to landing, and report what goes wrong.

WHAT THIS IS FOR, AND WHY IT IS NOT THE ROUTE COST
--------------------------------------------------
``route_cost.assess_route`` answers a planner's question -- what does this
sortie cost the engine -- and answers it with totals: litres, engine-hours, the
limiting component. Totals are the right shape for a decision made at a desk.

They are the wrong shape for the question an operator actually asks in front of
a map, which is *where*. A sortie that ends with coolant three degrees inside
its limit and one that spends forty minutes against that limit over the target
produce nearly the same totals and are not the same sortie. The second one is
the one that comes home on a spare engine.

So this flies the route MINUTE BY MINUTE and keeps the track: position,
altitude, phase, every engine temperature and pressure, the ground underneath,
and the fuel left. Then it judges each instant against the type certificate and
emits an EVENT the moment a limit is crossed -- with the time, the place and
the value. The console draws the aircraft along that track, so an operator sees
the sortie happen rather than reading its summary.

THE PROFILE IS SYNTHESISED, AND THE SHAPE OF IT IS AN AIRFRAME MATTER
--------------------------------------------------------------------
A route is waypoints. A flight is a take-off roll, a climb, cruise legs, a
descent and a landing, and a route does not contain those. They are built here
from the waypoints, and the parameters that decide their shape -- mass,
propeller efficiency, descent rate -- are AIRFRAME numbers, not engine numbers.
This system models an engine, so every one of them is declared in `Airframe`
below, carried out to the caller in `assumptions`, and printed on the screen
beside the answer. A reader who disagrees with 650 kg can see that they do.

What is NOT assumed is the rate of climb. That is computed from the power the
engine actually has left over at that altitude, which is why it falls as the
aircraft climbs, falls further on a hot day, and falls further still as the
engine wears -- until, at the altitude where there is nothing left over, the
aircraft stops climbing and this says so. That is the whole point: a chart
gives an aircraft one ceiling for its lifetime, and a real engine does not have
one ceiling for its lifetime.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field

from common import config
from layer2_physics import atmosphere as atm
from layer4_core.route_cost import (
    CRUISE_THROTTLE_PCT,
    RouteAssumptions,
    Waypoint,
    great_circle_km,
)

FT_PER_M = 3.280839895
G = 9.80665

# Phase names, as an operator says them. These are strings rather than the CAN
# database's phase codes because they are going to a screen, not to a bus.
START, WARMUP, TAKEOFF, CLIMB, CRUISE, DESCENT, LANDING = (
    "START", "WARMUP", "TAKEOFF", "CLIMB", "CRUISE", "DESCENT", "LANDING")

# Phases in which the engine is on the ground and deliberately at or near it.
# Terrain clearance means nothing here; see `_judge`.
GROUND_PHASES = (START, WARMUP, TAKEOFF, LANDING)


@dataclass(frozen=True)
class Airframe:
    """The airframe numbers this simulation needs, all of them declared.

    NOT ENGINE DATA, AND NOT HARD-CODED HERE. Every field is loaded from
    ``configs/airframes/*.yaml``, where each one carries a provenance tag the
    same way the engine configs do, and where the file says in its own words
    that it describes a CLASS of aircraft rather than any particular one --
    because `configs/engines/rotax_915is.yaml` sets that rule for itself and
    the rule does not stop at the engine mount:

        "Do not claim a specific DRDO or foreign MALE UAV uses this engine
         without a citation."

    Only the timeline depends on these. Power available, power required,
    excess power, the practical ceiling, every temperature and pressure, fuel
    flow, wear and the limiting component are measured from the engine model
    and the type certificate with no airframe input at all.
    """

    key: str = "male_uav_reference"
    name: str = ""
    note: str = ""
    mass_kg: float = 0.0
    prop_efficiency: float = 0.0
    # Bounds on the COMPUTED climb rate. The ceiling is found by the rate
    # falling to `min_climb_fpm`, not by clamping at the top; `max_climb_fpm`
    # only stops the arithmetic producing an unrealistically steep climb near
    # sea level, where the airframe and not the engine is the limit.
    max_climb_fpm: float = 0.0
    min_climb_fpm: float = 0.0
    descent_fpm: float = 0.0
    takeoff_s: float = 0.0
    landing_s: float = 0.0
    takeoff_throttle_pct: float = 0.0
    climb_throttle_pct: float = 0.0
    descent_throttle_pct: float = 0.0
    landing_throttle_pct: float = 0.0
    takeoff_screen_ft: float = 0.0
    reserve_minutes: float = 0.0
    # Starting and warming the engine. `warmup_max_s` is a CUT-OFF, not a
    # duration: the warm-up ends when the oil reaches the temperature the
    # operators manual requires before take-off, which is a measured condition
    # and takes as long as the day makes it take.
    start_s: float = 0.0
    idle_throttle_pct: float = 0.0
    warmup_max_s: float = 0.0

    @classmethod
    def load(cls, key: str = "male_uav_reference") -> Airframe:
        """Read an airframe from configs/airframes/<key>.yaml.

        Fails loudly on a missing file rather than falling back to defaults: a
        silent default is exactly the invented number this file exists to
        avoid, and it would be indistinguishable from a real one on screen.
        """
        import yaml

        path = (config.CONFIG_DIR if hasattr(config, "CONFIG_DIR")
                else _configs_dir()) / "airframes" / f"{key}.yaml"
        if not path.is_file():
            raise FileNotFoundError(
                f"no airframe configuration at {path}. The flight simulation "
                f"needs a mass and a propeller efficiency, and this system "
                f"will not invent them.")
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            key=str(d.get("key", key)), name=str(d.get("name", key)),
            note=str(d.get("note", "")).strip(),
            mass_kg=float(d["mass"]["all_up_kg"]),
            prop_efficiency=float(d["propeller"]["efficiency"]),
            max_climb_fpm=float(d["climb"]["max_fpm"]),
            min_climb_fpm=float(d["climb"]["min_fpm"]),
            climb_throttle_pct=float(d["climb"]["throttle_pct"]),
            descent_fpm=float(d["descent"]["fpm"]),
            descent_throttle_pct=float(d["descent"]["throttle_pct"]),
            takeoff_s=float(d["takeoff"]["duration_s"]),
            takeoff_throttle_pct=float(d["takeoff"]["throttle_pct"]),
            takeoff_screen_ft=float(d["takeoff"]["screen_ft"]),
            landing_s=float(d["landing"]["duration_s"]),
            landing_throttle_pct=float(d["landing"]["throttle_pct"]),
            reserve_minutes=float(d["reserve"]["minutes"]),
            start_s=float(d["start"]["duration_s"]),
            idle_throttle_pct=float(d["start"]["idle_throttle_pct"]),
            warmup_max_s=float(d["start"]["warmup_max_s"]),
        )


def _configs_dir():
    from pathlib import Path
    return Path(__file__).resolve().parents[1] / "configs"


@dataclass
class FlightSample:
    """One instant of the flight: where, how high, and what the engine is doing."""

    t_s: float
    lat_deg: float
    lon_deg: float
    altitude_ft: float
    phase: str
    leg: str
    throttle_pct: float
    power_kw: float
    rpm: float
    cht_c: float
    egt_c: float
    coolant_c: float
    oil_temp_c: float
    oil_press_psi: float
    manifold_bar: float
    fuel_flow_lph: float
    fuel_remaining_l: float
    oat_c: float
    terrain_ft: float
    clearance_ft: float
    wastegate_frac: float
    cooling_flap_frac: float
    vibration_rms: float

    def as_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


@dataclass
class FlightEvent:
    """Something that happened, at the moment and the place it happened.

    `severity` uses the console's own three-level vocabulary rather than
    inventing a fourth: ADVISORY is worth knowing, CAUTION needs a decision,
    WARNING means the sortie as planned does not work.
    """

    t_s: float
    phase: str
    severity: str          # ADVISORY | CAUTION | WARNING
    code: str
    message: str
    lat_deg: float
    lon_deg: float
    altitude_ft: float
    value: float | None = None
    limit: float | None = None
    unit: str = ""

    def as_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


@dataclass
class FlightSim:
    """The whole flight: the track, what went wrong on it, and the verdict."""

    samples: list[FlightSample] = field(default_factory=list)
    events: list[FlightEvent] = field(default_factory=list)
    verdict: str = "GO"                # GO | GO_WITH_LIMITS | NO_GO
    reasons: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    distance_km: float = 0.0
    fuel_used_l: float = 0.0
    fuel_remaining_l: float = 0.0
    reserve_l: float = 0.0
    top_of_climb_ft: float = 0.0
    requested_altitude_ft: float = 0.0
    ceiling_ft: float = 0.0
    peak: dict = field(default_factory=dict)
    conditions: dict = field(default_factory=dict)
    assumptions: dict = field(default_factory=dict)
    # Where the flight had to stop, if it did. None means it landed.
    terminated_at_s: float | None = None
    termination: str = ""

    def as_dict(self) -> dict:
        d = {k: (round(v, 3) if isinstance(v, float) else v)
             for k, v in asdict(self).items()
             if k not in ("samples", "events")}
        d["samples"] = [s.as_dict() for s in self.samples]
        d["events"] = [e.as_dict() for e in self.events]
        return d


# ---------------------------------------------------------------------------
# Profile construction
# ---------------------------------------------------------------------------


@dataclass
class _Segment:
    """One piece of the synthesised flight, with its geography attached."""

    name: str
    phase: str
    duration_s: float
    throttle_pct: float
    alt0_ft: float
    alt1_ft: float
    lat0: float
    lon0: float
    lat1: float
    lon1: float
    # A segment that ends on a MEASURED CONDITION rather than on the clock.
    # Only the warm-up uses it: it runs until the oil reaches the temperature
    # the manual requires before take-off, and `duration_s` is then the point
    # at which the simulation stops waiting rather than the length of it.
    until_oil_c: float | None = None


def _available_kw(engine_key: str, factors, altitude_ft: float,
                  throttle_pct: float, a: RouteAssumptions,
                  settle_h: float = 0.08) -> float:
    """Shaft power this engine makes at this throttle and altitude, flown.

    Short settle deliberately: this asks for POWER, which is in equilibrium
    within a minute, not for a fuel rate, which waits on the thermal states.
    The same shortcut `practical_ceiling_ft` takes, and for the same reason.
    """
    from layer2_physics import mvem
    from layer2_physics.degradation import DegradationEngine

    model = mvem.build(engine_key)
    if factors is not None:
        model.degradation = factors
    amb = atm.ambient_at(altitude_ft, isa_deviation_c=a.isa_deviation_c,
                         humidity_pct=a.humidity_pct,
                         airspeed_kmh=a.true_airspeed_kmh)
    # Warm, for the same reason `simulate` warms its engine: a model stepped
    # from rest does not answer "what power does this engine make here", it
    # answers "what happens if you slam the throttle open on a stopped engine",
    # and on a hot day the answer to the second one is that it never starts.
    model.initialise_warm(amb)
    steps = max(1, int(settle_h * 3600.0 / 30.0))
    out = None
    deg = DegradationEngine(engine=config.load_engine(engine_key))

    for _ in range(steps):
        out = model.step(30.0, throttle_pct=throttle_pct, ambient=amb)
        deg.advance(dt_hours=30.0 / 3600.0, oil_temp_c=out.oil_temperature_c,
                    cht_max_c=max(out.cht_c) if out.cht_c else 0.0)
    return float(out.power_kw) if out is not None else 0.0


def climb_rate_fpm(engine_key: str, factors, altitude_ft: float,
                   required_kw: float, a: RouteAssumptions,
                   af: Airframe) -> float:
    """How fast this engine can drag this airframe upwards, here, today.

    THE ONE NUMBER IN THIS FILE THAT IS NOT ASSUMED. Excess power is what
    climbs an aircraft: whatever the engine makes above the power needed to
    hold level flight goes into potential energy.

        rate of climb = (P_available - P_required) * prop efficiency / (m g)

    `P_required` is the airframe's level-flight demand, taken the same way the
    reach envelope and the practical ceiling take it -- the power an as-new
    engine makes at the cruise setting at the reference altitude -- so all
    three agree with each other by construction rather than by coincidence.

    The consequence is the useful part. `P_available` falls with altitude, and
    falls faster on a hot day, and falls faster still on a worn turbocharger.
    So the climb slows as the aircraft goes up, and the altitude at which it
    stops climbing is this engine's ceiling TODAY -- not the type's ceiling.
    Returns 0.0 there, and the caller reports that the aircraft cannot reach
    the altitude the route asked for.
    """
    avail = _available_kw(engine_key, factors, altitude_ft,
                          af.climb_throttle_pct, a)
    excess_kw = avail - required_kw
    if excess_kw <= 0.0:
        return 0.0
    ms = (excess_kw * 1000.0 * af.prop_efficiency) / (af.mass_kg * G)
    fpm = ms * 60.0 * FT_PER_M
    if fpm < af.min_climb_fpm:
        return 0.0
    return min(fpm, af.max_climb_fpm)


def _interp(lat0, lon0, lat1, lon1, f):
    return lat0 + (lat1 - lat0) * f, lon0 + (lon1 - lon0) * f


def oil_takeoff_min_c() -> float:
    """The oil temperature the manual requires before take-off.

    `configs/thresholds.yaml` declares it as `oil_temperature.takeoff_min`,
    50 degC [OM s2.1], and this reads that rather than choosing a second
    number -- the warm-up is over when the engine is legal to take off, not
    after some interval this file made up.
    """
    p = config.load_thresholds()["parameters"]["oil_temperature"]
    return float(p.get("takeoff_min", p.get("alert_min", 50.0)))


def build_profile(wps: list[Waypoint], a: RouteAssumptions, af: Airframe,
                  engine_key: str, factors, required_kw: float,
                  field_elev_ft: float,
                  start_engine: bool = True) -> tuple[list[_Segment], list[str]]:
    """Turn waypoints into a flight: roll, climb, cruise, descend, land.

    CLIMB IS FLOWN ALONG THE ROUTE, NOT BEFORE IT. An aircraft does not climb
    to altitude over the field and then set off; it climbs while going where it
    is going. So a leg whose altitude is above the previous one is split: the
    climbing part and then the level part, both on the same track. That matters
    for terrain, because the dangerous place on a leg into high ground is the
    part flown before the aircraft has got up to height.
    """
    segs: list[_Segment] = []
    notes: list[str] = []
    first, last = wps[0], wps[-1]

    # --- start the engine, then warm it ------------------------------------
    #
    # A SORTIE BEGINS WITH A STOPPED ENGINE, AND THIS ONE DOES TOO.
    #
    # Both segments sit on the departure field at field elevation. Nothing
    # about them is scripted: the engine is put on the starter cold (see
    # `mvem.initialise_cold`) and the speed, oil pressure and every temperature
    # that come out are the model's own, rising from a standstill at ambient.
    # The warm-up then runs until the oil reaches the take-off minimum the
    # operators manual gives -- so a cold morning warms up for longer than a
    # hot afternoon, because it has further to go.
    if start_engine:
        segs.append(_Segment("ENGINE START", START, af.start_s,
                             af.idle_throttle_pct, field_elev_ft, field_elev_ft,
                             first.lat_deg, first.lon_deg,
                             first.lat_deg, first.lon_deg))
        segs.append(_Segment("WARM-UP", WARMUP, af.warmup_max_s,
                             af.idle_throttle_pct, field_elev_ft, field_elev_ft,
                             first.lat_deg, first.lon_deg,
                             first.lat_deg, first.lon_deg,
                             until_oil_c=oil_takeoff_min_c()))

    # --- take-off roll and initial climb, over the departure field ---------
    screen_ft = field_elev_ft + af.takeoff_screen_ft
    segs.append(_Segment("TAKE-OFF", TAKEOFF, af.takeoff_s,
                         af.takeoff_throttle_pct, field_elev_ft, screen_ft,
                         first.lat_deg, first.lon_deg,
                         first.lat_deg, first.lon_deg))

    alt = screen_ft
    for frm, to in zip(wps, wps[1:], strict=False):
        km = great_circle_km(frm, to)
        leg_s = (km / max(a.true_airspeed_kmh, 1e-6)) * 3600.0
        target = to.altitude_ft
        name = f"{frm.name}→{to.name}"

        if target > alt + 50.0:
            # Climbing leg. The rate is taken at the MIDDLE of the band being
            # climbed through, which is where the average lies for a rate that
            # falls roughly linearly with altitude across it.
            mid = (alt + target) / 2.0
            fpm = climb_rate_fpm(engine_key, factors, mid, required_kw, a, af)
            if fpm <= 0.0:
                notes.append(
                    f"{name}: the engine has no power left over at "
                    f"{mid:,.0f} ft, so the aircraft cannot climb to the "
                    f"{target:,.0f} ft this leg asks for")
                # Fly the leg at the altitude actually reachable rather than
                # pretending. The verdict below reports it as a NO-GO.
                segs.append(_Segment(name, CRUISE, leg_s,
                                     CRUISE_THROTTLE_PCT, alt, alt,
                                     frm.lat_deg, frm.lon_deg,
                                     to.lat_deg, to.lon_deg))
                continue
            climb_s = (target - alt) / fpm * 60.0
            if climb_s >= leg_s:
                # The climb uses the whole leg and does not finish on it.
                reached = alt + fpm * (leg_s / 60.0)
                notes.append(
                    f"{name}: at {fpm:,.0f} ft/min the aircraft reaches "
                    f"{reached:,.0f} ft by the end of this leg, not the "
                    f"{target:,.0f} ft planned")
                segs.append(_Segment(name, CLIMB, leg_s, af.climb_throttle_pct,
                                     alt, reached,
                                     frm.lat_deg, frm.lon_deg,
                                     to.lat_deg, to.lon_deg))
                alt = reached
                continue
            f = climb_s / leg_s
            midlat, midlon = _interp(frm.lat_deg, frm.lon_deg,
                                     to.lat_deg, to.lon_deg, f)
            segs.append(_Segment(f"{name} climb", CLIMB, climb_s,
                                 af.climb_throttle_pct, alt, target,
                                 frm.lat_deg, frm.lon_deg, midlat, midlon))
            segs.append(_Segment(name, CRUISE, leg_s - climb_s,
                                 CRUISE_THROTTLE_PCT, target, target,
                                 midlat, midlon, to.lat_deg, to.lon_deg))
            alt = target

        elif target < alt - 50.0:
            desc_s = (alt - target) / af.descent_fpm * 60.0
            if desc_s >= leg_s:
                segs.append(_Segment(name, DESCENT, leg_s,
                                     af.descent_throttle_pct, alt, target,
                                     frm.lat_deg, frm.lon_deg,
                                     to.lat_deg, to.lon_deg))
                alt = target
                continue
            # Descend at the END of the leg, not the start: an aircraft holds
            # its cruise altitude until it has to come down, because altitude
            # that has been given away has to be bought back with fuel.
            f = (leg_s - desc_s) / leg_s
            midlat, midlon = _interp(frm.lat_deg, frm.lon_deg,
                                     to.lat_deg, to.lon_deg, f)
            segs.append(_Segment(name, CRUISE, leg_s - desc_s,
                                 CRUISE_THROTTLE_PCT, alt, alt,
                                 frm.lat_deg, frm.lon_deg, midlat, midlon))
            segs.append(_Segment(f"{name} descent", DESCENT, desc_s,
                                 af.descent_throttle_pct, alt, target,
                                 midlat, midlon, to.lat_deg, to.lon_deg))
            alt = target
        else:
            segs.append(_Segment(name, CRUISE, leg_s, CRUISE_THROTTLE_PCT,
                                 alt, target,
                                 frm.lat_deg, frm.lon_deg,
                                 to.lat_deg, to.lon_deg))
            alt = target

    # --- approach and landing, over the arrival field ----------------------
    if alt > field_elev_ft + 50.0:
        segs.append(_Segment("APPROACH", DESCENT,
                             (alt - field_elev_ft) / af.descent_fpm * 60.0,
                             af.descent_throttle_pct, alt, field_elev_ft,
                             last.lat_deg, last.lon_deg,
                             last.lat_deg, last.lon_deg))
    segs.append(_Segment("LANDING", LANDING, af.landing_s,
                         af.landing_throttle_pct,
                         field_elev_ft, field_elev_ft,
                         last.lat_deg, last.lon_deg, last.lat_deg, last.lon_deg))
    return segs, notes


# ---------------------------------------------------------------------------
# Limits, taken from the certificate rather than invented
# ---------------------------------------------------------------------------


def persistence_s() -> float:
    """How long an exceedance must HOLD before it is called one.

    THE BUG THIS EXISTS TO FIX, WHICH MADE EVERY SORTIE A NO-GO.
    A take-off advances the throttle to the take-off rating and the engine's
    speed overshoots for a few seconds before it settles: measured here at
    5,806 rpm against a certified 5,800, back to 5,769 within one step. The
    first version of `_judge` emitted a WARNING on that single sample,
    `_verdict` turns any WARNING into a NO-GO, and so every sortie flown --
    including an entirely ordinary one -- came back NOT ACHIEVABLE because of a
    six-rpm transient no operator would ever see.

    A spike is not an exceedance, which is why the live Tier-1 detectors do not
    fire on one either. This reads THEIR number
    (`detectors.tier1.persistence_default_s`) rather than choosing a second one,
    so the planning simulation and the running twin cannot disagree about what
    counts as a limit being exceeded.
    """
    d = config.load_thresholds().get("detectors", {}).get("tier1", {})
    return float(d.get("persistence_default_s", 60))


def _limits(engine_key: str) -> list[tuple]:
    """(key, label, caution, warning, unit, upper) from thresholds.yaml.

    Every number here is read from the same configuration the live twin's
    validator reads. Nothing in this file decides what an engine limit is; a
    second opinion about a certified limit is a defect, not a feature.
    """
    p = config.load_thresholds()["parameters"]
    return [
        ("cht_c", "cylinder head temperature",
         float(p["cht"]["alert_max"]), float(p["cht"]["critical_max"]),
         "°C", True),
        ("coolant_c", "coolant temperature",
         float(p["coolant_temperature"]["alert_max"]),
         float(p["coolant_temperature"]["critical_max"]), "°C", True),
        ("egt_c", "exhaust gas temperature",
         float(p["egt"]["alert_max"]), float(p["egt"]["critical_max"]),
         "°C", True),
        ("oil_temp_c", "oil temperature",
         float(p["oil_temperature"]["alert_max"]),
         float(p["oil_temperature"]["critical_max"]), "°C", True),
        ("rpm", "engine speed",
         float(p["rpm"]["alert_max"]), float(p["rpm"]["critical_max"]),
         "rpm", True),
        ("vibration_rms", "vibration",
         float(p["vibration_rms"]["alert_max"]),
         float(p["vibration_rms"]["critical_max"]), "m/s²", True),
        # A MINIMUM limit: oil pressure falling is the failure, so the sense
        # inverts. Kept in the same table so one loop judges everything, and
        # replaced per sample by `_oil_pressure_limit` -- see below.
        ("oil_press_psi", "oil pressure",
         float(p["oil_pressure"]["alert_min"]),
         float(p["oil_pressure"]["critical_min"]), "psi", False),
    ]


def _rpm_limit(phase: str) -> tuple[float, float]:
    """(caution, warning) engine speed FOR THIS PHASE OF FLIGHT.

    An engine at take-off power is above maximum continuous. That is what a
    take-off rating IS: `configs/thresholds.yaml` declares 5,500 rpm as max
    continuous [TCDS], 5,800 rpm as the take-off speed, and 300 seconds as how
    long the take-off rating may be held -- three numbers describing one rule,
    of which the first version of this file used only the first. Every sortie
    therefore came back carrying a CAUTION for doing exactly what a take-off is
    supposed to do.

    So the take-off roll is judged against the take-off rating, and the rest of
    the flight against maximum continuous. How LONG the rating is held is a
    separate question, checked once in `_verdict` against the same config's
    `takeoff_time_limit_s` rather than sampled here.
    """
    p = config.load_thresholds()["parameters"]["rpm"]
    if phase == TAKEOFF:
        to = float(p.get("takeoff_max_rpm", p["critical_max"]))
        # One number, so no advisory band: at the take-off rating the engine is
        # already at its limit and anything above it is over the limit.
        return to, to
    return float(p["alert_max"]), float(p["critical_max"])


def _oil_pressure_limit(rpm: float) -> tuple[float, float]:
    """(alert, critical) minimum oil pressure AT THIS ENGINE SPEED.

    THE SAME FALSE ALARM THIS PROJECT HAS ALREADY FIXED ONCE, REPEATED HERE.
    The operators manual gives two minima, not one: 2.0 bar (29 psi) above
    3,500 rpm and 0.8 bar (11.6 psi) below it, because pressure falls with pump
    speed and that is the pump working correctly. `configs/thresholds.yaml`
    says so in as many words, and records that the console tile and the twin's
    margin once took `alert_min` at every speed and showed OIL PRESS in red,
    tagged BELOW LIMIT, beside an alert panel correctly reading that every
    parameter was inside its limit.

    Flying the descent and the landing at reduced power reproduced it exactly:
    24.9 psi at an idling engine, reported against the 29 psi that applies to
    an engine at cruise. So the limit is read at the speed it applies to.
    """
    p = config.load_thresholds()["parameters"]["oil_pressure"]
    low_rpm = float(p.get("low_speed_rpm", 3500.0))
    if rpm < low_rpm:
        low = float(p.get("low_speed_min_psi", 11.6))
        # Below the speed break the manual gives ONE minimum, so alert and
        # critical coincide there. Anything under it is a warning outright:
        # there is no advisory band between "legal" and "not legal".
        return low, low
    return (float(p.get("high_speed_min_psi", p["alert_min"])),
            float(p["critical_min"]))


# How long the assessment stands aside for the live twin, and how often. Same
# reasoning as route_cost._fly_leg: an operator planning tomorrow's sortie must
# not degrade the monitoring of the engine flying now.
_YIELD_S = 0.030


def set_yield_s(seconds: float) -> None:
    """How long to stand aside for the live twin between steps.

    Zero when this is running in a process of its OWN, where there is no twin
    to stand aside for and the sleep is pure waste -- see
    `twin_api._run_flight`. Left at its default everywhere else, because in the
    server's own process the twin is sharing this interpreter and must not be
    starved by somebody planning tomorrow's sortie.
    """
    global _YIELD_S
    _YIELD_S = max(0.0, float(seconds))


@dataclass
class MissionFault:
    """A fault that belongs to ONE SIMULATED SORTIE and to nothing else.

    WHY THIS EXISTS, AND WHY IT IS NOT `twin.inject()`
    -------------------------------------------------
    The console could already ask "what does this mission cost the engine that
    is flying now". It could not ask "what would this mission cost if the
    cooling started to go halfway through it" without first injecting that
    fault into the LIVE twin -- which degrades the real engine's health index,
    its remaining life and every alert on every page, permanently and for
    everyone, to answer a hypothetical question.

    A planning question must not have side effects. So the fault is carried
    here, applied to a DegradationEngine this simulation owns, and thrown away
    with it. The live twin is never touched and never knows.

    `onset_s` is seconds INTO THE SORTIE, which is what makes injection during
    playback meaningful: the operator stops the aircraft at T+01:12:30, asks
    for a misfire from there, and the sortie is re-flown with the fault
    appearing at that second and not before.
    """

    mode: str
    severity: float = 0.7
    ramp_hours: float = 0.05
    onset_s: float = 0.0
    channel: str | None = None


def simulate(waypoints: list[Waypoint],
             assumptions: RouteAssumptions | None = None,
             airframe: Airframe | None = None,
             engine_key: str = "rotax_915is",
             factors=None,
             max_samples: int = 700,
             start_engine: bool = True,
             scenario: "MissionFault | None" = None) -> FlightSim:
    """Fly the route and report the flight, not a summary of it.

    `factors` is the degradation of the engine being flown. Passing the live
    twin's own factors is what makes this answer the question worth asking --
    can THIS engine, in the state it is in now, fly this sortie -- rather than
    the one a flight planner already answers for a healthy engine of the type.

    RESOLUTION IS COARSE IN THE CRUISE AND FINE AT THE ENDS. Take-off, climb,
    descent and landing are where the temperatures move; cruise is where they
    sit. Stepping the whole sortie at ten seconds would spend almost all of the
    time resolving a straight line, so cruise runs at a minute a step and the
    rest at ten seconds. Both are far finer than the plan they are resolving.
    """
    from layer2_physics import mvem
    from layer2_physics.degradation import DegradationEngine
    from layer4_core import terrain as terr
    from layer4_core.route_cost import _cruise_fuel_lph, practical_ceiling_ft

    a = assumptions or RouteAssumptions()
    af = airframe or Airframe.load()
    sim = FlightSim()
    sim.assumptions = {**asdict(a), "airframe": asdict(af)}

    if len(waypoints) < 2:
        sim.verdict = "NO_GO"
        sim.reasons.append("a flight needs at least two waypoints")
        return sim

    # --- what the airframe demands, and what this engine can still give ----
    _lph, required_kw, _ok = _cruise_fuel_lph(
        engine_key, None, 10000.0, a, settle_h=0.08, measure_h=0.08)
    # Handing it the reference power just measured, rather than letting it fly
    # the reference sortie a second time to arrive at the same number.
    sim.ceiling_ft = practical_ceiling_ft(factors, a, engine_key,
                                          required_kw=required_kw)
    sim.requested_altitude_ft = max(w.altitude_ft for w in waypoints)

    # Field elevation from the terrain under the departure waypoint, so the
    # take-off starts at the ground rather than at zero. A field at Leh is
    # 10,700 ft up and an aircraft does not take off from sea level there.
    e0 = terr.elevation_m(waypoints[0].lat_deg, waypoints[0].lon_deg)
    field_elev_ft = 0.0 if e0 is None else max(0.0, e0) * FT_PER_M

    segs, notes = build_profile(waypoints, a, af, engine_key, factors,
                                required_kw, field_elev_ft, start_engine)
    sim.reasons.extend(notes)

    total_s = sum(s.duration_s for s in segs)
    sim.duration_s = total_s
    sim.distance_km = sum(great_circle_km(f, t)
                          for f, t in zip(waypoints, waypoints[1:], strict=False))

    # --- fly it ------------------------------------------------------------
    model = mvem.build(engine_key)
    if factors is not None:
        model.degradation = factors
    # THE ENGINE HAS ALREADY BEEN STARTED AND RUN UP. THIS IS NOT A DETAIL.
    #
    # `mvem.build` returns a DEAD engine: omega 0, cylinder heads at 20 degC,
    # no oil pressure. That is the right default for a model, and it is the
    # wrong state to begin a take-off from, because nobody takes off from a
    # stopped engine -- there is a start, a warm-up and a run-up first.
    #
    # Stepping it dead did not merely start the numbers low, it broke the
    # simulation outright. From rest at the take-off throttle the speed
    # integration collapsed to its 1 rad/s floor on any day hotter than about
    # ISA+31 and stayed there: 9.5 rpm, zero power, zero fuel flow, zero oil
    # pressure for the whole sortie, reported as an oil-pressure WARNING and a
    # NO-GO. The engine had not failed the hot day -- it had never been
    # started. On cooler days it survived but overshot, which is where the
    # spurious 5,940 rpm over-speed came from as well.
    #
    # The live twin's own simulator does this on line 442 of engine_sim.py and
    # every physics test does it before measuring anything. Only the two
    # PLANNING modules were stepping a cold engine, which is why this never
    # showed up until a route was flown take-off to landing.
    field_amb = atm.ambient_at(field_elev_ft, isa_deviation_c=a.isa_deviation_c,
                               humidity_pct=a.humidity_pct, airspeed_kmh=0.0)
    if start_engine:
        # STOPPED AND COLD, ON THE STARTER. The sortie begins where a real one
        # begins, and every number in the first minutes -- speed, oil pressure,
        # cylinder head and oil temperature -- rises from a standstill at
        # ambient because the model computes it, not because it is played back.
        model.initialise_cold(field_amb)
    else:
        model.initialise_warm(field_amb)
    deg = DegradationEngine(engine=config.load_engine(engine_key))

    # --- a fault that belongs to this sortie -------------------------------
    #
    # THE LIVE TWIN IS NOT TOUCHED. `deg` is this simulation's own degradation
    # engine; it starts from a COPY of the engine's current wear so the sortie
    # begins where the real engine is, and the fault is injected into that
    # copy. `model.degradation` is then pointed at the copy, so every step of
    # the mean-value model reads factors that the fault is moving -- which is
    # the same mechanism the twin uses (`_apply_faults`), on a different
    # object.
    #
    # WITHOUT A SCENARIO NOTHING CHANGES. The model keeps reading the factors
    # it was handed, exactly as before: a baseline sortie flown today and the
    # same sortie flown before this existed are the same sortie.
    fault_state: dict | None = None
    if scenario is not None:
        import copy as _copy

        from layer2_physics.degradation import FaultMode, InjectedFault

        try:
            fault_mode = FaultMode(scenario.mode)
        except ValueError as exc:
            raise ValueError(f"unknown fault mode {scenario.mode!r}") from exc
        if factors is not None:
            deg.factors = _copy.deepcopy(factors)
        deg.inject(InjectedFault(
            mode=fault_mode,
            onset_hours=max(0.0, float(scenario.onset_s)) / 3600.0,
            severity=float(scenario.severity),
            ramp_hours=max(1e-4, float(scenario.ramp_hours)),
            channel=scenario.channel,
        ))
        model.degradation = deg.factors
        fault_state = {"mode": str(fault_mode), "severity": float(scenario.severity),
                       "ramp_hours": float(scenario.ramp_hours),
                       "onset_s": max(0.0, float(scenario.onset_s)),
                       "channel": scenario.channel, "announced": False}
        sim.assumptions["scenario"] = {k: v for k, v in fault_state.items()
                                       if k != "announced"}

    limits = _limits(engine_key)
    # What each judged quantity is currently doing, and for how long. An event
    # is emitted on the CROSSING and only once the crossing has held -- see
    # `_settle` and `persistence_s`.
    state: dict = {}
    hold_s = persistence_s()
    # The top of the departure and arrival circuit, below which ground
    # clearance is a landing rather than a terrain conflict. The screen height
    # is already the declared boundary between the take-off phase and the
    # en-route climb, so this reuses it rather than choosing a second number.
    circuit_ft = field_elev_ft + af.takeoff_screen_ft
    fuel = a.usable_fuel_l
    sim.reserve_l = 0.0
    t = 0.0
    keep = max(1, int(total_s / 10.0 / max_samples))
    step_i = 0
    peak: dict[str, float] = {}
    # The throttle the previous step was flown at, so a step that CHANGED it --
    # and is therefore mid-transient -- can be kept out of the peaks. Starts at
    # None so the very first step of the sortie is excluded too.
    last_throttle: float | None = None
    saturation_s = {"wastegate": 0.0, "cooling_flap": 0.0}
    terminated = False

    for seg in segs:
        # Fine where the numbers are moving, coarse where they sit: half a
        # second through the start, ten seconds through the climb, descent and
        # landing, a minute through the cruise.
        #
        # THE HALF SECOND IS NOT EXCESS PRECISION. The engine catches within
        # about two seconds, so at a two-second step the very first sample
        # already read 1,603 rpm and 53 psi: the start was over before it could
        # be drawn, and the display jumped from nothing straight to idle. At
        # half a second the crank, the catch and the oil coming up are each
        # several samples long, which is what makes them watchable.
        dt = 60.0 if seg.phase == CRUISE else (0.5 if seg.phase == START
                                               else 10.0)
        n = max(1, int(round(seg.duration_s / dt)))
        dt = seg.duration_s / n
        for i in range(n):
            if i % 2 == 0:
                # See route_cost._fly_leg: a real sleep, not sleep(0), because
                # the twin needs contiguous CPU and sleep(0) does not give it.
                time.sleep(_YIELD_S)
            f = (i + 1) / n
            alt = seg.alt0_ft + (seg.alt1_ft - seg.alt0_ft) * f
            lat, lon = _interp(seg.lat0, seg.lon0, seg.lat1, seg.lon1, f)
            amb = atm.ambient_at(alt, isa_deviation_c=a.isa_deviation_c,
                                 humidity_pct=a.humidity_pct,
                                 airspeed_kmh=a.true_airspeed_kmh)
            out = model.step(dt, throttle_pct=seg.throttle_pct, ambient=amb)
            cht = max(out.cht_c) if out.cht_c else 0.0
            egt = max(out.egt_c) if out.egt_c else 0.0
            burn = out.fuel_flow_lph * (dt / 3600.0)
            fuel -= burn
            t += dt
            deg.advance(dt_hours=dt / 3600.0,
                        oil_temp_c=out.oil_temperature_c, cht_max_c=cht)

            wg = float(getattr(out.turbo_state, "wastegate_fraction", 0.0))
            flap = float(getattr(out, "cooling_flap_fraction", 0.0))
            if wg >= 0.98:
                saturation_s["wastegate"] += dt
            if flap >= 0.98:
                saturation_s["cooling_flap"] += dt

            ground = terr.elevation_m(lat, lon)
            ground_ft = 0.0 if ground is None else max(0.0, ground) * FT_PER_M

            vals = {
                "cht_c": cht, "coolant_c": out.coolant_temperature_c,
                "egt_c": egt, "oil_temp_c": out.oil_temperature_c,
                "rpm": out.rpm, "vibration_rms": out.vibration_rms_m_s2,
                "oil_press_psi": out.oil_pressure_psi,
            }
            # THE WORST OF THE SORTIE, NOT THE WORST ARTEFACT IN IT.
            #
            # The model is stepped at ten seconds and a minute, and a throttle
            # change inside one step overshoots before it settles: measured at
            # 7,483 rpm on an engine certified to 5,800, back to 5,469 by the
            # next sample. That is the time step, not the engine, and printing
            # it as "worst of the sortie" invites a reader to conclude the
            # aircraft was flown 29 % past its redline.
            #
            # `_judge` already refuses to call such a sample an exceedance,
            # because it did not persist. The peaks now agree with it: a sample
            # is eligible only once the throttle has been where it is for a
            # whole step, which is exactly the set of samples the engine is in
            # equilibrium for. Nothing is smoothed and nothing is clipped --
            # the transient samples are still in `samples` for anyone who wants
            # to look at them.
            if seg.throttle_pct == last_throttle:
                for k, v in vals.items():
                    peak[k] = max(peak.get(k, -1e9), v) if k != "oil_press_psi" \
                        else min(peak.get(k, 1e9), v)
            last_throttle = seg.throttle_pct

            s = FlightSample(
                t_s=t, lat_deg=lat, lon_deg=lon, altitude_ft=alt,
                phase=seg.phase, leg=seg.name, throttle_pct=seg.throttle_pct,
                power_kw=out.power_kw, rpm=out.rpm, cht_c=cht, egt_c=egt,
                coolant_c=out.coolant_temperature_c,
                oil_temp_c=out.oil_temperature_c,
                oil_press_psi=out.oil_pressure_psi,
                manifold_bar=out.manifold_pressure_bar,
                fuel_flow_lph=out.fuel_flow_lph, fuel_remaining_l=fuel,
                oat_c=amb.oat_c, terrain_ft=ground_ft,
                clearance_ft=alt - ground_ft,
                wastegate_frac=wg, cooling_flap_frac=flap,
                vibration_rms=out.vibration_rms_m_s2)
            # THE START AND THE WARM-UP ARE ALWAYS KEPT, WHATEVER THE BUDGET.
            #
            # `keep` thins the samples so a long sortie fits in the response,
            # and the start is the shortest and fastest-moving part of the
            # whole flight -- exactly the part thinning would throw away. It is
            # also the part an operator is watching, because it is where every
            # value comes up off zero.
            if (step_i % keep == 0 or i == n - 1
                    or seg.phase in (START, WARMUP)):
                sim.samples.append(s)
            step_i += 1

            # AN ENGINE BEING CRANKED IS NOT IN ANY OPERATING BAND.
            #
            # Below idle it has no oil pressure yet and its speed is whatever
            # the starter gives it. Judging that against limits written for a
            # running engine reports the start as a fault. The warm-up IS
            # judged -- it is a running engine, idling.
            if seg.phase != START:
                _judge(sim, s, vals, limits, state, dt, hold_s, circuit_ft)

            # THE FAULT ANNOUNCES ITSELF ON THE TIMELINE, once, at the moment
            # it begins to express -- so the operator reading the trace can
            # see which of the things that follow are consequences of it.
            if fault_state is not None and not fault_state["announced"]:
                mag = max((m for md, m, _c in deg.active_faults()
                           if str(md) == fault_state["mode"]), default=0.0)
                if mag > 0.0:
                    fault_state["announced"] = True
                    # ADVISORY, NOT CAUTION, AND THE DISTINCTION IS THE POINT.
                    # `_verdict` turns every CAUTION into a reason and downgrades
                    # the sortie to GO WITH LIMITS for it -- so announcing the
                    # injection as a caution made the ANNOUNCEMENT decide the
                    # verdict, and a fault with no consequences still looked
                    # like one. The injection is the premise of the run; its
                    # consequences are judged on their own, like any other.
                    _event(sim, s, "ADVISORY", "FAULT_INJECTED",
                           fault_state["mode"].replace("_", " ").upper()
                           + " injected at severity "
                           + f"{fault_state['severity']:.2f}"
                           + (" on " + fault_state["channel"]
                              if fault_state["channel"] else "")
                           + " — this simulation only, the live engine is not "
                           + "affected",
                           value=round(fault_state["severity"], 3),
                           limit=None, unit="")

            # A SEGMENT THAT ENDS ON A MEASUREMENT RATHER THAN ON THE CLOCK.
            # The warm-up is over when the oil is warm enough to take off on,
            # which is why a cold day spends longer here than a hot one.
            if seg.until_oil_c is not None:
                if out.oil_temperature_c >= seg.until_oil_c:
                    # AN ADVISORY, NOT A REASON. A warm-up that succeeded is
                    # something that happened, not something wrong: putting it
                    # in `reasons` made `_verdict` see a non-empty reason list
                    # and downgrade an otherwise clean sortie from GO to GO
                    # WITH LIMITS for the crime of starting normally.
                    _event(sim, s, "ADVISORY", "WARMED_UP",
                           f"engine started and warmed to "
                           f"{out.oil_temperature_c:.0f} °C oil in "
                           f"{t/60.0:.1f} min, against the "
                           f"{seg.until_oil_c:.0f} °C required before take-off",
                           out.oil_temperature_c, seg.until_oil_c, "°C")
                    sim.conditions["warmup_min"] = round(t / 60.0, 1)
                    break
                if i == n - 1:
                    # The cut-off was reached and the oil never got there. Said
                    # as a finding rather than taken off anyway: an engine that
                    # will not come up to temperature on the ground is telling
                    # you something before it is airborne.
                    _event(sim, s, "CAUTION", "OIL_NEVER_WARMED",
                           f"oil reached only {out.oil_temperature_c:.0f} °C in "
                           f"{seg.duration_s/60.0:.0f} min, below the "
                           f"{seg.until_oil_c:.0f} °C required before take-off",
                           out.oil_temperature_c, seg.until_oil_c, "°C")

            if fuel <= 0.0:
                sim.terminated_at_s = t
                sim.termination = (
                    f"fuel exhausted {t/3600.0:.2f} h into the sortie, "
                    f"{sim.distance_km:.0f} km planned")
                _event(sim, s, "WARNING", "FUEL_EXHAUSTED",
                       "fuel exhausted before the route was complete")
                terminated = True
                break
        if terminated:
            break

    # THE SORTIE IS AS LONG AS IT TURNED OUT TO BE. `total_s` above is the
    # planned length and is used only to budget the sample thinning; the
    # warm-up ends on a temperature and not on the clock, so the real duration
    # is the time actually flown.
    sim.duration_s = t
    sim.fuel_remaining_l = max(0.0, fuel)
    sim.fuel_used_l = a.usable_fuel_l - sim.fuel_remaining_l
    sim.top_of_climb_ft = max((s.altitude_ft for s in sim.samples), default=0.0)
    sim.peak = {k: round(v, 2) for k, v in peak.items()}
    # MERGED, not replaced: the warm-up recorded how long it took while the
    # flight was being flown, and that is a condition of this sortie too.
    sim.conditions = {
        **sim.conditions,
        "isa_deviation_c": a.isa_deviation_c,
        "humidity_pct": a.humidity_pct,
        "field_elevation_ft": round(field_elev_ft, 0),
        "required_kw": round(required_kw, 1),
        "ceiling_ft": round(sim.ceiling_ft, 0),
        "wastegate_saturated_min": round(saturation_s["wastegate"] / 60.0, 1),
        "cooling_flap_saturated_min": round(saturation_s["cooling_flap"] / 60.0, 1),
        # Said out loud, because it is the difference between a report that
        # lists a six-rpm spike and one that does not.
        "persistence_s": hold_s,
    }
    _verdict(sim, a, af, saturation_s)
    return sim


def _event(sim: FlightSim, s: FlightSample, severity: str, code: str,
           message: str, value=None, limit=None, unit="") -> None:
    sim.events.append(FlightEvent(
        t_s=s.t_s, phase=s.phase, severity=severity, code=code,
        message=message, lat_deg=s.lat_deg, lon_deg=s.lon_deg,
        altitude_ft=s.altitude_ft, value=value, limit=limit, unit=unit))


def _settle(state: dict, key: str, level: str, dt: float, hold_s: float) -> bool:
    """Has `level` held on `key` long enough to be worth reporting?

    One helper for every judged quantity, so that a temperature, the ground and
    a saturated control all debounce the same way and none of them can be given
    a quietly different rule later. Returns True exactly once, on the step where
    a NEW level has been continuously present for `hold_s`.
    """
    st = state.setdefault(key, {"level": "OK", "pending": "OK", "held_s": 0.0})
    if level != st["pending"]:
        # FIRST SIGHTING EARNS NO CREDIT, and that is not an off-by-one.
        #
        # A step tells you the value at ONE instant -- the state at its end --
        # not that the value was there for the whole step. Crediting `dt` on
        # first sighting made the rule useless exactly where it was needed
        # most: the cruise steps at sixty seconds are the same length as the
        # sixty-second persistence, so a single sample satisfied it and the
        # throttle-change transient into the cruise (measured at 5,940 rpm,
        # settling to 5,469 by the next sample) was still reported as an
        # over-speed. Time is counted between sightings, so a level must be
        # seen twice, sixty seconds apart, before it has persisted.
        st["pending"], st["held_s"] = level, 0.0
        return False
    st["held_s"] += dt
    if st["held_s"] >= hold_s and level != st["level"]:
        st["level"] = level
        return True
    return False


def _judge(sim: FlightSim, s: FlightSample, vals: dict, limits: list[tuple],
           state: dict, dt: float, hold_s: float, floor_ft: float) -> None:
    """Emit an event when something has CHANGED AND STAYED changed.

    Two conditions, not one. "Changed" keeps a limit that is sitting breached
    from re-announcing itself every step -- a log that repeats itself is a log
    nobody reads. "Stayed changed" keeps a transient out of the record
    altogether; see `persistence_s` for the take-off overshoot that made every
    sortie a NO-GO before this was here.
    """
    for key, label, caution, warning, unit, upper in limits:
        v = vals[key]
        if key == "oil_press_psi":
            caution, warning = _oil_pressure_limit(vals["rpm"])
        elif key == "rpm":
            caution, warning = _rpm_limit(s.phase)
        if upper:
            level = "WARNING" if v >= warning else ("CAUTION" if v >= caution else "OK")
        else:
            level = "WARNING" if v <= warning else ("CAUTION" if v <= caution else "OK")
        if not _settle(state, key, level, dt, hold_s):
            continue
        if level == "OK":
            _event(sim, s, "ADVISORY", f"{key.upper()}_RECOVERED",
                   f"{label} back within limits at {v:.1f} {unit}".strip(),
                   v, None, unit)
        else:
            lim = warning if level == "WARNING" else caution
            over = "above" if upper else "below"
            _event(sim, s, level, f"{key.upper()}_{level}",
                   f"{label} {v:.1f} {unit} — {over} the "
                   f"{'certified' if level == 'WARNING' else 'alert'} "
                   f"limit of {lim:.1f} {unit}".strip(),
                   v, lim, unit)

    # --- the ground ---------------------------------------------------------
    # Terrain is judged here and not only per leg, because the dangerous part
    # of a leg into high ground is the part flown before the aircraft is up.
    #
    # NOT DURING TAKE-OFF OR LANDING, and that was the second false alarm this
    # simulation produced: an aircraft on its take-off roll is sixty-seven feet
    # above the ground because it is ON the ground, and reporting that as a
    # terrain conflict is reporting the runway. Clearance is a cruise, climb and
    # descent question; the two phases that are deliberately at ground level are
    # judged on their own terms, by whether the engine makes take-off power.
    # `floor_ft` is the top of the departure and arrival circuit -- the screen
    # height the take-off phase ends at and the approach comes back down
    # through. Below it the aircraft is DELIBERATELY near the ground, and the
    # approach segment reaching nought feet of clearance over the destination
    # field is a landing, not a terrain conflict. Judging it as one is how the
    # first version reported "0 ft above the ground" on every flight that
    # arrived somewhere.
    if s.phase not in GROUND_PHASES and s.altitude_ft > floor_ft:
        clear = s.clearance_ft
        level = ("WARNING" if clear < 0 else
                 "CAUTION" if clear < 1000.0 else "OK")
        if _settle(state, "_terrain", level, dt, hold_s):
            if level == "WARNING":
                _event(sim, s, "WARNING", "TERRAIN_CONTACT",
                       f"below the ground: terrain {s.terrain_ft:,.0f} ft, "
                       f"aircraft {s.altitude_ft:,.0f} ft",
                       clear, 0.0, "ft")
            elif level == "CAUTION":
                _event(sim, s, "CAUTION", "TERRAIN_CLEARANCE",
                       f"{clear:,.0f} ft above the ground — less than the "
                       f"1,000 ft clearance a route is planned to",
                       clear, 1000.0, "ft")
            else:
                _event(sim, s, "ADVISORY", "TERRAIN_CLEAR",
                       f"terrain clearance restored, {clear:,.0f} ft", clear,
                       1000.0, "ft")

    # --- authority ----------------------------------------------------------
    for name, frac, code in (("wastegate", s.wastegate_frac, "WASTEGATE_SATURATED"),
                             ("cooling flap", s.cooling_flap_frac,
                              "COOLING_FLAP_SATURATED")):
        lvl = "CAUTION" if frac >= 0.98 else "OK"
        if _settle(state, f"_{code}", lvl, dt, hold_s):
            if lvl == "CAUTION":
                _event(sim, s, "CAUTION", code,
                       f"{name} against its stop — the engine is holding this "
                       f"condition with nothing in hand", frac, 1.0, "")
            else:
                _event(sim, s, "ADVISORY", f"{code}_CLEARED",
                       f"{name} off its stop, authority back in hand",
                       frac, 1.0, "")


def _verdict(sim: FlightSim, a: RouteAssumptions, af: Airframe,
             saturation_s: dict) -> None:
    """GO, GO WITH LIMITS, or NO-GO -- and say which finding decided it."""
    warn = [e for e in sim.events if e.severity == "WARNING"]
    caut = [e for e in sim.events if e.severity == "CAUTION"]
    reserve_l = a.usable_fuel_l * 0.0  # filled below from the measured burn
    if sim.duration_s > 0:
        lph = sim.fuel_used_l / (sim.duration_s / 3600.0)
        reserve_l = lph * (af.reserve_minutes / 60.0)
    sim.reserve_l = reserve_l

    if sim.terminated_at_s is not None:
        sim.verdict = "NO_GO"
        sim.reasons.insert(0, sim.termination)
        return

    # THE OTHER HALF OF THE TAKE-OFF RATING. `_rpm_limit` judges the SPEED
    # against 5,800 rpm during the roll; this judges how LONG that rating is
    # held, against the same certificate's five minutes. Checked once here
    # rather than sampled, because it is a property of the profile and not of
    # any instant in it -- and it is a real check, because `takeoff.duration_s`
    # is an editable airframe number and a long field can be set past it.
    limit_s = float(config.load_thresholds()["parameters"]["rpm"]
                    .get("takeoff_time_limit_s", 300))
    if af.takeoff_s > limit_s:
        sim.reasons.append(
            f"the take-off runs {af.takeoff_s:,.0f} s at the take-off rating, "
            f"past the {limit_s:,.0f} s that rating may be held")

    # EVERY NO-GO FINDING IS COLLECTED BEFORE ANY VERDICT IS WRITTEN.
    #
    # The first version assigned `sim.verdict` as it went, and the if/elif
    # chain below it then reassigned unconditionally -- so a route asking for
    # more altitude than the engine can reach was correctly called NO-GO on one
    # line and quietly downgraded to GO WITH LIMITS three lines later, as long
    # as nothing else had raised a WARNING. The verdict is decided once, at the
    # end, from everything found.
    no_go: list[str] = []

    if sim.requested_altitude_ft > sim.ceiling_ft:
        no_go.append(
            f"the route asks for {sim.requested_altitude_ft:,.0f} ft and this "
            f"engine holds cruise power only to {sim.ceiling_ft:,.0f} ft today")

    seen: set[str] = set()
    for e in warn:
        if e.code in seen:
            continue
        seen.add(e.code)
        no_go.append(
            f"{e.message} at {e.t_s/3600.0:.2f} h, {e.altitude_ft:,.0f} ft")

    if sim.fuel_remaining_l < reserve_l:
        no_go.append(
            f"lands with {sim.fuel_remaining_l:.1f} L against a "
            f"{af.reserve_minutes:.0f} minute reserve of {reserve_l:.1f} L")

    if no_go:
        sim.verdict = "NO_GO"
        sim.reasons.extend(no_go)
    elif caut or sim.reasons:
        sim.verdict = "GO_WITH_LIMITS"
        seen = set()
        for e in caut:
            if e.code in seen:
                continue
            seen.add(e.code)
            sim.reasons.append(f"{e.message} at {e.t_s/3600.0:.2f} h")
    else:
        sim.verdict = "GO"
        sim.reasons.append(
            f"flies the route in limits and lands with "
            f"{sim.fuel_remaining_l:.1f} L, against a "
            f"{af.reserve_minutes:.0f} minute reserve of {reserve_l:.1f} L")

    if saturation_s["wastegate"] > 0 or saturation_s["cooling_flap"] > 0:
        sim.reasons.append(
            f"no reserve in hand: wastegate "
            f"{saturation_s['wastegate']/60.0:.0f} min, cooling flap "
            f"{saturation_s['cooling_flap']/60.0:.0f} min")


__all__ = ["Airframe", "FlightEvent", "FlightSample", "FlightSim",
           "build_profile", "climb_rate_fpm", "oil_takeoff_min_c",
           "persistence_s", "simulate", "GROUND_PHASES",
           "START", "WARMUP", "TAKEOFF", "CLIMB", "CRUISE", "DESCENT",
           "LANDING"]
