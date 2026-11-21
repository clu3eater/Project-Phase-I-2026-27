/* CHECKS — the pre-flight readiness of THIS sortie.
 *
 * WHAT MAKES THIS DIFFERENT FROM A LIST OF GREEN TICKS
 * ----------------------------------------------------
 * Half of a pre-flight check cannot be answered from the plan. Fuel, terrain,
 * ceiling and climb all come from the route costing, which flies the physics
 * minute by minute and takes minutes to answer. A console that shows those as
 * green before anything has been asked is not reporting readiness, it is
 * reporting that nobody looked.
 *
 * So every check carries its SOURCE -- plan, costing, flight, twin -- and a
 * check whose source has not run yet reads NOT EVALUATED, with the button that
 * would evaluate it named. There is no state in this panel that means "no
 * finding and no question asked".
 *
 * THE SHAPE. One line that says whether it can be flown, then six group tiles
 * that can be taken in at a glance, then the findings themselves. An operator
 * who wants the answer reads the first line; one who wants to know WHY reads
 * down. Nothing has to be opened.
 */

import { useMemo, useState } from "react";

import { Empty, ghostButton } from "../mission/ui";
import { StatusSymbol, type Level } from "../ui/status";
import type { Check, CheckState, Constraints } from "./mission";
import { groupLead, groupState, readiness } from "./mission";

const HUE: Record<CheckState, string> = {
  PASS: "var(--state-normal)",
  CAUTION: "var(--alert-caut)",
  FAIL: "var(--alert-warn)",
  PENDING: "var(--ink-mute)",
  NA: "var(--ink-mute)",
};

const WORD: Record<CheckState, string> = {
  PASS: "OK", CAUTION: "CHECK", FAIL: "NO-GO",
  PENDING: "NOT EVALUATED", NA: "—",
};

/* THE CONSOLE'S OWN STATUS VOCABULARY, not a glyph of this panel's invention.
 *
 * s14 forbids emoji as status icons and this console answers with `ui/status`:
 * six levels, each a SHAPE plus a colour plus a word, so an aircraft, an
 * alert, a mission and a check all annunciate the same way and an aggregate
 * takes the highest. A check maps onto it exactly. */
const LEVEL: Record<CheckState, Level> = {
  PASS: "normal", CAUTION: "caution", FAIL: "warning",
  PENDING: "standby", NA: "off",
};

/* A box so the mark keeps its column whatever shape is in it. */
function Mark({ state }: { state: CheckState }) {
  return (
    <span style={{ width: 20, height: 20, flex: "0 0 auto",
                   display: "flex", alignItems: "center",
                   justifyContent: "center" }}>
      <StatusSymbol level={LEVEL[state]} size={14} />
    </span>
  );
}

const GROUPS: Check["group"][] =
  ["ROUTE", "TERRAIN", "FUEL", "PERFORMANCE", "ENGINE", "SCENARIO"];

