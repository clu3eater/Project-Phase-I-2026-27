"""The API behind the roles' own work: maintenance, engines, accounts.

Each role had a login and little it could do with it. These run the real
application, with its live twin, and check that the maintainer can record
any job and see its effect, that an engine can be added and selected with
no code change, and that the commander can manage accounts -- and that each
of those is refused to the roles that do not own it.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from common import config
from layer4_core import security as sec


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("admin_api")
    engines = root / "configs" / "engines"
    engines.mkdir(parents=True)
    real = config.config_dir()
    for f in (real / "engines").iterdir():
        (engines / f.name).write_bytes(f.read_bytes())
    for name in ("thresholds.yaml", "fleet.yaml"):
        (root / "configs" / name).write_bytes((real / name).read_bytes())
    # The CAN database is referenced relative to the repository root.
    saved = {k: os.environ.get(k) for k in (
        "DT_DATA_DIR", "DT_CONFIG_DIR", "DT_ENGINE", "DT_PERSIST", "DT_SPEED",
        "DT_ALLOW_INITIAL_PASSWORDS", "DT_CRUISE_HOURS")}
    os.environ.update({
        "DT_DATA_DIR": str(root / "data"), "DT_CONFIG_DIR": str(root / "configs"),
        "DT_PERSIST": "0", "DT_SPEED": "200", "DT_ALLOW_INITIAL_PASSWORDS": "1",
        "DT_CRUISE_HOURS": "0.01",
    })
    os.environ.pop("DT_ENGINE", None)
    config.clear_cache()
    sec._PRIVATE = sec._PUBLIC = None
    import layer4_core.twin_api as api
    prev_audit = api.AUDIT
    api.AUDIT = sec.AuditLog()
    try:
        yield root
    finally:
        api.AUDIT = prev_audit
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config.clear_cache()
        sec._PRIVATE = sec._PUBLIC = None


@pytest.fixture(scope="module")
def client(env):
    from layer4_core.twin_api import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def creds(env) -> dict[str, tuple[str, str]]:
    sec._users()
    note = config.data_dir() / "keys" / "FIRST_RUN_CREDENTIALS.txt"
    out = {}
    for line in note.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1].startswith("ROLE_"):
            out[parts[1]] = (parts[0], parts[2])
    return out


def _h(client, creds, role):
    user, pw = creds[role]
    r = client.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _wait(pred, timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.2)
    raise AssertionError("timed out")


# --- maintenance -----------------------------------------------------------


def _ground_run(client, headers, tail="MALE-01", timeout=180):
    r = client.post(f"/api/ops/aircraft/{tail}/ground_run", headers=headers)
    assert r.status_code == 200, r.text
    # the station is busy until the engine has been shut down again
    _wait(lambda: client.get("/api/ops/board", headers=headers).json()["busy"] is None,
          timeout=timeout)


@pytest.mark.slow
def test_maintainer_can_record_any_job_and_see_its_before_and_after(client, creds):
    mt = _h(client, creds, "ROLE_MAINTENANCE")
    cat = client.get("/api/maintenance/catalog", headers=mt)
    assert cat.status_code == 200
    ids = [a["action_id"] for a in cat.json()["actions"]]
    assert ids == ["A1", "A2", "A3", "A4", "A5", "A6", "A7"]
    # The engine is parked: nothing to judge until it is run.
    _ground_run(client, mt)
    assert client.get("/api/ops/aircraft/MALE-01", headers=mt).json()["health"].get("chi") \
        is not None

    # An oil change NOT currently recommended can still be signed off...
    r = client.post("/api/maintenance/performed", headers=mt,
                    json={"action_id": "A1", "note": "scheduled 100 h"})
    assert r.status_code == 200, r.text
    # ...and is verified by the next engine run.
    _ground_run(client, mt)
    perf = client.get("/api/maintenance/catalog", headers=mt).json()["performed"]
    rec = next(p for p in reversed(perf) if p["action_id"] == "A1")
    assert rec["note"] == "scheduled 100 h"
    assert "oil_quality" in rec["restored"]
    assert rec["health_before"]["chi"] is not None
    assert set(rec["health_after"]) == {"lhi", "oti", "chi"}
    assert "chi" in rec["health_delta"]


def test_only_maintenance_can_record_work(client, creds):
    op = _h(client, creds, "ROLE_OPERATOR")
    r = client.post("/api/maintenance/performed", headers=op, json={"action_id": "A1"})
    assert r.status_code == 403


# --- engines ---------------------------------------------------------------


def test_every_role_sees_the_engine_catalogue(client, creds):
    op = _h(client, creds, "ROLE_OPERATOR")
    body = client.get("/api/engines", headers=op).json()
    keys = {e["key"] for e in body["engines"]}
    assert {"rotax_915is", "austro_ae330"} <= keys
    assert body["running"] == "rotax_915is"


def test_engineer_adds_an_engine_and_an_incomplete_one_is_refused(client, creds):
    eng = _h(client, creds, "ROLE_ENGINEER")
    bad = client.post("/api/engines", headers=eng, json={
        "engine_key": "half_engine",
        "yaml_text": "schema_version: 1\nidentity: {ignition: SPARK}\n"})
    assert bad.status_code == 422
    assert not (config.config_dir() / "engines" / "half_engine.yaml").exists()

    tmpl = client.get("/api/engines/template", headers=eng).text
    ok = client.post("/api/engines", headers=eng, json={
        "engine_key": "test_engine", "yaml_text": tmpl})
    assert ok.status_code == 200, ok.text[:2000]
    assert "test_engine" in config.available_engines()
    # engineers author engines; fitting one to an aircraft is the commander's
    sel = client.post("/api/ops/aircraft/MALE-02/engine", headers=eng,
                      json={"engine_key": "test_engine"})
    assert sel.status_code == 403


def test_commander_changes_an_aircrafts_engine(client, creds):
    cdr = _h(client, creds, "ROLE_COMMANDER")
    eng = _h(client, creds, "ROLE_ENGINEER")
    assert client.post("/api/ops/aircraft/MALE-02/engine", headers=eng,
                       json={"engine_key": "austro_ae330"}).status_code == 403
    r = client.post("/api/ops/aircraft/MALE-02/engine", headers=cdr,
                    json={"engine_key": "austro_ae330", "note": "trial fit"})
    assert r.status_code == 200, r.text
    assert r.json()["engine_key"] == "austro_ae330"
    assert r.json()["status"] == "AWAITING INSPECTION"
    fitted = client.get("/api/engines", headers=cdr).json()["fitted"]
    assert "MALE-02" in fitted["austro_ae330"]
    r = client.post("/api/ops/aircraft/MALE-02/engine", headers=cdr,
                    json={"engine_key": "rotax_915is"})
    assert r.status_code == 200
    # the station-wide switch is gone: engines belong to aircraft
    assert client.post("/api/engines/select", headers=cdr,
                       json={"engine_key": "austro_ae330"}).status_code in (404, 405)


# --- the squadron chain ------------------------------------------------------


def test_signing_in_does_not_start_the_engine(client, creds):
    _h(client, creds, "ROLE_OPERATOR")
    cdr = _h(client, creds, "ROLE_COMMANDER")
    live = client.get("/api/ops/board", headers=cdr).json()["live"]
    assert live["sortie"]["state"] in ("parked", "complete")
    assert client.post("/api/sortie/start", headers=cdr).status_code == 409


@pytest.mark.slow
def test_tasking_to_debrief_through_the_api(client, creds):
    cdr = _h(client, creds, "ROLE_COMMANDER")
    op = _h(client, creds, "ROLE_OPERATOR")
    mt = _h(client, creds, "ROLE_MAINTENANCE")
    op_user = creds["ROLE_OPERATOR"][0]

    # maintainer signs the release; commander plans and allots
    r = client.post("/api/ops/aircraft/MALE-01/release", headers=mt, json={"note": "BFI"})
    assert r.status_code == 200, r.text
    assert client.post("/api/ops/missions", headers=op,
                       json={"type": "TRAINING"}).status_code == 403
    m = client.post("/api/ops/missions", headers=cdr,
                    json={"type": "TRAINING", "name": "Circuit", "area": "local"}).json()
    cands = client.get(f"/api/ops/missions/{m['id']}/candidates", headers=cdr).json()
    assert any(c["tail"] == "MALE-01" and c["eligible"] for c in cands)
    r = client.post(f"/api/ops/missions/{m['id']}/approve", headers=cdr,
                    json={"tail": "MALE-01", "operator": op_user})
    assert r.status_code == 200, r.text

    # the operator sees it, prepares, and cannot start without the checklist
    board = client.get("/api/ops/board", headers=op).json()
    assert [x["id"] for x in board["missions"]] == [m["id"]]
    assert any(m["id"] in t["text"] for t in board["tasks"])
    assert client.post(f"/api/ops/missions/{m['id']}/prepare", headers=op).status_code == 200
    assert client.post(f"/api/ops/missions/{m['id']}/start", headers=op,
                       json={"checklist": {}}).status_code == 400
    checks = {i: True for i in board["checklist"]}
    r = client.post(f"/api/ops/missions/{m['id']}/start", headers=op, json={"checklist": checks})
    assert r.status_code == 200, r.text
    # launch is refused until the engine is warm and holding
    first = client.post(f"/api/ops/missions/{m['id']}/launch", headers=op)
    assert first.status_code == 409
    _wait(lambda: all(ch["ok"] is not False for ch in client.get("/api/ops/board", headers=op)
                      .json()["live"].get("launch_checks", [{"ok": False}])), timeout=120)
    r = client.post(f"/api/ops/missions/{m['id']}/launch", headers=op)
    assert r.status_code == 200, r.text
    _wait(lambda: client.get("/api/ops/board", headers=op).json()["live"]["sortie"]["phase"]
          in ("CLIMB", "CRUISE"), timeout=120)
    assert client.post(f"/api/ops/missions/{m['id']}/rtb", headers=op).status_code == 200
    _wait(lambda: client.get("/api/ops/board", headers=op).json()["busy"] is None, timeout=240)

    mission = next(x for x in client.get("/api/ops/board", headers=op).json()["missions"]
                   if x["id"] == m["id"])
    assert mission["status"] == "AWAITING_DEBRIEF" and mission["engine_hours"] > 0
    r = client.post(f"/api/ops/missions/{m['id']}/debrief", headers=op,
                    json={"outcome": "PARTIAL", "remarks": "recalled for weather",
                          "snags": [{"description": "camera gimbal drift", "severity": "ADVISORY"}]})
    assert r.status_code == 200, r.text
    ac = client.get("/api/ops/aircraft/MALE-01", headers=mt).json()
    assert ac["status"] == "AWAITING INSPECTION"     # after-flight inspection due
    kinds = [e["kind"] for e in ac["logbook"]]
    for k in ("RELEASE", "MISSION_APPROVED", "ENGINE_START", "LAUNCH", "RTB", "ENGINE_STOP",
              "DEBRIEF"):
        assert k in kinds, k
    assert any(d["description"] == "camera gimbal drift" for d in ac["defects"])


# --- users -----------------------------------------------------------------


def test_commander_manages_accounts_and_nobody_else_can(client, creds):
    cdr = _h(client, creds, "ROLE_COMMANDER")
    mt = _h(client, creds, "ROLE_MAINTENANCE")
    assert client.get("/api/users", headers=mt).status_code == 403

    r = client.post("/api/users", headers=cdr, json={
        "username": "mt.new", "password": "Hangar-Door-2026", "role": "ROLE_MAINTENANCE"})
    assert r.status_code == 200, r.text
    names = {u["username"]: u for u in client.get("/api/users", headers=cdr).json()["users"]}
    assert names["mt.new"]["role"] == "ROLE_MAINTENANCE"
    assert names["mt.new"]["must_change"] is True

    r = client.post("/api/users/mt.new", headers=cdr,
                    json={"role": "ROLE_ENGINEER", "disabled": True})
    assert r.status_code == 200
    names = {u["username"]: u for u in client.get("/api/users", headers=cdr).json()["users"]}
    assert names["mt.new"]["role"] == "ROLE_ENGINEER"
    assert names["mt.new"]["disabled"] is True

    me = creds["ROLE_COMMANDER"][0]
    assert client.post(f"/api/users/{me}", headers=cdr,
                       json={"disabled": True}).status_code == 400
