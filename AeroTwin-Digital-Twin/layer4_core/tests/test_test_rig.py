"""Tests for the engine test-rig deployment context (gap G2).

The problem statement names three contexts -- GCS, engine test rigs, and
fleet-level infrastructure. This is the second, and it is judged differently
from the other two: a rig does not predict a failure in flight, it says whether
the engine that just came off the bench meets the numbers on its type
certificate.

Much of what follows is about the difference between a test that is PASSED and
a test that is VALID. A cell that cannot cool, a dyno that lost the speed, or a
schedule with no criteria in it can each produce a green light backed by
nothing, and each of those is checked here.
"""

from __future__ import annotations

import pytest

from layer2_physics.degradation import DegradationFactors
from layer4_core.test_rig import (
    SCHEDULES,
    TestPoint,
    TestRig,
    TestSchedule,
    acceptance_schedule,
    throttle_response_schedule,
)


@pytest.fixture(scope="module")
def healthy():
    return TestRig(seed=3).run(acceptance_schedule())


def _point(rep, name):
    return next(p for p in rep.points if p.name.startswith(name))


# ---------------------------------------------------------------------------
# A sound engine passes, and passes for the right reasons
# ---------------------------------------------------------------------------


def test_a_sound_engine_meets_its_type_certificate(healthy):
    assert healthy.passed
    assert not healthy.cell_limited
    assert all(c["passed"] for c in healthy.checks)


def test_the_rated_points_are_measured_at_the_rated_speeds(healthy):
    """A power figure is not a rating. A power figure AT A SPEED is.

    A bench that lets the engine free-run to wherever the throttle puts it
    measures a different point: measured that way, 92 percent throttle settled
    at 5742 rpm, made 100.9 kW, and was recorded as a pass against the 99 kW
    max-continuous rating 242 rpm below it.
    """
    assert _point(healthy, "MAX CONTINUOUS").rpm == pytest.approx(5500, abs=25)
    assert _point(healthy, "TAKE-OFF").rpm == pytest.approx(5800, abs=25)


def test_power_at_the_rated_points_matches_the_certificate(healthy):
    assert _point(healthy, "MAX CONTINUOUS").power_kw == pytest.approx(99.0, rel=0.06)
    assert _point(healthy, "TAKE-OFF").power_kw == pytest.approx(104.0, rel=0.06)


def test_a_healthy_engine_still_has_cylinder_to_cylinder_scatter(healthy):
    """Without build scatter all four cylinders are numerically identical, EGT
    spread is exactly 0.0 C, and cylinder balance -- one of the few things a
    bench is actually for -- cannot fail. Real scatter puts a healthy engine
    between roughly 7 and 45 C.
    """
    spread = _point(healthy, "TAKE-OFF").egt_spread_c
    assert 3.0 < spread < 120.0


# ---------------------------------------------------------------------------
# Faults are rejected, and rejected distinguishably
# ---------------------------------------------------------------------------


def test_a_worn_engine_fails_on_power_not_on_temperature():
    rep = TestRig(seed=3).run(
        acceptance_schedule(),
        degradation=DegradationFactors(combustion_efficiency=0.88,
                                       injector_condition=0.70),
    )
    assert not rep.passed
    failed = {c["name"] for c in rep.checks if not c["passed"]}
    assert "max-continuous power" in failed
    assert "max-continuous coolant" not in failed


def test_a_blocked_radiator_fails_on_temperature_not_on_power():
    """Severe enough that even a well-cooled cell overheats the engine.

    The severity is 0.30 of the cooling air, not the 0.55 this used to ask for.
    Measured in this cell -- 25 degC air and a 200 km/h-equivalent blower -- 45 %
    of the radiator blocked moves max-continuous coolant by 3.5 degC and nothing
    catches it on temperature, which is a true fact about ground acceptance
    testing rather than a defect: a cell cools better than a hot day. What
    catches it is the cooling authority check below.
    """
    rep = TestRig(seed=3).run(
        acceptance_schedule(), degradation=DegradationFactors(cooling_airflow=0.30)
    )
    assert not rep.passed
    failed = {c["name"] for c in rep.checks if not c["passed"]}
    assert "max-continuous coolant" in failed
    assert "max-continuous power" not in failed
    assert any("did not meet" in n and "coolant" in n for n in rep.notes), rep.notes


