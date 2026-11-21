"""Tests for the autonomous maintenance advisory.

The layers below say what is wrong; this one says what to do, when, and what it
costs. So the tests are about whether the output is something a maintenance
planner could actually schedule against -- ordered by urgency, costed without
double-counting, and silent on a healthy engine.
"""

from __future__ import annotations

import pytest

from layer3_ai.advisory import AdvisoryEngine

HEALTHY = dict(
    oil_quality=0.95, cooling_efficiency=0.98, injector_condition=0.95,
    combustion_efficiency=0.97, bearing_condition=0.96, turbocharger_condition=0.98,
)


def _plan(engine, deg=None, chi=0.95, **kw):
    return engine.recommend(
        degradation={**HEALTHY, **(deg or {})},
        health={"chi": chi},
        residuals=kw.pop("residuals", {}),
        **kw,
    )


@pytest.fixture
def engine():
    return AdvisoryEngine()


# ---------------------------------------------------------------------------
# Silence on a healthy engine
# ---------------------------------------------------------------------------


def test_a_healthy_engine_gets_no_recommendations():
    """A maintenance system that suggests plausible work on a healthy engine
    is a maintenance system that gets switched off.

    The same MIL-STD-411F 4.1.1a discipline the alerting layer follows, applied
    to advice rather than alarms.
    """
    p = _plan(AdvisoryEngine())
    assert p.actions == []
    assert p.total_cost_inr == 0
    assert not p.grounding_required
    assert "No maintenance action" in p.summary


# ---------------------------------------------------------------------------
# Triggers fire on their own evidence
# ---------------------------------------------------------------------------


def test_each_action_fires_only_on_its_own_trigger(engine):
    cases = {
        "A1": dict(oil_quality=0.50),
        "A2": dict(cooling_efficiency=0.60),
        "A3": dict(injector_condition=0.50),
        "A5": dict(bearing_condition=0.60),
        "A6": dict(turbocharger_condition=0.70),
    }
    for action_id, deg in cases.items():
        ids = [a.action_id for a in _plan(engine, deg).actions]
        assert action_id in ids, (action_id, ids)


def test_a_recommendation_names_the_measurement_that_prompted_it(engine):
    """An action that cannot say why it was recommended is one an engineer
    will ignore."""
    p = _plan(engine, dict(cooling_efficiency=0.60))
    a = next(x for x in p.actions if x.action_id == "A2")
    assert "cooling efficiency" in a.reason
    assert a.evidence.get("cooling_efficiency") == pytest.approx(0.60)


def test_a_residual_can_trigger_a_job_with_no_factor_degraded(engine):
    """The residual is observable; the degradation factor is not.

    A fielded system has only the first, so a trigger that can fire on it is
    the one that would work on a real aircraft.
    """
    p = _plan(engine, residuals={"cht": {"usable": True, "mean_delta": 14.0}})
    a = next(x for x in p.actions if x.action_id == "A2")
    assert "hotter than an as-new engine" in a.reason


def test_an_unusable_residual_does_not_trigger_anything(engine):
    """A residual from a stale measurement is not evidence."""
    p = _plan(engine, residuals={"cht": {"usable": False, "mean_delta": 40.0}})
    assert [a.action_id for a in p.actions] == []


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def test_the_action_is_as_urgent_as_its_own_evidence(engine):
    """Grading only on the composite is the dilution DEV-45 and DEV-72 found,
    arriving a third time.

    Measured: an engine whose oil quality had fallen to 0.00 was told to change
    the oil "at the next scheduled maintenance", because three healthy
    subsystems held the composite above 0.80.
    """
    worn = _plan(engine, dict(oil_quality=0.55), chi=0.88).actions[0]
    finished = _plan(engine, dict(oil_quality=0.0), chi=0.88).actions[0]
    assert worn.severity == "ADVISORY"
    assert finished.severity == "WARNING"
    assert finished.due_within_hours is not None and finished.due_within_hours <= 10.0


