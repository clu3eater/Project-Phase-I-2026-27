"""FADEC lanes: each lane's own reading, its failures, and the ECU's own report.

The Rotax 915 iS has a dual-lane engine management system. Crankshaft position,
manifold pressure and manifold air temperature are measured by a sensor on EACH
lane; oil pressure and oil temperature by lane B only; coolant temperature by
lane A only [IM Rev.5 failure matrix, configs/engines/rotax_915is.yaml].

Audit 15 Sep (P0): lane B sent a copy of lane A's number, the receiver merged
the lanes into one value that the last frame overwrote, a lane's last reading
was compared for ever after it went quiet, and the ECU's lane health, warning
lamps and error flags were never used.
"""

from __future__ import annotations

import numpy as np
import pytest

from common import config
from common.fadec import dual_lane_channels
from layer1_edge.can_ingest import CanIngest, Telemetry, ValueState
from layer1_edge.can_simulator import NODE_ECU_A, NODE_ECU_B, CanSimulator
from layer1_edge.edge_rules import RuleEngine
from layer1_edge.mavlink_efi import EfiStatusSource
from layer2_physics.engine_sim import VirtualEngine, run_profile


@pytest.fixture
def link(request):
    channel = f"fadec_{request.node.name}"
    sim = CanSimulator(interface="virtual", channel=channel)
    ing = CanIngest(interface="virtual", channel=channel)
    yield sim, ing
    sim.close()
    ing.close()


def _fly(sim, ing, v, seconds, *, fail=None, fail_at=0.0, rules=None):
    """Fly a profile over the bus; return (telemetry, rule ids before, after the failure)."""
    before: set[str] = set()
    after: set[str] = set()
    t = None
    for f in run_profile(v, dt=0.5, max_seconds=seconds):
        sim.send_frame(f)
        t = ing.poll(now=f.t_s)
        if rules is not None:
            ids = {a.rule_id for a in rules.evaluate(t, ing.derived()).active}
            (after if v.lane_failures else before).update(ids)
        if fail and f.t_s >= fail_at and not v.lane_failures:
            v.fail_lane_item(*fail)  # takes effect from the next frame
    return t, before, after


# ---------------------------------------------------------------------------
# The lanes are two measurements
# ---------------------------------------------------------------------------


def test_the_dual_lane_channels_are_the_sensors_the_manufacturer_fits_to_both_lanes():
    assert dual_lane_channels(config.load_engine("rotax_915is")) == {
        "rpm", "manifold_pressure", "manifold_air_temperature"}


def test_lane_b_is_its_own_measurement_not_a_copy_of_lane_a():
    d = np.array([
        (f.rpm - f.rpm_lane_b,
         f.manifold_pressure_bar - f.manifold_pressure_bar_lane_b,
         f.manifold_air_temp_c - f.manifold_air_temp_c_lane_b)
        for f in run_profile(VirtualEngine(seed=5), dt=0.5, max_seconds=120.0)
    ])
    assert (d != 0.0).mean(axis=0).min() > 0.5, "lane B repeats lane A"
    # Two instruments of one type on one quantity differ by noise, not by a bias.
    assert abs(d[:, 0].mean()) < 2.0 and np.abs(d[:, 0]).max() < 50.0


def test_lane_b_noise_leaves_every_lane_a_reading_unchanged():
    """Lane B draws from its own random stream, so adding it moved no existing reading."""
    a, b = VirtualEngine(seed=7), VirtualEngine(seed=7)
    b.rng_lane_b = np.random.default_rng(12345)
    lane_b_differs = False
    for fa, fb in zip(run_profile(a, dt=0.5, max_seconds=60.0),
                      run_profile(b, dt=0.5, max_seconds=60.0), strict=True):
        assert (fa.rpm, fa.manifold_pressure_bar, fa.oil_pressure_bar, fa.cht_c) == (
            fb.rpm, fb.manifold_pressure_bar, fb.oil_pressure_bar, fb.cht_c)
        lane_b_differs |= fa.rpm_lane_b != fb.rpm_lane_b
    assert lane_b_differs


