/* OPERATIONS -- the commander's home (docs/UX_REDESIGN.md section 6).
 *
 * A commander answers three questions: what can fly, what must be flown, and
 * who flies it on which aircraft. The page is those three in that order.
 *
 *   Readiness    one tile per aircraft: its status, the longest mission it
 *                may take, its health, and what it is doing.
 *   Mission board one column per stage, the way Maven lays out a targeting
 *                workflow: Planned, Approved, In progress, Debrief, Done. A
 *                mission is where its column says it is; nothing else to read.
 *   Drawers      planning and allotment open beside the board, never over the
 *                engine strip. Allotment ranks every aircraft by the twin's
 *                heuristic score (uncalibrated) FOR THIS MISSION and says why any aircraft
 *                may not be chosen, so a refusal is never a surprise.
 *
 * The rules (serviceable, released, not already allotted, inside its
 * limitations, not NO-GO) are the API's; this page shows them.
 */

import { useEffect, useState } from "react";

import { type Aircraft, type Board, type Focus, opsPost, useOpsBoard } from "../../lib/ops";
import {
  Button, ConfirmButton, Drawer, Empty, Field, Result, Workspace, utc,
} from "../../ui/kit";
import {
  Status, aircraftLevel, bandLevel, missionLevel, verdictLevel, words,
} from "../../ui/status";

import { PlanDrawer, AllotDrawer } from "./MissionPlanning";

