"""REST and WebSocket interface to the live twin -- PRD Part 1 section 7.

Run:  python -m layer4_core.twin_api
      (then open http://127.0.0.1:8000)

Everything served here comes from the running pipeline in ``layer4_core.live``.
There is no mock data path and no seeded demo file: if a number appears on the
console, a physics step produced it, a CAN frame carried it, and the ingest
layer validated it. That property is worth the extra work, because a
demonstrator with a mock path eventually gets demonstrated on the mock path.

THE WEBSOCKET SENDS SNAPSHOTS, NOT EVENTS
-----------------------------------------
Each message is a complete state, not a delta. A console that has been open for
an hour and one that just connected therefore render identically, and a dropped
message costs one frame of latency rather than permanent divergence -- which is
the same reasoning that made the edge buffer replay oldest-first.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json
import logging
import math
import os
import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from common import config
from common import logging as dt_logging
from layer4_core.live import LiveTwin, Snapshot, available_faults
from layer4_core import fleet as fleet_mod
from layer4_core import history as hist
from layer4_core import recorder as rec
from layer4_core import fleet_sync as fsync
from layer4_core import demo
from layer4_core import ops as ops_mod
from layer4_core import replay as replay_mod
from layer4_core import report_pdf
from layer4_core import scenarios as scen
from layer4_core import security as sec
from layer4_core import test_rig as rig

CONSOLE_DIST = Path(__file__).resolve().parent.parent / "layer5_viz" / "gcs_console" / "dist"

twin: LiveTwin | None = None
# Persistent across restarts. Created in the lifespan rather than at
# import so that a test can point DT_DATA_DIR somewhere else first.
history: hist.FlightHistory | None = None
# Store-and-forward to the central fleet server. Absent configuration
# this is inert: a standalone station is a supported deployment.
syncer: fsync.FleetSync | None = None
# The flight data recorder. Without it `replay.py` can only replay the
# SYNTHETIC TRAINING FLEET -- which is not the same thing as replaying
# yesterday's sortie, and the PS asks for the latter.
recorder: rec.FlightRecorder | None = None
# The squadron: aircraft, missions, defects, releases. See layer4_core/ops.py.
OPS: ops_mod.OpsStore | None = None
# The aircraft whose engine twin is on the ground station now.
_active_tail: str | None = None
# Where each aircraft's engine life is kept. None is data/twin_state; with
# DT_PERSIST=0 a directory made fresh for this run, so a demonstration starts
# clean yet keeps every aircraft's wear while it runs.
_LIFE_DIR: str | None = None


# MODULE SCOPE, because the routes need it too.
#
# This existed only as a LOCAL inside lifespan(), which is where every other
# use of it is. A route that logged -- /api/fleet, explaining that a missing
# fleet dataset is not an operator's problem -- raised NameError and returned
# 500 instead. The endpoint scan in the launcher's self-check found it; a
# reader would not, because the name resolves perfectly well four functions
# above.
_log = logging.getLogger("layer4_core.twin_api")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global twin
    # Logging FIRST, so that anything the startup itself reports is captured.
    # Until this existed the pipeline could stop with no log line at all.
    dt_logging.setup_logging()
    if demo.enabled():
        demo.seed_accounts()
        demo.start_idle_reset()

    global OPS, _LIFE_DIR
    ops_path = None
    if os.environ.get("DT_PERSIST", "1") == "0":
        import tempfile
        _LIFE_DIR = tempfile.mkdtemp(prefix="astra-demo-")
        ops_path = Path(_LIFE_DIR) / "squadron.db"
    OPS = ops_mod.OpsStore(ops_path)
    restarted = OPS.recover_after_restart()
    if restarted:
        _log.warning("the station stopped with work on it", extra={"note": restarted})
    if demo.enabled():
        demo.stage_ready_to_fly(OPS)
    first = OPS.active_tail()

    # Then refuse to start on a bad configuration rather than raising a
    # KeyError inside a physics tick minutes later, far from the cause --
    # for every engine the squadron has fitted, not only the first.
    for key in sorted({OPS.aircraft_cfg(t)["engine_key"] for t in OPS.tails()}):
        config.set_runtime_engine(key)
        config.validate(key)

    global history, syncer, recorder
    history = hist.FlightHistory()
    syncer = fsync.FleetSync()
    syncer.start()
    recorder = rec.FlightRecorder(aircraft_id=first,
                                  engine_key=OPS.aircraft_cfg(first)["engine_key"])
    # Rebuild anything a previous run left as loose parts because it was
    # killed rather than stopped. Scans the directory rather than asking the
    # new recorder to recover, which would look only at its own fresh path.
    for restored in rec.recover_orphans():
        _log.warning("recovered a recording from an unclean shutdown",
                     extra={"path": str(restored)})

    # DEMONSTRATION AND DEPLOYMENT DIFFER IN EXACTLY ONE THING: THE CLOCK.
    #
    # The twin advances `speed` simulated seconds per wall second. 20x is a
    # demonstration convenience -- nobody watches a climb in real time -- and
    # it is WRONG on an aircraft, where the twin must stay in step with an
    # engine that is running at 1x. So it is configurable, and a deployment
    # sets DT_SPEED=1.
    #
    # The default stays at 20 rather than at 1 because the thing most often
    # started with no environment at all is the demonstrator, and a demo that
    # appears frozen is worse than a deployment that has to set one variable
    # it is already setting four of.
    twin = _load_aircraft(first)
    try:
        yield
    finally:
        # A flight still open when the station stops is written on the way
        # out; every flight that ENDED was written the moment it ended.
        try:
            snap = twin.snapshot()
            if not (snap.sortie or {}).get("recorded"):
                _record_flight(snap, "station stopped")
        except Exception:
            # Shutdown bookkeeping must never stop a clean shutdown, but it
            # must not be silent either -- that was DEV-156's whole lesson.
            _log.exception("could not write the flight history record")
        if OPS is not None and _active_tail is not None:
            with contextlib.suppress(Exception):
                OPS.update_health(_active_tail, twin.snapshot(), force_flush=True)
        if recorder is not None:
            written = recorder.close()
            _log.info("recording closed",
                      extra={"path": str(written) if written else None,
                             "rows": recorder.rows})
        if syncer is not None:
            syncer.stop()
        twin.stop()
        _log.info("twin stopped")


_tick_count = 0


def _on_tick(snap: Snapshot) -> None:
    """Every complete tick: the flight recorder, and now and then the squadron
    log's record of this aircraft's condition."""
    global _tick_count
    if recorder is not None:
        recorder.record(snap)
    _tick_count += 1
    if OPS is not None and _active_tail is not None and _tick_count % 20 == 0:
        OPS.update_health(_active_tail, snap)


def _load_aircraft(tail: str) -> LiveTwin:
    """Put one aircraft's engine twin on the ground station, engine stopped.

    The aircraft's engine keeps its own life -- hours, wear, trend, the work
    done on it -- in its own file. An aircraft never seen before is given the
    hours fleet.yaml says it has flown (and any fault it is developing) once,
    and keeps them from then on.
    """
    global _active_tail
    cfg = OPS.aircraft_cfg(tail)
    # The limits that apply are this aircraft's engine's (thresholds_override).
    config.set_runtime_engine(cfg["engine_key"])
    t = LiveTwin(
        twin_id=cfg["twin_id"],
        aircraft_id=tail,
        engine_key=cfg["engine_key"],
        speed=float(os.environ.get("DT_SPEED", "20")),
        persist=True,
        life_dir=_LIFE_DIR,
    )
    if (t.engine_life_restored is None and not cfg.get("engine_changed")
            and float(cfg.get("initial_engine_hours") or 0.0) > 0.0):
        t.age_engine(float(cfg["initial_engine_hours"]),
                     inspection_every_h=OPS.inspection_interval())
        from layer2_physics.degradation import FaultMode, InjectedFault
        for f in cfg.get("developing_faults") or []:
            t.veng.inject(InjectedFault(
                mode=FaultMode(f["mode"]),
                onset_hours=t.veng.flight_hours + float(f.get("onset_after_hours", 0.0)),
                severity=float(f["severity"]),
                ramp_hours=float(f.get("ramp_hours", 1.0))))
        t.save_engine_life()
        _log.info("aircraft registered with its engine's past life",
                  extra={"tail": tail, "engine_hours": cfg["initial_engine_hours"]})
    # PARKED. The engine starts when an operator starts it, for a mission, or
    # a maintainer runs it on the ground -- not because the station started.
    t.park()
    t._on_tick = _on_tick
    # EACH FLIGHT IS WRITTEN WHEN IT ENDS. It used to be written only when the
    # server process stopped, so every sortie flown and ended in between was
    # lost to the trend across flights.
    t.on_sortie_end = _record_flight
    # Work signed off while this aircraft was not on the station reaches its
    # engine now, before the first tick.
    for w in OPS.take_pending_maintenance(tail):
        try:
            t.record_maintenance(w["action_id"], repaired=w.get("repaired"),
                                 by=str(w.get("by", "")), note=str(w.get("note", "")),
                                 health_before=w.get("health_before"))
        except ValueError:
            _log.exception("queued maintenance could not be applied")
    t.start()
    _active_tail = tail
    OPS.set_active(tail)
    if t.speed != 1.0:
        _log.warning(
            "twin is running FASTER THAN REAL TIME; this is a demonstration "
            "setting and must not be used against a real engine",
            extra={"speed_x": t.speed})
    _log.info("aircraft on the ground station",
              extra={"tail": tail, "engine": t.engine_key, "speed_x": t.speed})
    return t


def _swap_to(tail: str) -> LiveTwin:
    """Change which aircraft is on the ground station. The one leaving is
    parked with its condition written to the squadron log and its life saved."""
    global twin, recorder
    cfg = OPS.aircraft_cfg(tail)
    with _twin_swap_lock:
        if (twin is not None and _active_tail == tail
                and twin.engine_key == cfg["engine_key"]):
            return twin
        old = twin
        if old is not None:
            try:
                snap = old.snapshot()
                if _active_tail is not None:
                    OPS.update_health(_active_tail, snap, force_flush=True)
                if (snap.sortie or {}).get("state") == "running" \
                        and not (snap.sortie or {}).get("recorded"):
                    _record_flight(snap, "aircraft changed")
            except Exception:
                _log.exception("could not close the outgoing aircraft's record")
            old.stop()
        twin = None
        if recorder is not None:
            recorder.close()
            recorder = rec.FlightRecorder(aircraft_id=tail, engine_key=cfg["engine_key"])
        twin = _load_aircraft(tail)
        return twin


def _history_key(md: dict | None = None) -> str:
    """The ENGINE a flight belongs to: its serial, not its type.

    Filed under the engine type ("rotax_915is"), every engine of that type was
    one trend -- and the live engine was a different random engine on every
    station start, so the "change since the first comparable flight" compared
    two unrelated engines. The twin's serial names one engine.
    """
    serial = (md or {}).get("twin_id")
    if not serial and twin is not None:
        serial = twin.twin_id
    return str(serial or "")


def _record_flight(snap: Snapshot, reason: str) -> int | None:
    """Write one ended flight to the station's history and queue it for the fleet.

    ``reason`` says how it ended: "complete" (shut down at the end of the
    sortie), "interrupted" (a new sortie was started over it) or "station
    stopped". A flight that never held a stabilised cruise contributes
    nothing to the trend, and `FlightHistory.record` says so.
    """
    if history is None:
        return None
    sortie = snap.sortie or {}
    # THIS flight's duration. The pipeline's `flight_hours` is the engine's
    # TOTAL hours, and the trend sums this column as per-flight durations --
    # two comparable flights read as ~840 h apart and the drift rate came out
    # ~1,000 times too small (REP-01).
    hours = round(float(sortie.get("flight_time_s") or snap.t_s or 0.0) / 3600.0, 4)
    events = list((snap.flight_record or {}).get("events") or [])
    events.append({"kind": "SORTIE_END", "reason": reason,
                   "t_s": sortie.get("ended_t_s") or snap.t_s})
    fid = history.record(
        (snap.flight_record or {}).get("cruise_datum"),
        engine_key=_history_key(snap.twin.get("metadata")),
        aircraft_id=str(snap.twin.get("metadata", {}).get("aircraft_id")),
        flight_hours=hours,
        health_chi=snap.health.get("chi"),
        health=snap.health,
        events=events,
    )
    _log.info("flight history written",
              extra={"flight_id": fid, "ended": reason, "flight_h": hours})
    # The squadron learns the engine has stopped: the mission goes to debrief,
    # the aircraft's release is withdrawn, the twin's advisories become defects.
    if (OPS is not None and reason == "complete"
            and sortie.get("kind") in ("mission", "ground_run")):
        try:
            ended = OPS.engine_stopped(snap, flight_hours=hours)
            _log.info("engine run ended", extra={"ended": ended})
        except Exception:
            _log.exception("could not record the end of the engine run")
    # The local store is authoritative for this station; the outbox is how
    # the fleet tier eventually learns about it. Queued, never sent inline.
    if fid is not None and syncer is not None:
        cruise = (snap.flight_record or {}).get("cruise_datum") or {}
        syncer.outbox.enqueue("flight_record", {
            **cruise,
            "engine_key": twin.engine_key if twin is not None else "",
            "engine_serial": _history_key(snap.twin.get("metadata")),
            "aircraft_id": str(snap.twin.get("metadata", {}).get("aircraft_id")),
            "flight_hours": hours,
            "health_chi": snap.health.get("chi"),
            "recorded_utc": None,
        })
    return fid


# One version string, used by the API surface and printed on the post-flight
# report's cover. Two of them would drift, and the cover's whole job is to say
# which build produced the document.
GCS_VERSION = "1.0"


def _version() -> str:
    return GCS_VERSION


def _json_safe(obj):
    """Replace NaN and infinity with None, recursively.

    JSON has no representation for either. Python's encoder emits bare `NaN`
    by default, which is invalid JSON that many parsers reject; Starlette's
    JSONResponse instead raises, taking the whole response with it.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _one_series(history: dict, key: str) -> list:
    """One history channel as [[hours, value], ...], gaps dropped.

    The snapshot keeps parallel arrays with a shared `t` in SECONDS. The report
    plots hours, and a None in the middle of a series draws a line through
    zero rather than a break, so unusable samples are dropped rather than
    substituted.

    Hours FROM THE START OF THIS FLIGHT. `t` is the station's clock, and the
    series is reset at each sortie -- so a ten-minute sortie flown two hours
    after the station started was plotted at the right-hand edge of a 0-2.5 h
    axis, a sliver of data in an empty chart (reported from use).
    """
    t = (history or {}).get("t") or []
    ys = (history or {}).get(key) or []
    t0 = next((float(a) for a in t if a is not None), 0.0)
    return [[round((float(a) - t0) / 3600.0, 4), round(float(b), 4)]
            for a, b in zip(t, ys) if a is not None and b is not None]


def _flight_hours_span(series: dict) -> float | None:
    """How long THIS flight's record runs, in hours (None if empty)."""
    t = [float(a) for a in (series or {}).get("t") or [] if a is not None]
    return round((t[-1] - t[0]) / 3600.0, 3) if len(t) > 1 else None


def _mission_for_report() -> dict:
    """The squadron's own record of the mission this flight was, if any.

    The report called every flight "MISSION-<date>-<engine>" and "ISR patrol
    profile", whatever was flown, while the operations store held the real
    tasking: MSN-0002, communication relay, op.rao, approved by the commander.
    The mission in progress on the aircraft on the station, or failing that the
    most recent one it flew.
    """
    try:
        o = _ops()
    except Exception:  # noqa: BLE001 - the report still exports without ops
        return {}
    tail = _active_tail
    busy = o.busy() or {}
    ms = o.missions(limit=100)
    m = None
    if busy.get("kind") == "mission":
        m = next((x for x in ms if x["id"] == busy.get("id")), None)
    if m is None:
        m = next((x for x in ms if x.get("tail") == tail and x.get("launched_utc")), None)
    if m is None:
        return {}
    types = o.mission_types()
    return {
        "id": m["id"], "name": m.get("name"), "status": m.get("status"),
        "task": (types.get(m.get("type"), {}) or {}).get("label") or m.get("type"),
        "operator": m.get("operator"), "approved_by": m.get("approved_by"),
        "area": m.get("area"), "planned_endurance_h": m.get("duration_h"),
        "planned_altitude_ft": m.get("altitude_ft"), "environment": m.get("environment"),
        "outcome": m.get("outcome"), "launched_utc": m.get("launched_utc"),
        "landed_utc": m.get("landed_utc"), "debrief": (m.get("debrief") or {}).get("remarks"),
    }


def _series(history: dict, mapping: tuple) -> dict:
    """Several channels at once, under the names the report asks for."""
    return {report_key: _one_series(history, snap_key)
            for report_key, snap_key in mapping}


_TREND_UNITS = {
    "cht_max_c": "C", "cht_spread_c": "C", "egt_max_c": "C",
    "egt_spread_c": "C", "oil_pressure_psi": "psi",
    "oil_temperature_c": "C", "coolant_temperature_c": "C",
    "fuel_flow_lph": "L/h", "power_kw": "kW",
}
# Flight hours a trend must span before a per-100-hour rate is quoted. Five is
# not a statistical threshold -- it is the point below which the extrapolation
# is more than an order of magnitude and the figure stops describing anything
# that was measured.
_MIN_TREND_SPAN_H = 5.0

