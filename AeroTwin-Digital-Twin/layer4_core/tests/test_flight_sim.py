"""Flying a route take-off to landing, and judging what happened on it.

These are the checks that matter for a GO/NO-GO an operator would act on. Most
of them exist because the first version got the answer wrong in a way that was
not obvious from reading it, and each of those is named after the wrong answer
it produces if it regresses:

  * a dead cold engine that never starts on a hot day, and reports the fact as
    an oil-pressure failure;
  * a transient counted as an exceedance, so every sortie is a NO-GO;
  * the take-off rating judged against maximum continuous, so every take-off
    raises a caution for being a take-off;
  * oil pressure at idle judged against the above-3500-rpm minimum;
  * the runway judged as a terrain conflict;
  * a NO-GO finding quietly overwritten by a GO WITH LIMITS on the next line.
"""

from __future__ import annotations

import pytest

from layer4_core.flight_sim import (
    CLIMB,
    CRUISE,
    DESCENT,
    LANDING,
    TAKEOFF,
    START,
    WARMUP,
    Airframe,
    _oil_pressure_limit,
    _rpm_limit,
    _settle,
    oil_takeoff_min_c,
    persistence_s,
    simulate,
)
from layer4_core.route_cost import RouteAssumptions, Waypoint, practical_ceiling_ft

# The same two real places test_route_cost uses, so a distance or a fuel figure
# can be compared between the two modules without a second set of coordinates.
DELHI = Waypoint("DELHI", 28.6139, 77.2090, 2000.0)
JAIPUR = Waypoint("JAIPUR", 26.9124, 75.7873, 15000.0)
SORTIE = [DELHI, JAIPUR, DELHI]


# ---------------------------------------------------------------------------
# The judging rules, which are cheap to test and are where the false alarms were
# ---------------------------------------------------------------------------


def test_the_airframe_is_configuration_and_not_code():
    """Every number the timeline depends on comes from the YAML, not a default."""
    af = Airframe.load()
    assert af.mass_kg > 0 and af.prop_efficiency > 0
    assert af.max_climb_fpm > af.min_climb_fpm > 0
    assert af.takeoff_s > 0 and af.landing_s > 0 and af.reserve_minutes > 0
    assert af.note, "the airframe must say what it is and is not claiming to be"


def test_a_missing_airframe_is_said_out_loud():
    with pytest.raises(FileNotFoundError):
        Airframe.load("no_such_airframe")


def test_persistence_is_the_live_detectors_number():
    """Not a second opinion about what counts as an exceedance."""
    from common import config

    assert persistence_s() == float(
        config.load_thresholds()["detectors"]["tier1"]["persistence_default_s"])


def test_a_single_sample_is_never_an_exceedance():
    """THE BUG: the take-off over-speed that made every sortie a NO-GO.

    In the cruise the step length equals the persistence, so crediting the
    first sighting made one sample enough. A level must be SEEN TWICE, a
    persistence apart, before it has persisted.
    """
    state: dict = {}
    hold = 60.0
    assert _settle(state, "rpm", "WARNING", 60.0, hold) is False  # first sighting
    assert _settle(state, "rpm", "OK", 60.0, hold) is False       # gone again
    # And a level that really does hold is reported, on the second sighting.
    assert _settle(state, "rpm", "WARNING", 60.0, hold) is False
    assert _settle(state, "rpm", "WARNING", 60.0, hold) is True
    # ...and only once, not on every step it stays there.
    assert _settle(state, "rpm", "WARNING", 60.0, hold) is False


def test_ten_second_steps_need_a_full_minute_of_it():
    state: dict = {}
    fired = [_settle(state, "cht_c", "CAUTION", 10.0, 60.0) for _ in range(9)]
    assert fired.count(True) == 1
    # The first sighting earns nothing, so the sixth step of credit is the one
    # that reaches sixty seconds.
    assert fired.index(True) == 6


def test_a_take_off_is_not_a_caution_for_being_a_take_off():
    """The certificate gives 5,500 rpm max continuous AND 5,800 for take-off."""
    to_caution, to_warning = _rpm_limit(TAKEOFF)
    cr_caution, cr_warning = _rpm_limit(CRUISE)
    assert to_caution == to_warning == 5800.0
    assert cr_caution == 5500.0 and cr_warning == 5800.0
    # An ordinary take-off sits above max continuous and below the rating.
    assert cr_caution < 5770.0 < to_caution


