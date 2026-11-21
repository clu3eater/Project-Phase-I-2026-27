"""Instrument offset, and who is to blame for it (audit 15 Sep, P0-4).

The number the console called "sensor drift" was the residual VARIANCE ratio --
scatter, not offset -- so a transducer reading steadily 6 psi low scored as
engine wear and the offset itself was never reported. A sensor drifting low is
how an overheat stays hidden.

What these tests pin down is the honesty of the verdict, not just the detection:
an offset is blamed on the instrument only where a second source disagrees with
it, and a real cooling fault is never called a sensor drift.
"""

from __future__ import annotations

import pytest

from layer1_edge.can_ingest import CanIngest
from layer1_edge.can_simulator import CanSimulator
from layer1_edge.edge_rules import RuleEngine
from layer2_physics.degradation import FaultMode, InjectedFault
from layer2_physics.engine_sim import VirtualEngine, run_profile
from layer4_core.sensor_bias import BiasMonitor
from layer4_core.shadow_model import ShadowModel
from layer4_core.twin_state import create_twin

DT = 0.5


def _drift(channel: str, severity: float = 0.8, sign: float = 1.0) -> InjectedFault:
    return InjectedFault(mode=FaultMode.SENSOR_DRIFT, onset_hours=0.0, severity=severity,
                         ramp_hours=0.02, channel=channel, drift_sign=sign)


def _fly(tag: str, fault=None, seconds: float = 1200.0):
    """The full stack plus the bias monitor. Returns (monitor, telemetry)."""
    sim = CanSimulator(interface="virtual", channel=tag)
    ing = CanIngest(interface="virtual", channel=tag)
    rules, shadow = RuleEngine(), ShadowModel()
    v = VirtualEngine(seed=11)
    if fault:
        v.inject(fault)
    state, sync = create_twin("DT-BIAS", aircraft_id="MALE-01")
    monitor = BiasMonitor(ing)
    try:
        for f in run_profile(v, dt=DT, max_seconds=seconds):
            sim.send_frame(f)
            tel = ing.poll(now=f.t_s)
            derived = ing.derived()
            sync.sync(tel, derived=derived, physics=shadow.update(tel, DT),
                      alerts=rules.evaluate(tel, derived))
            monitor.update(state.residuals)
    finally:
        sim.close()
        ing.close()
    return monitor, ing.telemetry


def test_a_healthy_engine_reports_no_instrument_offset():
    monitor, _ = _fly("bias_healthy")
    flagged = {n: b.as_dict() for n, b in monitor.bias.items() if b.level != "none"}
    assert flagged == {}, flagged
    assert monitor.indicators()["instrument_offset_fraction_fs"] == 0.0


def test_a_drifting_oil_pressure_sensor_is_measured_and_left_open():
    """One sensor, no second source: the engine and the instrument both stay open.

    Measured 5.6 to 6.4 psi against the twin for this fault; the injected bias is
    0.55 bar at full severity, here 0.8 of it, which is 6.4 psi.
    """
    monitor, _ = _fly("bias_oilp", _drift("oil_pressure"))
    b = monitor.bias["oil_pressure"]
    assert b.offset == pytest.approx(0.8 * 0.55 * 14.5038, abs=1.5)
    assert b.level in ("drift", "fault")
    assert b.attribution == "unattributed"
    assert "nothing else measures" in b.evidence
    assert monitor.indicators()["instrument_offset_fraction_fs"] == 0.0
    assert monitor.indicators()["sensor_offset_fraction_fs"] > 0.0


def test_a_real_cooling_fault_is_never_called_a_sensor_drift():
    """The case the offset alone cannot settle: cooling degradation reads hot too."""
    monitor, _ = _fly("bias_cooling", InjectedFault(
        mode=FaultMode.COOLING_DEGRADATION, onset_hours=0.0, severity=0.8, ramp_hours=0.02))
    assert monitor.bias["cht"].level in ("drift", "fault")
    assert monitor.bias["cht"].attribution == "unattributed"
    assert monitor.indicators()["instrument_offset_fraction_fs"] == 0.0


def test_a_drifting_lane_sensor_is_blamed_on_the_instrument():
    """Manifold pressure is measured on both FADEC lanes, and only lane A drifts."""
    monitor, tel = _fly("bias_map", _drift("manifold_pressure", severity=1.0))
    b = monitor.bias["manifold_pressure"]
    assert b.level in ("drift", "fault"), b.as_dict()
    assert b.attribution == "instrument", b.as_dict()
    assert "lanes disagree" in b.evidence
    assert monitor.indicators()["instrument_offset_fraction_fs"] > 0.0
    assert tel.channels["manifold_pressure"].lane_delta is not None


def test_the_drift_indicator_is_an_offset_not_a_scatter():
    from layer3_ai.rul_fault import INDICATORS

    ind = INDICATORS["sensor_drift"]
    assert ind.degraded_key == "bias_drift_fraction_fs"
    assert ind.fault_key == "bias_fault_fraction_fs"
    assert "offset" in ind.name