def test_a_partly_blocked_radiator_is_caught_by_authority_before_temperature():
    """The blockage a cool cell cannot overheat is still measurable.

    This engine has no thermostat (engine definition, from the manufacturer's
    own manuals), so the airframe's cooling flap holds the coolant -- and what a
    losing radiator spends first is that flap's travel. Measured at max
    continuous: healthy 0.49, 30 % blocked 0.68, 45 % blocked 0.84, while
    coolant moved 98.4 -> 100.3 -> 101.9 degC against a 120 degC limit.
    """
    healthy = TestRig(seed=3).run(acceptance_schedule())
    blocked = TestRig(seed=3).run(
        acceptance_schedule(), degradation=DegradationFactors(cooling_airflow=0.55))

    def at(rep, name):
        return next(p for p in rep.points if p.name == name)

    assert healthy.passed, [c for c in healthy.checks if not c["passed"]]
    assert at(blocked, "MAX CONTINUOUS").coolant_c < 120.0, "the cell did overheat it"
    assert at(blocked, "MAX CONTINUOUS").cooling_flap_fraction >         at(healthy, "MAX CONTINUOUS").cooling_flap_fraction + 0.2
    failed = {c["name"] for c in blocked.checks if not c["passed"]}
    assert failed == {"cooling authority at max continuous"}, failed


def test_a_worn_turbocharger_spends_wastegate_travel_before_it_costs_power():
    """Checked against the manufacturer's own performance table (17 Sep).

    This test used to demand that a turbocharger at condition 0.75 drop
    max-continuous power below 85 kW. The manual says otherwise. Across its 941
    printed operating points, at essentially one plenum pressure (1.49-1.52 bar)
    and 5800 rpm, plenum temperature runs from -24.6 degC to +44.2 degC -- a 22 %
    change in charge density -- and printed power moves 105.0 kW to 104.0 kW,
    about one percent, with fuel flow flat.

    So on this engine a worn compressor does not cost power while the boost
    controller can still hold the plenum: it holds it by CLOSING THE WASTEGATE,
    and what it spends is travel. That is the early signal, and it is the one
    the twin tracks (live.py wastegate closure against the as-new model). Power
    only falls once the wastegate is shut and the boost cannot be held.
    """
    healthy = TestRig(seed=3).run(acceptance_schedule())
    worn = TestRig(seed=3).run(
        acceptance_schedule(),
        degradation=DegradationFactors(turbocharger_condition=0.75),
    )
    h, w = _point(healthy, "MAX CONTINUOUS"), _point(worn, "MAX CONTINUOUS")

    assert w.power_kw == pytest.approx(h.power_kw, rel=0.02), "power should hold"
    assert w.wastegate_fraction < h.wastegate_fraction - 0.03, (
        f"a worn turbo must spend wastegate travel: healthy {h.wastegate_fraction:.2f} "
        f"worn {w.wastegate_fraction:.2f}")

    # Worn far enough that the wastegate runs out, and the power does go.
    spent = TestRig(seed=3).run(
        acceptance_schedule(),
        degradation=DegradationFactors(turbocharger_condition=0.20),
    )
    s_mc = _point(spent, "MAX CONTINUOUS")
    assert s_mc.wastegate_fraction < w.wastegate_fraction
    assert s_mc.power_kw < h.power_kw


# ---------------------------------------------------------------------------
# Was the TEST valid, or only the engine sound?
# ---------------------------------------------------------------------------


def test_an_under_cooled_cell_is_blamed_on_the_cell_not_the_engine():
    """A test cell is not an aircraft standing still.

    Modelled as one, a healthy engine reaches 203 C coolant against a 120 C
    certified limit and would be condemned for a fault it does not have. A real
    cell has dedicated cooling; saying which failed is the difference between a
    week spent on a real fault and a week wasted.
    """
    rep = TestRig(seed=3, cell_cooling_kmh=45.0).run(acceptance_schedule())
    assert not rep.passed
    assert rep.cell_limited
    assert any("FACILITY" in n for n in rep.notes)


