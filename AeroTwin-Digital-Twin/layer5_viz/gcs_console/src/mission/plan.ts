/* The mission plan, and how it becomes something the engine model can fly.
 *
 * TWO MODELS, NOT ONE, AND THE DIFFERENCE IS THE POINT
 * ---------------------------------------------------
 * What the operator builds is a PLAN: named bases, transit points, and patrol
 * areas with a time on station. What `/api/mission/flight` accepts is a list of
 * between two and twenty-four plain waypoints -- name, latitude, longitude,
 * altitude -- and nothing else. There is no loiter in the backend's vocabulary;
 * `layer4_core/flight_sim.py` knows START, WARMUP, TAKEOFF, CLIMB, CRUISE,
 * DESCENT and LANDING, and that is the whole list.
 *
 * So a patrol area is not a flag on a request the server would ignore. It is
 * EXPANDED HERE into the actual circuit the aircraft would fly -- laps of an
 * orbit or a racetrack at the patrol altitude -- and those legs are sent as
 * ordinary waypoints. The model then flies every one of them: the time on
 * station, the fuel burned and the engine life consumed are results of the
 * physics stepping through that geometry, not a loiter allowance added
 * afterwards.
 *
 * WHICH MEANS THE TIME ON STATION IS MEASURED, NOT ASKED FOR
 * ---------------------------------------------------------
 * A pattern of a given radius flown at a given airspeed takes as long as it
 * takes. The operator asks for 90 minutes; this lays out whole laps and
 * reports what those laps actually come to. Where the two differ the UI says
 * so. Rounding a lap up to hit a round number would be the one thing this file
 * exists to avoid -- a number on the screen that the simulation did not fly.
 *
 * WHAT IS NOT OFFERED, AND WHY
 * ----------------------------
 *   Per-waypoint speed. `RouteRequest.true_airspeed_kmh` is one figure for the
 *   whole sortie (layer4_core/twin_api.py). A per-leg speed control would be a
 *   control that changes nothing.
 *
 *   Cruise throttle. `flight_sim` flies the cruise at CRUISE_THROTTLE_PCT and
 *   takes no throttle from the request. Throttle IS settable on
 *   /api/scenarios/custom, which holds one condition rather than flying a
 *   route, and that is where the console offers it.
 *
 *   An alternate that is flown. The backend has no divert concept. The
 *   alternate is carried in the plan and drawn on the map because it is part of
 *   the decision; it is not part of the sortie the model flies, and the panel
 *   says so.
 */

import { BASE_BY_ID, bearingDeg, destination, greatCircleKm,
         type Airbase } from "../data/airbases";
import type { RouteWaypoint } from "../lib/api";

export type PointKind = "DEPARTURE" | "TRANSIT" | "PATROL" | "RECOVERY";
export type Pattern = "ORBIT" | "RACETRACK";

export interface PlanPoint {
  /** Stable across edits so selection and animation survive a reorder. */
  id: string;
  kind: PointKind;
  name: string;
  lat_deg: number;
  lon_deg: number;
  altitude_ft: number;
  /** PATROL only: asked-for time on station, in minutes. */
  loiter_min?: number;
  /** PATROL only. */
  pattern?: Pattern;
  /** PATROL only: orbit radius / racetrack turn radius, in kilometres. */
  radius_km?: number;
  /** Set when the point came from the airbase table rather than the map. */
  base_id?: string;
}

export interface MissionPlan {
  name: string;
  /** One of MISSION_TYPES. Becomes CUSTOM once the operator edits the route. */
  type: string;
  points: PlanPoint[];
  /** Planning only -- never flown. See the file header. */
  alternate_id: string | null;
  /** Sent as RouteRequest.true_airspeed_kmh. */
  airspeed_kmh: number;
  isa_deviation_c: number;
  humidity_pct: number;
  usable_fuel_l: number;
  /** FlightRequest.use_live_engine: this engine as worn, or the type as new. */
  live_engine: boolean;
}

