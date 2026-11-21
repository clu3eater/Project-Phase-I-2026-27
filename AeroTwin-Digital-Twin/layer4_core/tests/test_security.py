"""Tests for authentication, authorisation and the audit log.

The claim these exist to check is PRD Part 4 s10c:

    "Authorisation SHALL be enforced server-side regardless of UI state; the
     UI is a convenience, never the security boundary."

A UI that hides a button proves nothing. So the tests here FORCE calls the
console would never render and assert the API refuses them, which is the only
version of that claim worth making.
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest
from fastapi.testclient import TestClient

from layer4_core import security as sec
from layer4_core.twin_api import app


@pytest.fixture(scope="module", autouse=True)
def isolated_store(tmp_path_factory):
    """A credential store per run.

    These tests create accounts and change passwords. Pointed at the real data
    directory they rewrote the store the demonstration itself logs in with:
    fifteen leftover `rv.*` test accounts accumulated in it, and a commander
    whose password had since been changed through the console no longer matched
    the first-run note, which failed three of these tests on a later run for a
    reason that had nothing to do with the code. A test that depends on what
    earlier runs left behind is not a test.
    """
    import os

    import layer4_core.twin_api as api

    root = tmp_path_factory.mktemp("security_data")
    prev = os.environ.get("DT_DATA_DIR")
    os.environ["DT_DATA_DIR"] = str(root)
    sec._PRIVATE = sec._PUBLIC = None      # the signing keys are cached per process
    # The API binds its audit log at import (twin_api.AUDIT), so it must be
    # rebuilt here or the calls under test append to the real log while these
    # tests read the temporary one.
    prev_audit = api.AUDIT
    api.AUDIT = sec.AuditLog()
    try:
        yield root
    finally:
        api.AUDIT = prev_audit
        if prev is None:
            os.environ.pop("DT_DATA_DIR", None)
        else:
            os.environ["DT_DATA_DIR"] = prev
        sec._PRIVATE = sec._PUBLIC = None


@pytest.fixture(scope="module")
def client(isolated_store):
    # These tests exercise authentication and authorisation with the seeded
    # first-run accounts, which must now change their password before use
    # (SEC-02). The demonstration override keeps them usable here; the
    # enforcement itself is tested below with the override removed.
    import os

    prev = os.environ.get("DT_ALLOW_INITIAL_PASSWORDS")
    os.environ["DT_ALLOW_INITIAL_PASSWORDS"] = "1"
    yield TestClient(app)
    if prev is None:
        os.environ.pop("DT_ALLOW_INITIAL_PASSWORDS", None)
    else:
        os.environ["DT_ALLOW_INITIAL_PASSWORDS"] = prev


@pytest.fixture(scope="module")
def creds(isolated_store) -> dict[str, tuple[str, str]]:
    """The first-run demonstration accounts, one per role."""
    sec._users()  # seeds on first call
    note = sec.config.data_dir() / "keys" / "FIRST_RUN_CREDENTIALS.txt"
    out: dict[str, tuple[str, str]] = {}
    for line in note.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1].startswith("ROLE_"):
            out[parts[1]] = (parts[0], parts[2])
    return out


def _token(client, creds, role: str) -> dict[str, str]:
    user, pw = creds[role]
    r = client.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_every_api_route_refuses_an_unauthenticated_caller(client):
    for path in ("/api/state", "/api/engine", "/api/faults", "/api/mission",
                 "/api/maintenance", "/api/fleet", "/api/audit",
                 "/api/replay/sessions", "/api/testrig/schedules"):
        assert client.get(path).status_code == 401, path


def test_the_demo_endpoint_discloses_nothing_on_a_real_station(client, monkeypatch):
    """/api/demo is public because the login screen reads it before anyone has
    signed in. Off the demonstration copy it must carry no account at all."""
    monkeypatch.delenv("DT_DEMO_MODE", raising=False)
    r = client.get("/api/demo")
    assert r.status_code == 200
    assert r.json() == {"demo": False, "accounts": []}


def test_healthz_stays_public(client):
    """A liveness probe that needs a credential cannot be used by the thing
    that restarts the service."""
    assert client.get("/api/healthz").status_code in (200, 503)


def test_a_wrong_password_and_an_unknown_user_are_indistinguishable(client, creds):
    user, _ = creds["ROLE_COMMANDER"]
    a = client.post("/api/auth/login",
                    json={"username": user, "password": "wrong"})
    b = client.post("/api/auth/login",
                    json={"username": "no.such.person", "password": "wrong"})
    assert a.status_code == b.status_code == 401
    # Distinguishing them tells an attacker which usernames exist, which is
    # half the work of guessing a credential.
    assert a.json()["detail"] == b.json()["detail"]


def test_a_garbage_token_is_refused(client):
    r = client.get("/api/state",
                   headers={"Authorization": "Bearer not.a.real.token"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# The token itself
# ---------------------------------------------------------------------------


def _craft(alg: str, secret: bytes, payload: dict) -> str:
    """Hand-rolled JWT, to attack the verifier rather than PyJWT's encoder."""
    import base64
    import hashlib
    import hmac

    def b64(b: bytes) -> bytes:
        return base64.urlsafe_b64encode(b).rstrip(b"=")

    head = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = b64(json.dumps(payload).encode())
    signing = head + b"." + body
    if alg == "none":
        return (signing + b".").decode()
    sig = hmac.new(secret, signing, hashlib.sha256).digest()
    return (signing + b"." + b64(sig)).decode()


