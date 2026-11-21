"""Completed maintenance restores what the work physically renews, and no more.

The action ids are the maintenance library in configs/thresholds.yaml
(advisory.actions). Each test pins one physical fact about a job: an oil change
renews oil but cures no fault, new spark plugs cure a misfire but leave
combustion deposits, an inspection replaces nothing unless parts were fitted,
and no job prevents a fault that has not yet arrived.
"""

from __future__ import annotations

import math

import pytest

from common import config
from layer2_physics.degradation import DegradationEngine, FaultMode, InjectedFault

ENGINE = config.load_engine("rotax_915is")


def _engine_at(hours: float = 200.0) -> DegradationEngine:
    deg = DegradationEngine(ENGINE)
    deg.hours = hours
    return deg


def _started(mode: FaultMode, deg: DegradationEngine, severity: float = 0.8) -> InjectedFault:
    fault = InjectedFault(mode=mode, onset_hours=deg.hours - 10.0, severity=severity,
                          ramp_hours=0.0)
    deg.inject(fault)
    return fault


def test_an_oil_change_renews_the_oil_and_its_clock_but_cures_no_fault():
    deg = _engine_at()
    deg.factors.oil_quality, deg.factors.oil_viscosity_ratio = 0.40, 1.20
    deg.hours_since_oil_change = 95.0
    fault = _started(FaultMode.LUBRICATION_ISSUE, deg)
    done = deg.perform_maintenance("A1")
    assert deg.factors.oil_quality == 1.0 and deg.factors.oil_viscosity_ratio == 1.0
    assert deg.hours_since_oil_change == 0.0 and deg.oil_changes == 1
    assert fault.active, "fresh oil does not repair what is contaminating it"
    assert done == {"restored": ["oil_quality"], "faults_removed": []}


def test_new_spark_plugs_cure_a_misfire_but_leave_combustion_deposits():
    deg = _engine_at()
    deg.factors.combustion_efficiency = 0.88
    fault = _started(FaultMode.MISFIRE, deg)
    done = deg.perform_maintenance("A4")
    assert not fault.active
    assert deg.factors.combustion_efficiency == 0.88
    assert done["faults_removed"] == ["misfire"] and done["restored"] == []


def test_an_inspection_replaces_nothing_unless_parts_were_fitted():
    deg = _engine_at()
    design = deg.factors.bearing_clearance_mm
    deg.factors.bearing_condition, deg.factors.bearing_clearance_mm = 0.50, design * 1.5
    fault = _started(FaultMode.ABNORMAL_VIBRATION, deg)

    looked = deg.perform_maintenance("A5", repaired=False)
    assert looked == {"restored": [], "faults_removed": []}
    assert deg.factors.bearing_condition == 0.50 and fault.active

    replaced = deg.perform_maintenance("A5", repaired=True)
    assert deg.factors.bearing_condition == 1.0
    assert deg.factors.bearing_clearance_mm == pytest.approx(design)
    assert not fault.active
    assert replaced["faults_removed"] == ["abnormal_vibration"]


def test_cleaned_injectors_stay_clean_on_the_next_hour_of_running():
    deg = _engine_at()
    _started(FaultMode.INJECTOR_ABNORMAL, deg, severity=0.9)
    deg.advance(1.0)
    deg.perform_maintenance("A3")
    deg.advance(1.0)
    assert deg.factors.injector_condition > 0.95


def test_no_job_prevents_a_fault_that_has_not_arrived():
    deg = _engine_at()
    dealt = InjectedFault(mode=FaultMode.INJECTOR_ABNORMAL, onset_hours=math.inf,
                          severity=0.7)
    later = InjectedFault(mode=FaultMode.INJECTOR_ABNORMAL, onset_hours=deg.hours + 100.0,
                          severity=0.7)
    deg.inject(dealt)
    deg.inject(later)
    assert deg.perform_maintenance("A3")["faults_removed"] == []
    assert dealt.active and later.active


def test_an_overhaul_restores_every_engine_pathway_and_removes_every_started_fault():
    deg = _engine_at()
    design = deg.factors.bearing_clearance_mm
    f = deg.factors
    f.cooling_efficiency, f.oil_quality, f.combustion_efficiency = 0.6, 0.5, 0.85
    f.injector_condition, f.bearing_condition, f.turbocharger_condition = 0.5, 0.4, 0.7
    f.cooling_airflow, f.bearing_clearance_mm = 0.5, design * 1.8
    battery = f.battery_health = 0.6
    faults = [_started(m, deg) for m in (FaultMode.MISFIRE, FaultMode.OVERHEATING_TREND,
                                         FaultMode.SENSOR_DRIFT)]
    deg.perform_maintenance("A7")
    for name in ("cooling_efficiency", "oil_quality", "combustion_efficiency",
                 "injector_condition", "bearing_condition", "turbocharger_condition",
                 "cooling_airflow"):
        assert getattr(f, name) == 1.0, name
    assert f.bearing_clearance_mm == pytest.approx(design)
    assert f.battery_health == battery, "the battery is not part of the engine"
    assert not any(x.active for x in faults)


def test_an_unknown_action_is_refused():
    with pytest.raises(ValueError):
        _engine_at().perform_maintenance("A9")
