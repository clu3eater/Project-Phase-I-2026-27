"""Tests for remaining-useful-life estimation -- PRD Part 2 s12.

The first test is the one that matters most. The loss function as the PRD
prints it rewards over-predicting remaining life, which is the single error in
prognostics that puts an aircraft in the air past the point its engine should
have been pulled. That test pins the correction so the printed formula cannot
be restored by someone tidying the code back toward the spec.
"""

from __future__ import annotations

import numpy as np
import pytest
# torch is the OPTIONAL `ml` extra, deliberately kept off the serving
# path so an aircraft image does not carry a training framework. These
# tests genuinely need it, so they SKIP when it is absent rather than
# erroring at collection -- an optional dependency that breaks the whole
# suite is not optional. Found by CI on its first run; locally torch is
# installed, so nobody had ever seen it.
pytest.importorskip("torch")
import torch

from layer3_ai import rul_lstm as rl
from layer3_ai import rul_physics as rp


# ---------------------------------------------------------------------------
# The scoring direction
# ---------------------------------------------------------------------------


def test_over_predicting_remaining_life_costs_more_than_under_predicting():
    """The asymmetry is the whole point of the NASA score.

    Predicting MORE life than there is flies the engine past its pull point.
    Predicting less costs an early inspection. They must not cost the same,
    and the dangerous one must cost more.
    """
    early = rp.nasa_score(np.array([100.0]), np.array([200.0]))   # conservative
    late = rp.nasa_score(np.array([200.0]), np.array([100.0]))    # dangerous
    assert late > early
    assert early > 0.0, "an early prediction is still an error"


def test_the_prd_formula_would_have_rewarded_the_dangerous_error():
    """PRD Part 2 s12.3 prints a formula that contradicts its own intent.

    "Score = exp((RUL_true - RUL_pred)/13) - 1 for RUL_pred < RUL_true", with
    the stated aim of penalising LATE predictions more. It penalises
    RUL_pred < RUL_true -- the conservative case -- and scores over-prediction
    at exactly zero.
    """
    def prd_as_written(pred, true):
        return np.exp((true - pred) / 13.0) - 1.0 if pred < true else 0.0

    assert prd_as_written(100.0, 200.0) > 2000.0   # safe case, huge penalty
    assert prd_as_written(200.0, 100.0) == 0.0     # dangerous case, free
    # The corrected score gets the ordering right.
    assert rp.nasa_score(np.array([200.0]), np.array([100.0])) > rp.nasa_score(
        np.array([100.0]), np.array([200.0])
    )


def test_nasa_score_does_not_overflow_on_a_wild_prediction():
    """An untrained network is easily thousands of hours out.

    exp(7000/10) is not representable, and a NaN in the metric hides whatever
    the model was actually doing.
    """
    s = rp.nasa_score(np.array([9000.0, 0.0]), np.array([10.0, 9000.0]))
    assert np.isfinite(s)


def test_score_time_constants_scale_with_the_rul_horizon():
    """C-MAPSS defines them against 0-130 CYCLES; this RUL is in hours.

    Left unscaled, a 100 h error costs exp(100/10) = 22,000 per sample -- a
    statement about units, not about the model.
    """
    te, tl = rp.score_time_constants(400.0)
    assert tl > 10.0 and te > 13.0
    assert te > tl, "early must stay more forgiving than late"
    base_e, base_l = rp.score_time_constants(130.0)
    assert base_e == pytest.approx(13.0)
    assert base_l == pytest.approx(10.0)


