/* THE WORKSPACE HEAD — what this mission is, what state it is in, and the two
 * things an operator does to it.
 *
 * This replaces the page's own command bar. The console it now lives in draws
 * a title row for every workspace (`ui/kit` Workspace: title, context line,
 * actions, tabs), so a second bar underneath it would have been two headers
 * for one page. What was in that bar is split between the two slots the frame
 * already has:
 *
 *   sub      the mission's identity and its state, in the console's own
 *            six-level status vocabulary (`ui/status`)
 *   actions  COST IT and SIMULATE while planning, the elapsed count while the
 *            server works, EDIT PLAN and the verdict once a sortie is locked
 *
 * THE STATE WORD IS THE CHECKS' WORD. "Ready" alone only ever meant the server
 * would accept the request. A plan that will be accepted and has a leg through
 * the ground is not ready, and a plan nobody has costed is not ready either --
 * it is unchecked, and the word says so rather than showing green.
 */

import type { FlightSim } from "../lib/api";
import { Button } from "../ui/kit";
import { Status, type Level } from "../ui/status";
import { TYPE_BY_KEY, type MissionPlan } from "../mission/plan";
import { verdictColour } from "../components/TerrainMap";
import type { CheckState, MissionIdentity } from "./mission";
import type { Mode } from "./Timeline";

/* The readiness of a PLAN in the vocabulary the rest of this console speaks.
 * Six levels, each a shape plus a colour plus a word, and an aggregate takes
 * the highest -- so a mission's state reads the same way an aircraft's or an
 * alert's does. */
export function planState(p: {
  mode: Mode; ready: boolean; readiness: CheckState; stale: boolean;
}): { level: Level; text: string; why: string } {
  if (p.mode === "SIMULATING") {
    return { level: "advisory", text: "Simulating",
             why: "the engine model is being stepped through the sortie" };
  }
  if (p.mode === "PLAYBACK" || p.mode === "ANALYZE") {
    return p.stale
      ? { level: "caution", text: "Plan changed",
          why: "the route has changed since this sortie was flown; fly it again to judge the new one" }
      : { level: "advisory",
          text: p.mode === "PLAYBACK" ? "Locked · playback" : "Locked · complete",
          why: "the plan is frozen to the sortie on screen. EDIT PLAN releases it." };
  }
  if (!p.ready) {
    return { level: "warning", text: "Not flyable",
             why: "the route cannot be sent: see the ROUTE section" };
  }
  switch (p.readiness) {
    case "FAIL":
      return { level: "warning", text: "Not ready",
               why: "a check has failed — see CHECKS" };
    case "CAUTION":
      return { level: "caution", text: "Ready · check",
               why: "the sortie can be flown, with findings — see CHECKS" };
    case "PENDING":
      return { level: "standby", text: "Unchecked",
               why: "some checks have not been evaluated yet — COST IT answers them" };
    default:
      return { level: "normal", text: "Ready",
               why: "every check that can be answered has passed" };
  }
}

/** The context line: which sortie this is, where it goes, and its state. */
export function MissionLine(props: {
  plan: MissionPlan;
  identity: MissionIdentity;
  mode: Mode; ready: boolean; readiness: CheckState; stale: boolean;
  err: string;
}) {
  const t = TYPE_BY_KEY[props.plan.type] ?? TYPE_BY_KEY.CUSTOM;
  const dep = props.plan.points.find((q) => q.kind === "DEPARTURE");
  const rec = [...props.plan.points].reverse().find((q) => q.kind === "RECOVERY");
  const st = planState(props);

  return (
    <span style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
      <span className="ellipsis">
        {props.plan.type ? t.label : "New mission"} · {dep?.name ?? "—"} → {rec?.name ?? "—"}
      </span>
      <span className="t-num t-mute">{props.identity.id}</span>
      <span title={st.why}><Status level={st.level} text={st.text} /></span>
      {props.err && (
        <span className="ellipsis" style={{ color: "var(--alert-caut)" }}
              title={props.err}>
          {props.err.slice(0, 120)}
        </span>
      )}
    </span>
  );
}

/** The primary actions, which are different in each of the three moments. */
export function Actions(props: {
  mode: Mode;
  ready: boolean;
  costing: boolean;
  busy: boolean;
  elapsed: number;
  sim: FlightSim | null;
  onCost: () => void;
  onSimulate: () => void;
  onEdit: () => void;
}) {
  if (props.mode === "SIMULATING") {
    return (
      <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span className="ms-spin" aria-hidden="true"
              style={{ width: 18, height: 18, borderRadius: 9,
                       border: "2px solid var(--line)",
                       borderTopColor: "var(--alert-advis)" }} />
        <span className="t-num" style={{ fontSize: 20, fontWeight: 700 }}>
          {props.elapsed} s
        </span>
      </span>
    );
  }

  if (props.mode === "PLAN") {
    return (
      <>
        <Button kind="secondary" onClick={props.onCost}
                disabled={!props.ready || props.busy}
                title="price the route in fuel and engine life without flying it">
          {props.costing ? "Costing…" : "Cost it"}
        </Button>
        <Button kind="primary" onClick={props.onSimulate}
                disabled={!props.ready || props.busy}
                title="fly the whole sortie through the engine model, take-off to landing">
          Simulate ▶
        </Button>
      </>
    );
  }

  /* A sortie is on screen: the verdict is the headline, and the only thing to
     do to the plan is release it. */
  return (
    <>
      {props.sim && (
        <span style={{ alignSelf: "center", fontSize: 17, fontWeight: 800,
                       letterSpacing: "0.04em", whiteSpace: "nowrap",
                       color: verdictColour(props.sim.verdict) }}>
          {props.sim.verdict.replace(/_/g, " ")}
        </span>
      )}
      <Button kind="secondary" onClick={props.onEdit}
              title="unlock the plan and start a new mission from this one">
        Edit plan
      </Button>
    </>
  );
}
