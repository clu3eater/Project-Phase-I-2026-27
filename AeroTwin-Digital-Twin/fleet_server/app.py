"""Central fleet server -- the tier above the ground stations.

WHY THIS EXISTS
---------------
Each ground station held its own SQLite file and its own users. Two stations
shared nothing, so there was no fleet: no cross-airframe history, no common
directory, and `layer4_core/fleet.py` had to assemble its roster from RECORDED
SYNTHETIC lives because no real station was reporting anywhere.

The problem statement asks for "fleet-level health monitoring infrastructures"
and "cloud or local server-based analytics". Note the OR: an on-premise server
satisfies it, and for a defence deliverable that is the better reading --
docs/INDIGENISATION.md claims no foreign vendor in the critical path, and a
cloud tenancy would be exactly that.

THE DIVISION OF AUTHORITY, WHICH IS THE WHOLE DESIGN
----------------------------------------------------
  * A ground station is authoritative for ITS OWN observations. Flight records
    are immutable facts that only the station that flew the sortie can produce,
    so they flow upward and are never edited here.
  * The central server is authoritative for the DIRECTORY -- who exists, what
    role they hold, whether they are disabled.

Getting that backwards produces the classic distributed failure: two writers
for one fact and no rule for which wins. Here each fact has exactly one owner,
so there is nothing to reconcile.

A STATION MUST SURVIVE THIS SERVER BEING DOWN
---------------------------------------------
Completely, and for days. That is why the station keeps SQLite and queues
locally (`layer4_core/fleet_sync.py`); this server is a destination, never a
dependency. If it is unreachable the aircraft still flies, the console still
works, and the backlog drains when the link returns.

WHY POSTGRESQL HERE AND SQLITE THERE
------------------------------------
Not fashion, and not a reversal. It is the same criterion at a different scale:
a station has ONE writer and hundreds of rows, so SQLite is right; the fleet
tier has MANY stations writing concurrently, which is exactly what SQLite
serialises and PostgreSQL is built for. asyncpg rather than psycopg because it
is Apache-2.0 rather than LGPL and async-native, which matters for a claim
audited over the whole dependency closure.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from common import logging as dt_logging

_log = logging.getLogger("fleet_server")

# No default connection string (SEC-08): the old default carried a fixed
# username and password that every deployment shared unless it remembered to
# override them. The server refuses to start without DT_FLEET_DSN.
DSN = os.environ.get("DT_FLEET_DSN", "")

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    station_id     TEXT PRIMARY KEY,
    name           TEXT,
    api_key_hash   TEXT NOT NULL,
    disabled       BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_utc  TIMESTAMPTZ
);

-- record_uuid is the PRIMARY KEY, which is what makes ingest idempotent: a
-- batch whose acknowledgement was lost is re-sent and lands on the same row
-- instead of duplicating the sortie. That failure -- send succeeded, ack lost
-- -- is the ordinary one on an intermittent link, not the exotic one.
CREATE TABLE IF NOT EXISTS flight_records (
    record_uuid    UUID PRIMARY KEY,
    station_id     TEXT NOT NULL REFERENCES stations(station_id),
    engine_key     TEXT,
    aircraft_id    TEXT,
    recorded_utc   TIMESTAMPTZ,
    flight_hours   DOUBLE PRECISION,
    altitude_ft    DOUBLE PRECISION,
    oat_c          DOUBLE PRECISION,
    airspeed_kmh   DOUBLE PRECISION,
    throttle_pct   DOUBLE PRECISION,
    cht_max_c      DOUBLE PRECISION,
    cht_spread_c   DOUBLE PRECISION,
    egt_max_c      DOUBLE PRECISION,
    egt_spread_c   DOUBLE PRECISION,
    oil_pressure_psi      DOUBLE PRECISION,
    oil_temperature_c     DOUBLE PRECISION,
    coolant_temperature_c DOUBLE PRECISION,
    fuel_flow_lph  DOUBLE PRECISION,
    power_kw       DOUBLE PRECISION,
    health_chi     DOUBLE PRECISION,
    payload        JSONB,
    received_utc   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fr_aircraft ON flight_records(aircraft_id, recorded_utc);
CREATE INDEX IF NOT EXISTS ix_fr_station  ON flight_records(station_id, received_utc);

-- THE DIRECTORY. One row per person, for the whole fleet, so an operator has
-- ONE account rather than one per ground station.
--
-- `hash` is bcrypt and is the only password material that exists anywhere. It
-- is served to authenticated stations, which cache it and verify locally --
-- see the module docstring for why the password is never sent here.
--
-- NOT NULL DEFAULT on every flag for the same reason the station's own table
-- has them: `must_change` read as a missing value is False, which is the
-- permissive answer, and a security flag that can vanish silently will.
CREATE TABLE IF NOT EXISTS directory (
    username     TEXT    PRIMARY KEY,
    role         TEXT    NOT NULL,
    hash         TEXT    NOT NULL,
    disabled     BOOLEAN NOT NULL DEFAULT FALSE,
    must_change  BOOLEAN NOT NULL DEFAULT TRUE,
    token_epoch  BIGINT  NOT NULL DEFAULT 0,
    full_name    TEXT,
    created_utc  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_utc  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_dir_updated ON directory(updated_utc);
"""