const COLUMNS: { id: string; label: string; has: string[] }[] = [
  { id: "planned", label: "Planned", has: ["PLANNED"] },
  { id: "approved", label: "Approved", has: ["APPROVED"] },
  { id: "flying", label: "In progress", has: ["PREFLIGHT", "ENGINE_RUNNING", "AIRBORNE", "RTB", "ABORTING"] },
  { id: "debrief", label: "Debrief", has: ["AWAITING_DEBRIEF"] },
  { id: "done", label: "Done", has: ["COMPLETED", "ABORTED", "CANCELLED"] },
];
const CANCELLABLE = ["PLANNED", "APPROVED", "PREFLIGHT"];
const pct0 = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(0)} %`);

type DrawerState = null | { kind: "plan" } | { kind: "allot"; id: string; preferredTail?: string } | { kind: "mission"; id: string };

export function OperationsHome(props: { go: (ws: string) => void; focus?: Focus | null; onAircraft: (tail: string) => void }) {
  const { board, error, reload } = useOpsBoard();
  const [createdMission, setCreatedMission] = useState<any>(null);
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // A task in "Waiting on you" opens the mission it is about.
  useEffect(() => {
    if (!props.focus?.mission || !board) return;
    const m = board.missions.find((x) => x.id === props.focus?.mission);
    if (m) setDrawer({ kind: m.status === "PLANNED" ? "allot" : "mission", id: m.id });
  }, [props.focus?.n, board === null]);

  if (!board) return <Workspace title="Operations"><Empty>{error ?? "Loading the squadron board…"}</Empty></Workspace>;

  const ready = board.aircraft.filter((a) => a.status === "SERVICEABLE").length;
  const open = board.missions.filter((m) => !["COMPLETED", "CANCELLED", "ABORTED"].includes(m.status));
  const byId = (id: string) => board.missions.find((m) => m.id === id) ?? (createdMission?.id === id ? createdMission : null);
  const done = (text: string, ok = true, next: DrawerState = null) => {
    setMsg({ ok, text }); if (ok) setDrawer(next); reload();
  };

  return (
    <Workspace title="Operations"
               sub={`${board.unit} · ${ready} of ${board.aircraft.length} aircraft ready · ${open.length} mission${open.length === 1 ? "" : "s"} open`}
               actions={<Button kind="primary" onClick={() => { setMsg(null); setDrawer({ kind: "plan" }); }}>
                 Plan mission</Button>}>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <Result msg={msg} />

        <div>
          <div className="t-section" style={{ marginBottom: 10 }}>Readiness</div>
          <div style={{ display: "grid", gap: 12,
                        gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 240px), 1fr))" }}>
            {board.aircraft.map((a) => <ReadinessTile key={a.tail} a={a} onOpen={() => props.onAircraft(a.tail)} />)}
          </div>
        </div>

        <div>
          <div className="t-section" style={{ marginBottom: 10 }}>Missions</div>
          <div className="board">
            {COLUMNS.map((c) => {
              const all = board.missions.filter((m) => c.has.includes(m.status));
              const items = c.id === "done" ? all.slice(0, 6) : all;
              const more = all.length - items.length;
              return (
                <div key={c.id} className="board-col">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <span className="t-label">{c.label}</span>
                    <span className="t-num t-dim">{all.length}</span>
                  </div>
                  {items.length === 0 && <span className="t-mute">None</span>}
                  {items.map((m) => (
                    <MissionCard key={m.id} m={m} board={board}
                                 onOpen={() => { setMsg(null);
                                   setDrawer({ kind: m.status === "PLANNED" ? "allot" : "mission", id: m.id }); }} />
                  ))}
                  {more > 0 && <span className="t-mute">and {more} earlier</span>}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {drawer?.kind === "plan" && (
        <PlanDrawer board={board} onClose={() => setDrawer(null)}
                    onPlanned={(m, preferredTail) => { setCreatedMission(m); done(`${m.id} planned. Review the selected aircraft and assign an operator.`, true,
                                           { kind: "allot", id: m.id, preferredTail }); }} />
      )}
      {drawer?.kind === "allot" && byId(drawer.id) && (
        <AllotDrawer key={drawer.id} m={byId(drawer.id)} board={board} onClose={() => setDrawer(null)} onDone={done}
                     preferredTail={drawer.preferredTail}
                     cancel={<CancelMission m={byId(drawer.id)} onDone={done} />} />
      )}
      {drawer?.kind === "mission" && byId(drawer.id) && (
        <MissionDrawer m={byId(drawer.id)} board={board} onClose={() => setDrawer(null)} onDone={done}
                       onReallot={() => setDrawer({ kind: "allot", id: drawer.id })}
                       onLive={() => { setDrawer(null); props.go("live"); }} />
      )}
    </Workspace>
  );
}

// ------------------------------------------------------------------ pieces

function ReadinessTile({ a, onOpen }: { a: Aircraft; onOpen: () => void }) {
  const h = a.health ?? {};
  const lim = a.limitations ?? {};
  const doing = a.mission ? `${a.mission.id} · ${words(a.mission.status)}`
    : a.grounding.length ? a.grounding[0]
    : a.status === "SERVICEABLE" ? (a.released ? "Released, ready" : "Awaiting release")
    : words(a.status_detail);
  return (
    <div className="card" style={{ padding: "14px 16px" }}>
      <b style={{ fontSize: 20, whiteSpace: "nowrap" }}>{a.tail}</b>
      <button type="button" className="engine-details-link" onClick={onOpen}
              aria-label={`View ${a.engine_name} engine details for ${a.tail}`}>
        <span>{a.engine_name || a.engine_key}</span>
        <span className="t-dim">Engine details →</span>
      </button>
      <div style={{ marginTop: 4 }}><Status level={aircraftLevel(a.status)} text={words(a.status)} /></div>
      <div className="t-dim" style={{ marginTop: 6, minHeight: 22, overflow: "hidden",
                                       textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={doing}>
        {doing}
      </div>
      <div style={{ display: "flex", gap: 16, marginTop: 8, flexWrap: "wrap" }}>
        <span>
          <span className="t-mute">Health </span>
          {h.chi == null ? <span className="t-mute">not assessed</span>
            : bandLevel(h.band) === "normal" ? pct0(h.chi)
            : <Status level={bandLevel(h.band)} text={pct0(h.chi)} bold={false} />}
        </span>
        <span>
          <span className="t-mute">Endurance limit </span>
          {lim.max_mission_hours != null ? `${lim.max_mission_hours} h` : "not recorded"}
        </span>
      </div>
    </div>
  );
}

function MissionCard(props: { m: any; board: Board; onOpen: () => void }) {
  const { m, board } = props;
  const v = m.assessment?.verdict;
  return (
    <button className="board-card" onClick={props.onOpen}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
        <b>{m.id}</b>
        {m.priority && m.priority !== "ROUTINE" && <span className="t-label">{words(m.priority)}</span>}
      </div>
      <div style={{ marginTop: 2 }}>{m.name}</div>
      <div className="t-dim" style={{ marginTop: 4 }}>
        {m.duration_h} h · {Number(m.altitude_ft).toLocaleString()} ft
        {m.status === "PLANNED" ? ` · ${board.mission_types[m.type]?.label ?? words(m.type)}` : ""}
      </div>
      {m.area && <div className="t-dim" style={{ marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={m.area}>{m.area}</div>}
      {m.tail && <div style={{ marginTop: 4 }}>{m.tail} · {m.operator}</div>}
      {["PREFLIGHT", "ENGINE_RUNNING", "AIRBORNE", "RTB", "ABORTING"].includes(m.status) && (
        <div style={{ marginTop: 6 }}><Status level="advisory" text={words(m.status)} bold={false} /></div>
      )}
      {m.status === "APPROVED" && v && (
        <div style={{ marginTop: 6 }}>
          <Status level={verdictLevel(v)} bold={false}
                  text={`Model ${words(v).toLowerCase()}${m.assessment?.success_probability != null
                    ? ` · heuristic score ${pct0(m.assessment.success_probability)}` : ""}`} />
        </div>
      )}
      {["COMPLETED", "ABORTED", "CANCELLED"].includes(m.status) && (
        <div className="t-mute" style={{ marginTop: 4 }}>{words(m.outcome ?? m.status)}</div>
      )}
    </button>
  );
}

// ------------------------------------------------------------------ drawers

function MissionDrawer(props: { m: any; board: Board; onClose: () => void;
                                onDone: (t: string, ok?: boolean) => void;
                                onReallot: () => void; onLive: () => void }) {
  const { m, board } = props;
  const flying = ["PREFLIGHT", "ENGINE_RUNNING", "AIRBORNE", "RTB", "ABORTING"].includes(m.status);
  const v = m.assessment?.verdict;
  const t = utc;
  return (
    <Drawer open title={`${m.id} · ${m.name}`}
            sub={<Status level={missionLevel(m.status)} text={words(m.status)} />}
            onClose={props.onClose}
            footer={<>
              <Button kind="quiet" onClick={props.onClose}>Close</Button>
              {m.status === "APPROVED" && <Button onClick={props.onReallot}>Re-allot</Button>}
              {flying && <Button kind="primary" onClick={props.onLive}>Watch live</Button>}
            </>}>
      <dl className="dl">
        <dt>Task</dt><dd>{board.mission_types[m.type]?.label ?? words(m.type)}</dd>
        <dt>Endurance</dt><dd>{m.duration_h} h at {Number(m.altitude_ft).toLocaleString()} ft · {words(m.environment)}</dd>
        <dt>Priority</dt><dd>{words(m.priority)}</dd>
        {m.area && <><dt>Area / route</dt><dd>{m.area}</dd></>}
        {m.launch_utc && <><dt>Launch</dt><dd>{m.launch_utc}</dd></>}
        <dt>Planned</dt><dd>{m.created_by} · {t(m.created_utc)}</dd>
        {m.tail && <><dt>Aircraft</dt><dd>{m.tail}</dd></>}
        {m.operator && <><dt>Operator</dt><dd>{m.operator}</dd></>}
        {m.approved_by && <><dt>Approved</dt><dd>{m.approved_by} · {t(m.approved_utc)}</dd></>}
        {v && <><dt>Twin verdict</dt>
          <dd><Status level={verdictLevel(v)} text={`${words(v)}${m.assessment?.success_probability != null
            ? ` · ${pct0(m.assessment.success_probability)} heuristic score (uncalibrated)` : ""}`} /></dd></>}
        {m.launched_utc && <><dt>Launched</dt><dd>{t(m.launched_utc)}</dd></>}
        {m.landed_utc && <><dt>Landed</dt><dd>{t(m.landed_utc)}</dd></>}
        {m.engine_hours != null && <><dt>Engine hours</dt><dd>{Number(m.engine_hours).toFixed(2)} h</dd></>}
        {m.outcome && <><dt>Outcome</dt><dd>{words(m.outcome)}</dd></>}
        {m.debrief?.remarks && <><dt>Debrief</dt><dd>{m.debrief.remarks}</dd></>}
        {m.cancel_reason && <><dt>Cancelled</dt><dd>{m.cancelled_by}: {m.cancel_reason}</dd></>}
        {m.notes && <><dt>Notes</dt><dd>{m.notes}</dd></>}
      </dl>
      {CANCELLABLE.includes(m.status) && <CancelMission m={m} onDone={props.onDone} />}
    </Drawer>
  );
}

/** Cancelling needs a reason, and it is two presses, not a browser pop-up. */
function CancelMission({ m, onDone }: { m: any; onDone: (t: string, ok?: boolean) => void }) {
  const [reason, setReason] = useState("");
  return (
    <div style={{ marginTop: 8, paddingTop: 16, borderTop: "1px solid var(--line)",
                  display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="t-section">Cancel this mission</div>
      <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 220px" }}>
          <Field label="Reason">
            <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        </div>
        <ConfirmButton label="Cancel mission" confirmLabel="Confirm cancel" disabled={!reason.trim()}
                       onConfirm={async () => {
                         try {
                           await opsPost(`/api/ops/missions/${m.id}/cancel`, { reason });
                           onDone(`${m.id} cancelled.`);
                         } catch (e: any) { onDone(e.message, false); }
                       }} />
      </div>
    </div>
  );
}

