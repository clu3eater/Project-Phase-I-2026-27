"""Recording maintenance: the twin learns the work was done, and acts on it.

Before this, nothing told the twin that an oil change or an injector clean had
happened. The 100 h clock ran on, the health trend was fitted straight across
the repair, and remaining life went on projecting the decline of the engine as
it was before the work. These tests run the real pipeline, tick by tick.
"""

from __future__ import annotations

import pytest

from layer4_core.live import LiveTwin
from layer4_core.twin_state import TwinMetadata


def test_time_between_overhaul_runs_from_the_last_overhaul():
    md = TwinMetadata(twin_id="T", total_flight_hours=1500.0,
                      hours_at_last_overhaul=1100.0, tbo_hours=1200.0)
    assert md.hours_since_overhaul == pytest.approx(400.0)
    assert md.tbo_hours_remaining == pytest.approx(800.0)
    never = TwinMetadata(twin_id="N", total_flight_hours=300.0, tbo_hours=1200.0)
    assert never.tbo_hours_remaining == pytest.approx(900.0)


@pytest.fixture
def twin():
    t = LiveTwin(seed=7, speed=1000.0)
    yield t
    t.stop()


@pytest.mark.slow
def test_recorded_injector_work_restores_the_engine_and_restarts_its_trends(twin):
    for _ in range(3):
        twin._tick()
    twin.inject("injector_abnormal", 0.9, ramp_hours=0.001)
    for _ in range(3):
        twin._tick()

    rec = twin.record_maintenance("A3", by="mt.iyer")
    assert rec["status"] == "queued" and rec["repaired"] is True
    twin._tick()

    done = twin.snapshot().maintenance["performed"][-1]
    assert done["status"] == "applied"
    assert done["faults_removed"] == ["injector_abnormal"]
    assert "injector_condition" in done["restored"]
    assert "injector_abnormal" in done["trends_restarted"]
    assert twin.veng.degradation.factors.injector_condition > 0.95
    assert twin.snapshot().faults_injected == []
    assert twin.health._baseline is None


@pytest.mark.slow
def test_an_inspection_that_replaced_nothing_restarts_nothing(twin):
    for _ in range(3):
        twin._tick()
    twin.health._baseline = 0.97
    twin.record_maintenance("A5")
    twin._tick()
    done = twin.snapshot().maintenance["performed"][-1]
    assert done["repaired"] is False
    assert done["restored"] == [] and done["trends_restarted"] == []
    assert twin.health._baseline == 0.97, "the wear it found is still the evidence"


@pytest.mark.slow
def test_an_oil_change_restarts_the_hundred_hour_clock(twin):
    twin._tick()
    twin.state.history.hours_since_inspection = 120.0
    twin.record_maintenance("A1")
    twin._tick()
    assert twin.state.history.hours_since_inspection < 0.01
    assert twin.state.metadata.last_maintenance_date is not None


@pytest.mark.slow
def test_an_overhaul_puts_the_whole_overhaul_interval_ahead_again(twin):
    twin._tick()
    md = twin.state.metadata
    md.total_flight_hours = 900.0
    assert md.tbo_hours_remaining == pytest.approx(md.tbo_hours - 900.0)
    twin.record_maintenance("A7")
    twin._tick()
    assert md.hours_at_last_overhaul == pytest.approx(900.0)
    assert md.tbo_hours_remaining == pytest.approx(md.tbo_hours, abs=0.01)
    assert md.last_overhaul_date is not None
    done = twin.snapshot().maintenance["performed"][-1]
    assert done["trends_restarted"][:2] == ["composite health", "remaining life"]


@pytest.mark.slow
def test_an_unknown_action_is_refused_before_it_is_queued(twin):
    with pytest.raises(ValueError):
        twin.record_maintenance("A9")
