"""The training data must not contain anything the aircraft would not have.

Two properties, checked rather than asserted in prose:

  * the early-life baseline each residual is measured against uses only that
    engine's OWN first hours, so removing an engine's later rows cannot change
    the value computed for an earlier row;
  * and it uses nothing from any other engine, so an engine evaluated alone
    gets the same numbers it gets inside the fleet.

If either failed, every held-out metric in the project would be measuring a
model that had seen its own answers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from layer3_ai import features as feat

RES = [c for c, _ in feat.RESIDUALS][:3]


def _fleet(seed: int = 0, engines: int = 3, rows: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    for e in range(engines):
        hours = np.linspace(0.0, 300.0, rows)
        # A build offset per engine, plus a drift that only appears later in
        # life -- exactly the shape a leaking baseline would absorb.
        frame = {"engine_id": np.full(rows, f"E{e}"), "flight_hours": hours}
        for i, c in enumerate(RES):
            offset = 3.0 * (e + 1) + i
            drift = np.where(hours > 150.0, 0.05 * (hours - 150.0), 0.0)
            frame[c] = offset + drift + rng.normal(0.0, 0.2, rows)
        frames.append(pd.DataFrame(frame))
    return pd.concat(frames, ignore_index=True)


def test_a_rows_baseline_cannot_change_when_its_future_is_deleted():
    """The property that makes the baseline servable from installation."""
    full = _fleet()
    cut = full[full.flight_hours <= 120.0].copy()

    whole = feat.baseline_residuals(full)
    early = feat.baseline_residuals(cut)

    common = whole[whole.flight_hours <= 120.0].reset_index(drop=True)
    early = early.reset_index(drop=True)
    for c in RES:
        assert np.allclose(common[c].to_numpy(), early[c].to_numpy(), atol=1e-9), c


def test_one_engine_alone_gets_the_same_numbers_as_it_does_in_the_fleet():
    """No engine's baseline may be built from another engine's data."""
    fleet = feat.baseline_residuals(_fleet())
    alone = feat.baseline_residuals(_fleet()[lambda d: d.engine_id == "E1"].copy())

    mine = fleet[fleet.engine_id == "E1"].reset_index(drop=True)
    alone = alone.reset_index(drop=True)
    for c in RES:
        assert np.allclose(mine[c].to_numpy(), alone[c].to_numpy(), atol=1e-9), c


def test_the_baseline_removes_the_build_offset_and_keeps_the_drift():
    """What it exists to do: strip where an engine started, keep where it went."""
    out = feat.baseline_residuals(_fleet())
    one = out[out.engine_id == "E2"]
    c = RES[0]
    start = one[one.flight_hours <= 60.0][c].median()
    end = one[one.flight_hours > 250.0][c].median()
    assert start == pytest.approx(0.0, abs=0.15), "the build offset must be gone"
    assert end > 4.0, "the late-life drift must survive"
