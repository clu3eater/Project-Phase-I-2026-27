/* The planner: what the sortie IS, floating at the right edge of the canvas.
 *
 * WHAT CHANGED FROM THE PANEL IT REPLACES
 * ---------------------------------------
 * It no longer owns an action. SIMULATE MISSION and COST IT belong to the
 * dock, at the bottom of the canvas, because they are things done to the
 * WHOLE mission rather than to the field in front of them -- and because a
 * primary button at the foot of a scrolling form is a button that scrolls.
 * What is left here is exactly the definition of the sortie, in the order the
 * decision is taken, and nothing else.
 *
 * It floats OVER the map rather than beside it. The map does not stop at its
 * edge and does not resize when it closes: closing it reveals ground that was
 * always being drawn. That is the difference between a panel and a column.
 *
 * WHAT IT STILL REFUSES TO OFFER
 * ------------------------------
 * A per-waypoint speed, because `RouteRequest` carries one airspeed for the
 * whole sortie. A cruise throttle, because `flight_sim` flies the cruise at
 * its own setting and takes none from the request. Both would be controls
 * that change nothing. See mission/plan.ts for the whole list.
 */

import { AIRBASES, BASE_BY_ID, type Airbase } from "../data/airbases";
import {
  MISSION_TYPES, TYPE_BY_KEY, basePoint, buildPlan, fmtMin, newId,
  type Expansion, type MissionPlan, type PlanPoint,
} from "./plan";
import { Chip, Field, LockGlyph, Section, Slider, ghostButton,
         inputStyle } from "./ui";
import { WhatIf } from "./WhatIf";

/* THE CONDITIONS THE PROBLEM STATEMENT ASKS FOR, AS PRESETS.
 *
 * PRD Part 3 s18 names them: ISA, ISA+10 as the hot day and ISA-10 as the cold
 * day; 30 to 50 degC over Indian desert country at 10 % relative humidity
 * inland and up to 90 % on the coast. The ISA deviations are arithmetic rather
 * than choice -- ISA is 15 degC at sea level, so a 45 degC day IS ISA+30. */
export const CONDITIONS = [
  { label: "Standard", isa: 0, rh: 30,
    note: "ISA — 15 °C at sea level. The reference every figure is quoted against." },
  { label: "Hot day", isa: 10, rh: 30,
    note: "ISA+10, the hot-day model in PRD Part 3 §18.1." },
  { label: "Cold day", isa: -10, rh: 30,
    note: "ISA−10, the cold-day model in PRD Part 3 §18.1." },
  { label: "Thar 45 °C", isa: 30, rh: 10,
    note: "Indian desert: 45 °C at sea level and 10 % humidity — the dry end of PRD §18.3." },
  { label: "Coastal 40 °C", isa: 25, rh: 90,
    note: "40 °C at 90 % humidity. Water vapour displaces the oxygen the charge "
        + "air was carrying, so a wet hot day is not the same day as a dry one." },
  { label: "Himalayan −10 °C", isa: -25, rh: 20,
    note: "ISA−25: dense air and a high field. The engine makes more power and "
        + "the ground is closer to the aircraft." },
];

export interface PlannerProps {
  plan: MissionPlan;
  onPlan: (p: MissionPlan) => void;
  expansion: Expansion;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** Locked from the moment the mission is committed to the engine model. */
  locked: boolean;
  flying: boolean;
  onEdit: () => void;
  onClose: () => void;
  /** snap.faults_injected, for the what-if section. */
  injected: any;
  mayInject: boolean;
  haveBaseline: boolean;
  onReFly: () => void;
  busy: boolean;
}

