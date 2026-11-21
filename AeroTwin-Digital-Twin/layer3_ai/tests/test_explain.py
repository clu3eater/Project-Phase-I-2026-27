"""Tests for explainability.

Two properties matter more than the arithmetic.

An explanation must be EXACT where an exact answer exists. The composite health
index is a weighted sum of minima, so its decomposition is closed-form; a
sampled approximation of a known quantity is strictly worse than the quantity,
because it invites the reader to wonder about the sampling error.

And an explanation must agree with the thing it explains. An attribution that
drifts from the computation is worse than no attribution at all, because it is
believed.
"""

from __future__ import annotations

import pytest

from common import config
from layer3_ai import explain as ex
from layer3_ai import health as hl

HEALTHY = dict(thi=0.99, oti=0.98, mhi=0.97, lhi=0.99, rsi=0.996,
               ehi=0.98, comb_hi=0.99, fshi=0.99, csi=0.95)


# ---------------------------------------------------------------------------
# The decomposition is exact, not approximate
# ---------------------------------------------------------------------------


def test_the_decomposition_reproduces_the_index_exactly():
    """Not "close to". The shortfall is a sum of weighted terms and must add up.

    If the parts do not sum to the whole, the explanation is describing a
    different calculation from the one that ran.
    """
    e = ex.explain_health(HEALTHY)
    assert e.shortfall == pytest.approx(sum(c.contribution for c in e.contributions))
    assert e.chi == pytest.approx(1.0 - e.shortfall)


def test_the_explained_index_matches_what_the_estimator_computes():
    """The attribution must agree with the code it claims to explain.

    Both are derived from the same weights and the same subsystem roll-up, so
    any disagreement means one of them has drifted.
    """
    w = config.load_thresholds()["health"]["composite_weights"]
    thermal = min(HEALTHY["thi"], HEALTHY["oti"])
    mechanical = min(HEALTHY["mhi"], HEALTHY["lhi"], HEALTHY["rsi"])
    electrical = HEALTHY["ehi"]
    combustion = min(HEALTHY["comb_hi"], HEALTHY["fshi"], HEALTHY["csi"])
    expected = (
        w["thermal"] * thermal + w["mechanical"] * mechanical
        + w["electrical"] * electrical + w["combustion"] * combustion
    )
    assert ex.explain_health(HEALTHY).chi == pytest.approx(expected)


def test_subsystem_inputs_match_the_estimator():
    """The two tables must not drift apart.

    ``SUBSYSTEM_INPUTS`` names which sub-indices feed each subsystem; if the
    estimator ever adds one, the explanation would silently stop accounting
    for it.
    """
    snapshot = hl.HealthSnapshot()
    for inputs in ex.SUBSYSTEM_INPUTS.values():
        for name in inputs:
            assert hasattr(snapshot, name), f"{name} is not a real sub-index"


def test_shares_sum_to_one():
    e = ex.explain_health({**HEALTHY, "thi": 0.62})
    assert sum(c.share for c in e.contributions) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# It names the right driver
# ---------------------------------------------------------------------------


def test_the_dominant_subsystem_is_identified_and_ranked_first():
    e = ex.explain_health({**HEALTHY, "thi": 0.62})
    assert e.contributions[0].name == "thermal"
    assert e.contributions[0].share > 0.7
    assert e.drivers[0].name == "thermal"


def test_the_binding_sub_index_is_named_not_just_the_subsystem():
    """"Thermal is degraded" is not actionable. "Limited by cylinder head and
    coolant temperature" tells an engineer where to look."""
    e = ex.explain_health({**HEALTHY, "oti": 0.55})
    thermal = next(c for c in e.contributions if c.name == "thermal")
    assert "OTI" in thermal.detail
    assert "oil temperature" in thermal.detail


def test_a_minor_contributor_is_not_promoted_to_a_driver():
    """Listing all four subsystems every time trains the reader to skip the
    list, which costs exactly when one of them matters."""
    e = ex.explain_health({**HEALTHY, "thi": 0.55})
    assert len(e.drivers) < len(e.contributions)
    assert all(d.share >= 0.20 for d in e.drivers)


