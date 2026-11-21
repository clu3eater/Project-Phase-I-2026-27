/* THE TWO TABLES.
 *
 *   Segments  the leg as an object rather than a line between two rows
 *   Compare   what the fault did, against the same sortie without it
 *
 * Both are derived in mission.ts; this file only draws them. Where a figure
 * needs the route costing or the flown sortie and neither has run, the cell
 * reads a dash and the column header says where it comes from -- an empty cell
 * that looks like a zero is the one thing worth avoiding here.
 *
 * THE MISSION IDENTITY USED TO LIVE HERE as a row of three fields. It is now
 * generated, shown in the dock header and edited behind one button
 * (Summary.tsx): a sortie should not need paperwork before it can be drawn.
 */

import type { FlightSim } from "../lib/api";
import { fmtClock, fmtMin, type MissionPlan } from "../mission/plan";
import { zuluAfter, type MissionIdentity, type Segment } from "./mission";

const TH: React.CSSProperties = {
  padding: "4px 6px", textAlign: "left", fontWeight: 500,
  fontSize: "var(--size-label)", color: "var(--ink-mute)",
  letterSpacing: "0.05em", whiteSpace: "nowrap",
};
const TD: React.CSSProperties = {
  padding: "5px 6px", fontSize: "var(--size-label)", whiteSpace: "nowrap",
};
const NUM: React.CSSProperties = {
  ...TD, fontFamily: "var(--font-num)", textAlign: "right",
};

/* ------------------------------------------------------------------ *
 * SEGMENTS
 * ------------------------------------------------------------------ */

