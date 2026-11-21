/* MISSION -- the operator's home (docs/UX_REDESIGN.md section 6).
 *
 * The operator's whole job is one sortie at a time, so this page is one
 * sortie at a time: where it is in its life, the one thing to do next, and the
 * task and aircraft beside it. It changes with the phase of the sortie the
 * way Honeywell Anthem and the F-35 display configure by phase of flight,
 * and it never shows the operator anything they cannot act on
 * (WHO_READS_THIS_SCREEN: "a state word, the parameters against their
 * limits, and any alert with the action attached").
 */

import { useEffect, useState } from "react";

import { type Snapshot } from "../../lib/api";
import { TwinTable } from "../../components/TwinCompare";
import { type Focus, opsPost, useOpsBoard } from "../../lib/ops";
import {
  Button, ConfirmButton, Empty, Field, Result, Section, Stat, Stepper, Workspace,
} from "../../ui/kit";
import {
  type Level, Status, aircraftLevel, bandLevel, verdictLevel, words,
} from "../../ui/status";

const STEPS = ["Brief", "Pre-flight", "Engine", "Airborne", "Debrief"];
const OPEN = ["APPROVED", "PREFLIGHT", "ENGINE_RUNNING", "AIRBORNE", "RTB", "ABORTING",
              "AWAITING_DEBRIEF"];

function stepOf(status: string): number {
  switch (status) {
    case "APPROVED": return 0;
    case "PREFLIGHT": return 1;
    case "ENGINE_RUNNING": case "ABORTING": return 2;
    case "AIRBORNE": case "RTB": return 3;
    case "AWAITING_DEBRIEF": return 4;
    default: return 5;
  }
}

