"""The survival head: P(fail within H hours).

The property that matters is NOT the AUC. It is that the number MEANS
something -- told 0.30, an operator must be right to expect failure about three
times in ten -- and that a horizon with no skill says so instead of publishing
a confident-looking probability.
"""

from __future__ import annotations

import numpy as np
import pytest

from layer3_ai.rul_survival import (
    FORBIDDEN_FEATURES,
    HORIZONS,
    MIN_BRIER_SKILL,
    SurvivalHead,
    format_report,
    labels_for,
)


def _fleet(n_engines=60, per=40, seed=0, signal=1.0):
    """Engines whose RUL is partly readable from two features and partly not.

    `signal` scales how much of the truth is visible, so a test can ask for a
    learnable fleet or an unlearnable one and check the head reports the
    difference honestly.
    """
    rng = np.random.default_rng(seed)
    x, rul, grp = [], [], []
    for e in range(n_engines):
        life = rng.uniform(200.0, 900.0)
        for i in range(per):
            h = life * i / per
            r = life - h
            wear = 1.0 - h / life
            x.append([
                wear * signal + rng.normal(0, 0.05),
                r / 400.0 * signal + rng.normal(0, 0.1),
                rng.normal(0, 1.0),                      # pure noise column
            ])
            rul.append(r)
            grp.append(e)
    return np.array(x), np.array(rul), np.array(grp)


def _split(x, rul, grp):
    """By ENGINE, never by row."""
    eng = np.unique(grp)
    n = len(eng)
    tr = np.isin(grp, eng[: int(n * 0.6)])
    va = np.isin(grp, eng[int(n * 0.6): int(n * 0.8)])
    te = np.isin(grp, eng[int(n * 0.8):])
    return (x[tr], rul[tr]), (x[va], rul[va]), (x[te], rul[te])


def _fitted(seed=0, signal=1.0, horizons=(25.0, 50.0, 100.0)):
    x, rul, grp = _fleet(seed=seed, signal=signal)
    (xt, rt), (xv, rv), (xs, rs_) = _split(x, rul, grp)
    head = SurvivalHead(horizons=horizons, seed=seed)
    head.fit(xt, rt, x_val=xv, rul_val=rv)
    return head, xs, rs_


# ------------------------------------------------------------------ labelling


def test_the_label_is_failure_within_the_horizon():
    rul = np.array([5.0, 25.0, 25.1, 400.0])
    assert list(labels_for(rul, 25.0)) == [1, 1, 0, 0]


def test_horizons_span_a_dispatch_decision_and_beyond():
    """12-18 h is a MALE ISR sortie and the advisory's own bands are 10 h and
    25 h, so the near horizons must exist. The far ones exist so that the loss
    of skill is VISIBLE rather than assumed."""
    assert 12.0 in HORIZONS and 25.0 in HORIZONS
    assert max(HORIZONS) >= 400.0


# -------------------------------------------------------------------- leakage


def test_the_label_source_can_never_be_a_feature():
    """`rul_hours` DEFINES the label. Admitted as a feature it would let the
    model read the answer, and the failure is silent: a superb AUC and a system
    that cannot work on an aircraft."""
    x, rul, grp = _fleet(n_engines=20, per=20)
    (xt, rt), (xv, rv), _ = _split(x, rul, grp)
    head = SurvivalHead(horizons=(50.0,))
    with pytest.raises(ValueError, match="never be model inputs"):
        head.fit(xt, rt, x_val=xv, rul_val=rv,
                 columns=["res_cht", "rul_hours", "cht_max"])


@pytest.mark.parametrize("bad", ["deg_bearing_condition", "chi_true", "censored",
                                 "engine_id", "lab_misfire"])
def test_every_ground_truth_family_is_refused(bad):
    x, rul, grp = _fleet(n_engines=20, per=20)
    (xt, rt), (xv, rv), _ = _split(x, rul, grp)
    with pytest.raises(ValueError):
        SurvivalHead(horizons=(50.0,)).fit(
            xt, rt, x_val=xv, rul_val=rv, columns=["cht_max", bad]
        )


def test_the_forbidden_list_covers_the_label_and_the_target():
    assert "rul_hours" in FORBIDDEN_FEATURES
    assert "rul_target" in FORBIDDEN_FEATURES


# ------------------------------------------------------------- discrimination


def test_a_learnable_fleet_is_learned():
    head, xs, rs_ = _fitted(signal=1.0)
    rep = head.evaluate(xs, rs_)
    h50 = rep.at(50.0)
    assert h50 is not None and h50.auc > 0.80, h50.as_dict()
    assert h50.skilful, h50.reason


