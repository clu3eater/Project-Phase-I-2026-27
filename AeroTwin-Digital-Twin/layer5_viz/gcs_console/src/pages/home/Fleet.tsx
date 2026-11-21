/* FLEET -- the maintainer's home, and the commander's view of the aircraft
 * (docs/UX_REDESIGN.md section 6).
 *
 * Master and detail. On the left, every aircraft ordered by what it needs,
 * each with the one next thing to do. On the right, the chosen aircraft's
 * technical log, in four tabs: Status, Defects, Work, Logbook. The primary
 * button is whatever that aircraft needs next, so a maintainer never has to
 * work out which of six buttons applies.
 *
 * The commander sees the same log read-only, with the one fleet decision that
 * is theirs: an engine change.
 */

import { useEffect, useMemo, useState } from "react";

import { type Aircraft, type Focus, ACTION_NAMES, opsGet, opsPost, useOpsBoard } from "../../lib/ops";
import {
  Button, Callout, ConfirmButton, Drawer, Empty, Field, Result, Section, Workspace, utc,
} from "../../ui/kit";
import {
  StatusSymbol, Status, aircraftLevel, severityLevel, words,
} from "../../ui/status";
import { FleetStatusDashboard } from "./FleetStatusDashboard";

type Mode = "maintain" | "command";
const RANK: Record<string, number> = {
  UNSERVICEABLE: 0, "AWAITING INSPECTION": 1, "GROUND RUN": 2, "ENGINE RUNNING": 2,
  FLYING: 2, "ON GCS": 3, SERVICEABLE: 4,
};

/** The one thing this aircraft needs next, in words. */
function nextFor(a: Aircraft, interval: number): string {
  const open = a.open_defects.filter((d: any) => d.status === "OPEN" || d.status === "CONFIRMED");
  const grounding = open.filter((d: any) => d.grounding);
  if (["FLYING", "ENGINE RUNNING", "GROUND RUN"].includes(a.status)) return words(a.status_detail);
  if (grounding.length) return `Rectify ${grounding.length === 1 ? `defect #${grounding[0].id}` : `${grounding.length} grounding defects`}`;
  if (a.grounding.some((g) => g.includes("inspection due"))) return `${interval} h inspection due`;
  if (a.grounding.some((g) => g.includes("TBO"))) return "Engine overhaul due";
  if (a.grounding.length) return a.grounding[0];
  if (!a.released) return "Inspect and sign release";
  if (open.length) return `${open.length} open defect${open.length > 1 ? "s" : ""}, not grounding`;
  if (a.mission) return `${a.mission.id} ${words(a.mission.status)}`;
  return "Ready";
}

