/* THE COMMAND DOCK — four questions, in the order they are asked.
 *
 *   PLAN      what the sortie IS: who it is for, where it goes, and the eight
 *             things it is made of
 *   CHECKS    whether it can be flown, with every finding carrying the thing
 *             that answered it
 *   SIMULATE  the commit point before, the elapsed count during, and the
 *             monitor after
 *   RESULTS   what came back, and what the fault did to it
 *
 * FAULT IS NOT A FIFTH TAB. It was, and that was the wrong shape: a fault is
 * not a stage of a mission, it is a property of one simulation of it. It now
 * has one surface -- FaultSheet -- opened from the SCENARIO row in PLAN before
 * the sortie, and from the transport during playback. Same controls, same
 * backend call, two verbs.
 *
 * The tab follows the state rather than waiting to be clicked: planning shows
 * PLAN, a running sortie shows SIMULATE, a landed one shows RESULTS. Clicking
 * still wins.
 *
 * THREE WIDTHS. A rail of 46 px, a working column, and a wide column for the
 * things that are really tables -- the segments and the comparison. All three
 * are real: the grid column changes and the map takes the space through its
 * own ResizeObserver.
 */

import { useLayoutEffect, useRef, useState } from "react";

import type { Envelope, FlightSim, MissionScenario, RouteCost } from "../lib/api";
import { GoNoGo, MissionTrace, Results } from "../mission/Analysis";
import { Playback } from "../mission/clock";
import type { Expansion, MissionPlan, PlanPoint } from "../mission/plan";
import { Section } from "../mission/ui";
import { Checks } from "./Checks";
import { FaultSheet, type ScenarioDraft } from "./FaultSheet";
import { Compare, SegmentTable } from "./Inspect";
import { Simulate } from "./Monitor";
import { Figures, MissionHead, StatusTiles } from "./Summary";
import { Inspector, type Sel } from "./Selection";
import { Sections } from "./Sections";
import type { Check, CheckState, Constraints, MissionIdentity,
              Segment } from "./mission";
import type { Mode } from "./Timeline";

export type Tab = "PLAN" | "CHECKS" | "SIMULATE" | "RESULTS";
export const TABS: Tab[] = ["PLAN", "CHECKS", "SIMULATE", "RESULTS"];

const TITLE: Record<Tab, string> = {
  PLAN: "what the sortie is",
  CHECKS: "whether it can be flown",
  SIMULATE: "fly it, and watch it",
  RESULTS: "what came back",
};

