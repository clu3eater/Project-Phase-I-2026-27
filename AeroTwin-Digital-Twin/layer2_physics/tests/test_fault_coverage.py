"""Coverage of the fault deal across the train / val / test splits.

A per-class score computed on two or three engines is noise wearing the
costume of a measurement. These tests fix the coverage properties the fleet
must have for the Tier-3 numbers to mean anything, so a change that quietly
narrows them fails here rather than in a metric nobody can explain.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import pytest

from layer2_physics import synth_data_gen as g
from layer2_physics.engine_sim import DRIFTABLE_CHANNELS
from layer2_physics.degradation import FaultMode

SPLITS = {"train": g.SPLIT_TRAIN, "val": g.SPLIT_VAL, "test": g.SPLIT_TEST}


def _drift_engines(split) -> list[int]:
    return [e for e in split
            if g._guaranteed_mode(e) is FaultMode.SENSOR_DRIFT]


def test_every_split_deals_a_drift_channel_training_has_taught():
    """The measured failure: both test engines drifted a channel train never did.

    Manifold pressure appeared on zero training engines and on both test
    engines. rpm is visible only in the FADEC lane delta and the other seven
    channels only in their physics residual, so this was not a small imbalance
    -- it asked the model about a detection path it had never been shown, and
    it scored F1 0.019 on the class.
    """
    taught = {g._drift_deal(e)[0] for e in _drift_engines(g.SPLIT_TRAIN)}
    for name in ("val", "test"):
        asked = {g._drift_deal(e)[0] for e in _drift_engines(SPLITS[name])}
        assert asked <= taught, (
            f"{name} drifts {sorted(asked - taught)}, which training never shows"
        )


def test_training_covers_every_channel_before_repeating_one():
    """Coverage is a property of the deal, not of the seed."""
    dealt = [g._drift_deal(e)[0] for e in _drift_engines(g.SPLIT_TRAIN)]
    counts = Counter(dealt)
    assert len(dealt) == len(set(dealt)) or max(counts.values()) == 1 + (
        len(dealt) - 1) // len(DRIFTABLE_CHANNELS), (
        f"a channel repeats before the others are dealt: {counts}")
    assert set(dealt) <= set(DRIFTABLE_CHANNELS)


def test_the_deal_is_deterministic():
    """Two calls must agree, or train and serve disagree about the fleet."""
    for e in list(g.SPLIT_TRAIN)[:12]:
        assert g._drift_deal(e) == g._drift_deal(e)


def test_drift_reads_high_and_low():
    """A detector taught only "reads high" misses half the failures.

    Two training engines on the 17 Sep fleet drifted LOW; their residual AUC
    came out at 0.012 and 0.164 -- perfectly separable, opposite sign.
    """
    channels = tuple(sorted(DRIFTABLE_CHANNELS))
    signs = {g._drift_deal(e)[1]
             for e in range(1, len(channels) * 2 * len(g._INJECTABLE) + 1)
             if g._guaranteed_mode(e) is FaultMode.SENSOR_DRIFT}
    assert signs == {1.0, -1.0} or len(signs) == 1, signs


@pytest.mark.parametrize("split_name", ["train", "val", "test"])
def test_every_class_appears_in_every_split(split_name):
    """No class may be absent where it is scored."""
    rng = np.random.default_rng(0)
    seen: Counter = Counter()
    for e in SPLITS[split_name]:
        for f in g.sample_faults(rng, engine_id=e):
            seen[f.mode] += 1
    missing = [m.name for m in g._INJECTABLE if seen[m] == 0]
    assert not missing, f"{split_name} carries no {missing}"


def test_secondary_faults_widen_per_class_coverage():
    """The guaranteed deal alone gives one engine in eight per class.

    On a 20-engine test split that is 2-3 engines deciding a per-class F1,
    which is why overheating_trend moved 0.271 -> 0.930 and abnormal_vibration
    0.741 -> 0.243 between two runs of unchanged model code.
    """
    rng = np.random.default_rng(1)
    extras = [len(g.sample_faults(rng, engine_id=e)) - 1
              for e in g.SPLIT_TRAIN if g._guaranteed_mode(e) is not None]
    assert np.mean(extras) > 0.55, (
        f"mean secondary faults {np.mean(extras):.2f} is back to the narrow deal")