def test_alg_none_is_refused():
    """The oldest JWT attack there is: drop the signature and assert a role."""
    import time

    tok = _craft("none", b"", {
        "sub": "attacker", "role": "ROLE_COMMANDER", "iss": "dt-uav-gcs",
        "iat": int(time.time()), "exp": int(time.time()) + 999,
    })
    with pytest.raises(sec.AuthError):
        sec.verify_token(tok)


def test_algorithm_confusion_is_refused():
    """RS256 downgraded to HS256, signed with the PUBLIC key.

    The public key is, by definition, public. If the verifier trusts the
    header's algorithm it will happily HMAC-verify with a key the attacker
    already has. The algorithm is pinned to the configured one instead.
    """
    import time

    _, pub = sec._keys()
    tok = _craft("HS256", pub, {
        "sub": "attacker", "role": "ROLE_COMMANDER", "iss": "dt-uav-gcs",
        "iat": int(time.time()), "exp": int(time.time()) + 999,
    })
    with pytest.raises(sec.AuthError):
        sec.verify_token(tok)


def test_an_expired_token_is_refused():
    import jwt

    priv, _ = sec._keys()
    tok = jwt.encode(
        {"sub": "x", "role": "ROLE_OPERATOR", "iss": "dt-uav-gcs",
         "iat": 1, "exp": 2},
        priv, algorithm="RS256",
    )
    with pytest.raises(sec.AuthError, match="expired"):
        sec.verify_token(tok)


def test_a_token_from_another_issuer_is_refused():
    import jwt
    import time

    priv, _ = sec._keys()
    tok = jwt.encode(
        {"sub": "x", "role": "ROLE_COMMANDER", "iss": "somewhere-else",
         "iat": int(time.time()), "exp": int(time.time()) + 999},
        priv, algorithm="RS256",
    )
    with pytest.raises(sec.AuthError):
        sec.verify_token(tok)


def test_an_access_token_expires_when_the_config_says(client, creds):
    user, pw = creds["ROLE_OPERATOR"]
    j = client.post("/api/auth/login",
                    json={"username": user, "password": pw}).json()
    minutes = int(sec.config.load_thresholds()["security"]["jwt"]
                  ["access_token_minutes"])
    assert j["expires_in_s"] == minutes * 60


# ---------------------------------------------------------------------------
# Authorisation -- the UI is never the boundary (s10c)
# ---------------------------------------------------------------------------


def test_an_operator_cannot_reach_what_the_console_would_not_render(client, creds):
    """The console hides these tabs from an operator. That is not why they are
    refused; this forces the call anyway."""
    h = _token(client, creds, "ROLE_OPERATOR")
    for path in ("/api/fleet", "/api/audit", "/api/maintenance",
                 "/api/testrig/schedules"):
        assert client.get(path, headers=h).status_code == 403, path


def test_an_engineer_may_simulate_but_not_read_the_audit_log(client, creds):
    h = _token(client, creds, "ROLE_ENGINEER")
    assert client.get("/api/testrig/schedules", headers=h).status_code == 200
    assert client.get("/api/audit", headers=h).status_code == 403


def test_maintenance_may_read_the_advisory_but_not_run_the_rig(client, creds):
    h = _token(client, creds, "ROLE_MAINTENANCE")
    assert client.get("/api/testrig/schedules", headers=h).status_code == 403
    # The advisory itself needs a running twin, so a 503 here is the twin
    # being absent rather than authorisation refusing.
    assert client.get("/api/maintenance", headers=h).status_code != 403


