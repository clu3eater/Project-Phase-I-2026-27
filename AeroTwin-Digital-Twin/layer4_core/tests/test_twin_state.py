"""Tests for the twin state and the shadow model.

Two things are being guarded here, and only one of them is the schema.

The schema tests check that invalid state is REJECTED rather than stored --
a health index of 1.4, an unknown fault name, a remaining-life figure with no
confidence interval. Those are cheap tests and they matter, because everything
downstream (console, reports, fleet view) trusts this object.

The shadow-model tests are the important ones. They check the property the
whole digital twin rests on: that the residual actually moves when the engine
degrades. A shadow that quietly tracks the failing engine would still produce a
twin that validates, serialises and renders perfectly -- and detects nothing.
``test_shadow_stays_as_new_...`` and the residual-shift tests are the guard on
that failure mode.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from layer1_edge.can_ingest import CanIngest, ValueState
from layer1_edge.can_simulator import CanSimulator
from layer1_edge.edge_rules import RuleEngine
from layer2_physics.degradation import FaultMode, InjectedFault
from layer2_physics.engine_sim import VirtualEngine, run_profile
from layer4_core.shadow_model import ShadowModel
from layer4_core.twin_state import (
    FAULT_KEYS,
    DegradationEstimate,
    HealthIndices,
    Measurement,
    RemainingLife,
    TwinMetadata,
    create_twin,
)

DT = 0.5
SECONDS = 700.0


def _fly(fault=None, channel="x", seconds=SECONDS):
    """Run a mission through the full stack and return the finished twin."""
    sim = CanSimulator(interface="virtual", channel=f"tw_{channel}")
    ing = CanIngest(interface="virtual", channel=f"tw_{channel}")
    rules = RuleEngine()
    shadow = ShadowModel()
    veng = VirtualEngine(seed=11)
    if fault:
        veng.inject(fault)
    state, sync = create_twin("DT-TEST", aircraft_id="MALE-01")
    try:
        for frame in run_profile(veng, dt=DT, max_seconds=seconds):
            sim.send_frame(frame)
            tel = ing.poll(now=frame.t_s)
            derived = ing.derived()
            alerts = rules.evaluate(tel, derived)
            sync.sync(tel, derived=derived, physics=shadow.update(tel, DT), alerts=alerts)
        sync.apply_fault_evidence(network=None, source="not scored: test harness",
                                  rule_levels=rules.active_fault_modes())
    finally:
        sim.close()
        ing.close()
    return state, sync, shadow


@pytest.fixture(scope="module")
def healthy():
    return _fly(channel="healthy")


@pytest.fixture(scope="module")
def cooling():
    return _fly(
        InjectedFault(
            mode=FaultMode.COOLING_DEGRADATION,
            severity=0.8,
            onset_hours=0.0,
            ramp_hours=0.02,
        ),
        channel="cool",
    )


# ---------------------------------------------------------------------------
# Schema: invalid state must be rejected, not stored
# ---------------------------------------------------------------------------


def test_twin_is_built_from_the_engine_configuration():
    """Identity and both TBO clocks come from config, never from code."""
    state, _ = create_twin("DT-1", engine_key="rotax_915is")
    assert state.metadata.engine_type == "ROTAX_915IS"
    assert state.metadata.tbo_hours == 1200.0
    assert state.metadata.tbo_calendar_years == 15.0


def test_unknown_field_is_rejected():
    """A typo must fail loudly rather than create a field nobody reads."""
    with pytest.raises(ValidationError):
        TwinMetadata(twin_id="DT-1", total_flght_hours=10.0)


def test_health_index_outside_unit_range_is_rejected():
    with pytest.raises(ValidationError):
        HealthIndices(composite=1.4)
    with pytest.raises(ValidationError):
        HealthIndices(thermal=-0.1)


def test_unknown_fault_name_is_rejected():
    """The eight problem-statement faults are the only ones that exist."""
    state, sync = create_twin("DT-1")
    with pytest.raises(ValidationError):
        sync.apply_predictions(fault_probability={"gremlins": 0.5})


def test_fault_probability_must_be_a_probability():
    state, sync = create_twin("DT-1")
    with pytest.raises(ValidationError):
        sync.apply_predictions(fault_probability={"misfire": 1.7})


def test_remaining_life_without_an_interval_is_not_reportable():
    """PRD Part 4 section 7.4a: a bare RUL number must not reach the operator.

    The point-estimate is meaningless to a maintenance decision without the
    interval around it, and displaying one invites false confidence.
    """
    assert not RemainingLife(hours=340.0).reportable
    assert RemainingLife(hours=340.0, lower_hours=280.0, upper_hours=410.0).reportable


def test_tbo_respects_whichever_clock_runs_out_first():
    """1200 h OR 15 years -- a rarely-flown engine still ages (DEV-26)."""
    md = TwinMetadata(
        twin_id="DT-1",
        installation_date=datetime.now(UTC) - timedelta(days=int(14.5 * 365.25)),
        total_flight_hours=200.0,
    )
    assert md.tbo_hours_remaining == pytest.approx(1000.0)
    # Half a year of calendar life left is far less than 1000 hours of flying.
    assert md.tbo_remaining_hours_effective(hours_per_year=300.0) < 1000.0
    assert md.tbo_years_remaining() == pytest.approx(0.5, abs=0.1)


# ---------------------------------------------------------------------------
# Validity is carried through, not discarded
# ---------------------------------------------------------------------------


def test_a_residual_from_an_unusable_measurement_is_unusable_not_zero():
    """The difference matters more than it looks.

    A zero residual says "the engine matches prediction". An unusable residual
    says "we do not know". Collapsing the second into the first is how a
    monitoring system talks itself into believing a failing engine is healthy.
    """
    _, sync = create_twin("DT-1")
    bad = Measurement(value=None, state=ValueState.MISSING.value)
    res = sync._residual("cht", bad, predicted=110.0)
    assert res.usable is False
    assert res.delta is None
    assert res.samples == 0


def test_stale_measurements_do_not_feed_the_running_mean():
    _, sync = create_twin("DT-1")
    good = Measurement(value=115.0, state=ValueState.VALID.value)
    stale = Measurement(value=115.0, state=ValueState.STALE.value)
    sync._residual("cht", good, 110.0)
    sync._residual("cht", stale, 110.0)
    assert sync._residual_counts["cht"] == 1


def test_running_mean_accumulates_over_a_mission(healthy):
    state, _, _ = healthy
    cht = state.residuals.cht
    assert cht.usable
    assert cht.samples > 500
    assert cht.mean_delta is not None


# ---------------------------------------------------------------------------
# The shadow model -- the part that makes the twin a twin
# ---------------------------------------------------------------------------


def test_shadow_declines_to_predict_when_the_engine_is_not_running():
    """No answer beats a stale answer.

    A prediction carried over from the last valid operating point looks exactly
    like a real one to everything downstream.
    """
    shadow = ShadowModel()

    class _Stub:
        def get(self, name):
            return 0.0 if name == "rpm" else None

    assert shadow.update(_Stub(), DT) is None
    assert shadow.status.usable is False
    assert shadow.status.skipped_no_rpm == 1


def test_shadow_withholds_its_air_data_when_airspeed_is_missing():
    """A missing airspeed is not a parked aircraft (audit 15 Sep, P0).

    Taken as 0 km/h it removed ram-air cooling, so the shadow expected a hotter
    engine than the one flying and a real overheat shrank in the residual.
    """
    shadow = ShadowModel()

    class _Stub:
        def __init__(self, **values):
            self.values = values

        def get(self, name):
            return self.values.get(name)

    air = {"altitude_ft": 8000.0, "oat": 5.0}
    assert shadow._ambient(_Stub(**air)) is None
    assert shadow._ambient(_Stub(**air, airspeed_kmh=150.0)) is not None
    assert shadow._ambient(_Stub(**air, airspeed_kmh=0.0)) is not None  # a measured zero counts


def test_shadow_stays_as_new_through_a_whole_mission(cooling):
    """The reference must not degrade, even while flying a degrading engine.

    If the shadow aged alongside the real engine the residual would stay flat
    and the twin would detect nothing -- while still looking entirely healthy
    from the outside.
    """
    _, _, shadow = cooling
    factors = shadow.model.degradation
    assert factors.cooling_efficiency == pytest.approx(1.0)
    assert factors.injector_condition == pytest.approx(1.0)
    assert factors.bearing_clearance_mm > 0.0  # as-new, not the 0.0 default
    assert shadow.status.steps > 500


def test_cooling_degradation_shifts_the_cht_residual(healthy, cooling):
    """The headline claim: degradation shows up as a residual.

    Scale build-up in the coolant passages impedes heat OUT of the head, so the
    real engine runs hotter than an as-new engine would at the same operating
    point. That gap is visible long before any temperature limit is reached.
    """
    h_state, _, _ = healthy
    c_state, _, _ = cooling
    h = h_state.residuals.cht.mean_delta
    c = c_state.residuals.cht.mean_delta
    assert h is not None and c is not None
    assert c > h + 3.0, f"CHT residual barely moved: healthy {h:.2f} -> degraded {c:.2f}"


def test_cooling_degradation_widens_the_head_to_coolant_gap(healthy, cooling):
    """The signature that separates cooling loss from a hot day.

    A thermostatted loop holds coolant temperature nearly constant, so ambient
    heat raises BOTH numbers while a fouled head-to-coolant path raises only
    the head. The difference is what tells the two apart
    (PRD Part 2 section 10.3).
    """
    h_state, _, _ = healthy
    c_state, _, _ = cooling
    assert c_state.residuals.cht_minus_coolant > h_state.residuals.cht_minus_coolant + 3.0


def test_healthy_engine_tracks_its_shadow_closely(healthy):
    """The other half of the claim: no fault, no residual.

    A reference model that disagrees with a healthy engine would raise a
    residual alarm on every airframe in the fleet.
    """
    state, _, _ = healthy
    assert abs(state.residuals.cht.mean_delta) < 8.0
    assert abs(state.residuals.coolant.mean_delta) < 8.0


# ---------------------------------------------------------------------------
# Synchronisation bookkeeping
# ---------------------------------------------------------------------------


def test_sync_populates_the_reported_state(healthy):
    state, _, _ = healthy
    r = state.reported
    assert r.rpm.usable and r.rpm.value > 1000.0
    assert r.cht.spread is not None
    assert r.vibration.rms_total is not None
    assert r.channels_total > 30


def test_data_quality_is_reported_alongside_the_data(healthy):
    """The console must be able to say how much of the frame it trusts."""
    state, _, _ = healthy
    assert 0.0 <= state.reported.data_quality <= 1.0
    assert state.reported.channels_usable + state.reported.channels_stale \
        + state.reported.channels_invalid <= state.reported.channels_total


def test_flight_hours_accumulate_only_while_running(healthy):
    state, _, _ = healthy
    assert 0.0 < state.metadata.total_flight_hours < SECONDS / 3600.0 + 1e-6
    assert state.metadata.tbo_hours_remaining < 1200.0


def test_lifecycle_advances_on_first_sync(healthy):
    state, _, _ = healthy
    assert state.metadata.lifecycle == "ACTIVE"
    assert state.sync_count > 1000


def test_life_to_date_extremes_are_recorded(healthy):
    """Usage monitoring: the maxima outlive any single frame."""
    state, _, _ = healthy
    h = state.history
    assert h.max_cht_recorded >= state.reported.cht_max.value
    assert h.max_rpm_recorded >= state.reported.rpm.value
    assert h.max_egt_recorded is not None


def test_alerts_are_mirrored_into_the_twin(cooling):
    """Replay and reporting read the twin, not the rule engine."""
    state, _, _ = cooling
    assert isinstance(state.alerts.active, list)
    assert state.alerts.master_warning == any(a.level >= 4 for a in state.alerts.active)


def test_a_fault_probability_is_the_trained_head_or_nothing_at_all(cooling):
    """It used to be the rule level times 0.20 (audit 15 Sep, P1-1).

    A YELLOW alert became 0.60 whatever the evidence behind it: arithmetic on
    an alert level, wearing the clothes of a probability. With nothing scoring
    the engine there is no probability to show, and the source says which case
    the reader is looking at.
    """
    state, _, _ = cooling
    p = state.predicted
    assert set(p.fault_probability) == set(FAULT_KEYS)
    assert p.fault_probability_source.startswith("not scored"), p.fault_probability_source
    assert all(v == 0.0 for v in p.fault_probability.values()), (
        "nothing scored these, so no probability may be shown")
    # What the rules DID see survives, as the alert levels they actually are.
    assert p.rule_fault_levels, "the rule evidence must not be lost"
    assert all(1 <= lvl <= 5 for lvl in p.rule_fault_levels.values())


def test_a_scored_network_supplies_the_fault_probabilities():
    state, sync = create_twin("DT-FAULT", aircraft_id="MALE-01")
    sync.apply_fault_evidence(
        network={"cooling_degradation": 0.81, "misfire": 0.02},
        source="Tier-3 fault head", rule_levels={"cooling_degradation": 4})
    p = state.predicted
    assert p.fault_probability["cooling_degradation"] == pytest.approx(0.81)
    assert p.fault_probability["misfire"] == pytest.approx(0.02)
    assert p.fault_probability["injector_abnormal"] == 0.0
    assert p.fault_probability_source == "Tier-3 fault head"
    assert p.rule_fault_levels == {"cooling_degradation": 4}


def test_low_model_confidence_forces_the_rule_based_fallback():
    """PRD Part 4 section 7.4b: the system must SAY when it has fallen back."""
    state, sync = create_twin("DT-1")
    sync.apply_predictions(model_confidence=0.95)
    assert state.predicted.rule_based_fallback is False
    sync.apply_predictions(model_confidence=0.20)
    assert state.predicted.rule_based_fallback is True


# ---------------------------------------------------------------------------
# Serialisation and audit
# ---------------------------------------------------------------------------


def test_twin_serialises_to_json(healthy):
    state, _, _ = healthy
    payload = state.to_json()
    assert '"schema_version"' in payload
    assert len(payload) > 2000


def test_change_hash_is_stable_and_sensitive():
    """PRD Part 1 section 2.5: every state mutation is auditable."""
    state, _ = create_twin("DT-1")
    before = state.change_hash()
    assert state.change_hash() == before
    state.metadata.total_flight_hours = 42.0
    assert state.change_hash() != before


# ---------------------------------------------------------------------------
# PRD Part 1 section 6.1 completeness -- fields the first pass missed
# ---------------------------------------------------------------------------


def test_ambient_pressure_is_derived_from_pressure_altitude(healthy):
    """PRD Part 1 section 6.1 lists ambient pressure; no transducer supplies it.

    Pressure altitude IS a pressure measurement expressed in feet, so the
    conversion is exact rather than an estimate. ISA at 18,000 ft is 506 hPa.
    """
    state, _, _ = healthy
    env = state.reported.environmental
    assert env.ambient_pressure_hpa is not None
    assert 100.0 < env.ambient_pressure_hpa < 1100.0


def test_alternator_voltage_is_absent_rather_than_invented(healthy):
    """The 915 iS publishes one regulated bus voltage, not two.

    Mirroring bus voltage into this field would manufacture a measurement that
    no sensor produces -- the same substitution error the ingest layer exists
    to prevent.
    """
    state, _, _ = healthy
    assert state.reported.electrical.alternator_voltage.state == ValueState.MISSING.value
    assert state.reported.electrical.bus_voltage.usable


def test_start_stop_and_thermal_cycles_are_counted(healthy):
    """PRD Part 2 section 12: one cycle = one start-stop.

    These stayed at zero in the first implementation -- the fields existed and
    were never incremented, so consumed cycle life would have read as nil for
    the life of the engine.
    """
    state, _, _ = healthy
    assert state.metadata.total_cycles == 1
    assert state.history.thermal_cycles == 1


def test_cycle_counting_uses_hysteresis_not_a_bare_threshold():
    """Noise around the counting threshold must not inflate consumed life."""
    _, sync = create_twin("DT-1")
    r = sync.state.reported
    for rpm in (1501.0, 1499.0, 1502.0, 1498.0, 1503.0):
        r.rpm = Measurement(value=rpm, state=ValueState.VALID.value)
        sync._count_cycles()
    assert sync.state.metadata.total_cycles == 1

    # A genuine stop and restart is a second cycle.
    r.rpm = Measurement(value=0.0, state=ValueState.VALID.value)
    sync._count_cycles()
    r.rpm = Measurement(value=2000.0, state=ValueState.VALID.value)
    sync._count_cycles()
    assert sync.state.metadata.total_cycles == 2


def test_healthy_engine_gets_an_advisory_that_says_nothing_is_wrong(healthy):
    """MIL-STD-411F 4.1.1a extends to the advisory, not just the alert stack."""
    state, _, _ = healthy
    adv = state.advisory
    assert adv.severity == "INFO"
    assert adv.fault_codes == []
    assert adv.recommended_action


def test_advisory_names_an_action_and_a_deadline_not_just_a_fault():
    """PS section F / PRD Part 1 section 6.1.

    An advisory carrying only a fault legend is a status light. The maintenance
    engineer needs what to do and by when.
    """
    state, _, _ = _fly(
        InjectedFault(
            mode=FaultMode.INJECTOR_ABNORMAL, severity=0.8,
            onset_hours=0.0, ramp_hours=0.02,
        ),
        channel="adv",
    )
    adv = state.advisory
    assert adv.severity in ("WARNING", "EMERGENCY", "CAUTION")
    assert adv.recommended_action
    assert adv.time_to_action
    assert adv.fault_codes
    # Until Layer 3 exists the advisory is rule-driven, and it must say so.
    assert adv.source == "rules"
    assert adv.shap_explanation == {}


def test_model_residual_is_accumulated_not_instantaneous(healthy):
    """A one-sample "RMSE" is an instantaneous magnitude dominated by noise.

    Measured before this was fixed: the injector fault produced a LOWER
    model_residual than a healthy engine, purely from where the final frame
    landed.
    """
    state, sync, _ = healthy
    assert state.simulated.model_residual is not None
    assert sync._sq_n > 500


def test_degradation_estimate_matches_the_simulator_field_names():
    """The estimate is only scorable if it lines up with the ground truth."""
    from layer2_physics.degradation import DegradationFactors

    truth = set(DegradationFactors().as_dict())
    assert set(DegradationEstimate.model_fields) <= truth


def test_degradation_estimate_drops_auxiliary_physics_inputs():
    """Viscosity ratio and bearing clearance are model inputs, not health factors."""
    _, sync = create_twin("DT-1")
    sync.apply_predictions(
        degradation_factors={"cooling_efficiency": 0.7, "bearing_clearance_mm": 0.09}
    )
    assert sync.state.predicted.degradation_factors.cooling_efficiency == 0.7


def test_physics_constraints_are_checked_on_the_prediction():
    """PRD Part 1 section 6.2: a diverged model must be caught, not published."""
    state, sync = create_twin("DT-1")
    state.simulated.model_available = True
    state.simulated.cht_predicted = 400.0  # impossible on a liquid-cooled head
    sync._check_physics_constraints()
    assert state.simulated.physics_constraint_violations >= 1


def test_healthy_prediction_violates_no_physics_constraints(healthy):
    state, _, _ = healthy
    assert state.simulated.physics_constraint_violations == 0


def test_rul_carries_cycles_as_well_as_hours():
    """A short-sortie fleet burns cycle life far faster than hours."""
    rul = RemainingLife(hours=300.0, cycles=420, lower_hours=250.0, upper_hours=360.0)
    assert rul.reportable and rul.cycles == 420


def test_an_unassessed_engine_is_not_graded_by_its_cold_indices():
    """A parked, cold engine must not be told to ground itself.

    Measured on the console: after a restart, with the engine parked and never
    yet warm, the advisory read EMERGENCY "ELECTRICAL subsystem UNSAFE --
    ground the aircraft". The alternator gives no current on a stopped engine,
    so the electrical index computed from it is low -- which is the operating
    point, not wear. The composite health already waits for a warm, loaded
    engine (live.py `_assessable`); the advisory must honour the same gate.
    """
    _, sync = create_twin("DT-COLD")
    sync.state.predicted.health = HealthIndices(
        composite=0.95, thermal=0.97, mechanical=0.96, electrical=0.30,
        combustion=0.95, band="EXCELLENT")

    sync.health_assessed = False
    sync.refresh_advisory()
    assert sync.state.advisory.severity == "INFO"

    # Once the condition has been judged warm, the same low index IS a finding.
    sync.health_assessed = True
    sync.refresh_advisory()
    assert sync.state.advisory.severity == "EMERGENCY"
    assert "ELECTRICAL" in sync.state.advisory.message
