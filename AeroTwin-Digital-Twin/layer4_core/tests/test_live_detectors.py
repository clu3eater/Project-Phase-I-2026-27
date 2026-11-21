"""The live wiring of DEV-252 to DEV-254, checked on a real LiveTwin.

The offline benchmarks measure the models; these pin that the running twin
uses them as measured: the Tier-2 limits saved with the model, the fault
namer, and the engine reference that both wait for.
"""

from __future__ import annotations

import pytest

from layer4_core.live import LiveTwin


@pytest.fixture(scope="module")
def twin():
    tw = LiveTwin(seed=3, cruise_hours=0.5, persist=False)
    for _ in range(40):
        tw._tick()
        tw._ticks += 1
    yield tw
    tw.sim.close()


def test_the_tier2_limits_saved_with_the_model_are_the_ones_used(twin):
    if twin.tier2 is None:
        pytest.skip("no Tier-2 model on disk")
    assert twin.tier2_threshold is not None
    # a model saved by the current scripts/eval_tier2.py carries per-condition limits
    assert twin.tier2_limits, "per-condition limits were not loaded"
    assert twin._stat_gate == pytest.approx(0.70)


def test_the_snapshot_says_what_the_statistical_limit_was(twin):
    f = twin.snapshot().fusion
    assert "statistical_limit" in f
    assert "engine_reference" in f
    assert set(f["engine_reference"]) == {"ready", "frozen", "reason"}


def test_a_new_engine_waits_for_its_reference(twin):
    """Forty ticks in, still on the ground: no reference, so nothing learned
    may name a fault, and the snapshot says why rather than showing zeros."""
    s = twin.snapshot()
    ref = s.fusion["engine_reference"]
    assert not ref["ready"]
    src = s.twin["predicted"]["fault_probability_source"]
    assert src.startswith("not judged: waiting for this engine's first level flight")


def test_the_fault_namer_is_loaded_when_its_file_exists(twin):
    if twin.fault_namer is None:
        pytest.skip("no fault namer on disk")
    assert set(twin.fault_namer.classes) >= {"lubrication_issue", "misfire"}
    # its thresholds, not the network's, drive the console
    assert set(twin._fault_cal) == set(twin.fault_namer.classes)
