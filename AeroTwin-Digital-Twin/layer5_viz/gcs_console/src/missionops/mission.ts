/* THE MISSION, DERIVED.
 *
 * Everything in here is computed from what the operator drew and from what the
 * server has already answered. Nothing is invented: a figure that cannot be
 * derived from the plan or from a response is absent, and the CHECKS below say
 * "not evaluated" rather than guessing.
 *
 * THREE KINDS OF NUMBER, KEPT APART ON PURPOSE
 *   INPUT    the operator typed it
 *   AUTO     geometry, or a conversion of an input. Available immediately.
 *   RESULT   the server flew or costed it. Absent until it has.
 *
 * The one thing this file refuses to do is present an AUTO number as a RESULT.
 * Air time over the ground at the planned airspeed is geometry; the sortie's
 * actual duration includes a start, a warm-up, a climb and a landing, and only
 * the flight model knows what those cost on the day.
 */

import { bearingDeg, greatCircleKm, BASE_BY_ID } from "../data/airbases";
import type { Envelope, FlightSim, RouteCost } from "../lib/api";
import type { Expansion, MissionPlan } from "../mission/plan";

/* ------------------------------------------------------------------ *
 * Mission identity
 * ------------------------------------------------------------------ */

export interface MissionIdentity {
  /** Operator's own reference for the sortie. */
  id: string;
  /** Tasking authority's reference, if there is one. */
  tasking: string;
  /** Planned take-off, ISO minutes in Z. "" when not set. */
  launch_utc: string;
}

const IDENT_KEY = "astra.missionops.identity";
const SEQ_KEY = "astra.missionops.seq";

/* A SORTIE ARRIVES WITH A NAME AND A TAKE-OFF TIME ALREADY ON IT.
 *
 * Making the operator type a mission number before the console will let them
 * draw a line is paperwork, not planning -- and a blank launch field is worse
 * than paperwork, because every ETA in the panel reads "—" until it is filled
 * and the route table looks broken rather than unset. Both are generated, both
 * are editable, and neither is a claim that anything has been filed: the API
 * carries no mission store, and the editor says so in one line.
 *
 * ASTRA-DDMMYY-NN, the date being the day the sortie launches and NN counting
 * the missions minted in this console session. */
export function autoMissionId(launch: string, seq: number): string {
  const t = Date.parse(launch.length <= 16 ? launch + ":00Z" : launch);
  const d = new Date(isFinite(t) ? t : Date.now());
  const two = (n: number) => String(n).padStart(2, "0");
  return "ASTRA-" + two(d.getUTCDate()) + two(d.getUTCMonth() + 1)
    + two(d.getUTCFullYear() % 100) + "-" + two(seq);
}

/** The next whole half hour at least thirty minutes out, in Zulu. */
export function defaultLaunch(now = Date.now()): string {
  const d = new Date(now + 30 * 60000);
  d.setUTCSeconds(0, 0);
  d.setUTCMinutes(d.getUTCMinutes() > 30 ? 60 : 30);
  const two = (n: number) => String(n).padStart(2, "0");
  return d.getUTCFullYear() + "-" + two(d.getUTCMonth() + 1) + "-"
    + two(d.getUTCDate()) + "T" + two(d.getUTCHours()) + ":"
    + two(d.getUTCMinutes());
}

function bumpSeq(): number {
  try {
    const n = Number(window.sessionStorage.getItem(SEQ_KEY) || 0) + 1;
    window.sessionStorage.setItem(SEQ_KEY, String(n));
    return n;
  } catch { return 1; }
}

/** A fresh identity: a generated number, a sensible launch, no tasking ref. */
export function newIdentity(): MissionIdentity {
  const launch_utc = defaultLaunch();
  return { id: autoMissionId(launch_utc, bumpSeq()), tasking: "", launch_utc };
}

/* KEPT FOR THE SESSION, AND SAID TO BE. The server has no mission store --
 * nothing in the API carries a mission name -- so this is the console's own
 * memory and it lives as long as the console does. Anything stronger would be
 * a claim that a sortie had been filed somewhere. */
