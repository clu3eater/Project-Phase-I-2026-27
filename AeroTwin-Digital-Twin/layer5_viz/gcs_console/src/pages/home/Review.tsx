/* REVIEW -- the propulsion engineer's home (docs/UX_REDESIGN.md section 6).
 *
 * The twin writes its maintenance advisory onto an aircraft's technical log
 * after every engine run. Someone with engineering authority decides what each
 * finding means, and that is this page's first job, so it opens on the queue:
 *
 *   Confirm        the finding is real; if it grounds the aircraft it stays
 *                  grounded until a maintainer rectifies it.
 *   Defer          a concession: the aircraft may fly up to an hours limit,
 *                  by which the work must be done. The limit is enforced.
 *   No fault found closed, with the reasoning kept.
 *
 * One decision per finding, taken in a drawer beside the evidence. The
 * squadron's engines side by side and the concessions in force are one tab
 * away, because they are what an engineer reads BEFORE deciding, not what
 * they act on.
 */

import { useState } from "react";

import { type Aircraft, ACTION_NAMES, opsPost, useOpsBoard } from "../../lib/ops";
import { ComparisonChart } from "../../components/ComparisonChart";
import { Button, Drawer, Empty, Field, Result, Section, Workspace, utc } from "../../ui/kit";
import { type Level, Status, StatusSymbol, aircraftLevel, severityLevel, words } from "../../ui/status";

