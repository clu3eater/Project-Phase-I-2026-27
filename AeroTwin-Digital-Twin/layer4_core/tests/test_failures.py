"""Sudden engine failures, and the master warning after an acknowledgement.

Reported from use: with every fault injected the engine carried on at cruise
power, a fuel cut changed nothing, and once the master warning had been
acknowledged it never lit again. The eight fault modes are WEAR; these are
FAILURES -- the engine stops making power -- and each must be annunciated as
a new warning whatever was acknowledged before it.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DT_PERSIST", "0")

from layer2_physics import engine_sim as es  # noqa: E402
from layer4_core.live import LiveTwin  # noqa: E402


def _cruising() -> LiveTwin:
    t = LiveTwin(seed=7, speed=1000.0)
    t.park()
    t._thread = object()
    t.begin_profile(es.mission_profile(0.5, 8000), kind="mission", label="T")
    for _ in range(900):
        t._tick()
        if (t.snapshot().sortie or {}).get("holding"):
            t.launch()
    return t


def _state(t: LiveTwin):
    s = t.snapshot()
    r = s.twin["reported"]
    return (r["rpm"]["value"], r["environmental"]["altitude_ft"]["value"],
            s.twin["alerts"]["master_warning"],
            {a["legend"] for a in s.twin["alerts"]["active"]}, r)


@pytest.mark.parametrize("failure", ["fuel_starvation", "ignition_failure"])
def test_a_combustion_failure_stops_the_engine_and_warns(failure):
    t = _cruising()
    try:
        rpm0, alt0, _, _, _ = _state(t)
        assert rpm0 > 4000
        t.inject("abnormal_vibration", 0.95)          # a warning first ...
        for _ in range(300):
            t._tick()
        assert _state(t)[2]
        t.acknowledge()                                # ... acknowledged
        t._tick()
        assert not _state(t)[2]
        t.fail(failure)
        for _ in range(60):
            t._tick()
        rpm, alt, mw, legends, r = _state(t)
        assert rpm < 100, "the engine must stop"
        assert alt < 8000 - 100, "the aircraft must glide down"
        assert "ENGINE FAILURE" in legends
        assert mw, "a new warning re-lights the master after an acknowledgement"
        assert "TELEMETRY STALE" not in legends and "SENSOR FAULT" not in legends
    finally:
        t._thread = None
        t.stop()


def test_oil_loss_warns_then_seizes_the_engine():
    t = _cruising()
    try:
        t.fail("oil_loss")
        for _ in range(40):
            t._tick()
        assert "OIL PRESS LOW" in _state(t)[3]
        for _ in range(160):
            t._tick()
        rpm, _, mw, legends, _ = _state(t)
        assert rpm < 100 and "ENGINE FAILURE" in legends and mw
    finally:
        t._thread = None
        t.stop()


def test_coolant_loss_overheats_the_heads():
    t = _cruising()
    try:
        t.fail("coolant_loss")
        for _ in range(160):
            t._tick()
        rpm, _, mw, legends, r = _state(t)
        assert r["cht_max"]["value"] > 135.0
        assert "CHT HIGH" in legends and mw
    finally:
        t._thread = None
        t.stop()


def test_a_normal_shutdown_is_not_an_engine_failure():
    t = LiveTwin(seed=5, speed=1000.0)
    t.park()
    t._thread = object()
    t.begin_profile(es.ground_run_profile(), kind="ground_run")
    seen = set()
    try:
        for _ in range(3000):
            t._tick()
            seen |= {a["legend"] for a in t.snapshot().twin["alerts"]["active"]}
            if (t.snapshot().sortie or {}).get("state") == "complete":
                break
        assert "ENGINE FAILURE" not in seen
    finally:
        t._thread = None
        t.stop()


def test_after_a_forced_landing_the_engine_is_secured_and_the_warning_clears():
    """Reported from use: after the engine stopped, the throttle stayed at
    cruise on the ground, so ENGINE FAILURE -- and its tone -- never cleared."""
    t = _cruising()
    try:
        t.fail("fuel_starvation")
        for _ in range(60):
            t._tick()
        assert "ENGINE FAILURE" in _state(t)[3]
        for _ in range(1500):
            t._tick()
            if (t.snapshot().sortie or {}).get("state") == "complete":
                break
        for _ in range(20):
            t._tick()
        rpm, alt, mw, legends, r = _state(t)
        assert alt <= 0.0 and rpm == 0.0
        assert (t.snapshot().sortie or {}).get("state") == "complete"
        assert "ENGINE FAILURE" not in legends and not mw
    finally:
        t._thread = None
        t.stop()


def test_a_stopped_engine_reads_steady_zeros_and_raises_no_running_cautions():
    """Reported from use: after shutdown the caution tone kept restarting and
    values kept moving. Rules that judge a RUNNING engine flickered on the noise
    of a stopped one; flow and oil pressure read noise about zero, negative."""
    from layer1_edge.edge_rules import RUNNING_ONLY

    t = LiveTwin(seed=5, speed=1000.0)
    t.park()
    t._thread = object()
    t.begin_profile(es.ground_run_profile(), kind="ground_run")
    try:
        for i in range(3000):
            t._tick()
            if i == 300:
                for f in ("misfire", "injector_abnormal", "abnormal_vibration",
                          "combustion_instability"):
                    t.inject(f, 0.9)
            if (t.snapshot().sortie or {}).get("state") == "complete":
                break
        oil_t0 = _state(t)[4]["oil_temperature"]["value"]
        raised = set()
        for _ in range(300):
            t._tick()
            s = t.snapshot()
            raised |= {a["rule_id"] for a in s.twin["alerts"]["active"]}
            r = s.twin["reported"]
            assert r["fuel_flow"]["value"] == 0.0
            assert r["oil_pressure"]["value"] == 0.0
        assert not raised & RUNNING_ONLY, raised & RUNNING_ONLY
        assert _state(t)[4]["oil_temperature"]["value"] < oil_t0 - 1.0, "oil cools"
        assert _state(t)[4]["fuel_pressure"]["value"] < 1.0, "pumps off"
    finally:
        t._thread = None
        t.stop()
