"""A sensor that no longer follows the engine (audit 15 Sep, P0-5).

It keeps its electrical noise, so the ingest's range, rate and frozen-reading
checks all pass it. The as-new twin says how much the reading should have
moved; a reading that did not move while the prediction did is removed.

The test that matters most is the cooling fault: the first method tried
(slope of reading against prediction) would have removed the head temperature
of an engine that really was overheating.
"""

from __future__ import annotations

import numpy as np
import pytest

from common import config
from layer1_edge.can_ingest import CanIngest, ValueState
from layer1_edge.can_simulator import CanSimulator
from layer1_edge.edge_rules import RuleEngine
from layer2_physics.degradation import FaultMode, InjectedFault
from layer2_physics.engine_sim import VirtualEngine, _default_sensors, run_profile
from layer4_core.sensor_response import ResponseCheck, SensorResponseMonitor
from layer4_core.shadow_model import ShadowModel
from layer4_core.twin_state import create_twin

DT = 0.5


def _check() -> ResponseCheck:
    return ResponseCheck(noise=0.6, window_s=60.0, excitation_x=5.0, flat_x=2.0)


def _feed(check, reading, seconds: float = 60.0):
    rng = np.random.default_rng(0)
    verdict = None
    for i in range(int(seconds / DT) + 1):
        t = i * DT
        predicted = 100.0 + 40.0 * t / 60.0
        verdict = check.update(t, reading(t, predicted) + rng.normal(0.0, 0.6), predicted)
    return verdict


def test_a_reading_that_follows_the_prediction_is_responding():
    assert _feed(_check(), lambda t, p: p) is True


def test_a_flat_reading_while_the_prediction_moves_is_not_responding():
    # A full window, then the verdict must HOLD for persist_s before it counts.
    check = _check()
    assert _feed(check, lambda t, p: 100.0, seconds=60.0 + check.persist_s + 1.0) is False


def test_a_lagging_probe_at_the_start_of_a_change_is_not_removed():
    """A thermocouple lags the metal by ~10 s; the twin's prediction does not.

    Steady for a minute, then the prediction steps and the reading follows
    it through a 10 s lag. In the first seconds the reading has moved less
    than the prediction -- a good probe that the check used to remove for a
    second at every top of descent.
    """
    check = _check()
    rng = np.random.default_rng(1)
    lagged = 100.0
    verdicts = []
    for i in range(int(120.0 / DT)):
        t = i * DT
        predicted = 100.0 if t < 60.0 else 70.0
        lagged += (DT / (10.0 + DT)) * (predicted - lagged)
        verdicts.append(check.update(t, lagged + rng.normal(0.0, 0.6), predicted))
    assert False not in verdicts


def test_a_real_offset_or_lag_is_still_responding():
    """A degraded engine runs hotter or slower than the twin; it still moves."""
    assert _feed(_check(), lambda t, p: 108.0 + 0.5 * (p - 100.0)) is True


def test_no_verdict_while_the_engine_holds_a_steady_point():
    check = _check()
    rng = np.random.default_rng(0)
    verdicts = {check.update(i * DT, 100.0 + rng.normal(0.0, 0.6), 100.0) for i in range(200)}
    assert verdicts == {None}


def test_the_response_noise_is_the_simulated_instruments():
    noise = config.load_thresholds()["pipeline"]["response_noise"]
    specs = _default_sensors()
    assert noise["oil_pressure"] == pytest.approx(specs["oil_pressure"].noise_sigma * 14.5038,
                                                  rel=1e-3)  # psi on the bus, bar in the model
    for key in ("cht", "coolant_temperature", "egt", "oil_temperature", "fuel_flow"):
        assert noise[key] == pytest.approx(specs[key].noise_sigma), key


def _fly(tag, *, fault=None, stuck=None, seconds=1200.0):
    """The full stack plus the monitor. Returns ({channel: first condemned t}, telemetry)."""
    sim = CanSimulator(interface="virtual", channel=tag)
    ing = CanIngest(interface="virtual", channel=tag)
    rules, shadow = RuleEngine(), ShadowModel()
    v = VirtualEngine(seed=11)
    if fault:
        v.inject(fault)
    state, sync = create_twin("DT-RESP", aircraft_id="MALE-01")
    monitor = SensorResponseMonitor(ing)
    first: dict[str, float] = {}
    failed = False
    try:
        for f in run_profile(v, dt=DT, max_seconds=seconds):
            if stuck and not failed and f.t_s >= stuck[2]:
                v.fail_sensor(stuck[0], "stuck", key=stuck[1])
                failed = True
            sim.send_frame(f)
            tel = ing.poll(now=f.t_s)
            derived = ing.derived()
            sync.sync(tel, derived=derived, physics=shadow.update(tel, DT),
                      alerts=rules.evaluate(tel, derived))
            for name in monitor.update(f.t_s, state.simulated):
                first.setdefault(name, f.t_s)
    finally:
        sim.close()
        ing.close()
    return first, ing.telemetry


def test_a_healthy_engine_has_no_sensor_found_not_responding():
    first, _ = _fly("resp_healthy")
    assert first == {}


def test_a_real_cooling_fault_is_not_mistaken_for_a_stuck_sensor():
    first, _ = _fly("resp_cooling", fault=InjectedFault(
        mode=FaultMode.COOLING_DEGRADATION, severity=0.8, onset_hours=0.0, ramp_hours=0.02))
    assert first == {}


def test_a_stuck_head_probe_is_found_and_its_reading_removed():
    first, tel = _fly("resp_stuck", stuck=("cht", 2, 60.0))
    assert "cht_3" in first, first
    assert set(first) <= {"cht_3", "cht_max"}, first
    ch = tel.channels["cht_3"]
    assert ch.state is ValueState.INVALID and "not responding" in ch.reason
    assert tel.get("cht_3") is None