const pct = (v: number | null | undefined) =>
  typeof v !== "number" || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(1)} %`;

/** Health is quiet until it is not: no symbol at all when it is fine. */
function healthLevel(v: number | null | undefined): Level | null {
  if (v == null) return null;
  return v >= 0.9 ? null : v >= 0.75 ? "caution" : "warning";
}

function Health({ v }: { v: number | null | undefined }) {
  const l = healthLevel(v);
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center", justifyContent: "flex-end" }}>
      {l && <StatusSymbol level={l} size={12} />}{pct(v)}
    </span>
  );
}

function evidenceOf(d: any): any {
  try { return d.evidence ? JSON.parse(d.evidence) : null; } catch { return null; }
}

type Finding = any & { a: Aircraft };

export function ReviewHome() {
  const { board, error, reload } = useOpsBoard();
  const [tab, setTab] = useState("findings");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [deciding, setDeciding] = useState<Finding | null>(null);
  const [limitsFor, setLimitsFor] = useState<Aircraft | null>(null);

  if (!board) return <Workspace title="Review"><Empty>{error ?? "Loading the squadron board…"}</Empty></Workspace>;

  const findings: Finding[] = board.aircraft.flatMap((a) =>
    a.open_defects.filter((d: any) => d.status === "OPEN" && d.source === "TWIN")
      .map((d: any) => ({ ...d, a })))
    .sort((x, y) => Number(!!y.grounding) - Number(!!x.grounding) || x.id - y.id);
  const concessions = board.aircraft.flatMap((a) =>
    a.open_defects.filter((d: any) => d.status === "DEFERRED").map((d: any) => ({ ...d, a })));
  const limited = board.aircraft.filter((a) => Object.keys(a.limitations ?? {}).length > 0);
  const done = (text: string, ok = true) => {
    setMsg({ ok, text });
    if (ok) { setDeciding(null); setLimitsFor(null); }
    reload();
  };

  return (
    <Workspace title="Review"
               sub={findings.length === 0
                 ? "No twin findings waiting for a decision"
                 : `${findings.length} twin finding${findings.length > 1 ? "s" : ""} waiting for a decision`}
               tabs={[{ id: "findings", label: "Findings", count: findings.length },
                      { id: "engines", label: "Squadron engines" },
                      { id: "concessions", label: "Concessions and limits",
                        count: concessions.length + limited.length }]}
               tab={tab} onTab={(t) => { setTab(t); setMsg(null); }}>
      <div style={{ maxWidth: "var(--content-max)", display: "flex", flexDirection: "column", gap: 16 }}>
        <Result msg={msg} />

        {tab === "findings" && (
          findings.length === 0 ? (
            <Section>
              <Empty>Nothing to decide. The twin writes its findings here after each engine run.</Empty>
            </Section>
          ) : (
            <div className="card-flat" style={{ padding: 0 }}>
              {findings.map((d, i) => {
                const ev = evidenceOf(d);
                return (
                  <div key={d.id} style={{ display: "flex", gap: 16, alignItems: "flex-start",
                                           padding: "16px 20px",
                                           borderTop: i ? "1px solid var(--line)" : undefined }}>
                    <div style={{ paddingTop: 3 }}>
                      <StatusSymbol level={severityLevel(d.severity)} size={16} />
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
                        <b style={{ fontSize: 18 }}>{d.a.tail} · #{d.id}</b>
                        <span className="t-dim">{words(d.severity)}{d.grounding ? " · grounds the aircraft" : ""}</span>
                        <span className="t-mute">{utc(d.raised_utc)}{d.mission_id ? ` · after ${d.mission_id}` : ""}</span>
                      </div>
                      <div style={{ marginTop: 4 }}>{d.description}</div>
                      {d.action_id && (
                        <div className="t-dim" style={{ marginTop: 2 }}>
                          Twin recommends {d.action_id} {ACTION_NAMES[d.action_id] ?? ""}
                          {ev?.due_within_hours != null ? `, within ${Number(ev.due_within_hours).toFixed(0)} h` : ""}
                        </div>
                      )}
                    </div>
                    <Button kind={i === 0 ? "primary" : "secondary"}
                            onClick={() => { setMsg(null); setDeciding(d); }}>Decide</Button>
                  </div>
                );
              })}
            </div>
          )
        )}

        {tab === "engines" && (
          <Section title="Engines across the squadron"
                   right={<span className="t-mute">Health is the twin's last judgement, warm and loaded</span>}>
            <div className="review-health-chart">
              <ComparisonChart label="Last recorded overall health by aircraft"
                items={board.aircraft.map((a) => ({
                  label: a.tail,
                  value: typeof a.health?.chi === "number" ? a.health.chi * 100 : null,
                  display: pct(a.health?.chi),
                }))} />
            </div>
            <div className="review-engine-table-wrap" style={{ overflowX: "auto" }}>
              <table className="table review-engine-table">
                <thead>
                  <tr>
                    <th>Aircraft</th><th>Engine</th><th>Status</th>
                    <th className="num">Health</th><th className="num">Thermal</th>
                    <th className="num">Mechanical</th><th className="num">Combustion</th>
                    <th className="num">Electrical</th><th className="num">Engine h</th>
                    <th className="num">To inspection</th><th className="num">TBO left</th><th />
                  </tr>
                </thead>
                <tbody>
                  {board.aircraft.map((a) => {
                    const h = a.health ?? {};
                    const s = h.subsystems ?? {};
                    return (
                      <tr key={a.tail}>
                        <td data-label="Aircraft"><b>{a.tail}</b></td>
                        <td data-label="Engine">{a.engine_key}{!a.engine_validated && <span className="t-mute"> · unvalidated</span>}</td>
                        <td data-label="Status"><Status level={aircraftLevel(a.status)} text={words(a.status)} bold={false} /></td>
                        <td data-label="Health" className="num" title={h.assessed_utc ? `assessed ${utc(h.assessed_utc)}` : "never assessed on this station"}>
                          <Health v={h.chi} /></td>
                        {["thermal", "mechanical", "combustion", "electrical"].map((k) => (
                          <td key={k} data-label={words(k)} className="num"><Health v={s[k]} /></td>
                        ))}
                        <td data-label="Engine hours" className="num">{h.engine_hours != null ? Number(h.engine_hours).toFixed(1) : "—"}</td>
                        <td data-label="To inspection" className="num">{h.hours_since_inspection != null
                          ? `${Math.max(0, board.inspection_interval_h - h.hours_since_inspection).toFixed(1)} h` : "—"}</td>
                        <td data-label="TBO remaining" className="num">{h.tbo_remaining_hours != null ? `${Math.round(h.tbo_remaining_hours)} h` : "—"}</td>
                        <td data-label="Actions" style={{ textAlign: "right" }}>
                          <Button kind="quiet" onClick={() => { setMsg(null); setLimitsFor(a); }}>Limits</Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {tab === "concessions" && (
          <>
            <Section title="Deferred defects">
              {concessions.length === 0 ? <Empty>No concessions in force.</Empty> : (
                <table className="table">
                  <thead>
                    <tr><th>Aircraft</th><th>Defect</th><th className="num">Fly up to</th>
                      <th className="num">Left</th><th>Reasoning</th></tr>
                  </thead>
                  <tbody>
                    {concessions.map((d: any) => {
                      const left = d.defer_until_hours - Number(d.a.health?.engine_hours ?? 0);
                      return (
                        <tr key={d.id}>
                          <td><b>{d.a.tail}</b></td>
                          <td>#{d.id} {d.description}</td>
                          <td className="num">{d.defer_until_hours} engine h</td>
                          <td className="num">
                            {left < 1 ? <Status level="caution" text={`${left.toFixed(1)} h`} />
                              : `${left.toFixed(1)} h`}
                          </td>
                          <td className="t-dim">{d.disposition_note}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </Section>
            <Section title="Operating limitations">
              {limited.length === 0 ? <Empty>No aircraft is flying under a limitation.</Empty> : (
                <table className="table">
                  <thead>
                    <tr><th>Aircraft</th><th className="num">Longest mission</th>
                      <th className="num">Highest altitude</th><th>Reason</th><th /></tr>
                  </thead>
                  <tbody>
                    {limited.map((a) => (
                      <tr key={a.tail}>
                        <td><b>{a.tail}</b></td>
                        <td className="num">{a.limitations.max_mission_hours != null ? `${a.limitations.max_mission_hours} h` : "—"}</td>
                        <td className="num">{a.limitations.max_altitude_ft != null
                          ? `${Number(a.limitations.max_altitude_ft).toLocaleString()} ft` : "—"}</td>
                        <td className="t-dim">{a.limitations.note}</td>
                        <td style={{ textAlign: "right" }}>
                          <Button kind="quiet" onClick={() => { setMsg(null); setLimitsFor(a); }}>Change</Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Section>
          </>
        )}
      </div>

      {deciding && <DecideDrawer d={deciding} onClose={() => setDeciding(null)} onDone={done} />}
      {limitsFor && <LimitsDrawer a={limitsFor} onClose={() => setLimitsFor(null)} onDone={done} />}
    </Workspace>
  );
}

// ------------------------------------------------------------------ drawers

function DecideDrawer(props: { d: Finding; onClose: () => void;
                               onDone: (t: string, ok?: boolean) => void }) {
  const { d } = props;
  const ev = evidenceOf(d);
  const [disp, setDisp] = useState<"CONFIRM" | "DEFER" | "NFF">("CONFIRM");
  const [grounding, setGrounding] = useState(!!d.grounding);
  const [hours, setHours] = useState(5);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setErr(null);
    try {
      await opsPost(`/api/ops/defects/${d.id}/disposition`, {
        disposition: disp, note,
        defer_hours: disp === "DEFER" ? hours : null,
        grounding: disp === "CONFIRM" ? grounding : null,
      });
      props.onDone(`${d.a.tail} defect #${d.id}: ${disp === "NFF" ? "no fault found" : disp.toLowerCase()} recorded.`);
    } catch (e: any) { setErr(e.message); }
  };

  return (
    <Drawer open title={`Defect #${d.id} · ${d.a.tail}`} sub={d.description} onClose={props.onClose}
            footer={<>
              <Button kind="quiet" onClick={props.onClose}>Cancel</Button>
              <Button kind="primary" disabled={!note.trim() || (disp === "DEFER" && !(hours > 0))}
                      onClick={submit}>Record decision</Button>
            </>}>
      <dl className="dl">
        <dt>Raised</dt><dd>{d.source === "TWIN" ? "Engine twin" : d.raised_by} · {utc(d.raised_utc)}</dd>
        <dt>Severity</dt><dd><Status level={severityLevel(d.severity)} text={words(d.severity)} /></dd>
        {d.mission_id && <><dt>After</dt><dd>{d.mission_id}</dd></>}
        {d.action_id && <><dt>Recommends</dt>
          <dd>{d.action_id} {ACTION_NAMES[d.action_id] ?? ""}
            {ev?.due_within_hours != null ? `, within ${Number(ev.due_within_hours).toFixed(0)} h` : ""}</dd></>}
        {ev?.health && <><dt>Health then</dt>
          <dd>overall {pct(ev.chi)} · thermal {pct(ev.health.thermal)} · mechanical {pct(ev.health.mechanical)}
            {" "}· combustion {pct(ev.health.combustion)} · electrical {pct(ev.health.electrical)}</dd></>}
      </dl>

      <div className="divider" style={{ margin: "4px 0" }} />

      <Field label="Decision">
        <div className="segmented" role="group" aria-label="Decision">
          {([["CONFIRM", "Confirm"], ["DEFER", "Defer"], ["NFF", "No fault found"]] as const).map(([k, l]) => (
            <button key={k} type="button" aria-pressed={disp === k} onClick={() => setDisp(k)}>{l}</button>
          ))}
        </div>
      </Field>
      {disp === "CONFIRM" && (
        <label className="check" style={{ borderBottom: 0 }}>
          <input type="checkbox" checked={grounding} onChange={(e) => setGrounding(e.target.checked)} />
          <span>Grounds the aircraft until a maintainer rectifies it</span>
        </label>
      )}
      {disp === "DEFER" && (
        <Field label="May fly for (engine hours)"
               hint={`Deferred to ${(Number(d.a.health?.engine_hours ?? 0) + (hours || 0)).toFixed(1)} engine h; enforced at allotment`}>
          <input className="input" type="number" min={0.5} step={0.5} value={hours}
                 style={{ maxWidth: 160 }} onChange={(e) => setHours(Number(e.target.value))} />
        </Field>
      )}
      <Field label="Engineering reasoning (required)">
        <textarea className="input" value={note} onChange={(e) => setNote(e.target.value)}
                  placeholder="What the evidence shows, and why this decision" />
      </Field>
      {err && <Result msg={{ ok: false, text: err }} />}
    </Drawer>
  );
}

