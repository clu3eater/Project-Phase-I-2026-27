/* THE MISSION INSPECTOR — eight things a sortie is made of, one line each.
 *
 * WHAT THIS REPLACES, AND WHY
 * ---------------------------
 * The planner this page used was six accordions of controls. Every one of them
 * had to be opened to find out what it currently said, so the panel answered
 * "what can I change?" and never "what is this sortie?". These rows answer the
 * second question in their headers -- BASES reads VIJO → VIUT, ENVIRONMENT
 * reads ISA+0 · 30 % RH -- and hold the controls behind them.
 *
 * ONE OPEN AT A TIME. Eight open sections is the stack of forms this was meant
 * to stop being; one open section is an inspector. The open one takes the room
 * that is left and scrolls inside itself, so the list an operator is working
 * in is never the thing pushed off the bottom.
 *
 * NOTHING NEW IS INVENTED HERE. Every control is one the panel already had and
 * every figure is either geometry or something the server answered. Where the
 * server has no opinion -- wind, a per-leg speed, a cruise throttle, a divert
 * -- the row says so instead of offering a control that changes nothing.
 */

import { useState, type ReactNode } from "react";

import { AIRBASES, BASE_BY_ID, type Airbase } from "../data/airbases";
import type { RouteCost } from "../lib/api";
import { CONDITIONS } from "../mission/Planner";
import {
  TYPE_BY_KEY, buildPlan, emptyPlan, fmtMin, newId, withBase,
  type Expansion, type MissionPlan, type PlanPoint,
} from "../mission/plan";
import { Chip, Field, Slider, ghostButton, inputStyle, numStyle } from "../mission/ui";
import { densityAltitude, divert, isaOat, type Constraints } from "./mission";

/* ------------------------------------------------------------------ *
 * The row
 * ------------------------------------------------------------------ */

export type RowKey =
  | "BASES" | "ROUTE" | "PATROL" | "AIRCRAFT" | "SORTIE" | "ENVIRONMENT"
  | "CONSTRAINTS" | "SCENARIO";

