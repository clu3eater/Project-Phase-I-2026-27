"""Ground-station to fleet-server sync: store, forward, never lose.

These run against a REAL HTTP server on a real socket, not a mocked
`urlopen`. The failures worth catching live in the gap between "the function
was called" and "the bytes arrived and were acknowledged", and a mock cannot
express that gap.

The properties under test are the ones an intermittent link actually breaks:

  * a station with no route to the server loses nothing;
  * a batch whose acknowledgement is lost does not duplicate the sortie;
  * a partial acceptance retries only the remainder;
  * a standalone station is a valid deployment, not a broken one.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from layer4_core import fleet_sync as fs
from layer4_core.fleet_sync import FleetSync, SyncOutbox

DATUM = {"engine_key": "rotax_915is", "aircraft_id": "MALE-01",
         "flight_hours": 12.5, "cht_max_c": 104.0, "health_chi": 0.97}


class _Server:
    """A real fleet-server stand-in: real socket, real HTTP, scriptable."""

    def __init__(self, mode: str = "accept_all") -> None:
        self.mode = mode
        self.seen: list[dict] = []          # every batch it received
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):      # keep the test output readable
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n).decode())
                outer.seen.append(body)
                uuids = [r["record_uuid"] for r in body["records"]]

                if outer.mode == "accept_none":
                    payload = {"accepted": []}
                elif outer.mode == "accept_half":
                    payload = {"accepted": uuids[: max(1, len(uuids) // 2)]}
                elif outer.mode == "lose_ack":
                    # The record IS received, but the acknowledgement never
                    # arrives. This is the ordinary failure on a bad link, and
                    # the one that duplicates data if ingest is not idempotent.
                    self.close_connection = True
                    return
                else:
                    payload = {"accepted": uuids}

                out = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server():
    s = _Server()
    yield s
    s.stop()


def _sync(tmp_path, url: str) -> FleetSync:
    return FleetSync(base_url=url, station_id="GCS-TEST", api_key="k",
                     outbox=SyncOutbox(tmp_path / "outbox.db"))


# --- the offline case, which is the normal one -----------------------------

def test_a_station_with_no_route_to_the_server_loses_nothing(tmp_path):
    """The defining requirement. A field station may be offline for days."""
    s = _sync(tmp_path, "http://127.0.0.1:9")     # nothing listens on port 9
    s.outbox.enqueue("flight_record", DATUM)
    s.outbox.enqueue("flight_record", DATUM)

    assert s.sync_once() == 0
    assert s.outbox.pending() == 2, "records were dropped when the link failed"

    st = s.stats()
    assert st["pending"] == 2
    assert st["reachable"] is False
    assert st["last_error"], "the operator must be told WHY it is not draining"


def test_the_backlog_drains_when_the_link_returns(tmp_path, server):
    """Queue while offline, then deliver."""
    offline = _sync(tmp_path, "http://127.0.0.1:9")
    for _ in range(3):
        offline.outbox.enqueue("flight_record", DATUM)
    offline.sync_once()
    assert offline.outbox.pending() == 3

    online = FleetSync(base_url=server.url, station_id="GCS-TEST",
                       api_key="k", outbox=offline.outbox)
    assert online.sync_once() == 3
    assert online.outbox.pending() == 0
    assert len(server.seen[0]["records"]) == 3


# --- idempotence -----------------------------------------------------------

def test_a_uuid_is_assigned_once_and_survives_every_retry(tmp_path):
    """THE PROPERTY THAT PREVENTS DUPLICATED SORTIES.

    Generating the id at SEND time would mint a new one on each retry, so the
    ordinary failure -- delivered, acknowledgement lost -- would file the same
    flight twice, and again on the next retry.
    """
    fail = _Server(mode="accept_none")
    try:
        s = _sync(tmp_path, fail.url)
        rid = s.outbox.enqueue("flight_record", DATUM)
        s.sync_once()
        s.sync_once()
        s.sync_once()
        seen = {r["record_uuid"] for batch in fail.seen for r in batch["records"]}
        assert seen == {rid}, "the id changed between retries"
        assert len(fail.seen) == 3, "it did not actually retry"
        assert s.outbox.pending() == 1
    finally:
        fail.stop()


def test_a_dropped_connection_keeps_the_record_for_retry(tmp_path):
    """Delivered but unacknowledged must be retried, not assumed delivered."""
    flaky = _Server(mode="lose_ack")
    try:
        s = _sync(tmp_path, flaky.url)
        s.outbox.enqueue("flight_record", DATUM)
        assert s.sync_once() == 0
        assert s.outbox.pending() == 1
        assert flaky.seen, "the server never received it at all"
    finally:
        flaky.stop()


# --- partial acceptance ----------------------------------------------------

def test_only_acknowledged_records_are_marked_synced(tmp_path):
    """A 200 is not an acceptance.

    Marking a whole batch done because the call returned 200 is how records
    disappear: the server took two of four and the station forgets the rest.
    """
    half = _Server(mode="accept_half")
    try:
        s = _sync(tmp_path, half.url)
        for _ in range(4):
            s.outbox.enqueue("flight_record", DATUM)
        assert s.sync_once() == 2
        assert s.outbox.pending() == 2, "unacknowledged records were lost"
    finally:
        half.stop()


# --- deployment shapes -----------------------------------------------------

def test_a_standalone_station_is_valid_and_silent(tmp_path):
    """No central server configured is a supported deployment.

    It must not log a failure every thirty seconds about a server it was
    never told about.
    """
    s = FleetSync(base_url="", station_id="GCS-TEST",
                  outbox=SyncOutbox(tmp_path / "outbox.db"))
    assert s.configured is False
    assert s.sync_once() == 0
    s.start()                      # must be a no-op, not a crash
    assert s.stats()["configured"] is False
    s.stop()


def test_the_station_identifies_itself_on_every_batch(tmp_path, server):
    """Records are only attributable if the station says who it is."""
    s = _sync(tmp_path, server.url)
    s.outbox.enqueue("flight_record", DATUM)
    s.sync_once()
    assert server.seen[0]["station_id"] == "GCS-TEST"
    assert server.seen[0]["records"][0]["payload"]["aircraft_id"] == "MALE-01"


# ---------------------------------------------------------------------------
# The central directory: one account, every station
# ---------------------------------------------------------------------------


class _Resp:
    """Stand-in for urlopen's context-managed response."""

    def __init__(self, payload):
        import json as _j
        self._b = _j.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_urlopen(monkeypatch, payload):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp(payload))


