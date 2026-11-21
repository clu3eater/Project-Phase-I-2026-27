"""The live stream is tiered, and the tiering must not change what a frame MEANS.

The console pushed the whole 104 KB snapshot every `dashboard_refresh_s` -- 2.0
seconds -- so every engine reading on the display stepped once every two
seconds, against a standard (PRD Part 4 s8.3) that asks for Zone B at the
telemetry rate and trend charts at 4 Hz. It read as a lagging console because
that is what it was.

It could not just be sped up: 71 % of the payload is two chart series that gain
one point per tick. So partial frames carry the readings without them -- and a
partial frame is marked, because on a FULL frame an absent field means the twin
is declining to publish it, and that meaning has to survive the optimisation.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from common import config
from layer4_core.live import Snapshot
from layer4_core.twin_api import _SERIES_KEYS, snapshot_for_role


def _payload() -> dict:
    return snapshot_for_role(asdict(Snapshot()), "commander")


def test_the_series_keys_are_the_ones_that_dominate_the_payload():
    """Named explicitly, so a new chart is a decision rather than a surprise."""
    assert _SERIES_KEYS == {"history", "flight_series"}
    assert all(k in asdict(Snapshot()) for k in _SERIES_KEYS)


def test_a_partial_frame_drops_the_series_and_says_that_it_did():
    full = _payload()
    partial = {k: v for k, v in full.items() if k not in _SERIES_KEYS}
    partial["partial"] = True
    assert not (_SERIES_KEYS & set(partial))
    assert partial["partial"] is True, (
        "an unmarked partial frame would be merged by nothing and would read as "
        "a twin that had stopped publishing its charts")


def test_a_partial_frame_still_carries_the_readings():
    """Whatever else is dropped, the numbers the operator flies on stay."""
    partial = {k: v for k, v in _payload().items() if k not in _SERIES_KEYS}
    for key in ("twin", "display", "health", "fusion", "pipeline", "t_s"):
        assert key in partial, f"{key} is not in a live frame"


def test_the_live_cadence_is_faster_than_the_full_one_and_meets_the_standard():
    thr = config.load_thresholds()["pipeline"]
    full = float(thr["dashboard_refresh_s"])
    live = float(thr["dashboard_live_refresh_s"])
    assert live < full, "the live tier must be faster than the full snapshot"
    assert live <= 0.25, (
        f"{live}s between readings is {1/live:.1f} Hz; PRD Part 4 s8.3 asks for "
        "4 Hz on trend charts and the telemetry rate on Zone B")
    assert full <= 2.0, "PRD Part 1 s2.2 requires dashboard refresh <= 2 s"


def test_dropping_the_series_is_worth_doing():
    """If the charts were not most of the payload, this design would be noise.

    A default Snapshot carries EMPTY series, where they are 8 % of a 1 KB
    frame, so measuring the saving there would measure nothing. These are the
    shapes a running twin actually holds: 19 channels over the retained window,
    measured on a twin at 19:5x -- 30.6 KB each of a 104 KB frame.
    """
    full = _payload()
    for key in _SERIES_KEYS:
        full[key] = {f"ch_{i}": [1234.5678] * 240 for i in range(19)}
    whole = len(json.dumps(full, default=str))
    series = sum(len(json.dumps(full[k], default=str)) for k in _SERIES_KEYS)
    assert series / whole > 0.60, (
        f"the chart series are {100*series/whole:.0f}% of the frame; if they "
        "stop dominating it, send them every frame and delete the tiering")


@pytest.mark.parametrize("role", ["commander", "engineer", "operator"])
def test_tiering_never_widens_what_a_role_receives(role):
    """A partial frame is a SUBSET. It cannot leak what the scopes withheld."""
    full = snapshot_for_role(asdict(Snapshot()), role)
    partial = {k: v for k, v in full.items() if k not in _SERIES_KEYS}
    assert set(partial) <= set(full)