/* The server's own bound. `RouteRequest.waypoints` is min_length=2,
 * max_length=24, so a patrol cannot be expanded past what will be accepted and
 * the UI has to say when a request has been clipped rather than let the server
 * reject the sortie. */
export const MAX_WAYPOINTS = 24;

/* Points laid out per lap. A hexagon is a poor circle and a perfectly good
 * ORBIT: the aircraft flies straight legs between turn points either way, and
 * six keeps three laps inside the waypoint budget where twelve would not. */
const PER_LAP: Record<Pattern, number> = { ORBIT: 6, RACETRACK: 6 };

/* ------------------------------------------------------------------ *
 * Mission types
 *
 * These are TEMPLATES for a plan, not a mode the backend runs in. Each
 * seeds an altitude, an airspeed and a time on station in the region of
 * the corresponding profile in `layer4_core/mission.py`, which is what
 * the Go / No-Go table assesses. Choosing one fills the builder in;
 * everything it filled in can then be changed.
 * ------------------------------------------------------------------ */

export interface MissionType {
  key: string;
  label: string;
  /** The profile in snap.mission.profiles this template is shaped after. */
  profile: string | null;
  cruise_ft: number;
  patrol_ft: number;
  airspeed_kmh: number;
  loiter_min: number;
  radius_km: number;
  blurb: string;
}

export const MISSION_TYPES: MissionType[] = [
  { key: "TRANSIT", label: "Transit", profile: "TRANSIT",
    cruise_ft: 12000, patrol_ft: 12000, airspeed_kmh: 195, loiter_min: 0,
    radius_km: 12,
    blurb: "Point to point, no time on station. The shortest sortie the twin assesses." },
  { key: "ISR", label: "ISR patrol", profile: "ISR_PATROL",
    cruise_ft: 15000, patrol_ft: 18000, airspeed_kmh: 175, loiter_min: 90,
    radius_km: 15,
    blurb: "Transit out, orbit the area, transit home. The reference MALE sortie." },
  { key: "ENDURANCE", label: "Endurance", profile: "ENDURANCE",
    cruise_ft: 14000, patrol_ft: 16000, airspeed_kmh: 155, loiter_min: 180,
    radius_km: 22,
    blurb: "Long time on station at a low cruise setting. Consumes the most life per sortie." },
  { key: "HIGH_ALT", label: "High-altitude ISR", profile: "HIGH_ALT_ISR",
    cruise_ft: 20000, patrol_ft: 24000, airspeed_kmh: 185, loiter_min: 60,
    radius_km: 18,
    blurb: "Above 20,000 ft, where a worn turbocharger runs out of ceiling first." },
  { key: "CUSTOM", label: "Custom", profile: null,
    cruise_ft: 15000, patrol_ft: 18000, airspeed_kmh: 175, loiter_min: 60,
    radius_km: 15,
    blurb: "Whatever has been drawn on the map." },
];

export const TYPE_BY_KEY: Record<string, MissionType> =
  Object.fromEntries(MISSION_TYPES.map((t) => [t.key, t]));

let seq = 0;
export const newId = () => "p" + (++seq);

/* ------------------------------------------------------------------ *
 * Building a plan
 * ------------------------------------------------------------------ */

export function basePoint(b: Airbase, kind: "DEPARTURE" | "RECOVERY"): PlanPoint {
  return {
    id: newId(), kind, name: b.short, base_id: b.id,
    lat_deg: b.lat_deg, lon_deg: b.lon_deg,
    /* The field, at the field. `flight_sim` puts the start, warm-up, take-off
     * and landing at the elevation it reads out of the terrain grid, so this
     * altitude is only what the first leg climbs away from. */
    altitude_ft: Math.round(b.elevation_ft),
  };
}

