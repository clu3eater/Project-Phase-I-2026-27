"""Frozen readings (audit 15 Sep, P0-5).

The project's own documentation calls a frozen plausible value the most
dangerous failure a monitoring system has, and nothing detected one. A working
sensor's noise makes a long run of identical readings improbable, and how
improbable follows from its noise and resolution alone.

A sensor that keeps its noise but stops following the engine is the other half,
in layer4_core/tests/test_sensor_response.py.
"""

from __future__ import annotations

import numpy as np
import pytest

from common import config
from layer1_edge.can_ingest import (
    CanIngest,
    ValueState,
    frozen_run_limit,
    repeat_run_probability,
)
from layer1_edge.can_simulator import CanSimulator
from layer1_edge.edge_rules import RuleEngine
from layer2_physics.engine_sim import VirtualEngine, _default_sensors, run_profile


@pytest.fixture
def link(request):
    channel = f"frz_{request.node.name}"
    sim = CanSimulator(interface="virtual", channel=channel)
    ing = CanIngest(interface="virtual", channel=channel)
    yield sim, ing
    sim.close()
    ing.close()


def _fly(sim, ing, v, seconds, *, dt=0.5, at=None, act=None):
    """Fly; call ``act(v)`` once at ``at`` seconds. Returns the last telemetry."""
    t, done = None, False
    for f in run_profile(v, dt=dt, max_seconds=seconds):
        if act is not None and not done and f.t_s >= at:
            act(v)
            done = True
        sim.send_frame(f)
        t = ing.poll(now=f.t_s)
    return t


def test_the_noise_ratios_are_the_simulated_instruments():
    ratios = config.load_thresholds()["pipeline"]["frozen_noise_over_resolution"]
    specs = _default_sensors()
    for key, ratio in ratios.items():
        assert ratio == pytest.approx(specs[key].noise_sigma / specs[key].resolution), key
        lane_b = specs.get(f"{key}_lane_b")
        if lane_b is not None:
            assert lane_b.noise_sigma / lane_b.resolution == pytest.approx(ratio), key


def test_the_run_probability_matches_a_sensor_that_is_counted():
    """Where it can be counted: noise equal to the resolution, three readings."""
    readings = np.round(np.random.default_rng(1).normal(0.0, 1.0, size=(400_000, 3)))
    counted = float(np.mean((readings == readings[:, :1]).all(axis=1)))
    assert counted == pytest.approx(repeat_run_probability(1.0, 3), rel=0.03)


def test_the_run_limit_is_the_first_run_rarer_than_the_target():
    n = frozen_run_limit(4.0, 1e-9)
    assert repeat_run_probability(4.0, n) <= 1e-9 < repeat_run_probability(4.0, n - 1)


@pytest.mark.parametrize("seed, dt, seconds", [(3, 0.5, 900.0), (7, 0.1, 150.0)])
def test_a_healthy_flight_never_reads_as_frozen(seed, dt, seconds):
    channel = f"frz_healthy_{seed}"
    sim = CanSimulator(interface="virtual", channel=channel)
    ing = CanIngest(interface="virtual", channel=channel)
    try:
        for f in run_profile(VirtualEngine(seed=seed), dt=dt, max_seconds=seconds):
            sim.send_frame(f)
            t = ing.poll(now=f.t_s)
            for name, ch in t.channels.items():
                for r in (ch, *ch.lanes.values()):
                    assert "frozen" not in r.reason, (f.t_s, name, r.reason)
    finally:
        sim.close()
        ing.close()


def test_a_frozen_oil_pressure_sensor_is_removed_within_its_run_limit(link):
    sim, ing = link
    v = VirtualEngine(seed=11)
    rules = RuleEngine()
    limit = ing._frozen_limit["oil_pressure"]
    frozen_at = caught_at = None
    state = None
    for i, f in enumerate(run_profile(v, dt=0.5, max_seconds=200.0)):
        sim.send_frame(f)
        t = ing.poll(now=f.t_s)
        state = rules.evaluate(t, ing.derived())
        if frozen_at is None and f.t_s >= 100.0:
            v.fail_sensor("oil_pressure", "frozen")  # from the next frame
            frozen_at = i
        if frozen_at is not None and caught_at is None and "frozen" in t.channels["oil_pressure"].reason:
            caught_at = i
    assert caught_at is not None
    assert caught_at - frozen_at <= limit
    assert t.state("oil_pressure") is ValueState.INVALID and t.get("oil_pressure") is None
    assert "SENSOR_FAULT" in {a.rule_id for a in state.active}


def test_a_frozen_head_probe_is_removed_and_its_neighbours_are_not(link):
    sim, ing = link
    t = _fly(sim, ing, VirtualEngine(seed=11), 150.0, at=100.0,
             act=lambda v: v.fail_sensor("cht", "frozen", key=1))
    assert t.state("cht_2") is ValueState.INVALID and "frozen" in t.channels["cht_2"].reason
    assert all(t.state(f"cht_{i}") is ValueState.VALID for i in (1, 3, 4))


def test_a_frozen_lane_b_speed_sensor_leaves_lane_a_in_charge(link):
    sim, ing = link
    t = _fly(sim, ing, VirtualEngine(seed=11), 150.0, at=100.0,
             act=lambda v: v.fail_sensor("rpm_lane_b", "frozen"))
    ch = t.channels["rpm"]
    assert ch.lanes["B"].state is ValueState.INVALID and "frozen" in ch.lanes["B"].reason
    assert ch.state is ValueState.VALID and ch.redundancy_lost


def test_a_repaired_sensor_is_believed_again(link):
    sim, ing = link
    v = VirtualEngine(seed=11)
    t = _fly(sim, ing, v, 130.0, at=100.0, act=lambda e: e.fail_sensor("oil_pressure", "frozen"))
    assert t.state("oil_pressure") is ValueState.INVALID
    v.repair_sensor("oil_pressure")
    for f in run_profile(v, dt=0.5, max_seconds=5.0):
        sim.send_frame(f)
        t = ing.poll(now=f.t_s)
    assert t.state("oil_pressure") is ValueState.VALID


def test_a_condemned_channel_stays_removed_until_absolved(link):
    """The hold the twin's sensor-response check uses."""
    sim, ing = link
    v = VirtualEngine(seed=11)
    _fly(sim, ing, v, 30.0)
    ing.condemn("oil_temperature", "not responding: test")
    t = _fly(sim, ing, v, 5.0)
    assert t.state("oil_temperature") is ValueState.INVALID
    assert t.get("oil_temperature") is None and ing.raw("oil_temperature") is not None
    ing.absolve("oil_temperature")
    t = _fly(sim, ing, v, 2.0)
    assert t.state("oil_temperature") is ValueState.VALID