export function Planner(p: PlannerProps) {
  const { plan, onPlan, expansion } = p;
  const set = (patch: Partial<MissionPlan>) => onPlan({ ...plan, ...patch });

  /* Any edit to the geometry makes the plan its own thing rather than the
   * template it started from, and the type chip says so instead of continuing
   * to claim a shape the route no longer has. */
  const setPoints = (points: PlanPoint[]) =>
    onPlan({ ...plan, points, type: "CUSTOM" });

  const dep = plan.points.find((q) => q.kind === "DEPARTURE");
  const rec = plan.points.find((q) => q.kind === "RECOVERY");
  const ready = expansion.errors.length === 0 && expansion.waypoints.length >= 2;

  const setBase = (b: Airbase, kind: "DEPARTURE" | "RECOVERY") => {
    const i = plan.points.findIndex((q) => q.kind === kind);
    const next = [...plan.points];
    const made = basePoint(b, kind);
    if (i >= 0) next[i] = { ...made, id: next[i].id };
    else if (kind === "DEPARTURE") next.unshift(made);
    else next.push(made);
    setPoints(next);
  };

  const addPatrol = () => {
    /* Placed on the longest leg's midpoint, which is where an area usually
     * belongs and where it will not land on top of an existing point. */
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
      name: "AREA " + String.fromCharCode(65 + plan.points.filter(
        (x) => x.kind === "PATROL").length),
      lat_deg: +((a.lat_deg + b.lat_deg) / 2).toFixed(4),
      lon_deg: +((a.lon_deg + b.lon_deg) / 2).toFixed(4),
      altitude_ft: t.patrol_ft, loiter_min: 60, pattern: "ORBIT", radius_km: 15,
    };
    const next = [...plan.points];
    next.splice(at, 0, made);
    setPoints(next);
    p.onSelect(made.id);
  };

  const reset = () => {
    const d = dep?.base_id ? BASE_BY_ID[dep.base_id] : AIRBASES[0];
    const r = rec?.base_id ? BASE_BY_ID[rec.base_id] : AIRBASES[1];
    onPlan(buildPlan(TYPE_BY_KEY[plan.type] ?? TYPE_BY_KEY.ISR, d, r,
                     { ...plan, name: plan.name }));
    p.onSelect(null);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%",
                  minHeight: 0, pointerEvents: "auto",
                  background: "var(--bg-panel)",
                  border: "1px solid var(--ink-mute)",
                  borderRadius: "var(--radius)" }}>

      <header style={{ display: "flex", alignItems: "center", gap: 9,
                       padding: "8px 8px 8px 12px",
                       borderBottom: "1px solid var(--line)" }}>
        <input value={plan.name} disabled={p.locked} aria-label="mission name"
               title="the name of this mission"
               style={{ ...inputStyle, flex: 1, minWidth: 0, minHeight: 32,
                        background: "transparent", border: "1px solid transparent",
                        fontWeight: 600 }}
               onChange={(e) => set({ name: e.target.value })} />
        <span style={{ fontSize: "var(--size-label)", fontFamily: "var(--font-num)",
                       flex: "0 0 auto", whiteSpace: "nowrap",
                       color: ready ? "var(--ink-mute)" : "var(--alert-caut)" }}
              title="waypoints the server will be sent, of the 24 it accepts">
          {expansion.waypoints.length}/24
        </span>
        <button onClick={p.onClose} aria-label="hide the planner"
                title="hide the planner"
                style={{ width: 30, height: 30, flex: "0 0 auto", padding: 0,
                         display: "flex", alignItems: "center",
                         justifyContent: "center", background: "transparent",
                         border: "1px solid var(--line)",
                         borderRadius: "var(--radius)", color: "var(--ink-dim)",
                         cursor: "pointer" }}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round"
               strokeLinejoin="round" aria-hidden="true"
               style={{ transform: "scaleX(-1)" }}>
            <path d="M14 6l-6 6 6 6" /><path d="M19 4v16" opacity="0.5" />
          </svg>
        </button>
      </header>

      {/* THE LOCK, SAID WHERE THE EDITING WOULD HAPPEN. */}
      {p.locked && (
        <div className="ms-rise"
             style={{ display: "flex", alignItems: "center", gap: 9,
                      padding: "8px 12px",
                      borderBottom: "1px solid var(--alert-caut)",
                      background: "color-mix(in srgb, var(--alert-caut) 12%, transparent)",
                      color: "var(--alert-caut)" }}>
          <LockGlyph />
          <span style={{ fontSize: "var(--size-label)", fontWeight: 700,
                         letterSpacing: "0.07em", minWidth: 0 }}>
            {p.flying ? "LOCKED — BEING FLOWN" : "LOCKED TO THE FLOWN SORTIE"}
          </span>
          <button onClick={p.onEdit} disabled={p.flying}
                  style={{ ...ghostButton, marginLeft: "auto",
                           color: p.flying ? "var(--ink-mute)" : "var(--ink)",
                           cursor: p.flying ? "not-allowed" : "pointer" }}>
            EDIT
          </button>
        </div>
      )}

      <div className="panel-body"
           style={{ flex: 1, minHeight: 0, overflowY: "auto",
                    display: "flex", flexDirection: "column" }}>

        <Section title="Mission type" defaultOpen={false} locked={p.locked}
                 right={<span style={{ fontSize: "var(--size-label)",
                                       color: "var(--ink-mute)" }}>
                   {(TYPE_BY_KEY[plan.type] ?? TYPE_BY_KEY.CUSTOM).label}
                 </span>}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {MISSION_TYPES.map((t) => (
              <Chip key={t.key} on={plan.type === t.key} title={t.blurb}
                    onClick={() => {
                      if (t.key === "CUSTOM") { set({ type: "CUSTOM" }); return; }
                      const d = dep?.base_id ? BASE_BY_ID[dep.base_id] : AIRBASES[0];
                      const r = rec?.base_id ? BASE_BY_ID[rec.base_id] : AIRBASES[1];
                      onPlan(buildPlan(t, d, r, { ...plan, name: "" }));
                      p.onSelect(null);
                    }}>
                {t.label}
              </Chip>
            ))}
          </div>
          {TYPE_BY_KEY[plan.type]?.profile && (
            <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                          marginTop: 8, whiteSpace: "nowrap", overflow: "hidden",
                          textOverflow: "ellipsis" }}>
              Assessed as <b>{TYPE_BY_KEY[plan.type].profile!.replace(/_/g, " ")}</b>
              {" "}in Go / No-Go.
            </div>
          )}
        </Section>

        <Section title="Bases" defaultOpen={false} locked={p.locked}
                 right={<span style={{ fontSize: "var(--size-label)",
                                       color: "var(--ink-mute)",
                                       fontFamily: "var(--font-num)" }}>
                   {dep?.base_id ?? "—"} → {rec?.base_id ?? "—"}
                 </span>}>
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                          letterSpacing: "0.09em" }}>
              DEPARTURE → RECOVERY
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                          gap: "var(--space-2)", marginTop: -6 }}>
              <select style={inputStyle} value={dep?.base_id ?? ""}
                      aria-label="departure field"
                      onChange={(e) => setBase(BASE_BY_ID[e.target.value], "DEPARTURE")}>
                {!dep?.base_id && <option value="">— from the map —</option>}
                {AIRBASES.map((b) => (
                  <option key={b.id} value={b.id}>{b.short} · {b.id}</option>
                ))}
              </select>
              <select style={inputStyle} value={rec?.base_id ?? ""}
                      aria-label="recovery field"
                      onChange={(e) => setBase(BASE_BY_ID[e.target.value], "RECOVERY")}>
                {!rec?.base_id && <option value="">— from the map —</option>}
                {AIRBASES.map((b) => (
                  <option key={b.id} value={b.id}>{b.short} · {b.id}</option>
                ))}
              </select>
            </div>
            <Field label="Alternate">
              <select style={inputStyle} value={plan.alternate_id ?? ""}
                      onChange={(e) => set({ alternate_id: e.target.value || null })}>
                <option value="">— none —</option>
                {AIRBASES.map((b) => (
                  <option key={b.id} value={b.id}>{b.short} · {b.id}</option>
                ))}
              </select>
            </Field>
          </div>
          <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                        marginTop: "var(--space-2)", whiteSpace: "nowrap",
                        overflow: "hidden", textOverflow: "ellipsis" }}
               title={dep?.base_id
                 ? BASE_BY_ID[dep.base_id].name + " — " + BASE_BY_ID[dep.base_id].note
                 : undefined}>
            {dep?.base_id
              ? BASE_BY_ID[dep.base_id].name + ", "
                + BASE_BY_ID[dep.base_id].elevation_ft.toLocaleString() + " ft"
              : "Click a field on the map to set it."}
          </div>
          <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                        marginTop: 3, whiteSpace: "nowrap", overflow: "hidden",
                        textOverflow: "ellipsis" }}
               title="The alternate is planning only: the flight model flies departure to recovery and has no divert.">
            Alternate is planning only — the model has no divert.
          </div>
        </Section>

        {/* THE ROUTE takes the height that is left, and scrolls inside itself,
            so the list the map mirrors is never pushed off the bottom. */}
        <Section title="Route" defaultOpen grow locked={p.locked}
                 right={<span style={{ fontSize: "var(--size-label)",
                                       color: "var(--ink-mute)",
                                       fontFamily: "var(--font-num)" }}>
                   {Math.round(expansion.distance_km).toLocaleString()} km
                 </span>}
                 hint={<span style={{ display: "block", whiteSpace: "nowrap",
                                      overflow: "hidden", textOverflow: "ellipsis" }}
                             title={p.locked
                               ? "Locked to the sortie that was flown. The map still selects and inspects a point."
                               : "Click the map to add a point. Drag one to move it. Select a row to open its editor on the map."}>
                   {p.locked ? "Locked to the flown sortie."
                             : "Click the map to add · drag to move · select to edit"}
                 </span>}>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {plan.points.map((q, i) => {
              const isBase = q.kind === "DEPARTURE" || q.kind === "RECOVERY";
              const hue = isBase ? "var(--state-normal)"
                : q.kind === "PATROL" ? "var(--alert-caut)" : "var(--alert-advis)";
              const on = p.selectedId === q.id;
              return (
                <button key={q.id} className="ms-row"
                        onClick={() => p.onSelect(on ? null : q.id)}
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
            <button style={{ ...ghostButton, flex: 1 }} onClick={addPatrol}>
              + PATROL AREA
            </button>
            <button style={ghostButton} onClick={reset}>RESET</button>
          </div>

          {/* A SPEED PER WAYPOINT IS THE ONE THING EVERY REFERENCE ASKS FOR AND
              THE SERVER DOES NOT TAKE. One line, and the whole of it on hover. */}
          <div style={{ marginTop: 8, fontSize: "var(--size-label)",
                        color: "var(--ink-mute)", whiteSpace: "nowrap",
                        overflow: "hidden", textOverflow: "ellipsis",
                        borderLeft: "2px solid var(--line)", paddingLeft: 8 }}
               title={"RouteRequest carries one true airspeed for the whole sortie, "
                 + "so there is no per-leg speed to set. It is in Operating profile."}>
            All legs at <b style={{ fontFamily: "var(--font-num)" }}>
            {plan.airspeed_kmh} km/h</b> — one airspeed per sortie
          </div>

          {expansion.notes.map((n, i) => (
            <div key={i} style={{ marginTop: 8, fontSize: "var(--size-label)",
                                  color: "var(--ink-mute)", lineHeight: 1.5,
                                  borderLeft: "2px solid var(--line)",
                                  paddingLeft: 8 }}>{n}</div>
          ))}
          {expansion.errors.map((n, i) => (
            <div key={i} style={{ marginTop: 8, fontSize: "var(--size-label)",
                                  color: "var(--alert-caut)", lineHeight: 1.5,
                                  borderLeft: "2px solid var(--alert-caut)",
                                  paddingLeft: 8 }}>{n}</div>
          ))}
        </Section>

        <Section title="Environment" defaultOpen={false} locked={p.locked}
                 right={<span style={{ fontSize: "var(--size-label)",
                                       color: "var(--ink-mute)",
                                       fontFamily: "var(--font-num)" }}>
                   {plan.isa_deviation_c >= 0 ? "ISA+" : "ISA"}{plan.isa_deviation_c}
                   {" · "}{plan.humidity_pct}% RH
                 </span>}>
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
                    display={(plan.isa_deviation_c >= 0 ? "+" : "") + plan.isa_deviation_c}
                    onChange={(v) => set({ isa_deviation_c: v })} />
            <Slider label="Humidity" value={plan.humidity_pct}
                    min={0} max={100} step={5} unit="% RH"
                    onChange={(v) => set({ humidity_pct: v })} />
          </div>
        </Section>

        <Section title="Operating profile" defaultOpen={false} locked={p.locked}
                 right={<span style={{ fontSize: "var(--size-label)",
                                       color: "var(--ink-mute)",
                                       fontFamily: "var(--font-num)" }}>
                   {plan.airspeed_kmh} km/h
                 </span>}
                 hint={<>Cruise throttle is not a control: the flight simulator flies
                       the cruise at its own setting and takes none from the request.
                       To hold a throttle at a condition, use the conditions test in
                       the dock.</>}>
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
          </div>
        </Section>

        {p.mayInject && (
          <Section title="What if — fault on this mission" defaultOpen={false} muted
                   right={<span style={{ fontSize: "var(--size-label)",
                                         color: Array.isArray(p.injected) && p.injected.length
                                           ? "var(--alert-caut)" : "var(--ink-mute)" }}>
                     {Array.isArray(p.injected) && p.injected.length
                       ? p.injected.length + " injected" : "advanced"}
                   </span>}>
            <WhatIf injected={p.injected} onReFly={p.onReFly}
                    busy={p.busy} haveBaseline={p.haveBaseline} />
          </Section>
        )}
      </div>
    </div>
  );
}