export function Dock(props: {
  tab: Tab; onTab: (t: Tab) => void;
  collapsed: boolean; onCollapsed: (v: boolean) => void;
  floating: boolean;

  /* PLAN */
  identity: MissionIdentity; onIdentity: (v: MissionIdentity) => void;
  plan: MissionPlan; onPlan: (p: MissionPlan) => void; expansion: Expansion;
  cost: RouteCost | null; env: Envelope | null; engine: any; snap: any;
  locked: boolean; busy: boolean;
  sel: Sel | null; onSel: (s: Sel | null) => void;
  onPatch: (id: string, q: Partial<PlanPoint>) => void;
  onReorder: (i: number, d: number) => void;
  onRemove: (id: string) => void;
  segments: Segment[];
  coldStart: boolean; onColdStart: (v: boolean) => void;

  /* CHECKS */
  checks: Check[]; constraints: Constraints;
  onConstraints: (c: Constraints) => void;
  costing: boolean; onCost: () => void; canCost: boolean;
  profile: string | null;

  /* SIMULATE */
  mode: Mode; ready: boolean; readiness: CheckState; elapsed: number;
  sim: FlightSim | null; baseline: FlightSim | null;
  pb: Playback; version: number;
  scenario: MissionScenario | null;
  draft: ScenarioDraft; onDraft: (d: ScenarioDraft) => void;
  onSimulate: () => void; onEdit: () => void;
  mayRunScenarios: boolean; haveBaseline: boolean;

  /* THE FAULT SHEET */
  faultOpen: boolean;
  /** `atCursor` pre-selects the onset from the transport's position. */
  onOpenFault: (atCursor: boolean) => void;
  onCloseFault: () => void;
  onFlyFault: () => void;
  onClearFault: () => void;
}) {
  if (props.collapsed) {
    return (
      <nav aria-label="mission panel"
           style={{ display: "flex", flexDirection: "column", alignItems: "center",
                    gap: 8, height: "100%", padding: "8px 0",
                    background: "var(--bg-panel)", border: "1px solid var(--line)",
                    borderRadius: "var(--radius)", overflow: "hidden" }}>
        <button onClick={() => props.onCollapsed(false)} className="mo-tab"
                aria-label="show the mission panel" title="show the mission panel"
                style={railBtn}>
          <Chevron dir="left" />
        </button>
        {TABS.map((t) => (
          <button key={t} className="mo-tab"
                  onClick={() => { props.onTab(t); props.onCollapsed(false); }}
                  title={TITLE[t]}
                  style={{ flex: "0 0 auto", padding: "10px 4px", cursor: "pointer",
                           writingMode: "vertical-rl", letterSpacing: "0.14em",
                           fontFamily: "var(--font-ui)",
                           fontSize: "var(--size-label)", fontWeight: 700,
                           background: props.tab === t ? "var(--bg-raised)" : "transparent",
                           border: "1px solid " + (props.tab === t ? "var(--line)"
                                                                   : "transparent"),
                           borderRadius: "var(--radius)",
                           color: props.tab === t ? "var(--ink)" : "var(--ink-mute)" }}>
            {t}
          </button>
        ))}
      </nav>
    );
  }

  return (
    <section className={props.floating ? "mo-sheet" : undefined}
             aria-label="mission panel"
             style={{ position: "relative", display: "flex",
                      flexDirection: "column", height: "100%",
                      minHeight: 0, minWidth: 0, background: "var(--bg-panel)",
                      border: "1px solid var(--line)",
                      borderRadius: "var(--radius)", overflow: "hidden",
                      /* s14: no drop shadow. A floating dock is separated by a
                         stronger edge and the tone behind it. */
                      borderColor: props.floating ? "var(--ink-mute)"
                                                  : "var(--line)" }}>

      <TabBar {...props} />

      {/* ---- PLAN ------------------------------------------------------ */}
      {props.tab === "PLAN" && (
        <div key="PLAN" className="mo-swap"
             style={{ flex: 1, minHeight: 0, display: "flex",
                      flexDirection: "column" }}>
          <MissionHead plan={props.plan} onPlan={props.onPlan}
                       identity={props.identity} onIdentity={props.onIdentity}
                       locked={props.locked} />
          {/* THE SUMMARY, UNTIL SOMETHING ON THE MAP IS SELECTED. Then the
              dock belongs to that object and the mission-level figures stand
              down -- they are not about the thing being inspected, and the
              inspector needs the height more than they do. */}
          {props.sel ? (
            <Inspector sel={props.sel} plan={props.plan}
                       expansion={props.expansion} segments={props.segments}
                       identity={props.identity} sim={props.sim} pb={props.pb}
                       locked={props.locked} onSelect={props.onSel}
                       onPatch={props.onPatch} onReorder={props.onReorder}
                       onRemove={props.onRemove} />
          ) : (
            <>
              <Figures expansion={props.expansion} />
              <StatusTiles checks={props.checks} cost={props.cost}
                           sim={props.sim} snap={props.snap}
                           onPick={() => props.onTab("CHECKS")} />
              <Sections plan={props.plan} onPlan={props.onPlan}
                        expansion={props.expansion} cost={props.cost}
                        engine={props.engine} snap={props.snap}
                        locked={props.locked}
                        /* Nothing is selected in this branch -- a selection
                           replaces this whole list with the inspector. */
                        selectedId={null}
                        onSelect={(id) => props.onSel(id ? { kind: "point", id } : null)}
                        onPatch={props.onPatch}
                        constraints={props.constraints}
                        onConstraints={props.onConstraints}
                        coldStart={props.coldStart}
                        onColdStart={props.onColdStart}
                        draftMode={props.draft.mode}
                        draftSeverity={props.draft.severity}
                        onConfigureFault={() => props.onOpenFault(false)}
                        mayRunScenarios={props.mayRunScenarios} />
            </>
          )}
        </div>
      )}

      {/* ---- CHECKS ---------------------------------------------------- */}
      {props.tab === "CHECKS" && (
        <div key="CHECKS" className="panel-body mo-swap"
             style={{ flex: 1, minHeight: 0, overflowY: "auto",
                      padding: "var(--space-3)", display: "flex",
                      flexDirection: "column", gap: "var(--space-4)" }}>
          <Checks checks={props.checks} costing={props.costing}
                  onCost={props.onCost} canCost={props.canCost}
                  constraints={props.constraints}
                  onEditConstraints={() => props.onTab("PLAN")} />
          <Section title="Standing Go / No-Go" defaultOpen={false}>
            <GoNoGo snap={props.snap} highlight={props.profile} />
          </Section>
        </div>
      )}

      {/* ---- SIMULATE --------------------------------------------------- */}
      {props.tab === "SIMULATE" && (
        <div key="SIMULATE" className="panel-body mo-swap"
             style={{ flex: 1, minHeight: 0, overflowY: "auto",
                      padding: "var(--space-4)" }}>
          <Simulate mode={props.mode} plan={props.plan}
                    expansion={props.expansion} identity={props.identity}
                    sim={props.sim} pb={props.pb} version={props.version}
                    ready={props.ready} readiness={props.readiness}
                    elapsed={props.elapsed} coldStart={props.coldStart}
                    scenario={props.scenario} draftMode={props.draft.mode}
                    draftSeverity={props.draft.severity}
                    haveBaseline={props.haveBaseline}
                    mayInject={props.mayRunScenarios} busy={props.busy}
                    onSimulate={props.onSimulate}
                    onOpenFault={() => props.onOpenFault(props.mode !== "PLAN")}
                    onSelectEvent={(i) => props.onSel({ kind: "event", i })}
                    onResults={() => props.onTab("RESULTS")} />
        </div>
      )}

      {/* ---- RESULTS ---------------------------------------------------- */}
      {props.tab === "RESULTS" && (
        <div key="RESULTS" className="panel-body mo-swap"
             style={{ flex: 1, minHeight: 0, overflowY: "auto",
                      padding: "var(--space-3)", display: "flex",
                      flexDirection: "column", gap: "var(--space-4)" }}>
          {/* THE OUTCOME FIRST. For a clean sortie that is the verdict
              block; for a faulted one it is the comparison, which carries
              the verdict itself and answers the question the fault was
              configured to ask. Compare renders nothing when there is no
              second sortie to compare against. */}
          <Compare sim={props.sim} baseline={props.baseline} />
          <Results sim={props.sim} cost={props.cost} env={props.env}
                   pb={props.pb} baseline={null} />
          {props.segments.length > 0 && (
            <SegmentTable segments={props.segments} plan={props.plan}
                          identity={props.identity}
                          selected={props.sel?.kind === "leg"
                            ? props.sel.i : null}
                          onSelect={(i) => props.onSel(
                            i == null ? null : { kind: "leg", i })} />
          )}
          {props.sim && (
            <MissionTrace pb={props.pb} sim={props.sim} engine={props.engine}
                          cost={props.cost} height={190} />
          )}
        </div>
      )}

      {props.faultOpen && (
        <FaultSheet draft={props.draft} onDraft={props.onDraft}
                    flown={props.sim?.scenario ?? null}
                    cursor_s={props.sim ? props.pb.t : null}
                    duration_s={props.pb.duration} busy={props.busy}
                    onFly={props.onFlyFault}
                    onClear={props.onClearFault}
                    onClose={props.onCloseFault}
                    mayRun={props.mayRunScenarios}
                    haveBaseline={props.haveBaseline} />
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ *
 * The tabs, with one indicator that travels
 * ------------------------------------------------------------------ */

function TabBar(props: {
  tab: Tab; onTab: (t: Tab) => void;
  onCollapsed: (v: boolean) => void;
  floating: boolean;
  sim: FlightSim | null; mode: Mode;
  scenario: MissionScenario | null;
}) {
  const bar = useRef<HTMLDivElement>(null);
  const tabs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [ind, setInd] = useState({ x: 0, w: 0 });

  /* THE INDICATOR IS MEASURED, not computed from a share of the width: the
   * tabs are sized by their words, and a quarter-width bar would sit under
   * none of them. Re-measured when the dock is resized. */
  useLayoutEffect(() => {
    const read = () => {
      const el = tabs.current[props.tab];
      const host = bar.current;
      if (!el || !host) return;
      const a = el.getBoundingClientRect(), b = host.getBoundingClientRect();
      setInd((p) => {
        const n = { x: a.left - b.left, w: a.width };
        return Math.abs(p.x - n.x) < 0.5 && Math.abs(p.w - n.w) < 0.5 ? p : n;
      });
    };
    read();
    const ro = new ResizeObserver(read);
    if (bar.current) ro.observe(bar.current);
    return () => ro.disconnect();
  }, [props.tab]);

  return (
    <div ref={bar} role="tablist" aria-label="mission panel tabs"
         style={{ position: "relative", display: "flex", alignItems: "center",
                  gap: 0, flex: "0 0 auto", padding: "5px 4px 0 4px",
                  borderBottom: "1px solid var(--line)" }}>
      {TABS.map((t) => {
        const on = props.tab === t;
        const mark = t === "RESULTS" ? !!props.sim
          : t === "SIMULATE" ? !!props.scenario : false;
        return (
          <button key={t} role="tab" aria-selected={on} className="mo-tab"
                  ref={(el) => { tabs.current[t] = el; }}
                  onClick={() => props.onTab(t)} title={TITLE[t]}
                  style={{ flex: 1, minWidth: 0, minHeight: 34, cursor: "pointer",
                           padding: "0 2px", background: "transparent",
                           border: "none", color: on ? "var(--ink)"
                                                     : "var(--ink-mute)",
                           fontFamily: "var(--font-ui)",
                           fontSize: "var(--size-label)", fontWeight: 700,
                           /* TIGHT ON PURPOSE. Four tabs share 380 px and
                              SIMULATE is the long one; at 0.06em it ran into
                              RESULTS on a floating dock, which also carries a
                              close button. The type size is the floor and
                              does not move, so the tracking does. */
                           letterSpacing: "0.02em", whiteSpace: "nowrap" }}>
            {t}
            {mark && (
              <span aria-hidden="true"
                    style={{ marginLeft: 5, width: 6, height: 6, borderRadius: 6,
                             display: "inline-block",
                             background: t === "SIMULATE" ? "var(--alert-caut)"
                                                          : "var(--alert-advis)" }} />
            )}
          </button>
        );
      })}

      {/* THE TAB ROW IS FOUR TABS AND NOTHING ELSE.
          Two chrome buttons beside them left 73 px a tab, and SIMULATE needs
          82 px at the type floor -- the words ran together. Collapsing and
          resizing moved to the handle on the dock's own edge, which had to
          become visible anyway. A floating dock has no handle, so it keeps
          the one button. */}
      {props.floating && (
        <button onClick={() => props.onCollapsed(true)} className="mo-tab"
                aria-label="hide the mission panel" title="hide the mission panel"
                style={{ ...railBtn, marginBottom: 4 }}>
          <Chevron dir="right" />
        </button>
      )}

      <div className="mo-ind" aria-hidden="true"
           style={{ position: "absolute", bottom: -1, left: 0, height: 2,
                    width: ind.w, transform: "translateX(" + ind.x + "px)",
                    background: "var(--alert-advis)" }} />
    </div>
  );
}

const railBtn: React.CSSProperties = {
  width: 30, height: 30, flex: "0 0 auto", padding: 0, display: "flex",
  alignItems: "center", justifyContent: "center", background: "transparent",
  border: "1px solid var(--line)", borderRadius: "var(--radius)",
  color: "var(--ink-dim)", cursor: "pointer",
};

function Chevron({ dir }: { dir: "left" | "right" }) {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      {dir === "left"
        ? <><path d="M14 6l-6 6 6 6" /><path d="M19 4v16" opacity="0.5" /></>
        : <><path d="M10 6l6 6-6 6" /><path d="M5 4v16" opacity="0.5" /></>}
    </svg>
  );
}