const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)} %`);

export function MissionHome({ snap, focus }: { snap: Snapshot; focus?: Focus | null }) {
  const { board, error, reload } = useOpsBoard();
  const [pick, setPick] = useState<string | null>(null);
  // A task in "Waiting on you" opens the mission it is about.
  useEffect(() => { if (focus?.mission) setPick(focus.mission); }, [focus?.n]);
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  if (!board) {
    return <Workspace title="Mission"><Empty>{error ?? "Loading the squadron board…"}</Empty></Workspace>;
  }
  const open = board.missions.filter((m) => OPEN.includes(m.status));
  const inWork = open.find((m) => m.status !== "APPROVED");
  const m = open.find((x) => x.id === pick) ?? inWork ?? open[0] ?? null;

  if (!m) {
    const last = board.missions.find((x) => ["COMPLETED", "ABORTED"].includes(x.status));
    return (
      <Workspace title="Mission" sub="No mission is approved for you.">
        <div style={{ maxWidth: 760 }}>
          <Section title="Nothing to fly">
            <div className="t-body t-dim">
              The commander plans missions and allots an aircraft to an operator. When one
              is approved for you it appears here, with its aircraft, and you take it from
              pre-flight to debrief on this page.
            </div>
            {last && (
              <div className="t-body" style={{ marginTop: 12 }}>
                Last sortie: {last.id} {last.name} on {last.tail}, {words(last.outcome ?? last.status)}.
              </div>
            )}
          </Section>
        </div>
      </Workspace>
    );
  }

  const ac = board.aircraft.find((a) => a.tail === m.tail);
  const live = board.live?.mission_id === m.id ? board.live : null;
  const so: any = live?.sortie ?? {};
  const rep: any = snap.twin?.reported ?? {};
  const act = async (path: string, body: any, ok: string) => {
    try { await opsPost(path, body); setMsg({ ok: true, text: ok }); reload(); }
    catch (e: any) { setMsg({ ok: false, text: e.message }); }
  };
  const type = board.mission_types[m.type]?.label ?? words(m.type);

  // ---- the "now" card for this phase ----------------------------------
  let head = "";
  let body: React.ReactNode = null;
  let primary: React.ReactNode = null;
  let secondary: React.ReactNode = null;

  if (m.status === "APPROVED") {
    head = `Ready for pre-flight`;
    const busy = board.busy && board.busy.id !== m.id;
    body = (
      <div className="t-body t-dim">
        Take {m.tail} onto the ground station. Its engine stays off until the pre-flight
        checklist is complete.
        {busy && <div style={{ marginTop: 8 }}>
          <Status level="standby" text={`Ground station busy: ${board.busy.kind === "mission"
            ? `mission ${board.busy.id}` : `ground run on ${board.busy.tail}`}`} bold={false} />
        </div>}
      </div>
    );
    primary = (
      <Button kind="primary" large disabled={!!busy}
              onClick={() => act(`/api/ops/missions/${m.id}/prepare`, {},
                                 `${m.tail} is on the ground station.`)}>
        Prepare {m.tail}
      </Button>
    );
  } else if (m.status === "PREFLIGHT") {
    const done = board.checklist.filter((i) => checks[i]).length;
    head = "Pre-flight checks";
    body = (
      <div>
        <div className="t-dim" style={{ marginBottom: 4 }}>
          {done} of {board.checklist.length} confirmed
        </div>
        {board.checklist.map((item) => (
          <label key={item} className="check">
            <input type="checkbox" checked={!!checks[item]}
                   onChange={(e) => setChecks({ ...checks, [item]: e.target.checked })} />
            <span>{item}</span>
          </label>
        ))}
      </div>
    );
    primary = (
      <ConfirmButton kind="primary" large label="Start engine" confirmLabel="Confirm engine start"
                     disabled={done < board.checklist.length}
                     onConfirm={() => act(`/api/ops/missions/${m.id}/start`, { checklist: checks },
                                          "Engine start. It warms up and holds for your launch clearance.")} />
    );
    secondary = (
      <Button kind="quiet" onClick={() => act(`/api/ops/missions/${m.id}/handback`, {},
                                              "Pre-flight stopped; the mission is handed back.")}>
        Stop pre-flight
      </Button>
    );
  } else if (m.status === "ENGINE_RUNNING") {
    const cks: any[] = live?.launch_checks ?? [];
    const ready = cks.length > 0 && !cks.some((c) => c.ok === false);
    const oil = rep.oil_temperature?.value;
    head = ready ? "Ready for launch" : so.phase === "STARTUP" ? "Engine starting" : "Engine warming up";
    body = (
      <div>
        <div className="t-body t-dim" style={{ marginBottom: 8 }}>
          {rep.rpm?.value != null ? `${Math.round(rep.rpm.value)} rpm` : ""}
          {oil != null ? ` · oil ${oil.toFixed(0)} °C` : ""}
          {!ready ? " · launch unlocks when every check below is met" : ""}
        </div>
        <table className="table">
          <tbody>
            {cks.map((c) => {
              const lvl: Level = c.ok === true ? "normal" : c.ok === null ? "caution" : "standby";
              return (
                <tr key={c.item}>
                  <td style={{ width: 150 }}>
                    <Status level={lvl} text={c.ok === true ? "Met" : c.ok === null ? "Review" : "Waiting"}
                            bold={false} />
                  </td>
                  <td>{c.item}</td>
                  <td className="num t-dim">{c.value != null ? String(c.value) : ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
    primary = (
      <ConfirmButton kind="primary" large label="Launch" confirmLabel="Confirm launch"
                     disabled={!ready}
                     onConfirm={() => act(`/api/ops/missions/${m.id}/launch`, {},
                                          "Launch clearance given: taxi and take-off.")} />
    );
    secondary = (
      <ConfirmButton label="Abort and shut down" confirmLabel="Confirm abort"
                     onConfirm={() => act(`/api/ops/missions/${m.id}/abort`, {},
                                          "Aborted: the engine cools down and shuts down.")} />
    );
  } else if (["AIRBORNE", "RTB", "ABORTING"].includes(m.status)) {
    head = m.status === "RTB" ? `Returning to base · ${words(so.phase)}`
      : m.status === "ABORTING" ? "Shutting down"
      : `Airborne · ${words(so.phase)}`;
    const d: any = snap.display ?? {};
    const margins: any[] = d.margins ?? [];
    body = (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div className="mission-metric-grid">
          <Stat label="Altitude" value={rep.environmental?.altitude_ft?.value != null
            ? Math.round(rep.environmental.altitude_ft.value).toLocaleString() : "—"} unit="ft" />
          <Stat label="Airspeed" value={rep.environmental?.airspeed_kmh?.value != null
            ? Math.round(rep.environmental.airspeed_kmh.value) : "—"} unit="km/h" />
          <Stat label="Since start" value={so.flight_time_s != null
            ? `${Math.floor(so.flight_time_s / 60)}:${String(Math.floor(so.flight_time_s % 60)).padStart(2, "0")}` : "—"}
                unit="min" />
          <div>
            <div className="t-label">Engine</div>
            <div style={{ marginTop: 8 }}>
              <Status level={bandLevel(d.band)} text={d.band ? words(d.band) : "Assessing"} size={18} />
            </div>
          </div>
        </div>
        {d.instruction && <div className="well t-body"><b>{d.instruction}</b></div>}
        {/* The early warning first: each reading against what the twin says
            it should be now. The limit margins below are the backstop. */}
        <TwinTable twin={d.twin} reported={rep} />
        {margins.length > 0 && (
          <table className="table">
            <thead><tr><th>Limit margin</th><th className="num">Now</th><th className="num">Limit</th>
              <th className="num">Margin</th></tr></thead>
            <tbody>
              {margins.map((g) => (
                <tr key={g.name}>
                  <td><Status level={g.exceeded ? "warning" : "normal"} text={g.name} bold={false} /></td>
                  <td className="num">{Number(g.value).toFixed(0)} {g.unit}</td>
                  <td className="num t-dim">{Number(g.limit).toFixed(0)}</td>
                  <td className="num">{Number(g.margin).toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    );
    secondary = m.status === "AIRBORNE" ? (
      <ConfirmButton label="Recall (RTB)" confirmLabel="Confirm recall"
                     onConfirm={() => act(`/api/ops/missions/${m.id}/rtb`, {},
                                          "Recalled: descending to return to base.")} />
    ) : null;
  } else if (m.status === "AWAITING_DEBRIEF") {
    head = "Shut down · debrief";
    body = <Debrief m={m} onDone={(t) => { setMsg({ ok: true, text: t }); reload(); }} />;
  }

  const v = m.assessment;
  return (
    <Workspace title={`${m.id} · ${m.name}`}
               sub={<>{type} · {m.duration_h} h at {Number(m.altitude_ft).toLocaleString()} ft ·
                 aircraft <b>{m.tail}</b></>}
               actions={open.length > 1 ? (
                 <select className="input" style={{ width: 280 }} value={m.id} aria-label="Mission"
                         onChange={(e) => setPick(e.target.value)}>
                   {open.map((x) => <option key={x.id} value={x.id}>{x.id} · {x.name} · {words(x.status)}</option>)}
                 </select>
               ) : undefined}>
      <div className="mission-detail-grid">
        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <div className="card-flat" style={{ padding: "14px 20px" }}>
            <Stepper steps={STEPS} at={stepOf(m.status)} />
          </div>
          <Section>
            <div className="t-title" style={{ marginBottom: 12 }}>{head}</div>
            {body}
            {(primary || secondary) && (
              <div style={{ display: "flex", gap: 12, justifyContent: "flex-end",
                            marginTop: 20, flexWrap: "wrap" }}>
                {secondary}{primary}
              </div>
            )}
          </Section>
          <Result msg={msg} />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <Section title="Task">
            <dl className="dl">
              <dt>Task</dt><dd>{type}</dd>
              <dt>Endurance</dt><dd>{m.duration_h} h</dd>
              <dt>Altitude</dt><dd>{Number(m.altitude_ft).toLocaleString()} ft</dd>
              <dt>Conditions</dt><dd>{words(m.environment)}</dd>
              {m.area && <><dt>Area</dt><dd>{m.area}</dd></>}
              {m.launch_utc && <><dt>Launch</dt><dd>{m.launch_utc}</dd></>}
              <dt>Priority</dt><dd>{words(m.priority)}</dd>
              <dt>Approved by</dt><dd>{m.approved_by}</dd>
            </dl>
            {m.notes && <div className="t-dim" style={{ marginTop: 10 }}>{m.notes}</div>}
          </Section>
          {ac && (
            <Section title={`Aircraft ${ac.tail}`}
                     right={<Status level={aircraftLevel(ac.status)} text={words(ac.status)} />}>
              <dl className="dl">
                <dt>Engine</dt><dd>{ac.engine_name}</dd>
                <dt>Health</dt><dd><Status level={bandLevel(ac.health?.band)}
                  text={ac.health?.chi != null ? `${pct(ac.health.chi)} · ${words(ac.health.band)}` : "Not assessed"}
                  bold={false} /></dd>
                <dt>Engine hours</dt><dd className="t-num">{ac.health?.engine_hours != null
                  ? Number(ac.health.engine_hours).toFixed(1) : "—"}</dd>
                {v?.verdict && <><dt>Twin verdict</dt><dd><Status level={verdictLevel(v.verdict)}
                  text={`${words(v.verdict)}${v.success_probability != null
                    ? ` · ${Math.round(v.success_probability * 100)} %` : ""}`} bold={false} /></dd></>}
              </dl>
              {ac.limitations?.max_mission_hours != null && (
                <div style={{ marginTop: 10 }}>
                  <Status level="caution" text={`Limited to ${ac.limitations.max_mission_hours} h missions`}
                          bold={false} />
                  <div className="t-dim">{ac.limitations.note}</div>
                </div>
              )}
              {ac.open_defects.filter((d: any) => d.status === "DEFERRED").map((d: any) => (
                <div key={d.id} style={{ marginTop: 10 }}>
                  <Status level="caution" text={`Deferred defect #${d.id}`} bold={false} />
                  <div className="t-dim">{d.description} (until {d.defer_until_hours} engine h)</div>
                </div>
              ))}
            </Section>
          )}
        </div>
      </div>
    </Workspace>
  );
}

