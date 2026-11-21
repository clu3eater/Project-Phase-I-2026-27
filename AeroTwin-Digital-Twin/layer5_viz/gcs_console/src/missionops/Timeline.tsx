/* THE SIMULATION STRIP — the one place time is shown.
 *
 * It exists only when there is a sortie. While the mission is being planned
 * there is no time to show, so the strip is not drawn at all and the band
 * underneath is the engine instruments alone; the map gets the height back.
 * That is also why the two mission-level actions are not here any more: COST
 * IT and SIMULATE moved to the command bar at the top, where they are
 * reachable in every state and do not need a strip to live on.
 *
 * Two faces:
 *
 *   SIMULATING  what the server is doing and how long it has been doing it.
 *               An elapsed count, no percentage, because the endpoint reports
 *               no progress and a bar that fills on a timer is a lie.
 *   PLAYBACK    the transport -- one clock, one scrubber, the phases to scale,
 *               every event on the second it happened -- with where the
 *               aircraft has got to written beside it, and the fault that is
 *               running, if there is one.
 *
 * There is no second timeline anywhere on the page. The map's aircraft, the
 * telemetry band, the dock's monitor and this strip are four views of
 * `Playback.t`, and only this one owns it.
 */

import { useEffect, useMemo, useRef } from "react";

import { greatCircleKm } from "../data/airbases";
import type { FlightSim, MissionScenario } from "../lib/api";
import { Playback } from "../mission/clock";
import { fmtClock, type Expansion, type MissionPlan } from "../mission/plan";
import { ghostButton } from "../mission/ui";
import { verdictColour } from "../components/TerrainMap";
import { flownLegs, type MissionIdentity } from "./mission";

export type Mode = "PLAN" | "SIMULATING" | "PLAYBACK" | "ANALYZE";

export function Timeline(props: {
  mode: Mode;
  plan: MissionPlan;
  expansion: Expansion;
  sim: FlightSim | null;
  pb: Playback;
  version: number;
  elapsed: number;
  compact: boolean;
  identity: MissionIdentity;
  scenario: MissionScenario | null;
  mayInject: boolean;
  busy: boolean;
  onOpenFault: () => void;
  onEdit: () => void;
  onResults: () => void;
  onSelectEvent: (i: number) => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)",
                  minWidth: 0, height: "100%", overflow: "hidden" }}>
      {props.mode === "SIMULATING" && (
        <Flying plan={props.plan} elapsed={props.elapsed}
                waypoints={props.expansion.waypoints.length}
                compact={props.compact} />
      )}
      {(props.mode === "PLAYBACK" || props.mode === "ANALYZE") && props.sim && (
        <Transport {...props} sim={props.sim} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * SIMULATING — it is working, and it says what it is doing
 * ------------------------------------------------------------------ */

function Flying(props: { plan: MissionPlan; elapsed: number; waypoints: number;
                         compact: boolean }) {
  return (
    <>
      <span className="ms-spin" aria-hidden="true"
            style={{ width: 20, height: 20, flex: "0 0 auto", borderRadius: 10,
                     border: "2px solid var(--line)",
                     borderTopColor: "var(--alert-advis)" }} />
      <span style={{ fontSize: 17, fontWeight: 700, letterSpacing: "0.06em",
                     color: "var(--alert-advis)", whiteSpace: "nowrap" }}>
        FLYING THE SORTIE
      </span>
      {!props.compact && (
        <span style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                       minWidth: 0, overflow: "hidden", whiteSpace: "nowrap",
                       textOverflow: "ellipsis" }}>
          {props.waypoints} waypoints through the mean-value engine model,
          take-off to landing, on {props.plan.live_engine
            ? "this engine's own wear" : "an as-new engine of the type"} — nothing
          here is a lookup, which is why it takes tens of seconds.
        </span>
      )}
      <div style={{ flex: 1, minWidth: 8 }} />
      <span style={{ fontFamily: "var(--font-num)", fontSize: 21, fontWeight: 700,
                     flex: "0 0 auto" }}>
        {props.elapsed} s
      </span>
    </>
  );
}

/* ------------------------------------------------------------------ *
 * PLAYBACK — the transport, driven by the one clock
 * ------------------------------------------------------------------ */