def test_an_adequately_cooled_cell_is_not_blamed(healthy):
    assert not healthy.cell_limited
    assert not any("FACILITY" in n for n in healthy.notes)


def test_a_schedule_with_no_criteria_is_not_a_pass():
    """An empty aggregate must never read as success. A schedule defining no
    checks reported PASSED on zero evidence, because all of an empty list is
    true. A green light backed by nothing is worse than a red one.
    """
    rep = TestRig(seed=1).run(
        TestSchedule("BARE", [TestPoint("WARM-UP", 25.0, 30.0, settle_s=0.0)])
    )
    assert rep.checks == []
    assert not rep.passed
    assert any("no acceptance criteria" in n for n in rep.notes)


def test_the_rig_refuses_a_schedule_that_would_breach_the_certificate():
    """The take-off rating carries a five-minute limit, and the engine does not
    distinguish settling time from recorded time. Caught before the run rather
    than reported after it -- by then the engine has already been over-run.
    """
    bad = TestSchedule(
        "BAD",
        [TestPoint("TAKE-OFF", 100.0, 300.0, settle_s=45.0, max_duration_s=300.0)],
    )
    with pytest.raises(ValueError, match="time-limited rating"):
        TestRig().run(bad)


def test_the_shipped_acceptance_schedule_respects_that_limit():
    TestRig().validate(acceptance_schedule())


def test_a_saturated_dynamometer_voids_the_point():
    """Speed not held means the point is not the rated point, so a power
    reading taken from it is a reading of something else.
    """
    sched = TestSchedule(
        "IMPOSSIBLE",
        [TestPoint("MAX CONTINUOUS", 12.0, 30.0, settle_s=10.0, target_rpm=5500.0)],
    )
    rep = TestRig(seed=1).run(sched)
    pt = _point(rep, "MAX CONTINUOUS")
    assert pt.load_saturated
    assert abs(pt.rpm_error) > 100.0
    assert any("void" in n for n in rep.notes)


# ---------------------------------------------------------------------------
# The bench has no aircraft attached to it
# ---------------------------------------------------------------------------


def test_the_cell_supplies_the_operating_point_not_an_air_data_bus():
    """An engine on a stand has no altitude, no airspeed and no vehicle
    management computer. Ambient comes from the facility instead.
    """
    rig = TestRig(cell_temperature_c=42.0, cell_elevation_ft=1400.0)
    amb = rig._ambient()
    assert amb.oat_c == pytest.approx(42.0)
    assert amb.altitude_ft == pytest.approx(1400.0)


def test_a_hot_cell_runs_the_engine_hotter():
    cool = TestRig(seed=3, cell_temperature_c=15.0).run(acceptance_schedule())
    hot = TestRig(seed=3, cell_temperature_c=45.0).run(acceptance_schedule())
    assert (_point(hot, "TAKE-OFF").coolant_c
            > _point(cool, "TAKE-OFF").coolant_c)


# ---------------------------------------------------------------------------
# Throttle response
# ---------------------------------------------------------------------------


def test_throttle_response_is_reported_but_not_graded_against_an_invented_spec():
    """Rotax publishes no acceleration-time figure for the 915 iS, so there is
    no certified number to test against and the rig does not invent one.
    """
    rep = TestRig(seed=1).run(throttle_response_schedule())
    slams = [p for p in rep.points if p.name.startswith("SLAM OPEN")]
    assert all(p.response_time_s is not None for p in slams)
    assert any("no published spec" in c["criterion"] for c in rep.checks)


def test_every_shipped_schedule_is_runnable():
    for factory in SCHEDULES.values():
        TestRig().validate(factory())


def test_the_report_serialises_for_the_api(healthy):
    import json

    json.dumps(healthy.as_dict())