export function loadIdentity(): MissionIdentity {
  let held: Partial<MissionIdentity> = {};
  try {
    const raw = window.sessionStorage.getItem(IDENT_KEY);
    if (raw) held = JSON.parse(raw) ?? {};
  } catch { /* no storage: the mission is simply unnamed */ }
  /* A held identity is restored as it was. A missing one -- or one left blank
   * by the version of this panel that made the operator type it -- is minted
   * rather than presented as an empty form. */
  if (held.id && held.launch_utc) {
    return { id: held.id, tasking: held.tasking ?? "",
             launch_utc: held.launch_utc };
  }
  const made = newIdentity();
  const out = {
    id: held.id || made.id,
    tasking: held.tasking ?? "",
    launch_utc: held.launch_utc || made.launch_utc,
  };
  /* WRITTEN BACK IMMEDIATELY, so minting happens exactly once. React's strict
   * mode invokes a state initialiser twice in development; without this the
   * second call minted a second number and the first mission of the session
   * was labelled 02. */
  saveIdentity(out);
  return out;
}

export function saveIdentity(v: MissionIdentity) {
  try { window.sessionStorage.setItem(IDENT_KEY, JSON.stringify(v)); }
  catch { /* no storage */ }
}

/** Minutes after launch as a Zulu clock, or "—" when no launch time is set. */
export function zuluAfter(launch: string, minutes: number): string {
  if (!launch) return "—";
  const t = Date.parse(launch.length <= 16 ? launch + ":00Z" : launch);
  if (!isFinite(t)) return "—";
  const d = new Date(t + minutes * 60000);
  return String(d.getUTCHours()).padStart(2, "0") + ":"
       + String(d.getUTCMinutes()).padStart(2, "0") + "Z";
}

/* ------------------------------------------------------------------ *
 * Segments -- the leg as an object
 * ------------------------------------------------------------------ */

export interface Segment {
  i: number;
  from: string;
  to: string;
  /** Great-circle over the ground, km. */
  distance_km: number;
  cumulative_km: number;
  /** True course, degrees. */
  course_deg: number;
  alt0_ft: number;
  alt1_ft: number;
  /** Minutes at the plan's true airspeed. Geometry, not flight time. */
  ete_min: number;
  cumulative_min: number;
  /** Feet per minute the climb needs to make the next waypoint's altitude. */
  required_fpm: number;
  /** Filled from RouteCost when the route has been costed. */
  cost?: {
    fuel_l: number; life_hours: number; hours: number;
    mean_power_kw: number; mean_cht_c: number; oat_c: number;
    wastegate_saturated_min: number; cooling_flap_saturated_min: number;
  };
  /** Filled from RouteCost.terrain when the route has been costed. */
  terrain?: {
    max_terrain_ft: number; min_safe_ft: number; clears: boolean;
    margin_ft: number;
  };
}

/** The legs of the expanded route, with everything geometry can give. */
export function segments(plan: MissionPlan, ex: Expansion,
                         cost: RouteCost | null): Segment[] {
  const w = ex.waypoints;
  const speed = Math.max(plan.airspeed_kmh, 1);
  const out: Segment[] = [];
  let cum = 0, cumMin = 0;
  for (let i = 1; i < w.length; i++) {
    const a = w[i - 1], b = w[i];
    const d = greatCircleKm(a.lat_deg, a.lon_deg, b.lat_deg, b.lon_deg);
    const ete = (d / speed) * 60;
    cum += d; cumMin += ete;
    out.push({
      i: i - 1, from: a.name, to: b.name,
      distance_km: d, cumulative_km: cum,
      course_deg: bearingDeg(a.lat_deg, a.lon_deg, b.lat_deg, b.lon_deg),
      alt0_ft: a.altitude_ft, alt1_ft: b.altitude_ft,
      ete_min: ete, cumulative_min: cumMin,
      /* What the climb has to average to arrive at the next altitude. The
       * flight model computes what the engine can ACTUALLY give from excess
       * power; this is only the demand, and the two are compared in CHECKS. */
      required_fpm: ete > 0 ? (b.altitude_ft - a.altitude_ft) / ete : 0,
    });
  }
  /* The server's own per-leg answers, matched by position. `RouteCost.legs`
   * is computed over the same expanded waypoint list this was, in the same
   * order, so index is the join -- names repeat on a patrol circuit and would
   * not be. */
  if (cost?.legs) {
    cost.legs.forEach((l, i) => {
      if (!out[i]) return;
      out[i].cost = {
        fuel_l: l.fuel_l, life_hours: l.life_hours, hours: l.hours,
        mean_power_kw: l.mean_power_kw, mean_cht_c: l.mean_cht_c, oat_c: l.oat_c,
        wastegate_saturated_min: l.wastegate_saturated_min,
        cooling_flap_saturated_min: l.cooling_flap_saturated_min,
      };
    });
  }
  if (cost?.terrain?.legs) {
    cost.terrain.legs.forEach((t, i) => {
      if (!out[i]) return;
      out[i].terrain = {
        max_terrain_ft: t.max_terrain_ft, min_safe_ft: t.min_safe_ft,
        clears: t.clears, margin_ft: t.margin_ft,
      };
    });
  }
  return out;
}