function Transport(props: {
  pb: Playback; version: number; sim: FlightSim; compact: boolean;
  identity: MissionIdentity;
  scenario: MissionScenario | null; mayInject: boolean;
  busy: boolean;
  onOpenFault: () => void;
  onEdit: () => void; onResults: () => void;
  onSelectEvent: (i: number) => void;
}) {
  const { pb } = props;
  const clockRef = useRef<HTMLDivElement>(null);
  const rangeRef = useRef<HTMLInputElement>(null);
  const fillRef = useRef<HTMLDivElement>(null);
  const markRef = useRef<HTMLDivElement>(null);
  const phaseRef = useRef<HTMLSpanElement>(null);
  const nextRef = useRef<HTMLSpanElement>(null);
  const legRef = useRef<HTMLSpanElement>(null);
  const etaRef = useRef<HTMLSpanElement>(null);
  const pctRef = useRef<HTMLSpanElement>(null);
  const faultRef = useRef<HTMLSpanElement>(null);

  const legs = useMemo(() => flownLegs(props.sim.samples), [props.sim]);
  const launch = useMemo(() => {
    const s = props.identity.launch_utc;
    const t = Date.parse(s.length <= 16 ? s + ":00Z" : s);
    return isFinite(t) ? t : null;
  }, [props.identity.launch_utc]);

  useEffect(() => pb.subscribe((t) => {
    const f = pb.duration > 0 ? t / pb.duration : 0;
    if (clockRef.current) {
      clockRef.current.textContent = fmtClock(t) + " / " + fmtClock(pb.duration);
    }
    if (rangeRef.current && document.activeElement !== rangeRef.current) {
      rangeRef.current.max = String(Math.max(1, Math.ceil(pb.duration)));
      rangeRef.current.value = String(t);
    }
    if (fillRef.current) fillRef.current.style.width = (f * 100).toFixed(2) + "%";
    if (markRef.current) markRef.current.style.left = (f * 100).toFixed(2) + "%";
    if (pctRef.current) pctRef.current.textContent = Math.round(f * 100) + "%";

    const s = pb.samples[pb.indexAt(t)];
    if (s && phaseRef.current) phaseRef.current.textContent = s.phase;
    let li = legs.findIndex((l) => t <= l.t1);
    if (li < 0) li = legs.length - 1;
    const leg = legs[li];
    if (legRef.current) legRef.current.textContent = (li + 1) + " / " + legs.length;
    if (nextRef.current && leg) {
      const here = pb.interpolate(t);
      const km = here
        ? greatCircleKm(here.lat, here.lon, leg.lat, leg.lon).toFixed(0) + " km"
        : "";
      nextRef.current.textContent = leg.to + (km ? "  " + km : "");
    }
    if (etaRef.current && leg) {
      etaRef.current.textContent = launch
        ? zulu(launch + leg.t1 * 1000) : "T+" + fmtClock(leg.t1);
    }
    if (faultRef.current) {
      const sc = props.scenario;
      faultRef.current.textContent = !sc ? ""
        : t >= sc.onset_s ? "ACTIVE" : "ARMED";
    }
  }), [pb, legs, launch, props.scenario]);

  /* THE SHAPE OF THE SORTIE, TAKEN FROM THE SORTIE. Consecutive samples with
   * the same phase are one band, sized by the time they actually took. */
  const bands = useMemo(() => {
    const sm = pb.samples;
    if (sm.length < 2 || pb.duration <= 0) return [];
    const out: { phase: string; t0: number; t1: number }[] = [];
    for (const q of sm) {
      const last = out[out.length - 1];
      if (last && last.phase === q.phase) last.t1 = q.t_s;
      else out.push({ phase: q.phase, t0: last ? last.t1 : 0, t1: q.t_s });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pb, props.version]);

  const atStart = pb.t < 1 && pb.samples[0]?.phase === "START";
  const done = pb.ended;

  return (
    <>
      <button onClick={() => pb.toggle()} className="ms-primary"
              aria-label={pb.playing ? "pause" : "play"}
              title={pb.playing ? "pause" : done ? "fly it again" : "play the sortie"}
              style={{ width: 46, height: 42, flex: "0 0 auto", padding: 0,
                       display: "flex", alignItems: "center",
                       justifyContent: "center", borderRadius: "var(--radius)",
                       cursor: "pointer",
                       border: "1px solid " + (atStart ? "var(--state-normal)"
                                                       : "var(--line)"),
                       background: atStart
                         ? "color-mix(in srgb, var(--state-normal) 15%, transparent)"
                         : "var(--bg-raised)",
                       color: atStart ? "var(--state-normal)" : "var(--ink)" }}>
        {pb.playing ? (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"
               aria-hidden="true"><rect x="6" y="4" width="4" height="16" rx="1" />
          <rect x="14" y="4" width="4" height="16" rx="1" /></svg>
        ) : done ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round"
               strokeLinejoin="round" aria-hidden="true">
            <path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /></svg>
        ) : (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"
               aria-hidden="true"><path d="M7 4l12 8-12 8z" /></svg>
        )}
      </button>

      <Cell k={atStart ? "start engine" : done ? "fly it again" : "elapsed"}
            wide>
        <span ref={clockRef} />
      </Cell>
      {!props.compact && <Cell k="phase"><span ref={phaseRef} /></Cell>}
      {!props.compact && <Cell k="leg"><span ref={legRef} /></Cell>}
      <Cell k="next" wide><span ref={nextRef} /></Cell>
      {!props.compact && (
        <Cell k={launch ? "eta" : "reaches"}><span ref={etaRef} /></Cell>
      )}

      {/* THE SCRUBBER GETS THE WIDTH THAT IS LEFT. On a sortie of two and a
          half hours a pixel is about eight seconds, which is fine enough to
          put the cursor on the event that matters. */}
      <div style={{ flex: 1, minWidth: 140 }}>
        <div style={{ position: "relative", height: 20, display: "flex",
                      alignItems: "center" }}>
          <div style={{ position: "absolute", left: 0, right: 0, height: 6,
                        background: "var(--bg-raised)", borderRadius: 3,
                        border: "1px solid var(--line)", overflow: "hidden" }}>
            <div ref={fillRef} className="mo-progress"
                 style={{ height: "100%", width: "0%",
                          background: "var(--alert-advis)", opacity: 0.85 }} />
          </div>
          {/* WHERE THE FAULT BEGAN, if this sortie was flown with one. Drawn
              as a band from the onset to the end rather than a pip, because
              everything after it is affected and the reader should see that
              as a region and not as a moment. */}
          {props.scenario && pb.duration > 0 && (
            <div aria-hidden="true"
                 style={{ position: "absolute", top: 1, bottom: 1,
                          left: (Math.min(1, props.scenario.onset_s
                                             / pb.duration) * 100) + "%",
                          right: 0, borderLeft: "2px solid var(--alert-caut)",
                          background: "color-mix(in srgb, var(--alert-caut) 12%, transparent)",
                          pointerEvents: "none" }} />
          )}
          {/* Where a limit was crossed, on the second it was crossed. */}
          {props.sim.events.map((ev, i) => (
            <button key={i} className="mo-pip"
                    aria-label={"event at " + fmtClock(ev.t_s)}
                    title={fmtClock(ev.t_s) + " · " + ev.message}
                    onClick={() => { pb.pause(); pb.seek(ev.t_s);
                                     props.onSelectEvent(i); }}
                    style={{ position: "absolute", top: 0, width: 3, height: 9,
                             padding: 0, border: "none", cursor: "pointer",
                             ["--mo-i" as any]: Math.min(i, 20),
                             left: (pb.duration > 0
                               ? (ev.t_s / pb.duration) * 100 : 0) + "%",
                             background: ev.severity === "WARNING"
                               ? "var(--alert-warn)" : "var(--alert-caut)" }} />
          ))}
          <input ref={rangeRef} type="range" min={0}
                 max={Math.max(1, Math.ceil(pb.duration))} step={1} defaultValue={0}
                 aria-label="time into the sortie"
                 onChange={(e) => { pb.pause(); pb.seek(Number(e.target.value)); }}
                 style={{ position: "relative", width: "100%", margin: 0,
                          accentColor: "var(--alert-advis)",
                          background: "transparent" }} />
        </div>
        {/* The phases, to scale. A sortie is mostly cruise and the bar says so. */}
        {bands.length > 1 && (
          <div className="mo-bands"
               style={{ position: "relative", display: "flex", height: 6, gap: 1,
                        borderRadius: 2, overflow: "hidden", marginTop: 2 }}>
            {bands.map((b, i) => (
              <button key={i} title={b.phase + " · " + fmtClock(b.t1 - b.t0)}
                      aria-label={"go to " + b.phase}
                      onClick={() => { pb.pause(); pb.seek(b.t0); }}
                      style={{ flexGrow: Math.max(b.t1 - b.t0, 1), flexBasis: 0,
                               minWidth: 2, border: "none", padding: 0,
                               animationDelay: (i * 26) + "ms",
                               cursor: "pointer", background: phaseFill(b.phase) }} />
            ))}
            <div ref={markRef} style={{ position: "absolute", top: -1, bottom: -1,
                                        width: 2, left: "0%",
                                        background: "var(--ref-selected)",
                                        pointerEvents: "none" }} />
          </div>
        )}
      </div>

      <span ref={pctRef} className="mo-num"
            style={{ flex: "0 0 auto", fontFamily: "var(--font-num)",
                     fontSize: 17, fontWeight: 700, minWidth: 44,
                     textAlign: "right" }} />

      {!props.compact && (
        <select defaultValue={String(pb.speed)} aria-label="playback rate"
                onChange={(e) => pb.setSpeed(Number(e.target.value))}
                title="the cruise rate; the start, take-off and landing play slower"
                style={{ ...ghostButton, flex: "0 0 auto", padding: "5px 6px" }}>
          <option value={60}>60×</option>
          <option value={300}>300×</option>
          <option value={1200}>1200×</option>
        </select>
      )}

      {/* ---- the fault, and the one that could be put in here ---------- */}
      <div style={{ display: "flex", alignItems: "center", gap: 9,
                    paddingLeft: "var(--space-3)", flex: "0 0 auto",
                    borderLeft: "1px solid var(--line)" }}>
        {props.scenario ? (
          <div style={{ display: "flex", flexDirection: "column",
                        justifyContent: "center", minWidth: 0,
                        padding: "3px 9px", borderRadius: "var(--radius)",
                        border: "1px solid var(--alert-caut)",
                        background: "color-mix(in srgb, var(--alert-caut) 10%, transparent)" }}>
            <div style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
              <span style={{ fontSize: "var(--size-label)", fontWeight: 800,
                             letterSpacing: "0.06em", whiteSpace: "nowrap",
                             color: "var(--alert-caut)" }}>
                {props.scenario.mode.replace(/_/g, " ").toUpperCase()}
              </span>
              <span ref={faultRef}
                    style={{ fontSize: "var(--size-label)", fontWeight: 700,
                             color: "var(--alert-caut)" }} />
            </div>
            {!props.compact && (
              <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                            whiteSpace: "nowrap" }}>
                T+{fmtClock(props.scenario.onset_s)} · severity{" "}
                {props.scenario.severity.toFixed(2)}
              </div>
            )}
          </div>
        ) : (
          <span style={{ fontSize: 16, fontWeight: 800, letterSpacing: "0.04em",
                         whiteSpace: "nowrap",
                         color: verdictColour(props.sim.verdict) }}>
            {props.sim.verdict.replace(/_/g, " ")}
          </span>
        )}

        {/* INJECT WHERE THE AIRCRAFT HAS GOT TO.
            The transport is sitting at a second of the sortie; that second
            becomes the onset, and the sortie is re-flown with the fault
            appearing there. Everything before it is unchanged -- same engine,
            same day, same route, a deterministic model -- so the difference
            after it is the fault and nothing else. The live engine is never
            touched; this is the simulation's own fault. */}
        {props.mayInject && (
          <button onClick={props.onOpenFault} className="ms-chip"
                  disabled={props.busy}
                  style={{ ...ghostButton, whiteSpace: "nowrap",
                           color: "var(--alert-caut)",
                           borderColor: "var(--alert-caut)" }}
                  title="re-fly this sortie with a fault appearing at this second — this simulation only">
            INJECT FAULT
          </button>
        )}
        {/* THE FAULT CARD IS WORTH MORE THAN THIS BUTTON. With one on the
            strip there is not room for both and EDIT PLAN, and RESULTS is a
            tab two inches away that is already showing. */}
        {!props.compact && !props.scenario && (
          <button onClick={props.onResults} className="ms-chip"
                  style={{ ...ghostButton, whiteSpace: "nowrap" }}
                  title="the full assessment, beside the map">
            RESULTS
          </button>
        )}
        <button onClick={props.onEdit} className="ms-chip"
                style={{ ...ghostButton, whiteSpace: "nowrap" }}
                title="unlock the plan and start a new mission from this one">
          EDIT PLAN
        </button>
      </div>
    </>
  );
}

