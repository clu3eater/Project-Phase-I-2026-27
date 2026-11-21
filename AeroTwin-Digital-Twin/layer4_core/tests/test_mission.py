"""Tests for mission reliability -- the third pillar of the PS title.

The question this subsystem answers is operational, not diagnostic: can THIS
engine fly THAT mission. So the tests are about whether the verdict changes
with the mission as well as with the engine, and whether a refusal comes with
something the operator can actually do instead.
"""

from __future__ import annotations

import math

import pytest

from layer4_core.mission import (
    STANDARD_PROFILES,
    MissionProfile,
    MissionReliability,
    Verdict,
    rul_consumption_rate,
)

HEALTHY = {"thermal": 0.97, "mechanical": 0.98, "electrical": 0.96, "combustion": 0.95}


def _assess(mr, profile, **kw):
    base = dict(chi=0.95, subsystems=HEALTHY, rul_hours=400.0,
                rul_lower_hours=320.0, rul_confidence=0.8)
    base.update(kw)
    return mr.assess(profile, **base)


# ---------------------------------------------------------------------------
# The verdict depends on the mission, not only on the engine
# ---------------------------------------------------------------------------


def test_the_same_engine_can_pass_one_mission_and_fail_another():
    """This is the whole reason the subsystem exists.

    A 4-hour transit and an 18-hour endurance patrol are different questions of
    the same airframe on the same day, and a health index alone cannot tell
    them apart.
    """
    mr = MissionReliability()
    short = _assess(mr, MissionProfile("TRANSIT", 4.0), rul_hours=20.0, rul_lower_hours=16.0)
    long = _assess(mr, MissionProfile("ENDURANCE", 18.0), rul_hours=20.0, rul_lower_hours=16.0)
    assert short.verdict is Verdict.GO
    assert long.verdict is Verdict.NO_GO
    assert any("less than" in r for r in long.reasons)


def test_a_healthy_engine_with_ample_life_is_go_for_everything():
    mr = MissionReliability()
    for p in STANDARD_PROFILES:
        a = _assess(mr, p)
        assert a.verdict is Verdict.GO, (p.name, a.reasons)


def test_remaining_life_is_expressed_in_missions():
    """Hours are an engineering unit; missions are the operator's unit."""
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("ISR PATROL", 10.0), rul_lower_hours=45.0)
    assert a.missions_remaining == pytest.approx(4.5)


# ---------------------------------------------------------------------------
# Planning uses the lower bound, not the point estimate
# ---------------------------------------------------------------------------


def test_planning_uses_the_lower_confidence_bound():
    """Planning against the centre of an interval means being wrong half the
    time, and the half you are wrong is the half where the engine quits early.
    """
    mr = MissionReliability()
    p = MissionProfile("ISR PATROL", 10.0)
    optimistic = _assess(mr, p, rul_hours=30.0, rul_lower_hours=30.0)
    honest = _assess(mr, p, rul_hours=30.0, rul_lower_hours=9.0)
    assert optimistic.verdict is Verdict.GO
    assert honest.verdict is Verdict.NO_GO


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------


def test_the_15x_margin_policy_produces_go_with_limits_not_a_refusal():
    """PRD Part 2 advisory R6: below 1.5x the mission duration is a risk, not
    an impossibility. Refusing outright would ground serviceable aircraft."""
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("ISR PATROL", 10.0),
                rul_hours=13.0, rul_lower_hours=12.0)
    assert a.verdict is Verdict.GO_WITH_LIMITS
    assert any("1.5" in r or "policy" in r for r in a.reasons)


def test_an_active_warning_level_limit_is_an_outright_no_go():
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("TRANSIT", 4.0), highest_alert_level=5)
    assert a.verdict is Verdict.NO_GO
    assert any("WARNING" in r for r in a.reasons)


def test_one_unsafe_subsystem_fails_the_mission_whatever_the_composite_says():
    """A weighted average hides a destroyed subsystem behind healthy ones --
    the same dilution DEV-45 found at end-of-life and DEV-72 in the advisory.
    Engines fail at their weakest point, not at their average.
    """
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("TRANSIT", 4.0),
                chi=0.82, subsystems={**HEALTHY, "thermal": 0.30})
    assert a.verdict is Verdict.NO_GO
    assert a.limiting_subsystem == "thermal"
    assert any("UNSAFE" in r for r in a.reasons)