def test_a_deadline_never_exceeds_the_remaining_life(engine):
    """"Within 50 hours" on an engine with 12 hours left is not a schedule,
    it is a contradiction."""
    p = _plan(engine, dict(cooling_efficiency=0.60), chi=0.75, rul_hours=12.0)
    for a in p.actions:
        if a.due_within_hours is not None:
            assert a.due_within_hours <= 12.0


def test_actions_are_ordered_by_urgency_not_severity(engine):
    """A planner reads top-down. A distant overhaul above an oil change that
    is due now would have them schedule the wrong thing."""
    p = _plan(engine, dict(oil_quality=0.0, turbocharger_condition=0.75), chi=0.85)
    dues = [a.urgency_rank for a in p.actions]
    assert dues == sorted(dues)


# ---------------------------------------------------------------------------
# Cost integrity
# ---------------------------------------------------------------------------


def test_an_overhaul_subsumes_the_individual_jobs(engine):
    """An overhaul drains the oil and cleans the injectors by definition.

    Listing them alongside it double-counted cost and downtime: measured, a
    worn-out engine was quoted Rs 577,000 against the overhaul's own
    Rs 500,000, and a planner reading "complete overhaul AND oil change" would
    rightly stop trusting the rest of the list.
    """
    p = _plan(
        engine,
        dict(oil_quality=0.3, cooling_efficiency=0.45, injector_condition=0.4,
             bearing_condition=0.5, turbocharger_condition=0.7,
             combustion_efficiency=0.85),
        chi=0.45, rul_hours=6.0,
    )
    assert [a.action_id for a in p.actions] == ["A7"]
    assert p.total_cost_inr == pytest.approx(500_000)
    assert set(p.actions[0].subsumes) >= {"A1", "A2", "A3"}
    assert "supersedes" in p.actions[0].reason


def test_the_subsumed_evidence_is_not_thrown_away(engine):
    """A technician opening the engine should know the injectors were already
    suspect, even though the injector job is no longer a separate line."""
    p = _plan(engine, dict(oil_quality=0.3, injector_condition=0.4), chi=0.45)
    assert p.actions[0].subsumes


def test_totals_are_the_sum_of_what_is_actually_listed(engine):
    p = _plan(engine, dict(oil_quality=0.5, cooling_efficiency=0.6), chi=0.75)
    assert p.total_cost_inr == pytest.approx(sum(a.cost_inr for a in p.actions))
    assert p.total_downtime_hours == pytest.approx(
        sum(a.downtime_hours for a in p.actions)
    )


def test_every_action_carries_parts_and_a_procedure(engine):
    """A costed job with no parts list is an estimate, not a work package."""
    p = _plan(engine, dict(oil_quality=0.5, cooling_efficiency=0.6,
                           bearing_condition=0.6), chi=0.75)
    for a in p.actions:
        assert a.parts, a.action_id
        assert a.procedure, a.action_id


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------


def test_an_overhaul_grounds_the_aircraft(engine):
    p = _plan(engine, dict(oil_quality=0.3), chi=0.45, rul_hours=5.0)
    assert p.grounding_required
    assert "GROUND THE AIRCRAFT" in p.summary


def test_ordinary_work_does_not_ground_the_aircraft(engine):
    p = _plan(engine, dict(oil_quality=0.5), chi=0.85)
    assert not p.grounding_required
    assert "GROUND" not in p.summary


def test_the_summary_leads_with_the_most_urgent_job(engine):
    p = _plan(engine, dict(oil_quality=0.0, turbocharger_condition=0.75), chi=0.85)
    assert p.actions[0].name.lower() in p.summary.lower()
    assert "Rs" in p.summary


def test_the_plan_serialises_for_the_api(engine):
    import json

    json.dumps(_plan(engine, dict(oil_quality=0.5), chi=0.8).as_dict())


# ---------------------------------------------------------------------------
# The calibrated failure probability as a trigger
#
# The point RUL is late 55% of the time -- more than half its predictions say
# more life remains than actually does. The survival head is the better-
# measured prognostic (engine-grouped AUC 0.926 at 25 h), and until it was
# wired in it was computed, served and drawn on screen while every maintenance
# decision was still taken on the RUL. These tests pin the wiring so it cannot
# quietly revert to displaying one number and deciding on another.
# ---------------------------------------------------------------------------


