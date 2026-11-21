/* The lower band of the Mission Simulator: what the sortie did.
 *
 * ONE CLOCK DRIVES ALL OF IT
 * --------------------------
 * The transport, the telemetry strip, the trace cursor and the aircraft on the
 * map are four views of `Playback.t`. None of them holds its own time, none of
 * them steps its own index, and dragging the scrubber to 2 h 15 m puts every
 * one of them at 2 h 15 m because there is nothing else for them to be at.
 *
 * AND ALMOST NONE OF IT RE-RENDERS
 * --------------------------------
 * Each of these subscribes to the clock and writes text or a transform. React
 * is involved when the sortie changes, when the operator presses something,
 * and not otherwise -- so playback at 1200x costs a few DOM writes a frame
 * rather than a reconciliation of the page.
 *
 * WHAT THE TRACE PLOTS, AND WHY IT IS NOT "HEALTH"
 * ------------------------------------------------
 * `FlightSim` samples carry the engine's measured channels. They do NOT carry
 * a health index, a degradation figure or a remaining life -- those are
 * products of the live twin's own pipeline running against the real engine,
 * and the flight simulator does not produce them. Drawing a health curve here
 * would mean inventing one.
 *
 * So the trace plots what the sortie actually produced: how close the engine
 * came to its certified limits, instant by instant, against the SAME
 * `critical_max` numbers out of configs/thresholds.yaml that the server judged
 * the sortie with (`flight_sim._limits`). What the mission costs in engine
 * LIFE is a real number and it comes from the route costing, where it is
 * computed -- it is reported beside the trace rather than drawn as a curve
 * nothing measured.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { FlightSim, RouteCost, Envelope, FlightSample } from "../lib/api";
import { verdictColour } from "../components/TerrainMap";
import { Playback } from "./clock";
import { fmtClock } from "./plan";
import { Empty, Stat, ghostButton } from "./ui";

/* ------------------------------------------------------------------ *
 * Transport
 * ------------------------------------------------------------------ */

/* THE TRANSPORT AND THE COMPLETION STRIP LIVE IN THE DOCK NOW
 * (mission/Dock.tsx). They were a row in a band; the band is gone, and a
 * transport that is not attached to the thing it is transporting is furniture.
 * What is left in this file is what reads the sortie rather than drives it:
 * the telemetry, the margin trace, the results and the standing assessment. */

/* ------------------------------------------------------------------ *
 * Telemetry strip
 * ------------------------------------------------------------------ */

interface CellSpec {
  k: string;
  unit: string;
  get: (s: FlightSample) => number;
  dp?: number;
  /** Returns true when this value is the problem at this instant. */
  warn?: (s: FlightSample, sim: FlightSim) => boolean;
}

const CELLS: CellSpec[] = [
  { k: "altitude", unit: "ft", get: (s) => s.altitude_ft },
  { k: "clearance", unit: "ft", get: (s) => s.clearance_ft,
    warn: (s) => s.clearance_ft < 1000 },
  { k: "power", unit: "kW", get: (s) => s.power_kw, dp: 1 },
  { k: "rpm", unit: "", get: (s) => s.rpm },
  { k: "CHT", unit: "°C", get: (s) => s.cht_c, warn: (s) => s.cht_c >= 120 },
  { k: "EGT", unit: "°C", get: (s) => s.egt_c, warn: (s) => s.egt_c >= 900 },
  { k: "coolant", unit: "°C", get: (s) => s.coolant_c, warn: (s) => s.coolant_c >= 105 },
  { k: "oil temp", unit: "°C", get: (s) => s.oil_temp_c, warn: (s) => s.oil_temp_c >= 125 },
  { k: "oil press", unit: "psi", get: (s) => s.oil_press_psi, dp: 1 },
  { k: "fuel flow", unit: "L/h", get: (s) => s.fuel_flow_lph, dp: 1 },
  { k: "fuel left", unit: "L", get: (s) => s.fuel_remaining_l, dp: 1,
    warn: (s, sim) => s.fuel_remaining_l < sim.reserve_l },
  { k: "vibration", unit: "m/s²", get: (s) => s.vibration_rms, dp: 2 },
];