function Cell(props: { k: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div style={{ minWidth: 0, flex: "0 0 auto",
                  maxWidth: props.wide ? 200 : 116 }}>
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    letterSpacing: "0.08em", whiteSpace: "nowrap",
                    overflow: "hidden", textOverflow: "ellipsis" }}>
        {props.k.toUpperCase()}
      </div>
      <div className="mo-num"
           style={{ fontFamily: "var(--font-num)", fontSize: 17, fontWeight: 700,
                    whiteSpace: "nowrap", overflow: "hidden",
                    textOverflow: "ellipsis" }}>
        {props.children}
      </div>
    </div>
  );
}

/* The bands are drawn in the console's own palette and nothing else: the
 * powered phases in the advisory hue, the cruise in the normal-state hue, the
 * ground phases in ink. Same mapping as the dock on MISSION SIMULATOR, which
 * is presentation rather than a threshold -- there is no second opinion about
 * a limit anywhere in here. */
function phaseFill(phase: string): string {
  const mix = (c: string, pct: number) =>
    "color-mix(in srgb, " + c + " " + pct + "%, var(--bg-raised))";
  return phase === "TAKEOFF" ? mix("var(--alert-advis)", 85)
    : phase === "CLIMB" ? mix("var(--alert-advis)", 55)
    : phase === "CRUISE" ? mix("var(--state-normal)", 55)
    : phase === "DESCENT" ? mix("var(--alert-advis)", 35)
    : mix("var(--ink-mute)", 45);
}

function zulu(ms: number): string {
  const d = new Date(ms);
  return String(d.getUTCHours()).padStart(2, "0") + ":"
    + String(d.getUTCMinutes()).padStart(2, "0") + ":"
    + String(d.getUTCSeconds()).padStart(2, "0") + "Z";
}