def test_nasa_score_is_summed_over_engines_not_windows():
    """C-MAPSS's "< 500" target counts one prediction per unit.

    Summing over windows instead multiplies it by the windows per engine --
    about 140x here -- and the number then says nothing about the model.
    """
    pred = np.full(300, 100.0)
    true = np.full(300, 120.0)
    unit = np.repeat([1, 2, 3], 100)
    per_window = rp.rul_metrics(pred, true)["nasa_score"]
    per_engine = rp.rul_metrics(pred, true, unit=unit)["nasa_score"]
    assert per_engine < per_window / 50
    assert rp.rul_metrics(pred, true, unit=unit)["nasa_units"] == 3


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_late_fraction_is_reported():
    """An excellent RMSE achieved by over-predicting half the time is not
    safe to field, and no accuracy metric reveals that on its own."""
    m = rp.rul_metrics(np.array([110.0, 90.0]), np.array([100.0, 100.0]))
    assert m["late_fraction"] == pytest.approx(0.5)


def test_mape_ignores_targets_near_zero():
    """MAPE divides by the truth. An engine one hour from the threshold turns
    a one-hour error into an unbounded percentage."""
    pred = np.array([101.0, 2.0])
    true = np.array([100.0, 1.0])
    m = rp.rul_metrics(pred, true, mape_floor_hours=25.0)
    assert m["mape"] == pytest.approx(0.01, abs=1e-6)


def test_piecewise_target_actually_caps():
    """It did not -- both branches of the original were identical, so the cap
    never bound and the network was asked whether a healthy engine had 900 or
    1,100 hours left."""
    raw = np.array([50.0, 300.0, 900.0, 1200.0])
    out = rp.piecewise_rul_target(raw, rul_max=400.0)
    assert list(out) == [50.0, 300.0, 400.0, 400.0]


# ---------------------------------------------------------------------------
# Physics extrapolation
# ---------------------------------------------------------------------------


def test_physics_rul_tracks_a_known_decline():
    est = rp.PhysicsRul()
    rng = np.random.default_rng(0)
    rate = 0.0004
    last = None
    for h in range(0, 700, 2):
        chi = np.clip(0.97 - rate * h + rng.normal(0, 0.005), 0, 1)
        last = est.update(float(chi), float(h))
    actual = (0.97 - 0.60) / rate - 698
    assert last.reportable
    assert abs(last.hours - actual) < 60, (last.hours, actual)


def test_physics_rul_refuses_to_answer_on_a_flat_engine():
    """A huge number reads as reassurance. "Not yet determinable" is honest.

    Before this guard was tightened, a near-zero rate in the denominator
    produced estimates in the tens of thousands of hours and an RMSE of
    19,857 h.
    """
    est = rp.PhysicsRul()
    rng = np.random.default_rng(1)
    last = None
    for h in range(0, 600, 2):
        last = est.update(float(np.clip(0.95 + rng.normal(0, 0.005), 0, 1)), float(h))
    assert not last.reportable
    assert "no measurable degradation" in last.reason


def test_physics_rul_never_exceeds_an_overhaul_interval():
    est = rp.PhysicsRul()
    for h in range(0, 400, 2):
        e = est.update(0.9999 - 1e-6 * h, float(h))
    assert e.hours is None or e.hours <= est.rul_max


def test_physics_rul_interval_is_asymmetric():
    """The rate sits in a denominator, so the same uncertainty stretches
    further upward than downward. That is a real property, not untidiness.

    Uses a fast decline so the estimate sits well clear of the overhaul-interval
    cap -- once the cap binds it truncates the upper bound, which is correct
    behaviour but hides the asymmetry.
    """
    est = rp.PhysicsRul()
    rng = np.random.default_rng(2)
    last = None
    for h in range(0, 300, 2):
        last = est.update(float(np.clip(0.97 - 0.001 * h + rng.normal(0, 0.005), 0, 1)),
                          float(h))
    assert last.reportable
    assert last.upper_hours < est.rul_max, "the cap is binding; pick a faster decline"
    up = last.upper_hours - last.hours
    down = last.hours - last.lower_hours
    assert up > down


def test_physics_rul_upper_bound_is_capped_at_the_overhaul_interval():
    """No engine has more remaining life than a full overhaul interval, and an
    uncapped upper bound reads as reassurance."""
    est = rp.PhysicsRul()
    rng = np.random.default_rng(2)
    last = None
    for h in range(0, 600, 2):
        last = est.update(float(np.clip(0.97 - 0.0004 * h + rng.normal(0, 0.006), 0, 1)),
                          float(h))
    assert last.reportable
    assert last.upper_hours <= est.rul_max


