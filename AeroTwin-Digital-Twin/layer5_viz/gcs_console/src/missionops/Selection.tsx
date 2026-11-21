/* THE CONTEXTUAL INSPECTOR — what the thing on the map actually is.
 *
 * Selecting a waypoint, a leg or an event turns the dock into that object's
 * inspector: everything known about it, in one place, with the controls that
 * belong to it and no others. Clearing the selection puts the mission summary
 * back. That is the whole interaction, and it is the difference between a map
 * with a form beside it and a workspace with an inspector.
 *
 * WHY THE ANCHORED CARD IS GONE FROM THIS PAGE
 * --------------------------------------------
 * The old editor opened as a card pinned to the point on the map. It is a good
 * card -- MISSION SIMULATOR still uses it -- but with an inspector in the dock
 * there would be two editors for one object, in two places, disagreeing about
 * which is the one to use. Everything the card could do is here, and the
 * navigation figures the card had no room for are here too.
 *
 * Nothing in this file computes a figure of its own. The legs come from
 * mission.ts, the terrain and fuel from the route costing, the events from the
 * flown sortie. A cell whose source has not run says which button runs it.
 */

import type { FlightSim } from "../lib/api";
import { BASE_BY_ID } from "../data/airbases";
import { Playback } from "../mission/clock";
import { fmtClock, fmtMin, type Expansion, type MissionPlan,
         type PlanPoint } from "../mission/plan";
import { Chip, Field, ghostButton, inputStyle, numStyle } from "../mission/ui";
import { zuluAfter, type MissionIdentity, type Segment } from "./mission";

export type Sel =
  | { kind: "point"; id: string }
  | { kind: "leg"; i: number }
  | { kind: "event"; i: number };

/* ------------------------------------------------------------------ *
 * The shell: a header that says what is selected and how to get back
 * ------------------------------------------------------------------ */

export function Inspector(props: {
  sel: Sel;
  plan: MissionPlan;
  expansion: Expansion;
  segments: Segment[];
  identity: MissionIdentity;
  sim: FlightSim | null;
  pb: Playback;
  locked: boolean;
  onSelect: (s: Sel | null) => void;
  onPatch: (id: string, q: Partial<PlanPoint>) => void;
  onReorder: (i: number, d: number) => void;
  onRemove: (id: string) => void;
}) {
  const body = (() => {
    if (props.sel.kind === "point") {
      const id = props.sel.id;
      const i = props.plan.points.findIndex((q) => q.id === id);
      const q = props.plan.points[i];
      if (!q) return null;
      return <PointBody {...props} point={q} index={i} />;
    }
    if (props.sel.kind === "leg") {
      const s = props.segments[props.sel.i];
      if (!s) return null;
      return <LegBody segment={s} identity={props.identity} />;
    }
    const ev = props.sim?.events[props.sel.i];
    if (!ev) return null;
    return <EventBody ev={ev} pb={props.pb} />;
  })();

  if (!body) return null;

  return (
    <div className="mo-inspect"
         style={{ flex: 1, minHeight: 0, display: "flex",
                  flexDirection: "column" }}>
      <button onClick={() => props.onSelect(null)} className="mo-tab"
              style={{ display: "flex", alignItems: "center", gap: 8,
                       flex: "0 0 auto", minHeight: 34, width: "100%",
                       padding: "0 var(--space-4)", cursor: "pointer",
                       background: "transparent", border: "none",
                       borderBottom: "1px solid var(--line)", textAlign: "left",
                       color: "var(--ink-mute)", fontFamily: "var(--font-ui)",
                       fontSize: "var(--size-label)", letterSpacing: "0.08em" }}>
        <span aria-hidden="true">‹</span> MISSION
      </button>
      <div className="panel-body"
           style={{ flex: 1, minHeight: 0, overflowY: "auto",
                    padding: "var(--space-3) var(--space-4) var(--space-4)" }}>
        {body}
      </div>
    </div>
  );
}

function Head(props: { hue: string; kind: string; name: string;
                       right?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 9,
                  marginBottom: "var(--space-3)", minWidth: 0 }}>
      <span style={{ width: 4, alignSelf: "stretch", flex: "0 0 auto",
                     background: props.hue, borderRadius: 2 }} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                      letterSpacing: "0.1em" }}>
          {props.kind.toUpperCase()}
        </div>
        <div style={{ fontSize: 19, fontWeight: 700, whiteSpace: "nowrap",
                      overflow: "hidden", textOverflow: "ellipsis" }}>
          {props.name}
        </div>
      </div>
      {props.right}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * A point: a field, a turning point, or an area
 * ------------------------------------------------------------------ */