def test_the_directory_pull_caches_accounts_the_station_never_had(
        tmp_path, monkeypatch):
    """One account has to work on every ground station.

    Each station keeps its own store, so before the directory existed they
    seeded their own accounts and shared nothing: logging in on a colleague's
    station meant using that station's separate credentials.
    """
    import bcrypt

    monkeypatch.setenv("DT_DATA_DIR", str(tmp_path / "station"))
    from layer4_core import security as sec

    pw = "Falcon-Ridge-77!"
    payload = {"complete": True, "count": 1, "accounts": [{
        "username": "sqn.kapoor", "role": "ROLE_ENGINEER",
        "hash": bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode(),
        "disabled": False, "must_change": False, "token_epoch": 0,
    }]}

    with pytest.raises(sec.AuthError):
        sec.authenticate("sqn.kapoor", pw)

    # A real directory is signed, and this test link is plain HTTP by choice.
    monkeypatch.setenv("DT_FLEET_ALLOW_HTTP", "1")
    monkeypatch.setenv("DT_FLEET_DIRECTORY_KEY", "dir-key")
    payload["signature"] = fs.FleetSync.directory_signature(
        payload["accounts"], "dir-key")
    _patch_urlopen(monkeypatch, payload)
    syncer = fs.FleetSync(base_url="http://fleet.invalid",
                          station_id="station-alpha", api_key="k")
    assert syncer.pull_directory() == 1
    assert sec.authenticate("sqn.kapoor", pw) == "ROLE_ENGINEER"


