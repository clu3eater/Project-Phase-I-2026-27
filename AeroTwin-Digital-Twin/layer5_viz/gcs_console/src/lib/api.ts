/* Live data from the twin.
 *
 * One WebSocket carrying complete snapshots, not deltas. A console open for an
 * hour and one that just connected therefore render identically, and a dropped
 * frame costs one refresh of latency rather than permanent divergence.
 */

import { useEffect, useRef, useState } from "react";

/* ------------------------------------------------------------------------ *
 * Session.
 *
 * The token lives in memory, not localStorage. A token in localStorage is
 * readable by any script that reaches the page and survives the operator
 * walking away from the console, which is precisely the two things a
 * 15-minute access token exists to prevent. Closing the tab ends the session,
 * which is the correct behaviour for a crew station.
 * ------------------------------------------------------------------------ */

let TOKEN: string | null = null;
let SESSION: { role: string; scopes: string[]; subject: string } | null = null;

export function session() {
  return SESSION;
}

/** Whether the active role carries a scope. Used to HIDE controls (PRD Part 4
 *  s10a prefers hiding to disabling), never to authorise: the API enforces
 *  that server-side regardless of what this returns (s10c). */
export function can(scope: string): boolean {
  if (!SESSION) return false;
  return SESSION.scopes.includes("*") || SESSION.scopes.includes(scope);
}

let REFRESH: string | null = null;
let REFRESH_TIMER: number | undefined;

/* HMI-03: the access token lives 15 minutes and was never renewed, so the
 * console's first reconnect after that was refused for good. It is renewed a
 * minute before expiry with the refresh token issued at sign-in. */
function scheduleRefresh(expiresInS: number | undefined) {
  if (REFRESH_TIMER) window.clearTimeout(REFRESH_TIMER);
  if (!REFRESH || !expiresInS) return;
  const ms = Math.max(30, expiresInS - 60) * 1000;
  REFRESH_TIMER = window.setTimeout(async () => {
    try {
      const r = await fetch("/api/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: REFRESH }),
      });
      if (!r.ok) return;
      const j = await r.json();
      TOKEN = j.access_token;
      scheduleRefresh(j.expires_in_s);
    } catch {
      /* The link watchdog annunciates a lost link; a later reconnect retries. */
    }
  }, ms);
}

export async function login(username: string, password: string) {
  const r = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  // SEC-02: a first-run password must be replaced before the account is used.
  if (r.status === 403) throw new Error("password change required");
  if (!r.ok) throw new Error("invalid credentials");
  const j = await r.json();
  TOKEN = j.access_token;
  REFRESH = j.refresh_token ?? null;
  SESSION = { role: j.role, scopes: j.scopes, subject: username };
  scheduleRefresh(j.expires_in_s);
  return SESSION;
}

/** Replace a password with the current one as proof. Throws the server's
 *  reason (a policy rule, or "invalid credentials") on refusal. */
export async function changePassword(
  username: string, oldPassword: string, newPassword: string,
) {
  const r = await fetch("/api/auth/change_password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username, old_password: oldPassword, new_password: newPassword,
    }),
  });
  if (!r.ok) {
    let msg = "Password not changed.";
    try {
      const j = await r.json();
      if (typeof j.detail === "string") msg = j.detail;
    } catch {
      /* keep the generic message */
    }
    throw new Error(msg);
  }
}

export type DemoAccount = { label: string; username: string; password: string };

/** The accounts the demonstration copy lists on its login screen. Empty on a
 *  real station, and empty if the server cannot be reached. */
export async function demoAccounts(): Promise<DemoAccount[]> {
  try {
    const r = await fetch("/api/demo");
    if (!r.ok) return [];
    const j = await r.json();
    return j.demo && Array.isArray(j.accounts) ? j.accounts : [];
  } catch {
    return [];
  }
}

export function logout() {
  TOKEN = null;
  REFRESH = null;
  if (REFRESH_TIMER) window.clearTimeout(REFRESH_TIMER);
  SESSION = null;
}

export function authHeaders(): Record<string, string> {
  return TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};
}

/** fetch with the bearer token attached. */
export async function api(path: string, init: RequestInit = {}) {
  return fetch(path, {
    ...init,
    headers: { ...(init.headers ?? {}), ...authHeaders() },
  });
}

export type ValueState = "VALID" | "STALE" | "INVALID" | "MISSING" | "SUSPECT";