def test_health_at_the_maintenance_threshold_is_a_no_go():
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("TRANSIT", 4.0), chi=0.55)
    assert a.verdict is Verdict.NO_GO


# ---------------------------------------------------------------------------
# A refusal must be actionable
# ---------------------------------------------------------------------------


def test_a_refusal_offers_a_profile_the_engine_can_actually_fly():
    """An operator told "no" without an alternative flies anyway or loses the
    sortie. Naming the shorter profile turns a refusal into a plan."""
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("ENDURANCE", 18.0),
                rul_hours=12.0, rul_lower_hours=9.0)
    assert a.verdict is Verdict.NO_GO
    assert a.recommendations
    assert any("TRANSIT" in r or "maintenance" in r for r in a.recommendations)


def test_recommendations_name_the_limiting_subsystem():
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("ISR PATROL", 10.0),
                chi=0.72, subsystems={**HEALTHY, "thermal": 0.52})
    assert a.verdict is Verdict.GO_WITH_LIMITS
    assert any("thermal" in r.lower() for r in a.recommendations)


def test_every_verdict_carries_its_reasons():
    """PRD Part 4 s7.4c: a recommendation the operator cannot interrogate will
    be overridden by the first person under schedule pressure."""
    mr = MissionReliability()
    for kw in ({}, {"chi": 0.55}, {"highest_alert_level": 4},
               {"rul_hours": 12.0, "rul_lower_hours": 11.0}):
        a = _assess(mr, MissionProfile("ISR PATROL", 10.0), **kw)
        assert a.reasons, kw


def test_no_card_recommends_a_profile_the_plan_cannot_fly():
    """SAF-01. The verdict plans on the LOWER bound, so the alternative must
    be sized from it too. Sized from the central estimate, an engine planned
    at 5 h was told to fly the 18 h ENDURANCE profile -- on every card,
    ENDURANCE's own and the 4 h TRANSIT's included."""
    mr = MissionReliability()
    for p in STANDARD_PROFILES:
        a = _assess(mr, p, rul_hours=30.0, rul_lower_hours=5.0)
        for r in a.recommendations:
            for q in STANDARD_PROFILES:
                if f"fly the {q.name} profile" in r:
                    assert q.duration_hours < p.duration_hours, (p.name, r)
                    assert 5.0 / q.duration_hours >= mr.required_margin, (p.name, r)


def test_the_recommended_alternative_is_itself_flyable():
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("ENDURANCE", 18.0),
                rul_hours=40.0, rul_lower_hours=15.0)
    assert a.verdict is Verdict.NO_GO
    offered = [r for r in a.recommendations if "profile instead" in r]
    assert offered and "ISR PATROL" in offered[0]
    alt = next(p for p in STANDARD_PROFILES if p.name == "ISR PATROL")
    assert _assess(mr, alt, rul_hours=40.0,
                   rul_lower_hours=15.0).verdict is not Verdict.NO_GO


def test_a_health_refusal_offers_no_shorter_profile():
    """A shorter sortie does not cure a health index at the maintenance
    threshold; offering one would turn a grounding into a suggestion."""
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("ENDURANCE", 18.0), chi=0.55,
                rul_hours=12.0, rul_lower_hours=9.0)
    assert a.verdict is Verdict.NO_GO
    assert not any("profile instead" in r for r in a.recommendations)


@pytest.mark.parametrize("chi", [float("nan"), None])
def test_an_undeterminable_health_index_is_never_go(chi):
    """SAF-11. NaN compares False against every threshold, so it used to pass
    every test and read "health nan, all subsystems above 0.60" -- GO."""
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("TRANSIT", 4.0), chi=chi)
    assert a.verdict is Verdict.NO_GO
    assert any("not determinable" in r for r in a.reasons)
    assert math.isfinite(a.success_probability)


def test_an_unknown_subsystem_is_not_reported_as_healthy():
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("TRANSIT", 4.0),
                subsystems={**HEALTHY, "mechanical": float("nan")})
    assert a.verdict is not Verdict.GO
    assert any("mechanical" in r for r in a.reasons)


