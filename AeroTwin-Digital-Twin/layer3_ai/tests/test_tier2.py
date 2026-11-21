"""Tests for the feature contract and the Tier-2 statistical ensemble.

Two groups, and the first matters more than it looks.

The FEATURE tests guard against training/serving skew -- the failure where the
model keeps producing confident numbers that are simply about a different
engine than the one on the aircraft. It is silent, it is common, and the only
defence is that both paths compute features from one definition. So there is a
test that the batch path and the single-sample path agree exactly, and a test
that no ground-truth column can reach a model input.

The DETECTOR tests check that each algorithm does the thing it was chosen for,
on data where the right answer is known by construction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from layer3_ai import features as feat
from layer3_ai import tier2_statistical as t2


# ---------------------------------------------------------------------------
# The feature contract
# ---------------------------------------------------------------------------


def _frame(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cols = {c: rng.normal(0.0, 1.0, n) for c in feat.extended().columns}
    cols["rpm"] = rng.normal(4800, 200, n)
    cols["cht_max"] = rng.normal(108, 4, n)
    cols["egt_max"] = rng.normal(840, 30, n)
    cols["oil_pressure"] = rng.normal(52, 4, n)
    cols["oil_temperature"] = rng.normal(98, 5, n)
    cols["fuel_flow"] = rng.normal(23, 2, n)
    cols["vibration_rms_total"] = rng.normal(2.4, 0.3, n)
    cols["engine_id"] = np.repeat([1, 2], n // 2)
    cols["flight_hours"] = np.tile(np.linspace(0, 400, n // 2), 2)
    cols["chi_true"] = np.full(n, 0.95)
    cols["any_fault"] = np.zeros(n)
    cols["censored"] = np.zeros(n, dtype=bool)
    cols["rul_hours"] = np.tile(np.linspace(400, 0, n // 2), 2)
    return pd.DataFrame(cols)


def test_prd7_is_the_seven_channels_the_prd_names():
    fs = feat.prd7()
    assert len(fs) == 7
    assert fs.columns == (
        "rpm", "cht_max", "egt_max", "oil_pressure",
        "oil_temperature", "fuel_flow", "vibration_rms_total",
    )


def test_extended_adds_residuals_to_the_prd_baseline():
    base, ext = feat.prd7(), feat.extended()
    assert set(base.columns) < set(ext.columns)
    assert any(c.startswith("res_") for c in ext.columns)


def test_ground_truth_can_never_reach_a_model_input():
    """A single leaked label column lets a model read the answer off its input.

    The reported accuracy would then be excellent and meaningless, and nothing
    else in the pipeline would flag it.
    """
    for name in feat.FEATURE_SETS:
        feat.FEATURE_SETS[name]().validate()

    leaky = feat.FeatureSet(
        name="leaky", columns=("rpm", "chi_true"), centres=(0.0, 0.0), scales=(1.0, 1.0)
    )
    with pytest.raises(ValueError, match="leaks ground truth"):
        leaky.validate()

    for col in ("deg_cooling_efficiency", "lab_misfire", "rul_hours", "engine_id"):
        bad = feat.FeatureSet(name="b", columns=("rpm", col), centres=(0.0, 0.0), scales=(1.0, 1.0))
        with pytest.raises(ValueError):
            bad.validate()


def test_batch_and_single_sample_paths_agree_exactly():
    """Training/serving skew is silent. This is the test that catches it."""
    df = _frame(20)
    fs = feat.extended()
    batch = feat.build(df, fs)
    for i in range(len(df)):
        one = feat.build_one(df.iloc[i].to_dict(), fs)
        assert np.allclose(batch[i], one, atol=1e-12), f"row {i} differs between paths"


def test_normalisation_uses_fixed_constants_not_batch_statistics():
    """A sample's features must not depend on what arrived alongside it.

    Per-batch normalisation works in training and is meaningless at inference,
    where samples arrive one at a time.
    """
    fs = feat.prd7()
    df = _frame(400, seed=1)
    # Same twenty rows, once alone and once inside a much larger batch.
    alone = feat.build(df.iloc[:20], fs)
    in_batch = feat.build(df, fs)[:20]
    assert np.allclose(alone, in_batch, atol=1e-12)


def test_missing_values_become_the_feature_centre():
    """"No information", not an invented reading (PRD Part 4 section 7.2)."""
    df = _frame(10)
    df.loc[3, "oil_pressure"] = np.nan
    x = feat.build(df, feat.prd7())
    assert x[3, 3] == pytest.approx(0.0)
    assert np.isfinite(x).all()


def test_build_rejects_a_frame_that_is_missing_columns():
    df = _frame(10).drop(columns=["fuel_flow"])
    with pytest.raises(KeyError, match="fuel_flow"):
        feat.build(df, feat.prd7())


# ---------------------------------------------------------------------------
# Labelling
# ---------------------------------------------------------------------------


def test_a_worn_but_fault_free_engine_counts_as_degraded():
    """Scoring only against injected faults punishes a correct detector.

    An engine at CHI 0.65 from ordinary wear is genuinely not healthy, and
    flagging it is the right answer -- not a false positive. The problem
    statement asks for degradation tracking, not fault spotting alone.
    """
    df = pd.DataFrame({"chi_true": [0.98, 0.70, 0.85], "any_fault": [0.0, 0.0, 0.0]})
    assert list(feat.anomaly_mask(df)) == [False, True, False]
    assert list(feat.healthy_mask(df)) == [True, False, False]
    # The middle band belongs to neither and is excluded rather than assigned
    # to whichever class flatters the result.
    assert list(feat.ambiguous_mask(df)) == [False, False, True]


def test_healthy_requires_both_high_health_and_no_fault():
    """A fault that has just begun barely moves the composite index.

    Those rows are exactly the ones that would teach an unsupervised detector
    to treat early faults as normal, which is the only kind worth detecting.
    """
    df = pd.DataFrame({"chi_true": [0.97], "any_fault": [0.5]})
    assert not feat.healthy_mask(df)[0]


# ---------------------------------------------------------------------------
# Per-engine baselining
# ---------------------------------------------------------------------------


def test_baselining_removes_a_per_engine_offset_but_keeps_the_trend():
    """Manufacturing spread gives every engine a constant residual offset.

    Measured on this fleet, mean oil-pressure residual spans -25..+1 psi with
    no fault present anywhere. Thresholding the absolute residual therefore
    fires on whichever engines sit at the edge of build tolerance.
    """
    n = 200
    hours = np.linspace(0, 400, n)
    drift = np.where(hours > 200, (hours - 200) * 0.05, 0.0)
    df = pd.DataFrame({
        "engine_id": np.repeat([1, 2], n),
        "flight_hours": np.tile(hours, 2),
        # Engine 1 sits at -20, engine 2 at +5; both drift identically.
        "res_cht": np.concatenate([-20.0 + drift, 5.0 + drift]),
    })
    out = feat.baseline_residuals(df, hours=60.0, columns=["res_cht"])
    e1 = out[out.engine_id == 1]["res_cht"].to_numpy()
    e2 = out[out.engine_id == 2]["res_cht"].to_numpy()
    # Offsets gone...
    assert abs(e1[0]) < 1.0 and abs(e2[0]) < 1.0
    # ...and the two engines now look alike, which is the whole point.
    assert np.allclose(e1, e2, atol=1e-9)
    # ...but the degradation trend survives.
    assert e1[-1] > 8.0


def test_baselining_only_uses_the_engines_own_early_life():
    """Not hindsight: the deployed twin has this from the first flight hours."""
    n = 100
    df = pd.DataFrame({
        "engine_id": np.ones(n, dtype=int),
        "flight_hours": np.linspace(0, 500, n),
        "res_cht": np.concatenate([np.zeros(n // 2), np.full(n - n // 2, 50.0)]),
    })
    out = feat.baseline_residuals(df, hours=60.0, columns=["res_cht"])
    # A late excursion must not be absorbed into the baseline.
    assert out["res_cht"].to_numpy()[-1] == pytest.approx(50.0, abs=1e-6)


# ---------------------------------------------------------------------------
# The detectors
# ---------------------------------------------------------------------------


def test_calibrator_maps_healthy_scores_onto_the_unit_interval():
    rng = np.random.default_rng(0)
    healthy = rng.normal(0.0, 1.0, 5000)
    cal = t2.Calibrator.fit(healthy)
    out = cal.transform(np.array([-10.0, 0.0, 10.0]))
    assert 0.0 <= out[0] < 0.05
    assert 0.4 < out[1] < 0.6
    assert out[2] > 0.99


def test_cblof_scores_a_small_distant_cluster_as_anomalous():
    """Belonging to a small cluster is itself evidence of being unusual."""
    rng = np.random.default_rng(0)
    main = rng.normal(0.0, 1.0, (600, 3))
    outliers = rng.normal(12.0, 0.4, (12, 3))
    x = np.vstack([main, outliers])
    c = t2.CBLOF(n_clusters=4).fit(x)
    s = c.score(x)
    assert s[600:].mean() > s[:600].mean() * 3


def test_matrix_profile_finds_a_level_shift():
    """Degradation is a level shift, so z-normalisation is off by default.

    With it on, the profile peaked at index 83 instead of the planted anomaly
    at 3000: a shifted block of noise has the same SHAPE as unshifted noise.
    """
    rng = np.random.default_rng(0)
    x = np.concatenate([rng.normal(0, 1, 1500), rng.normal(0, 1, 200) + 6,
                        rng.normal(0, 1, 800)])
    mp = t2.MatrixProfile(window=100, exclusion=50)
    peak = int(np.argmax(mp.profile(x)))
    assert 1400 <= peak <= 1750, f"level shift missed, peak at {peak}"


def test_matrix_profile_is_blind_to_level_when_znormalised():
    """Documenting the trade-off, so nobody re-enables it by accident."""
    rng = np.random.default_rng(0)
    x = np.concatenate([rng.normal(0, 1, 1500), rng.normal(0, 1, 200) + 6,
                        rng.normal(0, 1, 800)])
    mp = t2.MatrixProfile(window=100, exclusion=50, znorm=True)
    peak = int(np.argmax(mp.profile(x)))
    assert not (1400 <= peak <= 1750)


def test_matrix_profile_handles_a_series_shorter_than_its_window():
    mp = t2.MatrixProfile(window=100, exclusion=50)
    assert mp.profile(np.arange(10, dtype=float)).shape == (10,)


def test_ensemble_scores_healthy_low_and_anomalous_high():
    rng = np.random.default_rng(0)
    healthy = rng.normal(0.0, 1.0, (2000, 6))
    ens = t2.Tier2Ensemble(
        feat.FeatureSet(
            name="t", columns=tuple(f"c{i}" for i in range(6)),
            centres=(0.0,) * 6, scales=(1.0,) * 6,
        )
    )
    ens.fit(healthy)
    s_ok = ens.score(rng.normal(0.0, 1.0, (500, 6))).score
    s_bad = ens.score(rng.normal(5.0, 1.0, (500, 6))).score
    assert s_ok.mean() < 0.7
    assert s_bad.mean() > 0.95


def test_ensemble_refuses_to_score_before_fitting():
    ens = t2.Tier2Ensemble()
    with pytest.raises(RuntimeError, match="before fit"):
        ens.score(np.zeros((3, len(feat.extended()))))


def test_ensemble_refuses_to_fit_on_too_little_data():
    ens = t2.Tier2Ensemble()
    with pytest.raises(ValueError, match="not enough healthy samples"):
        ens.fit(np.zeros((10, len(feat.extended()))))


def test_a_missing_matrix_profile_does_not_look_like_health():
    """Weights are renormalised over the algorithms that actually ran.

    Otherwise an absent detector contributes zero and drags the ensemble score
    down, which reads downstream as evidence the engine is fine.
    """
    rng = np.random.default_rng(0)
    healthy = rng.normal(0.0, 1.0, (2000, 4))
    fs = feat.FeatureSet(
        name="t", columns=("a", "b", "c", "d"), centres=(0.0,) * 4, scales=(1.0,) * 4
    )
    ens = t2.Tier2Ensemble(fs).fit(healthy)
    bad = rng.normal(6.0, 1.0, (200, 4))
    assert "matrix_profile" not in ens.score(bad).per_algorithm
    assert ens.score(bad).score.mean() > 0.95


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_roc_auc_matches_known_cases():
    assert t2.roc_auc(np.array([0.1, 0.2, 0.8, 0.9]),
                      np.array([0, 0, 1, 1], dtype=bool)) == pytest.approx(1.0)
    assert t2.roc_auc(np.array([0.9, 0.8, 0.2, 0.1]),
                      np.array([0, 0, 1, 1], dtype=bool)) == pytest.approx(0.0)
    # All-tied scores carry no information and must score 0.5, not 1.0.
    assert t2.roc_auc(np.array([0.5, 0.5, 0.5, 0.5]),
                      np.array([0, 0, 1, 1], dtype=bool)) == pytest.approx(0.5)


def test_evaluate_reports_the_false_positive_rate():
    """PRD Part 2 section 11.1 makes it a hard target, not a footnote.

    An operator alerted on healthy engines stops reading alerts, at which point
    recall stops mattering.
    """
    score = np.array([0.9, 0.9, 0.1, 0.1])
    truth = np.array([1, 0, 0, 0], dtype=bool)
    m = t2.evaluate(score, truth, 0.5)
    assert m["recall"] == pytest.approx(1.0)
    assert m["fpr"] == pytest.approx(1 / 3)
    assert m["precision"] == pytest.approx(0.5)


def test_detection_lead_time_ignores_censored_engines():
    """A censored engine has no true failure time to measure against."""
    df = pd.DataFrame({
        "engine_id": [1] * 6 + [2] * 6,
        "flight_hours": list(range(6)) * 2,
        "rul_hours": list(range(5, -1, -1)) * 2,
        "censored": [False] * 6 + [True] * 6,
    })
    score = np.array([0, 0, 1, 1, 1, 1] + [1] * 6, dtype=float)
    lead = t2.detection_lead_time(df, score, 0.5, min_run=3)
    assert lead["engines"] == 1
    assert lead["median_lead_h"] == pytest.approx(3.0)


def test_detection_lead_time_requires_a_sustained_firing():
    """One noisy sample is not a detection."""
    df = pd.DataFrame({
        "engine_id": [1] * 8,
        "flight_hours": list(range(8)),
        "rul_hours": list(range(7, -1, -1)),
        "censored": [False] * 8,
    })
    blip = np.array([0, 1, 0, 0, 0, 0, 0, 0], dtype=float)
    assert t2.detection_lead_time(df, blip, 0.5, min_run=3)["detected"] == 0
