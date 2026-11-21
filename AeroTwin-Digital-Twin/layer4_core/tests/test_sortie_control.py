"""The engine starts when a person starts it, and does what they command.

A squadron's engine does not fly itself because a browser opened: it is
parked, started from cold for a mission, held at warm-up until launch
clearance, can be recalled, and is shut down. These run the real pipeline.
"""

from __future__ import annotations

import pytest

from layer2_physics import engine_sim as es
from layer3_ai.efficiency import EfficiencyTracker
from layer4_core.live import LiveTwin


def _run_until(twin, pred, max_ticks):
    for _ in range(max_ticks):
        twin._tick()
        if pred(twin.snapshot()):
            return True
    return False


@pytest.fixture
def twin():
    t = LiveTwin(seed=7, speed=1000.0)
    yield t
    t._thread = None
    t.stop()


@pytest.mark.slow
def test_parked_launched_recalled_and_shut_down(twin):
    twin.park()
    for _ in range(40):
        twin._tick()
    s = twin.snapshot()
    assert s.sortie["state"] == "parked" and s.sortie["phase"] == es.PARKED_PHASE
    assert twin.veng.model.stopped
    hours_parked = twin.veng.flight_hours

    twin._thread = object()        # commands now queue for the twin thread
    assert not twin.launch()        # nothing is holding yet
    twin.begin_profile(es.mission_profile(0.01, 8000.0), kind="mission", label="MSN-T")
    assert _run_until(twin, lambda s: s.sortie.get("holding")
                      and (s.twin["reported"]["oil_temperature"] or {}).get("value", 0) >= 50.0,
                      900)
    s = twin.snapshot()
    assert s.sortie["kind"] == "mission" and s.sortie["label"] == "MSN-T"
    # the hold holds: without clearance it does not take off
    for _ in range(100):
        twin._tick()
    assert twin.snapshot().sortie["phase"] == es.HOLD_PHASE
    assert twin.launch()
    assert _run_until(twin, lambda s: s.sortie.get("phase") == "CLIMB", 600)
    assert twin.rtb()
    twin._tick()
    assert twin.snapshot().sortie["phase"] == "DESCENT"
    assert _run_until(twin, lambda s: s.sortie.get("state") == "complete", 4000)
    assert twin.veng.flight_hours > hours_parked

    # Shut down and sitting there: a stopped engine is not an oil-pressure
    # exceedance, however long it sits.
    for _ in range(200):
        twin._tick()
    exc = twin.snapshot().flight_record.get("exceedances") or []
    assert not any(e["parameter"] == "oil pressure" for e in exc), exc


@pytest.mark.slow
def test_a_ground_run_judges_the_engine_and_ends_stopped(twin):
    twin.begin_profile(es.ground_run_profile(), kind="ground_run")
    judged = False
    for _ in range(1100):
        twin._tick()
        s = twin.snapshot()
        judged = judged or s.health.get("chi") is not None
        if s.sortie.get("state") == "complete":
            break
    assert s.sortie["kind"] == "ground_run" and s.sortie["state"] == "complete"
    assert judged, "a ground run must hold the engine where the twin can judge it"
    assert s.health["chi"] > 0.9
    # a sound engine's ground run raises nothing
    assert not [a for a in s.maintenance.get("actions", [])
                if a.get("severity") in ("CAUTION", "WARNING", "EMERGENCY")]


def test_an_aged_engine_keeps_its_logbook_hours_across_a_restart(tmp_path):
    a = LiveTwin(twin_id="T-AGE", seed=3, persist=True, life_dir=tmp_path)
    a.age_engine(250.0)
    assert a.state.metadata.total_flight_hours == pytest.approx(250.0)
    assert a.state.history.hours_since_inspection == pytest.approx(50.0)
    a.save_engine_life()
    a.sim.close(); a.ingest.close()
    b = LiveTwin(twin_id="T-AGE", seed=3, persist=True, life_dir=tmp_path)
    try:
        assert b.engine_life_restored is not None
        assert b.state.metadata.total_flight_hours == pytest.approx(250.0)
        assert b.state.history.hours_since_inspection == pytest.approx(50.0)
    finally:
        b.sim.close(); b.ingest.close()


def test_efficiency_does_not_divide_by_zero_as_the_engine_runs_down():
    e = EfficiencyTracker("rotax_915is")
    out = e.update(fuel_flow_lph=0.0, power_kw=12.0, rpm=900.0)
    assert out.thermal_efficiency is None and "no fuel" in out.reason


@pytest.mark.slow
def test_an_engine_never_cleared_to_launch_is_shut_down(twin):
    twin.WARMUP_HOLD_LIMIT_S = 150.0
    twin.begin_profile(es.mission_profile(0.01, 8000.0), kind="mission")
    assert _run_until(twin, lambda s: s.sortie.get("state") == "complete", 1500)
    s = twin.snapshot()
    assert s.sortie["phase"] == "SHUTDOWN" and twin.veng.model.stopped
