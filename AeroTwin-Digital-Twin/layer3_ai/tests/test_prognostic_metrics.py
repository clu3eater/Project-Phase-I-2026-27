"""The prognostics metrics, tested on trajectories whose answer is known.

These metrics exist because RMSE cannot see the failure that matters -- an
estimator that is accurate on average and useless near end of life. So the
tests that matter here are the ones where RMSE and the prognostics metrics
DISAGREE: if a test cannot tell the two apart, it is not testing the reason
this module was written.
"""

from __future__ import annotations

import numpy as np
import pytest

from layer3_ai.prognostic_metrics import (
    DEFAULT_ALPHA,
    EngineTrajectory,
    alpha_bounds,
    alpha_lambda_accuracy,
    convergence,
    evaluate,
    prognostic_horizon_h,
    relative_accuracy,
    trajectories_from_frame,
)


def _traj(pred, true, t=None, eid="E1"):
    true = np.asarray(true, dtype=float)
    if t is None:
        t = np.arange(len(true), dtype=float)
    return EngineTrajectory(eid, np.asarray(t, float), np.asarray(pred, float), true)


def _countdown(n=100, start=400.0):
    """A engine counting down to death at 1 h per sample."""
    return np.linspace(start, 0.0, n)


def test_the_cone_narrows_as_the_engine_dies():
    """The reason these metrics exist: error is judged against life REMAINING.

    40 h of error on 400 h left is a good estimate. The same 40 h on 50 h left
    is a missed failure. A fixed band scores them the same; the cone does not.
    """
    lo, hi = alpha_bounds(np.array([400.0, 50.0]), 0.2)
    assert hi[0] - lo[0] == pytest.approx(160.0)   # +/- 80 h at 400 h left
    assert hi[1] - lo[1] == pytest.approx(20.0)    # +/- 10 h at 50 h left
    assert (hi - lo)[1] < (hi - lo)[0]


def test_a_perfect_estimator_scores_perfectly():
    true = _countdown()
    r = evaluate([_traj(true.copy(), true)])
    assert r.alpha_lambda == 1.0
    assert r.relative_accuracy == pytest.approx(1.0)
    assert r.prognostic_horizon_h > 0


def test_a_useless_estimator_scores_zero_not_nearly_zero():
    """Predicting a constant regardless of state must not earn a horizon."""
    true = _countdown()
    r = evaluate([_traj(np.full_like(true, 400.0), true)])
    assert r.alpha_lambda == 0.0
    assert r.prognostic_horizon_h == 0.0


def test_the_horizon_requires_the_estimate_to_STAY_good():
    """An estimate that is right intermittently has earned nothing.

    An operator cannot act on a number that wanders in and out of tolerance,
    so the horizon is the first index whose ENTIRE suffix is inside the cone.
    """
    true = _countdown(50)
    good = true.copy()
    settled = _traj(good, true)

    # Same estimator, one late excursion far outside the cone.
    flaky = good.copy()
    flaky[-5] = true[-5] + 200.0
    flaky_traj = _traj(flaky, true)

    assert prognostic_horizon_h(flaky_traj) < prognostic_horizon_h(settled)


def test_convergence_separates_two_estimators_RMSE_calls_identical():
    """THE POINT OF THE MODULE, as a test.

    Two estimators with the SAME total error: one wrong early and right at the
    end, one right early and wrong at the end. The first is usable and the
    second is dangerous. RMSE cannot tell them apart -- convergence must.
    """
    true = _countdown(100)
    err = np.zeros(100)
    err[:50] = 60.0
    wrong_early = _traj(true + err, true)
    wrong_late = _traj(true + err[::-1], true)

    rmse_a = float(np.sqrt(np.mean((wrong_early.pred_rul_h - true) ** 2)))
    rmse_b = float(np.sqrt(np.mean((wrong_late.pred_rul_h - true) ** 2)))
    assert rmse_a == pytest.approx(rmse_b), "fixture broken: RMSE must be equal"

    assert convergence(wrong_early) < convergence(wrong_late), (
        "convergence failed to distinguish an estimator that settles from one "
        "that degrades -- which is the only reason to compute it"
    )


def test_alpha_lambda_is_measured_at_the_lambda_point_not_averaged():
    """Right in the middle, wrong everywhere else, must still PASS at 0.5.

    Guards against the metric quietly becoming an average, which would make it
    a worse-behaved RMSE rather than a different question.
    """
    true = _countdown(101)
    pred = true + 300.0
    pred[50] = true[50]
    assert alpha_lambda_accuracy(_traj(pred, true), lam=0.5) is True
    assert alpha_lambda_accuracy(_traj(pred, true), lam=0.25) is False


def test_relative_accuracy_is_a_fraction_of_remaining_life():
    true = np.array([100.0, 100.0])
    # 20 h out of 100 h remaining -> 0.8
    assert relative_accuracy(_traj([80.0, 80.0], true), lam=1.0) == pytest.approx(0.8)