export function SegmentTable(props: {
  segments: Segment[];
  plan: MissionPlan;
  identity: MissionIdentity;
  /** The leg selected anywhere -- the map, the inspector, or this table. */
  selected?: number | null;
  onSelect: (i: number | null) => void;
}) {
  const costed = props.segments.some((s) => s.cost);
  const open = props.selected ?? null;

  return (
    <section style={{ flex: "0 0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8,
                    marginBottom: 4 }}>
        <span style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                       letterSpacing: "0.1em" }}>SEGMENTS</span>
        <span style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)" }}>
          {props.segments.length} legs · course and time are geometry
          {costed ? ", fuel and life are costed" : "; fuel and life need a costing"}
        </span>
      </div>
      <div className="panel-body" style={{ maxHeight: 300, overflowY: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={TH}>leg</th>
              <th style={{ ...TH, textAlign: "right" }}>km</th>
              <th style={{ ...TH, textAlign: "right" }}>crs</th>
              <th style={{ ...TH, textAlign: "right" }}>ete</th>
              <th style={{ ...TH, textAlign: "right" }}>
                {props.identity.launch_utc ? "eta" : "t+"}
              </th>
            </tr>
          </thead>
          <tbody>
            {props.segments.map((s) => {
              const on = open === s.i;
              const bad = s.terrain && !s.terrain.clears;
              return (
                <>
                  {/* Selecting a row selects the LEG, everywhere: the map
                      draws it in the selection colour and the inspector in
                      PLAN opens on it. One selection, three views. */}
                  <tr key={s.i} className="ms-row"
                      onClick={() => props.onSelect(on ? null : s.i)}
                      style={{ borderTop: "1px solid var(--line)",
                               cursor: "pointer",
                               background: on ? "var(--bg-raised)" : undefined }}>
                    <td style={{ ...TD, maxWidth: 130, overflow: "hidden",
                                 textOverflow: "ellipsis",
                                 color: bad ? "var(--alert-warn)" : "var(--ink)" }}>
                      {s.from} → {s.to}
                    </td>
                    <td style={NUM}>{s.distance_km.toFixed(0)}</td>
                    <td style={NUM}>{Math.round(s.course_deg)}°</td>
                    <td style={NUM}>{fmtMin(s.ete_min)}</td>
                    <td style={NUM}>
                      {props.identity.launch_utc
                        ? zuluAfter(props.identity.launch_utc, s.cumulative_min)
                        : fmtMin(s.cumulative_min)}
                    </td>
                  </tr>
                  {on && (
                    <tr key={s.i + "-d"}>
                      <td colSpan={5} style={{ padding: "6px 8px 10px",
                                               background: "var(--bg-raised)" }}>
                        <div style={{ display: "grid", gap: "4px 12px",
                                      gridTemplateColumns: "repeat(auto-fit, minmax(128px, 1fr))",
                                      fontSize: "var(--size-label)" }}>
                          <Cell k="altitude"
                                v={Math.round(s.alt0_ft).toLocaleString() + " → "
                                   + Math.round(s.alt1_ft).toLocaleString() + " ft"} />
                          <Cell k="climb required"
                                v={Math.abs(s.required_fpm) < 1 ? "level"
                                   : Math.round(s.required_fpm).toLocaleString() + " fpm"} />
                          <Cell k="cumulative"
                                v={s.cumulative_km.toFixed(0) + " km"} />
                          <Cell k="terrain"
                                v={s.terrain
                                  ? Math.round(s.terrain.max_terrain_ft).toLocaleString()
                                    + " ft · " + Math.round(s.terrain.margin_ft).toLocaleString()
                                    + " ft margin"
                                  : "— costing"}
                                hue={bad ? "var(--alert-warn)" : undefined} />
                          <Cell k="fuel" v={s.cost ? s.cost.fuel_l.toFixed(1) + " L"
                                                   : "— costing"} />
                          <Cell k="engine life"
                                v={s.cost ? s.cost.life_hours.toFixed(3) + " h"
                                          : "— costing"} />
                          <Cell k="mean power"
                                v={s.cost ? s.cost.mean_power_kw.toFixed(1) + " kW"
                                          : "— costing"} />
                          <Cell k="mean CHT"
                                v={s.cost ? Math.round(s.cost.mean_cht_c) + " °C"
                                          : "— costing"} />
                          <Cell k="OAT" v={s.cost ? Math.round(s.cost.oat_c) + " °C"
                                                  : "— costing"} />
                          {s.cost && s.cost.wastegate_saturated_min > 0 && (
                            <Cell k="wastegate at stop"
                                  v={fmtMin(s.cost.wastegate_saturated_min)}
                                  hue="var(--alert-caut)" />
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Cell(props: { k: string; v: string; hue?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ color: "var(--ink-mute)", letterSpacing: "0.05em" }}>
        {props.k.toUpperCase()}
      </div>
      <div style={{ fontFamily: "var(--font-num)",
                    color: props.hue ?? "var(--ink)" }}>{props.v}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * COMPARE -- the faulted sortie against the clean one
 * ------------------------------------------------------------------ */

export function Compare(props: { sim: FlightSim | null; baseline: FlightSim | null }) {
  const { sim, baseline } = props;
  /* ONLY WHEN BOTH SIDES EXIST, and only when they are different runs. A
   * comparison of a sortie with itself is a column of zeroes that reads like
   * a finding. */
  if (!sim || !baseline || sim === baseline || !sim.scenario) return null;

  const rows: { k: string; a: number; b: number; unit: string; dp: number;
                worseUp: boolean }[] = [
    { k: "fuel used", a: baseline.fuel_used_l, b: sim.fuel_used_l,
      unit: "L", dp: 1, worseUp: true },
    { k: "fuel remaining", a: baseline.fuel_remaining_l, b: sim.fuel_remaining_l,
      unit: "L", dp: 1, worseUp: false },
    { k: "duration", a: baseline.duration_s / 60, b: sim.duration_s / 60,
      unit: "min", dp: 1, worseUp: true },
    { k: "top of climb", a: baseline.top_of_climb_ft, b: sim.top_of_climb_ft,
      unit: "ft", dp: 0, worseUp: false },
    { k: "ceiling today", a: baseline.ceiling_ft, b: sim.ceiling_ft,
      unit: "ft", dp: 0, worseUp: false },
  ];
  const peaks: { k: string; key: string }[] = [
    { k: "peak CHT", key: "cht_c" }, { k: "peak coolant", key: "coolant_c" },
    { k: "peak EGT", key: "egt_c" }, { k: "peak oil temp", key: "oil_temp_c" },
  ];

  const verdictChanged = baseline.verdict !== sim.verdict;

  return (
    /* flex: 0 0 auto IS LOAD-BEARING. This sits in a column flex container,
       and `overflow: hidden` makes a flex item's automatic minimum size ZERO
       -- so the panel shrank to two pixels beside a tall results block and
       disappeared, while still being in the DOM and still passing a text
       test. It may not shrink. */
    <section className="mo-rise"
             style={{ flex: "0 0 auto", border: "1px solid var(--alert-caut)",
                      borderRadius: "var(--radius)", overflow: "hidden" }}>
      <div style={{ padding: "8px 11px",
                    background: "color-mix(in srgb, var(--alert-caut) 10%, transparent)",
                    borderBottom: "1px solid var(--line)" }}>
        <div style={{ fontSize: "var(--size-label)", fontWeight: 800,
                      letterSpacing: "0.08em", color: "var(--alert-caut)" }}>
          WHAT THE FAULT DID
        </div>
        <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                      marginTop: 2, lineHeight: 1.45 }}>
          {sim.scenario.mode.replace(/_/g, " ")} at severity{" "}
          {sim.scenario.severity.toFixed(2)}, from T+
          {fmtClock(sim.scenario.onset_s)}, against the same sortie flown clean
        </div>
      </div>

      <div style={{ padding: "8px 11px" }}>
        {/* THE VERDICT, ALWAYS. This panel leads the results for a faulted
            sortie, so the outcome has to be in it -- and "unchanged" is a
            finding too: a fault that moved every temperature and still came
            back GO is the answer to the question that was asked. */}
        <div style={{ display: "flex", alignItems: "baseline", gap: 8,
                      marginBottom: 8, fontWeight: 700, flexWrap: "wrap" }}>
          <span style={{ fontSize: "var(--size-label)",
                         color: "var(--ink-mute)" }}>VERDICT</span>
          {verdictChanged ? (
            <>
              <span>{baseline.verdict.replace(/_/g, " ")}</span>
              <span style={{ color: "var(--ink-mute)" }}>→</span>
              <span style={{ color: "var(--alert-caut)" }}>
                {sim.verdict.replace(/_/g, " ")}
              </span>
            </>
          ) : (
            <>
              <span>{sim.verdict.replace(/_/g, " ")}</span>
              <span style={{ fontSize: "var(--size-label)", fontWeight: 400,
                             color: "var(--ink-mute)" }}>
                unchanged by the fault
              </span>
            </>
          )}
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={TH} />
              <th style={{ ...TH, textAlign: "right" }}>clean</th>
              <th style={{ ...TH, textAlign: "right" }}>faulted</th>
              <th style={{ ...TH, textAlign: "right" }}>Δ</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => <Row key={r.k} {...r} />)}
            {peaks.map((p) => {
              const a = baseline.peak?.[p.key], b = sim.peak?.[p.key];
              if (typeof a !== "number" || typeof b !== "number") return null;
              return <Row key={p.k} k={p.k} a={a} b={b} unit="°C" dp={1}
                          worseUp />;
            })}
          </tbody>
        </table>
        <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                      marginTop: 8, lineHeight: 1.5 }}>
          Both sorties were flown on the same engine state, the same day and the
          same route; the only difference is the fault. The live engine was not
          touched by either.
        </div>
      </div>
    </section>
  );
}

function Row(props: { k: string; a: number; b: number; unit: string; dp: number;
                      worseUp: boolean }) {
  const d = props.b - props.a;
  const moved = Math.abs(d) > Math.pow(10, -props.dp) / 2;
  const worse = props.worseUp ? d > 0 : d < 0;
  return (
    <tr style={{ borderTop: "1px solid var(--line)" }}>
      <td style={TD}>{props.k}</td>
      <td style={NUM}>{props.a.toFixed(props.dp)}</td>
      <td style={NUM}>{props.b.toFixed(props.dp)}</td>
      <td style={{ ...NUM, fontWeight: 700,
                   color: !moved ? "var(--ink-mute)"
                     : worse ? "var(--alert-caut)" : "var(--state-normal)" }}>
        {!moved ? "—" : (d > 0 ? "+" : "") + d.toFixed(props.dp)}
        <span style={{ color: "var(--ink-mute)", fontWeight: 400 }}> {props.unit}</span>
      </td>
    </tr>
  );
}