# Every trended channel, so none falls through to a title-cased column name
# like "Egt Spread C" -- which is the database talking, not the report.
_TREND_LABEL = {
    "cht_max_c": "Cylinder Head Temp (max)",
    "cht_spread_c": "Cylinder Head Spread",
    "egt_max_c": "Exhaust Gas Temp (max)",
    "egt_spread_c": "Exhaust Gas Spread",
    "oil_pressure_psi": "Oil Pressure",
    "oil_temperature_c": "Oil Temperature",
    "coolant_temperature_c": "Coolant Temperature",
    "fuel_flow_lph": "Fuel Flow",
    "power_kw": "Power",
}


# The limit each trended channel is drifting toward, as the parameter and the
# field naming it in thresholds.yaml. Channels with no limit (fuel flow, power)
# are absent on purpose: there is no crossing to project.
_TREND_LIMIT = {
    "cht_max_c": ("cht", "critical_max"),
    "cht_spread_c": ("cht", "spread_critical"),
    "egt_max_c": ("egt", "critical_max"),
    "egt_spread_c": ("egt", "spread_critical"),
    "oil_pressure_psi": ("oil_pressure", "critical_min"),
    "oil_temperature_c": ("oil_temperature", "critical_max"),
    "coolant_temperature_c": ("coolant_temperature", "critical_max"),
}


def _hours_to_limit(key: str, value, per_100h) -> float | None:
    """Flight hours until this drift reaches the channel's limit, or nothing.

    Section 8 quoted a drift rate beside "Reaches limit in ---", which reads as
    a figure that was computed and came out empty. It never was computed.

    The signs do the work for both directions: oil pressure falls TOWARD a
    minimum, cylinder head temperature rises toward a maximum, and a channel
    drifting away from its limit has no crossing to quote.
    """
    spec = _TREND_LIMIT.get(key)
    if spec is None or value is None or not per_100h:
        return None
    try:
        limit = float(config.load_thresholds()["parameters"][spec[0]][spec[1]])
    except (KeyError, TypeError, ValueError):
        return None
    rate = float(per_100h) / 100.0          # channel units per flight hour
    gap = limit - float(value)              # signed distance to the limit
    if gap * rate <= 0:                     # flat, or moving away from it
        return None
    return gap / rate


def _trend_series(store, engine_key: str, want: int = 3) -> dict:
    """Cross-flight drift, reshaped for the report's section 8.

    `FlightHistory.trend()` already does the hard half: it compares each
    flight's stabilised datum against the FIRST recorded flight, and refuses
    the comparison when the two were taken at conditions too far apart. Only
    comparable flights reach a chart here -- a point taken on a day 20 C hotter
    is not drift, and plotting it is how a trend programme produces a false
    finding and gets switched off.
    """
    if store is None:
        return {"series": []}
    try:
        t = store.trend(engine_key)
    except Exception:
        return {"series": []}

    usable = [c for c in (t.get("comparisons") or []) if c.get("comparable")]
    if len(usable) < 2:
        return {"series": [],
                "reason": (f"{len(usable)} comparable flight(s) on record; a "
                           f"trend needs at least two")}

    # HOURS FLOWN BETWEEN THE FIRST AND LAST COMPARABLE FLIGHT.
    #
    # `flight_hours` on a record is the duration of THAT flight, not cumulative
    # engine hours, so subtracting one from another gives the difference in
    # sortie LENGTH -- 0.3829 minus 0.3711 is 0.0118 h between two 23-minute
    # flights. Dividing a 12 C difference by that produced a reported drift of
    # +101,694 C per 100 h.
    #
    # The hours that actually separate two datums are the durations of the
    # flights in between, summed.
    span_h = sum(float(c.get("flight_hours") or 0.0) for c in usable[1:])

    # And a rate is not quoted at all until enough hours support it. Scaling
    # 24 minutes of flying to a per-100-hour figure is an extrapolation by a
    # factor of 250, and printing it beside a measured value invites it to be
    # read as one. Below the floor the section reports the CHANGE and the span
    # it was seen over, which is what was actually observed.
    # Kept for display even when it is too short to divide by: "over 0.76
    # flight hours" is the fact that explains why no rate is quoted.
    observed_span = span_h
    if span_h < _MIN_TREND_SPAN_H:
        span_h = 0.0

    # The latest ABSOLUTE reading of each channel: the plotted points are
    # deltas from the baseline flight, and a distance to a limit is measured
    # from the reading itself.
    try:
        rows = {int(r["flight_id"]): r for r in store.flights(engine_key, 200)}
    except Exception:
        rows = {}
    last_row = rows.get(int(usable[-1].get("flight_id") or -1), {}) or {}

    out = []
    for key in (t.get("trended") or []):
        pts = [[i + 1, c["deltas"][key]]
               for i, c in enumerate(usable) if key in (c.get("deltas") or {})]
        if len(pts) < 2:
            continue
        rise = pts[-1][1] - pts[0][1]
        per_100 = (rise / span_h * 100.0) if span_h else None
        out.append({
            "name": _TREND_LABEL.get(key, key.replace("_", " ").title()),
            "unit": _TREND_UNITS.get(key, ""),
            "points": pts,
            "change": round(rise, 3),
            "span_hours": round(observed_span, 2) if observed_span else None,
            "drift_per_100h": (round(per_100, 3)
                               if per_100 is not None else None),
            "reach_limit_h": _hours_to_limit(key, last_row.get(key), per_100),
        })
    out.sort(key=lambda s: -abs(s["drift_per_100h"] or s["change"] or 0.0))
    return {"series": out[:want], "flights_comparable": len(usable),
            "flights_recorded": t.get("flights_recorded")}


def _envelope(history: dict, key: str) -> dict:
    """avg / min / max of one channel, or nothing at all.

    An environment table with a dash in every cell is honest but useless; one
    with a fabricated average is worse. A channel that produced no usable
    sample is simply absent, and section 3.2 shows what was actually measured.
    """
    vals = [float(x) for x in (history or {}).get(key) or [] if x is not None]
    if not vals:
        return {}
    return {"avg": round(sum(vals) / len(vals), 1),
            "min": round(min(vals), 1), "max": round(max(vals), 1)}


# ISA lapse rate. Used to work out what the standard-day temperature WOULD
# have been at the altitude the datum was taken at.
_ISA_SL_C = 15.0
_ISA_LAPSE_C_PER_FT = 0.0019812  # 6.5 C per 1000 m


def _baseline_datum(engine_key: str) -> dict:
    """The post-overhaul baseline: the first flight on record for this engine."""
    if history is None:
        return {}
    try:
        rows = history.flights(engine_key or None, limit=1)
    except Exception:
        return {}
    return dict(rows[0]) if rows else {}


def _series_max(series: dict, key: str):
    vals = [float(v) for v in (series or {}).get(key) or [] if v is not None]
    return round(max(vals)) if vals else None


def _oat_range(series: dict):
    vals = [float(v) for v in (series or {}).get("oat_c") or [] if v is not None]
    if not vals:
        return None
    return f"{min(vals):.0f} C to {max(vals):.0f} C"


# ATA chapter of each maintenance action the advisory layer can raise, worded
# as the event log words them (flight_record.ATA). Work on the engine itself is
# chapter 85, "Engine (Reciprocating)" in the FAA JASC table; 72 is the turbine
# engine chapter and used to be printed here for this piston engine.
_ACTION_ATA = {
    "A1": "79 Oil", "A2": "75 Engine cooling",
    "A3": "73 Engine fuel and control", "A4": "74 Ignition",
    "A5": "85 Engine (reciprocating)", "A6": "81 Exhaust turbocharger",
    "A7": "85 Engine (reciprocating)",
}


def _inr(x) -> str:
    """Rupees with Indian digit grouping: 5,00,000 rather than 500,000."""
    s = str(int(round(float(x))))
    if len(s) <= 3:
        return s
    head, groups = s[:-3], []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + s[-3:]


def _action_row(a: dict) -> dict:
    """One advisory action as Section 15 prints it.

    The advisory layer names its fields `name`, `due_within_hours` and
    `cost_inr`. This read `action`, `deadline` and `ata`, none of which exist,
    so every recommended action reached the document as "None / --- /
    500000.0".
    """
    due = a.get("due_within_hours")
    if a.get("deadline"):
        deadline = a["deadline"]
    elif due is None:
        # An ADVISORY action carries no hour limit: it is planned work.
        deadline = "Next scheduled maintenance"
    elif float(due) <= 0 or a.get("severity") == "EMERGENCY":
        deadline = "Before next flight"
    else:
        deadline = f"Within {float(due):.0f} flight hours"
    cost = a.get("cost")
    if cost is None and a.get("cost_inr") is not None:
        cost = f"INR {_inr(a['cost_inr'])}"
        if a.get("downtime_hours"):
            # :g, so half an hour of downtime does not print as "0 h".
            cost += f", {float(a['downtime_hours']):g} h downtime"
    ev = a.get("evidence")
    return {
        "action": a.get("action") or a.get("name") or a.get("summary"),
        "ata": a.get("ata") or _ACTION_ATA.get(str(a.get("action_id")),
                                               "72 Engine"),
        "deadline": deadline,
        "cost": cost,
        "evidence": a.get("reason") or (ev if isinstance(ev, str) else None),
    }


def _engine_name(md: dict):
    """The engine's published name, not its configuration key in capitals."""
    try:
        eng = config.load_engine(str(md.get("engine_key") or "rotax_915is"))
        # The published name lives under `identity:` in the engine file.
        return (eng.get("display_name")
                or (eng.get("identity") or {}).get("display_name")
                or md.get("engine_type"))
    except Exception:
        return md.get("engine_type")


def _months_since(when):
    if not when:
        return None
    import datetime as _dt
    try:
        t = _dt.datetime.fromisoformat(str(when).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return round((_dt.datetime.now(_dt.timezone.utc) - t).days / 30.44, 1)


def _cruise_readings(cd: dict, base: dict | None = None) -> list:
    """The stabilised datum as rows, corrected to standard day.

    ECTM compares the same reading at the same condition across months, so a
    reading taken on a day 20 C colder than standard is not comparable with one
    taken on a hot day -- and a trend built from the two is mostly weather.
    The first-order correction used here is the ISA temperature deviation:

        corrected = measured + (ISA temperature at this altitude - actual OAT)

    Applied to the TEMPERATURES only. Pressures and flows have their own
    corrections that need the engine's own maps, and applying a temperature
    deviation to a fuel flow would be worse than leaving it uncorrected -- so
    those rows carry the raw value and no correction, which the column heading
    then honestly reports as a dash.
    """
    if not cd:
        return []
    alt = cd.get("altitude_ft")
    oat = cd.get("oat_c")
    dev = None
    if alt is not None and oat is not None:
        isa_at_alt = _ISA_SL_C - _ISA_LAPSE_C_PER_FT * float(alt)
        dev = isa_at_alt - float(oat)

    comparable = False
    if base:
        try:
            comparable, _ = hist.FlightHistory._comparable(base, cd)
        except Exception:
            comparable = False

    rows = []
    for label, key, unit, correct in (
        ("Engine RPM", "rpm", "", False),
        ("Manifold Pressure", "manifold_pressure_bar", "bar", False),
        ("Cylinder Head Temp (max)", "cht_max_c", "C", True),
        ("Cylinder Head Spread", "cht_spread_c", "C", False),
        ("Exhaust Gas Temp (max)", "egt_max_c", "C", True),
        ("Exhaust Gas Spread", "egt_spread_c", "C", False),
        ("Oil Pressure", "oil_pressure_psi", "psi", False),
        ("Oil Temperature", "oil_temperature_c", "C", True),
        ("Coolant Temperature", "coolant_temperature_c", "C", True),
        ("Fuel Flow", "fuel_flow_lph", "L/h", False),
        ("Power", "power_kw", "kW", False),
    ):
        raw = cd.get(key)
        if raw is None:
            continue
        corrected = (round(float(raw) + dev, 1)
                     if (correct and dev is not None) else None)
        # Delta from the post-overhaul baseline -- the first flight on record
        # -- and only when the two datums were taken at a comparable condition,
        # the same rule the cross-flight trend applies. Otherwise a dash.
        b = (base or {}).get(key) if comparable else None
        delta = (round(float(raw) - float(b), 1)
                 if isinstance(b, (int, float)) else None)
        rows.append({"name": label, "raw": raw, "unit": unit,
                     "corrected": corrected, "delta": delta})
    return rows


def _scenario_verdict(r: dict) -> str:
    """One sentence a maintainer can act on, from a scenario result.

    The limiting parameter and its margin are the finding. A list of every
    sample is what the scenario screen is for.
    """
    exc = r.get("exceedances") or []
    if exc:
        return ("Limits exceeded: " + ", ".join(str(e) for e in exc[:3])
                + (" and others." if len(exc) > 3 else "."))
    lim = r.get("limiting")
    margin = r.get("limiting_margin_pct")
    if lim and margin is not None:
        return (f"Within limits. Closest approach was {lim}, "
                f"{margin:.1f} % margin remaining.")
    return "Within limits."


def _life_limits(md: dict, pipeline: dict) -> list:
    """Hours and calendar against every limit the twin already enforces.

    Life-limited PARTS are not modelled separately yet, so none are claimed.
    An empty parts table is a true statement about this build; an invented one
    would be a maintenance record asserting a part life nobody tracks.
    """
    # Time between overhaul runs from the last overhaul, not from new.
    used = pipeline.get("hours_since_overhaul")
    if used is None:
        used = pipeline.get("flight_hours")
    if used is None and md.get("total_flight_hours") is not None:
        used = (float(md["total_flight_hours"])
                - float(md.get("hours_at_last_overhaul") or 0.0))
    rows = []
    if used is not None and md.get("tbo_hours"):
        rows.append({"item": "Time between overhaul",
                     "used": round(float(used), 1),
                     "limit": float(md["tbo_hours"]), "unit": "h"})
    if md.get("tbo_calendar_years"):
        rows.append({"item": "Calendar limit since installation",
                     "used": (md.get("months_since_installation")
                              or _months_since(md.get("installation_date"))),
                     "limit": float(md["tbo_calendar_years"]) * 12.0,
                     "unit": "months"})
    return rows


def _local_window(start_iso: str | None, end_iso: str | None,
                  ident: dict) -> str | None:
    """The flight window in local time, for the crew who will read it.

    UTC is the record time: DGCA CAR 66 keeps the maintenance engineer's
    logbook in UTC, and is explicit that an entry must not mix local and Zulu.
    So this is an ADDITION beside the UTC window, never a replacement, and it
    always carries its zone name -- an unlabelled time on a maintenance record
    is the exact failure the rule exists to prevent.

    India's offset is +05:30, which is why this is minutes rather than hours.
    """
    import datetime as _dt

    if not start_iso or not end_iso:
        return None
    tz = str(ident.get("local_timezone", "IST"))
    offset = _dt.timedelta(
        minutes=int(ident.get("local_utc_offset_minutes", 330)))
    try:
        a = _dt.datetime.strptime(start_iso, "%Y-%m-%dT%H:%M:%SZ") + offset
        b = _dt.datetime.strptime(end_iso, "%Y-%m-%dT%H:%M:%SZ") + offset
    except (TypeError, ValueError):
        return None
    fmt = "%d %b %Y %H:%M"
    # The end date is printed too when the sortie crosses midnight -- an
    # endurance mission usually does, and "04:12 to 04:06" reads as backwards
    # rather than as the next day.
    if a.date() == b.date():
        return f"{a.strftime(fmt)} to {b.strftime('%H:%M')} {tz}"
    return f"{a.strftime(fmt)} to {b.strftime(fmt)} {tz}"


app = FastAPI(
    title="Aero Piston Engine Digital Twin",
    description="DRDO / IDEX PS 26054 -- MALE UAV engine health monitoring",
    version=GCS_VERSION,
    lifespan=lifespan,
)
# The console is served from the same origin in production; CORS is open only
# so a Vite dev server on another port can reach the API during development.
# CORS is NOT wide open. allow_origins=["*"] with credentials is how a console
# on one origin ends up accepting a token minted for another; the console is
# served by this same process, so same-origin plus explicit localhost origins
# for a separate `vite dev` is the whole legitimate set.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000", "http://localhost:8000",
        "http://127.0.0.1:5173", "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"]
)


