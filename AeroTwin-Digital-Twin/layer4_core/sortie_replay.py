"""Replay of the flights flown on THIS ground station.

WHY THIS EXISTS
---------------
The replay screen replayed one thing: the synthetic fleet data set, a library
of whole engine lives generated for training. Useful to an engineer checking
detection lead times -- and not what anyone means by "mission replay". The
station records every session it runs (`recorder.FlightRecorder`, one parquet
file per aircraft per session, written in parts while it runs), and none of
that was reachable. An operator who had just flown MSN-0001 opened Replay and
read "no flights recorded on this ground station yet".

This module turns those recordings into replayable sorties: the channels an
operator and an engineer look at, thinned to a size a browser draws at once,
and the events that give a sortie its shape -- engine start, airborne, peaks,
limit exceedances, landed, shutdown -- derived from the data itself rather
than from anybody's recollection of the flight.

Like `replay.py`, nothing here pretends to be live: every payload says
``live: false`` and names the aircraft and the session.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from common import config

# The channels served, with their units. Everything else in the recording is
# for the models, not for a person scrubbing through a sortie.
CHANNELS: dict[str, str] = {
    "rpm": "rpm", "cht_max": "°C", "egt_max": "°C", "oil_pressure": "psi",
    "oil_temperature": "°C", "coolant_temperature": "°C", "fuel_flow": "L/h",
    "manifold_pressure": "bar", "altitude_ft": "ft", "airspeed_kmh": "km/h",
    "throttle_pct": "%", "vibration_rms_total": "m/s²", "battery_voltage": "V",
    "chi": "",
}
MAX_POINTS = 1500
RUNNING_RPM = 500.0
AIRBORNE_MARGIN_FT = 150.0
MARGIN_S = 30.0
_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_NAME = re.compile(r"^(?P<tail>.+)_(?P<stamp>\d{8}T\d{6}Z)$")


def _dir() -> Path:
    return Path(config.data_dir()) / "recordings"


def _files(sid: str) -> list[Path]:
    """The final file, or the parts of a session still being written."""
    d = _dir()
    final = d / f"{sid}.parquet"
    if final.is_file():
        return [final]
    return sorted(d.glob(f"{sid}.part*.parquet"))


def _read(sid: str, columns: list[str] | None = None) -> pa.Table | None:
    files = _files(sid)
    if not files:
        return None
    tables = []
    for f in files:
        try:
            t = pq.read_table(f)
        except Exception:  # noqa: BLE001 - a torn part is skipped, not fatal
            continue
        if columns:
            t = t.select([c for c in columns if c in t.column_names])
        tables.append(t)
    if not tables:
        return None
    return pa.concat_tables(tables, promote_options="default")


def _session_ids() -> list[str]:
    d = _dir()
    if not d.is_dir():
        return []
    ids = {p.name.split(".")[0] for p in d.glob("*.parquet")}
    return sorted((i for i in ids if _NAME.match(i)), reverse=True)


def index() -> list[dict[str, Any]]:
    """Every recorded session in which the engine actually ran, newest first."""
    out = []
    for sid in _session_ids():
        t = _read(sid, ["t_s", "rpm", "altitude_ft"])
        if t is None or t.num_rows == 0:
            continue
        rpm = [v for v in t.column("rpm").to_pylist() if v is not None]
        if not rpm or max(rpm) < RUNNING_RPM:
            continue           # parked the whole session: nothing to replay
        ts = t.column("t_s").to_pylist()
        alt = [v for v in t.column("altitude_ft").to_pylist() if v is not None]
        m = _NAME.match(sid)
        started = datetime.strptime(m["stamp"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        flew = bool(alt) and max(alt) - min(alt) > AIRBORNE_MARGIN_FT
        out.append({
            "id": sid, "tail": m["tail"], "started_utc": started.isoformat(),
            "running_s": round(sum(1 for v in rpm if v >= RUNNING_RPM)
                               * (float(ts[-1] - ts[0]) / max(len(ts) - 1, 1)), 1),
            "kind": "sortie" if flew else "ground run",
            "max_altitude_ft": round(max(alt), 0) if alt else None,
            "in_progress": not (_dir() / f"{sid}.parquet").is_file(),
        })
    return out


def _limit(param: str, key: str) -> float | None:
    try:
        v = config.load_thresholds()["parameters"][param][key]
        return float(v) if v is not None else None
    except (KeyError, TypeError, ValueError):
        return None


def session(sid: str) -> dict[str, Any]:
    if not _ID.match(sid) or not _NAME.match(sid):
        raise KeyError(f"no such recording: {sid}")
    t = _read(sid, ["t_s", *CHANNELS])
    if t is None or t.num_rows == 0:
        raise KeyError(f"no such recording: {sid}")
    cols = {c: t.column(c).to_pylist() for c in t.column_names}
    # From just before the engine starts to just after it stops: a session
    # can hold twenty parked minutes either side, and a replay that opens on
    # them makes the operator scrub past nothing to find the flight.
    run = [i for i, v in enumerate(cols.get("rpm") or []) if v is not None and v >= RUNNING_RPM]
    if run:
        ts_all = cols["t_s"]
        lo_t, hi_t = ts_all[run[0]] - MARGIN_S, ts_all[run[-1]] + MARGIN_S
        idx = [i for i, v in enumerate(ts_all) if lo_t <= v <= hi_t]
        cols = {c: [v[i] for i in idx] for c, v in cols.items()}
    t0 = cols["t_s"][0]
    elapsed = [float(v - t0) for v in cols["t_s"]]
    n = len(elapsed)
    step = max(1, -(-n // MAX_POINTS))
    keep = list(range(0, n, step))
    if keep[-1] != n - 1:
        keep.append(n - 1)

    def rnd(v: Any) -> Any:
        return None if v is None else round(float(v), 3)

    series = {c: [rnd(cols[c][i]) for i in keep] for c in CHANNELS if c in cols}
    events = _events(elapsed, cols)
    m = _NAME.match(sid)
    return {
        "id": sid, "tail": m["tail"], "live": False,
        "source": "recorded on this ground station",
        "duration_s": round(elapsed[-1], 1),
        "n_points": len(keep),
        "t_s": [round(elapsed[i], 1) for i in keep],
        "series": series,
        "units": {c: CHANNELS[c] for c in series},
        "events": events,
    }


def _events(el: list[float], c: dict[str, list]) -> list[dict[str, Any]]:
    """The shape of the sortie, read from the data."""
    ev: list[dict[str, Any]] = []
    rpm = c.get("rpm") or []
    alt = c.get("altitude_ft") or []

    running = False
    for i, v in enumerate(rpm):
        on = v is not None and v >= RUNNING_RPM
        if on and not running:
            ev.append({"t_s": el[i], "kind": "phase", "label": "Engine start",
                       "detail": f"{v:.0f} rpm"})
        if running and not on:
            ev.append({"t_s": el[i], "kind": "phase", "label": "Engine shut down", "detail": ""})
        running = on

    vals = [v for v in alt if v is not None]
    if vals:
        ground = min(vals)
        up = False
        for i, v in enumerate(alt):
            a = v is not None and v - ground > AIRBORNE_MARGIN_FT
            if a and not up:
                ev.append({"t_s": el[i], "kind": "phase", "label": "Airborne", "detail": ""})
            if up and not a:
                ev.append({"t_s": el[i], "kind": "phase", "label": "Landed", "detail": ""})
            up = a
        top = max(range(len(alt)), key=lambda i: alt[i] if alt[i] is not None else -1e9)
        if alt[top] is not None and alt[top] - ground > AIRBORNE_MARGIN_FT:
            ev.append({"t_s": el[top], "kind": "peak", "label": "Highest point",
                       "detail": f"{alt[top]:,.0f} ft"})

    for ch, param, unit, name in (("cht_max", "cht", "°C", "CHT"),
                                  ("egt_max", "egt", "°C", "EGT")):
        xs = c.get(ch) or []
        if not any(v is not None for v in xs):
            continue
        k = max(range(len(xs)), key=lambda i: xs[i] if xs[i] is not None else -1e9)
        lim = _limit(param, "critical_max")
        ev.append({"t_s": el[k], "kind": "peak", "label": f"Peak {name}",
                   "detail": f"{xs[k]:.1f} {unit}" + (f" (limit {lim:.0f})" if lim else "")})
        if lim is None:
            continue
        over = False
        start = 0
        for i, v in enumerate(xs):
            o = v is not None and v > lim
            if o and not over:
                start = i
            if over and not o:
                ev.append({"t_s": el[start], "kind": "exceedance", "label": f"{name} over limit",
                           "detail": f"for {el[i] - el[start]:.0f} s, above {lim:.0f} {unit}"})
            over = o
        if over:
            ev.append({"t_s": el[start], "kind": "exceedance", "label": f"{name} over limit",
                       "detail": f"to the end of the recording, above {lim:.0f} {unit}"})

    ev.sort(key=lambda e: e["t_s"])
    return ev


__all__ = ["index", "session"]
