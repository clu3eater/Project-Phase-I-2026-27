"""The models must say when they are being asked about something new.

Audit 15 Sep, P1-6: nothing checked whether a sample resembled the data the
networks were trained on, so a Tier-3 score carried the same authority on an
engine, an altitude or a failure the fleet never contained as it did in the
middle of the training set.

The fit is on EVERYTHING the networks saw, healthy and faulted. Fitted on
healthy rows alone it becomes a novelty detector for faults instead: measured
that way it called 75.9 % of held-out FAULTED rows unfamiliar, which would
declare the models inapplicable exactly when a fault arrived.
"""

from __future__ import annotations

import numpy as np
import pytest

from layer3_ai.ood import OodDetector


@pytest.fixture(scope="module")
def fitted():
    rng = np.random.default_rng(0)
    # Two correlated channels and four independent ones, as engine features are.
    n = 4000
    a = rng.normal(0.0, 1.0, n)
    x = np.column_stack([a, a * 0.9 + rng.normal(0.0, 0.2, n),
                         rng.normal(5.0, 2.0, n), rng.normal(-3.0, 0.5, n),
                         rng.normal(0.0, 1.0, n), rng.normal(100.0, 10.0, n)])
    cols = ["res_cht", "res_cht_mean", "rpm", "res_oil_p", "vib", "egt"]
    return OodDetector.fit(x, cols), x, cols


def test_a_sample_from_the_training_distribution_is_familiar(fitted):
    det, x, _ = fitted
    inside = [det.verdict(row).inside for row in x[:500]]
    assert np.mean(inside) > 0.99


def test_a_channel_outside_everything_ever_seen_is_flagged_and_named(fitted):
    det, x, cols = fitted
    row = x[0].copy()
    row[2] = 500.0                      # an rpm feature far beyond the fleet's
    v = det.verdict(row)
    assert not v.inside
    assert "rpm" in v.outside_channels


def test_a_combination_never_seen_is_caught_even_when_each_value_is_ordinary(fitted):
    """The reason for a covariance and not a per-channel band.

    Both channels move together in the fleet. A sample that puts one high while
    the other is low is ordinary in each column and impossible in the pair, and
    only the distance sees it.
    """
    det, x, _ = fitted
    row = x[0].copy()
    row[0], row[1] = 2.5, -2.5
    v = det.verdict(row)
    assert not v.inside, v.as_dict()
    assert v.outside_channels == (), "each value on its own is within the fleet's range"


def test_the_artifact_survives_a_round_trip(tmp_path, fitted):
    det, x, _ = fitted
    det.save(tmp_path)
    back = OodDetector.load(tmp_path)
    assert back.threshold == pytest.approx(det.threshold)
    for row in x[:50]:
        assert back.verdict(row).distance == pytest.approx(det.verdict(row).distance)


def test_it_refuses_to_fit_on_too_little_data():
    with pytest.raises(ValueError, match="not enough"):
        OodDetector.fit(np.zeros((10, 3)), ["a", "b", "c"])
