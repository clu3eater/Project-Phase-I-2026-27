/* MAINTENANCE — the maintainer's own page.
 *
 * The maintenance role could sign in and then do almost nothing. It could
 * record work only from buttons on the PROGNOSTICS plan, which appeared only
 * for jobs the plan was recommending at that moment -- a scheduled oil change,
 * or a part replaced on inspection, had nowhere to be recorded. And when a
 * job was recorded nothing on screen said so: the click was fire-and-forget,
 * and the health the work restored climbed back somewhere else, over minutes,
 * with nothing connecting it to the job.
 *
 * So this page has three things, in the order a maintainer works:
 *   1. the engine's condition by subsystem, now;
 *   2. every job in the library, recommended ones first, each one recordable,
 *      with the health indices it is expected to move;
 *   3. the work log, where each job shows those indices BEFORE the work and
 *      AFTER the engine has run long enough to settle -- the evidence that the
 *      repair did what it was meant to.
 */

import { useCallback, useEffect, useState } from "react";

import { Panel } from "../components/Core";
import { ComparisonChart } from "../components/ComparisonChart";
import { api, can, type Snapshot } from "../lib/api";
import { Button, Drawer, Empty, Field, Result, utc } from "../ui/kit";
import { type Level, Status, StatusSymbol } from "../ui/status";

const INDEX_LABEL: Record<string, string> = {
  chi: "Overall health",
  thermal: "Thermal subsystem",
  mechanical: "Mechanical subsystem",
  combustion: "Combustion subsystem",
  electrical: "Electrical subsystem",
  thi: "Head / coolant temp (THI)",
  lhi: "Lubrication (LHI)",
  oti: "Oil temperature (OTI)",
  comb_hi: "EGT spread (combustion)",
  fshi: "Fuel system (FSHI)",
  csi: "Cylinder balance (CSI)",
  mhi: "Vibration (MHI)",
};

