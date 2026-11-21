"""Tier-2 alarm limits per flight condition (DEV-252).

Measured on held-out engines, one global limit gave a healthy engine 13.6 %
false alarms at part throttle, 10.7 % above 14,000 ft and 10.1 % in air below
-10 degC, against 0-3 % elsewhere. These tests pin the pieces that fix it:
the condition grid, one limit per cell, the mapping of a limit onto the
fusion gate, and the persistence rule the benchmark scores.
"""

from __future__ import annotations

import numpy as np
import pytest

from layer3_ai import features as feat
from layer3_ai import tier2_statistical as t2


def test_the_condition_grid_cells():
    # 60 % throttle, 15,000 ft, -20 degC: band 1, band 2, band 0
    assert t2.regime_code(60.0, 15000.0, -20.0) == 120
    codes = t2.regime_code(np.array([90.0, 40.0]), np.array([1000.0, 8000.0]),
                           np.array([20.0, 0.0]))
    assert list(codes) == [302, 11]


def test_a_missing_condition_has_no_cell():
    """No cell means the global limit, never a guessed condition."""
    assert t2.regime_code(60.0, None, -5.0) == -1
    assert t2.regime_code(np.nan, 5000.0, -5.0) == -1


def test_each_condition_gets_its_own_limit_holding_the_rate():
    rng = np.random.default_rng(0)
    # healthy scores run higher at part throttle (cell 100) than at cruise (cell 200)
    s = np.concatenate([rng.uniform(0.2, 0.9, 5000), rng.uniform(0.0, 0.5, 5000)])
    reg = np.array([100] * 5000 + [200] * 5000)
    healthy = np.ones(len(s), bool)
    per, glob = t2.per_regime_thresholds(s, healthy, reg, 0.05)
    assert per[100] > per[200]
    for cell in (100, 200):
        fpr = (s[reg == cell] > per[cell]).mean()
        assert fpr == pytest.approx(0.05, abs=0.01)
    # the single global limit is right on average and wrong in both cells
    assert (s[reg == 100] > glob).mean() > 0.08
    assert (s[reg == 200] > glob).mean() < 0.01


def test_a_sparse_condition_falls_back_to_the_global_limit():
    s = np.linspace(0, 1, 1000)
    reg = np.array([100] * 990 + [300] * 10)
    per, _ = t2.per_regime_thresholds(s, np.ones(1000, bool), reg, 0.05)
    assert 300 not in per and 100 in per


def test_the_calibrated_limit_lands_on_the_fusion_gate():
    """0 -> 0, limit -> gate, 1 -> 1, order kept."""
    assert t2.score_to_gate(0.87, 0.87, 0.70) == pytest.approx(0.70)
    assert t2.score_to_gate(0.0, 0.87, 0.70) == pytest.approx(0.0)
    assert t2.score_to_gate(1.0, 0.87, 0.70) == pytest.approx(1.0)
    xs = np.linspace(0, 1, 50)
    ys = [t2.score_to_gate(x, 0.6, 0.7) for x in xs]
    assert all(b >= a for a, b in zip(ys, ys[1:], strict=False))
    # below the limit stays below the gate; above it clears the gate
    assert t2.score_to_gate(0.86, 0.87, 0.70) < 0.70 < t2.score_to_gate(0.88, 0.87, 0.70)


def test_persistence_needs_two_of_three_in_the_same_sortie():
    alarm = np.array([1, 0, 1, 1, 0, 1, 0, 1], bool)
    sortie = np.array([0, 0, 0, 0, 0, 1, 1, 1])
    got = t2.persistent(alarm, sortie, 2, 3)
    assert list(got) == [False, False, True, True, True, False, False, True]


def test_the_condition_feature_set_extends_the_shipped_one():
    ext, ops = feat.extended(), feat.extended_ops()
    assert ops.columns[: len(ext)] == ext.columns
    assert ops.columns[len(ext):] == ("throttle_pct", "altitude_ft", "oat_c", "airspeed_kmh")
    ops.validate()
