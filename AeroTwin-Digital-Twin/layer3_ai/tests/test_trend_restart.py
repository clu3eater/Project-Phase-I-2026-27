"""After maintenance the trends restart from the engine as it now is.

A health baseline, a degradation rate or a per-fault slope fitted across a
repair joins two different engines, and forecasts nothing about either.
"""

from __future__ import annotations

from layer3_ai.health import HealthEstimator
from layer3_ai.rul_fault import FaultRul
from layer3_ai.rul_physics import PhysicsRul


def test_the_health_baseline_is_relearned_after_maintenance():
    h = HealthEstimator()
    for i in range(300):
        h.track(0.95 - 0.0005 * i, flight_hours=i * 0.01)
    assert h._baseline is not None
    h.restart_trend()
    out = h.track(0.99, flight_hours=3.0)
    assert out["baseline"] is None and out["cusum"] == 0.0
    assert not h.onset_detected and h.onset_hours is None


def test_remaining_life_forgets_the_decline_of_the_engine_before_the_repair():
    rul = PhysicsRul(min_samples=10)
    for i in range(400):
        est = rul.update(0.95 - 0.0004 * i, flight_hours=i * 0.5)
    assert est.rate_per_hour is not None and est.rate_per_hour < 0.0
    rul.restart()
    est = rul.update(0.99, flight_hours=200.5)
    assert est.hours is None
    assert est.reason == "establishing the degradation trend"


def test_only_the_repaired_fault_loses_its_trend():
    fr = FaultRul()
    for i in range(120):
        fr.observe(i / 60.0, {"injector_abnormal": 100.0 + i,
                              "cooling_degradation": 2.0 + 0.01 * i})
    assert fr._points("injector_abnormal")
    fr.restart(["injector_abnormal"])
    assert fr._points("injector_abnormal") == []
    assert len(fr._points("cooling_degradation")) > 1