export function FleetHome({ mode, focus }: { mode: Mode; focus?: Focus | null }) {
  const { board, error, reload } = useOpsBoard();
  const [sel, setSel] = useState<string | null>(focus?.tail ?? null);
  const [tab, setTab] = useState("status");
  // A task in "Waiting on you" opens the aircraft it is about.
  useEffect(() => { if (focus?.tail) { setSel(focus.tail); setTab("status"); } }, [focus?.n]);
  const [detail, setDetail] = useState<any>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [drawer, setDrawer] = useState<null | { kind: string; defect?: any }>(null);

  const list = useMemo(() => [...(board?.aircraft ?? [])].sort(
    (a, b) => (RANK[a.status] ?? 5) - (RANK[b.status] ?? 5)), [board]);
  const tail = sel ?? list[0]?.tail ?? null;
  // The aircraft first shown is HELD, not re-derived from the sort. Signing a
  // release moves that aircraft down the list, and the page used to follow the
  // new top of the list -- swapping to the next aircraft under the maintainer's
  // cursor, with "Sign release" in the same place, so the next click signed an
  // aircraft nobody had chosen. Only a click on the list changes the aircraft.
  useEffect(() => { if (sel === null && list[0]) setSel(list[0].tail); }, [sel, list]);

  useEffect(() => {
    if (!tail) return;
    let live = true;
    const load = () => opsGet(`/api/ops/aircraft/${tail}`)
      .then((d) => { if (live) setDetail(d); }).catch(() => undefined);
    load();
    const id = window.setInterval(load, 2500);
    return () => { live = false; window.clearInterval(id); };
  }, [tail]);

  if (!board) return <Workspace title="Fleet"><Empty>{error ?? "Loading the squadron board…"}</Empty></Workspace>;

  const a = detail && detail.tail === tail ? detail : null;
  const interval = board.inspection_interval_h;
  const refresh = async () => { reload(); if (tail) setDetail(await opsGet(`/api/ops/aircraft/${tail}`)); };
  const act = async (fn: () => Promise<any>, ok: string) => {
    try { await fn(); setMsg({ ok: true, text: ok }); setDrawer(null); await refresh(); }
    catch (e: any) { setMsg({ ok: false, text: e.message }); }
  };
  const running = a && ["FLYING", "ENGINE RUNNING", "GROUND RUN"].includes(a.status);
  const openDefects = a ? a.defects.filter((d: any) => d.status !== "CLOSED") : [];
  const ready = list.filter((x) => x.status === "SERVICEABLE").length;

  // The primary action is what this aircraft needs next (maintainer only).
  let primary: React.ReactNode = null;
  if (a && mode === "maintain" && !running) {
    const g = openDefects.find((d: any) => d.grounding && d.status !== "DEFERRED");
    if (g) {
      primary = <Button kind="primary" onClick={() => setDrawer({ kind: "rectify", defect: g })}>
        Rectify defect #{g.id}</Button>;
    } else if (a.grounding.some((x: string) => x.includes("inspection due"))) {
      primary = <ConfirmButton kind="primary" label={`Record ${interval} h inspection`}
                               onConfirm={() => act(() => opsPost(`/api/ops/aircraft/${a.tail}/maintenance`,
                                 { action_id: "A1", note: `${interval} h inspection with oil change` }),
                                 `${interval} h inspection recorded on ${a.tail}.`)} />;
    } else if (!a.released && a.grounding.length === 0) {
      primary = <Button kind="primary" onClick={() => setDrawer({ kind: "release" })}>Sign release</Button>;
    }
  }

  return (
    <Workspace title="Fleet"
               sub={`${board.unit} · ${ready} of ${list.length} aircraft ready to fly`}>
      <div className="fleet-master-detail" style={{ display: "grid", gap: 16,
                    alignItems: "start", width: "100%" }}>
        <div className="card-flat" style={{ padding: 0, overflow: "hidden" }}>
          {list.map((x) => (
            <button key={x.tail} className="list-item" aria-current={x.tail === tail}
                    onClick={() => { setSel(x.tail); setTab("status"); setMsg(null); }}>
              <StatusSymbol level={aircraftLevel(x.status)} size={16} />
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <b style={{ fontSize: 18 }}>{x.tail}</b>
                  <span className="t-dim">{words(x.status)}</span>
                </span>
                <span className="t-dim" style={{ display: "block", marginTop: 2 }}>
                  {nextFor(x, interval)}
                </span>
              </span>
            </button>
          ))}
        </div>

        {!a ? <Section><Empty>Loading {tail}…</Empty></Section> : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
            <Section>
              <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: "min(100%, 260px)" }}>
                  <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
                    <span className="t-title">{a.tail}</span>
                    <Status level={aircraftLevel(a.status)} text={words(a.status)} size={18} />
                    {a.on_gcs && <span className="app-state">ON GCS</span>}
                  </div>
                  <div className="t-dim" style={{ marginTop: 6 }}>
                    {a.engine_name} · engine serial {a.twin_id}
                    {!a.engine_validated && " · unvalidated engine model"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  {mode === "maintain" && !running && (
                    <ConfirmButton label="Engine ground run" confirmLabel="Confirm ground run"
                                   disabled={!!board.busy}
                                   onConfirm={() => act(() => opsPost(`/api/ops/aircraft/${a.tail}/ground_run`),
                                     `Ground run started on ${a.tail}: warm-up, run-up, cool-down, shutdown.`)} />
                  )}
                  {!a.on_gcs && !board.busy && (
                    <Button onClick={() => act(() => opsPost(`/api/ops/aircraft/${a.tail}/connect`),
                                               `${a.tail} is on the ground station, engine off.`)}>
                      Put on GCS
                    </Button>
                  )}
                  {mode === "command" && !running && (
                    <Button onClick={() => setDrawer({ kind: "engine" })}>Engine change</Button>
                  )}
                  {primary}
                </div>
              </div>
            </Section>

            <Result msg={msg} />

            <div className="tabs" role="tablist" style={{ marginTop: 0 }}>
              {[["status", "Status", 0], ["defects", "Defects", openDefects.length],
                ...(mode === "maintain" ? [["work", "Work", a.pending_maintenance.length]] : []),
                ["log", "Logbook", 0]].map(([id, label, n]: any) => (
                <button key={id} role="tab" className="tab" aria-selected={tab === id}
                        onClick={() => setTab(id)}>
                  {label}{n ? <span className="count">{n}</span> : null}
                </button>
              ))}
            </div>

            {tab === "status" && <StatusTab a={a} interval={interval} />}
            {tab === "defects" && (
              <DefectsTab a={a} mode={mode} running={!!running}
                          onRectify={(d) => setDrawer({ kind: "rectify", defect: d })}
                          onReport={() => setDrawer({ kind: "report" })}
                          onGround={() => setDrawer({ kind: "ground" })} />
            )}
            {tab === "work" && mode === "maintain" && (
              <WorkTab a={a} running={!!running} act={act} />
            )}
            {tab === "log" && <LogTab a={a} />}
          </div>
        )}
      </div>

      {a && drawer?.kind === "rectify" && (
        <RectifyDrawer d={drawer.defect} tail={a.tail} onClose={() => setDrawer(null)}
                       onDone={(t) => { setMsg({ ok: true, text: t }); setDrawer(null); refresh(); }} />
      )}
      {a && drawer?.kind === "release" && (
        <NoteDrawer title={`Sign release · ${a.tail}`}
                    sub="Confirms the inspection is complete and the aircraft is fit to fly."
                    label="Inspection" placeholder="BFI, AFI, work order…" initial="BFI"
                    action="Sign release" onClose={() => setDrawer(null)}
                    onSubmit={(note) => act(() => opsPost(`/api/ops/aircraft/${a.tail}/release`, { note }),
                                            `${a.tail} released for flight.`)} />
      )}
      {a && drawer?.kind === "ground" && (
        <NoteDrawer title={`Ground ${a.tail}`} sub="Declares the aircraft unserviceable until rectified."
                    label="Reason" placeholder="What makes it unfit to fly" action="Ground aircraft"
                    onClose={() => setDrawer(null)}
                    onSubmit={(reason) => act(() => opsPost(`/api/ops/aircraft/${a.tail}/ground`, { reason }),
                                              `${a.tail} grounded.`)} />
      )}
      {a && drawer?.kind === "report" && (
        <ReportDrawer tail={a.tail} onClose={() => setDrawer(null)}
                      onSubmit={(body) => act(() => opsPost(`/api/ops/aircraft/${a.tail}/defects`, body),
                                              `Defect raised on ${a.tail}.`)} />
      )}
      {a && drawer?.kind === "engine" && (
        <EngineDrawer a={a} onClose={() => setDrawer(null)}
                      onSubmit={(engine_key, note) => act(
                        () => opsPost(`/api/ops/aircraft/${a.tail}/engine`, { engine_key, note }),
                        `${engine_key} fitted to ${a.tail}. It needs a ground run and inspection.`)} />
      )}
    </Workspace>
  );
}

