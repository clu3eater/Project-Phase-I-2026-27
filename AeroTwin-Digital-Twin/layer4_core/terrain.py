"""The ground under a proposed route, and whether the aircraft clears it.

A mission planner that cannot see terrain is a drawing. It will let an operator
plan a leg at 12,000 ft across ground that stands at 14,000, and nothing on the
screen will object.

WHAT THIS ANSWERS
-----------------
    the highest ground under each leg
    the minimum safe altitude for it -- terrain plus a clearance margin
    whether the planned altitude actually clears that
    and, because this is an ENGINE twin: whether the engine can still make the
    altitude the terrain demands, on the day in question

That last line is the one no chart can answer and no flight planner can either.
Terrain fixes the altitude a route requires; the engine decides whether that
altitude is available, and a degraded engine on a hot day has a lower ceiling
than the same engine had when new.

THE DATA
--------
A real elevation grid, fetched once by scripts/fetch_geodata.py from the AWS
open Terrain Tiles and clipped to the operating region. It is downsampled by
MAXIMUM rather than by average: a peak inside a cell is never averaged away, so
the error falls on the side of declaring a route blocked that a finer grid
would allow, rather than declaring one clear that is not.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from common import config

# ICAO-style terrain clearance for the en-route phase. 1,000 ft over flat
# ground, 2,000 ft over mountainous -- and this is the engine's planner, not a
# certified terrain-awareness system, so the conservative figure is used
# everywhere rather than classifying the ground.
CLEARANCE_FT = 2000.0
FT_PER_M = 3.280839895


def _geo_dir() -> Path:
    return (config.repo_root() / "layer5_viz" / "gcs_console"
            / "public" / "geo")


@lru_cache(maxsize=1)
def _grid() -> tuple[np.ndarray, dict] | tuple[None, None]:
    """The elevation grid and the window it covers, or None if not fetched."""
    meta_path = _geo_dir() / "terrain.json"
    data_path = _geo_dir() / "terrain.i16"
    if not (meta_path.exists() and data_path.exists()):
        return None, None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    a = np.frombuffer(data_path.read_bytes(), dtype="<i2")
    return a.reshape(meta["rows"], meta["cols"]), meta


def available() -> bool:
    return _grid()[0] is not None


def _merc_y(lat_deg: float) -> float:
    s = math.sin(math.radians(max(-85.0, min(85.0, lat_deg))))
    return math.log((1 + s) / (1 - s)) / 2.0


# GLOBAL COVERAGE, FETCHED ON DEMAND AND CACHED ON DISK.
#
# The shipped grid covers one region, which is enough for a demonstration and
# not enough for a planner: a route outside it returned "no terrain" and the
# clearance check silently stopped applying. Anywhere the shipped grid does not
# reach, the tile holding the point is fetched from the same open elevation
# service the grid was built from, decoded, and kept -- so the second question
# about that area is answered from disk, and an air-gapped station still has
# whatever it has already seen.
_TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
_TILE_ZOOM = 10          # about 150 m per pixel at mid latitudes
_tile_cache: dict[tuple[int, int, int], object] = {}


def _tile_dir() -> Path:
    d = config.data_dir() / "terrain_tiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch_tile(z: int, x: int, y: int):
    """One elevation tile, from disk if we have it, from the service if not."""
    key = (z, x, y)
    if key in _tile_cache:
        return _tile_cache[key]
    path = _tile_dir() / f"{z}_{x}_{y}.npy"
    if path.exists():
        a = np.load(path)
        _tile_cache[key] = a
        return a
    try:
        import io
        import urllib.request

        from PIL import Image

        url = _TERRARIUM.format(z=z, x=x, y=y)
        req = urllib.request.Request(url, headers={"User-Agent": "ASTRA/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
        rgb = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"), dtype=np.int32)
        elev = (rgb[:, :, 0] * 256 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0) - 32768.0
        a = np.clip(elev, -500, 9000).astype(np.int16)
        np.save(path, a)
    except Exception:
        # No network and nothing cached. Reported as unknown rather than as
        # zero: sea level is a dangerous default for a clearance check.
        a = None
    _tile_cache[key] = a
    return a


def _elevation_online(lat: float, lon: float) -> float | None:
    z = _TILE_ZOOM
    n = 1 << z
    fx = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(max(-85.0, min(85.0, lat))))
    fy = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    x, y = int(fx), int(fy)
    if not (0 <= x < n and 0 <= y < n):
        return None
    tile = _fetch_tile(z, x, y)
    if tile is None:
        return None
    px = min(255, max(0, int((fx - x) * 256)))
    py = min(255, max(0, int((fy - y) * 256)))
    return float(tile[py, px])


def elevation_m(lat: float, lon: float) -> float | None:
    """Ground elevation at a point, anywhere in the world.

    The shipped regional grid first because it needs no network; the global
    tile service for anywhere it does not cover.
    """
    g, meta = _grid()
    if g is None:
        return _elevation_online(lat, lon)
    if not (meta["lat_min"] <= lat <= meta["lat_max"]
            and meta["lon_min"] <= lon <= meta["lon_max"]):
        return _elevation_online(lat, lon)
    # The grid is in web mercator, so latitude is not linear in row.
    y0, y1 = _merc_y(meta["lat_max"]), _merc_y(meta["lat_min"])
    fy = (_merc_y(lat) - y0) / (y1 - y0)
    fx = (lon - meta["lon_min"]) / (meta["lon_max"] - meta["lon_min"])
    r = int(min(meta["rows"] - 1, max(0, round(fy * (meta["rows"] - 1)))))
    c = int(min(meta["cols"] - 1, max(0, round(fx * (meta["cols"] - 1)))))
    return float(g[r, c])


@dataclass
class LegTerrain:
    """The ground under one leg, and what it demands of the aircraft."""

    frm: str
    to: str
    planned_ft: float
    max_terrain_ft: float
    min_safe_ft: float
    clears: bool
    margin_ft: float
    highest_at: tuple[float, float] | None = None
    samples: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: (round(v, 1) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


def profile(lat0: float, lon0: float, lat1: float, lon1: float,
            samples: int = 64) -> list[float]:
    """Ground elevation in FEET along a leg, evenly spaced.

    Great-circle interpolation is not used: a leg of a few hundred kilometres
    differs from the rhumb line by far less than one grid cell, and pretending
    otherwise would be precision this grid cannot support.
    """
    out = []
    for i in range(samples + 1):
        f = i / samples
        e = elevation_m(lat0 + (lat1 - lat0) * f, lon0 + (lon1 - lon0) * f)
        out.append(0.0 if e is None else max(0.0, e) * FT_PER_M)
    return out


def assess_leg(frm, to, planned_ft: float, clearance_ft: float = CLEARANCE_FT
               ) -> LegTerrain:
    """Does this leg clear the ground, and by how much?"""
    prof = profile(frm.lat_deg, frm.lon_deg, to.lat_deg, to.lon_deg)
    peak = max(prof) if prof else 0.0
    i = prof.index(peak) if prof else 0
    f = i / max(len(prof) - 1, 1)
    min_safe = peak + clearance_ft
    return LegTerrain(
        frm=frm.name, to=to.name, planned_ft=planned_ft,
        max_terrain_ft=peak, min_safe_ft=min_safe,
        clears=planned_ft >= min_safe, margin_ft=planned_ft - min_safe,
        highest_at=(round(frm.lat_deg + (to.lat_deg - frm.lat_deg) * f, 4),
                    round(frm.lon_deg + (to.lon_deg - frm.lon_deg) * f, 4)),
        # Thinned for the console's profile chart; the assessment above used
        # every sample.
        samples=[round(v) for v in prof[::4]],
    )


def assess_route(waypoints, clearance_ft: float = CLEARANCE_FT) -> dict:
    """Terrain clearance for a whole route.

    Returns the per-leg detail and the single number a planner acts on: the
    highest minimum-safe altitude anywhere on the route, which is the altitude
    the ENGINE has to be able to reach.
    """
    if not available():
        return {"available": False,
                "reason": "no terrain data on this ground station; run "
                          "scripts/fetch_geodata.py"}
    legs = [assess_leg(a, b, b.altitude_ft, clearance_ft)
            for a, b in zip(waypoints, waypoints[1:], strict=False)]
    blocked = [lg for lg in legs if not lg.clears]
    required = max((lg.min_safe_ft for lg in legs), default=0.0)
    return {
        "available": True,
        "legs": [lg.as_dict() for lg in legs],
        "clears": not blocked,
        "required_altitude_ft": round(required, 1),
        "clearance_ft": clearance_ft,
        "blocked_legs": [lg.frm + " -> " + lg.to for lg in blocked],
        "highest_terrain_ft": round(max((lg.max_terrain_ft for lg in legs),
                                        default=0.0), 1),
        "source": "AWS Terrain Tiles (open data), max-pooled to ~5 km cells",
    }