const pct = (v: number | null | undefined) =>
  typeof v !== "number" || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(1)} %`;

/** Quiet when healthy: a symbol only when an index needs looking at. */
function healthLevel(v: number | null | undefined): Level | null {
  if (v == null) return null;
  return v >= 0.9 ? null : v >= 0.75 ? "caution" : "warning";
}

function Pct({ v }: { v: number | null | undefined }) {
  const l = healthLevel(v);
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
      {l && <StatusSymbol level={l} size={12} />}{pct(v)}
    </span>
  );
}

export function MaintenancePage({ snap }: { snap: Snapshot }) {
  const [cat, setCat] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [job, setJob] = useState<any>(null);

  const load = useCallback(() => {
    api("/api/maintenance/catalog")
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 403
          ? "Your role cannot read the maintenance plan."
          : "maintenance data unavailable");
        return r.json();
      })
      .then((d) => { setCat(d); setError(null); })
      .catch((e) => setError(e.message));
  }, []);

  // The log changes as the twin applies and then verifies each job, so it is
  // re-read every two seconds rather than once.
  useEffect(() => {
    load();
    const id = window.setInterval(load, 2000);
    return () => window.clearInterval(id);
  }, [load]);

  if (error) return <Panel title="Maintenance plan"><Empty>{error}</Empty></Panel>;
  if (!cat) return <Panel title="Maintenance plan"><Empty>Loading the plan…</Empty></Panel>;

  const h: any = snap.health ?? cat.health ?? {};
  const actions: any[] = cat.actions ?? [];
  const due = actions.filter((a) => a.recommended);
  const other = actions.filter((a) => !a.recommended);
  const performed: any[] = [...(cat.performed ?? [])].reverse();
  const pending: any[] = cat.pending ?? [];
  const writer = can("write:maintenance");
  const systemHealth = ["chi", "thermal", "mechanical", "combustion", "electrical"];

  return (
    <div className="maintenance-layout">
      <div className="maintenance-summary card">
        <ComparisonChart label="Latest assessed health by system"
          items={systemHealth.map((k) => ({
            label: INDEX_LABEL[k].replace(" subsystem", ""),
            value: typeof h[k] === "number" ? h[k] * 100 : null,
            display: pct(h[k]),
          }))} />
        <dl className="dl" style={{ gap: "2px 16px" }}>
          {cat.hours_since_oil_change != null && <>
            <dt>Oil changed</dt><dd className="t-num">{Number(cat.hours_since_oil_change).toFixed(1)} h ago</dd></>}
          {cat.hours_since_inspection != null && <>
            <dt>100 h check</dt><dd className="t-num">{Number(cat.hours_since_inspection).toFixed(1)} h ago</dd></>}
        </dl>
      </div>

      <div className="maintenance-notice">
        <Result msg={notice} />
        {!writer && <Empty>Read only: recording work needs the maintenance role.</Empty>}
      </div>

      <Panel title={due.length ? `Jobs due (${due.length})` : "Jobs"} grow>
        {due.length === 0 && (
          <Empty>The twin recommends no work on this engine now.</Empty>
        )}
        {due.map((a, i) => (
          <div key={a.action_id} style={{ padding: "12px 0", borderBottom: "1px solid var(--line)",
                                          display: "flex", gap: 16, alignItems: "flex-start" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
                <b style={{ fontSize: 18 }}>{a.action_id} · {a.name}</b>
                <Status level="caution" bold={false}
                        text={a.due_within_hours != null ? `Due within ${Number(a.due_within_hours).toFixed(0)} h` : "Recommended"} />
              </div>
              <div style={{ marginTop: 4 }}>{a.reason}</div>
              <div className="t-dim" style={{ marginTop: 2 }}>
                Rs {Number(a.cost_inr ?? 0).toLocaleString()} · {a.downtime_hours} h
                {a.parts?.length ? ` · ${a.parts.join(", ")}` : ""}
              </div>
            </div>
            {writer && <Button kind={i === 0 ? "primary" : "secondary"} onClick={() => setJob(a)}>Record</Button>}
          </div>
        ))}
        {other.length > 0 && (
          <>
            <div className="t-label" style={{ margin: "16px 0 4px" }}>
              Other work, if done anyway
            </div>
            {other.map((a) => (
              <div key={a.action_id} style={{ display: "flex", gap: 12, alignItems: "center",
                                              padding: "6px 0", borderBottom: "1px solid var(--line)" }}>
                <span style={{ flex: 1, minWidth: 0 }}>
                  {a.action_id} · {a.name}
                  <span className="t-mute"> · Rs {Number(a.cost_inr ?? 0).toLocaleString()} · {a.downtime_hours} h</span>
                </span>
                {writer && <Button kind="quiet" onClick={() => setJob(a)}>Record</Button>}
              </div>
            ))}
          </>
        )}
      </Panel>

      <Panel title="Work log: health before and after" grow>
        {pending.map((w: any, i: number) => (
          <div key={`p-${i}`} style={{ padding: "8px 0" }}>
            <Status level="advisory" bold={false} text={`${w.name}: applying on the next tick`} />
          </div>
        ))}
        {performed.length === 0 && pending.length === 0 && (
          <Empty>No work recorded on this engine yet.</Empty>
        )}
        {performed.map((w: any, i: number) => {
          const before = w.health_before ?? {};
          const after = w.health_after;
          const keys: string[] = w.affects ?? Object.keys(before);
          const nothing = !(w.restored?.length || w.faults_removed?.length);
          return (
            <div key={`${w.action_id}-${w.recorded_utc}-${i}`}
                 style={{ padding: "12px 0", borderBottom: "1px solid var(--line)" }}>
              <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
                <b style={{ fontSize: 18 }}>{w.name}</b>
                {!nothing && (after
                  ? <Status level="normal" bold={false} text="Confirmed" />
                  : <Status level="advisory" bold={false} text="Confirming" />)}
              </div>
              <div className="t-dim" style={{ marginTop: 2 }}>
                {utc(w.recorded_utc)}{w.by ? ` · ${w.by}` : ""}
                {w.applied_flight_hours != null ? ` · at ${w.applied_flight_hours} engine h` : ""}
                {w.note ? ` · ${w.note}` : ""}
              </div>
              {nothing ? (
                <div className="t-dim" style={{ marginTop: 4 }}>
                  Nothing replaced: the engine's condition and trends are unchanged.
                </div>
              ) : keys.length > 0 && (
                <div className="table-scroll">
                <table className="table" style={{ marginTop: 6 }}>
                  <thead>
                    <tr><th>Index</th><th className="num">Before</th>
                      <th className="num">{after ? "After" : "Now"}</th><th className="num">Change</th></tr>
                  </thead>
                  <tbody>
                    {keys.map((k) => {
                      const b = before[k];
                      const n = after ? after[k] : h[k];
                      const d = b != null && n != null ? n - b : null;
                      return (
                        <tr key={k}>
                          <td>{INDEX_LABEL[k] ?? k}</td>
                          <td className="num"><Pct v={b} /></td>
                          <td className="num"><Pct v={n} /></td>
                          <td className="num">
                            {d == null ? "—" : d < -0.002
                              ? <Status level="caution" bold={false} text={(d * 100).toFixed(1)} />
                              : `${d >= 0 ? "+" : ""}${(d * 100).toFixed(1)}`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                </div>
              )}
              {!nothing && !after && (
                <div className="t-mute" style={{ marginTop: 6 }}>
                  The after reading is taken once the engine has run about{" "}
                  {Math.round((cat.settle_hours ?? 0.05) * 60)} min since the work.
                </div>
              )}
            </div>
          );
        })}
      </Panel>

      {job && (
        <RecordDrawer a={job} h={h} onClose={() => setJob(null)}
                      onDone={(ok, text) => { setNotice({ ok, text }); if (ok) setJob(null); load(); }} />
      )}
    </div>
  );
}

/* Recording a job is its own short form, beside the plan, instead of a
 * browser confirm() over the whole console. */
function RecordDrawer(props: { a: any; h: any; onClose: () => void;
                               onDone: (ok: boolean, text: string) => void }) {
  const { a, h } = props;
  const [note, setNote] = useState("");
  const [repaired, setRepaired] = useState<boolean | undefined>(a.inspection ? false : undefined);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api("/api/maintenance/performed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_id: a.action_id, repaired, note: note.slice(0, 200) }),
      });
      if (!r.ok) throw new Error((await r.text()).slice(0, 200));
      props.onDone(true, `${a.name} recorded. The twin applies it on its next tick; the after `
        + "reading is taken once the engine has run long enough to settle.");
    } catch (e: any) {
      props.onDone(false, `Not recorded: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Drawer open title={`${a.action_id} · ${a.name}`}
            sub={a.recommended ? a.reason : "Not currently recommended: record it if it was done anyway."}
            onClose={props.onClose}
            footer={<>
              <Button kind="quiet" onClick={props.onClose}>Cancel</Button>
              <Button kind="primary" disabled={busy} onClick={submit}>
                {busy ? "Recording…" : "Record as done"}</Button>
            </>}>
      <dl className="dl">
        <dt>Cost</dt><dd>Rs {Number(a.cost_inr ?? 0).toLocaleString()} · {a.downtime_hours} h downtime</dd>
        {a.parts?.length > 0 && <><dt>Parts</dt><dd>{a.parts.join(", ")}</dd></>}
        <dt>Should improve</dt>
        <dd>{a.affects.map((k: string) => `${INDEX_LABEL[k] ?? k} (now ${pct(h[k])})`).join(", ")}</dd>
      </dl>
      {a.inspection && (
        <Field label="Outcome">
          <div className="segmented" role="group" aria-label="Outcome">
            <button type="button" aria-pressed={repaired === false} onClick={() => setRepaired(false)}>
              Inspected, nothing replaced</button>
            <button type="button" aria-pressed={repaired === true} onClick={() => setRepaired(true)}>
              Parts replaced</button>
          </div>
        </Field>
      )}
      <Field label="Note (work order, part serials)">
        <textarea className="input" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
      </Field>
    </Drawer>
  );
}