def test_oil_pressure_has_two_minima_because_the_manual_does():
    """The same false alarm the console tile already had fixed once."""
    idle_alert, idle_crit = _oil_pressure_limit(2500.0)
    cruise_alert, _ = _oil_pressure_limit(5000.0)
    assert idle_alert == idle_crit == pytest.approx(11.6, abs=0.1)
    assert cruise_alert == pytest.approx(29.0, abs=0.1)
    # 24.9 psi is legal at idle and not legal at cruise -- which is the whole
    # point, and what the single-limit version got wrong on every descent.
    assert 24.9 > idle_alert
    assert 24.9 < cruise_alert


# ---------------------------------------------------------------------------
# Flying it. Slow: these step the mean-value model through a whole sortie.
# ---------------------------------------------------------------------------


def test_a_flight_needs_two_waypoints():
    sim = simulate([DELHI])
    assert sim.verdict == "NO_GO"
    assert "two waypoints" in sim.reasons[0]


@pytest.mark.slow
def test_the_whole_sortie_is_flown_engine_start_to_landing():
    sim = simulate(SORTIE)
    phases = {s.phase for s in sim.samples}
    assert phases == {START, WARMUP, TAKEOFF, CLIMB, CRUISE, DESCENT, LANDING}
    # Ordered in time, starting on the ground and ending on the ground.
    assert [s.t_s for s in sim.samples] == sorted(s.t_s for s in sim.samples)
    assert sim.samples[0].phase == START
    assert sim.samples[-1].phase == LANDING
    # Every sample carries the ground under it, not just the altitude over it.
    assert all(s.clearance_ft == pytest.approx(s.altitude_ft - s.terrain_ft,
                                               abs=0.01)
               for s in sim.samples)


@pytest.mark.slow
def test_an_ordinary_sortie_on_an_ordinary_day_is_a_go():
    """THE BUG: a six-rpm take-off transient turned every sortie into a NO-GO.

    This is the regression test for the whole false-alarm family at once. If
    any of the four judging rules above is broken this route stops being a GO,
    which is the symptom a user would actually report.
    """
    sim = simulate(SORTIE)
    assert sim.verdict == "GO", f"{sim.verdict}: {sim.reasons}"
    assert not [e for e in sim.events if e.severity == "WARNING"]
    assert sim.fuel_remaining_l > sim.reserve_l


@pytest.mark.slow
def test_the_engine_starts_from_stopped_and_cold():
    """WHAT THE OPERATOR ASKED TO SEE: every value coming up off the floor.

    The sortie begins with the crankshaft on the starter and the whole engine
    at ambient. Nothing about the start is scripted -- the speed, the oil
    pressure and the temperatures are the model's own -- so this checks that
    they actually RISE rather than appearing at their running values.
    """
    sim = simulate(SORTIE)
    crank = [s for s in sim.samples if s.phase == START]
    assert len(crank) > 8, "the start must be sampled finely enough to watch"
    first, last = crank[0], crank[-1]
    # Cranking, not running: well under the 1,800 rpm minimum idle.
    assert first.rpm < 1200.0, f"{first.rpm:.0f} rpm is already idling"
    assert first.power_kw < 3.0
    # And by the end of the start it has caught and is idling above the minimum.
    assert last.rpm > 1800.0
    assert last.oil_press_psi > first.oil_press_psi, "oil pressure must build"
    # Cold: the engine begins at the temperature of the air around it.
    assert first.cht_c < first.oat_c + 6.0
    assert first.oil_temp_c < first.oat_c + 6.0


@pytest.mark.slow
def test_the_warm_up_ends_on_the_oil_temperature_the_manual_requires():
    """A measured condition, not an interval this file made up.

    The take-off does not begin until the oil is at the temperature the
    operators manual requires, which is why a cold day warms up for longer.
    """
    sim = simulate(SORTIE)
    warm = [s for s in sim.samples if s.phase == WARMUP]
    assert warm, "there must be a warm-up"
    assert warm[-1].oil_temp_c >= oil_takeoff_min_c() - 1.0
    first_to = next(s for s in sim.samples if s.phase == TAKEOFF)
    assert first_to.oil_temp_c >= oil_takeoff_min_c()
    # The time it took is reported, because it is a property of the day.
    assert sim.conditions["warmup_min"] > 0.0


@pytest.mark.slow
def test_starting_normally_is_not_a_limitation():
    """THE BUG: a successful warm-up was written into `reasons`, and `_verdict`
    treats a non-empty reason list as a finding -- so an entirely clean sortie
    came back GO WITH LIMITS for the crime of starting its engine."""
    sim = simulate(SORTIE)
    assert sim.verdict == "GO", f"{sim.verdict}: {sim.reasons}"
    assert any(e.code == "WARMED_UP" for e in sim.events)


