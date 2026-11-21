/* The fields a sortie can be launched from and recovered to.
 *
 * WHY THIS FILE EXISTS AT ALL
 * ---------------------------
 * Nothing in ASTRA held a location database. The route planner opened on five
 * anonymous coordinates called BASE, IP, TARGET, EGRESS, BASE -- real numbers,
 * but nothing an operator could recognise, and no way to say "fly this from
 * Jodhpur". Departure and recovery are the two decisions a mission plan starts
 * from, so they are named things here rather than latitudes typed by hand.
 *
 * WHAT IT IS AND IS NOT
 * ---------------------
 * It is a SHORT, CURATED list of real, published airfields in the operating
 * region this system is built for -- western and northern India -- chosen so
 * that the four mission profiles the twin already assesses each have somewhere
 * sensible to fly from: desert fields for the ISR and endurance profiles, a
 * high-altitude field for the high-altitude profile, a coastal one for the
 * humid case the PRD's environmental conditions call out.
 *
 * It is NOT an aeronautical database and must never be used as one. There is
 * no runway data, no frequencies, no procedures, no currency. Coordinates are
 * the published field reference point to four decimals and elevations are the
 * published field elevation; both are here so the map can show the field in
 * the right place and the plan can start at a sensible altitude.
 *
 * THE SIMULATOR DOES NOT TAKE ITS FIELD ELEVATION FROM HERE. `flight_sim`
 * reads the elevation under the first waypoint out of the terrain grid it was
 * shipped with (layer4_core/flight_sim.py, `field_elev_ft`), which is the same
 * ground the terrain clearance check uses. Two sources for one number is how
 * they come to disagree, so this one is for display and for seeding the plan.
 *
 * To add a field: one row here, nothing anywhere else.
 */

export type BaseRole = "DEPARTURE" | "RECOVERY" | "ALTERNATE";

export interface Airbase {
  /** ICAO location indicator where the field has one; the short name otherwise. */
  id: string;
  name: string;
  /** What an operator would say out loud. Kept short -- it is a map label. */
  short: string;
  lat_deg: number;
  lon_deg: number;
  /** Published field elevation. Display and plan seeding only -- see above. */
  elevation_ft: number;
  /** One line on why this field is in a list of ten. */
  note: string;
}

export const AIRBASES: Airbase[] = [
  { id: "VIJO", name: "Jodhpur", short: "JODHPUR", lat_deg: 26.2511, lon_deg: 73.0489,
    elevation_ft: 717,
    note: "Desert field on the Thar's eastern edge — the hot-and-dry case in PRD §18.3." },
  { id: "VIUT", name: "Uttarlai", short: "UTTARLAI", lat_deg: 25.8130, lon_deg: 71.4270,
    elevation_ft: 500,
    note: "Forward desert field, short reach to the western border area." },
  { id: "VIJR", name: "Jaisalmer", short: "JAISALMER", lat_deg: 26.8887, lon_deg: 70.8650,
    elevation_ft: 754,
    note: "Deep desert. Highest summer ambient of any field here." },
  { id: "VIBK", name: "Nal (Bikaner)", short: "NAL", lat_deg: 28.0706, lon_deg: 73.2072,
    elevation_ft: 750,
    note: "Northern desert field; common recovery for sorties launched further south." },
  { id: "VIPL", name: "Phalodi", short: "PHALODI", lat_deg: 27.1333, lon_deg: 72.3870,
    elevation_ft: 730,
    note: "Central Thar. Useful as an alternate between Jodhpur and Jaisalmer." },
  { id: "VIDX", name: "Hindan", short: "HINDAN", lat_deg: 28.7078, lon_deg: 77.3587,
    elevation_ft: 705,
    note: "Plains field near Delhi — the transit profile's usual departure." },
  { id: "VIAG", name: "Agra", short: "AGRA", lat_deg: 27.1558, lon_deg: 77.9609,
    elevation_ft: 551,
    note: "Plains field, low elevation, long runway." },
  { id: "VISA", name: "Sirsa", short: "SIRSA", lat_deg: 29.5606, lon_deg: 75.0058,
    elevation_ft: 650,
    note: "Northern plains; the cold-day case in winter." },
  { id: "VILH", name: "Leh", short: "LEH", lat_deg: 34.1359, lon_deg: 77.5465,
    elevation_ft: 10682,
    note: "10,682 ft field. A turbocharged engine leaves the ground here with a "
        + "ceiling already partly spent — the high-altitude profile's hard case." },
  { id: "VAPR", name: "Porbandar", short: "PORBANDAR", lat_deg: 21.6487, lon_deg: 69.6572,
    elevation_ft: 22,
    note: "Coastal, sea level, high humidity — the wet-hot case in PRD §18.3." },
];

export const BASE_BY_ID: Record<string, Airbase> = Object.fromEntries(
  AIRBASES.map((b) => [b.id, b]));

/** The nearest field to a point, and how far away it is. Used to answer
 *  "what did I just click on" without a lookup service. */
export function nearestBase(lat: number, lon: number): { base: Airbase; km: number } {
  let best = AIRBASES[0];
  let bestKm = Infinity;
  for (const b of AIRBASES) {
    const km = greatCircleKm(lat, lon, b.lat_deg, b.lon_deg);
    if (km < bestKm) { bestKm = km; best = b; }
  }
  return { base: best, km: bestKm };
}

/** Great circle in kilometres. The same earth radius layer4_core uses. */
export function greatCircleKm(lat1: number, lon1: number,
                              lat2: number, lon2: number): number {
  const R = 6371.0088;
  const rad = Math.PI / 180;
  const p1 = lat1 * rad, p2 = lat2 * rad;
  const dp = (lat2 - lat1) * rad, dl = (lon2 - lon1) * rad;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** Initial true bearing from one point to another, in degrees. */
export function bearingDeg(lat1: number, lon1: number,
                          lat2: number, lon2: number): number {
  const rad = Math.PI / 180;
  const p1 = lat1 * rad, p2 = lat2 * rad, dl = (lon2 - lon1) * rad;
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (((Math.atan2(y, x) / rad) % 360) + 360) % 360;
}

/** Walk `km` from a point on `brg`. Used to lay out a patrol pattern. */
export function destination(lat: number, lon: number, brg: number, km: number):
    { lat: number; lon: number } {
  const R = 6371.0088;
  const rad = Math.PI / 180;
  const d = km / R;
  const p1 = lat * rad, l1 = lon * rad, b = brg * rad;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) +
                       Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1),
                             Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return { lat: p2 / rad, lon: (((l2 / rad + 540) % 360) - 180) };
}
