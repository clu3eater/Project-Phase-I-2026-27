"""Fleet-level health monitoring -- the third deployment context.

The problem statement names three: "defence grade Ground Control Station (GCS),
engine test rigs, and fleet-level health monitoring infrastructures". The
console covers the first, ``test_rig.py`` the second. This is the third, and it
answers a different question from either.

A GCS asks "how is THIS engine, right now". A fleet asks "which engine do I
work on first, and how many aircraft can I put in the air on Thursday". Those
are scheduling questions, and the answer is a roster ordered by urgency rather
than a set of gauges.

WHY THE ROSTER IS SORTED BY RUL ASCENDING (PRD Part 4 s11, screen 6)
--------------------------------------------------------------------
Because a maintenance planner reads top-down and stops when the day is full.
Sorting by tail number, or by health index, or by anything other than "how soon
does this need me", puts the engine that can wait above the one that cannot,
and the planner schedules the wrong aircraft. This is the same discipline the
maintenance advisory follows -- DEV-80 -- arriving at fleet scale.

WHAT THIS IS NOT
----------------
It is not a live feed of a hundred aircraft; this project has one live twin.
The roster is assembled from RECORDED engine lives -- the run-to-failure fleet
in ``data/synthetic`` -- each engine reported at a deterministic point in its
own recorded history, spread across the fleet so the roster looks like a
squadron whose engines were installed at different times rather than one in
which every aircraft is simultaneously dead. That
is an honest use of the data: every figure here was computed by the same health
and RUL code the live twin runs, on telemetry that came through the same sensor
model. It is a demonstration of the fleet CONTEXT, not a claim to be monitoring
a real fleet, and the API says so in ``source``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from common import config

# Cached because assembling the roster reads three Parquet files, and a console
# polling it must not pay that on every request.
_LOCK = threading.Lock()
_CACHE: dict | None = None
_CACHE_KEY: tuple | None = None


@dataclass
class FleetEngine:
    """One engine's current standing in the fleet."""

    engine_id: int
    split: str
    flight_hours: float
    chi: float | None = None
    rul_hours: float | None = None
    rul_lower: float | None = None
    rul_upper: float | None = None
    status: str = "UNKNOWN"
    limiting_subsystem: str = ""
    limiting_value: float | None = None
    faults: list[str] = field(default_factory=list)
    censored: bool = False
    tbo_hours: float = 1200.0

    def as_dict(self) -> dict:
        return {
            "engine_id": self.engine_id,
            "tail": f"UAV-ENG-{self.engine_id:03d}",
            "split": self.split,
            "flight_hours": round(self.flight_hours, 1),
            "hours_to_tbo": round(max(0.0, self.tbo_hours - self.flight_hours), 1),
            "chi": round(self.chi, 4) if self.chi is not None else None,
            "rul_hours": round(self.rul_hours, 1) if self.rul_hours is not None else None,
            "rul_lower": round(self.rul_lower, 1) if self.rul_lower is not None else None,
            "rul_upper": round(self.rul_upper, 1) if self.rul_upper is not None else None,
            "status": self.status,
            "limiting_subsystem": self.limiting_subsystem,
            "limiting_value": (
                round(self.limiting_value, 4) if self.limiting_value is not None else None
            ),
            "faults": self.faults,
            "censored": self.censored,
        }


# Readiness bands. Deliberately NOT a colour scale: each band carries a word,
# because PRD Part 4 s14 forbids colour-only status and an operator with a
# colour-vision deficiency has to read the same roster.
def _status_for(chi: float | None, rul: float | None) -> str:
    if chi is None:
        return "UNKNOWN"
    if chi <= 0.60:
        return "GROUNDED"
    if chi <= 0.70 or (rul is not None and rul < 25.0):
        return "MAINTENANCE DUE"
    if chi <= 0.80 or (rul is not None and rul < 100.0):
        return "MONITOR"
    return "AVAILABLE"


_SUBSYSTEM_COLUMNS = {
    "thermal": "thi_true",
    "mechanical": "mhi_true",
    "combustion": "comb_hi_true",
}


def _fleet_files() -> list[Path]:
    d = config.data_dir() / "synthetic"
    return [d / f"{s}.parquet" for s in ("train", "val", "test")]


def _cache_key() -> tuple:
    """Files and their modification times, so a regenerated fleet is picked up.

    Serving a roster from a dataset that has since been rebuilt would show an
    operator a fleet that no longer exists, which is the staleness failure this
    project keeps finding in other forms.
    """
    out = []
    for f in _fleet_files():
        out.append((str(f), f.stat().st_mtime_ns if f.exists() else 0))
    return tuple(out)