/** A plan shaped by a mission type, between two fields. */
export function buildPlan(type: MissionType, dep: Airbase, rec: Airbase,
                          existing?: Partial<MissionPlan>): MissionPlan {
  const points: PlanPoint[] = [basePoint(dep, "DEPARTURE")];

  /* The area sits on the track between the two fields, about two thirds of the
   * way out -- far enough to be a sortie, close enough to come home from. A
   * transit has none at all, which is what makes it a transit. */
  if (type.loiter_min > 0) {
    const km = greatCircleKm(dep.lat_deg, dep.lon_deg, rec.lat_deg, rec.lon_deg);
    const brg = bearingDeg(dep.lat_deg, dep.lon_deg, rec.lat_deg, rec.lon_deg);
    /* Two fields that are the same field give a bearing of zero and a distance
     * of zero, so the area would land on top of them. Push it out. */
    const out = km > 40 ? km * 0.62 : 180;
    const c = destination(dep.lat_deg, dep.lon_deg, km > 40 ? brg : 300, out);
    const ip = {
      lat_deg: +(dep.lat_deg + (c.lat - dep.lat_deg) * 0.45).toFixed(4),
      lon_deg: +(dep.lon_deg + (c.lon - dep.lon_deg) * 0.45).toFixed(4),
    };
    points.push({ id: newId(), kind: "TRANSIT", name: "IP",
                  ...ip, altitude_ft: type.cruise_ft });
    points.push({
      id: newId(), kind: "PATROL", name: "AREA ALPHA",
      lat_deg: +c.lat.toFixed(4), lon_deg: +c.lon.toFixed(4),
      altitude_ft: type.patrol_ft,
      loiter_min: type.loiter_min, pattern: "ORBIT", radius_km: type.radius_km,
    });
  } else {
    points.push({
      id: newId(), kind: "TRANSIT", name: "WP1",
      lat_deg: +((dep.lat_deg + rec.lat_deg) / 2).toFixed(4),
      lon_deg: +((dep.lon_deg + rec.lon_deg) / 2).toFixed(4),
      altitude_ft: type.cruise_ft,
    });
  }

  points.push(basePoint(rec, "RECOVERY"));

  return {
    name: existing?.name || (type.label + " — " + dep.short + " to " + rec.short),
    type: type.key,
    points,
    alternate_id: existing?.alternate_id ?? null,
    airspeed_kmh: type.airspeed_kmh,
    isa_deviation_c: existing?.isa_deviation_c ?? 0,
    humidity_pct: existing?.humidity_pct ?? 30,
    usable_fuel_l: existing?.usable_fuel_l ?? 120,
    live_engine: existing?.live_engine ?? true,
  };
}

/** A plan with nothing chosen: no type, no fields, no route.
 *
 * The page used to open on an ISR patrol from Jodhpur to Uttarlai with an IP
 * and a patrol area already laid down, so the first thing an operator saw was
 * a sortie somebody else had decided. Now every one of those is theirs to
 * pick; only the conditions (air, fuel, which engine) keep a starting value,
 * because a sortie cannot be flown without them. */
export function emptyPlan(existing?: Partial<MissionPlan>): MissionPlan {
  return {
    name: "",
    type: "",
    points: [],
    alternate_id: null,
    airspeed_kmh: existing?.airspeed_kmh ?? TYPE_BY_KEY.CUSTOM.airspeed_kmh,
    isa_deviation_c: existing?.isa_deviation_c ?? 0,
    humidity_pct: existing?.humidity_pct ?? 30,
    usable_fuel_l: existing?.usable_fuel_l ?? 120,
    live_engine: existing?.live_engine ?? true,
  };
}

/** Put a field in as the departure or the recovery.
 *
 * While the route is still only fields, the chosen mission type is kept, and
 * the pick that completes the pair draws that type's route between them --
 * the route choosing the type would have drawn had the fields come first.
 * Once a route has been drawn, changing a field edits it: CUSTOM, as before. */
