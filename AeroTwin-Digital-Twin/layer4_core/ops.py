"""Squadron operations: aircraft, missions, defects, releases and the logbook.

The digital twin answers "what condition is this engine in and will it
complete the mission". Until this module, nobody could act on the answer: the
station flew one aircraft, the sortie started itself whenever somebody signed
in, and the four roles differed mostly in which pages they could read.

A squadron works as a chain of decisions, each owned by one person:

    COMMANDER   plans a mission and allots a SERVICEABLE aircraft and an
                operator to it -- informed by the twin's predicted mission
                reliability for each candidate aircraft.
    OPERATOR    prepares the allotted aircraft on the ground station, runs the
                pre-flight checklist, starts the engine from cold, launches
                once the engine is warm and the twin raises no warning, can
                recall it, and debriefs after shutdown.
    MAINTAINER  signs the inspection and maintenance release without which an
                aircraft cannot be allotted, rectifies defects (the work
                reaches that aircraft's engine twin) and runs the engine on
                the ground to verify it.
    ENGINEER    dispositions the defects the TWIN raises after each engine
                run -- confirm, defer with an hours limit, or no fault found --
                and imposes operating limitations on an aircraft.

This module is the record of those decisions and the rules between them. It
does not run engines: the API loads the aircraft into the live twin and tells
this store what happened. Everything is kept in one SQLite file so the state
of the squadron survives a restart of the station, as a technical log does.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from common import config

# Mission states, in the order a mission passes through them.
PLANNED = "PLANNED"                  # created by the commander, not yet allotted
APPROVED = "APPROVED"                # aircraft and operator allotted, authorised
PREFLIGHT = "PREFLIGHT"              # aircraft on the GCS, checks in progress
ENGINE_RUNNING = "ENGINE_RUNNING"    # started, warming up, holding for launch
AIRBORNE = "AIRBORNE"
RTB = "RTB"                          # recalled; returning to base
ABORTING = "ABORTING"                # shut down on the ground before launch
AWAITING_DEBRIEF = "AWAITING_DEBRIEF"  # engine stopped; operator to debrief
COMPLETED = "COMPLETED"
ABORTED = "ABORTED"
CANCELLED = "CANCELLED"

OPEN_MISSION = (APPROVED, PREFLIGHT, ENGINE_RUNNING, AIRBORNE, RTB, ABORTING,
                AWAITING_DEBRIEF)
ON_STATION = (PREFLIGHT, ENGINE_RUNNING, AIRBORNE, RTB, ABORTING)
ENGINE_ON = (ENGINE_RUNNING, AIRBORNE, RTB, ABORTING)

# Aircraft states, derived -- never stored, so they cannot disagree with the
# record they are derived from.
SERVICEABLE = "SERVICEABLE"
AWAITING_INSPECTION = "AWAITING INSPECTION"
UNSERVICEABLE = "UNSERVICEABLE"
ON_GCS = "ON GCS"
ENGINE_RUNNING_A = "ENGINE RUNNING"
FLYING = "FLYING"
GROUND_RUN = "GROUND RUN"

# Defect states.
D_OPEN = "OPEN"              # raised, awaiting engineering review or rectification
D_CONFIRMED = "CONFIRMED"    # engineer confirmed: rectify before flight if grounding
D_DEFERRED = "DEFERRED"      # engineer concession: may fly until an hours limit
D_CLOSED = "CLOSED"          # rectified, or no fault found

SEVERITIES = ("ADVISORY", "CAUTION", "WARNING", "EMERGENCY")


class OpsError(ValueError):
    """A request the squadron's rules refuse. ``status`` is the HTTP code."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_fleet() -> dict[str, Any]:
    path = config.config_dir() / "fleet.yaml"
    import yaml
    with path.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    tails = [a["tail"] for a in cfg.get("aircraft", [])]
    if len(tails) != len(set(tails)) or not tails:
        raise config.ConfigError("fleet.yaml: aircraft tails must be present and unique")
    for a in cfg["aircraft"]:
        if a["engine_key"] not in config.available_engines():
            raise config.ConfigError(
                f"fleet.yaml: {a['tail']} names engine '{a['engine_key']}', "
                "which has no definition in configs/engines/")
    return cfg


_SCHEMA = """
CREATE TABLE IF NOT EXISTS aircraft (
    tail TEXT PRIMARY KEY,
    engine_key TEXT,
    released INTEGER NOT NULL DEFAULT 0,
    release_by TEXT, release_utc TEXT, release_note TEXT,
    limitations TEXT NOT NULL DEFAULT '{}',
    last_health TEXT NOT NULL DEFAULT '{}',
    pending_maintenance TEXT NOT NULL DEFAULT '[]',
    sorties INTEGER NOT NULL DEFAULT 0,
    ground_runs INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL, type TEXT NOT NULL, status TEXT NOT NULL,
    environment TEXT NOT NULL, duration_h REAL NOT NULL,
    altitude_ft REAL NOT NULL, throttle_pct REAL NOT NULL,
    area TEXT, launch_utc TEXT, priority TEXT, notes TEXT,
    created_by TEXT, created_utc TEXT,
    approved_by TEXT, approved_utc TEXT,
    tail TEXT, operator TEXT, assessment TEXT,
    preflight TEXT, prepared_utc TEXT, started_utc TEXT, launched_utc TEXT,
    landed_utc TEXT, completed_utc TEXT,
    outcome TEXT, debrief TEXT, engine_hours REAL,
    cancelled_by TEXT, cancel_reason TEXT
);
CREATE TABLE IF NOT EXISTS defects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tail TEXT NOT NULL, mission_id TEXT,
    source TEXT NOT NULL, raised_by TEXT, raised_role TEXT, raised_utc TEXT,
    description TEXT NOT NULL, severity TEXT NOT NULL,
    grounding INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL, action_id TEXT, evidence TEXT,
    disposition TEXT, disposition_note TEXT, disposed_by TEXT, disposed_utc TEXT,
    defer_until_hours REAL,
    rectified_by TEXT, rectified_utc TEXT, rectification TEXT
);
CREATE TABLE IF NOT EXISTS logbook (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tail TEXT, utc TEXT NOT NULL, kind TEXT NOT NULL,
    by TEXT, role TEXT, text TEXT NOT NULL, data TEXT
);
CREATE TABLE IF NOT EXISTS station (
    key TEXT PRIMARY KEY, value TEXT
);
"""


def _clip(text: str, n: int) -> str:
    """Shorten at a word boundary, and say so: "... an as-" read as a typo."""
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut}…"


