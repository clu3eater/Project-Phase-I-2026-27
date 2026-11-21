"""The squadron's rules, without an engine: who may do what, and when.

Each test walks a piece of the chain a real flight line follows -- release,
allotment, pre-flight, start, launch, recall, shutdown, debrief, defect,
disposition, rectification -- and checks the step that must be refused is.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from layer4_core import ops


@pytest.fixture
def store(tmp_path):
    return ops.OpsStore(tmp_path / "squadron.db")


def snap(chi=0.97, actions=(), hsi=10.0, hours=50.0, tbo_left=1100.0):
    subs = {"thermal": chi, "mechanical": chi, "combustion": chi, "electrical": chi}
    return SimpleNamespace(
        health={"chi": chi, "band": "EXCELLENT", **subs},
        twin={"metadata": {"total_flight_hours": hours, "tbo_hours": 1200.0},
              "history": {"hours_since_inspection": hsi}},
        mission={"inputs": {"chi": chi, "subsystems": subs, "rul_hours": 900.0,
                            "rul_lower_hours": 800.0, "rul_confidence": 0.8,
                            "active_alerts": 0, "highest_alert_level": 1,
                            "grounded": False, "grounding_reason": None,
                            "tbo_remaining_hours": tbo_left}},
        maintenance={"actions": list(actions)},
        rul={"hours": 900.0},
    )


CHECKS = None


def _all_checked(store):
    return {item: True for item in store.checklist()}


def _released(store, tail="MALE-01"):
    store.update_health(tail, snap(), force_flush=True)
    store.release(tail, by="mt.iyer", role="ROLE_MAINTENANCE", note="BFI")


def test_a_new_squadron_is_awaiting_inspection_until_released(store):
    board = {a["tail"]: a for a in store.fleet_board()}
    assert set(board) == {"MALE-01", "MALE-02", "MALE-03", "TAPAS-01"}
    assert all(a["status"] == ops.AWAITING_INSPECTION for a in board.values())
    _released(store)
    assert store.aircraft("MALE-01")["status"] == ops.SERVICEABLE


def test_commander_allots_only_a_serviceable_aircraft(store):
    m = store.create_mission(by="cdr", name="North ridge", mtype="ISR_PATROL",
                             environment=None, duration_h=None, altitude_ft=None)
    assert m["status"] == ops.PLANNED and m["duration_h"] == 10
    with pytest.raises(ops.OpsError, match="cannot be allotted"):
        store.approve(m["id"], by="cdr", tail="MALE-02", operator="op.rao")
    _released(store)
    cands = store.candidates(m["id"])
    assert cands[0]["tail"] == "MALE-01" and cands[0].get("recommended")
    assert cands[0]["assessment"]["verdict"] == "GO"
    m = store.approve(m["id"], by="cdr", tail="MALE-01", operator="op.rao")
    assert m["status"] == ops.APPROVED and m["tail"] == "MALE-01"
    # the same aircraft cannot be allotted twice
    m2 = store.create_mission(by="cdr", name="Relay", mtype="COMM_RELAY",
                              environment=None, duration_h=None, altitude_ft=None)
    with pytest.raises(ops.OpsError, match="already allotted"):
        store.approve(m2["id"], by="cdr", tail="MALE-01", operator="op.rao")


def test_the_full_sortie_chain(store):
    _released(store)
    m = store.create_mission(by="cdr", name="Coast", mtype="MARITIME",
                             environment=None, duration_h=None, altitude_ft=None)
    store.approve(m["id"], by="cdr", tail="MALE-01", operator="op.rao")
    mid = m["id"]
    # another operator may not fly it
    with pytest.raises(ops.OpsError) as e:
        store.prepare(mid, by="op.other", role="ROLE_OPERATOR")
    assert e.value.status == 403
    store.prepare(mid, by="op.rao", role="ROLE_OPERATOR")
    assert store.busy()["id"] == mid
    assert store.aircraft("MALE-01")["status"] == ops.ON_GCS
    # the station is busy: no ground run on another aircraft meanwhile
    with pytest.raises(ops.OpsError, match="busy"):
        store.begin_ground_run("MALE-02", by="mt", role="ROLE_MAINTENANCE")
    with pytest.raises(ops.OpsError, match="checklist incomplete"):
        store.start(mid, by="op.rao", role="ROLE_OPERATOR", checklist={})
    store.start(mid, by="op.rao", role="ROLE_OPERATOR", checklist=_all_checked(store))
    with pytest.raises(ops.OpsError):
        store.rtb(mid, by="op.rao", role="ROLE_OPERATOR")    # not airborne yet
    store.launch(mid, by="op.rao", role="ROLE_OPERATOR")
    assert store.aircraft("MALE-01")["status"] == ops.FLYING
    store.rtb(mid, by="op.rao", role="ROLE_OPERATOR")

    warn = {"action_id": "A2", "name": "Cooling System Flush", "severity": "WARNING",
            "reason": "cooling efficiency 0.62", "due_within_hours": 0}
    ended = store.engine_stopped(snap(chi=0.78, actions=[warn]), flight_hours=0.42)
    assert ended["mission_id"] == mid and len(ended["raised"]) == 1
    assert store.busy() is None
    a = store.aircraft("MALE-01")
    assert a["status"] == ops.UNSERVICEABLE           # the twin's WARNING grounds it
    assert store.mission(mid)["status"] == ops.AWAITING_DEBRIEF

    done = store.debrief(mid, by="op.rao", role="ROLE_OPERATOR", outcome="PARTIAL",
                         remarks="recalled early",
                         snags=[{"description": "datalink dropouts over the sea",
                                 "severity": "ADVISORY", "grounding": False}])
    assert done["status"] == ops.COMPLETED and len(done["debrief"]["snags"]) == 1

    # engineer defers the twin defect; maintainer can then release
    twin_def = next(d for d in a["open_defects"] if d["source"] == "TWIN")
    with pytest.raises(ops.OpsError, match="must say why"):
        store.dispose_defect(twin_def["id"], by="eng", role="ROLE_ENGINEER",
                             disposition="DEFER", note="", defer_hours=5)
    store.dispose_defect(twin_def["id"], by="eng", role="ROLE_ENGINEER",
                         disposition="DEFER", note="fly to next check", defer_hours=5)
    assert store.aircraft("MALE-01")["status"] == ops.AWAITING_INSPECTION
    store.release("MALE-01", by="mt", role="ROLE_MAINTENANCE", note="AFI")
    assert store.aircraft("MALE-01")["status"] == ops.SERVICEABLE


def test_a_repeat_twin_advisory_does_not_duplicate_the_defect(store):
    _released(store)
    store.begin_ground_run("MALE-01", by="mt", role="ROLE_MAINTENANCE")
    caut = {"action_id": "A3", "name": "Injector", "severity": "CAUTION", "reason": "spread"}
    store.engine_stopped(snap(actions=[caut]), flight_hours=0.1)
    store.begin_ground_run("MALE-01", by="mt", role="ROLE_MAINTENANCE")
    store.engine_stopped(snap(actions=[caut]), flight_hours=0.1)
    assert len(store.defects("MALE-01", open_only=True)) == 1
    # a CAUTION does not ground
    assert not store.aircraft("MALE-01")["grounding"]


def test_inspection_due_grounds_until_the_100h_check(store):
    store.update_health("MALE-02", snap(hsi=101.0), force_flush=True)
    a = store.aircraft("MALE-02")
    assert a["status"] == ops.UNSERVICEABLE and "inspection due" in a["grounding"][0]
    with pytest.raises(ops.OpsError, match="cannot be released"):
        store.release("MALE-02", by="mt", role="ROLE_MAINTENANCE")
    store.queue_maintenance("MALE-02", "A1", by="mt", role="ROLE_MAINTENANCE",
                            repaired=None, note="100 h check")
    assert store.aircraft("MALE-02")["pending_maintenance"][0]["action_id"] == "A1"
    store.release("MALE-02", by="mt", role="ROLE_MAINTENANCE")
    assert store.aircraft("MALE-02")["status"] == ops.SERVICEABLE
    assert [p["action_id"] for p in store.take_pending_maintenance("MALE-02")] == ["A1"]
    assert store.take_pending_maintenance("MALE-02") == []


def test_limitations_keep_an_aircraft_off_missions_it_may_not_fly(store):
    _released(store)
    store.set_limitations("MALE-01", by="eng", role="ROLE_ENGINEER",
                          max_mission_hours=6, max_altitude_ft=None, note="bearing watch")
    m = store.create_mission(by="cdr", name="Long", mtype="COMM_RELAY",
                             environment=None, duration_h=None, altitude_ft=None)
    c = {r["tail"]: r for r in store.candidates(m["id"])}["MALE-01"]
    assert not c["eligible"] and any("6 h" in p for p in c["problems"])


def test_each_role_sees_its_own_work(store):
    _released(store)
    m = store.create_mission(by="cdr", name="Recce", mtype="TRAINING",
                             environment=None, duration_h=None, altitude_ft=None)
    assert any("Allot" in t["text"] for t in store.tasks(role="ROLE_COMMANDER", user="cdr"))
    store.approve(m["id"], by="cdr", tail="MALE-01", operator="op.rao")
    op = store.tasks(role="ROLE_OPERATOR", user="op.rao")
    assert op and m["id"] in op[0]["text"]
    assert store.tasks(role="ROLE_OPERATOR", user="someone.else") == []
    mt = store.tasks(role="ROLE_MAINTENANCE", user="mt")
    assert any("MALE-02" in t["text"] and "release" in t["text"] for t in mt)
    store.begin_ground_run("MALE-03", by="mt", role="ROLE_MAINTENANCE")
    warn = {"action_id": "A2", "name": "Cooling", "severity": "WARNING", "reason": "x"}
    store.engine_stopped(snap(chi=0.7, actions=[warn]), flight_hours=0.1)
    eng = store.tasks(role="ROLE_ENGINEER", user="eng")
    assert any("review twin defect" in t["text"] for t in eng)
    assert any("engine health 70" in t["text"] for t in eng)


def test_cancel_frees_the_station_and_is_refused_once_started(store):
    _released(store)
    m = store.create_mission(by="cdr", name="X", mtype="TRANSIT",
                             environment=None, duration_h=None, altitude_ft=None)
    store.approve(m["id"], by="cdr", tail="MALE-01", operator="op.rao")
    store.prepare(m["id"], by="op.rao", role="ROLE_OPERATOR")
    store.start(m["id"], by="op.rao", role="ROLE_OPERATOR", checklist=_all_checked(store))
    with pytest.raises(ops.OpsError, match="can no longer be cancelled"):
        store.cancel(m["id"], by="cdr", reason="weather")


def test_an_allotted_aircraft_that_is_grounded_can_be_re_allotted(store):
    _released(store, "MALE-01")
    _released(store, "MALE-02")
    m = store.create_mission(by="cdr", name="Y", mtype="TRANSIT",
                             environment=None, duration_h=None, altitude_ft=None)
    store.approve(m["id"], by="cdr", tail="MALE-01", operator="op.rao")
    store.ground("MALE-01", by="mt", role="ROLE_MAINTENANCE", reason="oil leak at the sump")
    assert any("re-allot" in t["text"] for t in store.tasks(role="ROLE_COMMANDER", user="cdr"))
    with pytest.raises(ops.OpsError, match="no longer serviceable"):
        store.prepare(m["id"], by="op.rao", role="ROLE_OPERATOR")
    again = store.approve(m["id"], by="cdr", tail="MALE-02", operator="op.rao")
    assert again["tail"] == "MALE-02" and again["status"] == ops.APPROVED