export function withBase(plan: MissionPlan, b: Airbase,
                         kind: "DEPARTURE" | "RECOVERY"): MissionPlan {
  const i = plan.points.findIndex((q) => q.kind === kind);
  const made = basePoint(b, kind);
  const points = [...plan.points];
  if (i >= 0) points[i] = { ...made, id: points[i].id };
  else if (kind === "DEPARTURE") points.unshift(made);
  else points.push(made);

  const onlyFields = points.every((q) => q.kind === "DEPARTURE" || q.kind === "RECOVERY");
  if (!onlyFields) return { ...plan, points, type: "CUSTOM" };
  const t = TYPE_BY_KEY[plan.type];
  const dep = points.find((q) => q.kind === "DEPARTURE");
  const rec = [...points].reverse().find((q) => q.kind === "RECOVERY");
  if (t && t.key !== "CUSTOM" && dep?.base_id && rec?.base_id) {
    return buildPlan(t, BASE_BY_ID[dep.base_id], BASE_BY_ID[rec.base_id], plan);
  }
  return { ...plan, points };
}

/* ------------------------------------------------------------------ *
 * Expansion: plan -> the waypoints the server is actually sent
 * ------------------------------------------------------------------ */

export interface ExpandedPatrol {
  /** The PlanPoint this came from. */
  point_id: string;
  /** The circuit, closed, for drawing. */
  ring: { lat_deg: number; lon_deg: number }[];
  laps: number;
  /** Length of ONE lap as it will actually be flown, in km. */
  lap_km: number;
  /** What those laps come to at the plan's airspeed. */
  achieved_min: number;
  requested_min: number;
  /** True when the waypoint budget stopped it reaching the requested time. */
  clipped: boolean;
}

export interface Expansion {
  waypoints: RouteWaypoint[];
  patrols: ExpandedPatrol[];
  /** Straight-line route length over the expanded waypoints, km. */
  distance_km: number;
  /** distance / airspeed. GEOMETRY, not a flight time -- the model adds the
   *  start, warm-up, take-off, climb and landing, and it is the one that
   *  knows how long they take on the day. */
  air_minutes: number;
  on_station_min: number;
  /** Plain-language problems that would make the request invalid. */
  errors: string[];
  notes: string[];
}

/** Lay out one lap of a pattern, entered on the `inbound` bearing. */
function lap(centre: { lat: number; lon: number }, radiusKm: number,
             inbound: number, pattern: Pattern): { lat: number; lon: number }[] {
  const n = PER_LAP[pattern];
  if (pattern === "ORBIT") {
    /* A regular polygon, starting at the point nearest the arriving track so
     * the aircraft joins the circuit rather than cutting across it. */
    return Array.from({ length: n }, (_, i) =>
      destination(centre.lat, centre.lon, (inbound + 180 + (360 / n) * i) % 360,
                  radiusKm));
  }
  /* RACETRACK: straights aligned with the inbound track, with a turn point
   * beyond each end. Six points, laid out anticlockwise from the near side. */
  const ax = inbound;
  const cross = (inbound + 90) % 360;
  const half = radiusKm * 2;
  const a = destination(centre.lat, centre.lon, ax, half);
  const b = destination(centre.lat, centre.lon, (ax + 180) % 360, half);
  const off = (p: { lat: number; lon: number }, dir: number) =>
    destination(p.lat, p.lon, dir, radiusKm);
  return [
    off(b, cross),
    off(a, cross),
    destination(a.lat, a.lon, ax, radiusKm),
    off(a, (cross + 180) % 360),
    off(b, (cross + 180) % 360),
    destination(b.lat, b.lon, (ax + 180) % 360, radiusKm),
  ];
}

function ringKm(ring: { lat: number; lon: number }[]): number {
  let km = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i], b = ring[(i + 1) % ring.length];
    km += greatCircleKm(a.lat, a.lon, b.lat, b.lon);
  }
  return km;
}

/**
 * Turn a plan into the request body the server will fly.
 *
 * Every waypoint returned is one the engine model will actually step through.
 * Nothing is added to the answer afterwards.
 */
