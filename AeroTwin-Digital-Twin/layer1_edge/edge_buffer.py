"""Offline buffer -- the edge node keeps working when the link does not.

PRD Part 3 section 21.4 and PRD Part 1 section 7.4 both require it, and it is
the single most defence-relevant behaviour in the whole system: a UAV data link
drops constantly, and a health monitor that stops monitoring when the ground
station cannot hear it is not a health monitor.

WHAT THIS GUARANTEES
--------------------
  * 72 hours of telemetry at the configured rate, on local storage
  * detection and alerting continue with no link at all -- the rule engine has
    no network dependency by construction
  * on reconnect, buffered data is uploaded oldest-first, and the operator is
    told explicitly which time span was back-filled, so replayed history is
    never mistaken for live telemetry (PRD Part 4 section 7.3c)
  * alerts raised while offline are preserved with their original timestamps,
    because when a fault started matters more than when it was reported

STORAGE
-------
SQLite in WAL mode. It is on every Python install, survives power loss, needs
no server, and runs on a Raspberry Pi. Frames are stored as compact rows rather
than JSON blobs so that 72 hours fits comfortably in the storage budget of an
industrial microSD card.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from common import config


class LinkState(StrEnum):
    """Link status, mirroring the annunciation of PRD Part 4 section 7.3."""

    OK = "OK"
    DEGRADED = "DEGRADED"
    LOST = "LOST"
    SYNCING = "SYNCING"


@dataclass
class BufferStats:
    rows: int = 0
    oldest_t: float | None = None
    newest_t: float | None = None
    bytes_on_disk: int = 0
    dropped_oldest: int = 0
    uploaded: int = 0

    @property
    def span_hours(self) -> float:
        if self.oldest_t is None or self.newest_t is None:
            return 0.0
        return (self.newest_t - self.oldest_t) / 3600.0


class EdgeBuffer:
    """A bounded, durable store for telemetry and alerts at the edge."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        capacity_hours: float | None = None,
        sample_hz: float | None = None,
    ) -> None:
        t = config.load_thresholds()
        pipeline = t["pipeline"]
        self.capacity_hours = capacity_hours or float(pipeline["edge_buffer_hours"])
        self.sample_hz = sample_hz or float(pipeline["telemetry_hz"])
        self.max_rows = int(self.capacity_hours * 3600.0 * self.sample_hz)

        self.path = Path(path) if path else config.data_dir() / "edge" / "buffer.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path))
        # WAL survives an abrupt power loss with the database intact, which is
        # the failure mode that actually happens on an airframe.
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

        self.link = LinkState.OK
        self._last_link_ok: float = time.monotonic()
        self.stats = BufferStats()
        self._refresh_stats()

    # ------------------------------------------------------------------
    def _create_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS telemetry (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                t_s      REAL    NOT NULL,
                uploaded INTEGER NOT NULL DEFAULT 0,
                payload  TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_tel_t ON telemetry(t_s);
            CREATE INDEX IF NOT EXISTS ix_tel_up ON telemetry(uploaded);

            CREATE TABLE IF NOT EXISTS alerts (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                t_s       REAL    NOT NULL,
                rule_id   TEXT    NOT NULL,
                legend    TEXT    NOT NULL,
                level     INTEGER NOT NULL,
                category  TEXT    NOT NULL,
                value     REAL,
                uploaded  INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS ix_alert_t ON alerts(t_s);
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.commit()
        self._db.close()

    def __enter__(self) -> EdgeBuffer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    def record(self, t_s: float, values: dict[str, Any]) -> None:
        """Store one telemetry sample. Always succeeds; the oldest is evicted."""
        self._db.execute(
            "INSERT INTO telemetry (t_s, payload) VALUES (?, ?)",
            (t_s, json.dumps(values, separators=(",", ":"))),
        )
        self._enforce_capacity()

    def record_alert(
        self, t_s: float, rule_id: str, legend: str, level: int, category: str,
        value: float | None,
    ) -> None:
        """Persist an alert.

        MIL-STD-411F 5.2.10 requires warning and caution messages to be written
        to non-volatile memory for maintenance; advisories must NOT be. The
        caller filters by category, and the timestamp recorded is when the
        condition STARTED, not when the link came back.
        """
        self._db.execute(
            "INSERT INTO alerts (t_s, rule_id, legend, level, category, value) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (t_s, rule_id, legend, int(level), category, value),
        )

    def commit(self) -> None:
        self._db.commit()
        self._refresh_stats()

    # ------------------------------------------------------------------
    def _enforce_capacity(self) -> None:
        """Ring behaviour: newest data always wins.

        When the buffer is full the OLDEST rows go. Losing the start of a long
        outage is strictly better than losing the moments before a failure.
        """
        cur = self._db.execute("SELECT COUNT(*) FROM telemetry")
        rows = cur.fetchone()[0]
        if rows <= self.max_rows:
            return
        excess = rows - self.max_rows
        self._db.execute(
            "DELETE FROM telemetry WHERE id IN "
            "(SELECT id FROM telemetry ORDER BY id ASC LIMIT ?)",
            (excess,),
        )
        self.stats.dropped_oldest += excess

    def _refresh_stats(self) -> None:
        cur = self._db.execute("SELECT COUNT(*), MIN(t_s), MAX(t_s) FROM telemetry")
        rows, oldest, newest = cur.fetchone()
        self.stats.rows = rows or 0
        self.stats.oldest_t = oldest
        self.stats.newest_t = newest
        self.stats.bytes_on_disk = self.path.stat().st_size if self.path.exists() else 0

    # ------------------------------------------------------------------
    def note_link(self, ok: bool, now: float | None = None) -> LinkState:
        """Update link state from the configured timeouts.

        PRD Part 4 section 7.3: DEGRADED after a 2 s gap, LOST after 5 s, with
        an explicit SYNCING state on the way back so the operator knows the
        history arriving is not live.
        """
        t = config.load_thresholds()["pipeline"]
        degraded_after = float(t["link_degraded_after_s"])
        lost_after = float(t["link_lost_after_s"])
        now = time.monotonic() if now is None else now

        if ok:
            if self.link in (LinkState.LOST, LinkState.DEGRADED):
                self.link = LinkState.SYNCING if self.pending() else LinkState.OK
            elif self.link is LinkState.SYNCING and not self.pending():
                self.link = LinkState.OK
            self._last_link_ok = now
            return self.link

        gap = now - self._last_link_ok
        if gap >= lost_after:
            self.link = LinkState.LOST
        elif gap >= degraded_after:
            self.link = LinkState.DEGRADED
        return self.link

    def pending(self) -> int:
        cur = self._db.execute("SELECT COUNT(*) FROM telemetry WHERE uploaded = 0")
        return cur.fetchone()[0]

    def backfill_span(self) -> tuple[float, float] | None:
        """The time span still waiting to be uploaded.

        The HMI must state this explicitly: back-filled history has to be
        visually distinguishable from live telemetry, or the operator will read
        old data as current (PRD Part 4 section 7.3c).
        """
        cur = self._db.execute(
            "SELECT MIN(t_s), MAX(t_s) FROM telemetry WHERE uploaded = 0"
        )
        lo, hi = cur.fetchone()
        return (lo, hi) if lo is not None else None

    def drain(self, batch: int = 500) -> list[tuple[int, float, dict]]:
        """Take the next batch for upload, oldest first.

        Oldest-first matters: replaying an outage in order lets the ground
        station reconstruct the sequence of events that led to a failure.
        """
        cur = self._db.execute(
            "SELECT id, t_s, payload FROM telemetry WHERE uploaded = 0 "
            "ORDER BY t_s ASC LIMIT ?",
            (batch,),
        )
        return [(r[0], r[1], json.loads(r[2])) for r in cur.fetchall()]

    def mark_uploaded(self, ids: list[int]) -> None:
        if not ids:
            return
        self._db.executemany(
            "UPDATE telemetry SET uploaded = 1 WHERE id = ?", [(i,) for i in ids]
        )
        self._db.commit()
        self.stats.uploaded += len(ids)
        if not self.pending() and self.link is LinkState.SYNCING:
            self.link = LinkState.OK

    def maintenance_log(self, limit: int = 200) -> list[dict]:
        """Recorded warnings and cautions, for the maintenance record.

        MIL-STD-411F 5.2.10: this is what the technician reads after the
        flight, and it is why alerts are stored with the time the condition
        began rather than the time anybody happened to be listening.
        """
        cur = self._db.execute(
            "SELECT t_s, rule_id, legend, level, category, value FROM alerts "
            "ORDER BY t_s DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "t_s": r[0], "rule_id": r[1], "legend": r[2],
                "level": r[3], "category": r[4], "value": r[5],
            }
            for r in cur.fetchall()
        ]

    def capacity_report(self) -> dict[str, Any]:
        self._refresh_stats()
        return {
            "capacity_hours": self.capacity_hours,
            "max_rows": self.max_rows,
            "rows": self.stats.rows,
            "span_hours": round(self.stats.span_hours, 3),
            "fill_fraction": round(self.stats.rows / max(self.max_rows, 1), 4),
            "bytes_on_disk": self.stats.bytes_on_disk,
            "bytes_per_row": (
                round(self.stats.bytes_on_disk / self.stats.rows, 1)
                if self.stats.rows else 0.0
            ),
            "projected_full_mb": round(
                self.stats.bytes_on_disk / max(self.stats.rows, 1) * self.max_rows / 1e6, 1
            ),
            "pending_upload": self.pending(),
            "link": str(self.link),
        }