def test_a_healthy_engine_gets_a_narrative_that_says_so():
    """MIL-STD-411F 4.1.1a in prose: do not manufacture a finding."""
    e = ex.explain_health({k: 0.999 for k in HEALTHY})
    assert "as-new" in e.narrative
    assert e.shortfall < 0.01


def test_evenly_spread_wear_is_reported_as_such():
    """An engine with no single driver must not have one invented for it."""
    e = ex.explain_health({k: 0.90 for k in HEALTHY})
    assert "no single driver" in e.narrative or e.drivers


# ---------------------------------------------------------------------------
# Residual attribution
# ---------------------------------------------------------------------------


def test_residuals_are_ranked_by_healthy_spread_not_raw_magnitude():
    """A +9 K head residual and a +2 psi oil residual are different quantities
    in different units, and comparing them as numbers is meaningless.

    Divided by the scatter a healthy engine shows on each, they become
    comparable and the ranking means something.
    """
    res = {
        # Small in absolute terms, huge relative to its healthy spread.
        "coolant": {"usable": True, "mean_delta": 3.0},     # 3.0x
        # Large in absolute terms, ordinary relative to its spread.
        "egt": {"usable": True, "mean_delta": 20.0},        # 0.7x
    }
    out = ex.explain_residuals(res)
    assert out[0].name == "coolant", [c.name for c in out]


def test_an_unusable_residual_is_excluded_not_scored_zero():
    """A residual from a stale measurement is not a small residual, it is no
    residual -- the same distinction the twin makes."""
    res = {"cht": {"usable": False, "mean_delta": 40.0},
           "egt": {"usable": True, "mean_delta": 10.0}}
    names = [c.name for c in ex.explain_residuals(res)]
    assert "cht" not in names
    assert "egt" in names


def test_residual_shares_sum_to_one():
    res = {"cht": {"usable": True, "mean_delta": 8.0},
           "egt": {"usable": True, "mean_delta": 30.0}}
    out = ex.explain_residuals(res)
    assert sum(c.share for c in out) == pytest.approx(1.0)


def test_residual_detail_says_what_it_physically_means():
    res = {"cht": {"usable": True, "mean_delta": 9.0}}
    out = ex.explain_residuals(res)
    assert "heat is not leaving" in out[0].detail
    assert "2.2x" in out[0].detail or "2.3x" in out[0].detail


def test_no_residuals_produces_an_empty_ranking_not_an_error():
    assert ex.explain_residuals({}) == []


# ---------------------------------------------------------------------------
# The assembled explanation
# ---------------------------------------------------------------------------


def test_snapshot_explanation_joins_health_residual_and_advisory():
    out = ex.explain_snapshot(
        {**HEALTHY, "thi": 0.62},
        {"cht": {"usable": True, "mean_delta": 9.2}},
        {"severity": "CAUTION", "recommended_action": "maintain within 25h",
         "time_to_action": "Within 25 flight hours"},
    )
    n = out["narrative"]
    assert "thermal" in n
    assert "cht" in n
    assert "CAUTION" in n
    assert out["method"].startswith("exact decomposition")


def test_an_info_advisory_does_not_add_an_alarming_clause():
    out = ex.explain_snapshot(HEALTHY, {}, {"severity": "INFO"})
    assert "reported as" not in out["narrative"]


def test_the_explanation_is_ascii_so_it_survives_a_windows_console():
    """demo.py prints this text, and a cp1252 console cannot encode an em dash.

    The UnicodeEncodeError lands in the middle of a demonstration, which is
    the worst possible moment to discover a formatting choice.
    """
    out = ex.explain_snapshot(
        {**HEALTHY, "thi": 0.62},
        {"cht": {"usable": True, "mean_delta": 9.2}},
        {"severity": "CAUTION", "recommended_action": "x", "time_to_action": "y"},
    )
    for text in [out["narrative"]] + [c["detail"] for c in out["residuals"]]:
        assert all(ord(ch) < 128 for ch in text), repr(text)


def test_explanation_serialises_for_the_api():
    out = ex.explain_snapshot(HEALTHY, {}, {})
    import json

    json.dumps(out)   # must not raise
    assert set(out) >= {"health", "residuals", "narrative", "method"}