export function TelemetryStrip(props: { pb: Playback; sim: FlightSim }) {
  const refs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => props.pb.subscribe((t) => {
    const s = props.pb.samples[props.pb.indexAt(t)];
    if (!s) return;
    CELLS.forEach((c, i) => {
      const el = refs.current[i];
      if (!el) return;
      const v = c.get(s);
      el.textContent = c.dp != null ? v.toFixed(c.dp) : Math.round(v).toLocaleString();
      el.style.color = c.warn?.(s, props.sim) ? "var(--alert-caut)" : "var(--ink)";
    });
  }), [props.pb, props.sim]);

  return (
    <div style={{ display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(92px, 1fr))",
                  gap: "var(--space-2) var(--space-3)" }}>
      {CELLS.map((c, i) => (
        <div key={c.k} style={{ minWidth: 0 }}>
          <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                        letterSpacing: "0.06em", whiteSpace: "nowrap" }}>
            {c.k.toUpperCase()}
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 3 }}>
            <div ref={(el) => { refs.current[i] = el; }}
                 className="ms-num"
                 style={{ fontFamily: "var(--font-num)", fontSize: 18,
                          fontWeight: 600, color: "var(--ink)" }}>—</div>
            {c.unit && (
              <span style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)" }}>
                {c.unit}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * The trace: altitude, and how close the engine came to a limit
 * ------------------------------------------------------------------ */

export interface LimitSpec { key: string; label: string; get: (s: FlightSample) => number;
                             limit: number; upper: boolean; }

/* Exported so a second view of the same sortie -- the MISSION OPS telemetry
 * band -- reads the certified limits from here rather than keeping a copy. */
export function limitsFrom(engine: any): LimitSpec[] {
  const p = engine?.parameters ?? {};
  const num = (path: any, fallback: number) =>
    typeof path === "number" && isFinite(path) ? path : fallback;
  /* THE SAME NUMBERS THE SERVER JUDGED WITH. `/api/engine` serves
   * configs/thresholds.yaml's `parameters`, which is the table
   * `flight_sim._limits` reads. A second opinion about a certified limit is a
   * defect, so there is not one here.
   *
   * ENGINE SPEED IS DELIBERATELY ABSENT. Its limit depends on the phase --
   * take-off is allowed above maximum continuous for a bounded time -- and
   * reproducing that rule here would mean maintaining a second copy of it. The
   * server's event list is the authority on rpm, and it is beside this. */
  return [
    { key: "cht_c", label: "cylinder head", get: (s) => s.cht_c,
      limit: num(p.cht?.critical_max, 135), upper: true },
    { key: "coolant_c", label: "coolant", get: (s) => s.coolant_c,
      limit: num(p.coolant_temperature?.critical_max, 120), upper: true },
    { key: "egt_c", label: "exhaust gas", get: (s) => s.egt_c,
      limit: num(p.egt?.critical_max, 950), upper: true },
    { key: "oil_temp_c", label: "oil temperature", get: (s) => s.oil_temp_c,
      limit: num(p.oil_temperature?.critical_max, 130), upper: true },
    { key: "vibration_rms", label: "vibration", get: (s) => s.vibration_rms,
      limit: num(p.vibration_rms?.critical_max, 12), upper: true },
    { key: "oil_press_psi", label: "oil pressure", get: (s) => s.oil_press_psi,
      limit: num(p.oil_pressure?.critical_min, 29), upper: false },
  ];
}

export function MissionTrace(props: {
  pb: Playback; sim: FlightSim; engine: any; cost: RouteCost | null;
  /** Plot height. The band gives it what the band has. */
  height?: number;
  /** In the band, the provenance note is one line and a title rather than a
   *  paragraph -- the paragraph is still there, on the RESULTS tab, where
   *  there is room to read it. */
  compact?: boolean;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  const H = props.height ?? 170;
  const PAD_L = 4, PAD_R = 4, PAD_T = 14, PAD_B = 20;

  const cursorRef = useRef<SVGGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() =>
      setW((p) => (Math.abs(p - el.clientWidth) < 2 ? p : el.clientWidth)));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const limits = useMemo(() => limitsFrom(props.engine), [props.engine]);

  /* One pass over the samples, once. Margin is the fraction of the way to the
   * NEAREST certified limit that the worst channel has travelled -- 1.0 is
   * untouched, 0 is at the limit, below zero is past it. */
  const series = useMemo(() => {
    const s = props.sim.samples;
    const n = s.length;
    const margin = new Float32Array(n);
    const owner = new Array<string>(n);
    const alt = new Float32Array(n);
    let maxAlt = 1;
    for (let i = 0; i < n; i++) {
      let worst = 1, who = "—";
      for (const L of limits) {
        const v = L.get(s[i]);
        if (!isFinite(v) || L.limit <= 0) continue;
        const m = L.upper ? 1 - v / L.limit : 1 - L.limit / Math.max(v, 1e-6);
        if (m < worst) { worst = m; who = L.label; }
      }
      margin[i] = Math.max(-0.25, Math.min(1, worst));
      owner[i] = who;
      alt[i] = s[i].altitude_ft;
      if (alt[i] > maxAlt) maxAlt = alt[i];
    }
    return { margin, owner, alt, maxAlt: maxAlt * 1.12 };
  }, [props.sim, limits]);

  const iw = Math.max(80, w - PAD_L - PAD_R);
  const ih = H - PAD_T - PAD_B;
  const dur = Math.max(props.sim.duration_s, 1);

  const x = (t: number) => PAD_L + (t / dur) * iw;
  const yM = (m: number) => PAD_T + (1 - (m + 0.25) / 1.25) * ih;
  const yA = (a: number) => PAD_T + (1 - a / series.maxAlt) * ih;

  const paths = useMemo(() => {
    const s = props.sim.samples;
    if (s.length < 2) return { alt: "", margin: "" };
    /* One point per horizontal pixel at most: a two-hour sortie carries a
     * thousand samples and a path with a thousand nodes in a 600 px box is a
     * thousand nodes nobody can see. */
    const stride = Math.max(1, Math.floor(s.length / Math.max(iw, 1)));
    let a = "", m = "";
    for (let i = 0; i < s.length; i += stride) {
      const px = x(s[i].t_s).toFixed(1);
      a += (i ? "L" : "M") + px + " " + yA(series.alt[i]).toFixed(1);
      m += (i ? "L" : "M") + px + " " + yM(series.margin[i]).toFixed(1);
    }
    const last = s.length - 1;
    a += "L" + x(s[last].t_s).toFixed(1) + " " + yA(series.alt[last]).toFixed(1);
    m += "L" + x(s[last].t_s).toFixed(1) + " " + yM(series.margin[last]).toFixed(1);
    return { alt: a + "L" + x(s[last].t_s).toFixed(1) + " " + (PAD_T + ih)
                    + "L" + PAD_L + " " + (PAD_T + ih) + "Z",
             margin: m };
  }, [props.sim, series, iw, ih, dur, w]);

  /* The cursor follows the clock with two DOM writes and no render. */
  const paint = (t: number) => {
    const g = cursorRef.current;
    if (g) g.setAttribute("transform", "translate(" + x(t).toFixed(1) + ",0)");
    const tip = tipRef.current;
    if (tip) {
      const i = props.pb.indexAt(t);
      const m = series.margin[i] ?? 1;
      tip.textContent = (m * 100).toFixed(0) + "% margin · "
        + (series.owner[i] ?? "—") + " is closest";
      tip.style.color = m < 0 ? "var(--alert-warn-ink)"
        : m < 0.12 ? "var(--alert-caut)" : "var(--ink-dim)";
    }
  };
  useEffect(() => props.pb.subscribe(paint));
  useLayoutEffect(() => paint(props.pb.t));

  const worst = useMemo(() => {
    let lo = 1, at = 0;
    for (let i = 0; i < series.margin.length; i++) {
      if (series.margin[i] < lo) { lo = series.margin[i]; at = i; }
    }
    return { m: lo, label: series.owner[at] ?? "—", t: props.sim.samples[at]?.t_s ?? 0 };
  }, [series, props.sim]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-3)",
                    flexWrap: props.compact ? "nowrap" : "wrap",
                    marginBottom: "var(--space-2)" }}>
        {/* In the band the panel is already titled; repeating it here costs a
            line of a box that has 180 px to spend. */}
        {!props.compact && (
          <span style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                         letterSpacing: "0.08em" }}>
            MARGIN TO THE NEAREST CERTIFIED LIMIT
          </span>
        )}
        <div ref={tipRef} style={{ fontSize: "var(--size-label)",
                                   fontFamily: "var(--font-num)",
                                   flex: props.compact ? "1 1 0" : undefined,
                                   minWidth: 0, overflow: "hidden",
                                   whiteSpace: "nowrap", textOverflow: "ellipsis" }} />
        <button style={{ ...ghostButton, marginLeft: "auto", flex: "0 0 auto",
                         whiteSpace: "nowrap" }}
                onClick={() => { props.pb.pause(); props.pb.seek(worst.t); }}
                title="go to the tightest moment of the sortie">
          WORST: {(worst.m * 100).toFixed(0)}% · {worst.label.toUpperCase()}
        </button>
      </div>

      <div ref={wrap} style={{ width: "100%" }}>
        <svg width={w} height={H} style={{ display: "block", cursor: "crosshair" }}
             onPointerDown={(e) => {
               const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
               props.pb.pause();
               props.pb.seek(((e.clientX - r.left - PAD_L) / iw) * dur);
             }}>
          <defs>
            <linearGradient id="ms-alt" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--alert-advis)" stopOpacity="0.22" />
              <stop offset="100%" stopColor="var(--alert-advis)" stopOpacity="0.02" />
            </linearGradient>
          </defs>

          {/* The limit itself, and the band an engineer starts watching in. */}
          <rect x={PAD_L} y={yM(0.12)} width={iw} height={Math.max(0, yM(-0.25) - yM(0.12))}
                fill="var(--alert-caut)" opacity={0.07} />
          <line x1={PAD_L} y1={yM(0)} x2={PAD_L + iw} y2={yM(0)}
                stroke="var(--alert-warn)" strokeWidth={1} strokeDasharray="5 5"
                opacity={0.65} />
          <text x={PAD_L + 4} y={yM(0) - 4} fontSize={12} fill="var(--alert-warn-ink)"
                opacity={0.9}>certified limit</text>

          {/* Altitude, as the ground the rest of it happened over. */}
          <path d={paths.alt} fill="url(#ms-alt)" stroke="none" />
          <path d={paths.margin} fill="none" stroke="var(--state-normal)"
                strokeWidth={1.9} strokeLinejoin="round" pathLength={1}
                key={props.sim.duration_s + ":" + props.sim.samples.length}
                className="ms-draw-fast" />

          {/* Where a limit was crossed, on the timeline it was crossed on. */}
          {props.sim.events.map((e, i) => (
            <line key={i} x1={x(e.t_s)} y1={PAD_T} x2={x(e.t_s)} y2={PAD_T + ih}
                  stroke={e.severity === "WARNING" ? "var(--alert-warn)"
                    : e.severity === "CAUTION" ? "var(--alert-caut)" : "var(--alert-advis)"}
                  strokeWidth={1} opacity={0.45} />
          ))}

          <g ref={cursorRef}>
            <line x1={0} y1={PAD_T - 6} x2={0} y2={PAD_T + ih}
                  stroke="var(--ref-selected)" strokeWidth={1.4} />
            <circle cx={0} cy={PAD_T - 8} r={3} fill="var(--ref-selected)" />
          </g>

          <line x1={PAD_L} y1={PAD_T + ih} x2={PAD_L + iw} y2={PAD_T + ih}
                stroke="var(--line)" strokeWidth={1} />
          <text x={PAD_L} y={H - 5} fontSize={12} fill="var(--ink-mute)"
                fontFamily="var(--font-num)">0:00</text>
          <text x={PAD_L + iw} y={H - 5} fontSize={12} fill="var(--ink-mute)"
                textAnchor="end" fontFamily="var(--font-num)">
            {fmtClock(props.sim.duration_s)}
          </text>
          <text x={PAD_L + iw / 2} y={H - 5} fontSize={12} fill="var(--ink-mute)"
                textAnchor="middle">
            shaded area: altitude, peak {Math.round(props.sim.top_of_climb_ft).toLocaleString()} ft
          </text>
        </svg>
      </div>

      {/* WHAT THE SORTIE COSTS IN LIFE is a real number and it is not on the
          trace, because the flight simulator does not produce one per sample.
          It comes from the route costing, which computes it. */}
      {props.compact ? (
        <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                      lineHeight: 1.45, marginTop: "var(--space-2)",
                      whiteSpace: "nowrap", overflow: "hidden",
                      textOverflow: "ellipsis" }}
             title={"Computed from the simulated channels against the same "
               + "critical_max limits in configs/thresholds.yaml the server "
               + "judged the sortie with. Engine speed is excluded: its limit "
               + "depends on the phase of flight, and the event marks carry the "
               + "finding of the server itself."}>
          {props.cost
            ? "Costs " + props.cost.life_hours.toFixed(2) + " engine-hours of life ("
              + props.cost.life_ratio.toFixed(2) + "× nominal), from the route costing."
            : "Engine-life cost: run COST IT WITHOUT FLYING IT — the flight "
              + "simulation does not produce one."}
        </div>
      ) : (
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    lineHeight: 1.55, marginTop: "var(--space-2)" }}>
        Computed here from the simulated channels against the same{" "}
        <span style={{ fontFamily: "var(--font-num)" }}>critical_max</span> limits in{" "}
        configs/thresholds.yaml the server judged the sortie with. Engine speed is
        excluded: its limit depends on the phase of flight, and the event marks
        above carry the server's own finding.{" "}
        {props.cost
          ? <>This sortie costs <b>{props.cost.life_hours.toFixed(2)} engine-hours</b>{" "}
             of life ({props.cost.life_ratio.toFixed(2)}× nominal), from the route
             costing.</>
          : <>Run <b>COST IT WITHOUT FLYING IT</b> for the engine-life figure —
             the flight simulation does not produce one.</>}
      </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Results
 * ------------------------------------------------------------------ */