/** Where the aircraft will be, by segment, at a given time into the sortie. */
export function segmentAt(segs: Segment[], minutes: number): Segment | null {
  for (const s of segs) if (minutes <= s.cumulative_min) return s;
  return segs[segs.length - 1] ?? null;
}

/* ------------------------------------------------------------------ *
 * The alternate, which is planning-only and now says something
 * ------------------------------------------------------------------ */

export function divert(plan: MissionPlan): {
  id: string; name: string; km: number; course_deg: number; elevation_ft: number;
} | null {
  if (!plan.alternate_id) return null;
  const b = BASE_BY_ID[plan.alternate_id];
  const rec = [...plan.points].reverse().find((p) => p.kind === "RECOVERY")
              ?? plan.points[plan.points.length - 1];
  if (!b || !rec) return null;
  return {
    id: b.id, name: b.short, elevation_ft: b.elevation_ft,
    km: greatCircleKm(rec.lat_deg, rec.lon_deg, b.lat_deg, b.lon_deg),
    course_deg: bearingDeg(rec.lat_deg, rec.lon_deg, b.lat_deg, b.lon_deg),
  };
}

/* ------------------------------------------------------------------ *
 * CHECKS
 * ------------------------------------------------------------------ */

export type CheckState = "PASS" | "CAUTION" | "FAIL" | "PENDING" | "NA";

export interface Check {
  key: string;
  group: "ROUTE" | "TERRAIN" | "FUEL" | "PERFORMANCE" | "ENGINE" | "SCENARIO";
  label: string;
  state: CheckState;
  detail: string;
  /** Where the answer came from, so a reader can weigh it. */
  source: "plan" | "costing" | "flight" | "twin";
}

export interface Constraints {
  /** Feet of ground clearance the operator will accept. */
  min_clearance_ft: number;
  /** Minutes of fuel that must remain on landing. */
  reserve_min: number;
  /** Hours the sortie may not exceed. */
  max_duration_h: number;
  /** Feet of ceiling above the highest planned altitude. */
  ceiling_margin_ft: number;
}

export const DEFAULT_CONSTRAINTS: Constraints = {
  /* 1,000 ft is the figure the flight model itself raises a clearance caution
   * at, so the default here agrees with the server rather than competing. */
  min_clearance_ft: 1000,
  /* The airframe's own reserve: configs/airframes/*.yaml, 45 minutes, the
   * usual piston figure. Changing it here changes what CHECKS demands, not
   * what the model flies -- and the panel says so. */
  reserve_min: 45,
  max_duration_h: 14,
  ceiling_margin_ft: 1000,
};

export interface CheckInput {
  plan: MissionPlan;
  ex: Expansion;
  cost: RouteCost | null;
  env: Envelope | null;
  sim: FlightSim | null;
  snap: any;
  scenario: { mode: string; severity: number; onset_s: number } | null;
  constraints: Constraints;
  /** True when the route has changed since whatever was flown or costed. */
  stale: boolean;
}

/* NOTHING IS GREEN UNTIL SOMETHING HAS ANSWERED IT.
 *
 * Half of a pre-flight check cannot be done from the plan alone: fuel,
 * terrain, ceiling and per-leg climb all come from the route costing, which
 * takes minutes. The wrong answer to that is a green tick that means "not
 * asked". So those checks read PENDING until a costing exists, and say which
 * button produces it. */