def test_an_estimate_without_an_interval_is_not_reportable():
    """PRD Part 4 s7.4a: a bare RUL number must not reach an operator."""
    assert not rp.RulEstimate(hours=300.0).reportable
    assert rp.RulEstimate(hours=300.0, lower_hours=250.0, upper_hours=380.0).reportable


# ---------------------------------------------------------------------------
# The network
# ---------------------------------------------------------------------------


def test_rul_loss_penalises_the_late_direction_harder():
    true = torch.tensor([200.0])
    early = float(rl.rul_loss(torch.tensor([150.0]), true))
    late = float(rl.rul_loss(torch.tensor([250.0]), true))
    assert late > early, "the loss must not reward over-prediction"


def test_rul_loss_stays_finite_on_a_wild_prediction():
    """Without the internal scaling the score term overflows on the first
    batch and the very first gradient step destroys the weights."""
    v = float(rl.rul_loss(torch.tensor([5000.0]), torch.tensor([10.0])))
    assert np.isfinite(v)


def test_rul_network_shapes():
    net = rl.RulLstm(6)
    assert net(torch.randn(4, 30, 6)).shape == (4,)


def test_predictions_are_never_negative():
    """A negative remaining life is not conservative, it is meaningless."""
    net = rl.RulLstm(4)
    with torch.no_grad():
        net.head[-1].bias.fill_(-500.0)
    assert (rl.predict(net, np.zeros((5, 30, 4), dtype=np.float32)) >= 0).all()


def test_monte_carlo_dropout_produces_a_spread():
    """PRD Part 0 s0.5 point 5 and Part 4 s7.4a both want an interval."""
    net = rl.RulLstm(4)
    x = np.random.default_rng(0).normal(0, 1, (8, 30, 4)).astype(np.float32)
    mean, lo, hi = rl.predict_with_interval(net, x, passes=20)
    assert mean.shape == lo.shape == hi.shape == (8,)
    assert (hi >= lo).all()
    assert (hi - lo).max() > 0, "dropout was not left active"


# ---------------------------------------------------------------------------
# Fusion, PRD Part 2 section 12.5
# ---------------------------------------------------------------------------


def _phys(hours: float, conf: float = 0.8) -> rp.RulEstimate:
    return rp.RulEstimate(hours=hours, lower_hours=hours * 0.8,
                          upper_hours=hours * 1.4, estimator_confidence=conf)


def test_fusion_weights_by_confidence():
    """Within the agreement band, the more confident estimator dominates.

    The two figures must be close enough to be describing the same thing --
    see the disagreement gate below. 100 h against 300 h is not a weighting
    question, it is one of them being wrong.
    """
    high = rl.fuse_rul(100.0, _phys(130.0, conf=0.1), data_confidence=0.9)
    low = rl.fuse_rul(100.0, _phys(130.0, conf=0.9), data_confidence=0.1)
    assert high.hours < low.hours, "the more confident estimator must dominate"


def test_far_apart_estimators_are_not_averaged():
    """Averaging a right answer with a wrong one gives a third wrong answer.

    Measured on held-out engines: the LSTM scored RMSE 117.7 h, the physics
    extrapolation 255.7 h, and the PRD s12.5 weighted average came out at
    151.6 h -- worse than its own best component, because the physics estimate
    carried a hardcoded confidence of 0.8 against the data estimate's earned
    0.545 and so took 59 % of the weight.

    This is the weighted-average dilution defect for the fifth time in this
    project (DEV-45, DEV-72, DEV-80, the mission worst-subsystem rule).
    """
    f = rl.fuse_rul(100.0, _phys(300.0, conf=0.9), data_confidence=0.1)
    assert f.hours == pytest.approx(100.0), "must take the conservative figure"
    assert "disagree" in f.reason
    # And the interval must still span both, so the disagreement is visible
    # rather than hidden behind a single number.
    assert f.upper_hours == pytest.approx(300.0)


