"""Flight history that survives a restart, and the trend built from it.

WHY THIS EXISTS
---------------
The ground station kept nothing. Health, degradation and the stabilised cruise
datum all lived in memory and vanished when the process stopped. The edge node
has a 72-hour SQLite buffer; the GCS had nothing at all.

That is not a small omission, because the problem statement asks for "life
cycle management" and "mission-wise health reports", and DEV-141 already
captures the one reading a flight contributes to a trend -- and then dropped
it. A datum captured once per flight and never compared with the next flight is
the *cost* of trend monitoring without the *benefit*.

WHAT ENGINE CONDITION TREND MONITORING ACTUALLY IS
--------------------------------------------------
ECTM is not "plot the temperature". It is: take the SAME reading at the SAME
condition once per flight, and watch it drift over months. The discipline is
entirely in the words "same condition" -- a cylinder head is hotter on a hot
day at low airspeed, and reading that as engine deterioration is how a trend
programme produces false findings and gets ignored.

So this module does two things and refuses to do a third:

  * it stores each flight's stabilised datum together with the CONDITIONS it
    was taken at, because a reading without its condition cannot be compared;
  * it reports drift against the FIRST flight, which is the baseline an engine
    is measured against after overhaul;
  * it REFUSES to compare two flights whose conditions differ by more than a
    band, and says which one differed, rather than returning a difference that
    is mostly weather.

WHY SQLITE AND NOT DUCKDB OR A TIME-SERIES SERVER
-------------------------------------------------
This table gains ONE ROW PER FLIGHT. Over an engine's 1,200-hour life at a few
hours per sortie that is a few hundred rows; over a fleet, a few thousand.
DuckDB's columnar scan and InfluxDB's compression both start paying at a
million rows and both cost a dependency -- and docs/INDIGENISATION.md makes a
measured claim about the dependency closure. `sqlite3` is in the standard
library, needs no server to fail at an inconvenient moment, and is one file an
operator can copy off a ground station onto a memory stick.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import config

_log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# How far two flights' conditions may differ and still be comparable. These
# are deliberately tight: the whole value of a trend is that the difference it
# shows is the ENGINE, and every unit of slack here is weather leaking into
# that number.
COMPARABLE_BAND = {
    "altitude_ft": 1500.0,
    "oat_c": 12.0,
    "airspeed_kmh": 40.0,
    "throttle_pct": 8.0,
}

# The measurements a trend is built from. Everything else in the datum is a
# condition, not a reading.
TRENDED = (
    "cht_max_c", "cht_spread_c", "egt_max_c", "egt_spread_c",
    "oil_pressure_psi", "oil_temperature_c", "coolant_temperature_c",
    "fuel_flow_lph", "power_kw",
)

_DDL = """
CREATE TABLE IF NOT EXISTS flights (
    flight_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_utc  TEXT    NOT NULL,
    engine_key    TEXT    NOT NULL,
    aircraft_id   TEXT,
    flight_hours  REAL,
    altitude_ft   REAL, oat_c REAL, airspeed_kmh REAL,
    throttle_pct  REAL, rpm REAL, manifold_pressure_bar REAL,
    cht_max_c REAL, cht_spread_c REAL, egt_max_c REAL, egt_spread_c REAL,
    oil_pressure_psi REAL, oil_temperature_c REAL, coolant_temperature_c REAL,
    fuel_flow_lph REAL, power_kw REAL,
    health_chi    REAL,
    -- The SUBSYSTEM indices, not just the overall figure. The post-flight
    -- report shows "change since previous flight" per subsystem, and one
    -- number cannot answer that: an engine whose cooling fell while its
    -- lubrication improved has a flat chi and two findings.
    health_json   TEXT,
    events_json   TEXT,
    schema_version INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_flights_engine ON flights(engine_key, flight_id);
"""

_COLUMNS = (
    "altitude_ft", "oat_c", "airspeed_kmh", "throttle_pct", "rpm",
    "manifold_pressure_bar", *TRENDED,
)


@dataclass
class Comparison:
    """One flight measured against the baseline, or the reason it was not."""

    flight_id: int
    recorded_utc: str
    flight_hours: float | None
    comparable: bool
    reason: str
    deltas: dict[str, float]


class FlightHistory:
    """Append-only record of what each flight contributed to the trend."""

    def __init__(self, path: Path | str | None = None) -> None:
        if path is None:
            path = Path(config.data_dir()) / "history" / "flights.db"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as cx:
            cx.executescript(_DDL)
            self._migrate(cx)

    # The columns _DDL declares, so a database created by an older build can be
    # brought up to it. Every entry must be nullable or carry a DEFAULT --
    # SQLite cannot add a NOT NULL column without one to an existing table.
    _ADDED_COLUMNS = {
        "health_json": "TEXT",
    }

    def _migrate(self, cx: sqlite3.Connection) -> None:
        """Add columns a previous version of this file did not have.

        CREATE TABLE IF NOT EXISTS DOES NOTHING WHEN THE TABLE EXISTS. Adding a
        column to _DDL therefore has no effect on any database already on disk,
        and the next INSERT fails with

            sqlite3.OperationalError: table flights has no column named X

        which is exactly what happened: `health_json` was added for the report's
        per-subsystem change column, every existing ground station started
        refusing to record flights, and every test passed because tests build
        their database fresh in a tmp_path.

        So the schema is reconciled at open rather than assumed.
        """
        have = {r["name"] for r in cx.execute("PRAGMA table_info(flights)")}
        if not have:
            return                        # brand new; _DDL just built it
        for name, decl in self._ADDED_COLUMNS.items():
            if name not in have:
                cx.execute(f"ALTER TABLE flights ADD COLUMN {name} {decl}")
                _log.warning("flight history schema updated",
                             extra={"column": name, "path": str(self.path)})

    def _connect(self) -> sqlite3.Connection:
        cx = sqlite3.connect(self.path, timeout=5.0)
        cx.row_factory = sqlite3.Row
        # WAL so a reader (the console asking for a trend) never blocks the
        # writer (a flight finishing), which on a ground station is a real
        # concurrency rather than a theoretical one.
        cx.execute("PRAGMA journal_mode=WAL")
        return cx

    # ------------------------------------------------------------------
    def record(
        self,
        cruise: dict[str, Any] | None,
        *,
        engine_key: str,
        aircraft_id: str | None = None,
        flight_hours: float | None = None,
        health_chi: float | None = None,
        health: dict | None = None,
        events: list | None = None,
    ) -> int | None:
        """Store one flight's contribution. Returns its id, or None.

        A flight that never stabilised contributes NOTHING rather than a
        best-effort average. DEV-141 settled that: a number that is not
        comparable with the next flight's number is worse than its absence,
        because it will be plotted anyway.
        """
        if not cruise:
            _log.info("flight recorded no stabilised cruise datum; "
                      "nothing to trend", extra={"engine": engine_key})
            return None

        row: dict[str, Any] = {c: cruise.get(c) for c in _COLUMNS}
        row.update(
            recorded_utc=datetime.now(timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"),
            engine_key=engine_key,
            aircraft_id=aircraft_id,
            flight_hours=flight_hours,
            health_chi=health_chi,
            # Only the numeric subsystem indices. The health block also carries
            # `band` and `action`, which are strings derived from chi and would
            # make a nonsense of a subtraction next flight.
            health_json=json.dumps(
                {k: v for k, v in (health or {}).items()
                 if isinstance(v, (int, float))
                 and k not in ("chi", "chi_raw")},
                default=str),
            events_json=json.dumps(events or [], default=str),
            schema_version=SCHEMA_VERSION,
        )
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._lock, self._connect() as cx:
            cur = cx.execute(
                f"INSERT INTO flights ({cols}) VALUES ({marks})",
                tuple(row.values()),
            )
            fid = int(cur.lastrowid or 0)
        _log.info("flight recorded for trending",
                  extra={"flight_id": fid, "engine": engine_key,
                         "flight_hours": flight_hours})
        return fid

    # ------------------------------------------------------------------
    def previous_health(self, engine_key: str | None = None) -> dict:
        """The most recent flight's subsystem indices, for a change column.

        The flight being reported has not been written yet at export time, so
        the newest row IS the previous flight. Returns {} when there is no
        history -- a first flight has nothing to change from, and a dash says
        that better than a zero does.
        """
        q = "SELECT health_json FROM flights"
        args: tuple = ()
        if engine_key:
            q += " WHERE engine_key = ?"
            args = (engine_key,)
        q += " ORDER BY flight_id DESC LIMIT 1"
        try:
            with self._connect() as cx:
                row = cx.execute(q, args).fetchone()
        except sqlite3.Error:
            return {}
        if not row or not row["health_json"]:
            return {}
        try:
            return dict(json.loads(row["health_json"]))
        except (TypeError, ValueError):
            return {}

    # ------------------------------------------------------------------
    def flights(self, engine_key: str | None = None, limit: int = 200) -> list[dict]:
        q = "SELECT * FROM flights"
        args: tuple = ()
        if engine_key:
            q += " WHERE engine_key = ?"
            args = (engine_key,)
        q += " ORDER BY flight_id DESC LIMIT ?"
        with self._connect() as cx:
            rows = [dict(r) for r in cx.execute(q, (*args, limit))]
        # The NEWEST `limit` flights, returned oldest-first. Selected oldest-
        # first, a store past `limit` flights silently stopped admitting new
        # ones: with 205 on record the trend still ended at flight 200 (RT-04).
        return rows[::-1]

    def _first(self, engine_key: str | None = None) -> dict | None:
        """The first flight ever recorded for this engine: the trend baseline."""
        q = "SELECT * FROM flights"
        args: tuple = ()
        if engine_key:
            q += " WHERE engine_key = ?"
            args = (engine_key,)
        q += " ORDER BY flight_id ASC LIMIT 1"
        with self._connect() as cx:
            r = cx.execute(q, args).fetchone()
        return dict(r) if r is not None else None

    def _count(self, engine_key: str | None = None) -> int:
        q = "SELECT COUNT(*) FROM flights"
        args: tuple = ()
        if engine_key:
            q += " WHERE engine_key = ?"
            args = (engine_key,)
        with self._connect() as cx:
            return int(cx.execute(q, args).fetchone()[0])

    # ------------------------------------------------------------------
    def trend(self, engine_key: str | None = None, limit: int = 200) -> dict:
        """Drift against the baseline flight, with weather excluded.

        The baseline is the FIRST recorded flight -- an engine is measured
        against its own as-delivered or post-overhaul condition, not against a
        fleet average, because manufacturing spread between engines is larger
        than the drift being looked for.
        """
        base = self._first(engine_key)
        if base is None:
            return {"baseline": None, "comparisons": [],
                    "trended": list(TRENDED),
                    "note": "no flights recorded yet"}
        # Baseline: the FIRST flight ever recorded. Comparisons: the most
        # recent `limit` flights after it, so the trend keeps moving once the
        # store holds more than `limit` flights (RT-04).
        rows = [base] + [r for r in self.flights(engine_key, limit)
                         if int(r["flight_id"]) != int(base["flight_id"])]
        out: list[Comparison] = []
        for r in rows[1:]:
            ok, why = self._comparable(base, r)
            deltas: dict[str, float] = {}
            if ok:
                for k in TRENDED:
                    if isinstance(r.get(k), (int, float)) and \
                       isinstance(base.get(k), (int, float)):
                        deltas[k] = round(float(r[k]) - float(base[k]), 3)
            out.append(Comparison(
                flight_id=int(r["flight_id"]),
                recorded_utc=str(r["recorded_utc"]),
                flight_hours=r.get("flight_hours"),
                comparable=ok, reason=why, deltas=deltas,
            ))

        usable = [c for c in out if c.comparable]
        return {
            "baseline": {
                "flight_id": int(base["flight_id"]),
                "recorded_utc": base["recorded_utc"],
                "flight_hours": base.get("flight_hours"),
                "conditions": {k: base.get(k) for k in
                               ("altitude_ft", "oat_c", "airspeed_kmh",
                                "throttle_pct")},
            },
            "trended": list(TRENDED),
            "comparable_band": COMPARABLE_BAND,
            "flights_recorded": self._count(engine_key),
            "flights_comparable": len(usable),
            "comparisons": [c.__dict__ for c in out],
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _comparable(base: dict, other: dict) -> tuple[bool, str]:
        """Same condition, or say which one differed and by how much."""
        for key, band in COMPARABLE_BAND.items():
            a, b = base.get(key), other.get(key)
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                return False, f"{key} missing on one of the two flights"
            if abs(float(a) - float(b)) > band:
                return (
                    False,
                    f"{key} differs by {abs(float(a) - float(b)):.1f} "
                    f"(band {band}); the difference would be weather, "
                    f"not the engine",
                )
        return True, "same condition"
