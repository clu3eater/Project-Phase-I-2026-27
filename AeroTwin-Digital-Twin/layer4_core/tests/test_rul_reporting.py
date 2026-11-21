"""What the operator is shown as remaining life, and how far the models are believed.

Both gates come from measurements taken on 17 Sep on a HEALTHY engine:

  * served before its own inputs were valid, the network's remaining life read
    10.3 h, then 95.9 h, then 346.9 h within six minutes of one flight on an
    engine that had not changed -- and it carried no interval, which PRD Part 4
    s7.4a forbids outright;
  * the console reported "rule-based fallback" and a model confidence of 0
    while the trained network was scoring that same engine at 0.96, because the
    confidence had been wired to the remaining-life TREND, which on a healthy
    engine has nothing to extrapolate by definition.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from layer4_core.live import _detection_confidence, _reportable_life


def _served(hours=None, frozen=False, reason="from the network", lo=None, hi=None):
    return SimpleNamespace(hours=hours, baseline_frozen=frozen, reason=reason,
                           lower_hours=lo, upper_hours=hi,
                           reportable=hours is not None)


def _physics(hours=None, lo=None, hi=None, reason="from the trend"):
    return SimpleNamespace(hours=hours, lower_hours=lo, upper_hours=hi,
                           reason=reason, reportable=hours is not None)


def test_the_network_is_not_believed_until_its_baseline_is_formed():
    hours, source, why = _reportable_life(
        _served(31.6, frozen=False),
        _physics(reason="no measurable degradation trend yet"))
    assert hours is None and source == "none"
    assert "baseline" in why and "no measurable degradation" in why


def test_the_network_is_served_once_its_baseline_is_formed():
    hours, source, _ = _reportable_life(
        _served(410.0, frozen=True), _physics(380.0, 300.0, 520.0))
    assert (hours, source) == (410.0, "lstm")


def test_no_remaining_life_is_shown_without_an_interval():
    """PRD Part 4 s7.4a: a bare remaining life is forbidden."""
    hours, source, why = _reportable_life(
        _served(410.0, frozen=True), _physics(380.0, None, None, "no interval"))
    assert hours is None and source == "none" and "interval" in why


def test_the_network_may_carry_its_own_calibrated_interval():
    """Once train_rul.py saves the conformal multiplier the network needs no
    borrowed bound, and the interval shown belongs to the number beside it."""
    hours, source, _ = _reportable_life(
        _served(410.0, frozen=True, lo=250.0, hi=680.0),
        _physics(reason="no measurable degradation trend yet"))
    assert (hours, source) == (410.0, "lstm")


def test_the_physics_estimate_is_used_when_the_network_is_not_ready():
    hours, source, _ = _reportable_life(_served(), _physics(500.0, 400.0, 700.0))
    assert (hours, source) == (500.0, "physics_fallback")


def test_confidence_describes_the_tier_that_produced_the_score():
    assert _detection_confidence("Tier-3 network (ONNX)", 0.917) == pytest.approx(0.917)
    assert _detection_confidence("health-index proxy (Tier-3 window filling)", 0.917) == 0.0


def test_a_scoring_network_is_not_called_a_rule_based_fallback():
    from layer3_ai.fusion import ScoreFusion

    live = ScoreFusion().fuse(rule_level=0, s_statistical=0.2, s_deep=0.9,
                              model_confidence=_detection_confidence(
                                  "Tier-3 network (ONNX)", 0.917))
    assert live.rule_based_fallback is False
    proxied = ScoreFusion().fuse(rule_level=0, s_statistical=0.2, s_deep=0.9,
                                 model_confidence=_detection_confidence(
                                     "health-index proxy (Tier-3 not loaded)", 0.917))
    assert proxied.rule_based_fallback is True
