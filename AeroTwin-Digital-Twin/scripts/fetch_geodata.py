"""Fetch the real map data the mission planner draws: terrain and geography.

    python scripts/fetch_geodata.py

WHY THIS EXISTS
---------------
The first mission planner drew a coordinate graticule with the route on it and
called it a plan view. It was not a map: no terrain, no coastline, no borders,
nothing an operator could recognise a place by, and -- worse for a system that
claims to say whether a sortie is possible -- no ground to fly over. A route
that passes through a mountain looked exactly like one that did not.

WHAT IS FETCHED, AND WHY THESE SOURCES
--------------------------------------
Both are open data that can be REDISTRIBUTED and then used with no network at
all, which a ground station may not have:

  Natural Earth (public domain, CC0)      coastline, borders, states, rivers,
                                          populated places
  AWS Terrain Tiles (open data)           real elevation, decoded from the
                                          terrarium PNG encoding

Neither is a tile service the console calls at runtime. They are fetched once,
clipped to the operating region, and written into the console's own assets. A
console that goes blank without the internet is no use to an aircraft that
operates where there is none.

TERRAIN IS DOWNSAMPLED BY **MAXIMUM**, NOT BY AVERAGE
-----------------------------------------------------
The grid is coarsened to keep it small enough to ship. Averaging a cell would
quietly lower the peak inside it, and this grid is used to decide whether an
aircraft clears the ground. Taking the maximum keeps the answer on the safe
side of the error: the planner may tell you a route is blocked when a finer
grid would allow it, and will not tell you a route is clear when it is not.
"""

from __future__ import annotations

import io
import json
import math
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "layer5_viz" / "gcs_console" / "public" / "geo"

# The operating region. Generous around the Indian subcontinent; change it and
# re-run for a different theatre.
LAT_MIN, LAT_MAX = 6.0, 37.5
LON_MIN, LON_MAX = 67.0, 98.5

# z=7 is about 1.2 km per pixel at these latitudes. Finer buys detail the
# planner cannot use and a file the browser has to carry.
ZOOM = 7
DOWNSAMPLE = 4          # -> roughly 5 km per cell after the max-pool

TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
NE = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
      "geojson/{name}.geojson")


