/* Real geography for the mission planner: projection, terrain, basemap.
 *
 * WHY THIS IS NOT A TILE SERVICE
 * ------------------------------
 * A ground station for a MALE UAV may be air-gapped, and every online tile
 * provider worth using is, by definition, online. So the map data is fetched
 * ONCE by scripts/fetch_geodata.py, clipped to the operating region, and
 * shipped with the console: real coastline, borders, states, rivers and cities
 * from Natural Earth (public domain), and real elevation from the AWS open
 * Terrain Tiles. Nothing here calls anything at runtime.
 */

/** Web mercator, which is what the elevation grid is sampled in. */
export function mercY(latDeg: number): number {
  const s = Math.sin((Math.max(-85, Math.min(85, latDeg)) * Math.PI) / 180);
  return Math.log((1 + s) / (1 - s)) / 2;
}

export function latOfMercY(y: number): number {
  return (Math.atan(Math.sinh(y)) * 180) / Math.PI;
}

export interface TerrainMeta {
  rows: number; cols: number;
  lon_min: number; lon_max: number; lat_min: number; lat_max: number;
  pooling: string; source: string; note: string;
}

export interface Terrain {
  meta: TerrainMeta;
  data: Int16Array;
  /** Metres above sea level, or null outside the fetched region. */
  at(lat: number, lon: number): number | null;
}

export async function loadTerrain(): Promise<Terrain | null> {
  try {
    const [meta, buf] = await Promise.all([
      fetch("/geo/terrain.json").then((r) => r.json() as Promise<TerrainMeta>),
      fetch("/geo/terrain.i16").then((r) => r.arrayBuffer()),
    ]);
    const data = new Int16Array(buf);
    const y0 = mercY(meta.lat_max);
    const y1 = mercY(meta.lat_min);
    return {
      meta, data,
      at(lat, lon) {
        if (lat < meta.lat_min || lat > meta.lat_max ||
            lon < meta.lon_min || lon > meta.lon_max) return null;
        const fy = (mercY(lat) - y0) / (y1 - y0);
        const fx = (lon - meta.lon_min) / (meta.lon_max - meta.lon_min);
        const r = Math.min(meta.rows - 1, Math.max(0, Math.round(fy * (meta.rows - 1))));
        const c = Math.min(meta.cols - 1, Math.max(0, Math.round(fx * (meta.cols - 1))));
        return data[r * meta.cols + c];
      },
    };
  } catch {
    return null;   // the console says so rather than drawing a blank rectangle
  }
}

export type GeoJson = { features: { properties: any; geometry: any }[] };

export async function loadVectors(): Promise<Record<string, GeoJson>> {
  const names = ["coastline", "countries", "states", "rivers", "places"];
  const out: Record<string, GeoJson> = {};
  await Promise.all(names.map(async (n) => {
    try { out[n] = await fetch(`/geo/${n}.geojson`).then((r) => r.json()); }
    catch { /* a missing layer is drawn as absent, not as an error */ }
  }));
  return out;
}

/* HYPSOMETRIC TINT, the convention every aeronautical chart uses: low ground
 * green, rising through tan and brown, high ground white. It is not decoration
 * -- an operator reads altitude from colour before they read any number, and
 * the reference chart this was built against uses exactly this ramp.
 *
 * Deliberately NOT one of the console's six coding colours: terrain is not a
 * condition of the engine, and must never be mistaken for one. */
const BANDS: [number, [number, number, number]][] = [
  [-1,    [ 34,  62,  92]],   // water
  [0,     [ 92, 128,  86]],
  [300,   [126, 149,  92]],
  [800,   [166, 168,  99]],
  [1500,  [188, 160, 104]],
  [2500,  [176, 134,  98]],
  [3500,  [158, 118, 106]],
  [4500,  [178, 154, 148]],
  [5500,  [214, 206, 204]],
  [7000,  [246, 246, 248]],
];

export function terrainColour(m: number): [number, number, number] {
  if (m <= -400) return BANDS[0][1];
  let lo = BANDS[1];
  for (const b of BANDS) if (m >= b[0]) lo = b;
  const i = BANDS.indexOf(lo);
  const hi = BANDS[Math.min(i + 1, BANDS.length - 1)];
  if (hi === lo) return lo[1];
  const f = Math.max(0, Math.min(1, (m - lo[0]) / (hi[0] - lo[0])));
  return [0, 1, 2].map((k) =>
    Math.round(lo[1][k] + (hi[1][k] - lo[1][k]) * f)) as [number, number, number];
}