export interface Measurement {
  value: number | null;
  state: ValueState;
  age_s: number | null;
  reason: string;
}

export interface TwinCompare {
  available: boolean;
  measured?: number;
  expected?: number;
  deviation?: number;
  unit?: string;
  graded?: boolean;
  level?: "normal" | "degraded" | "fault" | null;
  offset_known?: boolean;
}

export interface Snapshot {
  t_s: number;
  wall_utc: string;
  twin: any;
  mission: any;
  explanation: any;
  maintenance: any;
  /* Battery state of health. Frequently NOT reportable, and that is the
     interesting part: pack resistance is only visible while the battery is
     actually supplying current, so between discharge events the console shows
     the last measurement WITH ITS AGE rather than a fresh-looking number. */
  battery: {
    soh: number | null;
    internal_resistance_mohm: number | null;
    open_circuit_v: number | null;
    samples: number;
    current_span_a: number;
    hours_since_measured: number | null;
    observable_now: boolean;
    reason: string;
    confidence: number;
  };
  /* Engine efficiency and its deterioration against the as-new twin.
     Problem statement section F: "Engine efficiency trends". */
  efficiency: {
    bsfc_g_per_kwh: number | null;
    bsfc_as_new_g_per_kwh: number | null;
    bsfc_deterioration_pct: number | null;
    thermal_efficiency: number | null;
    thermal_as_new: number | null;
    volumetric_efficiency: number | null;
    excess_fuel_lph: number | null;
    reason: string;
  };
  /* The OPERATOR's view of the slow quantities -- smoothed, quantised and
     held still enough to read. The raw sections above are what the model
     computed and are what the engineer's screens use; this is what goes in
     front of somebody flying an aircraft. See docs/WHO_READS_THIS_SCREEN.md. */
  display: {
    chi: number | null;
    chi_direction: string;
    rul_hours: number | null;
    bsfc_deterioration_pct: number | null;
    efficiency_direction: string;
    mission_success_pct: number | null;
    fusion_score: number | null;
    band: string;
    instruction: string;
    /* What the health figures ARE: judged now ("live"), carried from the
     * last warm, loaded running ("held", with its age), or not yet judged
     * since the station started ("assessing"). A cold or idling engine is not
     * at the condition the indices measure, so they are not taken there. */
    assessment?: { state: "live" | "held" | "assessing"; age_s: number | null;
                   reason: string };
    /* The oil-pressure minimum that applies AT THE CURRENT ENGINE SPEED.
     * OM s2.1 sets 2.0 bar above 3500 rpm and 0.8 bar below it, so there is no
     * single number to draw. The twin publishes the one in force rather than
     * the console re-deriving the condition -- deriving it here is how the
     * tile came to show a legal 22.9 psi at 3285 rpm in red, beside an alert
     * panel correctly reporting nothing out of limits. */
    oil_pressure_min_psi?: number;
    /* Each reading against the twin: what the as-new engine at this
     * operating point, plus this engine's build offset, would read now.
     * Graded ("normal" / "degraded" / "fault") only while the engine is warm,
     * loaded and steady (thresholds.yaml twin_compare). */
    twin?: Record<string, TwinCompare>;
    margins: {
      name: string; value: number; limit: number;
      margin: number; unit: string; exceeded: boolean;
    }[];
  };
  health: Record<string, number | string>;
  rul: {
    hours: number | null;
    lower: number | null;
    upper: number | null;
    confidence: number;
    reason: string;
    reportable: boolean;
    rate_per_hour: number | null;
    /* Which estimator produced `hours`: "lstm", "physics_fallback" or "none".
     * Needed on screen because `confidence` describes the PHYSICS estimator,
     * so a panel quoting it has to say whether that is the one that answered. */
    source?: "lstm" | "physics_fallback" | "none";
  };
  fusion: {
    score: number;
    level: number;
    level_name: string;
    predictive: boolean;
    rule_confirmed: boolean;
    reason: string;
    s_rule: number;
    s_statistical: number;
    s_deep: number;
    statistical_source?: string;
    deep_source?: string;
    rule_based_fallback: boolean;
  };
  trend: Record<string, number | null>;
  pipeline: Record<string, any>;
  history: Record<string, (number | null)[]>;
  faults_injected: { mode: string; severity: number; onset_hours: number }[];
  /* The sortie: "running" until the engine is shut down at the end of it,
   * then "complete". A completed flight has already been written to the
   * flight history when `recorded` is true. */
  sortie?: { state: "running" | "complete"; started_t_s: number;
             ended_t_s: number | null; flight_time_s: number; recorded: boolean };
  flight_record?: any;
}

