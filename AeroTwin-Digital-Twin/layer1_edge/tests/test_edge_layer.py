"""Tests for the edge layer: rule engine, fusion and offline buffer.

The rule-engine tests are the ones that matter most, because the alerting
semantics are the difference between a monitoring system and a colour-changing
dashboard. In particular the first test encodes MIL-STD-411F 4.1.1a -- the
system must be SILENT on a healthy engine. Every nuisance alert found during
development traced back to a real defect (a units error in the sensor model, a
trend rule differencing noisy endpoints, a flight profile commanding above max
continuous), so this test is the guard on all of them at once.
"""

from __future__ import annotations

import pytest

from common import config
from layer1_edge.can_ingest import CanIngest
from layer1_edge.can_simulator import CanSimulator
from layer1_edge.edge_buffer import EdgeBuffer, LinkState
from layer1_edge.edge_rules import (
    AlertCategory,
    AlertLevel,
    RuleEngine,
    build_rules,
)
from layer1_edge.sensor_fusion import (
    BiasEstimator,
    HampelFilter,
    LaneVote,
    RollingCorrelation,
    SensorFusion,
)
from layer2_physics.degradation import FaultMode, InjectedFault
from layer2_physics.engine_sim import VirtualEngine, run_profile


def _fly(fault=None, seconds=1100.0, channel="t"):
    """Run a mission end to end and return (engine, alerts-first-seen)."""
    sim = CanSimulator(interface="virtual", channel=f"tt_{channel}")
    ing = CanIngest(interface="virtual", channel=f"tt_{channel}")
    eng = RuleEngine()
    v = VirtualEngine(seed=11)
    if fault:
        v.inject(fault)
    seen: dict[str, float] = {}
    try:
        for frame in run_profile(v, dt=0.5, max_seconds=seconds):
            sim.send_frame(frame)
            tel = ing.poll(now=frame.t_s)
            state = eng.evaluate(tel, ing.derived())
            for a in state.active:
                seen.setdefault(a.rule_id, frame.t_s)
    finally:
        sim.close()
        ing.close()
    return eng, seen


# ---------------------------------------------------------------------------
# The rule engine
# ---------------------------------------------------------------------------


def test_healthy_engine_raises_no_alerts():
    """MIL-STD-411F 4.1.1a: no alerts when all systems operate normally.

    An alerting system that cries wolf on every flight teaches the operator to
    ignore it, which is worse than having none.
    """
    _eng, seen = _fly(channel="healthy")
    assert seen == {}, f"healthy engine raised {list(seen)}"


def test_every_rule_legend_obeys_the_message_syntax():
    """PRD Part 4 section 4.4 / MIL-STD-411F 5.2.5.1."""
    limit = int(config.load_thresholds()["alerting"]["legend_max_chars"])
    for rule in build_rules():
        assert len(rule.legend) <= limit, f"{rule.rule_id}: {rule.legend!r}"
        assert rule.legend == rule.legend.upper(), rule.rule_id
        assert "," not in rule.legend and "." not in rule.legend, rule.rule_id


def test_rule_evaluation_meets_the_latency_budget():
    """PRD Part 2 section 11.1: Tier-1 detection in under 5 ms."""
    sim = CanSimulator(interface="virtual", channel="tt_lat")
    ing = CanIngest(interface="virtual", channel="tt_lat")
    eng = RuleEngine()
    v = VirtualEngine(seed=3)
    worst = 0.0
    try:
        for frame in run_profile(v, dt=0.5, max_seconds=200.0):
            sim.send_frame(frame)
            tel = ing.poll(now=frame.t_s)
            state = eng.evaluate(tel, ing.derived())
            worst = max(worst, state.evaluation_ms)
    finally:
        sim.close()
        ing.close()
    assert worst < 5.0, f"worst-case rule latency {worst:.2f} ms exceeds the 5 ms budget"