function Row(props: {
  id: RowKey;
  title: string;
  summary: ReactNode;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  locked?: boolean;
  tone?: string;
}) {
  /* THE OPEN BODY TAKES ITS NATURAL HEIGHT AND THE COLUMN SCROLLS.
   *
   * It used to take the space that was left and scroll inside itself, which
   * is tidier when it fits and wrong when it does not: a body with a floor
   * taller than the room left overflowed its own section and PAINTED OVER
   * the rows underneath it. A list of waypoints drawn across AIRCRAFT and
   * ENVIRONMENT is not a layout bug an operator can work around.
   *
   * One scroller for the column, and the only nested one is the route list,
   * which is capped because it is the one thing here that has no bound. */
  return (
    <section
      style={{ borderBottom: "1px solid var(--line)", minWidth: 0,
               display: "flex", flexDirection: "column", flex: "0 0 auto" }}>
      <button onClick={props.onToggle} aria-expanded={props.open}
              className="mo-tab"
              style={{ display: "flex", alignItems: "center", gap: 8,
                       width: "100%", minHeight: 36, flex: "0 0 auto",
                       padding: "0 var(--space-4)", background: "transparent",
                       border: "none", cursor: "pointer", textAlign: "left",
                       color: "var(--ink-dim)", fontFamily: "var(--font-ui)",
                       fontSize: "var(--size-label)", letterSpacing: "0.1em",
                       fontWeight: 600 }}>
        <span aria-hidden="true" className="mo-chev"
              style={{ display: "inline-block", width: 9, textAlign: "center",
                       transform: props.open ? "rotate(90deg)" : "none",
                       color: "var(--ink-mute)" }}>›</span>
        <span style={{ flex: "0 0 auto", whiteSpace: "nowrap" }}>
          {props.title}
        </span>
        <span style={{ marginLeft: "auto", letterSpacing: 0, fontWeight: 400,
                       color: props.tone ?? "var(--ink-mute)", minWidth: 0,
                       overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap", fontFamily: "var(--font-num)" }}>
          {props.summary}
        </span>
      </button>
      {props.open && (
        <fieldset disabled={props.locked}
                  className={"mo-swap" + (props.locked ? " ms-locked" : "")}
                  style={{ flex: "0 0 auto", margin: 0, border: "none",
                           minWidth: 0, overflow: "visible",
                           padding: "0 var(--space-4) var(--space-4)" }}>
          {props.children}
        </fieldset>
      )}
    </section>
  );
}

const note: React.CSSProperties = {
  fontSize: "var(--size-label)", color: "var(--ink-mute)", lineHeight: 1.5,
  borderLeft: "2px solid var(--line)", paddingLeft: 8, marginTop: 8,
};

/* ------------------------------------------------------------------ *
 * The eight
 * ------------------------------------------------------------------ */

export function Sections(props: {
  plan: MissionPlan;
  onPlan: (p: MissionPlan) => void;
  expansion: Expansion;
  cost: RouteCost | null;
  engine: any;
  snap: any;
  locked: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onPatch: (id: string, q: Partial<PlanPoint>) => void;
  constraints: Constraints;
  onConstraints: (c: Constraints) => void;
  coldStart: boolean;
  onColdStart: (v: boolean) => void;
  /** The fault staged for the next sortie, if any. */
  draftMode: string;
  draftSeverity: number;
  onConfigureFault: () => void;
  mayRunScenarios: boolean;
}) {
  /* An empty plan starts where planning starts: choosing the two fields. */
  const [open, setOpen] = useState<RowKey | null>(
    () => (props.plan.points.length ? "ROUTE" : "BASES"));
  const toggle = (k: RowKey) => setOpen((x) => (x === k ? null : k));
  const { plan, expansion: ex } = props;
  const set = (patch: Partial<MissionPlan>) => props.onPlan({ ...plan, ...patch });
  const setPoints = (points: PlanPoint[]) =>
    props.onPlan({ ...plan, points, type: "CUSTOM" });

  const dep = plan.points.find((q) => q.kind === "DEPARTURE");
  const rec = [...plan.points].reverse().find((q) => q.kind === "RECOVERY");
  const alt = divert(plan);
  const patrols = plan.points.filter((q) => q.kind === "PATROL");

  const setBase = (b: Airbase, kind: "DEPARTURE" | "RECOVERY") =>
    props.onPlan(withBase(plan, b, kind));

  const addPatrol = () => {
    const pts = plan.points;
    let at = Math.max(1, pts.length - 1), best = -1;
    for (let i = 1; i < pts.length; i++) {
      const d = Math.hypot(pts[i].lat_deg - pts[i - 1].lat_deg,
                           pts[i].lon_deg - pts[i - 1].lon_deg);
      if (d > best) { best = d; at = i; }
    }
    const a = pts[at - 1], b = pts[at];
    const t = TYPE_BY_KEY[plan.type] ?? TYPE_BY_KEY.ISR;
    const made: PlanPoint = {
      id: newId(), kind: "PATROL",
      name: "AREA " + String.fromCharCode(65 + patrols.length),
      lat_deg: +((a.lat_deg + b.lat_deg) / 2).toFixed(4),
      lon_deg: +((a.lon_deg + b.lon_deg) / 2).toFixed(4),
      altitude_ft: t.patrol_ft, loiter_min: 60, pattern: "ORBIT", radius_km: 15,
    };
    const next = [...plan.points];
    next.splice(at, 0, made);
    setPoints(next);
    props.onSelect(made.id);
  };

  /* RESET never invents what was not chosen: with both fields and a type it
   * redraws that type's route between them; otherwise it keeps only the
   * fields that were picked and clears the rest. */
  const reset = () => {
    const t = TYPE_BY_KEY[plan.type];
    if (dep?.base_id && rec?.base_id && t) {
      props.onPlan(buildPlan(t, BASE_BY_ID[dep.base_id], BASE_BY_ID[rec.base_id],
                             { ...plan, name: plan.name }));
    } else {
      props.onPlan({ ...emptyPlan(plan), type: plan.type, name: plan.name,
                     alternate_id: plan.alternate_id,
                     points: plan.points.filter((q) => q.base_id
                       && (q.kind === "DEPARTURE" || q.kind === "RECOVERY")) });
    }
    props.onSelect(null);
  };

  /* Cruise, for the atmosphere readout: the highest altitude the sortie is
   * planned to hold, which is where the air matters most to the engine. */
  const cruise_ft = Math.max(...ex.waypoints.map((w) => w.altitude_ft), 0);
  const oat = isaOat(cruise_ft, plan.isa_deviation_c);
  /* The server's own answer, once there is one. A RESULT replaces an AUTO. */
  const flownOat = props.cost?.legs?.length
    ? props.cost.legs.reduce((m, l) => Math.min(m, l.oat_c), 1e9) : null;

  const id = props.engine?.identity ?? {};
  const rat = props.engine?.ratings ?? {};
  const lim = props.engine?.limits ?? {};

  return (
    <div className="panel-body"
         style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex",
                  flexDirection: "column" }}>

      {/* ---- BASES ---------------------------------------------------- */}
      <Row id="BASES" title="BASES" open={open === "BASES"}
           onToggle={() => toggle("BASES")} locked={props.locked}
           summary={(dep?.base_id ?? "—") + " → " + (rec?.base_id ?? "—")
                    + " · ALT " + (alt ? alt.id : "none")}>
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <Field label="Departure">
            <select style={inputStyle} value={dep?.base_id ?? ""}
                    aria-label="departure field"
                    onChange={(e) => setBase(BASE_BY_ID[e.target.value], "DEPARTURE")}>
              {!dep?.base_id && <option value="">— from the map —</option>}
              {AIRBASES.map((b) => (
                <option key={b.id} value={b.id}>{b.short} · {b.id}</option>
              ))}
            </select>
            {dep?.base_id && <Detail b={BASE_BY_ID[dep.base_id]} />}
          </Field>
          <Field label="Recovery">
            <select style={inputStyle} value={rec?.base_id ?? ""}
                    aria-label="recovery field"
                    onChange={(e) => setBase(BASE_BY_ID[e.target.value], "RECOVERY")}>
              {!rec?.base_id && <option value="">— from the map —</option>}
              {AIRBASES.map((b) => (
                <option key={b.id} value={b.id}>{b.short} · {b.id}</option>
              ))}
            </select>
            {rec?.base_id && <Detail b={BASE_BY_ID[rec.base_id]} />}
          </Field>
          <Field label="Alternate">
            <select style={inputStyle} value={plan.alternate_id ?? ""}
                    aria-label="alternate field"
                    onChange={(e) => set({ alternate_id: e.target.value || null })}>
              <option value="">— none —</option>
              {AIRBASES.map((b) => (
                <option key={b.id} value={b.id}>{b.short} · {b.id}</option>
              ))}
            </select>
          </Field>
          {alt && (
            <div style={{ display: "grid", gap: 2,
                          gridTemplateColumns: "repeat(auto-fit, minmax(96px, 1fr))",
                          fontSize: "var(--size-label)" }}>
              <KV k="bearing" v={Math.round(alt.course_deg) + "°"} />
              <KV k="distance" v={Math.round(alt.km).toLocaleString() + " km"} />
              <KV k="elevation"
                  v={Math.round(alt.elevation_ft).toLocaleString() + " ft"} />
              {/* FIRST ORDER, AND IT SAYS SO. The route costing prices the
                  ROUTE; there is no divert in the flight model, so this is
                  the sortie's own average burn carried over the diversion
                  distance and nothing more. */}
              <KV k="fuel ≈"
                  v={props.cost && props.cost.distance_km > 0
                    ? (props.cost.fuel_l / props.cost.distance_km * alt.km)
                        .toFixed(1) + " L"
                    : "— costing"}
                  title="the sortie's average burn over the diversion distance — first order, not a flown divert" />
            </div>
          )}
          <div style={note}>
            The alternate is planning only: the flight model flies departure to
            recovery and has no divert.
          </div>
        </div>
      </Row>

      {/* ---- ROUTE ---------------------------------------------------- */}
      <Row id="ROUTE" title="ROUTE" open={open === "ROUTE"}
           onToggle={() => toggle("ROUTE")} locked={props.locked}
           summary={plan.points.length + " points · "
                    + Math.round(ex.distance_km).toLocaleString() + " km · "
                    + fmtMin(ex.air_minutes)}>
        <div className="panel-body"
             style={{ display: "flex", flexDirection: "column", gap: 3,
                      maxHeight: 322, overflowY: "auto", overflowX: "hidden" }}>
          {plan.points.length === 0 && (
            <div style={note}>
              No route yet. Choose the departure and recovery fields in BASES
              (or click a field on the map), then add waypoints or a patrol area.
            </div>
          )}
          {plan.points.map((q, i) => {
            const isBase = q.kind === "DEPARTURE" || q.kind === "RECOVERY";
            const hue = isBase ? "var(--state-normal)"
              : q.kind === "PATROL" ? "var(--alert-caut)" : "var(--alert-advis)";
            const on = props.selectedId === q.id;
            return (
              <button key={q.id} className="ms-row"
                      onClick={() => props.onSelect(on ? null : q.id)}
                      aria-pressed={on}
                      style={{ display: "flex", alignItems: "center", gap: 9,
                               width: "100%", minHeight: 34, padding: "0 9px",
                               background: on ? "var(--bg-raised)" : "transparent",
                               border: "1px solid " + (on ? hue : "transparent"),
                               borderRadius: "var(--radius)", cursor: "pointer",
                               textAlign: "left", color: "var(--ink)",
                               fontFamily: "var(--font-ui)",
                               fontSize: "var(--size-body)" }}>
                <span style={{ width: 20, height: 20, flex: "0 0 auto",
                               borderRadius: 10, border: "1.5px solid " + hue,
                               color: hue, display: "flex",
                               alignItems: "center", justifyContent: "center",
                               fontSize: "var(--size-label)",
                               fontFamily: "var(--font-num)" }}>
                  {i + 1}
                </span>
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {q.name}
                  {q.kind === "PATROL" && q.loiter_min ? (
                    <span style={{ color: "var(--ink-mute)", marginLeft: 7,
                                   fontSize: "var(--size-label)" }}>
                      {fmtMin(q.loiter_min)}
                    </span>
                  ) : null}
                </span>
                <span style={{ fontFamily: "var(--font-num)",
                               fontSize: "var(--size-label)",
                               color: "var(--ink-dim)", whiteSpace: "nowrap" }}>
                  {Math.round(q.altitude_ft).toLocaleString()} ft
                </span>
              </button>
            );
          })}
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: "var(--space-3)" }}>
          <button style={{ ...ghostButton, flex: 1,
                           opacity: plan.points.length < 2 ? 0.5 : 1 }}
                  onClick={addPatrol} disabled={plan.points.length < 2}
                  title={plan.points.length < 2
                    ? "choose the departure and recovery fields first" : undefined}>
            + PATROL AREA
          </button>
          <button style={ghostButton} onClick={reset}>RESET</button>
        </div>
        <div style={note}
             title="RouteRequest carries one true airspeed for the whole sortie, so there is no per-leg speed to set.">
          All legs at <b style={{ fontFamily: "var(--font-num)" }}>
          {plan.airspeed_kmh} km/h</b> — one airspeed per sortie.
        </div>
        {ex.notes.map((n, i) => <div key={i} style={note}>{n}</div>)}
        {ex.errors.map((n, i) => (
          <div key={i} style={{ ...note, color: "var(--alert-caut)",
                                borderLeftColor: "var(--alert-caut)" }}>{n}</div>
        ))}
      </Row>

      {/* ---- PATROL AREA ---------------------------------------------- */}
      <Row id="PATROL" title="PATROL AREA" open={open === "PATROL"}
           onToggle={() => toggle("PATROL")} locked={props.locked}
           tone={ex.patrols.some((p) => p.clipped) ? "var(--alert-caut)" : undefined}
           summary={patrols.length === 0 ? "none"
             : (patrols[0].pattern ?? "ORBIT").toLowerCase() + " · "
               + (patrols[0].radius_km ?? 15) + " km · "
               + fmtMin(ex.on_station_min)}>
        {patrols.length === 0 ? (
          <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                        lineHeight: 1.55 }}>
            No area in this sortie — it is a transit. Add one from ROUTE, or
            make any waypoint a patrol area by selecting it.
          </div>
        ) : patrols.map((q) => {
          const pa = ex.patrols.find((x) => x.point_id === q.id);
          return (
            <div key={q.id} style={{ marginBottom: "var(--space-4)" }}>
              <button onClick={() => props.onSelect(q.id)} className="ms-row"
                      style={{ display: "flex", width: "100%", gap: 8,
                               alignItems: "baseline", background: "transparent",
                               border: "none", cursor: "pointer", padding: "0 0 6px",
                               color: "var(--ink)", fontFamily: "var(--font-ui)",
                               fontSize: "var(--size-body)", fontWeight: 600 }}>
                {q.name}
                <span style={{ marginLeft: "auto", fontSize: "var(--size-label)",
                               color: "var(--ink-mute)" }}>
                  {Math.round(q.altitude_ft).toLocaleString()} ft
                </span>
              </button>
              <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
                {(["ORBIT", "RACETRACK"] as const).map((x) => (
                  <Chip key={x} on={(q.pattern ?? "ORBIT") === x} tone="caut"
                        onClick={() => props.onPatch(q.id, { pattern: x })}>
                    {x}
                  </Chip>
                ))}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                            gap: "var(--space-2)" }}>
                <Field label="On station">
                  <input type="number" value={q.loiter_min ?? 60} style={numStyle}
                         min={0} max={600} step={5}
                         onChange={(e) => props.onPatch(q.id, {
                           loiter_min: Math.max(0, Math.min(600,
                             Number(e.target.value))) })} />
                </Field>
                <Field label="Radius km">
                  <input type="number" value={q.radius_km ?? 15} style={numStyle}
                         min={2} max={90} step={1}
                         onChange={(e) => props.onPatch(q.id, {
                           radius_km: Math.max(2, Math.min(90,
                             Number(e.target.value))) })} />
                </Field>
              </div>
              {/* WHAT WILL ACTUALLY BE FLOWN, against what was asked for. */}
              {pa && (
                <div style={{ ...note,
                              color: pa.clipped ? "var(--alert-caut)"
                                                : "var(--ink-mute)",
                              borderLeftColor: pa.clipped ? "var(--alert-caut)"
                                                          : "var(--line)" }}>
                  {pa.laps} lap{pa.laps === 1 ? "" : "s"} of{" "}
                  {pa.lap_km.toFixed(1)} km as {pa.laps * pa.ring.length} waypoints
                  {" "}— <b>{fmtMin(pa.achieved_min)}</b> on station
                  {pa.clipped
                    ? " of the " + fmtMin(pa.requested_min) + " asked for; the"
                      + " waypoint budget stopped it."
                    : "."}
                </div>
              )}
            </div>
          );
        })}
      </Row>

      {/* ---- AIRCRAFT -------------------------------------------------- */}
      <Row id="AIRCRAFT" title="AIRCRAFT" open={open === "AIRCRAFT"}
           onToggle={() => toggle("AIRCRAFT")}
           summary={props.snap?.twin?.metadata?.aircraft_id ?? "—"}>
        <div style={{ display: "grid", gap: 2, marginBottom: "var(--space-3)" }}>
          <KV k="airframe" v={props.snap?.twin?.metadata?.aircraft_id ?? "—"} />
          <KV k="twin" v={props.snap?.twin?.metadata?.twin_id ?? "—"} />
          <KV k="engine" v={id.display_name ?? props.snap?.twin?.metadata?.engine_type ?? "—"} />
          {id.certification && <KV k="certificate" v={id.certification} />}
          {rat.max_power_kW != null && (
            <KV k="rated" v={rat.max_power_kW + " kW at "
                             + (rat.max_power_rpm ?? "—").toLocaleString() + " rpm"} />
          )}
          {rat.continuous_power_kW != null && (
            <KV k="continuous" v={rat.continuous_power_kW + " kW at "
                                  + (rat.continuous_power_rpm ?? "—").toLocaleString()
                                  + " rpm"} />
          )}
          {rat.tbo_hours != null && (
            <KV k="overhaul" v={rat.tbo_hours.toLocaleString() + " h"} />
          )}
          {rat.max_operating_altitude_ft != null && (
            <KV k="ceiling, certified"
                v={rat.max_operating_altitude_ft.toLocaleString() + " ft"} />
          )}
          {lim.coolant_temperature_max_C != null && (
            <KV k="coolant limit" v={lim.coolant_temperature_max_C + " °C"} />
          )}
          {lim.egt_max_C != null && <KV k="EGT limit" v={lim.egt_max_C + " °C"} />}
        </div>
        {/* THE ASSUMPTIONS ARE PART OF THE AIRCRAFT, and this is where an
            operator would look for them. They are the server's own words,
            not the console's opinion. */}
        <div style={note}>
          The route model flies airframe numbers, not aerodynamics: ground speed
          equals true airspeed, and there is no wind, no drag polar and no
          divert. What the engine does with that is the physics.
        </div>
        {id.validated === false && (
          <div style={{ ...note, color: "var(--alert-caut)",
                        borderLeftColor: "var(--alert-caut)" }}>
            This engine file is an adaptation stub and is not validated. No
            accuracy claim may be made from a sortie flown on it.
          </div>
        )}
      </Row>

      {/* ---- SORTIE ---------------------------------------------------- */}
      <Row id="SORTIE" title="SORTIE ASSUMPTIONS" open={open === "SORTIE"}
           onToggle={() => toggle("SORTIE")} locked={props.locked}
           summary={plan.airspeed_kmh + " km/h · " + plan.usable_fuel_l + " L · "
                    + (props.coldStart ? "cold start" : "airborne")}>
        <div style={{ display: "grid", gap: "var(--space-4)" }}>
          <Slider label="True airspeed" value={plan.airspeed_kmh}
                  min={110} max={280} step={5} unit="km/h"
                  onChange={(v) => set({ airspeed_kmh: v })} />
          <Slider label="Usable fuel" value={plan.usable_fuel_l}
                  min={40} max={260} step={5} unit="L"
                  onChange={(v) => set({ usable_fuel_l: v })} />
          <Field label="Engine flown">
            <div style={{ display: "flex", gap: 6 }}>
              <Chip on={plan.live_engine} onClick={() => set({ live_engine: true })}
                    title="the engine that is running now, worn as it is">
                THIS ENGINE
              </Chip>
              <Chip on={!plan.live_engine} onClick={() => set({ live_engine: false })}
                    title="a fresh engine of the type — what a flight manual answers">
                AS NEW
              </Chip>
            </div>
          </Field>
          <Field label="Start">
            <div style={{ display: "flex", gap: 6 }}>
              <Chip on={props.coldStart} onClick={() => props.onColdStart(true)}
                    title="the sortie begins stopped and cold, on the starter, and warms up until the oil is fit to take off on">
                COLD START
              </Chip>
              <Chip on={!props.coldStart} onClick={() => props.onColdStart(false)}
                    title="the sortie begins from a warm running engine, which saves the minutes of ground running">
                AIRBORNE ONLY
              </Chip>
            </div>
          </Field>
        </div>
        <div style={note}>
          Cruise throttle is not a control: the flight model flies the cruise at
          its own setting and takes none from the request.
        </div>
      </Row>

      {/* ---- ENVIRONMENT ----------------------------------------------- */}
      <Row id="ENVIRONMENT" title="ENVIRONMENT" open={open === "ENVIRONMENT"}
           onToggle={() => toggle("ENVIRONMENT")} locked={props.locked}
           summary={(plan.isa_deviation_c >= 0 ? "ISA+" : "ISA")
                    + plan.isa_deviation_c + " °C · " + plan.humidity_pct + " % RH"}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6,
                      marginBottom: "var(--space-4)" }}>
          {CONDITIONS.map((c) => (
            <Chip key={c.label} title={c.note}
                  on={c.isa === plan.isa_deviation_c && c.rh === plan.humidity_pct}
                  onClick={() => set({ isa_deviation_c: c.isa, humidity_pct: c.rh })}>
              {c.label}
            </Chip>
          ))}
        </div>
        <div style={{ display: "grid", gap: "var(--space-4)" }}>
          <Slider label="ISA deviation" value={plan.isa_deviation_c}
                  min={-30} max={45} step={1} unit="°C"
                  display={(plan.isa_deviation_c >= 0 ? "+" : "")
                           + plan.isa_deviation_c}
                  onChange={(v) => set({ isa_deviation_c: v })} />
          <Slider label="Humidity" value={plan.humidity_pct}
                  min={0} max={100} step={5} unit="% RH"
                  onChange={(v) => set({ humidity_pct: v })} />
        </div>
        {/* WHAT THAT MEANS IN THE AIR. Arithmetic on the input until the
            costing has flown it, and then the model's own figure. */}
        <div style={{ display: "grid", gap: 2, marginTop: "var(--space-4)",
                      gridTemplateColumns: "repeat(auto-fit, minmax(108px, 1fr))" }}>
          <KV k="cruise" v={cruise_ft.toLocaleString() + " ft"} />
          <KV k={flownOat != null ? "OAT · costed" : "OAT · standard"}
              v={Math.round(flownOat ?? oat) + " °C"}
              title={flownOat != null
                ? "the coldest leg OAT the route costing computed"
                : "standard atmosphere at the planned cruise; the costing replaces it"} />
          <KV k="density alt"
              v={Math.round(densityAltitude(cruise_ft, plan.isa_deviation_c))
                 .toLocaleString() + " ft"}
              title="dry air at standard pressure. The console has no QNH to set; the engine model accounts for humidity itself." />
        </div>
        <div style={note}>
          No wind is modelled anywhere in this console — the route, the sortie
          and every ETA on the page are still-air figures.
        </div>
      </Row>

      {/* ---- CONSTRAINTS ------------------------------------------------ */}
      <Row id="CONSTRAINTS" title="CONSTRAINTS" open={open === "CONSTRAINTS"}
           onToggle={() => toggle("CONSTRAINTS")}
           summary={props.constraints.min_clearance_ft.toLocaleString() + " ft · "
                    + props.constraints.reserve_min + " min · "
                    + props.constraints.max_duration_h + " h"}>
        <Num label="Minimum terrain clearance" unit="ft" step={100}
             value={props.constraints.min_clearance_ft}
             hint="The flight model raises its own clearance caution at 1,000 ft."
             on={(v) => props.onConstraints({ ...props.constraints,
                                              min_clearance_ft: v })} />
        <Num label="Fuel reserve on landing" unit="min" step={5}
             value={props.constraints.reserve_min}
             hint="The airframe configuration plans 45 minutes."
             on={(v) => props.onConstraints({ ...props.constraints,
                                              reserve_min: v })} />
        <Num label="Maximum sortie duration" unit="h" step={1}
             value={props.constraints.max_duration_h}
             on={(v) => props.onConstraints({ ...props.constraints,
                                              max_duration_h: v })} />
        <Num label="Ceiling margin required" unit="ft" step={100}
             value={props.constraints.ceiling_margin_ft}
             on={(v) => props.onConstraints({ ...props.constraints,
                                              ceiling_margin_ft: v })} />
        <div style={note}>
          What this crew will accept. CHECKS judges the plan against these; the
          flight model flies its own reserve either way.
        </div>
      </Row>

      {/* ---- SCENARIO ---------------------------------------------------- */}
      <Row id="SCENARIO" title="SCENARIO" open={open === "SCENARIO"}
           onToggle={() => toggle("SCENARIO")}
           tone={props.draftMode ? "var(--alert-caut)" : undefined}
           summary={props.draftMode
             ? props.draftMode.replace(/_/g, " ").toUpperCase() + " · "
               + props.draftSeverity.toFixed(2)
             : "no active fault"}>
        <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                      lineHeight: 1.55 }}>
          {props.draftMode ? (
            <>The next sortie will be flown against{" "}
              <b style={{ color: "var(--alert-caut)" }}>
                {props.draftMode.replace(/_/g, " ").toUpperCase()}
              </b>{" "}at severity {props.draftSeverity.toFixed(2)}. The live
              engine is not touched by it.</>
          ) : (
            <>The sortie will be flown clean. A fault configured here belongs to
              the simulation and is discarded with it — to degrade the running
              engine instead, use the twin lab on the INJECT FAULT page.</>
          )}
        </div>
        <button onClick={props.onConfigureFault} className="ms-chip"
                disabled={!props.mayRunScenarios}
                style={{ ...ghostButton, marginTop: "var(--space-3)",
                         color: props.mayRunScenarios ? "var(--alert-caut)"
                                                      : "var(--ink-mute)",
                         borderColor: props.mayRunScenarios ? "var(--alert-caut)"
                                                            : "var(--line)" }}>
          {props.draftMode ? "CHANGE FAULT" : "CONFIGURE FAULT"}
        </button>
        {!props.mayRunScenarios && (
          <div style={note}>
            Flying a sortie against a fault is gated on <b>run:simulation</b>,
            which this role does not hold.
          </div>
        )}
      </Row>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Small parts
 * ------------------------------------------------------------------ */