export function Results(props: {
  sim: FlightSim | null; cost: RouteCost | null; env: Envelope | null;
  pb: Playback;
  /** The last clean run of THIS route, when there is one and this is not it. */
  baseline?: FlightSim | null;
}) {
  const { sim, cost, env } = props;
  if (!sim && !cost) {
    return (
      <Empty title="NOTHING IS SHOWN UNTIL THE SORTIE HAS BEEN FLOWN">
        There is no lookup table behind this. <b>SIMULATE MISSION</b> steps the
        engine model through the whole sortie, take-off to landing, and answers
        GO or NO-GO. <b>COST IT WITHOUT FLYING IT</b> prices the same route in
        fuel and engine life.
      </Empty>
    );
  }
  return (
    <div style={{ display: "grid", gap: "var(--space-5)",
                  gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
      {sim && (
        <div>
          <div className="ms-rise"
               style={{ border: "1.5px solid " + verdictColour(sim.verdict),
                        borderRadius: "var(--radius)", padding: "var(--space-3)",
                        background: "color-mix(in srgb, " + verdictColour(sim.verdict)
                                    + " 7%, transparent)" }}>
            <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: "0.04em",
                          color: verdictColour(sim.verdict) }}>
              {sim.verdict === "GO" ? "GO"
                : sim.verdict === "GO_WITH_LIMITS" ? "GO WITH LIMITS" : "NO-GO"}
            </div>
            <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                          marginTop: 2, marginBottom: "var(--space-2)" }}>
              {sim.engine_flown === "live"
                ? "this engine, worn as it is today"
                : "an as-new engine of the type"}
            </div>
            {sim.reasons.map((r, i) => (
              <div key={i} style={{ fontSize: "var(--size-label)",
                                    color: "var(--ink-dim)", lineHeight: 1.5 }}>
                • {r}
              </div>
            ))}
          </div>

          <div style={{ display: "grid", gap: "var(--space-3)",
                        gridTemplateColumns: "repeat(auto-fit, minmax(118px,1fr))",
                        marginTop: "var(--space-4)" }}>
            <Stat k="sortie" v={fmtClock(sim.duration_s)} />
            <Stat k="distance" v={Math.round(sim.distance_km).toLocaleString()} unit="km" />
            <Stat k="top of climb" v={Math.round(sim.top_of_climb_ft).toLocaleString()} unit="ft" />
            <Stat k="asked for" v={Math.round(sim.requested_altitude_ft).toLocaleString()} unit="ft" />
            <Stat k="reaches today" v={Math.round(sim.ceiling_ft).toLocaleString()} unit="ft"
                  tone={sim.requested_altitude_ft > sim.ceiling_ft
                    ? "var(--alert-caut)" : undefined} />
            <Stat k="fuel used" v={sim.fuel_used_l.toFixed(1)} unit="L" />
            <Stat k="lands with" v={sim.fuel_remaining_l.toFixed(1)} unit="L"
                  tone={sim.fuel_remaining_l < sim.reserve_l
                    ? "var(--alert-caut)" : undefined} />
            <Stat k="reserve needs" v={sim.reserve_l.toFixed(1)} unit="L" />
          </div>

          {props.baseline && <Delta now={sim} was={props.baseline} />}

          {Object.keys(sim.peak).length > 0 && (
            <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                          lineHeight: 1.55, marginTop: "var(--space-4)" }}>
              Worst of the sortie — CHT {Math.round(sim.peak.cht_c)} °C, coolant{" "}
              {Math.round(sim.peak.coolant_c)} °C, EGT {Math.round(sim.peak.egt_c)} °C,
              oil {Math.round(sim.peak.oil_temp_c)} °C,{" "}
              {Math.round(sim.peak.rpm).toLocaleString()} rpm, oil pressure down to{" "}
              {sim.peak.oil_press_psi?.toFixed(1)} psi. A limit is only called
              exceeded after it has held {sim.conditions.persistence_s ?? 60} s — the
              same persistence the live detectors use, so a transient is not a finding.
            </div>
          )}

          {sim.events.length > 0 && (
            <>
              <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                            letterSpacing: "0.08em", margin: "var(--space-4) 0 var(--space-2)" }}>
                WHAT HAPPENED, AND WHEN — CLICK ONE TO GO THERE
              </div>
              <div style={{ maxHeight: 190, overflowY: "auto" }} className="panel-body">
                {sim.events.map((e, i) => (
                  <button key={i} className="ms-event"
                          onClick={() => { props.pb.pause(); props.pb.seek(e.t_s); }}
                          style={{ display: "block", width: "100%", textAlign: "left",
                                   background: "transparent", border: "none",
                                   borderLeft: "3px solid " + (
                                     e.severity === "WARNING" ? "var(--alert-warn)"
                                     : e.severity === "CAUTION" ? "var(--alert-caut)"
                                     : "var(--alert-advis)"),
                                   padding: "5px 0 5px 10px", cursor: "pointer",
                                   color: "var(--ink-dim)", fontSize: "var(--size-label)",
                                   lineHeight: 1.45, fontFamily: "var(--font-ui)" }}>
                    <span style={{ fontFamily: "var(--font-num)", color: "var(--ink-mute)" }}>
                      {fmtClock(e.t_s)} · {e.phase.toLowerCase()} ·{" "}
                      {Math.round(e.altitude_ft).toLocaleString()} ft
                    </span>
                    <br />{e.message}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {cost && (
        <div>
          <div style={{ fontSize: 19, fontWeight: 700, marginBottom: "var(--space-3)",
                        letterSpacing: "0.03em",
                        color: cost.feasible ? "var(--state-normal)"
                                             : "var(--alert-warn-ink)" }}>
            {cost.feasible ? "WITHIN CAPABILITY" : "NOT ACHIEVABLE"}
          </div>
          <div style={{ display: "grid", gap: "var(--space-3)",
                        gridTemplateColumns: "repeat(auto-fit, minmax(128px,1fr))" }}>
            <Stat k="distance" v={Math.round(cost.distance_km).toLocaleString()} unit="km" />
            <Stat k="flight time" v={cost.hours.toFixed(2)} unit="h" />
            <Stat k="fuel required" v={cost.fuel_l.toFixed(1)} unit={"L of "
              + cost.usable_fuel_l.toFixed(0)} />
            {/* THE NUMBER NOTHING ELSE CAN PRODUCE. Not clock hours -- hours of
                LIFE, from the same wear model the fleet was generated with. */}
            <Stat k="engine life consumed" v={cost.life_hours.toFixed(2)}
                  unit={"h (" + cost.life_ratio.toFixed(2) + "× nominal)"} />
            <Stat k="limiting component" wide
                  v={cost.limiting_component.replace(/_/g, " ")}
                  unit={"at " + cost.limiting_margin.toFixed(3)} />
            {cost.terrain?.available && (
              <>
                <Stat k="highest terrain"
                      v={Math.round(cost.terrain.highest_terrain_ft ?? 0).toLocaleString()}
                      unit="ft" />
                <Stat k="route needs"
                      v={Math.round(cost.terrain.required_altitude_ft ?? 0).toLocaleString()}
                      unit="ft" />
              </>
            )}
            {env && (
              <Stat k="reach lost to wear"
                    v={env.lost_km > 0.5 ? Math.round(env.lost_km).toLocaleString() : "none"}
                    unit={env.lost_km > 0.5
                      ? "km of " + Math.round(env.radius_new_km) : "measurable yet"} />
            )}
            {(cost.wastegate_saturated_min > 0 || cost.cooling_flap_saturated_min > 0) && (
              <Stat k="no reserve in hand" wide
                    v={"wastegate " + cost.wastegate_saturated_min.toFixed(0)
                       + " min · flap " + cost.cooling_flap_saturated_min.toFixed(0) + " min"} />
            )}
          </div>

          <div style={{ marginTop: "var(--space-4)", fontSize: "var(--size-label)" }}>
            {cost.reasons.map((r, i) => (
              <div key={i} style={{ color: "var(--ink-dim)", lineHeight: 1.5 }}>• {r}</div>
            ))}
          </div>

          <div style={{ marginTop: "var(--space-5)", fontSize: "var(--size-label)",
                        color: "var(--ink-dim)", letterSpacing: "0.08em" }}>
            PER LEG
          </div>
          <div className="panel-body"
               style={{ maxHeight: 200, overflowY: "auto", marginTop: "var(--space-2)" }}>
            <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: "var(--size-label)" }}>
              <thead>
                <tr style={{ color: "var(--ink-mute)", textAlign: "right" }}>
                  <th style={{ textAlign: "left", fontWeight: 500, padding: "2px 0" }}>leg</th>
                  <th style={{ fontWeight: 500 }}>km</th><th style={{ fontWeight: 500 }}>ft</th>
                  <th style={{ fontWeight: 500 }}>L</th><th style={{ fontWeight: 500 }}>CHT</th>
                </tr>
              </thead>
              <tbody style={{ fontFamily: "var(--font-num)" }}>
                {cost.legs.map((l, i) => (
                  <tr key={i} style={{ borderTop: "1px solid var(--line)" }}>
                    <td style={{ fontFamily: "var(--font-ui)", padding: "4px 8px 4px 0",
                                 whiteSpace: "nowrap", overflow: "hidden",
                                 textOverflow: "ellipsis", maxWidth: 190 }}>
                      {l.frm} → {l.to}
                    </td>
                    <td style={{ textAlign: "right" }}>{Math.round(l.distance_km)}</td>
                    <td style={{ textAlign: "right" }}>
                      {Math.round(l.altitude_ft).toLocaleString()}</td>
                    <td style={{ textAlign: "right" }}>{l.fuel_l.toFixed(1)}</td>
                    <td style={{ textAlign: "right" }}>{Math.round(l.mean_cht_c)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ marginTop: "var(--space-4)", fontSize: "var(--size-label)",
                        color: "var(--ink-mute)", lineHeight: 1.5 }}>
            Assumes {cost.assumptions.true_airspeed_kmh} km/h true airspeed and{" "}
            {cost.assumptions.wind}. {cost.assumptions.note}
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * What the fault cost, measured against the clean run of the same route
 *
 * Both sorties were flown by the same model over the same geometry on the
 * same day; the only thing that changed is the engine, because an injected
 * fault went into the twin between them. So these differences are measured,
 * not forecast, and nothing here is scaled, interpolated or assumed.
 * ------------------------------------------------------------------ */

function Delta(props: { now: FlightSim; was: FlightSim }) {
  const rows: { k: string; now: number; was: number; unit: string; dp: number;
                good: "up" | "down" }[] = [
    { k: "reaches today", now: props.now.ceiling_ft, was: props.was.ceiling_ft,
      unit: "ft", dp: 0, good: "up" },
    { k: "fuel used", now: props.now.fuel_used_l, was: props.was.fuel_used_l,
      unit: "L", dp: 1, good: "down" },
    { k: "lands with", now: props.now.fuel_remaining_l, was: props.was.fuel_remaining_l,
      unit: "L", dp: 1, good: "up" },
    { k: "sortie", now: props.now.duration_s / 60, was: props.was.duration_s / 60,
      unit: "min", dp: 0, good: "down" },
    { k: "peak CHT", now: props.now.peak.cht_c ?? 0, was: props.was.peak.cht_c ?? 0,
      unit: "°C", dp: 0, good: "down" },
    { k: "peak coolant", now: props.now.peak.coolant_c ?? 0,
      was: props.was.peak.coolant_c ?? 0, unit: "°C", dp: 0, good: "down" },
  ];
  return (
    <div className="ms-rise"
         style={{ marginTop: "var(--space-4)", border: "1px solid var(--line)",
                  borderRadius: "var(--radius)", padding: "var(--space-3)",
                  background: "var(--bg-raised)" }}>
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                    letterSpacing: "0.08em", marginBottom: "var(--space-3)" }}>
        AGAINST THE CLEAN RUN OF THIS ROUTE
        {props.was.verdict !== props.now.verdict && (
          <span style={{ marginLeft: 10, color: verdictColour(props.now.verdict),
                         fontWeight: 700 }}>
            {props.was.verdict.replace(/_/g, " ")} → {props.now.verdict.replace(/_/g, " ")}
          </span>
        )}
      </div>
      <div style={{ display: "grid", gap: "var(--space-3)",
                    gridTemplateColumns: "repeat(auto-fit, minmax(126px,1fr))" }}>
        {rows.map((r) => {
          const d = r.now - r.was;
          const worse = r.good === "up" ? d < 0 : d > 0;
          const nil = Math.abs(d) < Math.pow(10, -r.dp) / 2;
          return (
            <Stat key={r.k} k={r.k}
                  v={(d > 0 ? "+" : d < 0 ? "−" : "") + Math.abs(d).toFixed(r.dp)}
                  unit={r.unit}
                  tone={nil ? "var(--ink-mute)"
                    : worse ? "var(--alert-caut)" : "var(--state-normal)"}
                  title={"clean " + r.was.toFixed(r.dp) + " " + r.unit
                         + " → now " + r.now.toFixed(r.dp) + " " + r.unit} />
          );
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Go / No-Go by mission profile -- the twin's own standing assessment
 * ------------------------------------------------------------------ */

const VERDICT: Record<string, string> = {
  GO: "var(--state-normal)",
  GO_WITH_LIMITS: "var(--alert-caut)",
  NO_GO: "var(--alert-warn)",
};

export function GoNoGo(props: { snap: any; highlight: string | null }) {
  const m: any = props.snap?.mission ?? {};
  const profiles: any[] = m.profiles ?? [];
  if (!profiles.length) {
    return <Empty title="NO STANDING ASSESSMENT YET">
      The twin publishes a Go / No-Go for each profile once it has been running
      long enough to have a degradation trend.
    </Empty>;
  }
  return (
    <div>
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                    marginBottom: "var(--space-3)", lineHeight: 1.5 }}>
        The engine as it is right now, against four fixed profiles — independent
        of the route drawn above. Limiting subsystem:{" "}
        <b>{m.limiting_subsystem || "—"}</b>
        {m.life_consumption_rate != null &&
          <> · life consumed {m.life_consumption_rate.toFixed(2)}× nominal</>}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        {profiles.map((p) => {
          const on = props.highlight === p.profile;
          return (
            <div key={p.profile} style={{
              display: "grid", gridTemplateColumns: "160px 128px 86px 104px 1fr",
              gap: "var(--space-3)", alignItems: "start", padding: "9px 12px",
              background: on ? "color-mix(in srgb, var(--alert-advis) 8%, var(--bg-raised))"
                             : "var(--bg-raised)",
              borderLeft: "4px solid " + (VERDICT[p.verdict] ?? "var(--line)"),
              border: on ? "1px solid var(--alert-advis)" : "1px solid transparent",
              borderLeftWidth: 4, borderRadius: "var(--radius)",
              transition: "background 180ms ease",
            }}>
              <div>
                <div style={{ fontWeight: 700 }}>{p.profile.replace(/_/g, " ")}</div>
                <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)" }}>
                  {p.duration_hours} h{on && " · this mission type"}
                </div>
              </div>
              <div style={{ color: VERDICT[p.verdict], fontWeight: 800,
                            letterSpacing: "0.05em" }}>
                {p.verdict.replace(/_/g, " ")}
              </div>
              <div style={{ fontFamily: "var(--font-num)" }}>
                {(p.success_probability * 100).toFixed(0)}%
                <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                              fontFamily: "var(--font-ui)" }}>success</div>
              </div>
              <div style={{ fontFamily: "var(--font-num)" }}>
                {p.missions_remaining != null ? p.missions_remaining.toFixed(1) : "—"}
                <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                              fontFamily: "var(--font-ui)" }}>missions left</div>
              </div>
              <div style={{ fontSize: "var(--size-label)", lineHeight: 1.5 }}>
                {/* A bare NO-GO is overridden by the first person under schedule
                    pressure. The reasons are the point. */}
                {p.reasons.map((r: string, i: number) => (
                  <div key={i} style={{ color: "var(--ink-dim)" }}>• {r}</div>
                ))}
                {p.recommendations.map((r: string, i: number) => (
                  <div key={"r" + i} style={{ color: "var(--ref-selected-ink)", marginTop: 3 }}>
                    → {r}
                  </div>
                ))}
                {p.confidence < 0.4 && (
                  <div style={{ color: "var(--alert-caut)", marginTop: 3 }}>
                    {props.snap?.rul?.source === "lstm"
                      ? "life margin from the network estimate; see its interval"
                      : "low confidence (" + (p.confidence * 100).toFixed(0) + "%)"}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