@pytest.mark.parametrize(
    "fault_mode,expect_rule",
    [
        (FaultMode.INJECTOR_ABNORMAL, "INJ_DEV_FAULT"),
        (FaultMode.ABNORMAL_VIBRATION, "VIB_HIGH"),
        (FaultMode.MISFIRE, "MISFIRE"),
    ],
)
def test_injected_fault_raises_its_alert(fault_mode, expect_rule):
    """Each injected fault must surface as an operator-visible alert."""
    _eng, seen = _fly(
        InjectedFault(mode=fault_mode, onset_hours=0.03, severity=0.9, ramp_hours=0.06),
        channel=fault_mode.value,
    )
    assert expect_rule in seen, f"{fault_mode.value} produced {list(seen)}"


def test_injection_timing_deviation_finally_raises_an_alert():
    """The gap that started this work.

    Injection timing was modelled, transmitted and decoded, and its deviation
    was computed -- but nothing compared it against a limit, so no operator was
    ever told. This test is the proof that the loop is closed.
    """
    eng, seen = _fly(
        InjectedFault(
            mode=FaultMode.INJECTOR_ABNORMAL, onset_hours=0.04,
            severity=0.9, ramp_hours=0.08,
        ),
        channel="injdev",
    )
    assert "INJ_DEV_DEGRADED" in seen
    assert "INJ_DEV_FAULT" in seen
    # And it must escalate: degraded before fault, not simultaneously.
    assert seen["INJ_DEV_DEGRADED"] < seen["INJ_DEV_FAULT"]
    assert eng.active_fault_modes().get("injector_abnormal") == AlertLevel.ORANGE


def test_fault_modes_are_reported_for_the_fusion_layer():
    """Tier 1 contributes to the fault vector Tiers 2 and 3 will fuse."""
    eng, _ = _fly(
        InjectedFault(
            mode=FaultMode.ABNORMAL_VIBRATION, onset_hours=0.03,
            severity=0.9, ramp_hours=0.06,
        ),
        channel="fm",
    )
    modes = eng.active_fault_modes()
    assert "abnormal_vibration" in modes
    assert modes["abnormal_vibration"] >= AlertLevel.ORANGE


def test_master_annunciators_reset_independently_and_rearm():
    """MIL-STD-411F 5.1.3.5, 5.1.4.5 and 4.1.3.8.

    Reset must extinguish the MASTER annunciator while leaving the individual
    alert displayed, and the system must re-arm so a later event lights it
    again. A reset that clears the alert, or that latches off permanently, is
    a safety defect.
    """
    from layer1_edge.can_ingest import Channel, Telemetry, ValueState

    eng = RuleEngine()
    tel = Telemetry(t_s=0.0)

    def put(name, value, t):
        tel.channels[name] = Channel(
            name=name, value=value, state=ValueState.VALID, updated_t=t, age_s=0.0
        )
        tel.t_s = t

    # Drive oil pressure below its critical limit at speed.
    for t in (0.0, 30.0, 60.0):
        put("rpm", 5000.0, t)
        put("oil_pressure", 5.0, t)
        put("oil_temperature", 95.0, t)
        put("throttle_pct", 80.0, t)
        state = eng.evaluate(tel)

    assert state.master_warning is True
    warnings = state.by_category(AlertCategory.WARNING)
    assert warnings, "a warning-level alert should be active"

    eng.reset_master_warning(now=60.0)
    put("rpm", 5000.0, 61.0)
    put("oil_pressure", 5.0, 61.0)
    state = eng.evaluate(tel)
    assert state.master_warning is False, "reset must extinguish the master annunciator"
    assert state.by_category(AlertCategory.WARNING), "the individual alert must remain"