# ---------------------------------------------------------------------------
# Honesty about what is and is not known
# ---------------------------------------------------------------------------


def test_an_unknown_remaining_life_lowers_confidence_and_says_so():
    """A verdict resting on an RUL estimate is only as good as that estimate."""
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("ISR PATROL", 10.0),
                rul_hours=None, rul_lower_hours=None, rul_confidence=0.9)
    assert a.confidence <= 0.3
    assert any("not yet determinable" in r for r in a.reasons)
    assert a.missions_remaining is None


def test_success_probability_is_bounded_and_falls_with_health():
    mr = MissionReliability()
    good = _assess(mr, MissionProfile("TRANSIT", 4.0))
    bad = _assess(mr, MissionProfile("TRANSIT", 4.0), chi=0.62,
                  subsystems={**HEALTHY, "thermal": 0.45})
    assert 0.0 <= bad.success_probability <= good.success_probability <= 1.0
    assert good.abort_risk == pytest.approx(1.0 - good.success_probability)


def test_a_warning_level_alert_collapses_the_success_probability():
    mr = MissionReliability()
    calm = _assess(mr, MissionProfile("TRANSIT", 4.0))
    alarmed = _assess(mr, MissionProfile("TRANSIT", 4.0), highest_alert_level=5)
    assert alarmed.success_probability < calm.success_probability * 0.4


# ---------------------------------------------------------------------------
# Fleet view of what is flyable
# ---------------------------------------------------------------------------


def test_assess_all_answers_what_can_i_fly_not_just_can_i_fly_this():
    """Presenting only the requested mission answers the wrong question when
    the answer is no."""
    mr = MissionReliability()
    out = mr.assess_all(chi=0.90, subsystems=HEALTHY, rul_hours=14.0,
                        rul_lower_hours=11.0, rul_confidence=0.7)
    assert len(out) == len(STANDARD_PROFILES)
    verdicts = {a.profile: a.verdict for a in out}
    # Short profiles remain flyable when long ones do not.
    assert verdicts["TRANSIT"] is Verdict.GO
    assert verdicts["ENDURANCE"] is Verdict.NO_GO


def test_assessment_serialises_for_the_console():
    mr = MissionReliability()
    d = _assess(mr, MissionProfile("TRANSIT", 4.0)).as_dict()
    assert set(d) >= {"profile", "verdict", "success_probability", "abort_risk",
                      "reasons", "recommendations", "confidence"}
    assert isinstance(d["verdict"], str)


# ---------------------------------------------------------------------------
# Life consumption
# ---------------------------------------------------------------------------


def test_life_consumption_rate_is_relative_to_a_nominal_engine():
    """"2.3 hours of life per mission hour" is what makes a thermal-margin
    argument concrete to someone planning a sortie."""
    slow = rul_consumption_rate(-1e-5, 0.90)
    fast = rul_consumption_rate(-1e-4, 0.90)
    assert fast > slow > 0


def test_life_consumption_is_undefined_for_an_engine_that_is_not_degrading():
    assert rul_consumption_rate(None, 0.95) is None
    assert rul_consumption_rate(0.0, 0.95) is None
    assert rul_consumption_rate(+1e-5, 0.95) is None


def test_a_grounding_advisory_is_a_no_go_on_every_card():
    """SAF-02. The advisory said GROUND while every card said GO."""
    mr = MissionReliability()
    for p in STANDARD_PROFILES:
        a = _assess(mr, p, grounded=True,
                    grounding_reason="60% chance of failure within 25 h")
        assert a.verdict is Verdict.NO_GO
        assert any("grounding" in r for r in a.reasons)
        assert not any("profile instead" in r for r in a.recommendations)


def test_the_overhaul_limit_bounds_planning_life():
    """SAF-07. No estimator may plan past 1200 h / 15 years."""
    mr = MissionReliability()
    a = _assess(mr, MissionProfile("ENDURANCE", 18.0), tbo_remaining_hours=6.0)
    assert a.verdict is Verdict.NO_GO
    b = _assess(mr, MissionProfile("TRANSIT", 4.0), tbo_remaining_hours=0.0)
    assert b.verdict is Verdict.NO_GO
    assert any("overhaul limit" in r for r in b.reasons)