export type LinkState = "OK" | "CONNECTING" | "STALE" | "LOST";

/* The snapshot fields the server withholds from a partial frame. Mirrors
 * twin_api._SERIES_KEYS; test_stream_tiering.py pins the server's half. */
const SERIES_KEYS = ["history", "flight_series"] as const;

/* PRD Part 4 s7.3, with configs/thresholds.yaml link_degraded_after_s (2.0)
 * and link_lost_after_s (5.0). A socket can stay open while nothing arrives,
 * so the AGE of the newest snapshot decides the link state, not the socket
 * alone (HMI-03): an open but silent link used to read LINK OK over frozen
 * numbers for as long as it stayed open. */
const LINK_STALE_AFTER_MS = 2000;
const LINK_LOST_AFTER_MS = 5000;

/* The chart series ride the slower tier, so their age is NOT the link's age.
 *
 * The socket can keep delivering partial frames -- the readings -- while the
 * full frames carrying `history` and `flight_series` stop arriving. The link
 * would read OK, because something is arriving, and the charts would sit there
 * showing the last thing they were sent, with nothing on screen saying so.
 * That is substituting the last good value for a missing one, which section
 * 7.2 forbids and which the Readout component already refuses to do.
 *
 * So a merged series is carried forward only while its own frame is recent.
 * Past this, the series are dropped and the charts go empty -- the correct
 * reading of "the twin has stopped sending me these". Three times the 2 s full
 * cadence, so a single dropped frame does not blank a chart. */
const SERIES_STALE_AFTER_MS = 6000;

/** Subscribe to the live snapshot stream. */
export function useLiveState(): {
  snap: Snapshot | null; link: LinkState; lastUpdate: number;
} {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [link, setLink] = useState<LinkState>("CONNECTING");
  const ws = useRef<WebSocket | null>(null);
  const lastMsg = useRef<number>(0);
  // When a FULL frame last arrived, which is not the same as when anything did.
  const lastFull = useRef<number>(0);

  useEffect(() => {
    let closed = false;
    let retry: number | undefined;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      // A WebSocket handshake cannot carry an Authorization header -- the browser
      // API has no way to set one -- so the token goes in the query string and
      // the server verifies it there. Same check, different carrier.
      const q = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : "";
      const sock = new WebSocket(`${proto}://${location.host}/ws/state${q}`);
      ws.current = sock;
      sock.onopen = () => setLink("OK");
      sock.onmessage = (e) => {
        lastMsg.current = Date.now();
        const msg = JSON.parse(e.data);
        // A PARTIAL frame carries the readings without the chart series, so the
        // gauges can run at 4 Hz without resending 61 KB of charts to do it.
        // Merge those over what we hold; a FULL frame always replaces.
        //
        // Replacing on a full frame is the point, not an optimisation. An
        // absent field there means the twin is DECLINING to publish it -- a
        // remaining-life figure with no calibrated interval, a fault
        // probability with no network behind it. Merging every frame would
        // leave the last value it did publish on screen, which is the one
        // outcome this system is built not to do.
        if (!msg.partial) lastFull.current = Date.now();
        setSnap((prev) => {
          if (!msg.partial || !prev) return msg;
          const merged: any = { ...prev, ...msg };
          // Carry the series forward only while the frame that brought them is
          // recent. Otherwise drop them, so the charts read empty rather than
          // showing an age they do not admit to.
          if (Date.now() - lastFull.current > SERIES_STALE_AFTER_MS) {
            for (const k of SERIES_KEYS) delete merged[k];
          }
          return merged;
        });
        setLink("OK");
      };
      sock.onclose = () => {
        if (closed) return;
        // The link state is shown to the operator rather than hidden behind a
        // silent retry: PRD Part 4 section 7.3 requires the console to say
        // when what it is showing is no longer live.
        setLink("LOST");
        retry = window.setTimeout(connect, 1500);
      };
      sock.onerror = () => sock.close();
    };
    connect();

    // Watchdog on the age of the newest snapshot. Past the lost threshold an
    // open socket is closed deliberately, so the normal retry path runs.
    const watchdog = window.setInterval(() => {
      if (!lastMsg.current) return;
      const age = Date.now() - lastMsg.current;
      if (age > LINK_LOST_AFTER_MS) {
        setLink("LOST");
        if (ws.current && ws.current.readyState === WebSocket.OPEN) ws.current.close();
      } else if (age > LINK_STALE_AFTER_MS) {
        setLink("STALE");
      }
    }, 500);

    return () => {
      closed = true;
      window.clearInterval(watchdog);
      if (retry) window.clearTimeout(retry);
      ws.current?.close();
    };
  }, []);

  return { snap, link, lastUpdate: lastMsg.current };
}