@pytest.mark.slow
def test_a_warm_start_skips_the_ground_running():
    sim = simulate(SORTIE, start_engine=False)
    assert not [s for s in sim.samples if s.phase in (START, WARMUP)]
    assert sim.samples[0].phase == TAKEOFF


@pytest.mark.slow
def test_the_engine_is_running_before_the_take_off_roll():
    """THE BUG: `mvem.build` returns a DEAD engine -- omega 0, heads at 20 degC.

    Stepping it from rest at the take-off throttle collapsed the speed
    integration to its 1 rad/s floor on any day hotter than about ISA+31: 9.5
    rpm and zero oil pressure for the whole sortie, reported as an oil-pressure
    WARNING. The engine had not failed the hot day, it had never been started.

    ISA+35 is inside the problem statement's own 30-50 degC hot-weather band
    (PRD Part 3 s18.3), so this is a condition the system is required to fly.
    """
    sim = simulate(SORTIE, RouteAssumptions(isa_deviation_c=35.0))
    running = [s for s in sim.samples if s.phase not in (START, LANDING)]
    assert min(s.rpm for s in running) > 1000.0, "the engine stopped"
    assert min(s.oil_press_psi for s in running) > 0.0
    assert not [e for e in sim.events if e.code.startswith("OIL_PRESS")
                and e.severity == "WARNING"]


@pytest.mark.slow
def test_a_hot_day_lowers_the_ceiling_without_destroying_it():
    """THE BUG: the cold-engine collapse made ISA+40 report a 4,000 ft ceiling.

    The 915 iS is turbocharged and holds power well above that. A hot day
    should cost the ceiling thousands of feet, not tens of thousands.
    """
    standard = practical_ceiling_ft(None, RouteAssumptions(isa_deviation_c=0.0))
    hot = practical_ceiling_ft(None, RouteAssumptions(isa_deviation_c=40.0))
    assert hot < standard, "a hot day must cost altitude"
    assert hot > 15000.0, f"{hot:,.0f} ft is the cold-engine collapse, not physics"


@pytest.mark.slow
def test_the_runway_is_not_reported_as_terrain():
    """An aircraft on its take-off roll is near the ground on purpose."""
    sim = simulate(SORTIE)
    ground = [e for e in sim.events if e.code.startswith("TERRAIN")
              and e.phase in (TAKEOFF, LANDING)]
    assert not ground, [e.message for e in ground]


@pytest.mark.slow
def test_a_route_above_the_ceiling_stays_a_no_go():
    """THE BUG: the ceiling NO-GO was overwritten by the branch below it.

    30,000 ft is above what this engine holds cruise power at on any day, so
    the verdict must be NO-GO and must SAY that is why -- even though nothing
    on the flight raises a WARNING, which is exactly the case the first version
    downgraded to GO WITH LIMITS.
    """
    high = [Waypoint("DELHI", 28.6139, 77.2090, 2000.0),
            Waypoint("TOP", 26.9124, 75.7873, 30000.0),
            Waypoint("DELHI", 28.6139, 77.2090, 2000.0)]
    sim = simulate(high)
    assert sim.verdict == "NO_GO", f"{sim.verdict}: {sim.reasons}"
    assert any("holds cruise power only to" in r for r in sim.reasons)


@pytest.mark.slow
def test_every_event_carries_the_place_it_happened():
    """An event without a position cannot be drawn on the map it belongs on."""
    sim = simulate(SORTIE, RouteAssumptions(isa_deviation_c=30.0))
    for e in sim.events:
        assert -90.0 <= e.lat_deg <= 90.0 and -180.0 <= e.lon_deg <= 180.0
        assert e.severity in ("ADVISORY", "CAUTION", "WARNING")
        assert e.message and e.code
        assert 0.0 <= e.t_s <= sim.duration_s + 1.0


@pytest.mark.slow
def test_the_conditions_it_was_flown_in_are_reported_with_the_answer():
    """An assumption a reader cannot see is one they cannot disagree with."""
    sim = simulate(SORTIE, RouteAssumptions(isa_deviation_c=15.0,
                                            humidity_pct=80.0))
    assert sim.conditions["isa_deviation_c"] == 15.0
    assert sim.conditions["humidity_pct"] == 80.0
    assert sim.conditions["persistence_s"] == persistence_s()
    assert "airframe" in sim.assumptions
    # The field elevation is read from the terrain, not assumed to be sea level.
    assert sim.conditions["field_elevation_ft"] > 0.0


# `DESCENT` and `CLIMB` are imported for the phase-set assertion above; naming
# them here keeps a linter from removing an import the test depends on.
assert CLIMB and DESCENT