export function Checks(props: {
  checks: Check[];
  /** Whether a costing is running, so the panel can say it is being answered. */
  costing: boolean;
  onCost: () => void;
  canCost: boolean;
  constraints: Constraints;
  onEditConstraints: () => void;
}) {
  const r = useMemo(() => readiness(props.checks), [props.checks]);
  const pending = props.checks.filter((q) => q.state === "PENDING").length;
  /* Opening a group shows its findings; the tiles alone are the overview. */
  const [open, setOpen] = useState<Check["group"] | null>(null);

  if (!props.checks.length) {
    return <Empty title="NOTHING TO CHECK YET">
      Draw a route and the checks appear as they can be answered.
    </Empty>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {/* ---- the one line that says whether this can be flown ---------- */}
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)",
                    padding: "10px 12px", borderRadius: "var(--radius)",
                    border: "1px solid " + HUE[r.state],
                    background: "color-mix(in srgb, " + HUE[r.state]
                                + " 8%, var(--bg-raised))" }}>
        <Mark state={r.state} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 800, letterSpacing: "0.06em",
                        color: HUE[r.state] }}>
            {r.state === "FAIL" ? "NOT READY"
              : r.state === "CAUTION" ? "READY WITH FINDINGS"
              : r.state === "PENDING" ? "PARTLY EVALUATED" : "READY"}
          </div>
          <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)" }}>
            {r.pass}/{r.total} checks pass
            {pending > 0 && <> · {pending} not evaluated</>}
          </div>
        </div>
        {pending > 0 && (
          <button onClick={props.onCost} className="ms-chip"
                  disabled={!props.canCost || props.costing}
                  style={{ ...ghostButton, flex: "0 0 auto", whiteSpace: "nowrap",
                           cursor: props.costing ? "wait" : "pointer" }}
                  title="prices the route and reads the ground under every leg; tens of seconds to minutes">
            {props.costing ? "EVALUATING…" : "EVALUATE"}
          </button>
        )}
      </div>

      {/* ---- the six groups, at a glance ------------------------------ */}
      <div style={{ display: "grid", gap: 1, background: "var(--line)",
                    border: "1px solid var(--line)",
                    borderRadius: "var(--radius)", overflow: "hidden",
                    gridTemplateColumns: "repeat(auto-fit, minmax(128px, 1fr))" }}>
        {GROUPS.map((g) => {
          const st = groupState(props.checks, g);
          const lead = groupLead(props.checks, g);
          if (!lead) return null;
          const on = open === g;
          return (
            <button key={g} className="mo-tile"
                    onClick={() => setOpen(on ? null : g)}
                    aria-expanded={on} title={lead.detail}
                    style={{ display: "flex", alignItems: "center", gap: 8,
                             padding: "8px 10px", minWidth: 0, cursor: "pointer",
                             textAlign: "left", border: "none",
                             fontFamily: "var(--font-ui)",
                             background: on ? "var(--bg-raised)"
                               : st === "PENDING" || st === "NA"
                                 ? "var(--bg-panel)"
                                 : "color-mix(in srgb, " + HUE[st]
                                   + " 7%, var(--bg-panel))" }}>
              <Mark state={st} />
              <span style={{ minWidth: 0 }}>
                <span style={{ display: "block", fontSize: "var(--size-label)",
                               color: "var(--ink-dim)", letterSpacing: "0.08em",
                               whiteSpace: "nowrap", overflow: "hidden",
                               textOverflow: "ellipsis" }}>
                  {g}
                </span>
                <span style={{ display: "block", fontSize: "var(--size-label)",
                               fontWeight: 700, color: HUE[st],
                               whiteSpace: "nowrap", overflow: "hidden",
                               textOverflow: "ellipsis" }}>
                  {WORD[st]}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {/* ---- the findings -------------------------------------------- */}
      {GROUPS.map((g) => {
        const rows = props.checks.filter((q) => q.group === g);
        if (!rows.length) return null;
        /* Everything, unless a tile has been picked -- then only that one. */
        if (open && open !== g) return null;
        return (
          <section key={g}>
            <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                          letterSpacing: "0.1em", marginBottom: 4 }}>
              {g}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              {rows.map((q) => (
                <div key={q.key}
                     style={{ display: "flex", gap: 9, padding: "7px 2px",
                              alignItems: "flex-start",
                              borderTop: "1px solid var(--line)" }}>
                  <Mark state={q.state} />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "baseline",
                                  gap: 8, minWidth: 0 }}>
                      <span style={{ fontWeight: 600 }}>{q.label}</span>
                      <span style={{ fontSize: "var(--size-label)",
                                     color: HUE[q.state], letterSpacing: "0.06em",
                                     fontWeight: 700 }}>
                        {WORD[q.state]}
                      </span>
                      <span style={{ marginLeft: "auto", flex: "0 0 auto",
                                     fontSize: "var(--size-label)",
                                     color: "var(--ink-mute)" }}
                            title={q.source === "plan" ? "answered from the plan itself"
                              : q.source === "costing" ? "answered by the route costing"
                              : q.source === "flight" ? "answered by the flown sortie"
                              : "answered by the live twin"}>
                        {q.source}
                      </span>
                    </div>
                    <div style={{ fontSize: "var(--size-label)",
                                  color: "var(--ink-dim)", lineHeight: 1.5 }}>
                      {q.detail}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        );
      })}

      {/* ---- what it was judged against ------------------------------- */}
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    paddingTop: "var(--space-2)",
                    borderTop: "1px solid var(--line)",
                    fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    lineHeight: 1.5 }}>
        <span style={{ minWidth: 0 }}>
          Judged against {props.constraints.min_clearance_ft.toLocaleString()} ft
          clearance, a {props.constraints.reserve_min} min reserve and{" "}
          {props.constraints.max_duration_h} h.
        </span>
        <button onClick={props.onEditConstraints} className="ms-chip"
                style={{ ...ghostButton, flex: "0 0 auto", minHeight: 28 }}
                title="the constraints are set in PLAN, where the rest of the sortie is defined">
          CONSTRAINTS
        </button>
      </div>
    </div>
  );
}