# THE MAP TILE HOSTS, NAMED ONE BY ONE.
#
# The mission planner draws a real map, and its tiles come from outside. The
# policy above refused them -- correctly, since it allows only what the console
# itself serves -- and the map came up black with "no route to the tile
# service" written across it.
#
# Widening `img-src` to these five hosts is a narrow and reversible decision,
# and a different kind from the one refused for the 3D model's decoder: that
# would have allowed a WORKER from a blob: URL the policy cannot inspect, which
# is executable. These are images, from named origins, over TLS.
#
# DT_MAP_TILES=off removes them. A fielded, air-gapped station should set it:
# the map then shows no imagery and says so, and the route, the reach rings and
# the terrain clearance all still work, because those are computed here.
_MAP_TILE_HOSTS = (
    "https://*.tile.opentopomap.org",
    "https://tile.openstreetmap.org",
    "https://server.arcgisonline.com",
    "https://*.basemaps.cartocdn.com",
    "https://s3.amazonaws.com",
)
_MAP_TILE_SRC = ("" if os.environ.get("DT_MAP_TILES", "on").lower() == "off"
                 else " " + " ".join(_MAP_TILE_HOSTS))


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Browser hardening on every response (SEC-12).

    None was set: the console could be framed by another page (clickjacking)
    and responses could be MIME-sniffed. The policy allows exactly what the
    built console uses -- its own scripts, styles and images, inline style
    attributes, and a same-origin WebSocket -- and nothing from elsewhere.
    """
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "no-referrer")
    if demo.enabled():
        # Reached from the link in the deck, never found by a search.
        h.setdefault("X-Robots-Tag", "noindex, nofollow")
    h.setdefault("Content-Security-Policy",
                 f"default-src 'self'; img-src 'self' data:{_MAP_TILE_SRC}; "
                 "style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; "
                 "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    return resp


def _twin() -> LiveTwin:
    if twin is None:
        raise HTTPException(503, "the twin is not running")
    return twin


# ---------------------------------------------------------------------------
# Authentication and authorisation (PRD Part 4 s10, thresholds.security)
# ---------------------------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)
AUDIT = sec.AuditLog()
LIMITER = sec.RateLimiter()
# Per-account backoff. LIMITER is per client address, which does not
# touch the distributed case: the same account tried slowly from many
# hosts. Credential stuffing is distributed by construction.
LOGIN_GUARD = sec.LoginGuard()


class LoginRequest(BaseModel):
    username: str
    password: str


AUTH_FAIL_LIMITER = sec.RateLimiter(per_minute=30)


def claims(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Verify the bearer token, or refuse.

    Every protected route depends on this. PRD Part 4 s10c: authorisation is
    enforced HERE, server-side, regardless of what the console chose to render.
    """
    if cred is None:
        raise HTTPException(401, "authentication required")
    try:
        c = sec.verify_token(cred.credentials)
    except sec.AuthError as exc:
        # Rejected tokens are rate-limited PER CLIENT ADDRESS before anything is
        # written (RT-05, SEC-09). Every rejection appended an audit record and
        # the per-subject limiter below only runs once a token verifies, so an
        # unauthenticated flood grew the log without bound and slowed every
        # audited action. The reply is generic: the token library's own detail
        # helps nobody but the sender (SEC-12). The audit entry keeps it.
        ip = request.client.host if request.client else "?"
        if not AUTH_FAIL_LIMITER.allow(ip):
            raise HTTPException(429, "too many rejected requests") from exc
        AUDIT.record("AUTH", subject="unknown", role="none",
                     outcome="rejected", reason=str(exc),
                     path=request.url.path)
        raise HTTPException(401, "invalid or expired token") from exc

    if not LIMITER.allow(str(c.get("sub", "?"))):
        raise HTTPException(429, "rate limit exceeded")
    if demo.enabled():
        demo.touch()
    return c


# ---------------------------------------------------------------------------
# What each role may see IN THE STREAM
# ---------------------------------------------------------------------------
#
# The REST routes are each gated on a scope, but the WebSocket used to check
# only ``read:telemetry`` and then send the WHOLE snapshot -- so the costed
# maintenance plan, guarded behind ``read:advisory`` on /api/maintenance, was
# being handed to every authenticated role twice a second anyway. The console
# declined to RENDER it, which is not the same thing as the server declining to
# SEND it, and PRD Part 4 section 10c puts enforcement server-side precisely so
# that the difference matters.
#
# So the stream is now filtered by the same scopes the REST surface uses.
#
# A withheld section is sent as an explicit refusal rather than omitted. An
# absent key reaches the console as ``undefined`` and renders as "---", which
# is the console's notation for a DEAD SENSOR (section 7.2): an operator would
# read a permissions boundary as a hardware failure. Saying "not authorised"
# keeps the two apart.
SNAPSHOT_SCOPES: dict[str, str] = {
    "twin": "read:telemetry",
    "trend": "read:telemetry",
    # The same channels as `history`, decimated across the whole sortie. It is
    # engine telemetry, so it carries telemetry's scope -- not the clock-field
    # exemption, which is only for a time and a date.
    "flight_series": "read:telemetry",
    "history": "read:telemetry",
    "pipeline": "read:telemetry",
    "battery": "read:telemetry",
    "efficiency": "read:telemetry",
    # The operator's own view. Every authenticated role reaching the console
    # gets it -- it is the least privileged thing in the snapshot, being the
    # summary the least privileged role exists to read. The RUL figure inside
    # it is suppressed for a role without read:prognostics by the page itself,
    # and the raw rul section remains separately gated.
    "display": "read:telemetry",
    # Which sortie this is and whether it has ended. The operator starts the
    # next one from it, so it carries the least privileged scope; it holds a
    # phase, a count and a stop reason -- no health or prognostic figure.
    "sortie": "read:telemetry",
    "health": "read:health",
    "fusion": "read:health",
    "explanation": "read:health",
    "mission": "read:mission",
    "rul": "read:prognostics",
    # Calibrated P(fail within h). Prognostics, on the same footing as the RUL
    # section beside it: it answers the same question -- how long has this
    # engine got -- in the form that is actually accurate on this data. Gating
    # it lower than `rul` would let a role read the better estimate while being
    # refused the worse one.
    "survival": "read:prognostics",
    "maintenance": "read:advisory",
    # Per-fault time-to-action. Prognostics: a prediction about when a fault
    # will need work, which is the maintenance planner's question.
    "fault_forecast": "read:prognostics",
    # The post-flight record. Reports, not live telemetry: it is the
    # debrief material, and read:reports is the scope the maintenance
    # role holds for exactly that.
    "flight_record": "read:reports",
    # The injected ground truth. An operator who can read this is being told
    # the answer the system is supposed to be deducing, which would make any
    # demonstration of the detector meaningless.
    "faults_injected": "run:simulation",
}


# Fields INSIDE the operator view that need more than the view itself.
#
# ``display`` is gated on read:telemetry because it is the summary the least
# privileged role exists to read -- but it carries a remaining-life figure, and
# that is prognostics. Hiding it only in the page would put the number on the
# wire for a role refused it everywhere else, which is exactly the defect
# DEV-107 was about, reintroduced one level down.
NESTED_SCOPES: dict[str, dict[str, str]] = {
    "display": {
        "rul_hours": "read:prognostics",
        "mission_success_pct": "read:mission",
    },
}


def snapshot_for_role(snap: dict, role: str) -> dict:
    """Redact a snapshot down to what one role is authorised to receive."""
    out = {}
    for key, value in snap.items():
        scope = SNAPSHOT_SCOPES.get(key)
        if scope is not None and not sec.has_scope(role, scope):
            out[key] = {"authorised": False, "scope": scope}
            continue
        nested = NESTED_SCOPES.get(key)
        if nested and isinstance(value, dict):
            # Removed, not nulled to a plausible-looking zero: the console
            # renders an absent figure as "not predicted", which is true, where
            # a 0 would read as an engine with no life left.
            value = {
                k: v for k, v in value.items()
                if k not in nested or sec.has_scope(role, nested[k])
            }
        out[key] = value
    return out


def require(scope: str):
    """Dependency factory: this route needs this scope.

    A refusal is AUDITED. An audit log that records only what succeeded is not
    an audit log -- the attempts that were refused are usually the interesting
    ones, which is why AUTHZ_DENY is one of the configured event types.
    """

    def _dep(request: Request, c: dict = Depends(claims)) -> dict:
        role = str(c.get("role", ""))
        if not sec.has_scope(role, scope):
            AUDIT.record("AUTHZ_DENY", subject=str(c.get("sub", "?")),
                         role=role, scope=scope, path=request.url.path)
            # 403, not 404: the caller is authenticated and the resource
            # exists. Hiding that would only mislead a legitimate operator who
            # has been given the wrong role.
            raise HTTPException(403, f"role {role} lacks scope {scope!r}")
        return c

    return _dep


@app.post("/api/auth/login")
def login(req: LoginRequest, request: Request) -> dict:
    """Exchange credentials for a short-lived access token."""
    if not LIMITER.allow(f"login:{request.client.host if request.client else '?'}"):
        raise HTTPException(429, "rate limit exceeded")
    # An account already backed off is refused before the password is even
    # checked, and with the SAME message a wrong password gets -- saying
    # "locked" would confirm the account exists.
    # Not in the demonstration copy: every evaluator shares four accounts, so
    # one person's typos would lock out everyone after them.
    wait = 0.0 if demo.enabled() else LOGIN_GUARD.locked_for(req.username)
    if wait > 0:
        AUDIT.record("AUTH", subject=req.username, role="none",
                     outcome="locked_out")
        logging.getLogger("layer4_core.twin_api").warning(
            "login refused, account backed off",
            extra={"subject": req.username, "wait_s": round(wait, 1)},
        )
        raise HTTPException(401, "invalid credentials")

    try:
        role = sec.authenticate(req.username, req.password)
    except sec.AuthError as exc:
        wait = 0.0 if demo.enabled() else LOGIN_GUARD.record_failure(req.username)
        AUDIT.record("AUTH", subject=req.username, role="none",
                     outcome="failed")
        logging.getLogger("layer4_core.twin_api").warning(
            "login failed",
            extra={"subject": req.username, "backoff_s": round(wait, 1)},
        )
        # Deliberately vague, and identical for a bad password and an unknown
        # user: distinguishing them enumerates accounts.
        raise HTTPException(401, "invalid credentials") from exc

    LOGIN_GUARD.record_success(req.username)
    # A first-run credential must be replaced before the account is used
    # (SEC-02). The flag was set on every seeded account and checked by
    # nothing: after 911 logins all four accounts still carried it, and the
    # plain-text file of those passwords was still on disk.
    # DT_ALLOW_INITIAL_PASSWORDS=1 keeps a demonstration usable and says so in
    # the log on every such login.
    if sec.must_change_password(req.username):
        if os.environ.get("DT_ALLOW_INITIAL_PASSWORDS") == "1":
            logging.getLogger("layer4_core.twin_api").warning(
                "first-run password accepted because "
                "DT_ALLOW_INITIAL_PASSWORDS=1; never set this outside a "
                "demonstration", extra={"subject": req.username})
        else:
            AUDIT.record("AUTH", subject=req.username, role=role,
                         outcome="password_change_required")
            raise HTTPException(403, "password change required")
    AUDIT.record("AUTH", subject=req.username, role=role, outcome="success")
    if demo.enabled():
        demo.touch()
    # SIGNING IN NO LONGER STARTS THE ENGINE. It used to put the aircraft
    # back on the ground and fly a sortie by itself, so every login restarted
    # a flight nobody had authorised. The engine now starts when an operator
    # starts it for an approved mission (/api/ops/missions/{id}/start) or a
    # maintainer runs it on the ground.
    return {
        "access_token": sec.issue_token(req.username, role),
        "refresh_token": sec.issue_token(req.username, role, refresh=True),
        "token_type": "bearer",
        "role": role,
        "scopes": sorted(sec.scopes_for(role)),
        "expires_in_s": int(config.load_thresholds()["security"]["jwt"]
                            ["access_token_minutes"]) * 60,
    }


