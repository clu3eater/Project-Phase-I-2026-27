/* SIMULATE — the tab that commits the sortie, then watches it.
 *
 * It has three faces because the sortie has three moments:
 *
 *   BEFORE   what is about to be flown, stated plainly, and the one control
 *            that commits it. Nothing here is a surprise afterwards: the
 *            engine, the start, the fault and whether there is a clean run to
 *            compare against are all said before the button.
 *   DURING   how long the server has been working, and what it is doing. NO
 *            PROGRESS BAR: /api/mission/flight reports no progress and there
 *            is none to draw. A bar that fills on a timer is a lie told at
 *            exactly the moment an operator is deciding whether to wait.
 *   AFTER    where the aircraft is, what phase it is in, what is next, when it
 *            lands, how far through it is -- and the fault, if there is one,
 *            with the control that puts another one in at this second.
 *
 * Everything on the third face that changes with time is written straight to
 * the DOM from the one `Playback` subscription. Nothing in this file causes a
 * re-render per frame.
 */

import { useEffect, useMemo, useRef } from "react";

import { greatCircleKm } from "../data/airbases";
import type { FlightSim, MissionScenario } from "../lib/api";
import { Playback } from "../mission/clock";
import { fmtClock, type Expansion, type MissionPlan } from "../mission/plan";
import { Empty, ghostButton } from "../mission/ui";
import { verdictColour } from "../components/TerrainMap";
import { flownLegs, type CheckState, type MissionIdentity } from "./mission";
import type { Mode } from "./Timeline";

const HUE: Record<CheckState, string> = {
  PASS: "var(--state-normal)", CAUTION: "var(--alert-caut)",
  FAIL: "var(--alert-warn)", PENDING: "var(--ink-mute)", NA: "var(--ink-mute)",
};

export function Simulate(props: {
  mode: Mode;
  plan: MissionPlan;
  expansion: Expansion;
  identity: MissionIdentity;
  sim: FlightSim | null;
  pb: Playback;
  version: number;
  ready: boolean;
  readiness: CheckState;
  elapsed: number;
  coldStart: boolean;
  scenario: MissionScenario | null;
  draftMode: string;
  draftSeverity: number;
  haveBaseline: boolean;
  mayInject: boolean;
  busy: boolean;
  onSimulate: () => void;
  onOpenFault: () => void;
  onSelectEvent: (i: number) => void;
  onResults: () => void;
}) {
  if (props.mode === "SIMULATING") return <Working {...props} />;
  if (props.sim && (props.mode === "PLAYBACK" || props.mode === "ANALYZE")) {
    return <Watching {...props} sim={props.sim} />;
  }
  return <Before {...props} />;
}

/* ------------------------------------------------------------------ *
 * BEFORE
 * ------------------------------------------------------------------ */

