/* THE FAULT SURFACE — one sheet, one verb, and one architectural rule.
 *
 * THE RULE
 * --------
 * The twin lab injects into the engine that is actually running: the health
 * index falls, the remaining life falls, alerts light on every page, and they
 * stay that way until somebody clears them. That is the right behaviour for a
 * demonstration of detection and the wrong one for a planning question, which
 * has to be answerable without damaging anything.
 *
 * A fault configured here is sent WITH the sortie -- /api/mission/flight
 * carries a `scenario` -- and applied to a degradation engine the simulation
 * owns (layer4_core/flight_sim.py). The live twin is never touched. The sheet
 * says so, in those words, because an operator who has used the twin lab has
 * every reason to expect otherwise.
 *
 * WHY THERE IS ONLY ONE SHEET
 * ---------------------------
 * There were two, briefly: STAGE, opened from the plan, and INJECT, opened
 * from the transport. They differed in exactly one thing -- what the onset
 * was -- and the INJECT one took that decision away from the operator by
 * fixing it to the cursor. So a sortie that had been flown could no longer be
 * re-flown with a fault from the START without going back to the plan to find
 * the other door.
 *
 * Now the onset is a control on one sheet, opening from the transport
 * pre-selects AT CURSOR, and there is one button. What the verb means does
 * not change either way: THE SORTIE IS FLOWN AGAIN FROM THE BEGINNING with
 * the fault appearing at the chosen second. Everything before that second is
 * identical -- same engine state, same day, same route, a deterministic model
 * -- so what changes after it is the fault and nothing else.
 *
 * It is a sheet over the dock rather than a tab, because a fault is not a
 * stage of the mission: it is a property of one simulation of it.
 */

import { useEffect, useRef, useState } from "react";

import { fetchFaults, type MissionScenario } from "../lib/api";
import { Chip, Field, Slider, ghostButton } from "../mission/ui";
import { fmtClock } from "../mission/plan";

/* SENSOR DRIFT IS NOT OFFERED HERE, AND THE SHEET SAYS WHY. A drift is
 * expressed in the instrument layer of the twin's own simulator; the flight
 * model has no instruments to drift, so a sortie flown with one would come
 * back identical to the baseline and look like a finding. The server refuses
 * it too, with a reason. It is also the only mode that takes a sensor
 * channel, which is why no channel control appears on this sheet. */
const NOT_FLYABLE = new Set(["sensor_drift"]);

export interface ScenarioDraft {
  mode: string;
  severity: number;
  ramp_hours: number;
  onset_s: number;
}

export const NEW_SCENARIO: ScenarioDraft = {
  mode: "", severity: 0.7,
  /* A minute and a bit of engine time to reach full severity: fast enough to
   * see inside a sortie, slow enough to be a ramp rather than a step. */
  ramp_hours: 0.02, onset_s: 0,
};