export function buildChecks(inp: CheckInput): Check[] {
  const { ex, cost, sim, snap, scenario, constraints: c } = inp;
  const out: Check[] = [];
  const add = (q: Check) => out.push(q);

  /* ---- ROUTE, entirely from the plan ------------------------------- */
  const nwp = ex.waypoints.length;
  add({
    key: "route.valid", group: "ROUTE", label: "Route accepted", source: "plan",
    state: ex.errors.length ? "FAIL" : nwp >= 2 ? "PASS" : "FAIL",
    detail: ex.errors.length ? ex.errors[0]
      : nwp + " waypoints, departure to recovery",
  });
  add({
    key: "route.budget", group: "ROUTE", label: "Waypoint budget", source: "plan",
    state: nwp > 24 ? "FAIL" : nwp > 21 ? "CAUTION" : "PASS",
    detail: nwp + " of 24 accepted by the server"
      + (nwp > 21 ? " — little room left for another lap" : ""),
  });
  const clipped = ex.patrols.filter((p) => p.clipped);
  add({
    key: "route.patrol", group: "ROUTE", label: "Patrol geometry", source: "plan",
    state: ex.patrols.length === 0 ? "NA" : clipped.length ? "CAUTION" : "PASS",
    detail: ex.patrols.length === 0 ? "no patrol area in this sortie"
      : clipped.length
        ? clipped.length + " area(s) clipped by the waypoint limit — "
          + "less time on station than asked for"
        : ex.patrols.map((p) => p.laps + " lap" + (p.laps === 1 ? "" : "s")).join(", ")
          + ", " + Math.round(ex.on_station_min) + " min on station",
  });

  /* ---- TERRAIN, from the costing ----------------------------------- */
  const terr = cost?.terrain;
  if (!cost) {
    add({ key: "terrain", group: "TERRAIN", label: "Terrain clearance",
          state: "PENDING", source: "costing",
          detail: "not evaluated — COST IT reads the ground under every leg" });
  } else if (!terr?.available) {
    add({ key: "terrain", group: "TERRAIN", label: "Terrain clearance",
          state: "CAUTION", source: "costing",
          detail: terr?.reason || "no terrain data for this route" });
  } else {
    const worst = (terr.legs ?? []).reduce(
      (m, l) => (l.margin_ft < m.margin_ft ? l : m),
      { margin_ft: 1e9, frm: "", to: "", clears: true } as any);
    const below = (terr.legs ?? []).filter(
      (l) => l.margin_ft < c.min_clearance_ft).length;
    add({
      key: "terrain", group: "TERRAIN", label: "Terrain clearance", source: "costing",
      state: terr.clears === false ? "FAIL" : below ? "CAUTION" : "PASS",
      detail: terr.clears === false
        ? "route does not clear the ground; " + (terr.required_altitude_ft
            ? Math.round(terr.required_altitude_ft).toLocaleString() + " ft required"
            : "raise the blocked legs")
        : below
          ? below + " leg(s) inside the " + c.min_clearance_ft.toLocaleString()
            + " ft minimum — worst " + Math.round(worst.margin_ft).toLocaleString()
            + " ft on " + worst.frm + "→" + worst.to
          : "lowest margin " + Math.round(worst.margin_ft).toLocaleString()
            + " ft on " + worst.frm + "→" + worst.to,
    });
  }

  /* ---- FUEL ---------------------------------------------------------- */
  if (sim) {
    const need = (sim.fuel_used_l / Math.max(sim.duration_s / 3600, 1e-6))
                 * (c.reserve_min / 60);
    add({
      key: "fuel", group: "FUEL", label: "Fuel and reserve", source: "flight",
      state: sim.fuel_remaining_l < 0 ? "FAIL"
        : sim.fuel_remaining_l < need ? "CAUTION" : "PASS",
      detail: sim.fuel_used_l.toFixed(1) + " L used, "
        + sim.fuel_remaining_l.toFixed(1) + " L left against a "
        + c.reserve_min + " min reserve of " + need.toFixed(1) + " L",
    });
  } else if (cost) {
    const spare = cost.usable_fuel_l - cost.fuel_l;
    const need = (cost.fuel_l / Math.max(cost.hours, 1e-6)) * (c.reserve_min / 60);
    add({
      key: "fuel", group: "FUEL", label: "Fuel and reserve", source: "costing",
      state: spare < 0 ? "FAIL" : spare < need ? "CAUTION" : "PASS",
      detail: cost.fuel_l.toFixed(1) + " L of " + cost.usable_fuel_l.toFixed(0)
        + " L, leaving " + spare.toFixed(1) + " L against a " + c.reserve_min
        + " min reserve of " + need.toFixed(1) + " L",
    });
  } else {
    add({ key: "fuel", group: "FUEL", label: "Fuel and reserve", state: "PENDING",
          source: "costing",
          detail: "not evaluated — COST IT prices the route in fuel" });
  }

  /* ---- PERFORMANCE --------------------------------------------------- */
  const want = Math.max(...ex.waypoints.map((w) => w.altitude_ft), 0);
  if (sim?.ceiling_ft || cost?.ceiling_ft) {
    const ceil = sim?.ceiling_ft ?? cost?.ceiling_ft ?? 0;
    add({
      key: "perf.ceiling", group: "PERFORMANCE", label: "Ceiling today",
      source: sim ? "flight" : "costing",
      state: want > ceil ? "FAIL"
        : want > ceil - c.ceiling_margin_ft ? "CAUTION" : "PASS",
      detail: "highest planned " + want.toLocaleString() + " ft against "
        + Math.round(ceil).toLocaleString() + " ft this engine can hold today",
    });
  } else {
    add({ key: "perf.ceiling", group: "PERFORMANCE", label: "Ceiling today",
          state: "PENDING", source: "costing",
          detail: "not evaluated — COST IT computes the practical ceiling" });
  }
  if (sim) {
    const short = sim.top_of_climb_ft + 200 < sim.requested_altitude_ft;
    add({
      key: "perf.climb", group: "PERFORMANCE", label: "Climb performance",
      source: "flight", state: short ? "CAUTION" : "PASS",
      detail: short
        ? "reached " + Math.round(sim.top_of_climb_ft).toLocaleString()
          + " ft of the " + Math.round(sim.requested_altitude_ft).toLocaleString()
          + " ft planned"
        : "planned altitudes reached",
    });
  } else {
    add({ key: "perf.climb", group: "PERFORMANCE", label: "Climb performance",
          state: "PENDING", source: "flight",
          detail: "not evaluated — the flight model computes the rate of climb "
                + "from excess power" });
  }
  if (sim) {
    add({
      key: "perf.duration", group: "PERFORMANCE", label: "Sortie duration",
      source: "flight",
      state: sim.duration_s / 3600 > c.max_duration_h ? "CAUTION" : "PASS",
      detail: (sim.duration_s / 3600).toFixed(2) + " h against a "
        + c.max_duration_h + " h limit",
    });
  }

  /* ---- ENGINE, live from the twin ------------------------------------ */
  const d = snap?.display ?? {};
  const injected = Array.isArray(snap?.faults_injected) ? snap.faults_injected : [];
  add({
    key: "engine.health", group: "ENGINE", label: "Engine health", source: "twin",
    state: typeof d.chi !== "number" ? "PENDING"
      : /POOR|CRITICAL|SEVERE/i.test(d.band ?? "") ? "CAUTION" : "PASS",
    detail: typeof d.chi === "number"
      ? "χ " + d.chi.toFixed(2) + (d.band ? " · " + d.band : "")
        + (typeof d.rul_hours === "number"
           ? " · " + d.rul_hours.toFixed(1) + " h remaining life" : "")
      : "the twin has not published a health index yet",
  });
  if (cost) {
    add({
      key: "engine.life", group: "ENGINE", label: "Life consumed", source: "costing",
      state: typeof d.rul_hours === "number" && cost.life_hours > d.rul_hours
        ? "FAIL" : cost.life_ratio > 1.5 ? "CAUTION" : "PASS",
      detail: cost.life_hours.toFixed(2) + " engine-hours at "
        + cost.life_ratio.toFixed(2) + "× nominal"
        + (cost.limiting_component
           ? " · limited by " + cost.limiting_component.replace(/_/g, " ") : ""),
    });
  }
  add({
    key: "engine.injected", group: "ENGINE", label: "Live twin faults",
    source: "twin",
    state: injected.length ? "CAUTION" : "PASS",
    detail: injected.length
      ? injected.length + " fault(s) injected into the LIVE engine in the twin "
        + "lab — this sortie is flown on that degraded engine"
      : "none injected; the engine is degrading only through normal wear",
  });

  /* ---- SCENARIO ------------------------------------------------------ */
  add({
    key: "scenario", group: "SCENARIO", label: "Mission fault", source: "plan",
    state: scenario ? "CAUTION" : "NA",
    detail: scenario
      ? scenario.mode.replace(/_/g, " ").toUpperCase() + " at severity "
        + scenario.severity.toFixed(2) + ", from T+"
        + Math.round(scenario.onset_s / 60) + " min — this simulation only"
      : "none — the sortie will be flown clean",
  });

  if (inp.stale) {
    add({
      key: "stale", group: "SCENARIO", label: "Results current", source: "plan",
      state: "CAUTION",
      detail: "the route has changed since the last run; the figures on screen "
            + "belong to the previous one",
    });
  }
  return out;
}