def test_minimum_display_time_is_honoured():
    """MIL-STD-411F 5.2.5.5: a warning or caution must be visible for at least
    three seconds even if the condition clears immediately."""
    from layer1_edge.can_ingest import Channel, Telemetry, ValueState

    eng = RuleEngine()
    tel = Telemetry(t_s=0.0)

    def put(name, value, t):
        tel.channels[name] = Channel(
            name=name, value=value, state=ValueState.VALID, updated_t=t, age_s=0.0
        )
        tel.t_s = t

    # Warm up so the start inhibit lifts, with the engine healthy.
    for t in (0.0, 15.0, 30.0):
        put("rpm", 5000.0, t)
        put("oil_pressure", 55.0, t)
        put("throttle_pct", 80.0, t)
        eng.evaluate(tel)
    assert not eng.state.by_category(AlertCategory.WARNING)

    # A BRIEF excursion: the condition appears and is gone half a second later.
    # This is precisely the case 411F 5.2.5.5 exists for -- without a minimum
    # display time the crew would never see it.
    put("oil_pressure", 5.0, 31.0)
    state = eng.evaluate(tel)
    assert state.by_category(AlertCategory.WARNING), "the excursion must raise a warning"

    put("oil_pressure", 55.0, 31.5)
    state = eng.evaluate(tel)
    assert state.by_category(AlertCategory.WARNING), "must persist for 3 s after clearing"

    put("oil_pressure", 55.0, 34.5)
    state = eng.evaluate(tel)
    assert not state.by_category(AlertCategory.WARNING), "must clear once 3 s has elapsed"


def test_alerts_are_ordered_warning_then_caution():
    """MIL-STD-411F 5.2.5.2: warnings at the top of the annunciator area."""
    order = {AlertCategory.WARNING: 0, AlertCategory.CAUTION: 1, AlertCategory.ADVISORY: 2}
    _eng, _ = _fly(
        InjectedFault(
            mode=FaultMode.ABNORMAL_VIBRATION, onset_hours=0.03,
            severity=0.95, ramp_hours=0.05,
        ),
        channel="order",
    )
    eng2, _ = _fly(
        InjectedFault(
            mode=FaultMode.ABNORMAL_VIBRATION, onset_hours=0.03,
            severity=0.95, ramp_hours=0.05,
        ),
        channel="order2",
    )
    ranks = [order[a.category] for a in eng2.state.active]
    assert ranks == sorted(ranks), "alerts must be ordered by urgency category"


def test_inhibits_are_reported_when_active():
    """PRD Part 4 section 4.5: an inhibit the operator cannot see is a defect."""
    from layer1_edge.can_ingest import Channel, Telemetry, ValueState

    eng = RuleEngine()
    tel = Telemetry(t_s=1.0, flight_phase=0)  # on ground
    for name, value in (("rpm", 1000.0), ("oil_temperature", 20.0), ("throttle_pct", 10.0)):
        tel.channels[name] = Channel(
            name=name, value=value, state=ValueState.VALID, updated_t=1.0, age_s=0.0
        )
    state = eng.evaluate(tel)
    assert state.inhibits_active is True


# ---------------------------------------------------------------------------
# Sensor fusion
# ---------------------------------------------------------------------------


def test_hampel_filter_rejects_a_spike_but_keeps_a_step():
    """The property a moving average does not have.

    A single outlier must be removed; a genuine step change must survive,
    because a step is the engine doing something real.
    """
    f = HampelFilter(window=7, n_sigma=3.0)
    for _ in range(7):
        f.filter(50.0)
    cleaned, rejected = f.filter(500.0)
    assert rejected is True
    assert cleaned == pytest.approx(50.0)

    g = HampelFilter(window=7, n_sigma=3.0)
    for _ in range(7):
        g.filter(50.0)
    # A sustained step: after enough samples the filter must follow it.
    last = None
    for _ in range(10):
        last, _ = g.filter(80.0)
    assert last == pytest.approx(80.0, abs=1e-6)


def test_bias_estimator_tracks_a_slow_drift_without_chasing_noise():
    est = BiasEstimator(process_noise=1e-5, measurement_noise=1e-2)
    for _ in range(500):
        est.update(measured=10.4, reference=10.0)
    assert est.bias == pytest.approx(0.4, abs=0.05)
    assert est.compensate(10.4) == pytest.approx(10.0, abs=0.05)