_NUMERIC = (
    "flight_hours", "altitude_ft", "oat_c", "airspeed_kmh", "throttle_pct",
    "cht_max_c", "cht_spread_c", "egt_max_c", "egt_spread_c",
    "oil_pressure_psi", "oil_temperature_c", "coolant_temperature_c",
    "fuel_flow_lph", "power_kw", "health_chi",
)

pool: Any = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    dt_logging.setup_logging()
    import asyncpg

    if not DSN:
        raise RuntimeError("DT_FLEET_DSN is not set; the fleet server has no "
                           "default database credentials")
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=10)
    async with pool.acquire() as cx:
        await cx.execute(SCHEMA)
    _log.info("fleet server ready", extra={"dsn_host": DSN.split("@")[-1]})
    try:
        yield
    finally:
        await pool.close()
        _log.info("fleet server stopped")


app = FastAPI(
    title="Fleet health monitoring server",
    description="DRDO / IDEX PS 26054 -- central tier above the ground stations",
    version="1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Station authentication
# ---------------------------------------------------------------------------

def _hash_key(key: str) -> str:
    """SHA-256, not bcrypt.

    A station key is a long random machine-generated secret, not a
    human-chosen password, so it is not guessable and does not need a slow
    KDF. It IS compared in constant time, because a timing oracle on the
    comparison is real regardless of the hash.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# DIRECTORY ADMINISTRATION IS NOT A STATION'S JOB (SEC-01). Any station key
# could upsert any account with any role and bcrypt hash, and every station
# then replaced its whole user store with the directory -- so one leaked
# station key was a Commander account on every ground station. Writes now need
# a separate administrator key, configured only where directory administration
# actually happens; without one the write routes refuse.
_ADMIN_KEY = os.environ.get("DT_FLEET_ADMIN_KEY", "")


async def directory_admin(authorization: str = Header(default="")) -> str:
    """Authenticate the directory administrator, or refuse."""
    if not _ADMIN_KEY:
        raise HTTPException(403, "directory administration is not enabled "
                                 "on this server")
    key = authorization.removeprefix("Bearer ").strip()
    if not key or not hmac.compare_digest(_hash_key(key), _hash_key(_ADMIN_KEY)):
        raise HTTPException(401, "invalid administrator credentials")
    return "directory-admin"


# The directory a station receives is SIGNED with a key the station also holds,
# so a man in the middle of the fleet link cannot hand a station an account it
# will then trust (SEC-01). Only the fields a station stores are covered.
_DIRECTORY_KEY = os.environ.get("DT_FLEET_DIRECTORY_KEY", "")
DIRECTORY_SIGNED_FIELDS = ("username", "role", "hash", "disabled",
                           "must_change", "token_epoch")


def directory_signature(accounts: list[dict], key: str) -> str:
    """HMAC-SHA256 over the canonical account list. Mirrored in fleet_sync."""
    import json as _json

    canon = _json.dumps(
        [{k: a.get(k) for k in DIRECTORY_SIGNED_FIELDS}
         for a in sorted(accounts, key=lambda a: str(a.get("username")))],
        sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(key.encode("utf-8"), canon.encode("utf-8"),
                    hashlib.sha256).hexdigest()


async def station(
    x_station_id: str = Header(default=""),
    authorization: str = Header(default=""),
) -> str:
    """Authenticate the calling ground station, or refuse."""
    key = authorization.removeprefix("Bearer ").strip()
    if not x_station_id or not key:
        raise HTTPException(401, "station credentials required")

    async with pool.acquire() as cx:
        row = await cx.fetchrow(
            "SELECT api_key_hash, disabled FROM stations WHERE station_id = $1",
            x_station_id,
        )
    # The same refusal for an unknown station and a wrong key: distinguishing
    # them enumerates which stations exist.
    if row is None or not hmac.compare_digest(row["api_key_hash"], _hash_key(key)):
        _log.warning("station rejected", extra={"station_id": x_station_id})
        raise HTTPException(401, "invalid station credentials")
    if row["disabled"]:
        raise HTTPException(403, "station disabled")

    async with pool.acquire() as cx:
        await cx.execute(
            "UPDATE stations SET last_seen_utc = now() WHERE station_id = $1",
            x_station_id,
        )
    return x_station_id


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

class Record(BaseModel):
    record_uuid: str
    kind: str
    created_utc: str
    payload: dict = Field(default_factory=dict)


class IngestRequest(BaseModel):
    station_id: str
    schema_version: int = 1
    records: list[Record] = Field(default_factory=list, max_length=500)


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _ts(v: Any) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


class DirectoryEntry(BaseModel):
    """One person, as the centre holds them.

    `hash` is a bcrypt digest. The API accepts a hash and never a password:
    hashing belongs where the password is typed, and an endpoint that took a
    plaintext password would put one on the wire on the way to a store that
    exists specifically so that never happens.
    """

    username: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=64)
    hash: str = Field(min_length=1, max_length=255)
    disabled: bool = False
    must_change: bool = True
    token_epoch: int = 0
    full_name: str | None = None


@app.get("/api/v1/directory")
async def directory(sid: str = Depends(station)) -> dict:
    """The whole directory, for a station to cache and verify against.

    Station-authenticated, not public: the rows carry bcrypt hashes, and while
    a bcrypt hash is not a password it is an offline-attackable artefact and
    has no business being readable by anything that has not proved it is a
    ground station.
    """
    async with pool.acquire() as cx:
        rows = await cx.fetch(
            "SELECT username, role, hash, disabled, must_change, token_epoch,"
            "       full_name, updated_utc "
            "FROM directory ORDER BY username"
        )
    _log.info("directory served", extra={"station": sid, "accounts": len(rows)})
    accounts = [dict(r) for r in rows]
    return {
        "accounts": accounts,
        # The station replaces its cache wholesale, so it needs to know the
        # answer is complete rather than a page of it.
        "complete": True,
        "count": len(rows),
        "signature": (directory_signature(accounts, _DIRECTORY_KEY)
                      if _DIRECTORY_KEY else None),
    }


@app.post("/api/v1/directory")
async def directory_upsert(entry: DirectoryEntry,
                           admin: str = Depends(directory_admin)) -> dict:
    """Create or update one account, centrally.

    Upsert rather than insert: re-sending an unchanged entry is how a station
    recovers from a lost acknowledgement, exactly as with flight records, and
    it must land on the same row rather than failing or duplicating.
    """
    async with pool.acquire() as cx:
        await cx.execute(
            """INSERT INTO directory
                   (username, role, hash, disabled, must_change, token_epoch,
                    full_name, updated_utc)
               VALUES ($1, $2, $3, $4, $5, $6, $7, now())
               ON CONFLICT (username) DO UPDATE SET
                   role = EXCLUDED.role,
                   hash = EXCLUDED.hash,
                   disabled = EXCLUDED.disabled,
                   must_change = EXCLUDED.must_change,
                   token_epoch = EXCLUDED.token_epoch,
                   full_name = EXCLUDED.full_name,
                   updated_utc = now()
            """,
            entry.username, entry.role, entry.hash, entry.disabled,
            entry.must_change, entry.token_epoch, entry.full_name,
        )
    _log.info("directory entry written",
              extra={"by": admin, "username": entry.username,
                     "role": entry.role})
    return {"ok": True, "username": entry.username}


@app.post("/api/v1/ingest")
async def ingest(req: IngestRequest, sid: str = Depends(station)) -> dict:
    """Accept a batch of station records. Idempotent by record_uuid.

    Returns the uuids actually written. The station marks ONLY those as
    synced, so a partial acceptance retries the remainder rather than
    silently dropping it -- assuming success from a 200 is how a batch
    disappears.
    """
    if req.station_id != sid:
        raise HTTPException(403, "station_id does not match the credentials")

    accepted: list[str] = []
    async with pool.acquire() as cx:
        for rec in req.records:
            if rec.kind != "flight_record":
                continue
            p = rec.payload
            try:
                await cx.execute(
                    """
                    INSERT INTO flight_records (
                        record_uuid, station_id, engine_key, aircraft_id,
                        recorded_utc, flight_hours, altitude_ft, oat_c,
                        airspeed_kmh, throttle_pct, cht_max_c, cht_spread_c,
                        egt_max_c, egt_spread_c, oil_pressure_psi,
                        oil_temperature_c, coolant_temperature_c,
                        fuel_flow_lph, power_kw, health_chi, payload
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                        $16,$17,$18,$19,$20,$21
                    )
                    ON CONFLICT (record_uuid) DO NOTHING
                    """,
                    rec.record_uuid, sid, p.get("engine_key"),
                    p.get("aircraft_id"),
                    _ts(p.get("recorded_utc") or rec.created_utc),
                    *[_num(p.get(k)) for k in _NUMERIC],
                    json.dumps(p, default=str),
                )
                accepted.append(rec.record_uuid)
            except Exception as exc:  # noqa: BLE001
                # One bad record must not reject the batch: the station would
                # retry the whole thing for ever and never make progress.
                _log.exception("record rejected",
                               extra={"record_uuid": rec.record_uuid,
                                      "error": str(exc)})

    _log.info("ingest", extra={"station_id": sid, "offered": len(req.records),
                               "accepted": len(accepted)})
    return {"accepted": accepted, "count": len(accepted)}


# ---------------------------------------------------------------------------
# Fleet queries
# ---------------------------------------------------------------------------

@app.get("/api/v1/fleet")
async def fleet(limit: int = 200, sid: str = Depends(station)) -> dict:
    """The roster, from REAL reported flights rather than synthetic lives.

    Station-authenticated (SEC-08). It was readable by anyone who could reach
    the port, and which airframes have weak engines is operationally
    sensitive.
    """
    async with pool.acquire() as cx:
        rows = await cx.fetch(
            """
            SELECT DISTINCT ON (aircraft_id)
                   aircraft_id, station_id, engine_key, recorded_utc,
                   flight_hours, health_chi, cht_max_c
            FROM flight_records
            WHERE aircraft_id IS NOT NULL
            ORDER BY aircraft_id, recorded_utc DESC
            LIMIT $1
            """,
            max(1, min(limit, 1000)),
        )
    roster = [dict(r) for r in rows]
    # Worst health first: a planner reads top-down and stops when the day is
    # full, so the engine that can wait must never sit above the one that
    # cannot. The same rule layer4_core/fleet.py applies at station scale.
    roster.sort(key=lambda r: (r.get("health_chi") is None,
                               r.get("health_chi") or 1.0))
    return {"aircraft": len(roster), "roster": roster}


@app.get("/api/v1/stations")
async def stations(admin: str = Depends(directory_admin)) -> dict:
    """Registered stations and when each was last seen. Administrator only
    (SEC-08): the list maps the ground-station estate."""
    async with pool.acquire() as cx:
        rows = await cx.fetch(
            "SELECT station_id, name, disabled, first_seen_utc, last_seen_utc, "
            "(SELECT COUNT(*) FROM flight_records f "
            " WHERE f.station_id = s.station_id) AS records "
            "FROM stations s ORDER BY station_id"
        )
    return {"stations": [dict(r) for r in rows]}


@app.get("/healthz")
async def healthz() -> dict:
    """Reachable AND able to reach its database -- not merely listening."""
    try:
        async with pool.acquire() as cx:
            await cx.fetchval("SELECT 1")
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        # The exception text stays in the log; the caller learns only that the
        # database is unreachable, not its driver's error or connection string
        # (SEC-08).
        _log.error("health check: database unreachable",
                   extra={"error": type(exc).__name__})
        raise HTTPException(503, "database unreachable") from exc


# ---------------------------------------------------------------------------

def main() -> None:
    import uvicorn
    # Loopback by default (SEC-08); a deployment binds a real interface on
    # purpose, behind TLS.
    host = os.environ.get("DT_FLEET_HOST", "127.0.0.1")
    port = int(os.environ.get("DT_FLEET_PORT", "8100"))
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