def _survival(p, horizon="25h"):
    return {"available": True, "reason": "ready", "horizons": {horizon: p}}


def test_a_high_failure_probability_triggers_the_overhaul(engine):
    """The case the point RUL misses: healthy-looking chi, plenty of RUL."""
    p = _plan(engine, chi=0.85, rul_hours=900.0, survival=_survival(0.80))
    ids = [a.action_id for a in p.actions]
    assert "A7" in ids, "a 80% chance of failure within 25 h must act"


def test_the_reason_states_the_probability_and_the_horizon(engine):
    """An engineer will not action a recommendation that cannot say why."""
    p = _plan(engine, chi=0.85, rul_hours=900.0, survival=_survival(0.80))
    a = next(a for a in p.actions if a.action_id == "A7")
    assert "80%" in a.reason and "25 h" in a.reason


def test_a_low_probability_does_not_trigger_an_overhaul(engine):
    """An overhaul is 400 hours and five lakh. It does not fire on a maybe."""
    p = _plan(engine, chi=0.85, rul_hours=900.0, survival=_survival(0.05))
    assert "A7" not in [a.action_id for a in p.actions]


def test_an_unavailable_head_changes_nothing(engine):
    """Before the first stabilised reading the head has no answer.

    The absence of a probability must not read as a low one -- silence is not
    reassurance -- and it must not crash the tick either.
    """
    for surv in ({"available": False, "reason": "no reading", "horizons": {}},
                 None, {}):
        p = _plan(engine, chi=0.85, rul_hours=900.0, survival=surv)
        assert "A7" not in [a.action_id for a in p.actions]


def test_the_rul_trigger_still_fires_without_any_probability(engine):
    """The wiring is additive: nothing that grounded an engine before stops."""
    p = _plan(engine, chi=0.85, rul_hours=5.0)
    assert "A7" in [a.action_id for a in p.actions]


def test_a_measured_bearing_breach_raises_a_bearing_inspection():
    """thresholds.yaml names `bearing_envelope_above_x: 5.0` as the A5 trigger.
    Only the simulator's hidden bearing factor was checked, so a vibration
    limit MEASURED as reached raised no inspection."""
    from layer3_ai.advisory import AdvisoryEngine
    plan = AdvisoryEngine().recommend(degradation={}, health={"chi": 0.9},
                                      residuals={}, bearing_envelope_x=6.0)
    a5 = [a for a in plan.actions if a.action_id == "A5"]
    assert a5, "no bearing inspection for a measured 6.0x breach"
    # Past its limit is a finding, not planned work.
    assert a5[0].severity == "CAUTION" and a5[0].due_within_hours <= 25.0


def test_a_bearing_inside_its_envelope_raises_nothing():
    from layer3_ai.advisory import AdvisoryEngine
    plan = AdvisoryEngine().recommend(degradation={}, health={"chi": 0.9},
                                      residuals={}, bearing_envelope_x=4.0)
    assert not [a for a in plan.actions if a.action_id == "A5"]


def test_a_measured_misfire_rate_raises_the_spark_plug_action():
    """`misfire_rate_above: 0.05` is the configured A4 trigger. At several
    times the limit the job is a warning, not a caution."""
    from layer3_ai.advisory import AdvisoryEngine
    plan = AdvisoryEngine().recommend(degradation={}, health={"chi": 0.9},
                                      residuals={}, misfire_rate=0.24)
    a4 = [a for a in plan.actions if a.action_id == "A4"]
    assert a4 and a4[0].severity == "WARNING"
    assert a4[0].due_within_hours <= 10.0
    assert "24%" in a4[0].reason


# ---------------------------------------------------------------------------
# Review fixes: SAF-03, SAF-05, SAF-06, SAF-10, SAF-13
# ---------------------------------------------------------------------------