def test_only_maintenance_and_the_commander_may_record_completed_work(client, creds):
    """write:maintenance, per thresholds.security.roles. Recording work changes
    what the twin believes about the engine, so it is not an operator's or an
    engineer's call."""
    body = {"action_id": "A1"}
    for role in ("ROLE_OPERATOR", "ROLE_ENGINEER"):
        h = _token(client, creds, role)
        assert client.post("/api/maintenance/performed", json=body,
                           headers=h).status_code == 403, role
    for role in ("ROLE_MAINTENANCE", "ROLE_COMMANDER"):
        h = _token(client, creds, role)
        # 503 is the twin being absent, as for the advisory above.
        assert client.post("/api/maintenance/performed", json=body,
                           headers=h).status_code in (200, 503), role
    h = _token(client, creds, "ROLE_MAINTENANCE")
    assert client.post("/api/maintenance/performed", json={"action_id": "A9"},
                       headers=h).status_code == 422


def test_only_the_commander_reaches_the_fleet_and_the_audit_log(client, creds):
    h = _token(client, creds, "ROLE_COMMANDER")
    # 503 means the synthetic fleet is absent -- data/synthetic is git-ignored,
    # so a fresh checkout and CI have none. That is a DATA condition, and this
    # test is about AUTHORISATION: asserting 200 made it fail on every clean
    # machine for a reason that has nothing to do with who may read the route.
    assert client.get("/api/fleet", headers=h).status_code in (200, 503)
    assert client.get("/api/audit", headers=h).status_code == 200


def test_every_role_can_read_replay(client, creds):
    """All four roles carry read:replay, per thresholds.security.roles."""
    for role in ("ROLE_OPERATOR", "ROLE_ENGINEER", "ROLE_MAINTENANCE",
                 "ROLE_COMMANDER"):
        h = _token(client, creds, role)
        # 503 = no recorded sessions on this machine; again a data condition.
        assert client.get("/api/replay/sessions",
                          headers=h).status_code in (200, 503)


def test_the_wildcard_belongs_to_the_commander_alone():
    assert sec.has_scope("ROLE_COMMANDER", "anything:at:all")
    for role in ("ROLE_OPERATOR", "ROLE_ENGINEER", "ROLE_MAINTENANCE"):
        assert not sec.has_scope(role, "anything:at:all")


def test_an_unknown_role_carries_no_scopes():
    assert sec.scopes_for("ROLE_INVENTED") == set()
    assert not sec.has_scope("ROLE_INVENTED", "read:telemetry")


# ---------------------------------------------------------------------------
# The websocket is a route like any other
# ---------------------------------------------------------------------------


