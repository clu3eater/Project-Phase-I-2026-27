"""Tests for three-tier score fusion.

The first test is the important one. PRD Part 2 s11.2's trigger logic cannot
raise any alert at all when the rule engine is silent, which is precisely the
situation this whole system was built to handle. That test pins the arithmetic
so the defect cannot be reintroduced by "restoring the spec".

The rest guard the safety property that must NOT be relaxed: a model may say an
engine is degrading, but it may not declare an emergency on its own.
"""

from __future__ import annotations

import numpy as np
import pytest

from layer3_ai import fusion as fu


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------


def test_prd_trigger_logic_alone_cannot_alert_with_the_rules_silent():
    """The arithmetic that forced the fourth path.

    S_rule = 0, so even with both models perfectly certain
    S_final = 0.3(0) + 0.3(1) + 0.4(1) = 0.70 -- below the 0.80 that L4 needs --
    while L3 is gated behind S_rule > 0.50. Nothing can fire.
    """
    f = fu.ScoreFusion()
    s_final = f.w_rule * 0.0 + f.w_stat * 1.0 + f.w_deep * 1.0
    assert s_final == pytest.approx(0.70)
    assert s_final < float(f.l4["s_final_above"]), "L4 would have been reachable"
    assert 0.0 <= float(f.l3["s_rule_above"]), "L3 gate is on the rule score"
    # The PRD's own three conditions, evaluated directly.
    prd_l3 = s_final > float(f.l3["s_final_above"]) and 0.0 > float(f.l3["s_rule_above"])
    prd_l4 = s_final > float(f.l4["s_final_above"])
    prd_l5 = s_final > float(f.l5["s_final_above"])
    assert not (prd_l3 or prd_l4 or prd_l5), "the spec defect has been masked"


def test_the_added_path_alerts_when_both_model_tiers_agree():
    """A residual-based finding with no limit crossed must still reach someone.

    Cooling degradation and lubrication issues are both detected by this system
    with the rule engine correctly silent. Without this path every one of them
    would be discarded on the way to the operator.
    """
    r = fu.ScoreFusion().fuse(rule_level=1, s_statistical=0.85, s_deep=0.80)
    assert r.level >= fu.FusedLevel.CAUTION
    assert r.predictive is True
    assert r.rule_confirmed is False
    assert "no limit exceeded" in r.reason


def test_one_model_tier_alone_is_only_an_advisory():
    """Two independent methods agreeing is evidence; one is an opinion.

    This path has no rule confirmation to fall back on, so it demands more.
    """
    r = fu.ScoreFusion().fuse(rule_level=1, s_statistical=0.90, s_deep=0.10)
    assert r.level == fu.FusedLevel.ADVISORY
    assert r.predictive is True


# ---------------------------------------------------------------------------
# The safety property that must not move
# ---------------------------------------------------------------------------


def test_models_alone_can_never_declare_an_emergency():
    """PRD Part 2 s11.2 requires S_rule = 1.0 for L5, and that gate is correct.

    An emergency grounds an aircraft. It must rest on a certified limit having
    actually been exceeded, not on a model's confidence.
    """
    f = fu.ScoreFusion()
    for stat in (0.95, 1.0):
        for deep in (0.95, 1.0):
            r = f.fuse(rule_level=1, s_statistical=stat, s_deep=deep)
            assert r.level < fu.FusedLevel.EMERGENCY


def test_emergency_requires_the_rule_engine_at_red():
    f = fu.ScoreFusion()
    assert f.fuse(rule_level=5, s_statistical=0.98, s_deep=0.99).level == (
        fu.FusedLevel.EMERGENCY
    )
    # One level down is not enough, however confident the models are.
    assert f.fuse(rule_level=4, s_statistical=0.99, s_deep=0.99).level < (
        fu.FusedLevel.EMERGENCY
    )


def test_a_healthy_engine_produces_no_alert():
    """MIL-STD-411F 4.1.1a reaches the fusion layer too."""
    r = fu.ScoreFusion().fuse(rule_level=1, s_statistical=0.08, s_deep=0.04)
    assert r.level == fu.FusedLevel.NONE
    assert r.predictive is False
    assert r.reason == "all tiers nominal"


def test_predictive_means_no_limit_exceeded_and_nothing_else():
    """A finding the rules confirm must never be labelled predictive.

    Marking it so would tell the operator the exact opposite of the truth.
    """
    f = fu.ScoreFusion()
    silent = f.fuse(rule_level=1, s_statistical=0.85, s_deep=0.80)
    firing = f.fuse(rule_level=3, s_statistical=0.85, s_deep=0.80)
    assert silent.predictive is True
    assert firing.predictive is False
    assert firing.rule_confirmed is True