/** The worst state in a group, for the group's own indicator. */
export function worstOf(checks: Check[]): CheckState {
  const order: CheckState[] = ["FAIL", "CAUTION", "PENDING", "PASS", "NA"];
  for (const s of order) if (checks.some((q) => q.state === s)) return s;
  return "NA";
}

export function readiness(checks: Check[]): {
  state: CheckState; pass: number; total: number; blocking: Check[];
} {
  const counted = checks.filter((q) => q.state !== "NA");
  return {
    state: worstOf(checks),
    pass: counted.filter((q) => q.state === "PASS").length,
    total: counted.length,
    blocking: checks.filter((q) => q.state === "FAIL"),
  };
}

/* ------------------------------------------------------------------ *
 * The air the sortie is planned in
 *
 * Both of these are ARITHMETIC ON AN INPUT, not a result: the operator sets an
 * ISA deviation and an altitude, and the standard atmosphere says what that
 * means. They are shown as AUTO until the route costing returns the model's
 * own per-leg OAT, which is a RESULT and replaces them.
 * ------------------------------------------------------------------ */

/** Outside air temperature at an altitude on an ISA+n day, degrees C. */
export function isaOat(altitude_ft: number, isa_deviation_c: number): number {
  /* 1.98 degC per 1,000 ft, the troposphere lapse rate the standard
   * atmosphere is defined with, from 15 degC at sea level. */
  return 15 + isa_deviation_c - 1.98 * (altitude_ft / 1000);
}

