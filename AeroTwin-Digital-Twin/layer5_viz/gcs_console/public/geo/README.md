# Map data

Fetched once by `python scripts/fetch_geodata.py`, not called at runtime.

| File | Source | Licence |
|---|---|---|
| `terrain.i16`, `terrain.json` | AWS Terrain Tiles (terrarium) | Open data |
| `coastline / countries / states / rivers / places .geojson` | Natural Earth | Public domain (CC0) |

The console's map draws **live global tiles** (OpenTopoMap, Esri, OpenStreetMap,
CARTO — each attributed on the map, none needing a key). These files are the
offline half: a station with no network shows no imagery, and the route, the
reach rings and the terrain clearance still work, because those are computed
from this data rather than fetched.

Terrain is downsampled by **maximum**, never by average. This grid decides
whether an aircraft clears the ground, so a peak inside a cell must not be
averaged away: the error has to fall on the side of calling a route blocked
that a finer grid would allow.
