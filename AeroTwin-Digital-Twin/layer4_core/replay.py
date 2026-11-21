"""Mission replay -- PRD Part 4 s11, screen 5.

    "REPLAY — transport (1x/10x/100x/event), scrubber with event markers,
     recomputed residuals, annotations."

WHY A REPLAY SCREEN EXISTS AT ALL
---------------------------------
A health-monitoring system earns its keep after the event as much as during it.
When an engine is pulled, the question is not "what is it doing now" but "when
did this start, and was there anything on the bus that would have told us
earlier". That is a question about recorded history, and it cannot be answered
from a live display.

The detection lead times this project reports -- a median of several hundred
flight hours between the first residual excursion and the maintenance threshold
-- are exactly the claim a replay screen lets somebody check rather than take
on trust.

THE ONE RULE THAT GOVERNS THIS SCREEN (PRD Part 4 s7.3c)
---------------------------------------------------------
    "Back-filled history SHALL be visually distinguishable from live data on
     trend charts ... so the operator never mistakes replayed history for live
     telemetry."

The dangerous failure of a replay feature is not that it replays badly. It is
that somebody walks past the console, reads a number, and acts on it, not
knowing they are looking at last Tuesday. So the API here never pretends to be
live: every payload is stamped ``live: false`` and carries the engine and the
flight hour it is showing, and the console is required to annunciate REPLAY
persistently rather than in a corner.

WHAT IS REPLAYED
----------------
Recorded run-to-failure lives from ``data/synthetic`` -- the same fleet the
models were trained and scored on. Each carries the sensor channels an
instrument actually saw, the residuals against the as-new shadow model, the
true health indices, and the fault labels. Nothing is recomputed on the fly:
these are the recorded values, which is the point of a replay.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from common import config

_LOCK = threading.Lock()
_INDEX: list[dict] | None = None
_INDEX_KEY: tuple | None = None

# Channels offered for the trend traces. Deliberately a short list: PRD Part 4
# s6 groups by function and warns against a wall of interchangeable plots.
CHANNELS = (
    "chi_true", "rul_hours",
    "cht_max", "coolant_temperature", "egt_max", "egt_spread",
    "oil_pressure", "oil_temperature", "vibration_rms_total",
    "fuel_flow", "manifold_pressure", "knock_retard_deg",
    "res_cht", "res_coolant", "res_egt", "res_oil_pressure",
)

# How many points a scrubber gets. A 1,200 hour life at one row per recorded
# window is a few thousand rows; a 1920 px scrubber cannot show more than about
# one point per pixel, and sending more is bandwidth spent on nothing.
MAX_POINTS = 900

_HEALTH_BANDS = (
    (0.80, "CHI fell below 0.80 - GOOD/FAIR boundary, monitoring advised"),
    (0.70, "CHI fell below 0.70 - FAIR/POOR boundary"),
    (0.60, "CHI fell below 0.60 - maintenance threshold"),
)


def _files() -> list[Path]:
    d = config.data_dir() / "synthetic"
    return [d / f"{s}.parquet" for s in ("train", "val", "test")]


def _key() -> tuple:
    return tuple(
        (str(f), f.stat().st_mtime_ns if f.exists() else 0) for f in _files()
    )


def available() -> bool:
    return any(f.exists() for f in _files())


def index() -> list[dict]:
    """Every recorded life that can be replayed, most interesting first."""
    global _INDEX, _INDEX_KEY
    import pandas as pd

    with _LOCK:
        k = _key()
        if _INDEX is not None and k == _INDEX_KEY:
            return _INDEX

        out: list[dict] = []
        for path in _files():
            if not path.exists():
                continue
            df = pd.read_parquet(
                path,
                columns=["engine_id", "flight_hours", "chi_true", "censored",
                         *[f"lab_{n}" for n in _fault_names(path)]],
            )
            for eid, g in df.groupby("engine_id"):
                faults = sorted(
                    c[4:] for c in g.columns
                    if c.startswith("lab_") and (g[c] > 0.05).any()
                )
                out.append({
                    "engine_id": int(eid),
                    "tail": f"UAV-ENG-{int(eid):03d}",
                    "split": path.stem,
                    "life_hours": round(float(g["flight_hours"].max()), 1),
                    "final_chi": round(float(g["chi_true"].iloc[-1]), 4),
                    "censored": bool(g["censored"].iloc[-1]),
                    "faults": faults,
                    "rows": int(len(g)),
                })

        # An engine that failed with faults is more instructive than one that
        # ran to TBO clean, so those sort first -- but the clean ones stay in
        # the list, because "what does a healthy life look like" is the
        # comparison every investigation actually needs.
        out.sort(key=lambda e: (e["censored"], -len(e["faults"]), e["life_hours"]))
        _INDEX, _INDEX_KEY = out, k
        return out


def _fault_names(path: Path) -> list[str]:
    import pyarrow.parquet as pq

    cols = pq.ParquetFile(path).schema.names
    return [c[4:] for c in cols if c.startswith("lab_")]


def _events(g, fault_names: list[str]) -> list[dict]:
    """Everything worth a marker on the scrubber.

    Fault ONSETS rather than fault presence: a marker on every row a fault is
    active turns the scrubber into a solid bar and tells the investigator
    nothing. What they are looking for is the moment it started.
    """
    events: list[dict] = []
    hours = g["flight_hours"].to_numpy()

    for name in fault_names:
        col = f"lab_{name}"
        if col not in g.columns:
            continue
        active = (g[col].to_numpy() > 0.05)
        if not active.any():
            continue
        # First rising edge, and any later re-appearance after a gap.
        edges = np.flatnonzero(active & ~np.r_[False, active[:-1]])
        for i in edges:
            events.append({
                "hours": round(float(hours[i]), 2),
                "kind": "fault",
                "label": name.replace("_", " "),
                "detail": f"{name.replace('_', ' ')} began to express",
            })

    chi = g["chi_true"].to_numpy()
    for level, text in _HEALTH_BANDS:
        below = chi <= level
        if not below.any():
            continue
        i = int(np.argmax(below))
        events.append({
            "hours": round(float(hours[i]), 2),
            "kind": "health",
            "label": f"CHI {level:.2f}",
            "detail": text,
        })

    # The first residual excursion: the earliest moment the twin's own
    # reference model disagreed with the aircraft. This is the marker the
    # detection-lead-time claim rests on, so it belongs on the scrubber where
    # somebody can check it against the fault onset beside it.
    if "res_cht" in g.columns:
        r = g["res_cht"].to_numpy()
        n_base = max(10, len(r) // 10)
        settled = r[:n_base]
        if len(settled) > 3:
            mu, sd = float(np.mean(settled)), float(np.std(settled))
            if sd > 1e-9:
                # Searched only AFTER the baseline window. Searching from index
                # zero finds an outlier inside the baseline itself and reports
                # the excursion at the first sample of the engine's life --
                # measured, 0.01 h on an engine whose fault began at 305 h,
                # which would have made the detection-lead-time marker
                # meaningless and flattering at the same time.
                #
                # And it must PERSIST. One sample outside 3 sigma is noise; the
                # rule engine applies the same discipline before it raises
                # anything, and a marker on the scrubber is a claim about when
                # something started.
                need = 5
                out = np.abs(r - mu) > 3.0 * sd
                run = 0
                hit = None
                for i in range(n_base, len(out)):
                    run = run + 1 if out[i] else 0
                    if run >= need:
                        hit = i - need + 1
                        break
                if hit is not None:
                    events.append({
                        "hours": round(float(hours[hit]), 2),
                        "kind": "residual",
                        "label": "residual excursion",
                        "detail": (
                            f"CHT residual against the as-new shadow model held "
                            f"outside 3 sigma of its own settled baseline for "
                            f"{need} consecutive windows"
                        ),
                    })

    events.sort(key=lambda e: e["hours"])
    return events


def session(engine_id: int) -> dict:
    """One recorded life, downsampled for a scrubber."""
    import pandas as pd

    for path in _files():
        if not path.exists():
            continue
        names = _fault_names(path)
        df = pd.read_parquet(path)
        g = df[df["engine_id"] == engine_id]
        if g.empty:
            continue
        g = g.sort_values("flight_hours")

        events = _events(g, names)

        step = max(1, len(g) // MAX_POINTS)
        s = g.iloc[::step]

        series = {
            c: [None if pd.isna(v) else round(float(v), 4)
                for v in s[c].to_numpy()]
            for c in CHANNELS if c in s.columns
        }
        active = {
            n: [bool(v > 0.05) for v in s[f"lab_{n}"].to_numpy()]
            for n in names if f"lab_{n}" in s.columns
        }

        return {
            # Stamped on every payload. A replay that can be mistaken for live
            # telemetry is the failure mode this screen has to design against
            # (PRD Part 4 s7.3c).
            "live": False,
            "source": f"recorded life, {path.stem} split",
            "engine_id": int(engine_id),
            "tail": f"UAV-ENG-{int(engine_id):03d}",
            "life_hours": round(float(g["flight_hours"].max()), 1),
            "censored": bool(g["censored"].iloc[-1]),
            "hours": [round(float(v), 3) for v in s["flight_hours"].to_numpy()],
            "series": series,
            "fault_active": active,
            "events": events,
            "n_points": int(len(s)),
            "n_rows": int(len(g)),
        }

    raise KeyError(f"no recorded life for engine {engine_id}")


__all__ = ["CHANNELS", "available", "index", "session"]