def _get(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ASTRA/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _tile_x(lon: float, z: int) -> float:
    return (lon + 180.0) / 360.0 * (1 << z)


def _tile_y(lat: float, z: int) -> float:
    s = math.sin(math.radians(lat))
    return (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * (1 << z)


def fetch_terrain() -> None:
    """Real elevation for the region, as an Int16 grid the console can carry."""
    x0, x1 = int(_tile_x(LON_MIN, ZOOM)), int(_tile_x(LON_MAX, ZOOM))
    y0, y1 = int(_tile_y(LAT_MAX, ZOOM)), int(_tile_y(LAT_MIN, ZOOM))
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    print(f"terrain: {nx} x {ny} = {nx * ny} tiles at z{ZOOM}")

    from PIL import Image

    grid = np.zeros((ny * 256, nx * 256), dtype=np.int16)

    def one(job):
        ix, iy = job
        url = TERRARIUM.format(z=ZOOM, x=x0 + ix, y=y0 + iy)
        for attempt in range(3):
            try:
                a = np.asarray(Image.open(io.BytesIO(_get(url))).convert("RGB"),
                               dtype=np.int32)
                # The terrarium encoding, from its own specification.
                elev = (a[:, :, 0] * 256 + a[:, :, 1] + a[:, :, 2] / 256.0) - 32768.0
                return ix, iy, np.clip(elev, -500, 9000).astype(np.int16)
            except Exception:
                if attempt == 2:
                    return ix, iy, None
        return ix, iy, None

    jobs = [(ix, iy) for iy in range(ny) for ix in range(nx)]
    failed = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for n, (ix, iy, tile) in enumerate(pool.map(one, jobs), 1):
            if tile is None:
                failed += 1
            else:
                grid[iy * 256:(iy + 1) * 256, ix * 256:(ix + 1) * 256] = tile
            if n % 25 == 0:
                print(f"  {n}/{len(jobs)} tiles")
    if failed:
        print(f"  WARNING: {failed} tile(s) could not be fetched and read as 0 m")

    # MAX-pool, not mean. See the module docstring: this grid decides whether an
    # aircraft clears the ground, so the error has to fall on the safe side.
    k = DOWNSAMPLE
    h, w = grid.shape[0] // k * k, grid.shape[1] // k * k
    small = grid[:h, :w].reshape(h // k, k, w // k, k).max(axis=(1, 3))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "terrain.i16").write_bytes(small.astype("<i2").tobytes())

    # The exact web-mercator window the grid covers, so the console can map a
    # latitude and longitude to a cell without guessing.
    def _lat_of_tile_y(ty: float) -> float:
        n = math.pi - 2.0 * math.pi * ty / (1 << ZOOM)
        return math.degrees(math.atan(math.sinh(n)))

    meta = {
        "rows": int(small.shape[0]), "cols": int(small.shape[1]),
        "lon_min": x0 / (1 << ZOOM) * 360.0 - 180.0,
        "lon_max": (x1 + 1) / (1 << ZOOM) * 360.0 - 180.0,
        "lat_max": _lat_of_tile_y(y0),
        "lat_min": _lat_of_tile_y(y1 + 1),
        "zoom": ZOOM, "downsample": k, "dtype": "int16-le", "units": "metres",
        "pooling": "maximum",
        "source": "AWS Terrain Tiles (open data), terrarium encoding",
        "note": ("downsampled by MAXIMUM so terrain clearance errs on the safe "
                 "side: a peak inside a cell is never averaged away"),
    }
    (OUT / "terrain.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"  wrote terrain.i16  {small.shape}  "
          f"{(OUT / 'terrain.i16').stat().st_size / 1e6:.1f} MB")
    print(f"  elevation range {int(small.min())} to {int(small.max())} m")


def _bbox_of(geom) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []

    def walk(c):
        if isinstance(c, (int, float)):
            return
        if len(c) == 2 and isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1]); return
        for part in c:
            walk(part)

    walk(geom.get("coordinates", []))
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _decimate(coords, tol: float):
    """Drop points closer together than `tol` degrees.

    Crude beside Douglas-Peucker and adequate here: this is a basemap drawn at
    a few hundred pixels, and the alternative is shipping 13 MB of coastline to
    a console so it can draw a line 400 px long.
    """
    if not coords or isinstance(coords[0], (int, float)):
        return coords
    if isinstance(coords[0][0], (int, float)):
        out = [coords[0]]
        for p in coords[1:-1]:
            q = out[-1]
            if abs(p[0] - q[0]) + abs(p[1] - q[1]) >= tol:
                out.append(p)
        if len(coords) > 1:
            out.append(coords[-1])
        return out if len(out) > 1 else coords[:2]
    return [_decimate(c, tol) for c in coords]


def fetch_vectors() -> None:
    """Coastline, borders, states, rivers and cities, clipped to the region."""
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = (
        ("ne_10m_coastline", "coastline", 0.02, None),
        ("ne_10m_admin_0_countries", "countries", 0.02, ("NAME",)),
        ("ne_10m_admin_1_states_provinces", "states", 0.03, ("name",)),
        ("ne_10m_rivers_lake_centerlines", "rivers", 0.03, ("name",)),
        ("ne_10m_populated_places_simple", "places", 0.0, ("name", "pop_max")),
    )
    for name, short, tol, keep in wanted:
        print(f"vectors: {short} ...", end=" ", flush=True)
        raw = json.loads(_get(NE.format(name=name), timeout=180))
        out = []
        for f in raw.get("features", []):
            g = f.get("geometry") or {}
            if not g.get("coordinates"):
                continue
            x0, y0, x1, y1 = _bbox_of(g)
            if x1 < LON_MIN or x0 > LON_MAX or y1 < LAT_MIN or y0 > LAT_MAX:
                continue
            if tol:
                g = {**g, "coordinates": _decimate(g["coordinates"], tol)}
            props = ({k: f.get("properties", {}).get(k) for k in keep}
                     if keep else {})
            if short == "places":
                # A basemap is for orientation, not a gazetteer. The largest
                # places only, or the label layer is unreadable.
                if (props.get("pop_max") or 0) < 300_000:
                    continue
            out.append({"type": "Feature", "properties": props, "geometry": g})
        blob = {"type": "FeatureCollection", "features": out}
        path = OUT / f"{short}.geojson"
        path.write_text(json.dumps(blob, separators=(",", ":")), encoding="utf-8")
        print(f"{len(out)} features, {path.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    print(f"region  lat {LAT_MIN}..{LAT_MAX}  lon {LON_MIN}..{LON_MAX}")
    if "--vectors-only" not in sys.argv:
        fetch_terrain()
    if "--terrain-only" not in sys.argv:
        fetch_vectors()
    print(f"\nwrote to {OUT}")