function Before(props: {
  plan: MissionPlan;
  expansion: Expansion;
  ready: boolean;
  readiness: CheckState;
  coldStart: boolean;
  draftMode: string;
  draftSeverity: number;
  haveBaseline: boolean;
  busy: boolean;
  mayInject: boolean;
  onSimulate: () => void;
  onOpenFault: () => void;
}) {
  const st: CheckState = !props.ready ? "FAIL" : props.readiness;
  const word = !props.ready ? "ROUTE NOT FLYABLE"
    : st === "FAIL" ? "NOT READY"
    : st === "CAUTION" ? "READY · WITH FINDINGS"
    : st === "PENDING" ? "READY · UNCHECKED" : "READY";

  return (
    <div style={{ display: "flex", flexDirection: "column",
                  gap: "var(--space-4)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                    padding: "10px 12px", borderRadius: "var(--radius)",
                    border: "1px solid " + HUE[st],
                    background: "color-mix(in srgb, " + HUE[st]
                                + " 8%, var(--bg-raised))" }}>
        <span aria-hidden="true"
              style={{ width: 10, height: 10, borderRadius: 10, flex: "0 0 auto",
                       background: HUE[st] }} />
        <span style={{ fontWeight: 800, letterSpacing: "0.05em",
                       color: HUE[st] }}>
          {word}
        </span>
      </div>

      {/* WHAT IS ABOUT TO BE FLOWN. Four lines, and the fourth one is the
          difference between a comparison and a single sortie. */}
      <div style={{ display: "grid", gap: 2 }}>
        <Line k="route" v={props.expansion.waypoints.length
          + " waypoints, departure to recovery"} />
        <Line k="engine" v={props.plan.live_engine
          ? "this engine, worn as it is today" : "an as-new engine of the type"} />
        <Line k="start" v={props.coldStart
          ? "cold, on the starter, with a warm-up"
          : "airborne — the ground run is skipped"} />
        <Line k="fault" tone={props.draftMode ? "var(--alert-caut)" : undefined}
              v={props.draftMode
                ? props.draftMode.replace(/_/g, " ").toUpperCase()
                  + " at " + props.draftSeverity.toFixed(2)
                : "none — the sortie is flown clean"} />
        <Line k="baseline" v={props.haveBaseline
          ? "a clean run of this route is held, so a faulted one will be compared"
          : props.draftMode
            ? "none for this route — there will be nothing to compare against"
            : "this run becomes the baseline for any faulted one"} />
      </div>

      <button onClick={props.onSimulate} disabled={!props.ready || props.busy}
              className="ms-primary"
              style={{ width: "100%", minHeight: 46, cursor: props.ready
                         ? "pointer" : "not-allowed",
                       borderRadius: "var(--radius)",
                       border: "1px solid var(--alert-advis)",
                       background: "color-mix(in srgb, var(--alert-advis) 16%, transparent)",
                       color: "var(--alert-advis)", fontFamily: "var(--font-ui)",
                       fontSize: 17, fontWeight: 700, letterSpacing: "0.07em",
                       opacity: props.ready ? 1 : 0.5 }}>
        ▶  SIMULATE MISSION
      </button>

      {props.mayInject && (
        <button onClick={props.onOpenFault} className="ms-chip"
                style={{ ...ghostButton, color: "var(--alert-caut)",
                         borderColor: "var(--alert-caut)" }}>
          {props.draftMode ? "CHANGE THE FAULT" : "FLY IT AGAINST A FAULT"}
        </button>
      )}

      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    lineHeight: 1.55 }}>
        There is no lookup table behind this. The mean-value engine model is
        stepped through the whole sortie, take-off to landing, which takes tens
        of seconds — and is why the figures that come back are a sortie rather
        than an interpolation.
      </div>
    </div>
  );
}

function Line(props: { k: string; v: string; tone?: string }) {
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "baseline",
                  padding: "5px 0", borderTop: "1px solid var(--line)" }}>
      <span style={{ flex: "0 0 74px", fontSize: "var(--size-label)",
                     color: "var(--ink-mute)", letterSpacing: "0.07em" }}>
        {props.k.toUpperCase()}
      </span>
      <span style={{ flex: 1, minWidth: 0, fontSize: "var(--size-label)",
                     color: props.tone ?? "var(--ink-dim)", lineHeight: 1.5 }}>
        {props.v}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * DURING
 * ------------------------------------------------------------------ */

function Working(props: { plan: MissionPlan; expansion: Expansion;
                          elapsed: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column",
                  gap: "var(--space-4)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span className="ms-spin" aria-hidden="true"
              style={{ width: 20, height: 20, flex: "0 0 auto", borderRadius: 10,
                       border: "2px solid var(--line)",
                       borderTopColor: "var(--alert-advis)" }} />
        <span style={{ fontSize: 17, fontWeight: 700, letterSpacing: "0.06em",
                       color: "var(--alert-advis)" }}>
          FLYING THE SORTIE
        </span>
        <span style={{ marginLeft: "auto", fontFamily: "var(--font-num)",
                       fontSize: 21, fontWeight: 700 }}>
          {props.elapsed} s
        </span>
      </div>
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                    lineHeight: 1.6 }}>
        {props.expansion.waypoints.length} waypoints through the mean-value
        engine model, take-off to landing, on{" "}
        {props.plan.live_engine ? "this engine's own wear"
                                : "an as-new engine of the type"}.
      </div>
      {/* THE HONEST SENTENCE. The server reports no progress, so the console
          shows none: an elapsed count is a fact, a percentage would not be. */}
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    lineHeight: 1.55, borderLeft: "2px solid var(--line)",
                    paddingLeft: 9 }}>
        The server reports elapsed time and nothing else while it works, so
        that is what is shown. There is no percentage to draw and none is
        drawn.
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * AFTER — the monitor
 * ------------------------------------------------------------------ */

