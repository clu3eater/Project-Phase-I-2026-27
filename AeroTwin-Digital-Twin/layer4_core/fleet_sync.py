"""Ground station to central fleet server: store, forward, never lose.

WHY THIS EXISTS
---------------
Each ground station kept its own SQLite file and its own four users. Two
stations shared nothing -- no users, no flight history, no fleet picture. The
problem statement asks for "fleet-level health monitoring infrastructures" and
"cloud or local server-based analytics", and `fleet.py` is honest that its
roster is assembled from RECORDED synthetic lives rather than from real
stations reporting in.

THE CONSTRAINT THAT SHAPES ALL OF THIS
--------------------------------------
A ground station in the field may have no route to the central server for days,
and it must keep working completely. So the local SQLite store stays
authoritative for the station, and this module is a one-way store-and-forward
pipe on top of it. The twin never blocks on the network, and a station that has
been offline for a week loses nothing.

That is the same discipline `layer1_edge/edge_buffer.py` already applies one
level down, aircraft to ground -- buffer locally, drain oldest-first on
reconnect, and tell the operator what is still outstanding. This deliberately
reuses its vocabulary (`pending`, `drain`, `mark_synced`) rather than inventing
a second one for the same idea.

IDEMPOTENCE, BECAUSE RETRIES ARE NORMAL
---------------------------------------
A link that drops mid-batch is the expected case, not the exception. Every
record therefore carries a UUID generated ONCE at the station, and the central
server upserts on it. A batch delivered twice is harmless; a batch whose
acknowledgement was lost is re-sent and de-duplicated at the far end. Without
that, the ordinary failure -- send succeeded, ack lost -- silently duplicates
every flight in the fleet history.

WHAT THIS IS NOT
----------------
Not two-way replication. Flight records are append-only facts that only the
station can produce, so they flow up and never down. Users flow the other way
and are handled separately, because a directory needs different conflict rules
from an immutable observation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import config

_log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS outbox (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    record_uuid  TEXT    NOT NULL UNIQUE,
    kind         TEXT    NOT NULL,
    payload      TEXT    NOT NULL,
    created_utc  TEXT    NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT,
    synced       INTEGER NOT NULL DEFAULT 0,
    synced_utc   TEXT
);
CREATE INDEX IF NOT EXISTS ix_outbox_pending ON outbox(synced, id);
"""