def test_probabilities_are_probabilities():
    head, xs, _ = _fitted()
    for h, p in head.predict_proba(xs).items():
        assert p.min() >= 0.0 and p.max() <= 1.0, h


def test_predict_one_matches_predict_proba():
    """Live serving and batch scoring must not diverge."""
    head, xs, _ = _fitted()
    one = head.predict_one(xs[0])
    batch = head.predict_proba(xs[:1])
    for h in batch:
        assert one[h] == pytest.approx(float(batch[h][0]))


# --------------------------------------------------------------- calibration


def test_the_number_means_what_it_says():
    """THE POINT OF THE MODULE. An AUC says the ranking is good; a maintenance
    decision needs the VALUE to be right. Bucket the predictions and check the
    observed failure rate tracks the predicted one."""
    head, xs, rs_ = _fitted(signal=1.0)
    p = head.predict_proba(xs)[50.0]
    y = labels_for(rs_, 50.0)

    # QUANTILE buckets, not fixed-width ones. Equal-width bins assume the
    # predictions are spread evenly across [0, 1]; a well-fitted model on a
    # mostly-healthy fleet piles them near zero, so most bins come back empty
    # and the test measures the estimator's output DISTRIBUTION rather than its
    # calibration. Equal-COUNT bins are how a reliability diagram is built and
    # they compare like with like whichever booster is underneath.
    order = np.argsort(p)
    groups = np.array_split(order, 5)
    checked = 0
    for i, idx in enumerate(groups):
        if len(idx) < 25:
            continue
        checked += 1
        assert abs(p[idx].mean() - y[idx].mean()) < 0.25, (
            f"quintile {i}: predicted {p[idx].mean():.2f}, "
            f"observed {y[idx].mean():.2f}"
        )
    assert checked >= 3, "fixture produced too few populated buckets to judge"


def test_calibration_is_fitted_on_validation_not_on_training_rows():
    """Calibrating on rows the model trained on measures memorisation, and the
    calibration is then optimistic exactly where it is relied on."""
    x, rul, grp = _fleet()
    (xt, rt), (xv, rv), _ = _split(x, rul, grp)
    head = SurvivalHead(horizons=(50.0,))
    rep = head.fit(xt, rt, x_val=xv, rul_val=rv)
    # The report returned by fit() is scored on the VALIDATION rows.
    assert rep.at(50.0).n == len(rv)


# -------------------------------------------------------------------- honesty


def test_a_horizon_with_no_skill_says_so():
    """The far horizon loses skill on the real fleet. It must be reported as
    unskilled rather than published as though the probability meant something.
    """
    head, xs, rs_ = _fitted(signal=0.0)          # nothing is learnable
    rep = head.evaluate(xs, rs_)
    for h in rep.horizons:
        if not np.isnan(h.brier_skill):
            assert not h.skilful, (h.horizon_h, h.as_dict())
            assert "NO SKILL" in h.reason


def test_skill_is_measured_against_predicting_the_base_rate():
    """Beating a constant predictor of the base rate is the minimum bar for the
    number to be worth showing anyone."""
    head, xs, rs_ = _fitted()
    for h in head.evaluate(xs, rs_).horizons:
        if np.isnan(h.brier):
            continue
        assert h.brier_base == pytest.approx(h.base_rate * (1 - h.base_rate))
        assert h.brier_skill == pytest.approx(1.0 - h.brier / h.brier_base)


def test_the_skill_threshold_is_above_zero():
    """A score barely above zero is inside the noise of 73 engines and would be
    a claim the data cannot support."""
    assert MIN_BRIER_SKILL > 0.0


def test_a_horizon_with_too_few_examples_is_refused_not_guessed():
    x, rul, grp = _fleet(n_engines=20, per=20)
    (xt, rt), (xv, rv), _ = _split(x, rul, grp)
    head = SurvivalHead(horizons=(0.001,))       # essentially never true
    rep = head.fit(xt, rt, x_val=xv, rul_val=rv)
    h = rep.at(0.001)
    assert not h.skilful
    assert "too few" in h.reason or "one class" in h.reason


def test_the_report_renders_without_a_fitted_horizon():
    """Formatting must survive a horizon that could not be fitted -- a report
    that crashes on the honest case is one nobody will print."""
    head = SurvivalHead(horizons=(50.0,))
    text = format_report(head.evaluate(np.zeros((3, 3)), np.array([1.0, 2.0, 3.0])))
    assert "horizon" in text