/** Density altitude at standard pressure, feet.
 *
 * Substituting the lapse rate into the usual 118.8 ft per degree of ISA
 * deviation leaves DA = altitude + 118.8 x deviation exactly, which is why no
 * temperature appears here. Dry air and standard pressure: the console has no
 * QNH to set and does not pretend to. The engine model accounts for humidity
 * itself, separately, and this figure does not.
 */
export function densityAltitude(altitude_ft: number,
                                isa_deviation_c: number): number {
  return altitude_ft + 118.8 * isa_deviation_c;
}

/* ------------------------------------------------------------------ *
 * Group state, for the four status tiles
 * ------------------------------------------------------------------ */

export function groupState(checks: Check[], group: Check["group"]): CheckState {
  const rows = checks.filter((q) => q.group === group);
  return rows.length ? worstOf(rows) : "PENDING";
}

/** The single worst check in a group, so a tile can say WHY in four words. */
export function groupLead(checks: Check[],
                          group: Check["group"]): Check | null {
  const rows = checks.filter((q) => q.group === group);
  if (!rows.length) return null;
  const order: CheckState[] = ["FAIL", "CAUTION", "PENDING", "PASS", "NA"];
  for (const s of order) {
    const hit = rows.find((q) => q.state === s);
    if (hit) return hit;
  }
  return rows[0];
}

/* ------------------------------------------------------------------ *
 * Where the aircraft is, for the monitor
 * ------------------------------------------------------------------ */

export interface FlownLeg {
  /** The leg name the flight model reported, usually "FROM→TO". */
  name: string;
  /** The waypoint being flown TO. */
  to: string;
  t0: number;
  /** The second the leg ends, and the place it ends at. */
  t1: number;
  lat: number;
  lon: number;
}

/** The legs of a flown sortie, with the moment and the place each one ends.
 *
 * Read off the samples rather than matched against the plan: a patrol circuit
 * repeats waypoint names, and the model's own leg names are what the monitor
 * and the transport should be quoting back. */
export function flownLegs(samples: { t_s: number; leg: string;
                                     lat_deg: number; lon_deg: number }[]):
    FlownLeg[] {
  const out: FlownLeg[] = [];
  for (const s of samples) {
    const last = out[out.length - 1];
    if (last && last.name === s.leg) {
      last.t1 = s.t_s; last.lat = s.lat_deg; last.lon = s.lon_deg;
    } else {
      out.push({ name: s.leg, to: legTo(s.leg), t0: last ? last.t1 : 0,
                 t1: s.t_s, lat: s.lat_deg, lon: s.lon_deg });
    }
  }
  return out;
}

/** "VIJO→WP01" names the leg; the half after the arrow is where it is going. */
export function legTo(leg: string): string {
  const to = (leg || "").split(/→|->/).pop()?.trim();
  return to && to !== leg ? to : (leg || "—");
}