class PasswordChange(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


@app.post("/api/auth/change_password")
def change_password(req: PasswordChange, request: Request) -> dict:
    """Replace a password, with the current one as proof (SEC-02).

    No token is needed or accepted: an account that must change its password
    is refused one until it has. The same rate limit and per-account backoff
    as login apply, and every token issued under the old password is revoked
    by `security.change_password`.
    """
    if demo.enabled():
        raise HTTPException(403, demo.REFUSAL)
    ip = request.client.host if request.client else "?"
    if not LIMITER.allow(f"pwchange:{ip}"):
        raise HTTPException(429, "rate limit exceeded")
    if LOGIN_GUARD.locked_for(req.username) > 0:
        raise HTTPException(401, "invalid credentials")
    try:
        sec.change_password(req.username, req.old_password, req.new_password)
    except sec.PolicyError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except sec.AuthError as exc:
        LOGIN_GUARD.record_failure(req.username)
        AUDIT.record("AUTH", subject=req.username, role="none",
                     outcome="password_change_failed")
        raise HTTPException(401, "invalid credentials") from exc
    LOGIN_GUARD.record_success(req.username)
    AUDIT.record("AUTH", subject=req.username, role="none",
                 outcome="password_changed")
    # Once no account still carries a first-run password, the plain-text file
    # of those passwords has no reason to exist.
    try:
        if not any(u.get("must_change") for u in sec._users().values()):
            (sec._users_db().parent / "FIRST_RUN_CREDENTIALS.txt").unlink(
                missing_ok=True)
    except OSError:
        pass
    return {"changed": True}


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


@app.post("/api/auth/refresh")
def refresh_access(req: RefreshRequest, request: Request) -> dict:
    """A new access token from the refresh token issued at sign-in.

    The 15-minute access token was never renewed, so the console's first
    reconnect after that was refused for good (HMI-03). Only a REFRESH token
    is accepted here, and only an ACCESS token anywhere else (SEC-07).
    """
    ip = request.client.host if request.client else "?"
    try:
        c = sec.verify_token(req.refresh_token, typ="refresh")
    except sec.AuthError as exc:
        if not AUTH_FAIL_LIMITER.allow(ip):
            raise HTTPException(429, "too many rejected requests") from exc
        AUDIT.record("AUTH", subject="unknown", role="none",
                     outcome="refresh_rejected", reason=str(exc))
        raise HTTPException(401, "invalid or expired token") from exc
    sub, role = str(c.get("sub", "")), str(c.get("role", ""))
    return {
        "access_token": sec.issue_token(sub, role),
        "token_type": "bearer",
        "role": role,
        "expires_in_s": int(config.load_thresholds()["security"]["jwt"]
                            ["access_token_minutes"]) * 60,
    }


@app.get("/api/auth/me")
def whoami(c: dict = Depends(claims)) -> dict:
    """Who the console is currently acting as (PRD Part 4 s10b)."""
    return {"subject": c.get("sub"), "role": c.get("role"),
            "scopes": c.get("scopes", []), "expires": c.get("exp")}


@app.get("/api/demo")
def demo_accounts() -> dict:
    """The accounts the login screen lists on the demonstration copy.

    Unauthenticated, because it is read before anyone has signed in. On a real
    station it discloses nothing: ``{"demo": false}`` and no accounts.
    """
    if not demo.enabled():
        return {"demo": False, "accounts": []}
    return {"demo": True, "accounts": demo.accounts()}


class TestRigRequest(BaseModel):
    """A ground run on the bench.

    ``use_live_engine`` runs the schedule against the degradation state of the
    engine currently flying, which answers the question a maintenance officer
    actually asks -- "would this engine pass a bench test today?" -- without
    taking it off the aircraft.
    """

    schedule: str = "acceptance"
    cell_temperature_c: float = Field(25.0, ge=-40.0, le=55.0)
    cell_elevation_ft: float = Field(500.0, ge=-500.0, le=15000.0)
    # Expressed as the airspeed giving the same radiator conductance. Below
    # roughly 120 km/h-equivalent a cell cannot hold this engine in limits at
    # full power and the run is attributed to the facility -- see DEV-86.
    cell_cooling_kmh: float = Field(200.0, ge=0.0, le=400.0)
    use_live_engine: bool = False
    # Bounded (RT-08): an unbounded int reached numpy's seeding and returned a
    # 500 with a traceback in the log instead of a 422.
    seed: int = Field(0, ge=0, le=2**32 - 1)


class MissionScenario(BaseModel):
    """A fault scheduled inside one simulated sortie.

    `onset_s` is seconds INTO THE SORTIE, which is what makes injection during
    playback meaningful: the operator stops at T+01:12:30, asks for a misfire
    from there, and the sortie is re-flown with the fault appearing at that
    second and not before.

    SENSOR DRIFT IS NOT ACCEPTED HERE. A drift is expressed in the INSTRUMENT
    layer of the twin's own simulator; the flight model has no instrument layer
    to drift, so the request would produce a sortie identical to the baseline
    and a result that looked like a finding. It belongs in the twin lab, where
    there is an instrument to watch.
    """

    mode: str
    severity: float = Field(0.7, ge=0.0, le=1.0)
    ramp_hours: float = Field(0.05, gt=0.0, le=500.0)
    onset_s: float = Field(0.0, ge=0.0)
    channel: str | None = None


class RouteWaypoint(BaseModel):
    name: str = Field("WP", max_length=24)
    lat_deg: float = Field(..., ge=-90.0, le=90.0)
    lon_deg: float = Field(..., ge=-180.0, le=180.0)
    altitude_ft: float = Field(15000.0, ge=0.0, le=30000.0)


class RouteRequest(BaseModel):
    """A proposed sortie, in the terms an operator plans it in."""

    waypoints: list[RouteWaypoint] = Field(..., min_length=2, max_length=24)
    true_airspeed_kmh: float = Field(175.0, gt=0.0, le=400.0)
    isa_deviation_c: float = Field(0.0, ge=-40.0, le=50.0)
    # THE SAME DAY THE SORTIE WOULD BE FLOWN ON. `RouteAssumptions` has always
    # carried a humidity and `/api/mission/flight` has always forwarded one;
    # this endpoint did not, so it was pinned at 30 % and the costed figure and
    # the flown figure quietly described two different days.
    humidity_pct: float = Field(30.0, ge=0.0, le=100.0)
    usable_fuel_l: float = Field(120.0, gt=0.0, le=1000.0)


class FlightRequest(RouteRequest):
    """The same sortie, to be FLOWN rather than costed.

    Two fields more than RouteRequest, and both of them are the point.

    ``humidity_pct`` because the problem statement asks for the engine under
    varying environmental conditions, and humidity is one of the three the
    atmosphere model takes. A hot day and a hot WET day are not the same day to
    a turbocharged engine: water vapour displaces the oxygen the charge air was
    supposed to be carrying.

    ``use_live_engine`` because there are two different questions here and
    conflating them would be the defect. True asks whether the engine that is
    flying NOW, worn as it is, can fly this sortie. False asks whether the TYPE
    can -- a fresh engine, which is what a flight-planning manual answers.
    Defaults to the live engine, because that is the question this system
    exists to answer and the one no manual can.
    """

    humidity_pct: float = Field(30.0, ge=0.0, le=100.0)
    use_live_engine: bool = True
    # A FAULT THIS SIMULATION IS FLOWN AGAINST, AND NOTHING ELSE.
    #
    # /api/faults/inject puts a fault into the engine that is actually running,
    # which is the right answer for a demonstration and the wrong one for a
    # planning question: it changes the health index, the remaining life and
    # every alert on every page, permanently, to answer "what if". This one is
    # handed to the simulation, applied to a degradation engine that simulation
    # owns, and discarded with it. The live twin is never touched.
    scenario: MissionScenario | None = None
    # Begin with the engine STOPPED AND COLD, on the starter, and let it catch
    # on the model's own dynamics -- so the speed, the oil pressure and every
    # temperature rise from a standstill at ambient the way they do on the
    # aircraft, and the warm-up runs until the oil reaches the temperature the
    # manual requires before take-off. False begins from a warm running engine,
    # which is the right question when only the airborne part is being asked
    # about and saves the minutes of ground running.
    start_engine: bool = True


class FaultRequest(BaseModel):
    mode: str
    severity: float = Field(0.7, ge=0.0, le=1.0)
    ramp_hours: float = Field(0.05, gt=0.0, le=500.0)
    # Which instrument drifts. SENSOR_DRIFT only; a drift afflicts one
    # transducer and which one decides how it is detectable at all -- rpm only
    # through the FADEC lane delta, the rest through their physics residual.
    channel: str | None = None


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@app.get("/api/state")
def get_state(c: dict = Depends(require("read:telemetry"))) -> JSONResponse:
    """The complete current snapshot -- what the WebSocket streams."""
    # json.dumps refuses NaN and infinity, and a SINGLE one anywhere in the
    # snapshot returns 500 for the whole endpoint -- which is the one the
    # console lives on. A stray non-finite value is a bug to fix at its source
    # (and one was: health.track returned float("nan") for an unestablished
    # baseline), but the console must not go dark because of it. Non-finite
    # becomes null, which is what "no value" means over JSON.
    return JSONResponse(_json_safe(asdict(_twin().snapshot())))


@app.get("/api/engine")
def get_engine(c: dict = Depends(require("read:telemetry"))) -> dict:
    """Identity, certified limits and thresholds, for the console's scales.

    Served rather than hardcoded in the front end so that the limits drawn on
    a gauge are the same limits the rule engine alerts on. A console with its
    own copy of the numbers will disagree with the system eventually, and the
    operator will believe the console.
    """
    eng = config.load_engine(_twin().engine_key)
    t = config.load_thresholds()
    return {
        "identity": eng["identity"],
        "ratings": eng["ratings"],
        "limits": eng["limits"],
        "parameters": t["parameters"],
        "chi_bands": t["health"]["chi_bands"],
        # The weights the composite health index is built from. Served for the
        # same reason as the bands beside them: the Health page shows how chi
        # was arrived at -- each subsystem weighted, then summed -- and a
        # console carrying its own copy of those four numbers would eventually
        # disagree with the estimator that produced the score it explains.
        "composite_weights": t["health"]["composite_weights"],
        "alert_levels": t.get("alerts", {}),
    }


@app.get("/api/faults")
def get_faults(c: dict = Depends(require("read:telemetry"))) -> list[dict]:
    """The eight problem-statement faults available for demonstration."""
    return available_faults()


@app.post("/api/faults/inject")
def inject_fault(req: FaultRequest, c: dict = Depends(require("run:simulation"))) -> dict:
    """Inject a fault into the running engine.

    Deliberately a POST with an explicit body rather than a click-to-fire
    control: PRD Part 4 section 9 requires a deliberate action for anything
    that changes system state.
    """
    try:
        return _twin().inject(req.mode, req.severity, req.ramp_hours,
                              channel=req.channel)
    except ValueError as exc:
        # inject() raises ValueError for an unknown MODE and for an instrument
        # this engine does not have. Reporting both as "unknown fault mode"
        # sent whoever typed the channel looking in the wrong place.
        raise HTTPException(400, str(exc) if "instrument" in str(exc)
                            else f"unknown fault mode '{req.mode}'") from exc


@app.get("/api/faults/failures")
def list_failures(c: dict = Depends(require("run:simulation"))) -> list[dict]:
    """The sudden failures the running engine can be given."""
    from layer4_core.live import LiveTwin
    return [{"name": k, "label": v[0], "description": v[1]} for k, v in LiveTwin.FAILURES.items()]


class FailureRequest(BaseModel):
    name: str = Field(max_length=40)


@app.post("/api/faults/failure")
def inject_failure(req: FailureRequest, c: dict = Depends(require("run:simulation"))) -> dict:
    """A sudden engine failure -- fuel, ignition, oil or coolant."""
    who, role = _who(c)
    try:
        out = _twin().fail(req.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    AUDIT.record("STATE_MUTATION", subject=who, role=role, change="failure", failure=req.name)
    return out


@app.post("/api/faults/clear")
def clear_faults(c: dict = Depends(require("run:simulation"))) -> dict:
    """Clear every injected fault, and repair failed instruments and lanes."""
    _twin().clear_faults()
    return {"cleared": True}


@app.get("/api/faults/sensors")
def sensor_failure_options(c: dict = Depends(require("read:telemetry"))) -> dict:
    """The instrument and FADEC-lane failures that can be injected."""
    from layer2_physics.engine_sim import LANE_FAILURES_SUPPORTED
    rows = config.load_engine(_twin().engine_key)["failure_matrix"]["items"]
    lanes = sorted({(r["item"], str(r["lane"])) for r in rows
                    if r["item"] in LANE_FAILURES_SUPPORTED})
    return {"channels": sorted(LiveTwin.SENSOR_FAILURES),
            "modes": ["frozen", "stuck"],
            "lane_items": [{"item": i, "lane": ln} for i, ln in lanes]}


class SensorFailureRequest(BaseModel):
    channel: str = Field(min_length=1, max_length=64)
    mode: str = Field(pattern="^(frozen|stuck)$")


class LaneFailureRequest(BaseModel):
    item: str = Field(min_length=1, max_length=64)
    lane: str = Field(pattern="^[AB]$")


@app.post("/api/faults/sensor")
def inject_sensor_failure(req: SensorFailureRequest,
                          c: dict = Depends(require("run:simulation"))) -> dict:
    """Fail one instrument, to demonstrate that the checks find it."""
    try:
        return _twin().fail_sensor(req.channel, req.mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/faults/lane")
def inject_lane_failure(req: LaneFailureRequest,
                        c: dict = Depends(require("run:simulation"))) -> dict:
    """Fail one FADEC item on one lane."""
    try:
        return _twin().fail_lane(req.item, req.lane)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sortie/start")
def start_sortie(c: dict = Depends(require("control:sortie"))) -> dict:
    """Retired: a sortie is flown for an approved mission, not on demand."""
    raise HTTPException(409, "the engine is started for an approved mission: "
                             "FLIGHT page, or /api/ops/missions/{id}/start")


@app.post("/api/alerts/acknowledge")
def acknowledge(c: dict = Depends(require("ack:alert"))) -> dict:
    """Master warning/caution reset.

    MIL-STD-411F 5.2.7: acknowledging silences the annunciator but must NOT
    clear the underlying condition, and the master must RE-ARM so a later,
    different alert lights it again. Both behaviours live in the rule engine.
    """
    _twin().acknowledge()
    return {"acknowledged": True}


@app.get("/api/report")
def mission_report(c: dict = Depends(require("read:reports"))) -> dict:
    """Mission-wise health report (PS section F).

    Assembled from the twin rather than recomputed, so the report and the live
    display can never disagree about what happened.
    """
    s = _twin().snapshot()
    md = s.twin.get("metadata", {})
    hist = s.twin.get("history", {})
    ident = config.load_report_identity()
    fr = s.flight_record or {}

    # Cover identity. Every field is derived from the running twin or from
    # deployment config -- none is a literal in the report generator, because a
    # cover that always says the same airframe is worse than one that says
    # nothing.
    # This flight's own length, from its record -- not the station's uptime.
    duration_h = _flight_hours_span(s.flight_series) or round(float(s.t_s) / 3600.0, 2)
    tasking = _mission_for_report()
    hours_after = s.pipeline.get("flight_hours")
    hours_before = (None if hours_after is None
                    else round(float(hours_after) - duration_h, 2))
    # The tasking authority owns mission numbers. This is the ground station's
    # own reference, used when none was supplied.
    # From the DATED stamp, not the console clock: wall_utc is a time of day,
    # so slicing it produced "MISSION-15:30:22Z-..." -- a reference with colons
    # in it that also failed to say which day.
    flown = (s.started_iso or s.wall_iso or "")
    mission_ref = tasking.get("id") or "{}-{}-{}".format(
        ident.get("mission_prefix", "MISSION"),
        flown[:10].replace("-", "") or "UNDATED",
        str(md.get("twin_id") or "TWIN"))
    serial = ident.get("engine_serial") or "{}/{}".format(
        str(md.get("engine_key", "engine")).upper(),
        str(md.get("twin_id") or "UNSERIALISED"))

    return {
        "twin_id": md.get("twin_id"),
        "mission_id": mission_ref,
        "aircraft_id": md.get("aircraft_id"),
        "engine": _engine_name(md),
        "engine_serial": serial,
        "location": ident.get("location"),
        "operator": ident.get("operator"),
        "classification": ident.get("classification"),
        "report_version": "1.0",
        "gcs_version": _version(),
        "date": (flown[:10] or None),
        # The flight's own window, not the instant somebody pressed export.
        # UTC is the record time -- DGCA CAR 66 keeps the maintenance logbook
        # in UTC and forbids mixing local and Zulu in one entry.
        "window_utc": ("{} to {}".format(s.started_iso, s.wall_iso)
                       if s.started_iso and s.wall_iso else s.wall_iso or None),
        # IST beside it, for the crew who will actually read this at the base.
        # Both are labelled; neither is ever printed as a bare time.
        "window_local": _local_window(s.started_iso, s.wall_iso, ident),
        "local_timezone": ident.get("local_timezone", "IST"),
        "generated_utc": s.wall_iso or s.wall_utc,
        "mission": {
            "simulated_seconds": round(s.t_s, 1),
            "duration_h": duration_h,
            "hours_before": hours_before,
            "flight_hours": hours_after,
            "start_stop_cycles": md.get("total_cycles"),
            "thermal_cycles": hist.get("thermal_cycles"),
            # From the whole-flight series when the life-to-date history does
            # not carry it: the flight's own ceiling, not a blank.
            "max_altitude_ft": (hist.get("max_altitude_ft")
                                or _series_max(s.flight_series, "altitude_ft")),
            "oat_range": _oat_range(s.flight_series) or "---",
            # The squadron's tasking when there is one; the twin's own
            # profile name only when the flight was not a tasked mission.
            "mission_type": (tasking.get("task") or md.get("mission_type")
                             or ("Ground run" if (s.sortie or {}).get("kind") == "ground_run"
                                 else "ISR patrol profile")),
            "tasking": tasking,
        },
        "health": s.health,
        "remaining_life": s.rul,
        "extremes": {
            "max_cht_c": hist.get("max_cht_recorded"),
            "max_coolant_c": hist.get("max_coolant_recorded"),
            "max_egt_c": hist.get("max_egt_recorded"),
            "max_rpm": hist.get("max_rpm_recorded"),
            "max_vibration": hist.get("max_vibration_recorded"),
            "time_above_max_continuous_s": hist.get("time_above_max_continuous_s"),
        },
        "advisory": s.twin.get("advisory", {}),
        "alerts": s.twin.get("alerts", {}),
        # What actually happened during the flight, as opposed to what is true
        # at the instant of export. Events carry the phase they occurred in,
        # exceedances carry time-above as well as peak, and the cruise datum is
        # the one row that can be trended against the flight before.
        # The cruise datum, with its readings laid out and the temperatures
        # corrected to standard day. Without this the section printed a table
        # of dashes beside a perfectly good reading.
        "flight_record": (
            {**s.flight_record,
             "cruise_datum": {**s.flight_record["cruise_datum"],
                              "readings": _cruise_readings(
                                  s.flight_record["cruise_datum"],
                                  _baseline_datum(_history_key(md)))}}
            if (s.flight_record or {}).get("cruise_datum")
            else s.flight_record),

        # ---- the sections that were rendering empty --------------------
        # The document had fifteen sections and the payload fed five of them.
        # Everything below already existed on the snapshot and simply was not
        # being handed over.

        # s11.2 -- the calibrated failure probability. The most accurate
        # prognostic this system produces, and it was reaching the live console
        # and stopping there.
        "survival": s.survival,

        # s03 and s04.2 -- the time histories. `cht_pred` is the twin's own
        # prediction of cylinder head temperature, which is what makes 4.2 a
        # twin-versus-actual chart rather than a second copy of 3.1.
        "history": _series(s.flight_series, (
            ("rpm", "rpm"), ("cht_max", "cht"), ("egt_max", "egt"),
            ("oil_pressure", "oil_pressure"),
            ("oil_temperature", "oil_temperature"),
            ("fuel_flow", "fuel_flow"),
            ("manifold_pressure", "manifold_pressure"),
            ("vibration_rms_total", "vibration_rms_total"),
        )),
        "twin_overlay": {
            "actual": _one_series(s.flight_series, "cht"),
            "twin": _one_series(s.flight_series, "cht_pred"),
        },

        # s10 -- all eight PS fault modes, each with the indicator it is judged
        # on, that indicator's value against its threshold, and where the trend
        # is going. Detection is `status == "reached"`, which is the forecast's
        # own word for the indicator having crossed its limit.
        #
        # The first version inferred detection from `hours_to_action <= 0`.
        # That is a FORECAST of when action becomes due, not a detection, and
        # it is None whenever the indicator is flat -- so a report on an engine
        # with an actively injected cooling fault said "No" against all eight
        # modes while the forecast was carrying the whole story.
        "faults": [
            {"name": f.get("mode"),
             "detected": f.get("status") == "reached",
             "status": f.get("status"),
             "indicator": f.get("indicator"),
             "value": f.get("value"),
             "threshold": f.get("threshold"),
             "unit": f.get("unit"),
             "hours_to_action": f.get("hours_to_action"),
             "reason": f.get("reason")}
            for f in (s.fault_forecast or [])
        ],

        # s12 -- hours and cycles against every limit the twin enforces.
        "life_limits": _life_limits(md, s.pipeline),

        # s02.2 -- the flight actually flown, not just the engine.
        "profile": {
            "altitude_ft": _one_series(s.flight_series, "altitude_ft"),
            "airspeed_kt": _one_series(s.flight_series, "airspeed_kt"),
        },

        # s03.2 -- the conditions the sortie was flown in. A cylinder head is
        # hotter on a hot day at low airspeed, and a reader who cannot see the
        # day reads that as deterioration.
        # Taken from the flight record, which accumulates over the whole
        # sortie, NOT from s.history -- that is a ring buffer of the last few
        # minutes and would report the descent as the flight's weather.
        "environment": (s.flight_record or {}).get("environment", {}),

        # s09 -- the change column. The flight being reported is not written
        # until shutdown, so the newest row in history IS the previous flight.
        "health_previous": (history.previous_health(_history_key(md))
                            if history is not None else {}),

        # s14.2 -- the what-if runs actually performed against this twin.
        "whatif": [
            {"scenario": r.get("name") or k,
             "result": _scenario_verdict(r)}
            for k, r in SCENARIO_RUNS.items()
        ],

        # s08 -- drift across flights, from the persistent flight history.
        # Empty until two COMPARABLE flights exist, and it says so rather
        # than drawing a line through one point.
        "trend": _trend_series(history, _history_key(md)),

        # s14.1 -- the recording this report can be replayed from. No position
        # track: the recorder stores engine channels, not navigation, so the
        # map states that rather than drawing an invented flight path.
        "replay": ({
            "recording_id": Path(getattr(recorder, "path", "") or "").stem or None,
            "window": ("{} to {}".format(s.started_iso, s.wall_iso)
                       if s.started_iso and s.wall_iso else None),
            "samples": getattr(recorder, "rows", None),
            "href": "/api/replay",
        } if recorder is not None else {}),

        # s15 -- the costed plan the advisory layer already produces.
        "actions": [_action_row(a)
                    for a in ((s.maintenance or {}).get("actions") or [])],

        "faults_injected": s.faults_injected,
        "data_quality": s.pipeline.get("data_quality"),
        # Counted from the last overhaul, not from new.
        "tbo_hours_remaining": round(
            float(md.get("tbo_hours", 1200.0))
            - (float(md.get("total_flight_hours", 0.0))
               - float(md.get("hours_at_last_overhaul", 0.0))), 2
        ),
    }


import threading as _threading  # noqa: E402 - beside the one thing that uses it

# ONE heavy job at a time (RT-03). Test-rig runs, scenarios and PDF exports
# each take seconds to tens of seconds of CPU on worker threads, and with no
# limit three rig runs, a scenario and two exports took the live twin from
# 6.7 to 2.3 ticks per second (tick p95 632 ms). A second request is refused
# with 429 and a reason rather than queued silently behind the first.
_HEAVY = _threading.BoundedSemaphore(1)


@contextlib.contextmanager
def _heavy_job(what: str):
    if not _HEAVY.acquire(blocking=False):
        raise HTTPException(
            429, f"a simulation or export is already running; {what} not "
                 f"started -- retry when it finishes")
    try:
        yield
    finally:
        _HEAVY.release()


@app.get("/api/report.pdf")
def mission_report_pdf(c: dict = Depends(require("read:reports"))):
    """The same report as /api/report, as a filed document.

    A report that exists only on a screen is not one a maintenance
    organisation can use: the artefact that matters is the one that leaves the
    ground station and gets filed against the airframe.

    It is generated from the SAME payload the JSON route returns, so the
    document and the console cannot disagree about what happened -- and the
    generation is audited, because a report leaving the system is exactly the
    kind of event an audit log exists to record.
    """
    if not report_pdf.AVAILABLE:
        raise HTTPException(503, report_pdf.UNAVAILABLE_MESSAGE)

    with _heavy_job("PDF export"):
        payload = mission_report(c)
        pdf = report_pdf.build(payload)
    AUDIT.record("REPORT_EXPORT", subject=str(c.get("sub", "?")),
                 role=str(c.get("role", "")),
                 digest=report_pdf.digest(payload))

    simulated = "SIMULATED_" if payload.get("faults_injected") else ""
    name = f"{simulated}{payload.get('twin_id', 'engine')}_postflight.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        # `inline` so the browser opens it rather than dropping it in Downloads
        # unseen; the filename still applies when the reader chooses to save.
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


class CustomEnvRequest(BaseModel):
    """One operator-chosen operating point to hold and judge.

    The bounds are the ENVELOPE THIS MODEL IS ANCHORED IN, not arbitrary
    guardrails: the physics is validated against twelve published points inside
    it, and a request outside it would return a confident number the model has
    no standing to produce. Refusing is the honest answer.
    """

    altitude_ft: float = Field(0.0, ge=0.0, le=25000.0)
    oat_c: float | None = Field(None, ge=-60.0, le=60.0)
    # A hot or cold day as an ISA deviation, used when no OAT override is
    # given, and relative humidity, which changes air density (REP-08: neither
    # could be set, and humidity was a flat 30 % on every sortie).
    isa_deviation_c: float | None = Field(None, ge=-40.0, le=40.0)
    humidity_pct: float | None = Field(None, ge=0.0, le=100.0)
    airspeed_kmh: float = Field(180.0, ge=80.0, le=250.0)
    throttle_pct: float = Field(75.0, ge=20.0, le=100.0)
    duration_s: float = Field(600.0, ge=120.0, le=3600.0)


@app.post("/api/scenarios/custom")
def scenario_custom(req: CustomEnvRequest,
                    c: dict = Depends(require("run:simulation"))) -> dict:
    """Hold one operator-chosen environment and judge it (PS section E).

    The four named scenarios answer "environmental condition simulation" for
    four points. This answers it for any point inside the validated envelope,
    with the SAME physics and the same certificate limits -- both paths go
    through scenarios._fly, because two code paths would eventually disagree
    and the disagreement would be invisible.
    """
    with _heavy_job("custom scenario"):
        return scen.run_custom(
            altitude_ft=req.altitude_ft, oat_c=req.oat_c,
            isa_deviation_c=req.isa_deviation_c, humidity_pct=req.humidity_pct,
            airspeed_kmh=req.airspeed_kmh, throttle_pct=req.throttle_pct,
            duration_s=req.duration_s,
        ).as_dict()


@app.get("/api/faults/forecast")
def fault_forecast(c: dict = Depends(require("read:prognostics"))) -> dict:
    """When each of the eight PS fault modes will need action.

    PS section C asks for the "detection/prediction" of eight faults, and the
    two are different questions. Detection says a fault is present; a
    maintenance planner holding that alone cannot schedule anything. This
    answers WHEN -- by extrapolating each mode's own measured indicator to the
    threshold at which the system itself would raise the fault.
    """
    s = _twin().snapshot()
    return {"forecasts": s.fault_forecast, "generated_utc": s.wall_utc,
            "flight_hours": s.pipeline.get("flight_hours")}


@app.get("/api/report.csv")
def mission_report_csv(c: dict = Depends(require("read:reports"))):
    """The report as CSV, for a spreadsheet or a maintenance system.

    FLAT KEY/VALUE, not a wide single row. The report is a nested document and
    flattening it into columns would produce a header line nobody can read and
    a shape that breaks whenever a section is added. One row per field survives
    both, and sorts and filters in a spreadsheet the way a maintainer expects.

    The digest identifies THIS export and matches the audit row recording it.
    It does NOT make two separately fetched exports identical: each request
    generates a fresh report from the live twin, so the timestamp and the values
    differ between calls, and so do the digests. Saying otherwise would invite
    somebody to "verify" a CSV against a PDF pulled a minute later and conclude
    the system was inconsistent.
    """
    payload = mission_report(c)
    rows: list[tuple[str, str]] = []

    def walk(prefix: str, node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(f"{prefix}.{k}" if prefix else str(k), v)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(f"{prefix}[{i}]", v)
        else:
            rows.append((prefix, "" if node is None else str(node)))

    walk("", payload)
    buf = io.StringIO()
    # Explicit LF. csv defaults to CRLF, and a report opened in one tool and
    # diffed in another should not differ by invisible characters.
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["field", "value"])
    w.writerows(rows)
    w.writerow(["sha256", report_pdf.digest(payload)])

    AUDIT.record("REPORT_EXPORT", subject=str(c.get("sub", "?")),
                 role=str(c.get("role", "")), format="csv",
                 digest=report_pdf.digest(payload))
    simulated = "SIMULATED_" if payload.get("faults_injected") else ""
    name = f"{simulated}{payload.get('twin_id', 'engine')}_postflight.csv"
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/api/report.json")
def mission_report_json(c: dict = Depends(require("read:reports"))) -> JSONResponse:
    """The report as JSON, for a maintenance system to ingest.

    The same payload /api/report returns, with the digest attached, so an
    ingested record can be matched to the audit row that recorded its export.
    Audited like the other formats: a report leaving the system is the event,
    whatever format it leaves in.
    """
    payload = mission_report(c)
    digest = report_pdf.digest(payload)
    AUDIT.record("REPORT_EXPORT", subject=str(c.get("sub", "?")),
                 role=str(c.get("role", "")), format="json", digest=digest)
    simulated = "SIMULATED_" if payload.get("faults_injected") else ""
    name = f"{simulated}{payload.get('twin_id', 'engine')}_postflight.json"
    return JSONResponse(
        content={**payload, "sha256": digest},
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/api/mission")
def mission(c: dict = Depends(require("read:mission"))) -> dict:
    """Mission reliability -- Go/No-Go across every standard profile.

    The third pillar of the problem statement's title. Health monitoring says
    how the engine IS and fault prediction says what is coming; neither answers
    the question an operator actually asks, which is whether this engine can
    fly the mission in front of it.
    """
    s = _twin().snapshot()
    return {
        **s.mission,
        "health": s.health,
        "remaining_life": s.rul,
        "generated_utc": s.wall_utc,
    }


@app.post("/api/mission/route")
def assess_mission_route(req: RouteRequest,
                         c: dict = Depends(require("read:mission"))) -> dict:
    """What this proposed sortie costs the ENGINE, before it is flown.

    Every other route in this API reports on an engine that is already
    running. This one answers the question asked before it starts: given these
    waypoints, at these altitudes, on a day this hot -- can the engine do it,
    what will it cost, and which component is the limit?

    A flight planner already computes the fuel. What it cannot compute is that
    a leg holds the wastegate against its stop for forty minutes, leaving
    nothing for a go-around, or that the sortie costs 1.03 engine-hours of life
    for every clock hour flown. Those come from the same mean-value model the
    twin runs and the same wear model the fleet was generated with.

    NOT A FAST CALL. It flies the route through the physics minute by minute
    and then flies a reference sortie to price the wear against, so it takes
    tens of seconds for a long route. That is the correct trade for a planning
    decision: the alternative -- scaling a short reference -- was measured and
    moved the life figure by a third.

    Gated on `read:mission` rather than `run:simulation`: this changes nothing
    about the running engine, and mission planning is exactly what the
    commander and the operator hold that scope for.
    """
    from layer4_core import route_cost as rc

    try:
        cost = rc.assess_route(
            [rc.Waypoint(w.name, w.lat_deg, w.lon_deg, w.altitude_ft)
             for w in req.waypoints],
            rc.RouteAssumptions(
                true_airspeed_kmh=req.true_airspeed_kmh,
                isa_deviation_c=req.isa_deviation_c,
                humidity_pct=req.humidity_pct,
                usable_fuel_l=req.usable_fuel_l,
            ),
            engine_key=_twin().engine_key,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return cost.as_dict()


@app.get("/api/mission/envelope")
def mission_envelope(altitude_ft: float = 15000.0,
                     isa_deviation_c: float = 0.0,
                     usable_fuel_l: float = 120.0,
                     c: dict = Depends(require("read:mission"))) -> dict:
    """How far THIS engine can still go, against how far it could when new.

    The difference between the two radii is what predictive maintenance is for,
    in one number. An engine does not announce that it has degraded; it
    announces it by failing to reach somewhere it used to reach, usually on the
    day that matters.

    The worn engine is the twin's OWN current degradation, not a scenario: the
    same factors the health index and the fault heads are reading. The as-new
    engine is the same model with nothing worn.

    Like /api/mission/route this flies the physics rather than looking anything
    up, and it bisects the throttle to hold cruise power for each engine, so it
    takes tens of seconds.
    """
    from layer4_core import route_cost as rc

    tw = _twin()
    env = rc.reach_envelope(
        factors=tw.veng.degradation.factors,
        assumptions=rc.RouteAssumptions(isa_deviation_c=isa_deviation_c,
                                        usable_fuel_l=usable_fuel_l),
        engine_key=tw.engine_key,
        altitude_ft=altitude_ft,
    )
    return env.as_dict()


def _run_flight(job: dict) -> dict:
    """Fly a sortie, in a process of this function's own. Must be importable.

    THE REASON THIS IS NOT JUST A FUNCTION CALL.
    Flying a sortie is tens of thousands of numerical integration steps, and
    Python runs them holding the interpreter lock. In the server's own process
    that lock is shared with the twin thread, which is simulating the engine
    twenty times faster than real time and needs the CPU continuously. The two
    fought: measured in a browser, a request that takes about a minute run on
    its own took between four and seven minutes through the console, and the
    console's own twin got slower while it did.

    `route_cost` and `flight_sim` both dealt with that by sleeping between
    steps to hand the twin its CPU back, which was correct and which also made
    the assessment slower still.

    In a separate process there is no shared lock and no twin to yield to, so
    the sleeps are switched off and the work runs on a core of its own. The
    twin is unaffected because it is no longer sharing anything with it.

    Takes and returns plain data because everything crossing a process boundary
    is pickled, and a dict of floats is a contract this can rely on.
    """
    from layer4_core import flight_sim as fs
    from layer4_core import route_cost as rc

    # Nothing to stand aside for in here.
    fs.set_yield_s(0.0)
    rc.set_yield_s(0.0)

    scen = job.get("scenario")
    sim = fs.simulate(
        [rc.Waypoint(**w) for w in job["waypoints"]],
        rc.RouteAssumptions(**job["assumptions"]),
        engine_key=job["engine_key"],
        factors=job["factors"],
        start_engine=job["start_engine"],
        scenario=None if scen is None else fs.MissionFault(**scen),
    )
    return sim.as_dict()


# One worker, kept warm. Created on first use rather than at import, so that
# every script and test that imports this module does not pay for a process it
# will never ask anything of. Rebuilt if it ever dies.
_FLIGHT_POOL: object | None = None
_FLIGHT_POOL_LOCK = threading.Lock()


def _flight_pool():
    global _FLIGHT_POOL
    with _FLIGHT_POOL_LOCK:
        if _FLIGHT_POOL is None:
            from concurrent.futures import ProcessPoolExecutor
            _FLIGHT_POOL = ProcessPoolExecutor(max_workers=1)
        return _FLIGHT_POOL


@app.post("/api/mission/flight")
def simulate_mission_flight(req: FlightRequest,
                            c: dict = Depends(require("read:mission"))) -> dict:
    """Fly the sortie take-off to landing and report WHERE things go wrong.

    /api/mission/route answers the planner's question in totals -- litres,
    engine-hours, the limiting component. Totals are the right shape for a
    decision made at a desk and the wrong shape for the question asked in front
    of a map, which is *where*. A sortie that lands with coolant three degrees
    inside its limit and one that spends forty minutes against that limit over
    the target have nearly the same totals and are not the same sortie.

    So this returns the TRACK: a sample every ten seconds through take-off,
    climb, descent and landing and every minute in the cruise, each carrying
    position, altitude, phase, every engine temperature and pressure, the
    ground underneath and the fuel left -- plus an EVENT at every moment a
    certified limit is crossed, with the time, the place and the value, and a
    GO / GO WITH LIMITS / NO-GO verdict that says which finding decided it.

    THE ENGINE FLOWN IS THE ONE THAT IS FLYING. With use_live_engine the
    simulation carries the twin's own degradation factors, so the ceiling, the
    climb rate and the temperatures are this engine's today. That is the whole
    claim: a chart gives an aircraft one ceiling for its lifetime and a real
    engine does not have one ceiling for its lifetime.

    NOT A FAST CALL, for the same reason as /api/mission/route: it steps the
    mean-value model through the entire sortie. Tens of seconds for a long one.

    Gated on `read:mission`, like the rest of mission planning: it changes
    nothing about the running engine.
    """
    tw = _twin()
    job = {
        "waypoints": [{"name": w.name, "lat_deg": w.lat_deg,
                       "lon_deg": w.lon_deg, "altitude_ft": w.altitude_ft}
                      for w in req.waypoints],
        "assumptions": {
            "true_airspeed_kmh": req.true_airspeed_kmh,
            "isa_deviation_c": req.isa_deviation_c,
            "humidity_pct": req.humidity_pct,
            "usable_fuel_l": req.usable_fuel_l,
        },
        "engine_key": tw.engine_key,
        "factors": tw.veng.degradation.factors if req.use_live_engine else None,
        "start_engine": req.start_engine,
        "scenario": (None if req.scenario is None else {
            "mode": req.scenario.mode,
            "severity": req.scenario.severity,
            "ramp_hours": req.scenario.ramp_hours,
            "onset_s": req.scenario.onset_s,
            "channel": req.scenario.channel,
        }),
    }
    if req.scenario is not None:
        from layer2_physics.degradation import FaultMode
        try:
            mode = FaultMode(req.scenario.mode)
        except ValueError as exc:
            raise HTTPException(
                400, f"unknown fault mode '{req.scenario.mode}'") from exc
        if mode is FaultMode.SENSOR_DRIFT:
            # REFUSED WITH A REASON rather than flown into a null result. The
            # flight model has no instrument layer for a drift to express in,
            # so the sortie would come back identical to the baseline and the
            # zero difference would read as a finding.
            raise HTTPException(
                400, "sensor drift is expressed in the instrument layer, which "
                     "the flight model does not have; flying it would return a "
                     "sortie identical to the baseline. Use the twin lab.")
        if req.scenario.onset_s > 0 and not req.start_engine:
            # Not a bug, but it would quietly move the onset: the sortie is
            # shorter without the ground run, so the same second is a different
            # moment of the flight.
            _log.info("mission fault onset is measured from the start of the "
                      "sortie, which this request begins airborne")
    try:
        # ON ITS OWN CORE, SO THE TWIN KEEPS ITS OWN. See `_run_flight`.
        # Falls back to running here if a worker cannot be started at all --
        # a restricted host that forbids subprocesses should get a slow answer
        # rather than no answer.
        try:
            out = _flight_pool().submit(_run_flight, job).result()
        except Exception as exc:                       # noqa: BLE001
            from concurrent.futures.process import BrokenProcessPool
            if isinstance(exc, (FileNotFoundError, ValueError)):
                raise
            global _FLIGHT_POOL
            if isinstance(exc, BrokenProcessPool):
                _FLIGHT_POOL = None                    # rebuilt on next request
            # `_log` is a Logger, not a callable. Called like this it raised
            # TypeError inside the handler for the failure it was reporting,
            # which replaced a slow-but-correct fallback with a 500 and hid
            # the real cause.
            _log.warning("flight simulation could not use a worker process; "
                         "running it in the server process instead",
                         extra={"error": str(exc)[:200]})
            out = _run_flight(job)
            # Put the yields back: this process DOES have a twin in it.
            from layer4_core import flight_sim as fs
            from layer4_core import route_cost as rc
            fs.set_yield_s(0.030)
            rc.set_yield_s(0.030)
    except FileNotFoundError as exc:
        # The airframe configuration is missing. Said as a 503 rather than a
        # 500 with a traceback: the station is correctly configured for
        # everything else and one file is absent, which is an operator-fixable
        # condition and should read like one.
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**out,
            "engine_flown": "live" if req.use_live_engine else "as-new",
            "scenario": job["scenario"]}


@app.get("/api/explain")
def explain(c: dict = Depends(require("read:prognostics"))) -> dict:
    """Why the system is saying what it is saying.

    PRD Part 4: a maintenance recommendation the operator cannot interrogate
    must not be presented at all. The health and residual attributions are
    EXACT closed-form decompositions rather than sampled approximations --
    the composite index is a weighted sum of minima, so there is nothing to
    approximate.
    """
    s = _twin().snapshot()
    return {**s.explanation, "advisory": s.twin.get("advisory", {}),
            "generated_utc": s.wall_utc}


@app.get("/api/maintenance")
def maintenance(c: dict = Depends(require("read:advisory"))) -> dict:
    """The costed, ordered maintenance plan (PS section D).

    Ordered by URGENCY rather than severity: a distant overhaul must not
    outrank an oil change that is due now, or a planner reading top-down
    schedules the wrong thing.
    """
    s = _twin().snapshot()
    return {**s.maintenance, "health": s.health, "generated_utc": s.wall_utc}


class MaintenanceDone(BaseModel):
    """A maintenance action that has been carried out."""

    action_id: str = Field(pattern=r"^A[1-7]$")
    # Only an inspection (A5, A6) needs saying: it restores nothing unless
    # parts were replaced. Every other action is a repair by definition.
    repaired: bool | None = None
    note: str = Field("", max_length=200)


@app.post("/api/maintenance/performed")
def maintenance_performed(req: MaintenanceDone,
                          c: dict = Depends(require("write:maintenance"))) -> dict:
    """Record maintenance that has been carried out (PS section D).

    The plan above says what to do; this is how the twin learns it was done.
    Without it an oil change never happened as far as the twin knew: the
    100-hour clock kept running, the health trend was fitted straight across
    the repair, and remaining life went on projecting the decline of the
    engine as it was before the work. Audited, because a record that changes
    what the twin believes about the engine is what an audit log is for.
    """
    busy = OPS.busy() if OPS is not None else None
    if busy and busy.get("tail") == _active_tail:
        raise HTTPException(409, "the engine is running; work is done with it stopped")
    try:
        rec = _twin().record_maintenance(
            req.action_id, repaired=req.repaired,
            by=str(c.get("sub", "?")), note=req.note,
            health_before=(OPS._before_reading(_active_tail)
                           if OPS is not None and _active_tail else None))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    AUDIT.record("MAINTENANCE_ACTION", subject=str(c.get("sub", "?")),
                 role=str(c.get("role", "")), action_id=req.action_id,
                 repaired=rec["repaired"])
    if OPS is not None and _active_tail is not None:
        OPS.record_live_maintenance(_active_tail, req.action_id,
                                    by=str(c.get("sub", "?")), role=str(c.get("role", "")),
                                    note=req.note)
    return rec


# ---------------------------------------------------------------------------
# Squadron operations -- the chain from tasking to debrief (layer4_core/ops.py)
# ---------------------------------------------------------------------------


def _ops() -> ops_mod.OpsStore:
    if OPS is None:
        raise HTTPException(503, "squadron operations are not running")
    return OPS


def _who(c: dict) -> tuple[str, str]:
    return str(c.get("sub", "?")), str(c.get("role", ""))


@contextlib.contextmanager
def _ops_errors():
    try:
        yield
    except ops_mod.OpsError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def _launch_checks(snap: Snapshot, m: dict) -> list[dict]:
    """What must be true before launch clearance, read off the live twin.

    A pilot does not take off with cold oil, a caution lit, or an engine the
    health monitor says will not last the task. These are those, checked
    against this engine now; the operator sees each one pass or fail.
    """
    so = snap.sortie or {}
    rep = (snap.twin or {}).get("reported") or {}
    oil = (rep.get("oil_temperature") or {}).get("value")
    rpm = (rep.get("rpm") or {}).get("value")
    tmin = float(config.load_thresholds()["parameters"]["oil_temperature"]["takeoff_min"])
    active = ((snap.twin or {}).get("alerts") or {}).get("active") or []
    # A WARNING (level 4 and above) stops the launch. A CAUTION is shown for
    # the operator to weigh, not a hard stop: a worn engine's bearing caution
    # came and went at the hold, and a check that flickers between pass and
    # fail cannot be launched against at all.
    warn = sorted({str(a.get("legend") or a.get("parameter")) for a in active
                   if int(a.get("level") or 1) >= 4})
    caut = sorted({str(a.get("legend") or a.get("parameter")) for a in active
                   if int(a.get("level") or 1) == 3})
    verdict = _ops().assess(m["tail"], m["duration_h"], m["altitude_ft"], m["throttle_pct"])
    return [
        {"item": "Engine started and holding at the warm-up setting",
         "ok": bool(so.get("holding")) and so.get("kind") == "mission"},
        {"item": f"Oil temperature at or above the {tmin:.0f} °C take-off minimum",
         "ok": oil is not None and float(oil) >= tmin,
         "value": None if oil is None else round(float(oil), 1)},
        {"item": "Engine running steadily", "ok": rpm is not None and float(rpm) > 1000.0,
         "value": None if rpm is None else round(float(rpm))},
        {"item": "No warning active", "ok": not warn,
         "value": ", ".join(warn) or None},
        # ok None: advisory -- shown, never blocking.
        {"item": "Cautions to review before launch", "ok": None if caut else True,
         "value": ", ".join(caut) or "none"},
        {"item": f"Twin verdict for the {m['duration_h']:g} h task is not NO-GO",
         "ok": verdict.get("verdict") != "NO_GO", "value": verdict.get("verdict")},
    ]


@app.get("/api/ops/board")
def ops_board(c: dict = Depends(require("read:ops"))) -> dict:
    """The squadron at a glance, and what is waiting on the person asking."""
    o = _ops()
    who, role = _who(c)
    missions = o.missions(operator=who if role == "ROLE_OPERATOR" else None)
    live = None
    if twin is not None:
        snap = twin.snapshot()
        so = dict(snap.sortie or {})
        live = {"tail": _active_tail, "sortie": so}
        busy = o.busy()
        if busy and busy.get("kind") == "mission":
            m = o.mission(busy["id"])
            live["mission_id"] = m["id"]
            if m["status"] == ops_mod.ENGINE_RUNNING:
                live["launch_checks"] = _launch_checks(snap, m)
    operators = []
    if sec.has_scope(role, "plan:mission"):
        operators = [u["username"] for u in sec.list_users()
                     if u["role"] == "ROLE_OPERATOR" and not u["disabled"]]
    return {
        "unit": o.fleet.get("unit"), "base": o.fleet.get("base"),
        "active_tail": _active_tail, "busy": o.busy(),
        "aircraft": o.fleet_board(),
        "missions": missions,
        "tasks": o.tasks(role=role, user=who),
        "mission_types": o.mission_types(),
        "environments": o.fleet.get("environments", []),
        "checklist": o.checklist(),
        "operators": operators,
        "inspection_interval_h": o.inspection_interval(),
        "simulated_cruise_hours": o.simulated_cruise_hours(),
        "live": live,
    }


@app.get("/api/ops/aircraft/{tail}")
def ops_aircraft(tail: str, c: dict = Depends(require("read:ops"))) -> dict:
    """One aircraft's technical log: status, defects, flights, every entry."""
    o = _ops()
    with _ops_errors():
        a = o.aircraft(tail)
    return {**a, "defects": o.defects(tail), "logbook": o.logbook(tail),
            "missions": [m for m in o.missions() if m["tail"] == tail][:30]}


class MissionPlan(BaseModel):
    name: str = Field("", max_length=80)
    type: str
    environment: str | None = None
    duration_h: float | None = None
    altitude_ft: float | None = None
    area: str = Field("", max_length=160)
    launch_utc: str = Field("", max_length=40)
    priority: str = Field("ROUTINE", pattern=r"^(ROUTINE|PRIORITY|IMMEDIATE)$")
    notes: str = Field("", max_length=400)


@app.post("/api/ops/missions")
def plan_mission(req: MissionPlan, c: dict = Depends(require("plan:mission"))) -> dict:
    who, role = _who(c)
    with _ops_errors():
        m = _ops().create_mission(by=who, name=req.name, mtype=req.type,
                                  environment=req.environment, duration_h=req.duration_h,
                                  altitude_ft=req.altitude_ft, area=req.area,
                                  launch_utc=req.launch_utc, priority=req.priority,
                                  notes=req.notes)
    AUDIT.record("MISSION", subject=who, role=role, mission=m["id"], change="planned")
    return m


@app.get("/api/ops/missions/{mid}/candidates")
def mission_candidates(mid: str, c: dict = Depends(require("plan:mission"))) -> list[dict]:
    """Every aircraft for this mission, with the twin's verdict on each."""
    with _ops_errors():
        return _ops().candidates(mid)


class Allotment(BaseModel):
    tail: str
    operator: str
    note: str = Field("", max_length=200)


@app.post("/api/ops/missions/{mid}/approve")
def approve_mission(mid: str, req: Allotment,
                    c: dict = Depends(require("plan:mission"))) -> dict:
    who, role = _who(c)
    ops_users = {u["username"]: u for u in sec.list_users()}
    u = ops_users.get(req.operator)
    if u is None or u["disabled"] or u["role"] not in ("ROLE_OPERATOR", "ROLE_COMMANDER"):
        raise HTTPException(400, f"{req.operator} is not an active operator")
    with _ops_errors():
        m = _ops().approve(mid, by=who, tail=req.tail, operator=req.operator, note=req.note)
    AUDIT.record("MISSION", subject=who, role=role, mission=mid, change="approved",
                 tail=req.tail, operator=req.operator)
    return m


class Reason(BaseModel):
    reason: str = Field("", max_length=300)


@app.post("/api/ops/missions/{mid}/cancel")
def cancel_mission(mid: str, req: Reason, c: dict = Depends(require("plan:mission"))) -> dict:
    who, role = _who(c)
    with _ops_errors():
        m = _ops().cancel(mid, by=who, reason=req.reason or "cancelled")
    AUDIT.record("MISSION", subject=who, role=role, mission=mid, change="cancelled")
    return m


@app.post("/api/ops/missions/{mid}/prepare")
def prepare_mission(mid: str, c: dict = Depends(require("fly:mission"))) -> dict:
    """Take the allotted aircraft onto the ground station, engine off."""
    who, role = _who(c)
    o = _ops()
    with _ops_errors():
        m = o.prepare(mid, by=who, role=role)
    try:
        _swap_to(m["tail"])
    except Exception as exc:
        with contextlib.suppress(Exception):
            o.release_gcs(mid, by=who, role=role)
        _log.exception("could not load the aircraft")
        raise HTTPException(500, f"could not load {m['tail']}: {exc}") from exc
    return m


@app.post("/api/ops/missions/{mid}/handback")
def handback_mission(mid: str, c: dict = Depends(require("fly:mission"))) -> dict:
    who, role = _who(c)
    with _ops_errors():
        return _ops().release_gcs(mid, by=who, role=role)


class Checklist(BaseModel):
    checklist: dict[str, bool]


@app.post("/api/ops/missions/{mid}/start")
def start_mission_engine(mid: str, req: Checklist,
                         c: dict = Depends(require("fly:mission"))) -> dict:
    """Checklist complete: start the engine from cold. It warms and HOLDS."""
    from layer2_physics.atmosphere import EnvCondition
    from layer2_physics.engine_sim import mission_profile
    who, role = _who(c)
    o = _ops()
    m = o.mission(mid)
    if _active_tail != m["tail"]:
        raise HTTPException(409, f"{m['tail']} is not on the ground station; prepare it")
    with _ops_errors():
        m = o.start(mid, by=who, role=role, checklist=req.checklist)
    _twin().begin_profile(
        mission_profile(o.simulated_cruise_hours(), m["altitude_ft"], m["throttle_pct"]),
        kind="mission", env_condition=EnvCondition(m["environment"]), label=mid)
    AUDIT.record("SORTIE_START", subject=who, role=role, mission=mid, tail=m["tail"])
    return m


@app.post("/api/ops/missions/{mid}/launch")
def launch_mission(mid: str, c: dict = Depends(require("fly:mission"))) -> dict:
    who, role = _who(c)
    o = _ops()
    m = o.mission(mid)
    if m["status"] != ops_mod.ENGINE_RUNNING:
        raise HTTPException(409, f"{mid} is {m['status']}")
    failed = [ch["item"] for ch in _launch_checks(_twin().snapshot(), m)
              if ch["ok"] is False]
    if failed:
        raise HTTPException(409, "not ready for launch: " + "; ".join(failed))
    with _ops_errors():
        m = o.launch(mid, by=who, role=role)
    _twin().launch()
    return m


@app.post("/api/ops/missions/{mid}/rtb")
def rtb_mission(mid: str, c: dict = Depends(require("fly:mission"))) -> dict:
    who, role = _who(c)
    if not _twin().rtb():
        raise HTTPException(409, "the aircraft is not in a phase it can be recalled from")
    with _ops_errors():
        return _ops().rtb(mid, by=who, role=role)


@app.post("/api/ops/missions/{mid}/abort")
def abort_mission(mid: str, c: dict = Depends(require("fly:mission"))) -> dict:
    who, role = _who(c)
    if not _twin().abort_on_ground():
        raise HTTPException(409, "not on the ground before launch")
    with _ops_errors():
        return _ops().abort(mid, by=who, role=role)


class Snag(BaseModel):
    description: str = Field(max_length=300)
    severity: str = "CAUTION"
    grounding: bool = False


class Debrief(BaseModel):
    outcome: str
    remarks: str = Field("", max_length=600)
    snags: list[Snag] = []


@app.post("/api/ops/missions/{mid}/debrief")
def debrief_mission(mid: str, req: Debrief, c: dict = Depends(require("fly:mission"))) -> dict:
    who, role = _who(c)
    with _ops_errors():
        return _ops().debrief(mid, by=who, role=role, outcome=req.outcome,
                              remarks=req.remarks, snags=[s.model_dump() for s in req.snags])


# --- the aircraft on the ground: inspection, work, ground runs ---------------


class Note(BaseModel):
    note: str = Field("", max_length=300)


@app.post("/api/ops/aircraft/{tail}/release")
def release_aircraft(tail: str, req: Note,
                     c: dict = Depends(require("write:maintenance"))) -> dict:
    who, role = _who(c)
    with _ops_errors():
        a = _ops().release(tail, by=who, role=role, note=req.note)
    AUDIT.record("MAINTENANCE_ACTION", subject=who, role=role, tail=tail, change="released")
    return a


@app.post("/api/ops/aircraft/{tail}/ground")
def ground_aircraft(tail: str, req: Reason, c: dict = Depends(require("raise:defect"))) -> dict:
    """Declare an aircraft unserviceable (maintainer, engineer)."""
    who, role = _who(c)
    if not sec.has_scope(role, "write:maintenance") and not sec.has_scope(role, "review:defects"):
        raise HTTPException(403, "grounding is for maintenance and engineering")
    if not req.reason.strip():
        raise HTTPException(400, "say why")
    with _ops_errors():
        return _ops().ground(tail, by=who, role=role, reason=req.reason)


class NewDefect(BaseModel):
    description: str = Field(max_length=300)
    severity: str = "CAUTION"
    grounding: bool = False


@app.post("/api/ops/aircraft/{tail}/defects")
def raise_defect(tail: str, req: NewDefect, c: dict = Depends(require("raise:defect"))) -> dict:
    who, role = _who(c)
    with _ops_errors():
        return _ops().raise_defect(tail, source=role.replace("ROLE_", ""), by=who, role=role,
                                   description=req.description, severity=req.severity,
                                   grounding=req.grounding)


class Disposition(BaseModel):
    disposition: str = Field(pattern=r"^(CONFIRM|DEFER|NFF)$")
    note: str = Field("", max_length=300)
    defer_hours: float | None = None
    grounding: bool | None = None


@app.post("/api/ops/defects/{did}/disposition")
def dispose_defect(did: int, req: Disposition,
                   c: dict = Depends(require("review:defects"))) -> dict:
    who, role = _who(c)
    with _ops_errors():
        return _ops().dispose_defect(did, by=who, role=role, disposition=req.disposition,
                                     note=req.note, defer_hours=req.defer_hours,
                                     grounding=req.grounding)


def _do_maintenance(tail: str, action_id: str, *, repaired: bool | None, who: str,
                    role: str, note: str) -> str:
    """Apply work to an aircraft's engine: now if it is on the station and
    stopped, otherwise at its next engine run. Returns which."""
    o = _ops()
    busy = o.busy()
    if busy and busy.get("tail") == tail:
        raise HTTPException(409, f"{tail} is running; work is done with the engine stopped")
    if tail == _active_tail and twin is not None:
        try:
            twin.record_maintenance(action_id, repaired=repaired, by=who, note=note,
                                    health_before=o._before_reading(tail))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        o.record_live_maintenance(tail, action_id, by=who, role=role, note=note)
        where = "applied"
    else:
        o.queue_maintenance(tail, action_id, by=who, role=role, repaired=repaired, note=note)
        where = "queued"
    AUDIT.record("MAINTENANCE_ACTION", subject=who, role=role, tail=tail,
                 action_id=action_id, applied=where)
    return where


class Rectification(BaseModel):
    actions: list[str] = []
    repaired: bool | None = None
    note: str = Field("", max_length=300)


@app.post("/api/ops/defects/{did}/rectify")
def rectify_defect(did: int, req: Rectification,
                   c: dict = Depends(require("write:maintenance"))) -> dict:
    who, role = _who(c)
    o = _ops()
    with _ops_errors():
        d = o.defect(did)
    for aid in req.actions:
        if aid not in {f"A{i}" for i in range(1, 8)}:
            raise HTTPException(400, f"unknown maintenance action {aid}")
    applied = [_do_maintenance(d["tail"], aid, repaired=req.repaired, who=who, role=role,
                               note=f"defect #{did}: {req.note}".strip())
               for aid in req.actions]
    with _ops_errors():
        out = o.rectify_defect(did, by=who, role=role, actions=req.actions, note=req.note)
    return {**out, "applied": applied}


class Work(BaseModel):
    action_id: str = Field(pattern=r"^A[1-7]$")
    repaired: bool | None = None
    note: str = Field("", max_length=200)


@app.post("/api/ops/aircraft/{tail}/maintenance")
def aircraft_maintenance(tail: str, req: Work,
                         c: dict = Depends(require("write:maintenance"))) -> dict:
    """Scheduled or unscheduled work on any aircraft of the squadron."""
    who, role = _who(c)
    with _ops_errors():
        _ops().aircraft_cfg(tail)
    where = _do_maintenance(tail, req.action_id, repaired=req.repaired, who=who, role=role,
                            note=req.note)
    return {"tail": tail, "action_id": req.action_id, "applied": where}


@app.post("/api/ops/aircraft/{tail}/ground_run")
def ground_run(tail: str, c: dict = Depends(require("write:maintenance"))) -> dict:
    """Run the engine on the ground: start, warm, run-up, cool, shut down.

    How work on an engine is verified before the aircraft is released, and
    how the twin gets a warm, loaded reading of an aircraft that has not
    flown since.
    """
    from layer2_physics.engine_sim import ground_run_profile
    who, role = _who(c)
    o = _ops()
    with _ops_errors():
        o.begin_ground_run(tail, by=who, role=role)
    try:
        t = _swap_to(tail)
    except Exception as exc:
        with contextlib.suppress(Exception):
            o.recover_after_restart()
        raise HTTPException(500, f"could not load {tail}: {exc}") from exc
    t.begin_profile(ground_run_profile(), kind="ground_run", label=f"ground run {tail}")
    return {"tail": tail, "started": True}


@app.post("/api/ops/aircraft/{tail}/connect")
def connect_aircraft(tail: str, c: dict = Depends(require("read:ops"))) -> dict:
    """Put a parked aircraft on the ground station, engine off, to look at
    its engine twin -- health history, trend, maintenance log.

    Changes what every console on the station shows, so it is for the roles
    that look after the squadron's aircraft; an operator's aircraft comes onto
    the station by preparing their mission.
    """
    role = str(c.get("role", ""))
    if not any(sec.has_scope(role, s) for s in
               ("plan:mission", "write:maintenance", "review:defects")):
        raise HTTPException(403, "an operator's aircraft comes on the station by "
                                 "preparing their mission")
    with _ops_errors():
        _ops().connect(tail)
    _swap_to(tail)
    return {"active_tail": _active_tail}


class Limits(BaseModel):
    max_mission_hours: float | None = Field(None, gt=0, le=40)
    max_altitude_ft: float | None = Field(None, gt=0, le=25000)
    note: str = Field("", max_length=200)


@app.post("/api/ops/aircraft/{tail}/limitations")
def aircraft_limitations(tail: str, req: Limits,
                         c: dict = Depends(require("review:defects"))) -> dict:
    who, role = _who(c)
    with _ops_errors():
        return _ops().set_limitations(tail, by=who, role=role,
                                      max_mission_hours=req.max_mission_hours,
                                      max_altitude_ft=req.max_altitude_ft, note=req.note)


class EngineFit(BaseModel):
    engine_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    note: str = Field("", max_length=200)


@app.post("/api/ops/aircraft/{tail}/engine")
def fit_engine(tail: str, req: EngineFit, c: dict = Depends(require("admin:fleet"))) -> dict:
    """An engine change: another engine definition fitted to this airframe."""
    who, role = _who(c)
    with _ops_errors():
        a = _ops().fit_engine(tail, req.engine_key, by=who, role=role, note=req.note)
    if tail == _active_tail:
        # Reload it on the station with its new engine, parked.
        _swap_to(tail)
    AUDIT.record("ENGINE_CHANGE", subject=who, role=role, tail=tail, engine_key=req.engine_key)
    return a


# ---------------------------------------------------------------------------
# Maintenance catalogue -- every job the maintainer can sign off, not only
# the ones the plan is currently recommending
# ---------------------------------------------------------------------------


@app.get("/api/maintenance/catalog")
def maintenance_catalog(c: dict = Depends(require("read:advisory"))) -> dict:
    """The whole action library, each marked with whether the plan wants it now.

    The console used to offer "record as done" only on actions the plan was
    recommending at that moment. A maintainer who changed the oil at its
    scheduled interval, or replaced a part on inspection, had nowhere to say
    so, and the twin went on believing the engine was as it had been.
    """
    tw = _twin()
    s = tw.snapshot()
    plan = {a.get("action_id"): a for a in (s.maintenance or {}).get("actions", [])}
    deg = tw.veng.degradation
    out = []
    for a in config.load_thresholds()["advisory"]["actions"]:
        aid = str(a["id"])
        rec = plan.get(aid)
        out.append({
            "action_id": aid,
            "name": a.get("name"),
            "parts": list(a.get("parts", [])),
            "procedure": list(a.get("procedure", [])),
            "cost_inr": a.get("cost_inr"),
            "downtime_hours": a.get("downtime_hours"),
            "inspection": aid in deg.INSPECTIONS,
            "affects": list(tw.MAINTENANCE_AFFECTS.get(aid, ("chi",))),
            "recommended": rec is not None,
            "severity": (rec or {}).get("severity"),
            "reason": (rec or {}).get("reason"),
            "due_within_hours": (rec or {}).get("due_within_hours"),
        })
    hist = s.twin.get("history", {}) or {}
    return {
        "actions": out,
        "hours_since_inspection": hist.get("hours_since_inspection"),
        "hours_since_oil_change": round(float(deg.hours_since_oil_change), 2),
        "health": s.health,
        "performed": (s.maintenance or {}).get("performed", []),
        "pending": (s.maintenance or {}).get("pending", []),
        "settle_hours": tw.MAINTENANCE_SETTLE_HOURS,
        "engine_running_hours": round(float(tw.veng.flight_hours), 3),
        "generated_utc": s.wall_utc,
    }


# ---------------------------------------------------------------------------
# Engine definitions -- adding and selecting an engine without editing code
# ---------------------------------------------------------------------------

_ENGINE_KEY_RE = r"^[a-z][a-z0-9_]{1,40}$"
_twin_swap_lock = threading.Lock()


@app.get("/api/engines")
def engines(c: dict = Depends(require("read:telemetry"))) -> dict:
    """Every engine definition present, whether it is complete, and which runs."""
    fitted: dict[str, list[str]] = {}
    if OPS is not None:
        for t in OPS.tails():
            fitted.setdefault(OPS.aircraft_cfg(t)["engine_key"], []).append(t)
    return {
        "running": twin.engine_key if twin is not None else None,
        "active_tail": _active_tail,
        # Engines are fitted per aircraft (configs/fleet.yaml, or an engine
        # change: POST /api/ops/aircraft/{tail}/engine).
        "fitted": fitted,
        "aircraft": OPS.tails() if OPS is not None else [],
        "reference": config.REFERENCE_ENGINE,
        "engines": config.engine_catalogue(),
    }


@app.get("/api/engines/template")
def engine_template(c: dict = Depends(require("write:engines"))) -> Response:
    """The starting point for a new engine file."""
    path = config.config_dir() / "engines" / "_template.yaml"
    return Response(path.read_text(encoding="utf-8"), media_type="text/plain")


@app.get("/api/engines/{engine_key}/yaml")
def engine_yaml(engine_key: str, c: dict = Depends(require("write:engines"))) -> Response:
    """An engine file as written, so it can be copied into a new one."""
    if engine_key not in config.available_engines():
        raise HTTPException(404, f"no engine '{engine_key}'")
    path = config.config_dir() / "engines" / f"{engine_key}.yaml"
    return Response(path.read_text(encoding="utf-8"), media_type="text/plain")


class EngineDefinition(BaseModel):
    """A new or updated engine file, as YAML text."""

    engine_key: str = Field(pattern=_ENGINE_KEY_RE)
    yaml_text: str = Field(max_length=200_000)
    # Check only: report the problems and write nothing.
    dry_run: bool = False
    overwrite: bool = False


def _engine_trial(engine_key: str) -> list[str]:
    """Problems with an engine file already on disk: keys, then a real run."""
    config.clear_cache()
    problems = config.check_engine(engine_key)
    if problems:
        return problems
    try:
        from layer2_physics.engine_sim import VirtualEngine
        veng = VirtualEngine(engine_key=engine_key, seed=1)
        for _ in range(20):
            veng.step(0.5)
    except Exception as exc:  # noqa: BLE001 - reported to the author
        return [f"the engine does not run: {type(exc).__name__}: {exc}"]
    return []


@app.post("/api/engines")
def save_engine(req: EngineDefinition,
                c: dict = Depends(require("write:engines"))) -> dict:
    """Check, and unless ``dry_run`` save, an engine definition.

    Nothing incomplete is kept: the file is checked against every key the
    running code reads and then flown for ten seconds in the virtual engine,
    and removed again if either fails. Only the commander can then fit it to
    an aircraft (POST /api/ops/aircraft/{tail}/engine).
    """
    import yaml

    try:
        parsed = yaml.safe_load(req.yaml_text)
    except yaml.YAMLError as exc:
        raise HTTPException(422, {"problems": [f"not valid YAML: {exc}"]}) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(422, {"problems": ["the file must be a YAML mapping"]})
    engines_dir = config.config_dir() / "engines"
    path = engines_dir / f"{req.engine_key}.yaml"
    exists = path.exists()
    if exists and not req.overwrite:
        raise HTTPException(409, f"engine '{req.engine_key}' already exists")
    if exists and twin is not None and twin.engine_key == req.engine_key:
        raise HTTPException(409, "the running engine's file cannot be replaced; "
                                 "select another engine first")
    old_text = path.read_text(encoding="utf-8") if exists else None
    with _twin_swap_lock:
        path.write_text(req.yaml_text, encoding="utf-8")
        problems = _engine_trial(req.engine_key)
        if problems or req.dry_run:
            if old_text is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(old_text, encoding="utf-8")
            config.clear_cache()
    if problems:
        raise HTTPException(422, {"problems": problems})
    if not req.dry_run:
        AUDIT.record("ENGINE_CONFIG", subject=str(c.get("sub", "?")),
                     role=str(c.get("role", "")), engine_key=req.engine_key,
                     change="updated" if exists else "added")
    return {"engine_key": req.engine_key, "ok": True, "saved": not req.dry_run}


# ---------------------------------------------------------------------------
# User administration -- the commander manages the station's accounts
# ---------------------------------------------------------------------------


@app.get("/api/users")
def users(c: dict = Depends(require("admin:users"))) -> dict:
    return {"users": sec.list_users(), "roles": sorted(sec.roles())}


class NewUser(BaseModel):
    username: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,31}$")
    password: str = Field(min_length=1, max_length=200)
    role: str


class UserChange(BaseModel):
    role: str | None = None
    disabled: bool | None = None
    # A temporary password; the user must change it at next sign-in.
    password: str | None = Field(None, max_length=200)


@app.post("/api/users")
def add_user(req: NewUser, c: dict = Depends(require("admin:users"))) -> dict:
    if demo.enabled():
        raise HTTPException(403, demo.REFUSAL)
    try:
        sec.create_user(req.username, req.password, req.role)
    except (sec.AuthError, sec.PolicyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    AUDIT.record("USER_ADMIN", subject=str(c.get("sub", "?")),
                 role=str(c.get("role", "")), target=req.username,
                 change="created", new_role=req.role)
    return {"username": req.username, "role": req.role, "must_change": True}


@app.post("/api/users/{username}")
def change_user(username: str, req: UserChange,
                c: dict = Depends(require("admin:users"))) -> dict:
    if demo.enabled():
        raise HTTPException(403, demo.REFUSAL)
    me = str(c.get("sub", "?"))
    # Locking yourself out of the only account that can let you back in is
    # not an administrative action anyone means to take.
    if username == me and (req.disabled or (req.role and req.role != c.get("role"))):
        raise HTTPException(400, "you cannot disable or demote your own account")
    changes = []
    try:
        if req.role is not None:
            sec.set_role(username, req.role)
            changes.append(f"role={req.role}")
        if req.disabled is not None:
            sec.set_disabled(username, req.disabled)
            changes.append(f"disabled={req.disabled}")
        if req.password:
            sec.reset_password(username, req.password)
            changes.append("password reset")
    except (sec.AuthError, sec.PolicyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    AUDIT.record("USER_ADMIN", subject=me, role=str(c.get("role", "")),
                 target=username, change=", ".join(changes) or "none")
    return {"username": username, "changes": changes}


# ---------------------------------------------------------------------------
# Engine test rig -- the second of the three deployment contexts the PS names
# ---------------------------------------------------------------------------


@app.get("/api/testrig/schedules")
def testrig_schedules(c: dict = Depends(require("run:simulation"))) -> list[dict]:
    """The ground runs this rig knows how to perform."""
    out = []
    for key, factory in rig.SCHEDULES.items():
        sched = factory()
        out.append({
            "key": key,
            "name": sched.name,
            "description": sched.description,
            "duration_s": round(sched.duration_s, 1),
            "points": [
                {"name": p.name, "throttle_pct": p.throttle_pct,
                 "duration_s": p.duration_s, "target_rpm": p.target_rpm}
                for p in sched.points
            ],
        })
    return out


@app.post("/api/testrig/run")
def testrig_run(req: TestRigRequest, c: dict = Depends(require("run:simulation"))) -> dict:
    """Run a ground test and judge it against the type certificate.

    A synchronous ``def`` on purpose: a run takes on the order of twenty
    seconds, and FastAPI executes a non-async endpoint in a worker thread, so
    the live telemetry stream is not held up by it.
    """
    factory = rig.SCHEDULES.get(req.schedule)
    if factory is None:
        raise HTTPException(
            400,
            f"unknown schedule '{req.schedule}'; "
            f"available: {sorted(rig.SCHEDULES)}",
        )

    degradation = None
    if req.use_live_engine:
        degradation = _twin().veng.degradation.factors

    bench = rig.TestRig(
        cell_temperature_c=req.cell_temperature_c,
        cell_elevation_ft=req.cell_elevation_ft,
        cell_cooling_kmh=req.cell_cooling_kmh,
        seed=req.seed,
    )
    try:
        with _heavy_job("test-rig run"):
            report = bench.run(factory(), degradation=degradation)
    except ValueError as exc:
        # The rig refuses a schedule that would breach a time-limited rating.
        raise HTTPException(400, str(exc)) from exc

    return {
        **report.as_dict(),
        "cell": {
            "temperature_c": req.cell_temperature_c,
            "elevation_ft": req.cell_elevation_ft,
            "cooling_kmh_equivalent": req.cell_cooling_kmh,
        },
        "engine_source": "live aircraft" if req.use_live_engine else "as-new",
    }


# ---------------------------------------------------------------------------
# Fleet -- the third deployment context the PS names
# ---------------------------------------------------------------------------


@app.get("/api/fleet")
def fleet(c: dict = Depends(require("read:fleet"))) -> dict:
    """The fleet roster, ordered by urgency (PRD Part 4 s11, screen 6).

    Sorted by RUL ascending because a maintenance planner reads top-down and
    stops when the day is full. Any other order puts the engine that can wait
    above the one that cannot.
    """
    if not fleet_mod.available():
        # AN OPERATOR DOES NOT RUN PYTHON MODULES.
        #
        # This read "no fleet dataset present -- run 'python -m
        # layer2_physics.synth_data_gen' first", which is a note from one
        # developer to another printed on a commander's fleet screen. It is the
        # same defect as the exception path that put a filesystem path on the
        # prognostics page: what reaches the console says WHAT IS TRUE and what
        # it means for the decision in hand; how to repair it belongs in the
        # log and the runbook, where the person who can act on it will look.
        _log.warning(
            "fleet roster unavailable: no fleet dataset under %s; generate one "
            "with 'python -m layer2_physics.synth_data_gen'",
            config.data_dir() / "synthetic")
        raise HTTPException(
            503,
            "No fleet records on this ground station. This aircraft is "
            "monitored normally; fleet-wide comparison is unavailable.",
        )
    return fleet_mod.roster()


# ---------------------------------------------------------------------------
# Replay -- PRD Part 4 s11 screen 5
# ---------------------------------------------------------------------------


@app.get("/api/checklists")
def checklists(c: dict = Depends(require("read:alerts"))) -> dict:
    """Every abnormal procedure, keyed by the alert legends it answers.

    Served whole, once: the console matches an alert to its procedure
    locally, so opening a checklist during an emergency never waits on the
    network.
    """
    cfg = config.load_checklists()
    return {"source": cfg.get("source", ""), "procedures": cfg["procedures"]}


@app.get("/api/replay/flights")
def replay_flights(c: dict = Depends(require("read:replay"))) -> list[dict]:
    """The sorties and ground runs flown on THIS station, newest first."""
    from layer4_core import sortie_replay
    return sortie_replay.index()


@app.get("/api/replay/flights/{sid}")
def replay_flight(sid: str, c: dict = Depends(require("read:replay"))) -> dict:
    """One recorded session, thinned for display, with its events."""
    from layer4_core import sortie_replay
    try:
        return sortie_replay.session(sid)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/replay/sessions")
def replay_sessions(c: dict = Depends(require("read:replay"))) -> list[dict]:
    """Recorded lives available for replay, most instructive first."""
    if not replay_mod.available():
        raise HTTPException(503, "no recorded fleet present")
    return replay_mod.index()


@app.get("/api/replay/{engine_id}")
def replay_session(engine_id: int, c: dict = Depends(require("read:replay"))) -> dict:
    """One recorded life, with event markers for the scrubber.

    Every payload is stamped ``live: false``. PRD Part 4 s7.3c: replayed
    history must never be mistakable for live telemetry, and the honest place
    to start is for the server never to imply otherwise.
    """
    if not replay_mod.available():
        raise HTTPException(503, "no recorded fleet present")
    try:
        return replay_mod.session(engine_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------------------------------------------------------------------------
# Audit -- PRD Part 4 s11 screen 7, Commander only
# ---------------------------------------------------------------------------


@app.get("/api/audit")
def audit_log(limit: int = 300,
              c: dict = Depends(require("read:audit"))) -> dict:
    """The append-only log, with the result of verifying its hash chain.

    The verification travels WITH the entries rather than behind a separate
    call nobody makes. A log presented without evidence that it is intact is
    just a list of claims.
    """
    return {
        "entries": AUDIT.entries(limit=limit),
        "integrity": AUDIT.verify(),
        "events_recorded": sorted(
            config.load_thresholds()["security"]["audit"]["log_events"]),
    }


# ---------------------------------------------------------------------------
# Mission scenarios -- PS section E
# ---------------------------------------------------------------------------


@app.get("/api/scenarios")
def scenario_index(c: dict = Depends(require("run:simulation"))) -> list[dict]:
    """The four engine-behaviour cases the problem statement names."""
    return scen.index()


@app.post("/api/scenarios/{key}")
def scenario_run(key: str,
                 c: dict = Depends(require("run:simulation"))) -> dict:
    """Fly one scenario and judge it against the type certificate.

    Synchronous on purpose: a scenario is tens of seconds of engine time and
    FastAPI runs a non-async endpoint on a worker thread, so the live
    telemetry stream is not held up by it.
    """
    try:
        with _heavy_job("scenario"):
            out = scen.run(key).as_dict()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    # Kept so the post-flight report can state what was actually explored.
    # The report does NOT run scenarios of its own: an export must not spend
    # tens of seconds of engine time, and a section listing runs nobody
    # performed would be describing an investigation that never happened.
    SCENARIO_RUNS[key] = out
    return out


# What-if runs the operator actually performed, newest result per scenario.
# Empty until somebody runs one, and section 14.2 says so rather than implying
# the twin was interrogated when it was not.
SCENARIO_RUNS: dict[str, dict] = {}

_LAST_TICK: dict = {"ticks": -1, "at": 0.0}
# How long the counter may stand still before this reports unhealthy. The loop
# runs at dt/speed, so several seconds is many missed ticks, not a slow one.
_STALL_S = 10.0


@app.get("/api/history/ectm")
def ectm_trend(limit: int = 200,
               c: dict = Depends(require("read:reports"))) -> dict:
    """Engine Condition Trend Monitoring across flights.

    The one thing a single flight's report cannot show. Each flight
    contributes one stabilised cruise reading; this compares each against the
    baseline flight and REFUSES the comparison when the conditions differ
    enough that the difference would be weather. PS: "life cycle management",
    "mission-wise health reports".
    """
    if history is None:
        raise HTTPException(503, "flight history is not available")
    return history.trend(_history_key() or None, limit=max(1, min(int(limit), 1000)))


@app.get("/api/fleet/sync")
def fleet_sync_status(c: dict = Depends(require("read:reports"))) -> dict:
    """Is the fleet server getting our records, and what is still queued?

    A backlog nobody can see is a backlog nobody drains.
    """
    if syncer is None:
        return {"configured": False, "pending": 0}
    return syncer.stats()


@app.get("/api/healthz")
def healthz() -> dict:
    """Is the engine ALIVE -- not merely, did it ever start.

    The original returned ok for `ticks > 0`, which is a test of existence.
    When DEV-149 froze the pipeline this went on reporting `{"ok": true}` for
    as long as the process stayed up, because the twin had ticked 8540 times
    before it stopped. A liveness check that cannot distinguish "running" from
    "stopped ten minutes ago" is not a liveness check.

    So this tests PROGRESS: the counter must have moved since the last call,
    or have moved recently. `error` is surfaced too -- `_run` records the
    exception there rather than dying, so a stalled loop has a reason.
    """
    import time as _t

    s = _twin().snapshot()
    ticks = s.pipeline.get("ticks", 0)
    now = _t.monotonic()

    if ticks != _LAST_TICK["ticks"]:
        _LAST_TICK["ticks"] = ticks
        _LAST_TICK["at"] = now

    stalled_s = now - _LAST_TICK["at"]
    alive = ticks > 0 and stalled_s < _STALL_S
    err = s.pipeline.get("error")
    # Set by the tick loop once failures persist past its limit. A twin that
    # is still ticking but failing every tick is NOT healthy, even though the
    # counter moves -- so degradation is checked separately from staleness.
    degraded = bool(s.pipeline.get("degraded"))

    out = {"ok": bool(alive and not degraded), "ticks": ticks}
    if not alive and ticks > 0:
        out["stalled_s"] = round(stalled_s, 1)
    if degraded:
        out["degraded"] = True
        out["consecutive_failures"] = s.pipeline.get("consecutive_failures")
    if err:
        out["error"] = err
    return out


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


def _require_tls13() -> None:
    """Make every TLS context uvicorn builds refuse anything below TLS 1.3.

    The previous configuration passed TLS 1.3 SUITE NAMES as `ssl_ciphers`.
    OpenSSL's set_ciphers() only governs TLS 1.2 and below, so starting with a
    certificate raised "No cipher can be selected" -- and nothing set a minimum
    version, so TLS 1.2 would have been negotiated anyway (SEC-03). uvicorn has
    no minimum-version setting, so the context factory it calls is wrapped to
    set one. TLS 1.3 suites are enabled by OpenSSL by default.
    """
    import uvicorn.config as uc

    if getattr(uc.create_ssl_context, "_tls13", False):
        return
    original = uc.create_ssl_context

    def create(*args, **kwargs):
        ctx = original(*args, **kwargs)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        return ctx

    create._tls13 = True  # type: ignore[attr-defined]
    uc.create_ssl_context = create


# The snapshot fields that are charts rather than readings: bounded, slow to
# change, and 71 % of the payload between them. They ride the slower cadence.
_SERIES_KEYS = frozenset({"history", "flight_series"})


@app.websocket("/ws/state")
async def stream_state(ws: WebSocket, token: str = "") -> None:
    """Push the live readings often and the derived series occasionally.

    THE CONSOLE WAS RUNNING TWENTY TIMES SLOWER THAN ITS OWN STANDARD.

    This sent the WHOLE snapshot every `dashboard_refresh_s`, which is 2.0
    SECONDS -- so every engine reading on the display changed once every two
    seconds. PRD Part 4 s8.3 requires the opposite: Zone B at the telemetry rate
    (10 Hz), trend charts at 4 Hz, derived indices at 1 Hz. A gauge that steps
    once every two seconds does not read as a refresh rate to an operator, it
    reads as a console that is lagging, which is exactly what was reported.

    It could not simply be sped up, because the snapshot is 104 KB and 71 % of
    it is two chart series -- `history` and `flight_series`, 30.6 KB each --
    that gain ONE POINT per tick. Sending those ten times a second to make a
    tachometer live is 740 KB/s to move a few hundred bytes of new information.

    So the stream is tiered. Every frame carries the readings and the immediate
    state; the full snapshot, series included, goes out on the slower cadence
    the charts actually need. A partial frame is MARKED as partial, and the
    client merges those over what it already holds.

    The marking matters more than the saving. On a FULL frame an absent field
    means the system is declining to publish it -- a remaining-life figure with
    no calibrated interval, a fault probability with no network. That meaning
    must survive, so only a frame flagged `partial` is ever merged, and a full
    frame always replaces.

    AUTHENTICATED like every other route. A browser cannot set an Authorization
    header on a WebSocket handshake, so the token arrives as a query parameter
    -- the same check, a different carrier. Leaving the socket open while the
    REST API was locked down would have made the entire telemetry stream
    readable by anyone who could reach the port, which is the whole of what the
    console displays.
    """
    try:
        c = sec.verify_token(token)
    except sec.AuthError:
        # Closed before accept, so an unauthenticated peer never sees a frame.
        await ws.close(code=4401)
        return
    if not sec.has_scope(str(c.get("role", "")), "read:telemetry"):
        AUDIT.record("AUTHZ_DENY", subject=str(c.get("sub", "?")),
                     role=str(c.get("role", "")), scope="read:telemetry",
                     path="/ws/state")
        await ws.close(code=4403)
        return
    await ws.accept()
    if demo.enabled():
        demo.console_opened()
    role = str(c.get("role", ""))
    thr = config.load_thresholds()["pipeline"]
    full_period = float(thr["dashboard_refresh_s"])
    period = float(thr.get("dashboard_live_refresh_s", 0.25))
    period = min(period, full_period)
    full_every = max(1, int(round(full_period / max(period, 1e-3))))
    # The token is re-verified every few seconds, not only at connect (RT-02).
    # Checked once, a revoked, expired or disabled credential kept receiving
    # the full telemetry picture for as long as the socket stayed open.
    recheck_every = max(1, int(round(5.0 / max(period, 1e-3))))
    frames = 0
    try:
        while True:
            if frames and frames % recheck_every == 0:
                try:
                    c = sec.verify_token(token)
                except sec.AuthError:
                    await ws.close(code=4401)
                    return
                role = str(c.get("role", ""))
                if not sec.has_scope(role, "read:telemetry"):
                    await ws.close(code=4403)
                    return
            frames += 1
            # Filtered by the SAME scopes the REST routes use. Sending the whole
            # snapshot here would have made every scope check on every other
            # route decorative -- the data was already on the wire.
            payload = snapshot_for_role(asdict(_twin().snapshot()), role)
            if (frames - 1) % full_every:
                # A partial frame: the readings, without the two chart series
                # that dominate the payload and gain one point per tick.
                payload = {k: v for k, v in payload.items()
                           if k not in _SERIES_KEYS}
                payload["partial"] = True
            await ws.send_text(json.dumps(payload, default=str))
            await asyncio.sleep(period)
    except WebSocketDisconnect:
        return
    except Exception:
        with contextlib.suppress(Exception):
            await ws.close()
    finally:
        if demo.enabled():
            demo.console_closed()


# ---------------------------------------------------------------------------
# The console
# ---------------------------------------------------------------------------

if CONSOLE_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=CONSOLE_DIST / "assets"), name="assets")

    # The engine model, its registries and the Draco decoder.
    #
    # Vite emits `public/` at the DIST ROOT, not under assets/, so mounting
    # only /assets left the console asking for /engine3d/rotax915is.glb and
    # getting four 404s and an empty rectangle where the engine should be.
    # Mounted rather than served through a route because it is 5.7 MB of
    # static geometry: StaticFiles handles range requests and caching, and a
    # FileResponse per request would not.
    _model_dir = CONSOLE_DIST / "engine3d"
    if _model_dir.is_dir():
        app.mount("/engine3d", StaticFiles(directory=_model_dir), name="engine3d")

    @app.get("/favicon.png", include_in_schema=False)
    def favicon() -> FileResponse:
        """The State Emblem, which the console already shows in its masthead.

        Served explicitly because vite emits it at the dist ROOT, where only
        the index route reaches. Without it the browser takes a 404 on every
        load -- harmless, and the only console error left in the capture.
        """
        return FileResponse(CONSOLE_DIST / "favicon.png")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(CONSOLE_DIST / "index.html")
else:
    @app.get("/")
    def index_missing() -> dict:
        return {
            "console": "not built",
            "build": "cd layer5_viz/gcs_console && npm install && npm run build",
            "api": ["/api/state", "/api/engine", "/api/faults", "/api/report",
                    "/ws/state"],
        }


def main() -> None:
    """Serve the console and the API.

    TLS IS OPT-IN AND OFF BY DEFAULT, WHICH IS DELIBERATE.
    ------------------------------------------------------
    PRD Part 3 s20.1 threat 1 is interception of the UAV-to-GCS link, and s20.2
    answers it with TLS 1.3. That is right for a fielded ground station and
    wrong for the default here, because the default binds 127.0.0.1: traffic
    that never leaves the loopback interface cannot be intercepted by anything
    that is not already inside the machine, and a self-signed certificate
    generated on first run would train whoever demonstrates this to click
    through a browser warning -- which is a worse security posture than no TLS
    at all, because it is the same gesture an operator would make in front of a
    real man-in-the-middle.

    So TLS is enabled explicitly, with certificates the establishment issued:

        DT_TLS_CERT=/path/server.crt DT_TLS_KEY=/path/server.key \\
            python -m layer4_core.twin_api

    ``DT_HOST`` moves the bind address. Binding anything other than loopback
    WITHOUT TLS is refused rather than warned about: that combination puts
    plain-text telemetry and bearer tokens on a network, and a warning printed
    to a log nobody reads is not a control.
    """
    import os
    import ssl

    import uvicorn

    # ONE PROCESS PER AIRFRAME. NEVER `--workers N`.
    #
    # `twin` is a module-global singleton, and that is correct: a digital twin
    # of one engine IS a singleton. But it means every worker process would
    # start its OWN LiveTwin -- N independent engines, diverging immediately,
    # with the console showing whichever one happened to answer the request
    # and nothing anywhere reporting the disagreement. Scale by running one
    # process per airframe, not N workers per engine.
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
    if workers > 1:
        raise SystemExit(
            f"refusing to start {workers} workers: each would run its own "
            f"independent engine simulation and the console would show a "
            f"different one per request. Run one process per airframe."
        )

    host = os.environ.get("DT_HOST", "127.0.0.1")
    port = int(os.environ.get("DT_PORT", "8000"))
    cert = os.environ.get("DT_TLS_CERT")
    keyfile = os.environ.get("DT_TLS_KEY")
    loopback = host in ("127.0.0.1", "::1", "localhost")

    # A CONTAINER CANNOT USE THE LOOPBACK DEFAULT.
    #
    # Inside a container, 127.0.0.1 is the CONTAINER's loopback, so `-p
    # 8000:8000` forwards to an interface nothing is listening on. The image
    # started perfectly and was unreachable, which CI caught as "container
    # never reported a running pipeline" -- the process was fine; the port was
    # a dead end.
    #
    # The refusal below is still right: plain-text bearer tokens must not cross
    # a network by accident. But "bind 0.0.0.0 inside a container behind a
    # TLS-terminating proxy, or on an isolated demo network" is a legitimate
    # deployment, so it gets an EXPLICIT, loud opt-in rather than a silent
    # exception. Opting in is a decision someone has to make and can be found
    # in a compose file; a default is one nobody makes.
    insecure_ok = os.environ.get("DT_ALLOW_INSECURE_BIND") == "1"
    if not loopback and not (cert and keyfile) and not insecure_ok:
        raise SystemExit(
            f"refusing to bind {host} without TLS: that puts telemetry and "
            f"bearer tokens on the network in plain text. Set DT_TLS_CERT and "
            f"DT_TLS_KEY, bind 127.0.0.1, or -- only behind a TLS-terminating "
            f"proxy or on an isolated network -- set DT_ALLOW_INSECURE_BIND=1."
        )
    if not loopback and not (cert and keyfile):
        logging.getLogger("layer4_core.twin_api").warning(
            "serving WITHOUT TLS on a non-loopback address by explicit "
            "opt-in; bearer tokens cross this network in plain text",
            extra={"host": host, "port": port},
        )

    kw: dict = {}
    if cert and keyfile:
        # TLS 1.2 and below are refused outright rather than negotiated down:
        # s20.2 specifies 1.3, and a floor that can be talked underneath is
        # not a floor. Enforced by `_require_tls13`, not by a cipher string.
        _require_tls13()
        kw = {
            "ssl_certfile": cert,
            "ssl_keyfile": keyfile,
            "ssl_version": ssl.PROTOCOL_TLS_SERVER,
        }
        print(f"TLS 1.3 enabled, serving https://{host}:{port}")

    uvicorn.run(app, host=host, port=port, log_level="warning", **kw)


if __name__ == "__main__":
    main()