def test_close_estimators_are_still_averaged():
    """The gate must not swallow the ordinary case it was not written for."""
    f = rl.fuse_rul(200.0, _phys(240.0, conf=0.5), data_confidence=0.5)
    assert 200.0 < f.hours < 240.0
    assert "disagree" not in f.reason


def test_fusion_uses_whichever_estimator_is_ready():
    only_data = rl.fuse_rul(250.0, rp.RulEstimate(), data_confidence=0.7)
    assert only_data.hours == pytest.approx(250.0)
    assert only_data.source == "data"

    only_phys = rl.fuse_rul(None, _phys(180.0), data_confidence=0.0)
    assert only_phys.hours == pytest.approx(180.0)


def test_fusion_is_conservative_when_both_are_unsure():
    """An averaged RUL that is too high reads as permission to fly."""
    out = rl.fuse_rul(400.0, _phys(100.0, conf=0.0), data_confidence=0.0)
    assert out.hours == pytest.approx(100.0)
    assert "conservative" in out.reason


def test_fusion_reports_nothing_when_neither_estimator_is_ready():
    out = rl.fuse_rul(None, rp.RulEstimate(), data_confidence=0.0)
    assert not out.reportable
    assert "neither" in out.reason


def test_data_confidence_follows_the_prd_formula():
    """c_data = 1 / (1 + val_loss), PRD Part 2 s12.5."""
    assert rl.confidence_from_val_loss(0.0) == pytest.approx(1.0)
    assert rl.confidence_from_val_loss(1.0) == pytest.approx(0.5)
    assert rl.confidence_from_val_loss(9.0) == pytest.approx(0.1)


def test_fused_estimate_keeps_an_interval():
    out = rl.fuse_rul(200.0, _phys(300.0), data_confidence=0.6,
                      data_lower=150.0, data_upper=260.0)
    assert out.reportable
    assert out.lower_hours < out.hours < out.upper_hours


def test_a_late_prediction_costs_more_than_an_early_one_of_equal_size():
    """Late means claiming more remaining life than there is -- the failure
    that puts an aircraft up on an engine that should have been pulled.

    This was very nearly not true. `scale = 100` compresses the exponential
    enough that at a 200 h error the loss charged late only 1.21x early, while
    the NASA score the model is graded by charges 101x. The model was trained
    on a near-symmetric objective, scored on an asymmetric one, and produced a
    +44.5 h LATE bias on the informative band.
    """
    import torch
    from layer3_ai.rul_lstm import rul_loss

    for err in (25.0, 50.0, 100.0, 200.0):
        truth = torch.tensor([300.0])
        early = float(rul_loss(torch.tensor([300.0 - err]), truth))
        late = float(rul_loss(torch.tensor([300.0 + err]), truth))
        assert late > early, (
            f"a {err:.0f} h LATE error costs {late:.3f}, no more than the same "
            f"error early at {early:.3f}"
        )

    # And the asymmetry has to be worth something at the magnitudes that hurt.
    truth = torch.tensor([300.0])
    early = float(rul_loss(torch.tensor([100.0]), truth))
    late = float(rul_loss(torch.tensor([500.0]), truth))
    assert late / early > 2.0, (
        f"late/early at a 200 h error is only {late / early:.2f}x; the "
        f"compression has flattened the asymmetry away again"
    )


def test_late_weight_one_restores_the_symmetric_squared_term():
    """The previous behaviour stays reachable, so the change is measurable
    against it rather than remembered."""
    import torch
    from layer3_ai.rul_lstm import rul_loss

    p, t = torch.tensor([500.0]), torch.tensor([300.0])
    assert float(rul_loss(p, t, late_weight=1.0)) < float(rul_loss(p, t))