def test_an_unreachable_centre_does_not_empty_the_directory(
        tmp_path, monkeypatch):
    """The failure that locks a whole station out of its own console.

    A station is designed to survive the centre being down for days. If a
    failed pull replaced the cache with nothing, the first outage would take
    every account with it -- and it would happen at exactly the moment nobody
    could reach the centre to fix it.
    """
    import urllib.error
    import urllib.request

    monkeypatch.setenv("DT_DATA_DIR", str(tmp_path / "station"))
    from layer4_core import security as sec

    before = sec._users()                      # seeds the local accounts
    assert before, "no accounts to lose"

    def _boom(req, timeout=None):
        raise urllib.error.URLError("link down")

    monkeypatch.setenv("DT_FLEET_ALLOW_HTTP", "1")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    syncer = fs.FleetSync(base_url="http://fleet.invalid",
                          station_id="station-alpha", api_key="k")
    assert syncer.pull_directory() == 0
    assert sec._users() == before, "an outage emptied the account store"


def test_an_incomplete_answer_is_refused_rather_than_cached(
        tmp_path, monkeypatch):
    """A truncated response must not replace a complete cache.

    The endpoint says `complete` explicitly instead of leaving it to be
    inferred from a count, because a count cannot distinguish "three accounts"
    from "the first three of forty".
    """
    monkeypatch.setenv("DT_DATA_DIR", str(tmp_path / "station"))
    from layer4_core import security as sec

    before = sec._users()
    monkeypatch.setenv("DT_FLEET_ALLOW_HTTP", "1")
    _patch_urlopen(monkeypatch, {"complete": False, "count": 1, "accounts": [
        {"username": "x", "role": "ROLE_OPERATOR", "hash": "$2b$x"}]})
    syncer = fs.FleetSync(base_url="http://fleet.invalid",
                          station_id="s", api_key="k")
    assert syncer.pull_directory() == 0
    assert sec._users() == before



# ---------------------------------------------------------------------------
# Review fix SEC-01: the directory is signed, and the link is not plain HTTP
# ---------------------------------------------------------------------------


def test_an_unsigned_or_forged_directory_is_refused(tmp_path, monkeypatch):
    """The directory REPLACES the station user store, so an answer nobody can
    vouch for -- from a rogue station key or a man in the middle -- must never
    be cached. It would have planted a Commander account."""
    import bcrypt

    monkeypatch.setenv("DT_DATA_DIR", str(tmp_path / "station"))
    monkeypatch.setenv("DT_FLEET_ALLOW_HTTP", "1")
    from layer4_core import security as sec

    before = sec._users()
    acct = [{"username": "rogue.cdr", "role": "ROLE_COMMANDER",
             "hash": bcrypt.hashpw(b"Xy-12345678", bcrypt.gensalt(rounds=4)).decode(),
             "disabled": False, "must_change": False, "token_epoch": 0}]
    syncer = fs.FleetSync(base_url="http://fleet.invalid",
                          station_id="s", api_key="k")

    monkeypatch.delenv("DT_FLEET_DIRECTORY_KEY", raising=False)
    monkeypatch.delenv("DT_FLEET_ALLOW_UNSIGNED_DIRECTORY", raising=False)
    _patch_urlopen(monkeypatch, {"complete": True, "count": 1, "accounts": acct})
    assert syncer.pull_directory() == 0, "an unverifiable directory was cached"

    monkeypatch.setenv("DT_FLEET_DIRECTORY_KEY", "dir-key")
    _patch_urlopen(monkeypatch, {
        "complete": True, "count": 1, "accounts": acct,
        "signature": fs.FleetSync.directory_signature(acct, "other-key")})
    assert syncer.pull_directory() == 0, "a forged signature was accepted"
    assert sec._users() == before


def test_plain_http_to_a_remote_fleet_server_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("DT_DATA_DIR", str(tmp_path / "station"))
    monkeypatch.delenv("DT_FLEET_ALLOW_HTTP", raising=False)
    remote = fs.FleetSync(base_url="http://fleet.invalid", station_id="s", api_key="k")
    assert remote._link_refused()
    assert not fs.FleetSync(base_url="https://fleet.invalid",
                            station_id="s", api_key="k")._link_refused()
    assert not fs.FleetSync(base_url="http://127.0.0.1:8100",
                            station_id="s", api_key="k")._link_refused()