class OpsStore:
    """The squadron's record. Thread-safe; one SQLite file."""

    def __init__(self, path: Path | str | None = None,
                 fleet: dict[str, Any] | None = None) -> None:
        self.fleet = fleet or load_fleet()
        self.path = Path(path) if path else config.data_dir() / "ops" / "squadron.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._health: dict[str, dict] = {}      # tail -> last known condition
        self._health_flushed: dict[str, float] = {}
        with self._cx() as cx:
            cx.executescript(_SCHEMA)
            for a in self.fleet["aircraft"]:
                cx.execute("INSERT OR IGNORE INTO aircraft (tail) VALUES (?)", (a["tail"],))
            for r in cx.execute("SELECT tail, last_health FROM aircraft"):
                self._health[r["tail"]] = json.loads(r["last_health"] or "{}")
            # What is known of an aircraft before its engine has ever been on
            # this station: the hours its log came with. Its CONDITION is not
            # known until the twin has run it, and is not invented here.
            for a in self.fleet["aircraft"]:
                h = self._health.get(a["tail"], {})
                if "engine_hours" in h:
                    continue
                hrs = float(a.get("initial_engine_hours") or 0.0)
                tbo = float(config.load_engine(a["engine_key"])["ratings"]["tbo_hours"])
                h.update(engine_hours=hrs, tbo_hours=tbo,
                         hours_since_inspection=hrs % self.inspection_interval(),
                         tbo_remaining_hours=max(0.0, tbo - hrs))
                self._health[a["tail"]] = h
                cx.execute("UPDATE aircraft SET last_health=? WHERE tail=?",
                           (json.dumps(h), a["tail"]))

    # ------------------------------------------------------------------ plumbing
    @contextlib.contextmanager
    def _cx(self):
        """One connection per use: committed on success, always closed."""
        cx = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
        cx.row_factory = sqlite3.Row
        try:
            with cx:
                yield cx
        finally:
            cx.close()

    def _log(self, cx, tail: str | None, kind: str, text: str, *, by: str = "system",
             role: str = "system", data: dict | None = None) -> None:
        cx.execute("INSERT INTO logbook (tail, utc, kind, by, role, text, data) "
                   "VALUES (?,?,?,?,?,?,?)",
                   (tail, _now(), kind, by, role, text,
                    json.dumps(data) if data else None))

    def _station(self, cx, key: str) -> str | None:
        r = cx.execute("SELECT value FROM station WHERE key=?", (key,)).fetchone()
        return None if r is None else r["value"]

    def _set_station(self, cx, key: str, value: str | None) -> None:
        cx.execute("INSERT INTO station (key, value) VALUES (?,?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # ------------------------------------------------------------------ config
    def aircraft_cfg(self, tail: str, cx: sqlite3.Connection | None = None) -> dict[str, Any]:
        """The aircraft as configured, with any engine change since applied."""
        for a in self.fleet["aircraft"]:
            if a["tail"] == tail:
                cfg = dict(a)
                break
        else:
            raise OpsError(f"no aircraft {tail!r} in this squadron", 404)
        if cx is None:
            with self._cx() as own:
                r = own.execute("SELECT engine_key FROM aircraft WHERE tail=?",
                                (tail,)).fetchone()
        else:
            r = cx.execute("SELECT engine_key FROM aircraft WHERE tail=?", (tail,)).fetchone()
        if r is not None and r["engine_key"] and r["engine_key"] != cfg["engine_key"]:
            cfg["engine_key"] = r["engine_key"]
            # A different engine is a different engine: it arrives new, not
            # with the hours the airframe's original engine had.
            cfg["engine_changed"] = True
        return cfg

    def fit_engine(self, tail: str, engine_key: str, *, by: str, role: str,
                   note: str = "") -> dict:
        """An engine change: fit another engine definition to this airframe."""
        problems = (config.check_engine(engine_key)
                    if engine_key in config.available_engines()
                    else [f"no engine definition '{engine_key}'"])
        if problems:
            raise OpsError("; ".join(problems), 422)
        with self._lock, self._cx() as cx:
            busy = json.loads(self._station(cx, "busy") or "null")
            if busy and busy.get("tail") == tail:
                raise OpsError(f"{tail} is on the ground station; finish first")
            old = self.aircraft_cfg(tail, cx)["engine_key"]
            if old == engine_key:
                raise OpsError(f"{tail} already has {engine_key}")
            cx.execute("UPDATE aircraft SET engine_key=? WHERE tail=?", (engine_key, tail))
            tbo = float(config.load_engine(engine_key)["ratings"]["tbo_hours"])
            self._set_health_fields(cx, tail, chi=None, band=None, subsystems=None,
                                    inputs=None, advisory=[], assessed_utc=None,
                                    engine_hours=0.0, hours_since_inspection=0.0,
                                    tbo_hours=tbo, tbo_remaining_hours=tbo)
            self._log(cx, tail, "ENGINE_CHANGE",
                      f"Engine changed: {old} removed, {engine_key} fitted"
                      + (f". {note}" if note else ""), by=by, role=role)
            self._unrelease(cx, tail, "Engine change: ground run and inspection required",
                            by=by, role=role)
            return self._aircraft(cx, tail)

    def tails(self) -> list[str]:
        return [a["tail"] for a in self.fleet["aircraft"]]

    def mission_types(self) -> dict[str, dict]:
        return dict(self.fleet.get("mission_types", {}))

    def checklist(self) -> list[str]:
        return list(self.fleet.get("preflight_checklist", []))

    def inspection_interval(self) -> float:
        return float(self.fleet.get("inspection_interval_h", 100.0))

    def simulated_cruise_hours(self) -> float:
        import os
        env = os.environ.get("DT_CRUISE_HOURS", "").strip()
        if env:
            return float(env)
        return float(self.fleet.get("ops", {}).get("simulated_cruise_hours", 0.1))

    # ------------------------------------------------------------------ station
    def active_tail(self) -> str:
        with self._cx() as cx:
            t = self._station(cx, "active_tail")
        return t if t in self.tails() else self.tails()[0]

    def busy(self) -> dict | None:
        """What is occupying the ground station: a mission or a ground run."""
        with self._cx() as cx:
            v = self._station(cx, "busy")
        return json.loads(v) if v else None

    def set_active(self, tail: str) -> None:
        self.aircraft_cfg(tail)
        with self._lock, self._cx() as cx:
            self._set_station(cx, "active_tail", tail)

    def _require_free(self, cx, allow: dict | None = None) -> None:
        v = self._station(cx, "busy")
        busy = json.loads(v) if v else None
        if busy and busy != allow:
            what = (f"mission {busy['id']}" if busy.get("kind") == "mission"
                    else f"a ground run on {busy.get('tail')}")
            raise OpsError(f"the ground station is busy with {what}")

    # ------------------------------------------------------------------ health
    def update_health(self, tail: str, snap: Any, *, force_flush: bool = False) -> None:
        """Keep an aircraft's last-known condition from its twin's snapshot.

        Only ASSESSED values replace the kept ones: a parked engine's withheld
        health must not overwrite the condition its last run measured.
        """
        h = dict(self._health.get(tail, {}))
        health = getattr(snap, "health", None) or {}
        md = (getattr(snap, "twin", None) or {}).get("metadata", {}) or {}
        hist = (getattr(snap, "twin", None) or {}).get("history", {}) or {}
        mission = getattr(snap, "mission", None) or {}
        inputs = mission.get("inputs") or {}
        maint = getattr(snap, "maintenance", None) or {}
        assessment = health.get("assessment") or (getattr(snap, "display", None) or {}).get("assessment") or {}
        # A held assessment contains numeric values, but they are the previous
        # warm, loaded result. Do not refresh its recorded time or overwrite
        # the aircraft's saved assessment while the engine is cold or idle.
        if health.get("chi") is not None and assessment.get("state") in (None, "live"):
            h.update({
                "chi": health.get("chi"), "band": health.get("band"),
                "subsystems": {k: health.get(k) for k in
                               ("thermal", "mechanical", "combustion", "electrical")},
                "assessed_utc": _now(),
            })
            if inputs:
                h["inputs"] = inputs
            h["advisory"] = [
                {k: a.get(k) for k in ("action_id", "name", "severity", "reason",
                                       "due_within_hours")}
                for a in maint.get("actions", [])]
        if md.get("total_flight_hours") is not None:
            h["engine_hours"] = round(float(md["total_flight_hours"]), 3)
        if md.get("tbo_hours") is not None:
            h["tbo_hours"] = md.get("tbo_hours")
        if hist.get("hours_since_inspection") is not None:
            h["hours_since_inspection"] = round(float(hist["hours_since_inspection"]), 3)
        if inputs.get("tbo_remaining_hours") is not None:
            h["tbo_remaining_hours"] = inputs["tbo_remaining_hours"]
        rul = getattr(snap, "rul", None) or {}
        if isinstance(rul, dict) and rul.get("hours") is not None:
            h["rul_hours"] = rul.get("hours")
        h["updated_utc"] = _now()
        with self._lock:
            self._health[tail] = h
            due = force_flush or (time.monotonic() - self._health_flushed.get(tail, 0.0)
                                  >= float(self.fleet.get("ops", {}).get("health_flush_s", 30)))
            if due:
                self._health_flushed[tail] = time.monotonic()
                with self._cx() as cx:
                    cx.execute("UPDATE aircraft SET last_health=? WHERE tail=?",
                               (json.dumps(h), tail))

    def health(self, tail: str) -> dict:
        return dict(self._health.get(tail, {}))

    def _set_health_fields(self, cx, tail: str, **fields) -> None:
        with self._lock:
            h = dict(self._health.get(tail, {}))
            h.update(fields)
            self._health[tail] = h
            cx.execute("UPDATE aircraft SET last_health=? WHERE tail=?", (json.dumps(h), tail))

    # ------------------------------------------------------------------ aircraft
    def _row(self, cx, tail: str) -> sqlite3.Row:
        r = cx.execute("SELECT * FROM aircraft WHERE tail=?", (tail,)).fetchone()
        if r is None:
            raise OpsError(f"no aircraft {tail!r} in this squadron", 404)
        return r

    def _open_defects(self, cx, tail: str) -> list[dict]:
        return [dict(r) for r in cx.execute(
            "SELECT * FROM defects WHERE tail=? AND status != ? ORDER BY id",
            (tail, D_CLOSED))]

    def _grounding(self, cx, tail: str) -> list[str]:
        """Every reason this aircraft may not fly. Empty means none."""
        h = self._health.get(tail, {})
        hours = float(h.get("engine_hours") or 0.0)
        why: list[str] = []
        for d in self._open_defects(cx, tail):
            if d["status"] == D_DEFERRED:
                lim = d.get("defer_until_hours")
                if lim is not None and hours >= float(lim):
                    why.append(f"defect #{d['id']} deferral expired at {lim:.1f} h")
            elif d["grounding"]:
                why.append(f"defect #{d['id']}: {d['description']}")
        hsi = h.get("hours_since_inspection")
        if hsi is not None and float(hsi) >= self.inspection_interval():
            why.append(f"{self.inspection_interval():.0f} h inspection due "
                       f"({float(hsi):.1f} h since the last)")
        tbo = h.get("tbo_remaining_hours")
        if tbo is not None and float(tbo) <= 0.0:
            why.append("TBO reached: engine overhaul due")
        return why

    def aircraft(self, tail: str) -> dict:
        with self._cx() as cx:
            return self._aircraft(cx, tail)

    def _aircraft(self, cx, tail: str) -> dict:
        cfg = self.aircraft_cfg(tail, cx)
        r = self._row(cx, tail)
        busy = json.loads(self._station(cx, "busy") or "null")
        active = self._station(cx, "active_tail") or self.tails()[0]
        m = cx.execute(
            f"SELECT * FROM missions WHERE tail=? AND status IN "
            f"({','.join('?' * len(OPEN_MISSION))}) ORDER BY created_utc DESC LIMIT 1",
            (tail, *OPEN_MISSION)).fetchone()
        grounding = self._grounding(cx, tail)
        status, detail = SERVICEABLE, "released for flight"
        if busy and busy.get("tail") == tail:
            if busy.get("kind") == "ground_run":
                status, detail = GROUND_RUN, "engine ground run in progress"
            elif m is not None and m["status"] in (AIRBORNE, RTB):
                status, detail = FLYING, f"{m['id']} {m['status'].lower()}"
            elif m is not None and m["status"] in ENGINE_ON:
                status, detail = ENGINE_RUNNING_A, f"{m['id']} on the ground, engine running"
            else:
                status, detail = ON_GCS, "on the ground station for pre-flight"
        elif grounding:
            status, detail = UNSERVICEABLE, grounding[0]
        elif not r["released"]:
            status, detail = AWAITING_INSPECTION, "inspection and maintenance release required"
        eng = config.load_engine(cfg["engine_key"])
        return {
            "tail": tail,
            "twin_id": cfg["twin_id"],
            "engine_key": cfg["engine_key"],
            "engine_name": eng["identity"].get("display_name", cfg["engine_key"]),
            "engine_validated": eng["identity"].get("validated", True) is not False,
            "airframe": cfg.get("airframe", ""),
            "status": status,
            "status_detail": detail,
            "grounding": grounding,
            "released": bool(r["released"]),
            "release_by": r["release_by"], "release_utc": r["release_utc"],
            "release_note": r["release_note"],
            "limitations": json.loads(r["limitations"] or "{}"),
            "health": self._health.get(tail, {}),
            "pending_maintenance": json.loads(r["pending_maintenance"] or "[]"),
            "open_defects": self._open_defects(cx, tail),
            "sorties": int(r["sorties"]), "ground_runs": int(r["ground_runs"]),
            "mission": dict(m) if m is not None else None,
            "on_gcs": tail == active,
        }

    def fleet_board(self) -> list[dict]:
        with self._cx() as cx:
            return [self._aircraft(cx, t) for t in self.tails()]

    def serviceable(self, tail: str) -> bool:
        return self.aircraft(tail)["status"] == SERVICEABLE

    def release(self, tail: str, *, by: str, role: str, note: str = "") -> dict:
        """Before-flight inspection done and maintenance release signed."""
        with self._lock, self._cx() as cx:
            a = self._aircraft(cx, tail)
            if a["status"] in (FLYING, ENGINE_RUNNING_A, GROUND_RUN):
                raise OpsError(f"{tail} is running; inspect it after shutdown")
            if a["grounding"]:
                raise OpsError(f"{tail} cannot be released: " + "; ".join(a["grounding"]))
            cx.execute("UPDATE aircraft SET released=1, release_by=?, release_utc=?, "
                       "release_note=? WHERE tail=?", (by, _now(), note, tail))
            self._log(cx, tail, "RELEASE",
                      f"Inspection completed and maintenance release signed. {note}".strip(),
                      by=by, role=role)
            return self._aircraft(cx, tail)

    def _unrelease(self, cx, tail: str, why: str, *, by: str = "system",
                   role: str = "system") -> None:
        r = self._row(cx, tail)
        if r["released"]:
            cx.execute("UPDATE aircraft SET released=0 WHERE tail=?", (tail,))
            self._log(cx, tail, "RELEASE_WITHDRAWN", why, by=by, role=role)

    def set_limitations(self, tail: str, *, by: str, role: str,
                        max_mission_hours: float | None, max_altitude_ft: float | None,
                        note: str) -> dict:
        lim = {k: v for k, v in (("max_mission_hours", max_mission_hours),
                                 ("max_altitude_ft", max_altitude_ft)) if v is not None}
        if lim:
            lim.update(note=note, by=by, utc=_now())
        with self._lock, self._cx() as cx:
            self._row(cx, tail)
            cx.execute("UPDATE aircraft SET limitations=? WHERE tail=?",
                       (json.dumps(lim), tail))
            self._log(cx, tail, "LIMITATION",
                      ("Operating limitations set: " + ", ".join(
                          f"{k.replace('_', ' ')} {v}" for k, v in lim.items()
                          if k.startswith("max_")) + (f" ({note})" if note else ""))
                      if lim else "Operating limitations removed",
                      by=by, role=role, data=lim or None)
            return self._aircraft(cx, tail)

    # ------------------------------------------------------------------ maintenance
    def queue_maintenance(self, tail: str, action_id: str, *, by: str, role: str,
                          repaired: bool | None, note: str) -> dict:
        """Work done on an aircraft that is not on the ground station.

        The engine twin learns it the next time this aircraft is loaded -- the
        next ground run or flight, which is also when the work is verified.
        """
        rec = {"action_id": action_id, "repaired": repaired, "by": by, "note": note,
               "recorded_utc": _now(),
               "health_before": self._before_reading(tail)}
        with self._lock, self._cx() as cx:
            r = self._row(cx, tail)
            q = json.loads(r["pending_maintenance"] or "[]") + [rec]
            cx.execute("UPDATE aircraft SET pending_maintenance=? WHERE tail=?",
                       (json.dumps(q), tail))
            self._after_maintenance(cx, tail, action_id, by=by, role=role, note=note,
                                    applied_live=False)
        return rec

    def _before_reading(self, tail: str) -> dict:
        h = self._health.get(tail, {})
        out = dict(h.get("subsystems") or {})
        out["chi"] = h.get("chi")
        return out

    def take_pending_maintenance(self, tail: str) -> list[dict]:
        with self._lock, self._cx() as cx:
            r = self._row(cx, tail)
            q = json.loads(r["pending_maintenance"] or "[]")
            cx.execute("UPDATE aircraft SET pending_maintenance='[]' WHERE tail=?", (tail,))
        return q

    def record_live_maintenance(self, tail: str, action_id: str, *, by: str, role: str,
                                note: str) -> None:
        with self._lock, self._cx() as cx:
            self._after_maintenance(cx, tail, action_id, by=by, role=role, note=note,
                                    applied_live=True)

    def _after_maintenance(self, cx, tail: str, action_id: str, *, by: str, role: str,
                           note: str, applied_live: bool) -> None:
        name = next((a["name"] for a in config.load_thresholds()["advisory"]["actions"]
                     if a["id"] == action_id), action_id)
        self._log(cx, tail, "MAINTENANCE",
                  f"{action_id} {name} carried out"
                  + ("" if applied_live else " (the twin applies it at the next engine run)")
                  + (f". {note}" if note else ""), by=by, role=role,
                  data={"action_id": action_id})
        # The 100 h inspection includes the oil change; an overhaul restarts all.
        if action_id in ("A1", "A7"):
            self._set_health_fields(cx, tail, hours_since_inspection=0.0)
        self._unrelease(cx, tail, f"Maintenance ({action_id}) done: re-inspect before release",
                        by=by, role=role)

    # ------------------------------------------------------------------ defects
    def raise_defect(self, tail: str, *, source: str, by: str, role: str,
                     description: str, severity: str = "CAUTION", grounding: bool = False,
                     action_id: str | None = None, evidence: str | None = None,
                     mission_id: str | None = None) -> dict:
        if severity not in SEVERITIES:
            raise OpsError(f"severity must be one of {SEVERITIES}", 400)
        if not description.strip():
            raise OpsError("describe the defect", 400)
        with self._lock, self._cx() as cx:
            self._row(cx, tail)
            cur = cx.execute(
                "INSERT INTO defects (tail, mission_id, source, raised_by, raised_role, "
                "raised_utc, description, severity, grounding, status, action_id, evidence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (tail, mission_id, source, by, role, _now(), description.strip()[:400],
                 severity, int(bool(grounding)), D_OPEN, action_id, evidence))
            did = int(cur.lastrowid)
            self._log(cx, tail, "DEFECT_RAISED",
                      f"#{did} [{severity}{', GROUNDING' if grounding else ''}] "
                      f"{description.strip()[:200]} (source: {source})", by=by, role=role)
            if grounding:
                self._unrelease(cx, tail, f"Grounding defect #{did} raised", by=by, role=role)
            return dict(cx.execute("SELECT * FROM defects WHERE id=?", (did,)).fetchone())

    def defect(self, did: int) -> dict:
        with self._cx() as cx:
            r = cx.execute("SELECT * FROM defects WHERE id=?", (did,)).fetchone()
        if r is None:
            raise OpsError(f"no defect #{did}", 404)
        return dict(r)

    def defects(self, tail: str | None = None, *, open_only: bool = False) -> list[dict]:
        q, args = "SELECT * FROM defects", []
        cond = []
        if tail:
            cond.append("tail=?")
            args.append(tail)
        if open_only:
            cond.append("status != ?")
            args.append(D_CLOSED)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        with self._cx() as cx:
            return [dict(r) for r in cx.execute(q + " ORDER BY id DESC", args)]

    def dispose_defect(self, did: int, *, by: str, role: str, disposition: str,
                       note: str, defer_hours: float | None = None,
                       grounding: bool | None = None) -> dict:
        """The engineer's call on a defect: CONFIRM, DEFER or NFF."""
        d = self.defect(did)
        if d["status"] == D_CLOSED:
            raise OpsError(f"defect #{did} is already closed")
        if not note.strip():
            raise OpsError("an engineering disposition must say why", 400)
        with self._lock, self._cx() as cx:
            if disposition == "CONFIRM":
                g = d["grounding"] if grounding is None else int(bool(grounding))
                cx.execute("UPDATE defects SET status=?, grounding=?, disposition=?, "
                           "disposition_note=?, disposed_by=?, disposed_utc=? WHERE id=?",
                           (D_CONFIRMED, g, "CONFIRMED", note, by, _now(), did))
                text = (f"#{did} confirmed{' as GROUNDING' if g else ''}: {note}")
                if g:
                    self._unrelease(cx, d["tail"], f"Defect #{did} confirmed grounding",
                                    by=by, role=role)
            elif disposition == "DEFER":
                if not defer_hours or defer_hours <= 0:
                    raise OpsError("a deferral needs an hours limit", 400)
                hours = float(self._health.get(d["tail"], {}).get("engine_hours") or 0.0)
                until = round(hours + float(defer_hours), 2)
                cx.execute("UPDATE defects SET status=?, grounding=0, disposition=?, "
                           "disposition_note=?, disposed_by=?, disposed_utc=?, "
                           "defer_until_hours=? WHERE id=?",
                           (D_DEFERRED, "DEFERRED", note, by, _now(), until, did))
                text = f"#{did} deferred until {until:.1f} engine hours: {note}"
            elif disposition == "NFF":
                cx.execute("UPDATE defects SET status=?, grounding=0, disposition=?, "
                           "disposition_note=?, disposed_by=?, disposed_utc=? WHERE id=?",
                           (D_CLOSED, "NO FAULT FOUND", note, by, _now(), did))
                text = f"#{did} closed, no fault found: {note}"
            else:
                raise OpsError("disposition must be CONFIRM, DEFER or NFF", 400)
            self._log(cx, d["tail"], "DEFECT_DISPOSITION", text, by=by, role=role)
            return dict(cx.execute("SELECT * FROM defects WHERE id=?", (did,)).fetchone())

    def rectify_defect(self, did: int, *, by: str, role: str, actions: list[str],
                       note: str) -> dict:
        """Close a defect as rectified. The maintenance ACTIONS are applied by
        the caller (to the live twin, or queued) -- this records the closure."""
        d = self.defect(did)
        if d["status"] == D_CLOSED:
            raise OpsError(f"defect #{did} is already closed")
        if not note.strip() and not actions:
            raise OpsError("say what was done", 400)
        with self._lock, self._cx() as cx:
            text = ", ".join(actions) + (f" -- {note}" if note else "") if actions else note
            cx.execute("UPDATE defects SET status=?, rectified_by=?, rectified_utc=?, "
                       "rectification=?, grounding=0 WHERE id=?",
                       (D_CLOSED, by, _now(), text, did))
            self._log(cx, d["tail"], "DEFECT_RECTIFIED", f"#{did} rectified: {text}",
                      by=by, role=role)
            self._unrelease(cx, d["tail"], f"Defect #{did} rectified: re-inspect before release",
                            by=by, role=role)
            return dict(cx.execute("SELECT * FROM defects WHERE id=?", (did,)).fetchone())

    def ground(self, tail: str, *, by: str, role: str, reason: str) -> dict:
        """Declare an aircraft unserviceable. A grounding defect is the record."""
        return self.raise_defect(tail, source=role.replace("ROLE_", ""), by=by, role=role,
                                 description=reason, severity="WARNING", grounding=True)

    # ------------------------------------------------------------------ missions
    def _mission(self, cx, mid: str) -> dict:
        r = cx.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone()
        if r is None:
            raise OpsError(f"no mission {mid}", 404)
        m = dict(r)
        for k in ("assessment", "preflight", "debrief"):
            m[k] = json.loads(m[k]) if m.get(k) else None
        return m

    def mission(self, mid: str) -> dict:
        with self._cx() as cx:
            return self._mission(cx, mid)

    def missions(self, *, operator: str | None = None, limit: int = 100) -> list[dict]:
        q, args = "SELECT id FROM missions", []
        if operator:
            q += " WHERE operator=?"
            args.append(operator)
        with self._cx() as cx:
            ids = [r["id"] for r in cx.execute(
                q + " ORDER BY created_utc DESC, id DESC LIMIT ?", (*args, limit))]
            return [self._mission(cx, i) for i in ids]

    def create_mission(self, *, by: str, name: str, mtype: str, environment: str | None,
                       duration_h: float | None, altitude_ft: float | None,
                       area: str = "", launch_utc: str = "", priority: str = "ROUTINE",
                       notes: str = "") -> dict:
        types = self.mission_types()
        if mtype not in types:
            raise OpsError(f"mission type must be one of {sorted(types)}", 400)
        t = types[mtype]
        env = environment or t.get("environment", "STANDARD")
        if env not in self.fleet.get("environments", [env]):
            raise OpsError(f"environment must be one of {self.fleet.get('environments')}", 400)
        dur = float(duration_h if duration_h else t["duration_h"])
        alt = float(altitude_ft if altitude_ft else t["altitude_ft"])
        if not 0.25 <= dur <= 40.0:
            raise OpsError("planned duration must be between 0.25 and 40 hours", 400)
        if not 1000.0 <= alt <= 25000.0:
            raise OpsError("altitude must be between 1,000 and 25,000 ft", 400)
        with self._lock, self._cx() as cx:
            n = cx.execute("SELECT COUNT(*) AS n FROM missions").fetchone()["n"] + 1
            mid = f"MSN-{n:04d}"
            cx.execute(
                "INSERT INTO missions (id, name, type, status, environment, duration_h, "
                "altitude_ft, throttle_pct, area, launch_utc, priority, notes, created_by, "
                "created_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, name.strip() or t["label"], mtype, PLANNED, env, dur, alt,
                 float(t.get("throttle_pct", 70.0)), area, launch_utc, priority, notes,
                 by, _now()))
            self._log(cx, None, "MISSION_PLANNED",
                      f"{mid} {name or t['label']}: {t['label']}, {dur:g} h at "
                      f"{alt:,.0f} ft, {env}", by=by, role="ROLE_COMMANDER")
            return self._mission(cx, mid)

    def assess(self, tail: str, duration_h: float, altitude_ft: float,
               throttle_pct: float = 70.0) -> dict:
        """The twin's Go/No-Go for THIS aircraft on a mission of this length,
        from the condition its last engine run measured."""
        from layer4_core.mission import MissionProfile, MissionReliability
        h = self._health.get(tail, {})
        inputs = h.get("inputs")
        if not inputs or inputs.get("chi") is None:
            return {"verdict": "NOT_ASSESSED", "success_probability": None,
                    "reasons": ["the twin has not yet assessed this engine warm and loaded; "
                                "a ground run or a flight will"],
                    "assessed_utc": None}
        prof = MissionProfile("TASK", float(duration_h), float(altitude_ft), float(throttle_pct))
        a = MissionReliability().assess(
            prof, chi=inputs["chi"], subsystems=inputs.get("subsystems") or {},
            rul_hours=inputs.get("rul_hours"), rul_lower_hours=inputs.get("rul_lower_hours"),
            rul_confidence=float(inputs.get("rul_confidence") or 0.0),
            active_alerts=int(inputs.get("active_alerts") or 0),
            highest_alert_level=int(inputs.get("highest_alert_level") or 1),
            grounded=bool(inputs.get("grounded")),
            grounding_reason=inputs.get("grounding_reason"),
            tbo_remaining_hours=inputs.get("tbo_remaining_hours"))
        out = a.as_dict()
        out["assessed_utc"] = h.get("assessed_utc")
        return out

    def candidates(self, mid: str) -> list[dict]:
        """Every aircraft, ranked for this mission: serviceable and GO first."""
        m = self.mission(mid)
        rows = []
        for a in self.fleet_board():
            lim = a["limitations"] or {}
            problems = []
            if a["status"] != SERVICEABLE:
                problems.append(f"{a['status'].lower()}: {a['status_detail']}")
            if a["mission"] and a["mission"]["id"] != mid:
                problems.append(f"already allotted to {a['mission']['id']}")
            if lim.get("max_mission_hours") is not None and m["duration_h"] > lim["max_mission_hours"]:
                problems.append(f"limited to {lim['max_mission_hours']:g} h missions")
            if lim.get("max_altitude_ft") is not None and m["altitude_ft"] > lim["max_altitude_ft"]:
                problems.append(f"limited to {lim['max_altitude_ft']:,.0f} ft")
            ass = self.assess(a["tail"], m["duration_h"], m["altitude_ft"], m["throttle_pct"])
            if ass["verdict"] == "NO_GO":
                problems.append("twin predicts NO-GO for this mission")
            rows.append({"tail": a["tail"], "status": a["status"], "engine": a["engine_name"],
                         "engine_validated": a["engine_validated"],
                         "health": a["health"], "assessment": ass, "limitations": lim,
                         "eligible": not problems, "problems": problems})
        order = {"GO": 0, "GO_WITH_LIMITS": 1, "NOT_ASSESSED": 2, "NO_GO": 3}
        rows.sort(key=lambda r: (not r["eligible"], order.get(r["assessment"]["verdict"], 4),
                                 -(r["assessment"].get("success_probability") or 0.0)))
        if rows and rows[0]["eligible"]:
            rows[0]["recommended"] = True
        return rows

    def approve(self, mid: str, *, by: str, tail: str, operator: str,
                note: str = "") -> dict:
        with self._lock:
            m = self.mission(mid)
            if m["status"] not in (PLANNED, APPROVED):
                raise OpsError(f"{mid} is {m['status']}; only a planned mission can be allotted")
            cand = {c["tail"]: c for c in self.candidates(mid)}
            if tail not in cand:
                raise OpsError(f"no aircraft {tail!r} in this squadron", 404)
            c = cand[tail]
            if not c["eligible"]:
                raise OpsError(f"{tail} cannot be allotted: " + "; ".join(c["problems"]))
            with self._cx() as cx:
                cx.execute("UPDATE missions SET status=?, tail=?, operator=?, approved_by=?, "
                           "approved_utc=?, assessment=?, notes=COALESCE(notes,'') || ? "
                           "WHERE id=?",
                           (APPROVED, tail, operator, by, _now(), json.dumps(c["assessment"]),
                            (f"\n[approval] {note}" if note else ""), mid))
                v = c["assessment"]
                p = v.get("success_probability")
                self._log(cx, tail, "MISSION_APPROVED",
                          f"{mid} approved: {tail} allotted, operator {operator}. Twin: "
                          f"{v['verdict']}" + (f", {p * 100:.0f} % predicted success" if p is not None else ""),
                          by=by, role="ROLE_COMMANDER")
                return self._mission(cx, mid)

    def cancel(self, mid: str, *, by: str, reason: str) -> dict:
        with self._lock, self._cx() as cx:
            m = self._mission(cx, mid)
            if m["status"] not in (PLANNED, APPROVED, PREFLIGHT):
                raise OpsError(f"{mid} is {m['status']} and can no longer be cancelled; "
                               "the operator can recall it")
            cx.execute("UPDATE missions SET status=?, cancelled_by=?, cancel_reason=? WHERE id=?",
                       (CANCELLED, by, reason, mid))
            busy = json.loads(self._station(cx, "busy") or "null")
            if busy and busy.get("id") == mid:
                self._set_station(cx, "busy", None)
            self._log(cx, m["tail"], "MISSION_CANCELLED", f"{mid} cancelled: {reason}",
                      by=by, role="ROLE_COMMANDER")
            return self._mission(cx, mid)

    def _own(self, m: dict, by: str, role: str) -> None:
        if role != "ROLE_COMMANDER" and m["operator"] != by:
            raise OpsError(f"{m['id']} is allotted to {m['operator']}, not to you", 403)

    def prepare(self, mid: str, *, by: str, role: str) -> dict:
        """The operator takes the allotted aircraft onto the ground station."""
        with self._lock, self._cx() as cx:
            m = self._mission(cx, mid)
            self._own(m, by, role)
            if m["status"] == PREFLIGHT:
                return m
            if m["status"] != APPROVED:
                raise OpsError(f"{mid} is {m['status']}, not approved for flight")
            self._require_free(cx)
            a = self._aircraft(cx, m["tail"])
            if a["status"] != SERVICEABLE:
                raise OpsError(f"{m['tail']} is no longer serviceable ({a['status_detail']}); "
                               "the commander must re-allot")
            cx.execute("UPDATE missions SET status=?, prepared_utc=? WHERE id=?",
                       (PREFLIGHT, _now(), mid))
            self._set_station(cx, "busy", json.dumps({"kind": "mission", "id": mid,
                                                      "tail": m["tail"]}))
            self._set_station(cx, "active_tail", m["tail"])
            self._log(cx, m["tail"], "PREFLIGHT", f"{mid}: aircraft taken on the GCS by {by}",
                      by=by, role=role)
            return self._mission(cx, mid)

    def release_gcs(self, mid: str, *, by: str, role: str) -> dict:
        """Hand a prepared mission back without starting (e.g. a check failed)."""
        with self._lock, self._cx() as cx:
            m = self._mission(cx, mid)
            self._own(m, by, role)
            if m["status"] != PREFLIGHT:
                raise OpsError(f"{mid} is {m['status']}")
            cx.execute("UPDATE missions SET status=? WHERE id=?", (APPROVED, mid))
            self._set_station(cx, "busy", None)
            self._log(cx, m["tail"], "PREFLIGHT", f"{mid}: pre-flight stopped, aircraft "
                      "handed back", by=by, role=role)
            return self._mission(cx, mid)

    def start(self, mid: str, *, by: str, role: str, checklist: dict[str, bool]) -> dict:
        items = self.checklist()
        missing = [i for i in items if not checklist.get(i)]
        if missing:
            raise OpsError("pre-flight checklist incomplete: " + "; ".join(missing), 400)
        with self._lock, self._cx() as cx:
            m = self._mission(cx, mid)
            self._own(m, by, role)
            if m["status"] != PREFLIGHT:
                raise OpsError(f"{mid} is {m['status']}; prepare the aircraft first")
            cx.execute("UPDATE missions SET status=?, started_utc=?, preflight=? WHERE id=?",
                       (ENGINE_RUNNING, _now(), json.dumps(
                           {"checklist": items, "confirmed_by": by, "utc": _now()}), mid))
            self._log(cx, m["tail"], "ENGINE_START", f"{mid}: checklist complete, engine "
                      "start", by=by, role=role)
            return self._mission(cx, mid)

    def _step(self, mid: str, *, by: str, role: str, frm: tuple, to: str,
              kind: str, text: str, stamp: str | None = None) -> dict:
        with self._lock, self._cx() as cx:
            m = self._mission(cx, mid)
            self._own(m, by, role)
            if m["status"] not in frm:
                raise OpsError(f"{mid} is {m['status']}")
            if stamp:
                cx.execute(f"UPDATE missions SET status=?, {stamp}=? WHERE id=?",
                           (to, _now(), mid))
            else:
                cx.execute("UPDATE missions SET status=? WHERE id=?", (to, mid))
            self._log(cx, m["tail"], kind, f"{mid}: {text}", by=by, role=role)
            return self._mission(cx, mid)

    def launch(self, mid: str, *, by: str, role: str) -> dict:
        return self._step(mid, by=by, role=role, frm=(ENGINE_RUNNING,), to=AIRBORNE,
                          kind="LAUNCH", text="launch clearance given", stamp="launched_utc")

    def rtb(self, mid: str, *, by: str, role: str) -> dict:
        return self._step(mid, by=by, role=role, frm=(AIRBORNE,), to=RTB, kind="RTB",
                          text="recalled: return to base")

    def abort(self, mid: str, *, by: str, role: str) -> dict:
        return self._step(mid, by=by, role=role, frm=(ENGINE_RUNNING,), to=ABORTING,
                          kind="ABORT", text="aborted on the ground; engine shutting down")

    def engine_stopped(self, snap: Any, *, flight_hours: float) -> dict | None:
        """The engine on the ground station has been shut down.

        Ends the mission or ground run occupying the station, withdraws the
        aircraft's release (an after-flight inspection is due), and raises the
        twin's maintenance advisories as defects for the engineer to review.
        Returns what ended.
        """
        with self._lock, self._cx() as cx:
            busy = json.loads(self._station(cx, "busy") or "null")
            if not busy:
                return None
            tail = busy["tail"]
            self.update_health(tail, snap, force_flush=True)
            self._set_station(cx, "busy", None)
            ended: dict = {"kind": busy["kind"], "tail": tail}
            if busy["kind"] == "mission":
                m = self._mission(cx, busy["id"])
                cx.execute("UPDATE missions SET status=?, landed_utc=?, engine_hours=? "
                           "WHERE id=?", (AWAITING_DEBRIEF, _now(),
                                          round(flight_hours, 3), m["id"]))
                cx.execute("UPDATE aircraft SET sorties=sorties+1 WHERE tail=?", (tail,))
                airborne = m["launched_utc"] is not None
                self._log(cx, tail, "ENGINE_STOP",
                          f"{m['id']}: {'landed and ' if airborne else ''}shut down after "
                          f"{flight_hours:.2f} engine hours", data={"engine_hours": flight_hours})
                self._unrelease(cx, tail, "Engine run completed: after-flight inspection due")
                ended["mission_id"] = m["id"]
            else:
                cx.execute("UPDATE aircraft SET ground_runs=ground_runs+1 WHERE tail=?", (tail,))
                h = self._health.get(tail, {})
                self._log(cx, tail, "GROUND_RUN",
                          f"Ground run complete by {busy.get('by', '?')}: health "
                          + (f"{h['chi'] * 100:.1f} % ({h.get('band')})" if h.get("chi") is not None
                             else "not assessed"), by=busy.get("by", "system"),
                          role=busy.get("role", "system"), data={"health": h.get("subsystems")})
            ended["raised"] = self._raise_twin_defects(cx, tail, snap, busy.get("id"))
            return ended

    def _raise_twin_defects(self, cx, tail: str, snap: Any, mission_id: str | None) -> list[int]:
        """The twin's maintenance advisory, as defects on the aircraft's log.

        An advisory on a console is read by whoever is looking; a defect on the
        technical log is owned until someone closes it. CAUTION and above are
        raised; WARNING and EMERGENCY ground the aircraft until an engineer
        dispositions them or a maintainer rectifies them. One open defect per
        recommended action: a repeat advisory adds evidence, not a duplicate.
        """
        plan = getattr(snap, "maintenance", None) or {}
        open_ids = {d["action_id"] for d in self._open_defects(cx, tail) if d["action_id"]}
        raised = []
        for a in plan.get("actions", []):
            sev = str(a.get("severity") or "ADVISORY")
            if sev not in ("CAUTION", "WARNING", "EMERGENCY"):
                continue
            aid = a.get("action_id")
            if aid in open_ids:
                continue
            grounding = sev in ("WARNING", "EMERGENCY")
            cur = cx.execute(
                "INSERT INTO defects (tail, mission_id, source, raised_by, raised_role, "
                "raised_utc, description, severity, grounding, status, action_id, evidence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (tail, mission_id, "TWIN", "digital twin", "system", _now(),
                 f"{a.get('name')}: {a.get('reason')}", sev, int(grounding), D_OPEN, aid,
                 json.dumps({"health": self._health.get(tail, {}).get("subsystems"),
                             "chi": self._health.get(tail, {}).get("chi"),
                             "due_within_hours": a.get("due_within_hours")})))
            did = int(cur.lastrowid)
            raised.append(did)
            self._log(cx, tail, "DEFECT_RAISED",
                      f"#{did} [{sev}{', GROUNDING' if grounding else ''}] raised by the twin: "
                      f"{a.get('name')} -- {a.get('reason')}")
        return raised

    def debrief(self, mid: str, *, by: str, role: str, outcome: str, remarks: str,
                snags: list[dict]) -> dict:
        if outcome not in ("ACCOMPLISHED", "PARTIAL", "ABORTED"):
            raise OpsError("outcome must be ACCOMPLISHED, PARTIAL or ABORTED", 400)
        m = self.mission(mid)
        self._own(m, by, role)
        if m["status"] != AWAITING_DEBRIEF:
            raise OpsError(f"{mid} is {m['status']}; debrief follows engine shutdown")
        raised = []
        for s in snags or []:
            if str(s.get("description", "")).strip():
                d = self.raise_defect(m["tail"], source="OPERATOR", by=by, role=role,
                                      description=str(s["description"]),
                                      severity=str(s.get("severity") or "CAUTION"),
                                      grounding=bool(s.get("grounding")), mission_id=mid)
                raised.append(d["id"])
        with self._lock, self._cx() as cx:
            final = ABORTED if outcome == "ABORTED" else COMPLETED
            cx.execute("UPDATE missions SET status=?, outcome=?, completed_utc=?, debrief=? "
                       "WHERE id=?", (final, outcome, _now(), json.dumps(
                           {"remarks": remarks, "snags": raised, "by": by, "utc": _now()}), mid))
            self._log(cx, m["tail"], "DEBRIEF",
                      f"{mid} debriefed: {outcome.lower()}"
                      + (f"; {len(raised)} snag(s) reported" if raised else "; no snags")
                      + (f". {remarks}" if remarks else ""), by=by, role=role)
            return self._mission(cx, mid)

    # ------------------------------------------------------------------ ground runs
    def begin_ground_run(self, tail: str, *, by: str, role: str) -> None:
        with self._lock, self._cx() as cx:
            self._require_free(cx)
            a = self._aircraft(cx, tail)
            if a["mission"] and a["mission"]["status"] in ON_STATION:
                raise OpsError(f"{tail} is on {a['mission']['id']}")
            self._set_station(cx, "busy", json.dumps({"kind": "ground_run", "tail": tail,
                                                      "by": by, "role": role}))
            self._set_station(cx, "active_tail", tail)
            self._log(cx, tail, "GROUND_RUN", f"Engine ground run started by {by}",
                      by=by, role=role)

    def connect(self, tail: str) -> None:
        """Put a parked aircraft on the ground station, engine off, to inspect it."""
        with self._lock, self._cx() as cx:
            self._require_free(cx)
            self.aircraft_cfg(tail)
            self._set_station(cx, "active_tail", tail)

    def recover_after_restart(self) -> str | None:
        """The station stopped with something on it. Say so, and hand it back.

        The engine's running state does not survive a restart of the station;
        its wear and hours do. A mission in the air when the station stopped
        is closed for debrief with that on record rather than left open.
        """
        with self._lock, self._cx() as cx:
            busy = json.loads(self._station(cx, "busy") or "null")
            if not busy:
                return None
            self._set_station(cx, "busy", None)
            if busy.get("kind") == "mission":
                m = self._mission(cx, busy["id"])
                if m["status"] == PREFLIGHT:
                    cx.execute("UPDATE missions SET status=? WHERE id=?", (APPROVED, m["id"]))
                    text = f"{m['id']}: station restarted during pre-flight; mission handed back"
                elif m["status"] in ENGINE_ON:
                    cx.execute("UPDATE missions SET status=?, landed_utc=? WHERE id=?",
                               (AWAITING_DEBRIEF, _now(), m["id"]))
                    self._unrelease(cx, busy["tail"], "Station restarted with the engine running")
                    text = (f"{m['id']}: station restarted while {m['status'].lower()}; "
                            "the engine run was lost -- debrief and inspect")
                else:
                    text = f"{m['id']}: station restarted"
            else:
                text = "station restarted during a ground run; run it again"
            self._log(cx, busy.get("tail"), "STATION_RESTART", text)
            return text

    # ------------------------------------------------------------------ logbook, tasks
    def logbook(self, tail: str | None = None, limit: int = 200) -> list[dict]:
        with self._cx() as cx:
            if tail:
                rows = cx.execute("SELECT * FROM logbook WHERE tail=? ORDER BY id DESC LIMIT ?",
                                  (tail, limit))
            else:
                rows = cx.execute("SELECT * FROM logbook ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in rows]

    def tasks(self, *, role: str, user: str) -> list[dict]:
        """What is waiting on THIS person, most urgent first.

        Each role gets its OWN work and nothing else (docs/UX_REDESIGN.md s3.3).
        The commander used to receive every maintainer rectification and every
        engineering review as well, so their list was the squadron's whole
        backlog and the two decisions only they can take -- allot, re-allot --
        were two lines among twenty. A grounded aircraft reaches the commander
        as readiness, on the Operations page, not as a chore.
        """
        out: list[dict] = []
        board = self.fleet_board()
        missions = self.missions(limit=200)
        commander = role == "ROLE_COMMANDER"
        if role == "ROLE_OPERATOR":
            for m in missions:
                if m["operator"] != user:
                    continue
                if m["status"] == AWAITING_DEBRIEF:
                    out.append({"page": "FLIGHT", "urgency": 1, "mission": m["id"],
                                "text": f"Debrief {m['id']} {m['name']} ({m['tail']})"})
                elif m["status"] in ON_STATION:
                    out.append({"page": "FLIGHT", "urgency": 0, "mission": m["id"],
                                "text": f"{m['id']} in progress on {m['tail']}: "
                                        f"{m['status'].replace('_', ' ').lower()}"})
                elif m["status"] == APPROVED:
                    out.append({"page": "FLIGHT", "urgency": 2, "mission": m["id"],
                                "text": f"{m['id']} {m['name']} approved: {m['tail']} allotted to you"})
        if commander:
            for m in missions:
                if m["status"] == PLANNED:
                    out.append({"page": "OPERATIONS", "urgency": 2, "mission": m["id"],
                                "text": f"Allot an aircraft and operator to {m['id']} {m['name']}"})
                elif m["status"] == APPROVED:
                    a = next((b for b in board if b["tail"] == m["tail"]), None)
                    if a and a["status"] not in (SERVICEABLE, ON_GCS):
                        out.append({"page": "OPERATIONS", "urgency": 1, "mission": m["id"],
                                    "text": f"{m['id']}: allotted {m['tail']} is now "
                                            f"{a['status'].lower()} -- re-allot"})
        if role == "ROLE_MAINTENANCE":
            for a in board:
                for d in a["open_defects"]:
                    if d["status"] in (D_OPEN, D_CONFIRMED) and (d["source"] != "TWIN"
                                                                or d["status"] == D_CONFIRMED
                                                                or d["grounding"]):
                        out.append({"page": "AIRCRAFT", "urgency": 1 if d["grounding"] else 2,
                                    "tail": a["tail"],
                                    "text": f"{a['tail']}: rectify defect #{d['id']} "
                                            f"{_clip(d['description'], 80)}"})
                if a["status"] == AWAITING_INSPECTION:
                    out.append({"page": "AIRCRAFT", "urgency": 2, "tail": a["tail"],
                                "text": f"{a['tail']}: inspection and maintenance release due"})
                for g in a["grounding"]:
                    if "inspection due" in g or "TBO" in g:
                        out.append({"page": "AIRCRAFT", "urgency": 1, "tail": a["tail"],
                                    "text": f"{a['tail']}: {g}"})
        if role == "ROLE_ENGINEER":
            for a in board:
                for d in a["open_defects"]:
                    if d["source"] == "TWIN" and d["status"] == D_OPEN:
                        out.append({"page": "ENGINEERING", "urgency": 1 if d["grounding"] else 2,
                                    "tail": a["tail"],
                                    "text": f"{a['tail']}: review twin defect #{d['id']} "
                                            f"[{d['severity']}] {_clip(d['description'], 70)}"})
                h = a["health"]
                if h.get("chi") is not None and float(h["chi"]) < 0.8:
                    out.append({"page": "ENGINEERING", "urgency": 2, "tail": a["tail"],
                                "text": f"{a['tail']}: engine health {float(h['chi']) * 100:.0f} %"
                                        f" ({h.get('band')}) -- review the trend"})
        out.sort(key=lambda t: t["urgency"])
        return out


__all__ = ["OpsError", "OpsStore", "load_fleet"]