def test_bias_estimator_flags_drift_beyond_two_percent_of_full_scale():
    """PRD Part 1 section 8.4."""
    est = BiasEstimator(process_noise=1e-4, measurement_noise=1e-2)
    for _ in range(600):
        est.update(measured=106.0, reference=100.0)
    assert est.drifting(full_scale=100.0, fraction=0.02) is True


def test_rolling_correlation_detects_a_broken_relationship():
    """Oil pressure follows rpm on a healthy engine (PRD Part 2 section 10.4)."""
    good = RollingCorrelation(window_s=60.0)
    r = None
    for i in range(60):
        t = i * 0.5
        rpm = 2000.0 + 40.0 * i
        r = good.update(t, rpm, 20.0 + 0.008 * rpm)
    assert r is not None and r > 0.95

    broken = RollingCorrelation(window_s=60.0)
    r2 = None
    for i in range(60):
        t = i * 0.5
        rpm = 2000.0 + 40.0 * i
        r2 = broken.update(t, rpm, 40.0 + (3.0 if i % 2 else -3.0))
    assert r2 is not None and abs(r2) < 0.5


def test_lane_vote_marks_both_sources_suspect_on_disagreement():
    """With only two sources there is no majority, so neither can be trusted."""
    vote = LaneVote(tolerance_fraction=0.05)
    value, suspect = vote.fuse(100.0, 101.0)
    assert suspect is False and value == pytest.approx(100.5)

    value, suspect = vote.fuse(100.0, 130.0)
    assert suspect is True
    assert vote.disagreements == 1

    assert vote.fuse(None, 42.0) == (42.0, False)
    assert vote.fuse(None, None) == (None, False)


def test_fusion_conditions_a_live_stream():
    sim = CanSimulator(interface="virtual", channel="tt_fuse")
    ing = CanIngest(interface="virtual", channel="tt_fuse")
    fusion = SensorFusion()
    v = VirtualEngine(seed=4)
    features: dict[str, float] = {}
    try:
        for frame in run_profile(v, dt=0.5, max_seconds=200.0):
            sim.send_frame(frame)
            tel = ing.poll(now=frame.t_s)
            for name in ("rpm", "oil_pressure", "cht_max"):
                fusion.condition(name, tel.get(name))
            features = fusion.update_features(frame.t_s, tel)
    finally:
        sim.close()
        ing.close()
    assert "oil_rpm_correlation" in features


# ---------------------------------------------------------------------------
# Offline buffer
# ---------------------------------------------------------------------------


def test_buffer_holds_the_required_seventy_two_hours(tmp_path):
    """PRD Part 3 section 21.4 and PRD Part 1 section 7.4."""
    buf = EdgeBuffer(tmp_path / "b.sqlite")
    try:
        assert buf.capacity_hours >= 72.0
        expected = int(72.0 * 3600.0 * buf.sample_hz)
        assert buf.max_rows >= expected
    finally:
        buf.close()


def test_buffer_evicts_oldest_when_full(tmp_path):
    """Losing the start of an outage beats losing the moments before a failure."""
    buf = EdgeBuffer(tmp_path / "b.sqlite", capacity_hours=0.001, sample_hz=10.0)
    try:
        for i in range(120):
            buf.record(float(i), {"rpm": 5000 + i})
        buf.commit()
        assert buf.stats.rows <= buf.max_rows
        assert buf.stats.dropped_oldest > 0
        newest = buf.drain(batch=1000)[-1]
        assert newest[1] == 119.0, "the newest sample must always survive"
    finally:
        buf.close()


def test_buffer_uploads_oldest_first_and_reports_the_backfill_span(tmp_path):
    """PRD Part 4 section 7.3c: the operator must be told what was replayed."""
    buf = EdgeBuffer(tmp_path / "b.sqlite")
    try:
        for i in range(50):
            buf.record(float(i), {"rpm": 4000 + i})
        buf.commit()
        assert buf.pending() == 50
        span = buf.backfill_span()
        assert span == (0.0, 49.0)

        batch = buf.drain(batch=10)
        assert [t for _, t, _ in batch] == [float(i) for i in range(10)]
        buf.mark_uploaded([i for i, _, _ in batch])
        assert buf.pending() == 40
    finally:
        buf.close()