export function FaultSheet(props: {
  draft: ScenarioDraft;
  onDraft: (d: ScenarioDraft) => void;
  /** The scenario the sortie on screen was actually flown with. */
  flown: MissionScenario | null | undefined;
  /** Seconds into the sortie the transport is sitting at, when there is one. */
  cursor_s: number | null;
  duration_s: number;
  busy: boolean;
  onFly: () => void;
  onClear: () => void;
  onClose: () => void;
  mayRun: boolean;
  /** Whether a clean run of THIS route exists to compare a faulted one to. */
  haveBaseline: boolean;
}) {
  const [modes, setModes] = useState<any[]>([]);
  useEffect(() => { fetchFaults().then(setModes).catch(() => setModes([])); }, []);

  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") props.onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [props]);

  const d = props.draft;
  const set = (patch: Partial<ScenarioDraft>) => props.onDraft({ ...d, ...patch });
  const flyable = modes.filter((m) => !NOT_FLYABLE.has(m.mode));
  const c = props.cursor_s != null && props.duration_s > 0
    ? Math.max(0, Math.round(props.cursor_s)) : null;
  /* At the very beginning the cursor IS the start, and two chips offering
     the same second is a choice that is not one. */
  const cursor = c != null && c >= 1 ? c : null;
  const atCursor = cursor != null && d.onset_s > 0
    && Math.abs(d.onset_s - cursor) < 1.5;

  return (
    <div style={{ position: "absolute", inset: 0, zIndex: 20, display: "flex",
                  flexDirection: "column", justifyContent: "flex-end" }}>
      <div className="mo-scrim" onClick={props.onClose}
           style={{ position: "absolute", inset: 0,
                    background: "color-mix(in srgb, var(--bg-void) 62%, transparent)" }} />

      <div ref={box} className="mo-sheet-panel" role="dialog"
           aria-label="mission fault"
           style={{ position: "relative", maxHeight: "100%", display: "flex",
                    flexDirection: "column", background: "var(--bg-panel)",
                    borderTop: "2px solid var(--alert-caut)" }}>

        <div style={{ display: "flex", alignItems: "center", gap: 8,
                      flex: "0 0 auto", padding: "10px var(--space-4)",
                      borderBottom: "1px solid var(--line)" }}>
          <span style={{ fontSize: "var(--size-label)", fontWeight: 800,
                         letterSpacing: "0.1em", color: "var(--alert-caut)" }}>
            MISSION FAULT
          </span>
          <button onClick={props.onClose} aria-label="close"
                  style={{ marginLeft: "auto", width: 26, height: 26, padding: 0,
                           background: "transparent", border: "none",
                           color: "var(--ink-mute)", cursor: "pointer",
                           fontSize: 19, lineHeight: 1, fontFamily: "inherit" }}>
            ×
          </button>
        </div>

        <div className="panel-body"
             style={{ flex: 1, minHeight: 0, overflowY: "auto",
                      padding: "var(--space-4)", display: "flex",
                      flexDirection: "column", gap: "var(--space-4)" }}>

          {!props.mayRun ? (
            <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                          lineHeight: 1.55 }}>
              Flying a sortie against a fault is gated on <b>run:simulation</b>,
              which this role does not hold. The mission itself is unaffected.
            </div>
          ) : (
            <>
              {/* WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT DO.
                  Two lines, because the two decisions under it -- which fault
                  and when -- have to be on screen without scrolling, and a
                  five-line paragraph pushed them off. The whole of it is on
                  the hover. */}
              <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                            lineHeight: 1.55,
                            borderLeft: "2px solid var(--alert-advis)",
                            paddingLeft: 9 }}
                   title={"The fault is applied to a degradation engine the "
                     + "simulation owns and thrown away with the sortie. The "
                     + "live engine's health, remaining life and alerts are "
                     + "not touched by it."}>
                <b>This simulation only.</b> Flown with the sortie, discarded
                with it — the live engine is untouched. To degrade the real
                twin, use the <b>INJECT FAULT</b> page.
              </div>

              {props.flown && (
                <div style={{ padding: "8px 11px", borderRadius: "var(--radius)",
                              border: "1px solid var(--alert-caut)",
                              background: "color-mix(in srgb, var(--alert-caut) 10%, transparent)" }}>
                  <div style={{ fontSize: "var(--size-label)", fontWeight: 700,
                                letterSpacing: "0.08em",
                                color: "var(--alert-caut)" }}>
                    FLOWN WITH {props.flown.mode.replace(/_/g, " ").toUpperCase()}
                  </div>
                  <div style={{ fontSize: "var(--size-label)",
                                color: "var(--ink-dim)", marginTop: 2 }}>
                    severity {props.flown.severity.toFixed(2)} · ramp{" "}
                    {(props.flown.ramp_hours * 60).toFixed(0)} min · from T+
                    {fmtClock(props.flown.onset_s)}
                  </div>
                </div>
              )}

              <Field label="Fault">
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {flyable.map((m) => (
                    <Chip key={m.mode} tone="caut" on={d.mode === m.mode}
                          title={m.description || m.label}
                          onClick={() => set({ mode: d.mode === m.mode ? "" : m.mode })}>
                      {m.label}
                    </Chip>
                  ))}
                </div>
              </Field>

              {/* WHEN IT APPEARS, DIRECTLY AFTER WHAT IT IS. A fault from the
                  first second is a different question from one that appears
                  over the target, and it is the second thing an operator
                  decides -- not the fourth, below two sliders. */}
              <Field label="Appears at">
                <div style={{ display: "flex", gap: 6, alignItems: "center",
                              flexWrap: "wrap" }}>
                  <Chip on={d.onset_s === 0} onClick={() => set({ onset_s: 0 })}
                        title="the fault is there from the moment the engine starts">
                    FROM START
                  </Chip>
                  {cursor != null && (
                    <Chip on={atCursor}
                          onClick={() => set({ onset_s: cursor })}
                          title="take the onset from where the transport is sitting">
                      AT CURSOR · T+{fmtClock(cursor)}
                    </Chip>
                  )}
                  {d.onset_s > 0 && !atCursor && (
                    <span style={{ fontFamily: "var(--font-num)",
                                   fontSize: "var(--size-label)",
                                   color: "var(--ink-dim)" }}>
                      T+{fmtClock(d.onset_s)}
                    </span>
                  )}
                </div>
              </Field>

              {d.onset_s > 0 && (
                <div style={{ fontSize: "var(--size-label)",
                              color: "var(--ink-dim)", lineHeight: 1.55,
                              marginTop: -6 }}>
                  The sortie is flown again from the beginning with the fault
                  appearing at <b style={{ fontFamily: "var(--font-num)" }}>
                  T+{fmtClock(d.onset_s)}</b>. Everything before that second is
                  unchanged, so what differs after it is the fault and nothing
                  else.
                </div>
              )}

              <Slider label="Severity" value={d.severity} min={0.2} max={0.95}
                      step={0.05} unit="" display={d.severity.toFixed(2)}
                      onChange={(v) => set({ severity: v })} />
              <Slider label="Onset ramp" value={Math.round(d.ramp_hours * 60)}
                      min={1} max={120} step={1} unit="min"
                      onChange={(v) => set({ ramp_hours: v / 60 })} />

              {/* A COMPARISON NEEDS TWO SORTIES. Said before the wait rather
                  than discovered after it. */}
              {!props.haveBaseline && (
                <div style={{ fontSize: "var(--size-label)",
                              color: "var(--ink-dim)", lineHeight: 1.5,
                              borderLeft: "2px solid var(--line)",
                              paddingLeft: 9 }}>
                  There is no clean run of this route yet, so there will be
                  nothing to compare against. Fly one first — <b>SIMULATE</b>{" "}
                  with no fault staged.
                </div>
              )}

              <div style={{ fontSize: "var(--size-label)",
                            color: "var(--ink-mute)", lineHeight: 1.5 }}>
                Sensor drift is not offered here: it is expressed in the
                instrument layer, which the flight model does not have, so the
                sortie would come back identical to the baseline. It is in the
                twin lab, where there is an instrument to watch.
              </div>
            </>
          )}
        </div>

        {props.mayRun && (
          <div style={{ display: "flex", gap: 6, flex: "0 0 auto",
                        padding: "var(--space-3) var(--space-4)",
                        borderTop: "1px solid var(--line)" }}>
            {props.flown && (
              <button onClick={props.onClear} className="ms-chip"
                      disabled={props.busy} style={{ ...ghostButton }}
                      title="fly the same sortie again with no fault">
                CLEAR
              </button>
            )}
            <button onClick={props.onFly} className="ms-chip"
                    disabled={!d.mode || props.busy}
                    style={{ ...ghostButton, flex: 1, minHeight: 42,
                             fontWeight: 700, letterSpacing: "0.06em",
                             color: d.mode ? "var(--alert-caut)"
                                           : "var(--ink-mute)",
                             borderColor: d.mode ? "var(--alert-caut)"
                                                 : "var(--line)",
                             cursor: props.busy ? "wait"
                               : d.mode ? "pointer" : "not-allowed" }}>
              {props.busy ? "FLYING…" : "FLY WITH THIS FAULT"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