// ---------------------------------------------------------------- tabs

function StatusTab({ a, interval }: { a: any; interval: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {a.grounding.length > 0 && (
        <Callout level="caution" title="May not fly">
          {a.grounding.map((g: string) => <div key={g}>{g}</div>)}
        </Callout>
      )}
      <FleetStatusDashboard a={a} interval={interval} />
    </div>
  );
}

function DefectsTab(props: { a: any; mode: Mode; running: boolean; onRectify: (d: any) => void;
                             onReport: () => void; onGround: () => void }) {
  const open = props.a.defects.filter((d: any) => d.status !== "CLOSED");
  const closed = props.a.defects.filter((d: any) => d.status === "CLOSED").slice(0, 8);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Section title={`Open defects (${open.length})`}
               right={props.mode === "maintain" && (
                 <div style={{ display: "flex", gap: 10 }}>
                   <Button kind="quiet" onClick={props.onGround}>Ground aircraft</Button>
                   <Button onClick={props.onReport}>Report a defect</Button>
                 </div>
               )}>
        {open.length === 0 && <Empty>No open defects.</Empty>}
        {open.map((d: any) => (
          <div key={d.id} style={{ padding: "14px 0", borderTop: "1px solid var(--line)" }}>
            <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
              <Status level={severityLevel(d.severity)} text={`#${d.id} ${words(d.severity)}`} />
              {!!d.grounding && <span className="app-state">GROUNDING</span>}
              <span className="t-dim">{words(d.status)} · raised by {d.source === "TWIN" ? "the engine twin"
                : d.raised_by} · {utc(d.raised_utc)}
                {d.mission_id ? ` · after ${d.mission_id}` : ""}</span>
              <span style={{ flex: 1 }} />
              {props.mode === "maintain" && !props.running && (
                <Button onClick={() => props.onRectify(d)}>Rectify</Button>
              )}
            </div>
            <div className="t-body" style={{ marginTop: 6 }}>{d.description}</div>
            {d.action_id && <div className="t-dim">Recommended: {d.action_id} {ACTION_NAMES[d.action_id]}</div>}
            {d.disposition && (
              <div className="t-dim">Engineering: {words(d.disposition)} by {d.disposed_by} — {d.disposition_note}
                {d.defer_until_hours != null ? ` (until ${d.defer_until_hours} engine h)` : ""}</div>
            )}
          </div>
        ))}
      </Section>
      {closed.length > 0 && (
        <Section title="Recently closed" flat>
          {closed.map((d: any) => (
            <div key={d.id} className="t-dim" style={{ padding: "4px 0" }}>
              #{d.id} {d.description} — {d.rectification ? `rectified: ${d.rectification}` : words(d.disposition ?? "closed")}
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}

function WorkTab({ a, running, act }: { a: any; running: boolean;
                                        act: (fn: () => Promise<any>, ok: string) => void }) {
  const [work, setWork] = useState({ action_id: "A1", note: "", repaired: true });
  const recent = a.logbook.filter((e: any) =>
    ["MAINTENANCE", "DEFECT_RECTIFIED", "GROUND_RUN", "RELEASE"].includes(e.kind)).slice(0, 10);
  const inspection = work.action_id === "A5" || work.action_id === "A6";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Section title="Record work">
        <div style={{ display: "grid", gap: 12, gridTemplateColumns: "minmax(240px, 1fr) minmax(240px, 1.4fr) auto",
                      alignItems: "end" }}>
          <Field label="Job">
            <select className="input" value={work.action_id}
                    onChange={(e) => setWork({ ...work, action_id: e.target.value })}>
              {Object.entries(ACTION_NAMES).map(([k, v]) => <option key={k} value={k}>{k} · {v}</option>)}
            </select>
          </Field>
          <Field label="Note">
            <input className="input" value={work.note} placeholder="Work order, part serials"
                   onChange={(e) => setWork({ ...work, note: e.target.value })} />
          </Field>
          {/* Secondary: the header already carries this aircraft's one
              primary action, and recording other work is not it. */}
          <Button disabled={running}
                  onClick={() => act(() => opsPost(`/api/ops/aircraft/${a.tail}/maintenance`,
                    { action_id: work.action_id, note: work.note, repaired: inspection ? work.repaired : null }),
                    `${work.action_id} recorded on ${a.tail}.`)}>
            Record
          </Button>
        </div>
        {inspection && (
          <label className="check" style={{ borderBottom: 0 }}>
            <input type="checkbox" checked={work.repaired}
                   onChange={(e) => setWork({ ...work, repaired: e.target.checked })} />
            <span>Parts were replaced during the inspection (an inspection that replaced nothing restores nothing)</span>
          </label>
        )}
        <div className="t-mute" style={{ marginTop: 8 }}>
          {a.on_gcs ? "This aircraft is on the ground station: the work reaches its engine twin now."
            : "Recorded now; the engine twin applies it at this aircraft's next ground run or flight."}
        </div>
      </Section>
      <Section title="Recent work" flat>
        {recent.length === 0 ? <Empty>No work recorded yet.</Empty> : (
          <table className="table"><tbody>
            {recent.map((e: any) => (
              <tr key={e.id}>
                <td className="t-num t-dim" style={{ width: 140 }}>{utc(e.utc)}</td>
                <td>{e.text}</td><td className="t-dim">{e.by !== "system" ? e.by : ""}</td>
              </tr>
            ))}
          </tbody></table>
        )}
      </Section>
    </div>
  );
}

function LogTab({ a }: { a: any }) {
  return (
    <Section flat>
      <table className="table">
        <thead><tr><th>Time (UTC)</th><th>Entry</th><th>Detail</th><th>By</th></tr></thead>
        <tbody>
          {a.logbook.slice(0, 60).map((e: any) => (
            <tr key={e.id}>
              <td className="t-num t-dim" style={{ whiteSpace: "nowrap" }}>{utc(e.utc)}</td>
              <td style={{ whiteSpace: "nowrap" }}>{words(e.kind)}</td>
              <td>{e.text}</td>
              <td className="t-dim">{e.by !== "system" ? e.by : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

// ---------------------------------------------------------------- drawers

function NoteDrawer(props: { title: string; sub: string; label: string; placeholder: string;
                             initial?: string; action: string; onClose: () => void;
                             onSubmit: (note: string) => void }) {
  const [note, setNote] = useState(props.initial ?? "");
  return (
    <Drawer open title={props.title} sub={props.sub} onClose={props.onClose}
            footer={<><Button kind="quiet" onClick={props.onClose}>Cancel</Button>
              <Button kind="primary" disabled={!note.trim()} onClick={() => props.onSubmit(note)}>
                {props.action}</Button></>}>
      <Field label={props.label}>
        <input className="input" value={note} placeholder={props.placeholder}
               onChange={(e) => setNote(e.target.value)} />
      </Field>
    </Drawer>
  );
}

function RectifyDrawer(props: { d: any; tail: string; onClose: () => void; onDone: (t: string) => void }) {
  const [acts, setActs] = useState<string[]>(props.d.action_id ? [props.d.action_id] : []);
  const [note, setNote] = useState("");
  const [repaired, setRepaired] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    try {
      const r = await opsPost(`/api/ops/defects/${props.d.id}/rectify`, { actions: acts, note, repaired });
      const later = (r.applied ?? []).includes("queued");
      props.onDone(`Defect #${props.d.id} rectified.${later ? " The engine twin applies the work at the next engine run." : ""}`
        + " Inspect and sign the release.");
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <Drawer open title={`Rectify defect #${props.d.id}`} sub={`${props.tail} · ${props.d.description}`}
            onClose={props.onClose}
            footer={<><Button kind="quiet" onClick={props.onClose}>Cancel</Button>
              <Button kind="primary" disabled={!acts.length && !note.trim()} onClick={submit}>
                Close as rectified</Button></>}>
      <div>
        <div className="field"><span>Work done</span></div>
        {Object.entries(ACTION_NAMES).map(([k, v]) => (
          <label key={k} className="check">
            <input type="checkbox" checked={acts.includes(k)}
                   onChange={(e) => setActs(e.target.checked ? [...acts, k] : acts.filter((x) => x !== k))} />
            <span>{k} · {v}{props.d.action_id === k ? "  (recommended)" : ""}</span>
          </label>
        ))}
      </div>
      {acts.some((x) => x === "A5" || x === "A6") && (
        <label className="check">
          <input type="checkbox" checked={repaired} onChange={(e) => setRepaired(e.target.checked)} />
          <span>Parts were replaced during the inspection</span>
        </label>
      )}
      <Field label="What was found and done">
        <textarea className="input" value={note} onChange={(e) => setNote(e.target.value)}
                  placeholder="Findings, work order, part serials" />
      </Field>
      {err && <Callout level="caution" title="Not done">{err}</Callout>}
    </Drawer>
  );
}

function ReportDrawer(props: { tail: string; onClose: () => void; onSubmit: (b: any) => void }) {
  const [b, setB] = useState({ description: "", severity: "CAUTION", grounding: false });
  return (
    <Drawer open title={`Report a defect · ${props.tail}`} onClose={props.onClose}
            footer={<><Button kind="quiet" onClick={props.onClose}>Cancel</Button>
              <Button kind="primary" disabled={!b.description.trim()} onClick={() => props.onSubmit(b)}>
                Raise defect</Button></>}>
      <Field label="What is wrong">
        <textarea className="input" value={b.description}
                  onChange={(e) => setB({ ...b, description: e.target.value })} />
      </Field>
      <Field label="Severity">
        <div className="segmented" role="group">
          {["ADVISORY", "CAUTION", "WARNING", "EMERGENCY"].map((s) => (
            <button key={s} type="button" aria-pressed={b.severity === s}
                    onClick={() => setB({ ...b, severity: s })}>{words(s)}</button>
          ))}
        </div>
      </Field>
      <label className="check">
        <input type="checkbox" checked={b.grounding} onChange={(e) => setB({ ...b, grounding: e.target.checked })} />
        <span>The aircraft may not fly until this is rectified</span>
      </label>
    </Drawer>
  );
}

function EngineDrawer(props: { a: any; onClose: () => void; onSubmit: (k: string, note: string) => void }) {
  const [engines, setEngines] = useState<any[]>([]);
  const [key, setKey] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    opsGet("/api/engines").then((d) => {
      const ok = (d.engines ?? []).filter((e: any) => e.usable && e.key !== props.a.engine_key);
      setEngines(ok); if (ok[0]) setKey(ok[0].key);
    }).catch(() => undefined);
  }, [props.a.engine_key]);
  return (
    <Drawer open title={`Engine change · ${props.a.tail}`}
            sub={`Now fitted: ${props.a.engine_name}. The new engine starts at 0 h; the aircraft needs a ground run and inspection.`}
            onClose={props.onClose}
            footer={<><Button kind="quiet" onClick={props.onClose}>Cancel</Button>
              <Button kind="primary" disabled={!key} onClick={() => props.onSubmit(key, note)}>Fit engine</Button></>}>
      {engines.length === 0 ? <Empty>No other complete engine definition.</Empty> : (
        <Field label="Engine to fit">
          <select className="input" value={key} onChange={(e) => setKey(e.target.value)}>
            {engines.map((e) => <option key={e.key} value={e.key}>
              {e.display_name}{e.validated ? "" : " (unvalidated)"}</option>)}
          </select>
        </Field>
      )}
      <Field label="Note"><input className="input" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
    </Drawer>
  );
}