def test_both_lanes_arrive_separately_and_are_voted(link):
    sim, ing = link
    v = VirtualEngine(seed=5)
    last = None
    for last in run_profile(v, dt=0.5, max_seconds=60.0):
        sim.send_frame(last)
        t = ing.poll(now=last.t_s)
    ch = t.channels["rpm"]
    assert ch.state is ValueState.VALID and not ch.redundancy_lost
    assert ch.lanes["A"].value == pytest.approx(last.rpm, abs=1.0)
    assert ch.lanes["B"].value == pytest.approx(last.rpm_lane_b, abs=1.0)
    assert ch.value == pytest.approx(0.5 * (ch.lanes["A"].value + ch.lanes["B"].value))
    for name in ("manifold_pressure", "manifold_air_temperature"):
        assert set(t.channels[name].lanes) == {"A", "B"}, name
    assert set(t.channels["oil_pressure"].lanes) == {"B"}
    assert set(t.channels["coolant_temperature"].lanes) == {"A"}
    assert "fuel_flow" in t.channels and not t.channels["fuel_flow"].lanes  # HUMS, no lane
    assert t.ecu is not None and t.ecu.active_lane == 3 and t.ecu_error_flags is not None


# ---------------------------------------------------------------------------
# One lane's trouble is that lane's
# ---------------------------------------------------------------------------


def test_one_lane_declaring_its_data_bad_leaves_the_other_lanes_reading(link):
    sim, ing = link
    f = next(iter(run_profile(VirtualEngine(seed=10), dt=0.5, max_seconds=5.0)))
    sim.send_frame(f)
    ing.poll(now=f.t_s)
    sim._send_float("ECSA_ENGINE_SPEED", "ENGINE_SPEED", 5000.0, NODE_ECU_A, service=2)
    ch = ing.poll(now=f.t_s + 0.1).channels["rpm"]
    assert ch.lanes["A"].state is ValueState.INVALID and "service code" in ch.lanes["A"].reason
    assert ch.state is ValueState.VALID and ch.value == pytest.approx(f.rpm_lane_b, abs=1.0)
    assert ch.redundancy_lost and "lane A unavailable" in ch.reason


def test_lanes_that_disagree_make_the_value_suspect(link):
    sim, ing = link
    sim._send_float("ECSA_ENGINE_SPEED", "ENGINE_SPEED", 4000.0, NODE_ECU_A)
    sim._send_float("ECSB_ENGINE_SPEED", "ENGINE_SPEED", 4600.0, NODE_ECU_B)
    ch = ing.poll(now=0.0).channels["rpm"]
    assert ch.state is ValueState.SUSPECT and "disagree" in ch.reason
    assert (ch.lane_a, ch.lane_b) == (4000.0, 4600.0)


def test_a_temperature_near_zero_is_not_suspect_for_ordinary_sensor_noise():
    """5 % of 0.5 degC is 0.025 degC; two healthy sensors differ by more than that."""
    from layer1_edge.can_ingest import Channel, LaneReading

    ing = CanIngest.__new__(CanIngest)
    ing.stale_after_intervals, ing.telemetry_hz = 3, 10.0
    thr = config.load_thresholds()["pipeline"]
    from layer1_edge.sensor_fusion import LaneVote

    ing.lane_vote = LaneVote(tolerance_fraction=float(thr["lane_agreement_fraction"]))
    ing.lane_floor = {k: float(v) for k, v in thr["lane_agreement_floor"].items()}
    ing.dual_lane = dual_lane_channels(config.load_engine("rotax_915is"))
    ch = Channel(name="manifold_air_temperature", lanes={
        "A": LaneReading(0.5, ValueState.VALID, 0.0), "B": LaneReading(1.4, ValueState.VALID, 0.0)})
    ing._resolve(ch, 0.0)
    assert ch.state is ValueState.VALID
    ch.lanes["B"] = LaneReading(5.0, ValueState.VALID, 0.0)
    ing._resolve(ch, 0.0)
    assert ch.state is ValueState.SUSPECT


def test_a_quiet_lane_leaves_the_vote_instead_of_being_compared_by_its_last_value(link):
    sim, ing = link
    sim._send_float("ECSA_ENGINE_SPEED", "ENGINE_SPEED", 4000.0, NODE_ECU_A)
    sim._send_float("ECSB_ENGINE_SPEED", "ENGINE_SPEED", 4000.0, NODE_ECU_B)
    ing.poll(now=0.0)
    for k in range(1, 11):  # lane A climbs 300 rpm/s; lane B has gone quiet
        sim._send_float("ECSA_ENGINE_SPEED", "ENGINE_SPEED", 4000.0 + 30.0 * k, NODE_ECU_A)
        t = ing.poll(now=0.1 * k)
    ch = t.channels["rpm"]
    assert ch.state is ValueState.VALID and ch.value == pytest.approx(4300.0)
    assert ch.redundancy_lost and "lane B unavailable: no update" in ch.reason