/** Static engine data: identity, certified limits, alert thresholds. */
export function useEngineInfo(engineKey?: string | null) {
  const [info, setInfo] = useState<any>(null);
  useEffect(() => {
    if (!engineKey) return;
    let current = true;
    setInfo(null);
    api("/api/engine")
      .then((r) => {
        if (!r.ok) throw new Error("engine limits unavailable");
        return r.json();
      })
      .then((value) => { if (current) setInfo(value); })
      .catch(() => { if (current) setInfo(null); });
    return () => { current = false; };
  }, [engineKey]);
  return info;
}

export interface RouteWaypoint {
  name: string; lat_deg: number; lon_deg: number; altitude_ft: number;
}

export interface RouteLeg {
  frm: string; to: string; distance_km: number; altitude_ft: number;
  oat_c: number; hours: number; fuel_l: number; life_hours: number;
  mean_power_kw: number; mean_cht_c: number;
  wastegate_saturated_min: number; cooling_flap_saturated_min: number;
}

export interface TerrainLeg {
  frm: string; to: string; planned_ft: number; max_terrain_ft: number;
  min_safe_ft: number; clears: boolean; margin_ft: number;
  highest_at: [number, number] | null; samples: number[];
}

export interface RouteTerrain {
  available: boolean; reason?: string;
  legs?: TerrainLeg[]; clears?: boolean;
  required_altitude_ft?: number; clearance_ft?: number;
  blocked_legs?: string[]; highest_terrain_ft?: number; source?: string;
}

export interface RouteCost {
  legs: RouteLeg[];
  /** The ground under the route, and the altitude it demands. */
  terrain?: RouteTerrain;
  /** The altitude this engine can still hold cruise power at, today. */
  ceiling_ft?: number;
  distance_km: number; hours: number; fuel_l: number; usable_fuel_l: number;
  life_hours: number; life_ratio: number;
  limiting_component: string; limiting_margin: number;
  wastegate_saturated_min: number; cooling_flap_saturated_min: number;
  feasible: boolean; reasons: string[]; assumptions: Record<string, any>;
}

/** What a proposed sortie costs the ENGINE, before it is flown.
 *
 * TENS OF SECONDS, not milliseconds. The server flies the route through the
 * physics minute by minute and then flies a reference sortie to price the wear
 * against. Callers must show that it is working rather than appearing to hang;
 * the alternative the server rejected -- scaling a short reference -- moved the
 * life figure by a third.
 */
export async function assessRoute(
  waypoints: RouteWaypoint[],
  opts: { true_airspeed_kmh?: number; isa_deviation_c?: number;
          /* THE SAME DAY THE SORTIE WOULD BE FLOWN ON. Without this the
             costing is pinned at 30 % while /api/mission/flight honours what
             it is given, so the planner could set a humidity that moved the
             flown sortie and not the figure printed beside it. */
          humidity_pct?: number;
          usable_fuel_l?: number } = {},
): Promise<RouteCost> {
  const r = await api("/api/mission/route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ waypoints, ...opts }),
  });
  if (!r.ok) throw new Error((await r.text()).slice(0, 200));
  return r.json();
}

export interface Envelope {
  radius_km: number; radius_new_km: number;
  endurance_h: number; endurance_new_h: number;
  fuel_flow_lph: number; fuel_flow_new_lph: number;
  lost_km: number; lost_pct: number; altitude_ft: number;
  holds_cruise: boolean; required_kw: number;
  assumptions: Record<string, any>; basis: string;
}

/** How far THIS engine can still go, against how far it could when new.
 *
 * The worn engine is the twin's own current degradation, not a scenario. Like
 * assessRoute this flies the physics and takes tens of seconds.
 */