function Debrief({ m, onDone }: { m: any; onDone: (t: string) => void }) {
  const [outcome, setOutcome] = useState(m.launched_utc ? "ACCOMPLISHED" : "ABORTED");
  const [remarks, setRemarks] = useState("");
  const [snags, setSnags] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    try {
      await opsPost(`/api/ops/missions/${m.id}/debrief`, { outcome, remarks, snags });
      onDone(`${m.id} debriefed.${snags.length ? ` ${snags.length} snag(s) are on ${m.tail}'s technical log.` : ""}`);
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="t-dim">Engine shut down after {Number(m.engine_hours ?? 0).toFixed(2)} engine hours.</div>
      <Field label="Outcome">
        <div className="segmented" role="group">
          {["ACCOMPLISHED", "PARTIAL", "ABORTED"].map((o) => (
            <button key={o} type="button" aria-pressed={outcome === o} onClick={() => setOutcome(o)}>
              {words(o)}
            </button>
          ))}
        </div>
      </Field>
      <Field label="Remarks">
        <textarea className="input" value={remarks} onChange={(e) => setRemarks(e.target.value)}
                  placeholder="Task result; anything the engine did" />
      </Field>
      <div>
        <div className="field"><span>Snags (defects observed)</span></div>
        {snags.length === 0 && <div className="t-mute" style={{ marginTop: 6 }}>None reported.</div>}
        {snags.map((s, i) => (
          <div key={i} style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
            <input className="input" style={{ flex: "1 1 260px", width: "auto" }} value={s.description}
                   aria-label={`Snag ${i + 1}`} placeholder="What was observed"
                   onChange={(e) => setSnags(snags.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))} />
            <select className="input" style={{ width: 150 }} value={s.severity} aria-label={`Snag ${i + 1} severity`}
                    onChange={(e) => setSnags(snags.map((x, j) => (j === i ? { ...x, severity: e.target.value } : x)))}>
              {["ADVISORY", "CAUTION", "WARNING", "EMERGENCY"].map((v) => <option key={v} value={v}>{words(v)}</option>)}
            </select>
            <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="checkbox" checked={s.grounding}
                     onChange={(e) => setSnags(snags.map((x, j) => (j === i ? { ...x, grounding: e.target.checked } : x)))} />
              Aircraft unserviceable
            </label>
            <Button kind="quiet" onClick={() => setSnags(snags.filter((_, j) => j !== i))}>Remove</Button>
          </div>
        ))}
        <div style={{ marginTop: 10 }}>
          <Button onClick={() => setSnags([...snags, { description: "", severity: "CAUTION", grounding: false }])}>
            Add a snag
          </Button>
        </div>
      </div>
      {err && <div className="t-body" style={{ color: "var(--alert-warn-ink)" }}>{err}</div>}
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Button kind="primary" large onClick={submit}>Submit debrief</Button>
      </div>
    </div>
  );
}