def test_relative_accuracy_floors_at_zero():
    """One hopeless engine must not drag a fleet mean to a negative number."""
    true = np.array([10.0, 10.0])
    assert relative_accuracy(_traj([500.0, 500.0], true), lam=1.0) == 0.0


def test_an_unscorable_engine_is_reported_never_silently_dropped():
    """Dropping it would flatter whichever metric it would have hurt."""
    true = _countdown(60)
    r = evaluate([_traj(true.copy(), true), _traj([1.0], [1.0], eid="E_short")])
    assert r.engines == 2
    assert r.scored_engines == 1
    assert any("E_short" in s for s in r.skipped), r.skipped


def test_late_predictions_are_counted_because_they_are_the_dangerous_ones():
    """Over-predicting remaining life is how an engine is flown past its pull."""
    true = _countdown(50)
    assert evaluate([_traj(true + 30.0, true)]).late_fraction == 1.0
    assert evaluate([_traj(true - 30.0, true)]).late_fraction == 0.0


def test_the_flat_capped_region_must_not_inflate_the_horizon():
    """64.9 % of test labels sit at the 400 h cap. Predicting a constant
    correctly is not prognosis, and an estimator must not be credited with a
    horizon that mostly measures how much of the fixture was flat.

    A PERFECT estimator is used deliberately: the naive horizon then spans the
    engine's whole life, and the difference is purely the trivial region.
    """
    true = np.concatenate([np.full(60, 400.0), np.linspace(400.0, 0.0, 40)])
    traj = _traj(true.copy(), true)

    naive = prognostic_horizon_h(traj, informative_below_h=None)
    honest = prognostic_horizon_h(traj, informative_below_h=399.0)

    assert naive == pytest.approx(99.0), "fixture broken: expected full life"
    assert honest < naive
    # Only the countdown earns credit, not the 60 samples pinned at the cap.
    assert honest == pytest.approx(38.0)


def test_a_constant_prediction_never_earns_a_horizon_even_if_right_at_first():
    """Right while the target is flat, useless once it moves: horizon zero."""
    true = np.concatenate([np.full(60, 400.0), np.linspace(400.0, 0.0, 40)])
    pred = np.full_like(true, 400.0)
    assert prognostic_horizon_h(_traj(pred, true)) == 0.0


def test_trajectories_are_grouped_per_engine_and_time_ordered():
    """Pooling engines into one array discards the ordering these metrics need."""
    ids = np.array(["A", "B", "A", "B"])
    t = np.array([1.0, 5.0, 0.0, 4.0])
    trajs = trajectories_from_frame(ids, t, np.zeros(4), np.ones(4))
    assert len(trajs) == 2
    for tr in trajs:
        assert list(tr.t_h) == sorted(tr.t_h), "trajectory not time-ordered"


def test_alpha_default_is_the_published_convention_not_our_own_number():
    """A target chosen from our own data is one we have already met."""
    assert DEFAULT_ALPHA == 0.2


def test_the_cone_stops_narrowing_at_the_decision_granularity():
    """Without a floor the cone reaches ZERO width and no estimator can pass.

    Measured before the floor existed: an estimator at RMSE 0.165 sigma with
    alpha-lambda 1.00 still scored a horizon of 0.0 h, which says nothing about
    the estimator and everything about the metric.
    """
    lo, hi = alpha_bounds(np.array([400.0, 20.0, 0.0]), 0.2, min_bound_h=10.0)
    assert hi[0] - lo[0] == pytest.approx(160.0)  # alpha dominates
    assert hi[2] - lo[2] == pytest.approx(20.0)   # floor dominates, not zero
    assert (hi - lo).min() == pytest.approx(20.0)


def test_the_horizon_degrades_with_estimator_noise():
    """The metric must RANK estimators, not read zero for everything.

    Measured over 12 seeds, the horizon is a CLIFF rather than a gradient:
    median 99 h at sigma <= 4 h, 5.5 h at sigma 6, and 0 h by sigma 20. That
    is inherent to Saxena's "and stays there" rule -- one excursion anywhere in
    the suffix forfeits the whole horizon, so the metric asks a near-binary
    question of a noisy estimator. Recorded as behaviour to read the number
    with, not smoothed away: an operator cannot act on an estimate that leaves
    tolerance, so the strictness is the point.
    """
    n = 100
    true = np.linspace(400.0, 0.0, n)
    t = np.arange(n, dtype=float)

    def median_horizon(sd):
        return float(np.median([
            prognostic_horizon_h(
                _traj(true + np.random.default_rng(s).normal(0, sd, n), true, t)
            )
            for s in range(12)
        ]))

    tight, mid, loose = median_horizon(2.0), median_horizon(6.0), median_horizon(20.0)
    assert tight >= mid >= loose, (tight, mid, loose)
    assert tight > 50.0, "a near-perfect estimator earned no horizon"
    assert loose == 0.0, "a badly noisy estimator was still credited"