function Watching(props: {
  sim: FlightSim;
  pb: Playback;
  version: number;
  identity: MissionIdentity;
  scenario: MissionScenario | null;
  mayInject: boolean;
  busy: boolean;
  onOpenFault: () => void;
  onSelectEvent: (i: number) => void;
  onResults: () => void;
}) {
  const { pb, sim } = props;
  const legs = useMemo(() => flownLegs(sim.samples), [sim]);

  const phase = useRef<HTMLSpanElement>(null);
  const legNo = useRef<HTMLSpanElement>(null);
  const next = useRef<HTMLSpanElement>(null);
  const dist = useRef<HTMLSpanElement>(null);
  const eta = useRef<HTMLSpanElement>(null);
  const pct = useRef<HTMLSpanElement>(null);
  const fill = useRef<HTMLDivElement>(null);
  const faultRow = useRef<HTMLDivElement>(null);

  const launch = useMemo(() => {
    const t = Date.parse(props.identity.launch_utc.length <= 16
      ? props.identity.launch_utc + ":00Z" : props.identity.launch_utc);
    return isFinite(t) ? t : null;
  }, [props.identity.launch_utc]);

  useEffect(() => pb.subscribe((t) => {
    const s = pb.samples[pb.indexAt(t)];
    if (!s) return;
    let li = legs.findIndex((l) => t <= l.t1);
    if (li < 0) li = legs.length - 1;
    const leg = legs[li];
    if (phase.current) phase.current.textContent = s.phase;
    if (legNo.current) {
      legNo.current.textContent = (li + 1) + " / " + legs.length;
    }
    if (next.current) next.current.textContent = leg?.to ?? "—";
    if (dist.current && leg) {
      const here = pb.interpolate(t);
      dist.current.textContent = here
        ? greatCircleKm(here.lat, here.lon, leg.lat, leg.lon).toFixed(0) + " km"
        : "—";
    }
    if (eta.current && leg) {
      eta.current.textContent = launch
        ? zulu(launch + leg.t1 * 1000) : "T+" + fmtClock(leg.t1);
    }
    const f = pb.duration > 0 ? t / pb.duration : 0;
    if (pct.current) pct.current.textContent = Math.round(f * 100) + "%";
    if (fill.current) fill.current.style.width = (f * 100).toFixed(2) + "%";
    if (faultRow.current) {
      const on = !!props.scenario && t >= props.scenario.onset_s;
      faultRow.current.style.opacity = on ? "1" : "0.45";
    }
  }), [pb, legs, launch, props.scenario]);

  return (
    <div style={{ display: "flex", flexDirection: "column",
                  gap: "var(--space-4)" }}>

      {/* ---- where it is ---------------------------------------------- */}
      <div style={{ display: "grid", gap: "var(--space-3)",
                    gridTemplateColumns: "1fr 1fr" }}>
        <Readout k="phase"><span ref={phase} /></Readout>
        <Readout k="leg"><span ref={legNo} /></Readout>
        {/* THE WHOLE ROW: a waypoint name and the distance to it do not fit
            in half a 380 px panel, and this is the line an operator watching
            a sortie reads most. */}
        <div style={{ gridColumn: "1 / -1" }}>
          <Readout k="next">
            <span ref={next} />
            <span ref={dist} style={{ marginLeft: 8, fontSize: "var(--size-label)",
                                      color: "var(--ink-dim)" }} />
          </Readout>
        </div>
        <Readout k={launch ? "eta" : "reaches it at"}><span ref={eta} /></Readout>
      </div>

      <div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8,
                      marginBottom: 4 }}>
          <span style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                         letterSpacing: "0.08em" }}>FLOWN</span>
          <span ref={pct} className="mo-num"
                style={{ marginLeft: "auto", fontFamily: "var(--font-num)",
                         fontWeight: 700 }} />
        </div>
        <div style={{ height: 6, borderRadius: 3, background: "var(--bg-raised)",
                      border: "1px solid var(--line)", overflow: "hidden" }}>
          <div ref={fill} className="mo-progress"
               style={{ height: "100%", width: "0%",
                        background: "var(--alert-advis)", opacity: 0.85 }} />
        </div>
        <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                      marginTop: 4 }}>
          of a sortie that has already been flown — this is the transport, not
          the simulation.
        </div>
      </div>

      {/* ---- the fault ------------------------------------------------- */}
      {props.scenario ? (
        <div ref={faultRow}
             style={{ padding: "9px 11px", borderRadius: "var(--radius)",
                      border: "1px solid var(--alert-caut)",
                      background: "color-mix(in srgb, var(--alert-caut) 10%, transparent)",
                      transition: "opacity 200ms ease" }}>
          <div style={{ fontSize: "var(--size-label)", fontWeight: 800,
                        letterSpacing: "0.07em", color: "var(--alert-caut)" }}>
            {props.scenario.mode.replace(/_/g, " ").toUpperCase()} ACTIVE
          </div>
          <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                        marginTop: 2 }}>
            injected T+{fmtClock(props.scenario.onset_s)} · severity{" "}
            {props.scenario.severity.toFixed(2)} · this simulation only
          </div>
        </div>
      ) : (
        <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                      lineHeight: 1.5 }}>
          Flown clean — no fault on this sortie.
        </div>
      )}

      {props.mayInject && (
        <button onClick={props.onOpenFault}
                className="ms-chip" disabled={props.busy}
                style={{ ...ghostButton, minHeight: 40,
                         color: "var(--alert-caut)",
                         borderColor: "var(--alert-caut)" }}
                title="re-fly this sortie with a fault appearing at the second the transport is sitting at — this simulation only">
          INJECT FAULT AT THIS POINT
        </button>
      )}

      {/* ---- what happened -------------------------------------------- */}
      <div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8,
                      marginBottom: 4 }}>
          <span style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                         letterSpacing: "0.1em" }}>EVENTS</span>
          <span style={{ fontSize: "var(--size-label)",
                         color: "var(--ink-mute)" }}>
            {sim.events.length || "none"}
          </span>
          <span style={{ marginLeft: "auto", fontSize: 16, fontWeight: 800,
                         letterSpacing: "0.04em",
                         color: verdictColour(sim.verdict) }}>
            {sim.verdict.replace(/_/g, " ")}
          </span>
        </div>
        {sim.events.length === 0 ? (
          <Empty title="NOTHING WAS RAISED">
            No limit was crossed and no advisory was issued on this sortie.
          </Empty>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            {sim.events.map((e, i) => (
              <button key={i} className="ms-event"
                      onClick={() => props.onSelectEvent(i)}
                      style={{ display: "flex", gap: 9, alignItems: "baseline",
                               width: "100%", textAlign: "left", padding: "6px 4px",
                               background: "transparent", border: "none",
                               borderTop: "1px solid var(--line)",
                               cursor: "pointer", color: "var(--ink-dim)",
                               fontFamily: "var(--font-ui)",
                               fontSize: "var(--size-label)" }}>
                <span style={{ fontFamily: "var(--font-num)", flex: "0 0 auto",
                               color: "var(--ink-mute)" }}>
                  {fmtClock(e.t_s)}
                </span>
                <span style={{ flex: "0 0 auto", fontWeight: 700,
                               color: e.severity === "WARNING"
                                 ? "var(--alert-warn-ink)"
                                 : e.severity === "CAUTION"
                                   ? "var(--alert-caut)" : "var(--alert-advis)" }}>
                  {e.severity[0]}
                </span>
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {e.message}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      <button onClick={props.onResults} className="ms-chip"
              style={{ ...ghostButton }}>
        THE FULL ASSESSMENT →
      </button>
    </div>
  );
}

function Readout(props: { k: string; children: React.ReactNode }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    letterSpacing: "0.08em", whiteSpace: "nowrap" }}>
        {props.k.toUpperCase()}
      </div>
      <div className="mo-num"
           style={{ fontFamily: "var(--font-num)", fontSize: 18, fontWeight: 700,
                    whiteSpace: "nowrap", overflow: "hidden",
                    textOverflow: "ellipsis" }}>
        {props.children}
      </div>
    </div>
  );
}

function zulu(ms: number): string {
  const d = new Date(ms);
  return String(d.getUTCHours()).padStart(2, "0") + ":"
    + String(d.getUTCMinutes()).padStart(2, "0") + ":"
    + String(d.getUTCSeconds()).padStart(2, "0") + "Z";
}
