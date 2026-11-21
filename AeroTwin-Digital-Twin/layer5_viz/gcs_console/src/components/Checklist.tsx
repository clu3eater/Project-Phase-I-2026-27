/* THE ELECTRONIC CHECKLIST.
 *
 * An alert says what is wrong; this says what to do about it, one step at a
 * time, the way Airbus ECAM and the Boeing ECL put the procedure on the
 * screen the moment the alert fires. It opens beside the work area, never
 * over the engine strip, so the numbers the procedure asks about stay in view
 * while it is worked (Part 4 s6.2d).
 *
 * In flight and on the ground are different procedures -- "shut down the
 * engine" is the answer on the ground and the last resort in the air -- so the
 * phase is chosen from the aircraft's state and can be changed by hand.
 */

import { type Procedure } from "../lib/checklists";
import { Button, Drawer } from "../ui/kit";
import { type Level, Status } from "../ui/status";

export function ChecklistDrawer(props: {
  procedure: Procedure;
  legend: string;
  level: Level;
  phase: "airborne" | "ground";
  onPhase: (p: "airborne" | "ground") => void;
  done: boolean[];
  onDone: (d: boolean[]) => void;
  source: string;
  onClose: () => void;
}) {
  const steps = props.procedure[props.phase];
  const done = steps.map((_, i) => !!props.done[i]);
  const n = done.filter(Boolean).length;
  const next = done.findIndex((d) => !d);
  return (
    <Drawer open title={props.procedure.title}
            sub={<Status level={props.level} text={props.legend} />}
            onClose={props.onClose}
            footer={<>
              <span className="t-mute" style={{ flex: 1, alignSelf: "center" }}>{props.source}</span>
              <Button kind="primary" onClick={props.onClose}>Close</Button>
            </>}>
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
        <div className="segmented" role="group" aria-label="Phase">
          <button type="button" aria-pressed={props.phase === "airborne"}
                  onClick={() => props.onPhase("airborne")}>In flight</button>
          <button type="button" aria-pressed={props.phase === "ground"}
                  onClick={() => props.onPhase("ground")}>On the ground</button>
        </div>
        <span className="t-dim">
          {n === steps.length ? <Status level="normal" text="Procedure complete" />
            : `${n} of ${steps.length} done`}
        </span>
      </div>
      <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {steps.map((s, i) => (
          <li key={i}>
            <label className="check" style={{ alignItems: "flex-start",
                                               background: i === next ? "var(--bg-raised)" : undefined,
                                               paddingInline: 8 }}>
              <input type="checkbox" checked={done[i]}
                     onChange={(e) => {
                       const d = [...done];
                       d[i] = e.target.checked;
                       props.onDone(d);
                     }} />
              <span style={{ display: "flex", gap: 10 }}>
                <span className="t-num t-dim" style={{ minWidth: 22 }}>{i + 1}.</span>
                <span>
                  <span style={{ fontWeight: i === next ? 700 : 600,
                                 textDecoration: done[i] ? "line-through" : undefined,
                                 color: done[i] ? "var(--ink-dim)" : "var(--ink)" }}>{s.do}</span>
                  {s.why && <span className="t-dim" style={{ display: "block", marginTop: 2 }}>{s.why}</span>}
                </span>
              </span>
            </label>
          </li>
        ))}
      </ol>
    </Drawer>
  );
}