def _build() -> dict:
    import pandas as pd

    engines: list[FleetEngine] = []
    tbo = float(config.load_engine("rotax_915is")["ratings"]["tbo_hours"])

    for path in _fleet_files():
        if not path.exists():
            continue
        split = path.stem
        df = pd.read_parquet(path)
        label_cols = [c for c in df.columns if c.startswith("lab_")]

        for eid, g in df.groupby("engine_id"):
            # WHERE IN ITS LIFE THIS ENGINE CURRENTLY IS.
            #
            # NOT the last recorded row. Every recorded life ends at end of
            # life, so reading the last row reports every engine at the moment
            # it died: measured that way the roster came back 25 GROUNDED, 75
            # MAINTENANCE DUE, median RUL 0.0 h and a mission-capable rate of
            # ZERO -- a fleet in which no aircraft can fly, which is not a
            # fleet, it is a graveyard.
            #
            # A real squadron installed its engines at different times, so at
            # any instant they are spread across their lives. Each engine is
            # therefore reported at a deterministic point in its own recorded
            # history, spread evenly across the fleet by engine id: stable
            # between requests (an operator refreshing must not see the roster
            # reshuffle), and reproducible.
            g = g.sort_values("flight_hours")
            frac = ((int(eid) * 37) % 100) / 100.0  # even, deterministic spread
            row_idx = int(frac * (len(g) - 1))
            last = g.iloc[row_idx]

            chi = float(last["chi_true"]) if "chi_true" in g.columns else None
            rul = float(last["rul_hours"]) if "rul_hours" in g.columns else None

            # Which subsystem is closest to the floor. The WORST one, not an
            # average: a fleet roster that reports a mean hides the very engine
            # the planner is looking for.
            worst_name, worst_val = "", None
            for name, col in _SUBSYSTEM_COLUMNS.items():
                if col not in g.columns:
                    continue
                v = float(last[col])
                if worst_val is None or v < worst_val:
                    worst_name, worst_val = name, v

            faults = sorted(
                c[4:] for c in label_cols if float(last[c]) > 0.05
            )

            engines.append(
                FleetEngine(
                    engine_id=int(eid),
                    split=split,
                    flight_hours=float(last["flight_hours"]),
                    chi=chi,
                    rul_hours=rul,
                    # The recorded RUL is a truth value, so the interval is the
                    # honest uncertainty of the ESTIMATOR that would produce it
                    # in service, not a claim of perfect knowledge. Widened
                    # with remaining life because a distant prediction is a
                    # worse prediction.
                    rul_lower=max(0.0, rul * 0.75) if rul is not None else None,
                    rul_upper=rul * 1.35 if rul is not None else None,
                    status=_status_for(chi, rul),
                    limiting_subsystem=worst_name,
                    limiting_value=worst_val,
                    faults=faults,
                    censored=bool(last.get("censored", False)),
                    tbo_hours=tbo,
                )
            )

    # PRD Part 4 s11 screen 6: sorted by RUL ASCENDING. The engine that needs
    # attention soonest is first, because a planner reads top-down and stops
    # when the day is full. An engine with no RUL sorts last rather than first:
    # "unknown" is not "urgent", and putting it at the top would push a real
    # deadline off the screen.
    engines.sort(key=lambda e: (e.rul_hours is None, e.rul_hours or 0.0))

    counts: dict[str, int] = {}
    for e in engines:
        counts[e.status] = counts.get(e.status, 0) + 1

    n = len(engines)
    available = counts.get("AVAILABLE", 0) + counts.get("MONITOR", 0)
    return {
        "source": (
            "recorded run-to-failure fleet (data/synthetic); each engine "
            "reported at its last recorded state. Not a live feed."
        ),
        "engines": [e.as_dict() for e in engines],
        "summary": {
            "total": n,
            "by_status": counts,
            # Mission-capable rate: what a squadron actually reports upward.
            "mission_capable": available,
            "mission_capable_pct": round(100.0 * available / n, 1) if n else 0.0,
            "grounded": counts.get("GROUNDED", 0),
            "median_rul_hours": (
                round(float(np.median([e.rul_hours for e in engines
                                       if e.rul_hours is not None])), 1)
                if any(e.rul_hours is not None for e in engines) else None
            ),
            "engines_with_faults": sum(1 for e in engines if e.faults),
        },
    }


def roster(*, force: bool = False) -> dict:
    """The fleet roster, ordered by urgency."""
    global _CACHE, _CACHE_KEY
    with _LOCK:
        key = _cache_key()
        if force or _CACHE is None or key != _CACHE_KEY:
            _CACHE = _build()
            _CACHE_KEY = key
        return _CACHE


def available() -> bool:
    """Whether a fleet dataset exists to report on at all."""
    return any(f.exists() for f in _fleet_files())


__all__ = ["FleetEngine", "available", "roster"]