# ---------------------------------------------------------------------------
# Lane failures, from the manufacturer's failure matrix
# ---------------------------------------------------------------------------


def test_a_lane_b_crank_sensor_failure_is_seen_in_the_data_and_in_the_ecu_report(link):
    sim, ing = link
    v = VirtualEngine(seed=11)
    t, before, after = _fly(sim, ing, v, 420.0, fail=("CPS", "B"), fail_at=300.0,
                            rules=RuleEngine())
    ch = t.channels["rpm"]
    assert ch.state is ValueState.VALID and ch.redundancy_lost and "lane B" in ch.reason
    # Failure matrix, CPS lane B: lamp B ON, mode Auto_A.
    assert (t.ecu.active_lane, t.ecu.lane_b_health, t.ecu.warn_lamp_b) == (1, 0, 1)
    assert t.ecu_error_flags & (1 << 9) and t.ecu_error_flags & 1
    assert before == set(), before
    assert {"ECU_LANE_B", "SENSOR_REDUNDANCY"} <= after
    assert not after & {"ECU_LANE_A", "ECU_SENSOR_B", "SENSOR_FAULT"}


def test_a_lane_b_oil_pressure_sensor_failure_flashes_lamp_b_with_both_lanes_in_control(link):
    sim, ing = link
    v = VirtualEngine(seed=11)
    t, before, after = _fly(sim, ing, v, 420.0, fail=("OPS", "B"), fail_at=300.0,
                            rules=RuleEngine())
    # Failure matrix, OPS lane B: lamp B FLASHING, mode Auto_AB.
    assert (t.ecu.active_lane, t.ecu.warn_lamp_b, t.ecu.lane_b_health) == (3, 2, 1)
    assert t.ecu_error_flags & 1 and not t.ecu_error_flags & (1 << 9)
    assert t.state("oil_pressure") is ValueState.STALE
    assert before == set(), before
    assert "ECU_SENSOR_B" in after and "ECU_LANE_B" not in after


def test_losing_lane_b_power_silences_its_node_and_its_own_sensors_go_stale(link):
    sim, ing = link
    v = VirtualEngine(seed=11)
    t, _, _ = _fly(sim, ing, v, 60.0, fail=("ECU_POWER", "B"), fail_at=40.0)
    assert sim.frames_lane_silent > 0
    assert t.state("oil_pressure") is ValueState.STALE      # lane B only
    assert t.state("oil_temperature") is ValueState.STALE
    assert t.state("coolant_temperature") is ValueState.VALID  # lane A only
    assert t.state("rpm") is ValueState.VALID and t.channels["rpm"].redundancy_lost
    assert (t.ecu.active_lane, t.ecu.warn_lamp_b) == (1, 1)


@pytest.mark.parametrize("item, lane", [("MATS", "A"), ("COIL_2_4", "B")])
def test_a_failure_the_simulation_cannot_represent_is_refused(item, lane):
    with pytest.raises(ValueError, match="not simulated"):
        VirtualEngine(seed=1).fail_lane_item(item, lane)


def test_a_failure_the_manufacturer_does_not_list_is_refused():
    with pytest.raises(ValueError, match="failure matrix"):
        VirtualEngine(seed=1).fail_lane_item("OPS", "A")  # OPS is a lane B sensor


# ---------------------------------------------------------------------------
# The ECU's report is used, and never assumed
# ---------------------------------------------------------------------------


def test_an_ecu_that_stops_reporting_is_unknown_not_healthy(link):
    sim, ing = link
    f = next(iter(run_profile(VirtualEngine(seed=5), dt=0.5, max_seconds=5.0)))
    sim.send_frame(f)
    assert ing.poll(now=f.t_s).ecu_error_flags is not None
    t = ing.poll(now=f.t_s + 2.0)
    assert t.ecu.stale and t.ecu_error_flags is None
    assert EfiStatusSource().values(t)["health"] == 0
    assert EfiStatusSource().values(Telemetry())["health"] == 0  # never reported