export function expand(plan: MissionPlan): Expansion {
  const out: RouteWaypoint[] = [];
  const patrols: ExpandedPatrol[] = [];
  const errors: string[] = [];
  const notes: string[] = [];
  const speed = Math.max(plan.airspeed_kmh, 1);

  const pts = plan.points;
  if (pts.length < 2) {
    errors.push("A sortie needs at least a departure and a recovery field.");
  }

  /* How many waypoints the non-patrol points will use, so a patrol knows what
   * budget is left before it lays out its laps. */
  const fixed = pts.filter((p) => p.kind !== "PATROL").length;
  let spare = MAX_WAYPOINTS - fixed;

  pts.forEach((p, i) => {
    if (p.kind !== "PATROL") {
      out.push({ name: p.name.slice(0, 24) || ("WP" + (i + 1)),
                 lat_deg: p.lat_deg, lon_deg: p.lon_deg,
                 altitude_ft: p.altitude_ft });
      return;
    }

    const radius = Math.max(2, p.radius_km ?? 15);
    const pattern = p.pattern ?? "ORBIT";
    const prev = pts[i - 1];
    const inbound = prev
      ? bearingDeg(prev.lat_deg, prev.lon_deg, p.lat_deg, p.lon_deg)
      : 0;
    const ring = lap({ lat: p.lat_deg, lon: p.lon_deg }, radius, inbound, pattern);
    const lapKm = ringKm(ring);
    const lapMin = (lapKm / speed) * 60;
    const want = Math.max(0, p.loiter_min ?? 0);

    const budgetLaps = Math.max(0, Math.floor(spare / ring.length));
    const wantLaps = Math.max(1, Math.round(want / Math.max(lapMin, 0.1)));
    const laps = Math.max(0, Math.min(wantLaps, budgetLaps));

    if (laps === 0) {
      errors.push(
        p.name + ": no room left inside the twenty-four waypoints the server "
        + "accepts for even one lap. Remove a transit point or an area.");
      return;
    }

    for (let L = 0; L < laps; L++) {
      ring.forEach((q, k) => {
        out.push({
          name: (p.name.slice(0, 14) + " " + (L + 1) + "." + (k + 1)).slice(0, 24),
          lat_deg: +q.lat.toFixed(4), lon_deg: +q.lon.toFixed(4),
          altitude_ft: p.altitude_ft,
        });
      });
    }
    spare -= laps * ring.length;

    const achieved = laps * lapMin;
    const clipped = laps < wantLaps;
    if (clipped) {
      notes.push(
        p.name + ": " + laps + " lap" + (laps === 1 ? "" : "s")
        + " fit inside the waypoint limit — " + fmtMin(achieved)
        + " on station rather than the " + fmtMin(want)
        + " asked for. A wider radius buys more time per lap.");
    } else if (want > 0 && Math.abs(achieved - want) > 1) {
      notes.push(
        p.name + ": laps are whole, so " + fmtMin(achieved) + " on station "
        + "rather than exactly " + fmtMin(want) + ". The model flies the laps.");
    }

    patrols.push({
      point_id: p.id,
      ring: ring.map((q) => ({ lat_deg: q.lat, lon_deg: q.lon })),
      laps, lap_km: lapKm, achieved_min: achieved, requested_min: want, clipped,
    });
  });

  if (out.length > MAX_WAYPOINTS) {
    errors.push(out.length + " waypoints; the server accepts " + MAX_WAYPOINTS + ".");
  }
  if (out.length < 2 && errors.length === 0) {
    errors.push("A sortie needs at least two waypoints.");
  }

  let distance = 0;
  for (let i = 1; i < out.length; i++) {
    distance += greatCircleKm(out[i - 1].lat_deg, out[i - 1].lon_deg,
                              out[i].lat_deg, out[i].lon_deg);
  }

  return {
    waypoints: out, patrols, errors, notes,
    distance_km: distance,
    air_minutes: (distance / speed) * 60,
    on_station_min: patrols.reduce((s, q) => s + q.achieved_min, 0),
  };
}

export function fmtMin(m: number): string {
  if (!isFinite(m)) return "—";
  const h = Math.floor(m / 60), r = Math.round(m % 60);
  return h ? h + " h " + String(r).padStart(2, "0") + " m" : r + " m";
}

export function fmtClock(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const x = Math.floor(s % 60);
  return h + ":" + String(m).padStart(2, "0") + ":" + String(x).padStart(2, "0");
}
