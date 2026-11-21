"""The scatter features, and that training and serving compute the same thing.

Rough running is cycle-to-cycle variation, not a level. Measuring it on the
exhaust residual alone left combustion_instability at F1 0.372 while the
simulator was also injecting a 30 rpm speed scatter that nothing read.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from layer3_ai import features as feat


def _frame(n=400, rpm_noise=0.0, egt_noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "engine_id": np.ones(n, dtype=int),
        "t_s": np.arange(n, dtype=float),
        "rpm": 5000.0 + rng.normal(0.0, rpm_noise, n),
        "res_egt": rng.normal(0.0, egt_noise, n),
        "egt_spread": 20.0 + rng.normal(0.0, egt_noise, n),
    })


def test_all_three_scatter_columns_are_produced():
    out = feat.add_egt_scatter(_frame(rpm_noise=30.0, egt_noise=15.0))
    for _, name in feat.SCATTER_SOURCES:
        assert name in out.columns, f"{name} was not computed"
        assert out[name].notna().sum() > 100, f"{name} is almost all NaN"


def test_scatter_rises_with_the_roughness_it_measures():
    """A quiet engine and a rough one must not produce the same number."""
    quiet = feat.add_egt_scatter(_frame(rpm_noise=2.0, egt_noise=1.0))
    rough = feat.add_egt_scatter(_frame(rpm_noise=30.0, egt_noise=15.0))
    for _, name in feat.SCATTER_SOURCES:
        q, r = quiet[name].median(), rough[name].median()
        assert r > 3 * q, f"{name}: rough {r:.3f} vs quiet {q:.3f}"


def test_the_window_is_time_not_rows():
    """The fleet steps at 1 s and the twin at 0.5 s.

    A window counted in samples would be two different features, and the
    network would be served a column it was never trained on.
    """
    fast = _frame(n=800, rpm_noise=30.0)
    fast["t_s"] = np.arange(800) * 0.5          # same minute, twice the rows
    slow = _frame(n=400, rpm_noise=30.0)
    a = feat.rolling_scatter(fast, "rpm", "rpm_scatter")["rpm_scatter"].median()
    b = feat.rolling_scatter(slow, "rpm", "rpm_scatter")["rpm_scatter"].median()
    assert abs(a - b) / max(b, 1e-9) < 0.25, (
        f"a 60 s window gave {a:.2f} at 0.5 s steps and {b:.2f} at 1 s steps")


def test_scatter_is_per_engine():
    """One engine's last sortie must not be spliced onto the next engine's first."""
    a = _frame(n=200, rpm_noise=2.0, seed=1)
    b = _frame(n=200, rpm_noise=2.0, seed=2)
    b["engine_id"] = 2
    b["rpm"] += 500.0                       # a different engine, offset speed
    joined = pd.concat([a, b], ignore_index=True)
    out = feat.rolling_scatter(joined, "rpm", "rpm_scatter")
    seam = out.iloc[195:215]["rpm_scatter"].max()
    assert seam < 100.0, (
        f"the join between two engines reads as {seam:.0f} rpm of scatter")


def test_missing_source_columns_do_not_crash_the_contract():
    df = _frame().drop(columns=["egt_spread"])
    out = feat.add_egt_scatter(df)
    assert "rpm_scatter" in out.columns
    assert "egt_spread_scatter" not in out.columns


def test_only_the_exhaust_scatter_is_served():
    """The other two are computed and deliberately NOT in the contract.

    They were added and measured out again: each separates
    combustion_instability better than the exhaust residual does on its own
    (AUC 0.707 and 0.736 against 0.599), and the network still scored worse
    with them -- that class went 0.372 -> 0.283 and the fused detector
    0.910 -> 0.893. Serving a column because its single-feature AUC looks good
    is how a model gets diluted. This test records the decision so a future
    change to SCATTER_SOURCES does not silently re-serve them.
    """
    served = feat.FEATURE_SETS["EXTENDED"]().columns
    assert "egt_scatter" in served
    assert "rpm_scatter" not in served
    assert "egt_spread_scatter" not in served