export async function fetchEnvelope(
  opts: { altitude_ft?: number; isa_deviation_c?: number; usable_fuel_l?: number } = {},
): Promise<Envelope> {
  const q = new URLSearchParams(
    Object.entries(opts).map(([k, v]) => [k, String(v)]));
  const r = await api(`/api/mission/envelope?${q}`);
  if (!r.ok) throw new Error((await r.text()).slice(0, 200));
  return r.json();
}

/* ---- flying the route, rather than costing it ---------------------------
 *
 * assessRoute answers the planner's question in TOTALS -- litres, engine-hours,
 * the limiting component. simulateFlight answers the operator's, which is
 * WHERE: the track take-off to landing, and an event at every moment a
 * certified limit is crossed, with the place it was crossed at.
 */

/** One instant of the flight: where, how high, and what the engine is doing. */
export interface FlightSample {
  t_s: number; lat_deg: number; lon_deg: number; altitude_ft: number;
  phase: string; leg: string;
  throttle_pct: number; power_kw: number; rpm: number;
  cht_c: number; egt_c: number; coolant_c: number;
  oil_temp_c: number; oil_press_psi: number; manifold_bar: number;
  fuel_flow_lph: number; fuel_remaining_l: number;
  oat_c: number; terrain_ft: number; clearance_ft: number;
  wastegate_frac: number; cooling_flap_frac: number; vibration_rms: number;
}

/** Something that happened, at the moment and the place it happened. */
export interface FlightEvent {
  t_s: number; phase: string;
  severity: "ADVISORY" | "CAUTION" | "WARNING";
  code: string; message: string;
  lat_deg: number; lon_deg: number; altitude_ft: number;
  value: number | null; limit: number | null; unit: string;
}

export interface FlightSim {
  samples: FlightSample[];
  events: FlightEvent[];
  verdict: "GO" | "GO_WITH_LIMITS" | "NO_GO";
  reasons: string[];
  duration_s: number; distance_km: number;
  fuel_used_l: number; fuel_remaining_l: number; reserve_l: number;
  top_of_climb_ft: number; requested_altitude_ft: number; ceiling_ft: number;
  peak: Record<string, number>;
  conditions: Record<string, number>;
  assumptions: Record<string, any>;
  terminated_at_s: number | null;
  termination: string;
  /** "live" -- the engine now, worn as it is -- or "as-new". */
  engine_flown: string;
  /** The fault this sortie was flown with, echoed by the server. */
  scenario?: MissionScenario | null;
}

/** A FAULT THAT BELONGS TO ONE SIMULATED SORTIE.
 *
 * Not /api/faults/inject. That one degrades the engine that is actually
 * running -- its health index, its remaining life and every alert on every
 * page -- to answer a hypothetical, and it stays degraded until it is
 * cleared. This is handed to the simulation, applied to a degradation engine
 * that simulation owns, and thrown away with it.
 *
 * `onset_s` is seconds INTO THE SORTIE, which is what makes injection during
 * playback meaningful: stop at T+01:12:30, ask for a misfire from there, and
 * the sortie is re-flown with the fault appearing at that second.
 *
 * SENSOR DRIFT IS NOT OFFERED HERE. A drift is expressed in the instrument
 * layer of the twin's own simulator; the flight model has no instruments to
 * drift, so the server refuses it rather than returning a sortie identical to
 * the baseline. It belongs in the twin lab.
 */
export interface MissionScenario {
  mode: string;
  severity: number;
  ramp_hours: number;
  onset_s: number;
  channel?: string | null;
}

/** Fly the sortie take-off to landing, on the engine that is flying now.
 *
 * TENS OF SECONDS, like assessRoute and for the same reason: it steps the
 * mean-value model through the whole sortie rather than looking anything up.
 */
export async function simulateFlight(
  waypoints: RouteWaypoint[],
  opts: { true_airspeed_kmh?: number; isa_deviation_c?: number;
          humidity_pct?: number; usable_fuel_l?: number;
          use_live_engine?: boolean; start_engine?: boolean;
          scenario?: MissionScenario | null } = {},
): Promise<FlightSim> {
  const r = await api("/api/mission/flight", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ waypoints, ...opts }),
  });
  if (!r.ok) throw new Error((await r.text()).slice(0, 200));
  return r.json();
}

export async function injectFault(mode: string, severity: number) {
  return api("/api/faults/inject", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, severity, ramp_hours: 0.02 }),
  }).then((r) => r.json());
}