def _utc() -> str:
    return (datetime.now(timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"))


@dataclass
class SyncStats:
    """What an operator needs to know about the backlog, per PRD Part 4 s7."""

    pending: int = 0
    synced: int = 0
    last_success_utc: str | None = None
    last_error: str | None = None
    reachable: bool = False

    def as_dict(self) -> dict:
        return {
            "pending": self.pending,
            "synced": self.synced,
            "last_success_utc": self.last_success_utc,
            "last_error": self.last_error,
            "reachable": self.reachable,
        }


class SyncOutbox:
    """Durable queue of records waiting to reach the central server."""

    def __init__(self, path: Path | str | None = None) -> None:
        if path is None:
            path = Path(config.data_dir()) / "history" / "outbox.db"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as cx:
            cx.executescript(_DDL)

    def _connect(self) -> sqlite3.Connection:
        cx = sqlite3.connect(self.path, timeout=5.0)
        cx.row_factory = sqlite3.Row
        cx.execute("PRAGMA journal_mode=WAL")
        return cx

    def enqueue(self, kind: str, payload: dict[str, Any]) -> str:
        """Queue one record. Returns the uuid the far end de-duplicates on.

        The uuid is generated HERE, once, and travels with the record for its
        whole life. Generating it at send time would produce a new id on every
        retry, which is precisely the duplication this is meant to prevent.
        """
        rid = str(uuid.uuid4())
        with self._lock, self._connect() as cx:
            cx.execute(
                "INSERT INTO outbox (record_uuid, kind, payload, created_utc) "
                "VALUES (?, ?, ?, ?)",
                (rid, kind, json.dumps(payload, default=str), _utc()),
            )
        _log.info("queued for the fleet server",
                  extra={"kind": kind, "record_uuid": rid})
        return rid

    def pending(self) -> int:
        with self._connect() as cx:
            return int(cx.execute(
                "SELECT COUNT(*) FROM outbox WHERE synced = 0").fetchone()[0])

    def drain(self, batch: int = 100) -> list[dict]:
        """Oldest first. The far end reads a backlog in the order it happened."""
        with self._connect() as cx:
            rows = cx.execute(
                "SELECT id, record_uuid, kind, payload, created_utc "
                "FROM outbox WHERE synced = 0 ORDER BY id ASC LIMIT ?",
                (batch,),
            ).fetchall()
        return [
            {"id": r["id"], "record_uuid": r["record_uuid"], "kind": r["kind"],
             "created_utc": r["created_utc"], "payload": json.loads(r["payload"])}
            for r in rows
        ]

    def mark_synced(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock, self._connect() as cx:
            cx.executemany(
                "UPDATE outbox SET synced = 1, synced_utc = ? WHERE id = ?",
                [(_utc(), i) for i in ids],
            )

    def mark_failed(self, ids: list[int], error: str) -> None:
        """Record the attempt. Nothing is ever discarded on failure."""
        if not ids:
            return
        with self._lock, self._connect() as cx:
            cx.executemany(
                "UPDATE outbox SET attempts = attempts + 1, last_error = ? "
                "WHERE id = ?",
                [(error[:500], i) for i in ids],
            )

    def stats(self) -> SyncStats:
        with self._connect() as cx:
            pend = int(cx.execute(
                "SELECT COUNT(*) FROM outbox WHERE synced = 0").fetchone()[0])
            done = int(cx.execute(
                "SELECT COUNT(*) FROM outbox WHERE synced = 1").fetchone()[0])
            last = cx.execute(
                "SELECT synced_utc FROM outbox WHERE synced = 1 "
                "ORDER BY id DESC LIMIT 1").fetchone()
            err = cx.execute(
                "SELECT last_error FROM outbox WHERE synced = 0 "
                "AND last_error IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        return SyncStats(
            pending=pend, synced=done,
            last_success_utc=last["synced_utc"] if last else None,
            last_error=err["last_error"] if err else None,
        )


class FleetSync:
    """Drains the outbox to the central server, in the background, forever.

    Backoff is exponential and capped. A station that cannot reach the server
    must not spend its uplink retrying every second, and must not give up
    either -- the link may return in an hour or in a week.
    """

    def __init__(
        self,
        base_url: str | None = None,
        station_id: str | None = None,
        api_key: str | None = None,
        outbox: SyncOutbox | None = None,
        *,
        interval_s: float = 30.0,
        timeout_s: float = 15.0,
        batch: int = 100,
    ) -> None:
        self.base_url = (base_url or os.environ.get("DT_FLEET_URL") or "").rstrip("/")
        self.station_id = station_id or os.environ.get("DT_STATION_ID") or "GCS-01"
        self.api_key = api_key or os.environ.get("DT_STATION_KEY") or ""
        self.outbox = outbox or SyncOutbox()
        self.interval_s = interval_s
        self.timeout_s = timeout_s
        self.batch = batch

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._reachable = False
        self._backoff = interval_s

    # Fields covered by the directory signature. Mirrors fleet_server/app.py.
    _SIGNED_FIELDS = ("username", "role", "hash", "disabled", "must_change",
                      "token_epoch")

    @classmethod
    def directory_signature(cls, accounts: list[dict], key: str) -> str:
        canon = json.dumps(
            [{k: a.get(k) for k in cls._SIGNED_FIELDS}
             for a in sorted(accounts, key=lambda a: str(a.get("username")))],
            sort_keys=True, separators=(",", ":"), default=str)
        return hmac.new(key.encode("utf-8"), canon.encode("utf-8"),
                        hashlib.sha256).hexdigest()

    def _link_refused(self) -> bool:
        """Plain HTTP to anything but loopback is refused unless opted in.

        The link carries bearer station keys up and account hashes down, so in
        clear text it hands both to anyone on the path (SEC-01). A compose
        network or an isolated test bench sets DT_FLEET_ALLOW_HTTP=1 on
        purpose; everything else uses HTTPS.
        """
        from urllib.parse import urlparse

        u = urlparse(self.base_url)
        if u.scheme != "http" or u.hostname in ("127.0.0.1", "localhost", "::1"):
            return False
        if os.environ.get("DT_FLEET_ALLOW_HTTP") == "1":
            return False
        _log.error("fleet link refused: plain HTTP to a non-loopback server; "
                   "use HTTPS or set DT_FLEET_ALLOW_HTTP=1 on an isolated "
                   "network", extra={"url": self.base_url})
        return True

    def pull_directory(self) -> int:
        """Fetch the fleet directory and replace the local account cache.

        This is what makes one account work on every ground station. The centre
        owns WHO EXISTS; each station keeps a copy and checks passwords against
        it locally.

        THE PASSWORD IS NEVER SENT ANYWHERE. What comes down the wire is the
        bcrypt hash, and the station verifies against that. So an operator can
        log in to an isolated station on the third day of a link outage with
        the credentials they were issued on the first -- which matters, because
        this station is designed to survive the centre being down for days, and
        central password checking would make every login depend on the one link
        expected to fail.

        Returns the number of accounts cached, or 0 if the centre is
        unreachable -- in which case the existing cache is LEFT ALONE. An
        unreachable server must not empty the directory and lock everyone out.
        """
        if not self.configured or self._link_refused():
            return 0
        req = urllib.request.Request(
            f"{self.base_url}/api/v1/directory", method="GET",
            headers={"X-Station-Id": self.station_id,
                     "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                answer = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self._reachable = False
            _log.warning("directory pull failed; keeping the cached accounts",
                         extra={"error": f"{type(exc).__name__}: {exc}"})
            return 0

        accounts = answer.get("accounts") or []
        # A partial answer must not replace a complete cache. The endpoint says
        # so explicitly rather than leaving it to be inferred from a count.
        if not answer.get("complete") or not accounts:
            _log.warning("directory answer incomplete or empty; cache kept",
                         extra={"count": len(accounts),
                                "complete": answer.get("complete")})
            return 0

        # THE DIRECTORY MUST BE SIGNED (SEC-01). It REPLACES this station's
        # whole user store, so an unsigned answer -- from a rogue station key
        # upserting accounts, or anyone in the middle of the link -- could
        # plant a Commander account. Verified against a key this station holds;
        # an unsigned directory is accepted only by explicit opt-in.
        key = os.environ.get("DT_FLEET_DIRECTORY_KEY", "")
        sig = answer.get("signature")
        if key:
            if not sig or not hmac.compare_digest(
                    str(sig), self.directory_signature(accounts, key)):
                _log.error("directory signature invalid; cache kept")
                return 0
        elif os.environ.get("DT_FLEET_ALLOW_UNSIGNED_DIRECTORY") != "1":
            _log.error("directory refused: DT_FLEET_DIRECTORY_KEY is not set, "
                       "so the answer cannot be verified; cache kept")
            return 0

        store = {
            a["username"]: {
                "role": a["role"],
                "hash": a["hash"],
                "disabled": bool(a.get("disabled", False)),
                "must_change": bool(a.get("must_change", True)),
                "token_epoch": int(a.get("token_epoch", 0) or 0),
            }
            for a in accounts
            if a.get("username") and a.get("role") and a.get("hash")
        }
        if not store:
            _log.warning("directory carried no usable accounts; cache kept")
            return 0

        # Imported here rather than at module scope: fleet_sync is used by
        # tooling that has no reason to pull in bcrypt and jwt.
        from layer4_core import security as sec

        sec._write_users(store)
        self._reachable = True
        _log.info("fleet directory cached", extra={"accounts": len(store)})
        return len(store)

    @property
    def configured(self) -> bool:
        """No central server configured is a VALID state, not an error.

        A standalone ground station is a supported deployment. It then queues
        nothing and reports nothing, rather than logging a failure every thirty
        seconds about a server it was never told about.
        """
        return bool(self.base_url)

    def stats(self) -> dict:
        s = self.outbox.stats()
        s.reachable = self._reachable
        d = s.as_dict()
        d["configured"] = self.configured
        d["station_id"] = self.station_id
        return d

    # ------------------------------------------------------------------
    def sync_once(self) -> int:
        """One drain-and-post. Returns how many records were accepted."""
        if not self.configured or self._link_refused():
            return 0
        rows = self.outbox.drain(self.batch)
        if not rows:
            self._reachable = True
            return 0

        body = json.dumps({
            "station_id": self.station_id,
            "schema_version": SCHEMA_VERSION,
            "records": [
                {"record_uuid": r["record_uuid"], "kind": r["kind"],
                 "created_utc": r["created_utc"], "payload": r["payload"]}
                for r in rows
            ],
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/v1/ingest", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "X-Station-Id": self.station_id,
                     "Authorization": f"Bearer {self.api_key}"},
        )
        ids = [r["id"] for r in rows]
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                answer = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # Expected, not exceptional. Keep the records, note why, back off.
            self._reachable = False
            self.outbox.mark_failed(ids, f"{type(exc).__name__}: {exc}")
            _log.warning("fleet sync failed; records retained",
                         extra={"pending": self.outbox.pending(),
                                "error": f"{type(exc).__name__}: {exc}"})
            return 0

        # Only mark what the server SAID it accepted. Assuming success because
        # the call returned 200 is how a batch silently disappears.
        accepted = {str(u) for u in answer.get("accepted", [])}
        done = [r["id"] for r in rows if r["record_uuid"] in accepted]
        self.outbox.mark_synced(done)
        missed = [r["id"] for r in rows if r["record_uuid"] not in accepted]
        if missed:
            self.outbox.mark_failed(missed, "server did not acknowledge")
        self._reachable = True
        _log.info("fleet sync", extra={"accepted": len(done),
                                       "unacknowledged": len(missed),
                                       "pending": self.outbox.pending()})
        return len(done)

    # ------------------------------------------------------------------
    # How many sync cycles between directory pulls. The roster changes when
    # somebody joins, leaves or is disabled -- rarely -- so pulling it every
    # cycle would spend a link that exists to carry flight records. But
    # DISABLING an account has to take effect within minutes, not hours, which
    # is why this is a small multiple and not a daily job.
    _DIRECTORY_EVERY = 10

    def _run(self) -> None:
        cycles = 0
        while not self._stop.is_set():
            try:
                # First cycle pulls immediately: a station that has just come
                # up after a roster change should not run for five minutes on
                # a stale directory.
                if cycles % self._DIRECTORY_EVERY == 0:
                    self.pull_directory()
                cycles += 1
                sent = self.sync_once()
                self._backoff = (
                    self.interval_s if sent or self._reachable
                    else min(self._backoff * 2.0, 3600.0)
                )
            except Exception:
                # A sync worker must never take the ground station down.
                _log.exception("fleet sync worker error")
                self._backoff = min(self._backoff * 2.0, 3600.0)
            self._stop.wait(self._backoff)

    def start(self) -> None:
        if self._thread is not None or not self.configured:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="fleet-sync")
        self._thread.start()
        _log.info("fleet sync started",
                  extra={"url": self.base_url, "station_id": self.station_id})

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
