"""The fault namer's history features (DEV-253): causal, and one definition.

Training replays each engine through the same `SortieHistory` the live twin
runs, so these tests pin the two properties a replay cannot hide: nothing
from later in a sortie, or from a later sortie, reaches a feature; and the
trend features move the way the physics says they should.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from layer3_ai import fault_namer as fn


def _fly(h: fn.SortieHistory, sorties: list[list[float]], hours_per_sortie: float = 2.0):
    for i, samples in enumerate(sorties):
        for v in samples:
            h.observe({"res_cht": v, "res_coolant": 0.0, "res_egt": 0.0}, i * hours_per_sortie)
        h.close_sortie()


def test_the_feature_set_is_exactly_the_declared_columns():
    h = fn.SortieHistory()
    h.observe({"res_cht": 1.0}, 0.0)
    assert set(h.features()) == set(fn.history_columns())


def test_the_sortie_mean_is_of_the_sortie_so_far_never_later():
    h = fn.SortieHistory()
    h.observe({"res_cht": 1.0}, 0.0)
    first = h.features()["sm_res_cht"]
    h.observe({"res_cht": 9.0}, 0.0)
    assert first == pytest.approx(1.0), "a later sample leaked into an earlier feature"
    assert h.features()["sm_res_cht"] == pytest.approx(5.0)


def test_history_features_use_completed_sorties_only():
    h = fn.SortieHistory()
    _fly(h, [[1.0] * 5] * 6)
    before = h.features()["ew_res_cht"]
    h.observe({"res_cht": 50.0}, 20.0)          # the current sortie, still open
    assert h.features()["ew_res_cht"] == pytest.approx(before)
    h.close_sortie()
    assert h.features()["ew_res_cht"] > before  # once it is complete, it counts


def test_a_rising_residual_gives_a_rising_trend():
    h = fn.SortieHistory()
    _fly(h, [[0.5 * i] * 4 for i in range(15)])   # 11-20 back needs 13+ sorties
    f = h.features()
    assert f["slope_res_cht"] == pytest.approx(0.25, rel=1e-6)   # 0.5 per sortie, 2 h each
    assert f["d10_res_cht"] == pytest.approx(7.0 - 1.0)          # last vs mean of sorties 0-4


def test_too_little_history_is_unknown_not_zero():
    h = fn.SortieHistory()
    _fly(h, [[1.0] * 3] * 2)
    f = h.features()
    assert math.isnan(f["slope_res_cht"])
    assert math.isnan(f["d10_res_cht"])


def test_closing_an_empty_sortie_changes_nothing():
    h = fn.SortieHistory()
    _fly(h, [[1.0] * 3] * 3)
    n = len(h.means)
    h.close_sortie()
    h.close_sortie()
    assert len(h.means) == n


class _Stub:
    """A classifier that reports how many inputs it was given."""

    def predict_proba(self, x):
        return np.array([[0.0, x.shape[1] / 1000.0]])


def test_history_is_given_only_to_the_faults_that_chose_it():
    blob = {"classes": ["misfire", "cooling_degradation"],
            "models": {"misfire": _Stub(), "cooling_degradation": _Stub()},
            "choice": {"misfire": "sample", "cooling_degradation": "history"},
            "thresholds": {"misfire": 0.5, "cooling_degradation": 0.5},
            "base_columns": ["a", "b"], "history_columns": fn.history_columns()}
    p = fn.FaultNamer(blob).probabilities({"a": 1.0}, fn.SortieHistory().features())
    assert p["misfire"] == pytest.approx(2 / 1000)
    assert p["cooling_degradation"] == pytest.approx((2 + len(fn.history_columns())) / 1000)


def test_now_is_the_last_minute_not_the_whole_sortie():
    """A live sortie is an hour; its so-far mean diluted a +9 psi fault to +0.6."""
    h = fn.SortieHistory()
    for _ in range(1000):
        h.observe({"res_oil_pressure": 0.0}, 1.0)
    for _ in range(fn.RECENT):
        h.observe({"res_oil_pressure": 9.0}, 1.0)
    assert h.features()["sm_res_oil_pressure"] == pytest.approx(9.0)
    h.close_sortie()
    # ...while the sortie's entry in the history is the whole-sortie mean
    assert h.means[-1]["res_oil_pressure"] == pytest.approx(9.0 * fn.RECENT / (1000 + fn.RECENT))


def test_a_young_engine_is_named_by_the_sample_only_twin():
    blob = {"classes": ["lubrication_issue"],
            "models": {"lubrication_issue": _Stub()},
            "sample_models": {"lubrication_issue": _Stub()},
            "choice": {"lubrication_issue": "history"},
            "thresholds": {"lubrication_issue": 0.40},
            "sample_thresholds": {"lubrication_issue": 0.25},
            "base_columns": ["a", "b"], "history_columns": fn.history_columns()}
    namer = fn.FaultNamer(blob)
    hist = fn.SortieHistory().features()
    young = namer.probabilities({"a": 1.0}, hist, sorties_done=0)
    assert young["lubrication_issue"] == pytest.approx(2 / 1000)      # sample-only width
    assert namer.threshold("lubrication_issue") == pytest.approx(0.25)
    old = namer.probabilities({"a": 1.0}, hist, sorties_done=fn.MIN_HISTORY_SORTIES)
    assert old["lubrication_issue"] == pytest.approx((2 + len(fn.history_columns())) / 1000)
    assert namer.threshold("lubrication_issue") == pytest.approx(0.40)


def test_the_history_faults_answered_by_twins_are_listed_for_the_detector_gate():
    """On a young engine the caller names these only while a detector agrees."""
    blob = {"classes": ["misfire", "overheating_trend"],
            "models": {"misfire": _Stub(), "overheating_trend": _Stub()},
            "sample_models": {"overheating_trend": _Stub()},
            "choice": {"misfire": "sample", "overheating_trend": "history"},
            "thresholds": {"misfire": 0.5, "overheating_trend": 0.05},
            "base_columns": ["a"], "history_columns": fn.history_columns()}
    namer = fn.FaultNamer(blob)
    namer.probabilities({"a": 1.0}, fn.SortieHistory().features(), sorties_done=0)
    assert namer.served_by_twin() == ["overheating_trend"]
    namer.probabilities({"a": 1.0}, fn.SortieHistory().features(), sorties_done=10)
    assert namer.served_by_twin() == []