export async function clearFaults() {
  return api("/api/faults/clear", { method: "POST" }).then((r) => r.json());
}

/** Record maintenance that has been carried out. The twin applies it on its
 *  next tick. `repaired` only matters for the two inspections (A5, A6). */
export async function recordMaintenance(actionId: string, repaired?: boolean) {
  return api("/api/maintenance/performed", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action_id: actionId, repaired }),
  }).then((r) => r.json());
}


export async function acknowledge() {
  return api("/api/alerts/acknowledge", { method: "POST" }).then((r) => r.json());
}

/** The instrument and FADEC-lane failures the running engine can be given. */
export async function fetchSensorFailureOptions(): Promise<{
  channels: string[]; modes: string[]; lane_items: { item: string; lane: string }[];
}> {
  return api("/api/faults/sensors").then((r) => r.json());
}

export async function injectSensorFailure(channel: string, mode: string) {
  return api("/api/faults/sensor", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ channel, mode }),
  }).then((r) => r.json());
}

export async function injectLaneFailure(item: string, lane: string) {
  return api("/api/faults/lane", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item, lane }),
  }).then((r) => r.json());
}

/** The sudden failures: the engine stops making power (or soon will). */
export async function fetchFailures(): Promise<{ name: string; label: string; description: string }[]> {
  return api("/api/faults/failures").then((r) => (r.ok ? r.json() : []));
}

export async function injectFailure(name: string) {
  return api("/api/faults/failure", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  }).then((r) => r.json());
}

export async function fetchFaults() {
  return api("/api/faults").then((r) => r.json());
}

export async function fetchReport() {
  return api("/api/report").then((r) => r.json());
}

/* --- Engine test rig: the second of the three deployment contexts --------- */

export async function fetchRigSchedules() {
  return api("/api/testrig/schedules").then((r) => r.json());
}

export async function runRig(body: {
  schedule: string;
  cell_temperature_c?: number;
  cell_cooling_kmh?: number;
  use_live_engine?: boolean;
}) {
  return api("/api/testrig/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(async (r) => {
    if (!r.ok) {
      const e = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(e.detail ?? "test rig run failed");
    }
    return r.json();
  });
}

/* ------------------------------------------------------------------------ */

/** Colour token for an alert level (PRD Part 4 section 3.1). */
export function levelColour(level: number): string {
  if (level >= 5) return "var(--alert-warn)";
  if (level >= 4) return "var(--alert-caut-hi)";
  if (level >= 3) return "var(--alert-caut)";
  if (level >= 2) return "var(--alert-advis)";
  return "var(--state-normal)";
}

/** Short legend for an alert level. */
/** The same five levels as TEXT.
 *
 * `levelColour` returns the CERTIFIED hues, which is right for the status bar
 * and the icon and wrong for a legend: s3.4a wants 7:1 on alert legends and
 * saturated aviation red reaches 4.93:1 on a night panel. See tokens.css --
 * the saturated token is a lamp, this one is a typeface. Missed by the first
 * contrast sweep because the colour is returned from a function rather than
 * written at the use site.
 */
export function levelInk(level: number): string {
  if (level >= 5) return "var(--alert-warn-ink)";
  if (level >= 4) return "var(--alert-caut-hi)";
  if (level >= 3) return "var(--alert-caut)";
  if (level >= 2) return "var(--alert-advis)";
  return "var(--state-normal)";
}

export function levelName(level: number): string {
  return ["", "NORMAL", "ADVISORY", "CAUTION", "CAUTION", "WARNING"][level] ?? "NORMAL";
}

/**
 * Format a measurement for display.
 *
 * A value that failed validation is NEVER rendered as a number. PRD Part 4
 * section 7.2 is explicit: remove, never substitute. Showing the last good
 * reading, or a zero, is how an operator ends up flying on a dead sensor.
 */
export function fmt(m: Measurement | undefined, digits = 1): string {
  if (!m || m.value === null) return "———";
  if (m.state === "INVALID" || m.state === "MISSING") return "———";
  return m.value.toFixed(digits);
}

export function isDegraded(m: Measurement | undefined): boolean {
  return !m || m.state === "STALE" || m.state === "SUSPECT";
}

export function isMissing(m: Measurement | undefined): boolean {
  return !m || m.value === null || m.state === "INVALID" || m.state === "MISSING";
}