def test_the_telemetry_socket_refuses_an_unauthenticated_peer(client):
    """Leaving the socket open while the REST API was locked down would make
    the entire telemetry stream readable by anyone who could reach the port."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/state") as ws:
            ws.receive_text()
    assert exc.value.code == 4401


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def _tmp_log() -> sec.AuditLog:
    return sec.AuditLog(pathlib.Path(tempfile.mkdtemp()) / "audit.jsonl")


def test_a_clean_chain_verifies():
    log = _tmp_log()
    for i in range(4):
        log.record("AUTH", subject=f"u{i}", role="ROLE_OPERATOR", n=i)
    v = log.verify()
    assert v["ok"] and v["entries"] == 4 and v["broken_at"] is None


def test_editing_an_entry_breaks_the_chain():
    """A log that is merely appended to is not append-only: whoever can write
    the file can rewrite the middle of it."""
    log = _tmp_log()
    log.record("AUTH", subject="a", role="ROLE_COMMANDER")
    log.record("AUTHZ_DENY", subject="b", role="ROLE_OPERATOR",
               scope="write:maintenance")
    log.record("ALERT_ACK", subject="a", role="ROLE_COMMANDER")

    lines = log.path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1])
    rec["event"] = "AUTH"          # hide the refusal
    lines[1] = json.dumps(rec, separators=(",", ":"))
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    v = log.verify()
    assert not v["ok"]
    assert v["broken_at"] == 2


def test_deleting_an_entry_breaks_the_chain():
    log = _tmp_log()
    for i in range(4):
        log.record("AUTH", subject=f"u{i}", role="ROLE_OPERATOR")
    lines = log.path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not log.verify()["ok"]


def test_a_refused_call_is_recorded(client, creds):
    """An audit log that records only successes is not an audit log."""
    before = len(sec.AuditLog().entries(limit=10_000))
    h = _token(client, creds, "ROLE_OPERATOR")
    client.get("/api/audit", headers=h)          # refused, and recorded
    entries = sec.AuditLog().entries(limit=10_000)
    assert len(entries) > before
    denies = [e for e in entries if e["event"] == "AUTHZ_DENY"]
    assert denies, "a refusal must reach the audit log"
    # The scope lives under "detail" -- record() collects its kwargs there.
    assert denies[-1]["detail"].get("scope") == "read:audit"
    assert denies[-1]["role"] == "ROLE_OPERATOR"


def test_a_successful_login_is_recorded(client, creds):
    user, pw = creds["ROLE_ENGINEER"]
    client.post("/api/auth/login", json={"username": user, "password": pw})
    entries = sec.AuditLog().entries(limit=10_000)
    auths = [e for e in entries if e["event"] == "AUTH"
             and e["subject"] == user]
    assert auths


# ---------------------------------------------------------------------------
# Credential hygiene
# ---------------------------------------------------------------------------


def test_the_user_store_holds_only_hashes():
    """The store must disclose nothing even if it is read.

    Now checked against the RAW DATABASE FILE rather than against the records
    read back through the code. Reading it back can only find what the schema
    exposes; scanning the bytes finds a plaintext password wherever it landed,
    including in a stale page SQLite has not yet reused.
    """
    users = sec._users()
    assert users, "no accounts in the store"
    for rec in users.values():
        assert "password" not in rec
        assert rec["hash"].startswith("$2"), "not a bcrypt hash"

    note = sec.config.data_dir() / "keys" / "FIRST_RUN_CREDENTIALS.txt"
    if not note.exists():
        return
    issued = {
        line.split()[-1]
        for line in note.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(("op.", "eng.", "mt.", "cdr."))
    }
    assert issued, "could not read the issued passwords to check against"

    raw = (sec.config.data_dir() / "keys" / "users.db").read_bytes()
    for pw in issued:
        assert pw.encode() not in raw, "a plaintext password reached the store"


def test_the_account_flags_cannot_go_missing():
    """The reason this store is a table and not a file.

    The JSON store lost `disabled`, `must_change` and `token_epoch` from every
    record, and nothing failed: `must_change_password` reads a missing field as
    False, so the forced password change silently stopped being enforced on
    every seeded account. A NOT NULL DEFAULT column cannot do that.
    """
    import sqlite3

    with sec._connect_users() as cx:
        cols = {r["name"]: r for r in
                cx.execute("PRAGMA table_info(users)").fetchall()}

    for flag, default in (("disabled", "0"), ("must_change", "1"),
                          ("token_epoch", "0")):
        assert flag in cols, f"{flag} is not a column"
        assert cols[flag]["notnull"], f"{flag} may be NULL"
        assert cols[flag]["dflt_value"] == default, flag

    # And the safe default is the CONSERVATIVE one: an account whose password
    # history is unknown is one that should change it.
    with sec._connect_users() as cx:
        cx.execute(
            "INSERT INTO users (username, role, hash, created_utc, updated_utc)"
            " VALUES ('probe.user', 'ROLE_OPERATOR', '$2b$x', 'x', 'x')")
        cx.commit()
        row = cx.execute(
            "SELECT * FROM users WHERE username='probe.user'").fetchone()
        assert row["must_change"] == 1, "a new account was not asked to change"
        assert row["disabled"] == 0
        cx.execute("DELETE FROM users WHERE username='probe.user'")
        cx.commit()


def test_the_signing_key_and_store_are_git_ignored():
    """A private key committed to a repository is not a private key."""
    import subprocess

    for rel in ("data/keys/gcs_signing_key.pem", "data/keys/users.json",
                "data/keys/FIRST_RUN_CREDENTIALS.txt"):
        # The REPOSITORY is what must ignore these, so ask git about the repo
        # rather than about whatever data directory the process is pointed at.
        out = subprocess.run(
            ["git", "check-ignore", rel],
            cwd=sec.config.repo_root(), capture_output=True, text=True,
        )
        assert out.returncode == 0, f"{rel} is NOT git-ignored"



# ---------------------------------------------------------------------------
# Review fixes: SEC-02, SEC-04, SEC-06, SEC-07, SEC-13
# ---------------------------------------------------------------------------


def _new_user(role: str = "ROLE_OPERATOR") -> tuple[str, str]:
    import secrets as _s

    user = "rv." + _s.token_hex(4)
    pw = "Kestrel-Range-" + _s.token_hex(3) + "!A9"
    sec.create_user(user, pw, role)
    return user, pw


def test_a_first_run_password_must_be_changed_before_use(client, monkeypatch):
    """SEC-02. must_change was set on every seeded account and enforced nowhere."""
    user, pw = _new_user()
    monkeypatch.delenv("DT_ALLOW_INITIAL_PASSWORDS", raising=False)
    r = client.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 403
    new = "Harrier-Crest-" + pw[-6:] + "Z"
    r = client.post("/api/auth/change_password", json={
        "username": user, "old_password": pw, "new_password": new})
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/login", json={"username": user, "password": new})
    assert r.status_code == 200, r.text


def test_a_password_change_needs_the_current_password(client):
    user, _ = _new_user()
    r = client.post("/api/auth/change_password", json={
        "username": user, "old_password": "not-it",
        "new_password": "Osprey-Lake-42!"})
    assert r.status_code == 401


def test_a_refresh_token_renews_access_but_opens_no_route(client, creds):
    """SEC-07 and HMI-03. The refresh token worked as an access token, and
    nothing could renew an expiring access token."""
    user, pw = creds["ROLE_OPERATOR"]
    j = client.post("/api/auth/login",
                    json={"username": user, "password": pw}).json()
    bad = client.get("/api/auth/me",
                     headers={"Authorization": "Bearer " + j["refresh_token"]})
    assert bad.status_code == 401
    r = client.post("/api/auth/refresh", json={"refresh_token": j["refresh_token"]})
    assert r.status_code == 200, r.text
    ok = client.get("/api/auth/me",
                    headers={"Authorization": "Bearer " + r.json()["access_token"]})
    assert ok.status_code == 200
    again = client.post("/api/auth/refresh",
                        json={"refresh_token": r.json()["access_token"]})
    assert again.status_code == 401


def test_a_token_whose_role_no_longer_matches_the_store_is_refused():
    """SEC-06. The role claim inside the token was trusted on its own."""
    user, _ = _new_user("ROLE_OPERATOR")
    with pytest.raises(sec.AuthError):
        sec.verify_token(sec.issue_token(user, "ROLE_COMMANDER"))


def test_a_password_longer_than_bcrypt_can_use_is_refused():
    """SEC-13. Silently cut at 72 bytes, two different long passwords matched."""
    with pytest.raises(ValueError):
        sec._hash_pw("A" * 80)
    assert sec._verify_pw("A" * 80, sec._hash_pw("A" * 72)) is False


def test_a_truncated_or_deleted_audit_log_no_longer_verifies(tmp_path):
    """SEC-04. Cutting the tail or deleting the file used to verify as ok."""
    log = sec.AuditLog(path=tmp_path / "audit.jsonl")
    for i in range(6):
        log.record("TEST", subject=f"s{i}")
    assert log.verify()["ok"]
    lines = log.path.read_text(encoding="utf-8").splitlines(keepends=True)
    log.path.write_text("".join(lines[:-2]), encoding="utf-8")
    r = sec.AuditLog(path=tmp_path / "audit.jsonl").verify()
    assert not r["ok"] and "truncated" in r["reason"]
    log.path.unlink()
    assert not sec.AuditLog(path=tmp_path / "audit.jsonl").verify()["ok"]


def test_a_rewritten_audit_entry_cannot_be_resealed_without_the_key(tmp_path):
    """SEC-04. Editing an entry and recomputing every plain SHA-256 after it
    used to verify; the key and the sealed head now catch it."""
    import hashlib
    import json as _json

    log = sec.AuditLog(path=tmp_path / "audit.jsonl")
    for i in range(3):
        log.record("TEST", subject=f"s{i}")
    recs = [_json.loads(x) for x in log.path.read_text(encoding="utf-8").splitlines()]
    recs[1]["subject"] = "someone-else"
    prev = recs[0]["hash"]
    for r in recs[1:]:
        r.pop("v", None)
        r["prev_hash"] = prev
        body = {k: r[k] for k in ("seq", "utc", "event", "subject", "role",
                                  "detail", "prev_hash")}
        r["hash"] = hashlib.sha256(_json.dumps(
            body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        prev = r["hash"]
    log.path.write_text("".join(_json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    assert not sec.AuditLog(path=tmp_path / "audit.jsonl").verify()["ok"]


def test_every_role_can_read_the_emergency_procedures(client, creds):
    """A procedure is part of the alert, so whoever sees alerts sees it."""
    for role in ("ROLE_OPERATOR", "ROLE_MAINTENANCE", "ROLE_ENGINEER", "ROLE_COMMANDER"):
        r = client.get("/api/checklists", headers=_token(client, creds, role))
        assert r.status_code == 200, role
        assert any(p["id"] == "oil_pressure_low" for p in r.json()["procedures"])
    assert client.get("/api/checklists").status_code == 401