function PointBody(props: {
  point: PlanPoint;
  index: number;
  plan: MissionPlan;
  expansion: Expansion;
  segments: Segment[];
  identity: MissionIdentity;
  locked: boolean;
  onPatch: (id: string, q: Partial<PlanPoint>) => void;
  onReorder: (i: number, d: number) => void;
  onRemove: (id: string) => void;
}) {
  const q = props.point;
  const isBase = q.kind === "DEPARTURE" || q.kind === "RECOVERY";
  const hue = isBase ? "var(--state-normal)"
    : q.kind === "PATROL" ? "var(--alert-caut)" : "var(--alert-advis)";
  const pa = props.expansion.patrols.find((x) => x.point_id === q.id);
  const base = q.base_id ? BASE_BY_ID[q.base_id] : null;

  /* WHERE THIS POINT SITS IN THE FLOWN ORDER. The expanded list is what the
   * server is sent and what the legs were computed over, so the join is by
   * name in that list -- a patrol's laps are separate waypoints with their own
   * names and are not looked for here. */
  const wi = props.expansion.waypoints.findIndex((w) => w.name === q.name);
  const inbound = wi > 0 ? props.segments[wi - 1] : null;
  const outbound = wi >= 0 ? props.segments[wi] : null;
  const eta = inbound
    ? zuluAfter(props.identity.launch_utc, inbound.cumulative_min) : null;

  return (
    <>
      <Head hue={hue}
            kind={isBase ? q.kind.toLowerCase() + " field"
              : q.kind === "PATROL" ? "patrol area" : "waypoint"}
            name={q.name}
            right={<span style={{ fontFamily: "var(--font-num)",
                                  fontSize: "var(--size-label)",
                                  color: "var(--ink-mute)" }}>
              {props.index + 1} / {props.plan.points.length}
            </span>} />

      {/* ---- what the geometry says about it ------------------------- */}
      <div style={{ display: "grid", gap: "4px 12px", marginBottom: "var(--space-4)",
                    gridTemplateColumns: "repeat(auto-fit, minmax(112px, 1fr))" }}>
        <Cell k="altitude"
              v={Math.round(q.altitude_ft).toLocaleString() + " ft"}
              note={isBase ? "field elevation" : "MSL"} />
        {inbound && (
          <Cell k="course in" v={Math.round(inbound.course_deg) + "°"} />
        )}
        {outbound && (
          <Cell k="course out" v={Math.round(outbound.course_deg) + "°"} />
        )}
        {inbound && (
          <Cell k="leg in" v={inbound.distance_km.toFixed(0) + " km"} />
        )}
        {inbound && (
          <Cell k="cumulative" v={inbound.cumulative_km.toFixed(0) + " km"} />
        )}
        {inbound && (
          <Cell k={eta && eta !== "—" ? "eta" : "t+"}
                v={eta && eta !== "—" ? eta : fmtMin(inbound.cumulative_min)} />
        )}
        {inbound?.terrain && (
          <Cell k="terrain below"
                v={Math.round(inbound.terrain.max_terrain_ft).toLocaleString() + " ft"} />
        )}
        {inbound?.terrain && (
          <Cell k="clearance"
                v={Math.round(inbound.terrain.margin_ft).toLocaleString() + " ft"}
                hue={inbound.terrain.clears ? undefined : "var(--alert-warn)"} />
        )}
      </div>

      {/* ---- what can be changed about it ---------------------------- */}
      <fieldset disabled={props.locked}
                className={props.locked ? "ms-locked" : undefined}
                style={{ border: "none", margin: 0, padding: 0, minWidth: 0,
                         display: "grid", gap: "var(--space-3)" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 108px",
                      gap: "var(--space-2)" }}>
          <Field label="Name">
            <input value={q.name} style={inputStyle} maxLength={24}
                   aria-label="waypoint name"
                   onChange={(e) => props.onPatch(q.id, { name: e.target.value })} />
          </Field>
          <Field label="Altitude">
            <input type="number" value={Math.round(q.altitude_ft)} style={numStyle}
                   min={0} max={30000} step={500} aria-label="waypoint altitude"
                   onChange={(e) => props.onPatch(q.id, {
                     altitude_ft: Math.max(0, Math.min(30000,
                       Number(e.target.value))) })} />
          </Field>
        </div>

        {q.kind === "PATROL" && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                          gap: "var(--space-2)" }}>
              <Field label="On station">
                <input type="number" value={q.loiter_min ?? 60} style={numStyle}
                       min={0} max={600} step={5} aria-label="time on station"
                       onChange={(e) => props.onPatch(q.id, {
                         loiter_min: Math.max(0, Math.min(600,
                           Number(e.target.value))) })} />
              </Field>
              <Field label="Radius km">
                <input type="number" value={q.radius_km ?? 15} style={numStyle}
                       min={2} max={90} step={1} aria-label="patrol radius"
                       onChange={(e) => props.onPatch(q.id, {
                         radius_km: Math.max(2, Math.min(90,
                           Number(e.target.value))) })} />
              </Field>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              {(["ORBIT", "RACETRACK"] as const).map((x) => (
                <Chip key={x} on={(q.pattern ?? "ORBIT") === x} tone="caut"
                      onClick={() => props.onPatch(q.id, { pattern: x })}>{x}</Chip>
              ))}
            </div>
            {pa && (
              <div style={{ fontSize: "var(--size-label)", lineHeight: 1.5,
                            color: pa.clipped ? "var(--alert-caut)"
                                              : "var(--ink-mute)",
                            borderLeft: "2px solid " + (pa.clipped
                              ? "var(--alert-caut)" : "var(--line)"),
                            paddingLeft: 8 }}>
                {pa.laps} lap{pa.laps === 1 ? "" : "s"} of {pa.lap_km.toFixed(1)} km
                {" "}as {pa.laps * pa.ring.length} waypoints —{" "}
                <b>{fmtMin(pa.achieved_min)}</b> on station.
              </div>
            )}
          </>
        )}

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button style={ghostButton} disabled={props.index === 0}
                  aria-label="earlier in the route"
                  onClick={() => props.onReorder(props.index, -1)}>↑</button>
          <button style={ghostButton}
                  disabled={props.index === props.plan.points.length - 1}
                  aria-label="later in the route"
                  onClick={() => props.onReorder(props.index, 1)}>↓</button>
          {!isBase && (
            <button style={ghostButton}
                    onClick={() => props.onPatch(q.id,
                      q.kind === "PATROL"
                        ? { kind: "TRANSIT", loiter_min: undefined }
                        : { kind: "PATROL", loiter_min: 60, pattern: "ORBIT",
                            radius_km: 15 })}>
              {q.kind === "PATROL" ? "MAKE TRANSIT" : "MAKE PATROL"}
            </button>
          )}
          <button style={{ ...ghostButton, marginLeft: "auto",
                           color: "var(--alert-warn-ink)" }}
                  disabled={props.plan.points.length <= 2}
                  onClick={() => props.onRemove(q.id)}>REMOVE</button>
        </div>
      </fieldset>

      <div style={{ marginTop: "var(--space-3)", fontSize: "var(--size-label)",
                    color: "var(--ink-mute)", fontFamily: "var(--font-num)" }}>
        {Math.abs(q.lat_deg).toFixed(4)}°{q.lat_deg >= 0 ? "N" : "S"}{"  "}
        {Math.abs(q.lon_deg).toFixed(4)}°{q.lon_deg >= 0 ? "E" : "W"}
      </div>
      {base && (
        <div style={{ marginTop: 6, fontSize: "var(--size-label)",
                      color: "var(--ink-mute)", lineHeight: 1.5 }}>
          {base.name} · {base.elevation_ft.toLocaleString()} ft · {base.note}
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ *
 * A leg
 * ------------------------------------------------------------------ */

function LegBody(props: { segment: Segment; identity: MissionIdentity }) {
  const s = props.segment;
  const bad = s.terrain && !s.terrain.clears;
  const eta = zuluAfter(props.identity.launch_utc, s.cumulative_min);
  return (
    <>
      <Head hue={bad ? "var(--alert-warn)" : "var(--ref-selected)"}
            kind={"leg " + (s.i + 1)} name={s.from + " → " + s.to} />
      <div style={{ display: "grid", gap: "4px 12px",
                    gridTemplateColumns: "repeat(auto-fit, minmax(112px, 1fr))" }}>
        <Cell k="distance" v={s.distance_km.toFixed(1) + " km"} />
        <Cell k="course" v={Math.round(s.course_deg) + "°"} />
        <Cell k="ete" v={fmtMin(s.ete_min)} />
        <Cell k={eta === "—" ? "t+" : "eta"}
              v={eta === "—" ? fmtMin(s.cumulative_min) : eta} />
        <Cell k="cumulative" v={s.cumulative_km.toFixed(0) + " km"} />
        {/* Two altitudes and a unit do not fit in half a 380 px panel. */}
        <div style={{ gridColumn: "1 / -1" }}>
          <Cell k="altitude"
                v={Math.round(s.alt0_ft).toLocaleString() + " → "
                   + Math.round(s.alt1_ft).toLocaleString() + " ft"} />
        </div>
        <Cell k="climb required"
              v={Math.abs(s.required_fpm) < 1 ? "level"
                 : Math.round(s.required_fpm).toLocaleString() + " fpm"} />
        <Cell k="terrain"
              v={s.terrain
                ? Math.round(s.terrain.max_terrain_ft).toLocaleString() + " ft"
                : "— costing"} />
        <Cell k="clearance"
              v={s.terrain
                ? Math.round(s.terrain.margin_ft).toLocaleString() + " ft"
                : "— costing"}
              hue={bad ? "var(--alert-warn)" : undefined} />
        <Cell k="fuel" v={s.cost ? s.cost.fuel_l.toFixed(1) + " L" : "— costing"} />
        <Cell k="engine life"
              v={s.cost ? s.cost.life_hours.toFixed(3) + " h" : "— costing"} />
        <Cell k="mean power"
              v={s.cost ? s.cost.mean_power_kw.toFixed(1) + " kW" : "— costing"} />
        <Cell k="mean CHT"
              v={s.cost ? Math.round(s.cost.mean_cht_c) + " °C" : "— costing"} />
        <Cell k="OAT" v={s.cost ? Math.round(s.cost.oat_c) + " °C" : "— costing"} />
        {s.cost && s.cost.wastegate_saturated_min > 0 && (
          <Cell k="wastegate at stop"
                v={fmtMin(s.cost.wastegate_saturated_min)}
                hue="var(--alert-caut)" />
        )}
      </div>
      <div style={{ marginTop: "var(--space-4)", fontSize: "var(--size-label)",
                    color: "var(--ink-mute)", lineHeight: 1.55,
                    borderLeft: "2px solid var(--line)", paddingLeft: 8 }}>
        Course, distance and time are geometry at the planned airspeed.
        {s.cost ? " Fuel, life, power and temperature are the route costing's."
                : " Fuel, life and terrain need COST IT."}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ *
 * An event
 * ------------------------------------------------------------------ */

function EventBody(props: { ev: FlightSim["events"][number]; pb: Playback }) {
  const e = props.ev;
  const hue = e.severity === "WARNING" ? "var(--alert-warn)"
    : e.severity === "CAUTION" ? "var(--alert-caut)" : "var(--alert-advis)";
  return (
    <>
      <Head hue={hue} kind={e.severity.toLowerCase()}
            name={e.code.replace(/_/g, " ")} />
      <div style={{ fontSize: "var(--size-body)", lineHeight: 1.55,
                    marginBottom: "var(--space-4)" }}>
        {e.message}
      </div>
      <div style={{ display: "grid", gap: "4px 12px",
                    gridTemplateColumns: "repeat(auto-fit, minmax(112px, 1fr))" }}>
        <Cell k="at" v={"T+" + fmtClock(e.t_s)} />
        <Cell k="phase" v={e.phase} />
        <Cell k="altitude" v={Math.round(e.altitude_ft).toLocaleString() + " ft"} />
        {e.value != null && (
          <Cell k="value" v={e.value.toFixed(1) + " " + e.unit} hue={hue} />
        )}
        {e.limit != null && (
          <Cell k="limit" v={e.limit.toFixed(1) + " " + e.unit} />
        )}
      </div>
      <button onClick={() => { props.pb.pause(); props.pb.seek(e.t_s); }}
              className="ms-chip"
              style={{ ...ghostButton, marginTop: "var(--space-4)" }}>
        GO TO THIS MOMENT
      </button>
      <div style={{ marginTop: "var(--space-3)", fontSize: "var(--size-label)",
                    color: "var(--ink-mute)", fontFamily: "var(--font-num)" }}>
        {Math.abs(e.lat_deg).toFixed(4)}°{e.lat_deg >= 0 ? "N" : "S"}{"  "}
        {Math.abs(e.lon_deg).toFixed(4)}°{e.lon_deg >= 0 ? "E" : "W"}
      </div>
    </>
  );
}

function Cell(props: { k: string; v: string; hue?: string; note?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    letterSpacing: "0.05em", whiteSpace: "nowrap",
                    overflow: "hidden", textOverflow: "ellipsis" }}>
        {props.k.toUpperCase()}
      </div>
      <div style={{ fontFamily: "var(--font-num)", fontSize: "var(--size-body)",
                    color: props.hue ?? "var(--ink)", whiteSpace: "nowrap",
                    overflow: "hidden", textOverflow: "ellipsis" }}>
        {props.v}
      </div>
      {props.note && (
        <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)" }}>
          {props.note}
        </div>
      )}
    </div>
  );
}