# ---------------------------------------------------------------------------
# Mechanics
# ---------------------------------------------------------------------------


def test_rule_level_normalisation_matches_the_prd_gate():
    """S_rule > 0.50 must mean "at least ORANGE", which is what breaks L3."""
    assert fu.normalise_rule_level(1) == 0.0     # GREEN
    assert fu.normalise_rule_level(3) == 0.5     # YELLOW -- NOT > 0.5
    assert fu.normalise_rule_level(4) == 0.75    # ORANGE
    assert fu.normalise_rule_level(5) == 1.0     # RED
    assert fu.normalise_rule_level(None) == 0.0


def test_weights_come_from_configuration():
    f = fu.ScoreFusion()
    assert f.w_rule == pytest.approx(0.3)
    assert f.w_stat == pytest.approx(0.3)
    assert f.w_deep == pytest.approx(0.4)
    assert f.w_rule + f.w_stat + f.w_deep == pytest.approx(1.0)


def test_score_is_the_prd_weighted_sum():
    r = fu.ScoreFusion().fuse(rule_level=5, s_statistical=0.5, s_deep=0.25)
    assert r.score == pytest.approx(0.3 * 1.0 + 0.3 * 0.5 + 0.4 * 0.25)


def test_scores_outside_the_unit_interval_are_clipped():
    r = fu.ScoreFusion().fuse(rule_level=1, s_statistical=1.7, s_deep=-0.4)
    assert r.s_statistical == 1.0
    assert r.s_deep == 0.0


def test_low_model_confidence_declares_the_rule_based_fallback():
    """PRD Part 4 s7.4b: the operator must never mistake a threshold trip for
    a learned prediction."""
    f = fu.ScoreFusion()
    assert f.fuse(rule_level=1, s_statistical=0.1, s_deep=0.1,
                  model_confidence=0.95).rule_based_fallback is False
    assert f.fuse(rule_level=1, s_statistical=0.1, s_deep=0.1,
                  model_confidence=0.20).rule_based_fallback is True


# ---------------------------------------------------------------------------
# Combining the two Tier-3 outputs
# ---------------------------------------------------------------------------


def test_deep_combiner_defaults_to_max_because_the_mean_threw_away_recall():
    """The reasoning that first chose the mean was wrong, and measured so.

    Same precision, same zero false-positive rate, 33 points more recall --
    the mean was averaging the autoencoder's sensitivity against a head that
    abstains.
    """
    assert fu.DeepScoreCombiner().mode == "max"
    ae = np.array([4.0])       # ratio against the calibrated healthy threshold
    head = np.array([0.10])
    out = fu.DeepScoreCombiner(mode="max")(ae, head)
    assert out[0] > 0.7, "a confident autoencoder must not be averaged away"


def test_deep_combiner_squashes_the_autoencoder_ratio_onto_the_unit_interval():
    """1.0 means "at the calibrated boundary" and must map to 0.5."""
    out = fu.DeepScoreCombiner(mode="ae")(np.array([0.0, 1.0, 9.0]), np.zeros(3))
    assert out[0] == pytest.approx(0.0)
    assert out[1] == pytest.approx(0.5)
    assert out[2] == pytest.approx(0.9)


def test_deep_combiner_modes_are_all_available_for_measurement():
    ae = np.array([2.0, 0.1])
    head = np.array([0.2, 0.9])
    modes = {m: fu.DeepScoreCombiner(mode=m)(ae, head) for m in
             ("mean", "max", "min", "ae", "head")}
    assert np.all(modes["max"] >= modes["min"])
    assert np.allclose(modes["head"], head)


def test_fuse_many_matches_fuse_one_by_one():
    f = fu.ScoreFusion()
    rng = np.random.default_rng(0)
    n = 200
    levels = rng.integers(1, 6, n)
    stat = rng.random(n)
    deep = rng.random(n)
    batch = f.fuse_many(levels, stat, deep)
    for i in range(n):
        one = f.fuse(rule_level=int(levels[i]), s_statistical=float(stat[i]),
                     s_deep=float(deep[i]))
        assert batch["score"][i] == pytest.approx(one.score)
        assert batch["level"][i] == int(one.level)
        assert bool(batch["predictive"][i]) is one.predictive