function Detail({ b }: { b: Airbase | undefined }) {
  if (!b) return null;
  return (
    <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                  marginTop: 4, whiteSpace: "nowrap", overflow: "hidden",
                  textOverflow: "ellipsis" }} title={b.note}>
      {b.name} · {b.elevation_ft.toLocaleString()} ft
    </div>
  );
}

function KV(props: { k: string; v: string; title?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}
         title={props.title}>
      <span style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                     letterSpacing: "0.05em", flex: "0 0 auto" }}>
        {props.k.toUpperCase()}
      </span>
      <span style={{ marginLeft: "auto", fontFamily: "var(--font-num)",
                     fontSize: "var(--size-label)", color: "var(--ink-dim)",
                     minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap" }}>
        {props.v}
      </span>
    </div>
  );
}

function Num(props: { label: string; value: number; unit: string; step: number;
                      hint?: string; on: (v: number) => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minHeight: 34 }}
         title={props.hint}>
      <span style={{ flex: 1, minWidth: 0, fontSize: "var(--size-label)",
                     color: "var(--ink-dim)" }}>{props.label}</span>
      <input type="number" value={props.value} step={props.step}
             aria-label={props.label}
             onChange={(e) => props.on(Number(e.target.value))}
             style={{ ...numStyle, width: 88, minHeight: 30 }} />
      <span style={{ width: 28, fontSize: "var(--size-label)",
                     color: "var(--ink-mute)" }}>{props.unit}</span>
    </div>
  );
}