def test_link_state_transitions_through_degraded_lost_and_syncing(tmp_path):
    buf = EdgeBuffer(tmp_path / "b.sqlite")
    try:
        assert buf.note_link(True, now=0.0) is LinkState.OK
        assert buf.note_link(False, now=1.0) is LinkState.OK
        assert buf.note_link(False, now=3.0) is LinkState.DEGRADED
        assert buf.note_link(False, now=10.0) is LinkState.LOST

        buf.record(1.0, {"rpm": 5000})
        buf.commit()
        assert buf.note_link(True, now=11.0) is LinkState.SYNCING

        rows = buf.drain()
        buf.mark_uploaded([r[0] for r in rows])
        assert buf.link is LinkState.OK
    finally:
        buf.close()


def test_alerts_are_recorded_with_the_time_the_condition_began(tmp_path):
    """MIL-STD-411F 5.2.10 maintenance record.

    When a fault started is what the technician needs; when the link happened
    to come back is irrelevant.
    """
    buf = EdgeBuffer(tmp_path / "b.sqlite")
    try:
        buf.record_alert(120.5, "OILP_CRIT", "OIL PRESS LOW", 5, "WARNING", 8.2)
        buf.record_alert(300.0, "CHT_HIGH", "CHT HIGH", 4, "CAUTION", 131.0)
        buf.commit()
        log = buf.maintenance_log()
        assert len(log) == 2
        assert log[-1]["t_s"] == 120.5
        assert log[-1]["legend"] == "OIL PRESS LOW"
    finally:
        buf.close()


def test_capacity_report_projects_the_storage_requirement(tmp_path):
    buf = EdgeBuffer(tmp_path / "b.sqlite")
    try:
        for i in range(200):
            buf.record(float(i), {"rpm": 5000, "cht": 105.2, "egt": 812.4})
        buf.commit()
        report = buf.capacity_report()
        assert report["rows"] == 200
        assert report["bytes_per_row"] > 0
        assert report["projected_full_mb"] > 0
        assert report["link"] == "OK"
    finally:
        buf.close()


# ---------------------------------------------------------------------------
# Review fixes: a lost reading is not a cleared condition (SAF-08, CAN-12)
# ---------------------------------------------------------------------------


class _Tel:
    """Just enough of Telemetry for a single rule: a clock and readings."""

    def __init__(self, t_s: float, **values):
        self.t_s = t_s
        self._v = values

    def get(self, name):
        return self._v.get(name)


def test_a_latched_limit_holds_when_its_reading_is_lost():
    """Oil pressure LOW used to clear the moment the sensor went quiet, and the
    only alert left was a caution-level sensor fault."""
    from layer1_edge.edge_rules import AlertLevel, ThresholdRule

    rule = ThresholdRule(rule_id="OILP_T", parameter="oil_pressure",
                         level=AlertLevel.RED, legend="OIL PRESS LOW",
                         limit=29.0, direction="below", hysteresis=2.0)
    assert rule.evaluate(_Tel(0.0, oil_pressure=20.0), {})[0]
    assert rule.evaluate(_Tel(0.5), {})[0], "losing the reading cleared the warning"
    assert rule.evaluate(_Tel(1.0, oil_pressure=30.0), {})[0], "inside hysteresis must hold"
    assert not rule.evaluate(_Tel(1.5, oil_pressure=32.0), {})[0]


def test_a_single_dropout_does_not_restart_a_persistence_clock():
    from layer1_edge.edge_rules import AlertLevel, PersistenceRule

    rule = PersistenceRule(rule_id="CHT_P", parameter="cht", level=AlertLevel.ORANGE,
                           legend="CHT HIGH", limit=120.0, direction="above",
                           duration_s=10.0)
    for t in range(8):
        rule.evaluate(_Tel(float(t), cht=125.0), {})
    rule.evaluate(_Tel(8.0), {})
    assert rule.evaluate(_Tel(10.5, cht=125.0), {})[0]