function LimitsDrawer(props: { a: Aircraft; onClose: () => void;
                               onDone: (t: string, ok?: boolean) => void }) {
  const { a } = props;
  const has = Object.keys(a.limitations ?? {}).length > 0;
  const [hrs, setHrs] = useState<string>(a.limitations?.max_mission_hours?.toString() ?? "");
  const [alt, setAlt] = useState<string>(a.limitations?.max_altitude_ft?.toString() ?? "");
  const [note, setNote] = useState<string>(a.limitations?.note ?? "");
  const [err, setErr] = useState<string | null>(null);

  const save = async (clear: boolean) => {
    setErr(null);
    try {
      await opsPost(`/api/ops/aircraft/${a.tail}/limitations`, clear ? {} : {
        max_mission_hours: hrs ? Number(hrs) : null,
        max_altitude_ft: alt ? Number(alt) : null, note });
      props.onDone(clear ? `${a.tail}: limitations removed.` : `${a.tail}: limitations set.`);
    } catch (e: any) { setErr(e.message); }
  };

  return (
    <Drawer open title={`Operating limitations · ${a.tail}`}
            sub="The commander's allotment respects these. Leave a field empty for no limit."
            onClose={props.onClose}
            footer={<>
              {has && <Button kind="quiet" onClick={() => save(true)}>Remove limitations</Button>}
              <Button kind="primary" disabled={!hrs && !alt} onClick={() => save(false)}>Save limitations</Button>
            </>}>
      <Field label="Longest mission (hours)">
        <input className="input" type="number" min={0.5} step={0.5} value={hrs}
               style={{ maxWidth: 200 }} onChange={(e) => setHrs(e.target.value)} />
      </Field>
      <Field label="Highest altitude (ft)">
        <input className="input" type="number" min={1000} step={500} value={alt}
               style={{ maxWidth: 200 }} onChange={(e) => setAlt(e.target.value)} />
      </Field>
      <Field label="Reason">
        <textarea className="input" value={note} onChange={(e) => setNote(e.target.value)}
                  placeholder="e.g. cylinder 3 CHT trending high; limit until borescope" />
      </Field>
      {err && <Result msg={{ ok: false, text: err }} />}
    </Drawer>
  );
}