def test_a_mild_trigger_does_not_hide_a_severe_measured_one(engine):
    """SAF-03. A bearing at 12x its envelope floor was booked for routine
    maintenance because a milder bearing-condition trigger matched first."""
    p = _plan(engine, deg={"bearing_condition": 0.69}, bearing_envelope_x=12.0)
    a5 = next(a for a in p.actions if a.action_id == "A5")
    assert a5.severity == "WARNING"
    assert a5.due_within_hours == 10.0
    assert "12.0x" in a5.reason


def test_a_dead_cylinder_grounds_the_aircraft(engine):
    """SAF-06. 100 % cold-cylinder share used to be 'within 10 flight hours'."""
    p = _plan(engine, misfire_rate=1.0)
    assert p.grounding_required
    assert any(a.action_id == "A4" and a.severity == "EMERGENCY" for a in p.actions)


def test_a_bearing_far_past_its_limit_grounds_the_aircraft(engine):
    p = _plan(engine, bearing_envelope_x=50.0)
    assert p.grounding_required


def test_grounding_on_failure_probability_does_not_flicker(engine):
    """SAF-05. Trip above 0.35, release only below 0.25."""
    seq = [
        _plan(engine, survival={"available": True, "horizons": {"25h": p}}).grounding_required
        for p in (0.349, 0.351, 0.349, 0.351, 0.30, 0.24, 0.30)
    ]
    assert seq == [False, True, True, True, True, False, False]


def test_an_unavailable_head_neither_trips_nor_clears(engine):
    _plan(engine, survival={"available": True, "horizons": {"25h": 0.6}})
    held = _plan(engine, survival={"available": False, "horizons": {}})
    assert held.grounding_required


def test_the_measured_limit_is_acted_on_at_the_threshold_itself(engine):
    """SAF-13. The fault tracker calls 5.00 % 'reached'; so must the advisory."""
    p = _plan(engine, misfire_rate=0.05)
    assert any(a.action_id == "A4" for a in p.actions)


def test_measured_limits_come_from_the_action_library(engine):
    from common import config

    trig = {a["id"]: a["trigger"] for a in config.load_thresholds()["advisory"]["actions"]}
    assert engine._SEVERE_ABOVE["misfire_rate"] == float(trig["A4"]["misfire_rate_above"])
    assert engine._SEVERE_ABOVE["bearing_envelope_x"] == float(
        trig["A5"]["bearing_envelope_above_x"])


def test_with_no_component_trigger_the_advisory_repeats_the_health_band(engine):
    """SAF-10. Health 0.55 read 'maintain within 10 h' on the band and 'No
    configured trigger has fired' here."""
    p = _plan(engine, chi=0.55)
    assert not p.actions
    assert "10 flight hours" in p.summary


# ---------------------------------------------------------------------------
# Review fix ML-02: measured triggers a real aircraft actually has
# ---------------------------------------------------------------------------


def test_the_oil_change_falls_due_on_the_maintenance_clock(engine):
    """Oil quality is a simulator factor no sensor reports. The 100 h
    interval (MML-915 i 05-20-00) is what a real aircraft has."""
    early = engine.recommend(degradation={}, health={"chi": 0.95}, residuals={},
                             hours_since_inspection=60.0)
    due = engine.recommend(degradation={}, health={"chi": 0.95}, residuals={},
                           hours_since_inspection=101.0)
    assert not any(a.action_id == "A1" for a in early.actions)
    a1 = next(a for a in due.actions if a.action_id == "A1")
    assert "05-20-00" in a1.reason


def test_a_turbocharger_is_found_from_measurements_alone(engine):
    """No simulator factor passed: boost short of the twin, or exhaust
    hotter than it, is enough."""
    by_boost = engine.recommend(degradation={}, health={"chi": 0.95}, residuals={},
                                boost_drop_fraction=0.25)
    by_egt = engine.recommend(degradation={}, health={"chi": 0.95}, residuals={},
                              egt_rise_c=60.0)
    healthy = engine.recommend(degradation={}, health={"chi": 0.95}, residuals={},
                               boost_drop_fraction=0.02, egt_rise_c=6.0)
    assert any(a.action_id == "A6" for a in by_boost.actions)
    assert any(a.action_id == "A6" for a in by_egt.actions)
    assert not healthy.actions
