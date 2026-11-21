import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { type Board, opsGet, opsPost } from "../../lib/ops";
import { Button, Drawer, Empty, Field, Result, utc } from "../../ui/kit";
import { Status, verdictLevel, words } from "../../ui/status";
import { AIRBASES, greatCircleKm } from "../../data/airbases";
import { MissionMap } from "../../components/MissionMap";
import { Playback } from "../../mission/clock";
import { buildPlan, expand, MISSION_TYPES, TYPE_BY_KEY } from "../../mission/plan";
import "./mission-planning.css";

const percent = (v: unknown) => typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1 ? `${Math.round(v * 100)} / 100` : "Unavailable";
const numeric = (v: unknown) => typeof v === "number" && Number.isFinite(v);

export function PlanDrawer({ board, onClose, onPlanned }: { board: Board; onClose: () => void; onPlanned: (m: any, preferredTail: string) => void }) {
  const first = Object.keys(board.mission_types)[0] ?? "";
  const defaults = board.mission_types[first] ?? {};
  const [plan, setPlan] = useState<any>({ type: first, name: "", area: "", launch_utc: "", priority: "ROUTINE", notes: "",
    duration_h: defaults.duration_h ?? "", altitude_ft: defaults.altitude_ft ?? "", environment: defaults.environment ?? "STANDARD" });
  const initialTail = board.active_tail && board.aircraft.some(a => a.tail === board.active_tail)
    ? board.active_tail : board.aircraft[0]?.tail ?? "";
  const [preferredTail, setPreferredTail] = useState(initialTail);
  const [departureId, setDepartureId] = useState("VIJO");
  const [recoveryId, setRecoveryId] = useState("VIUT");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const pending = useRef(false);
  const playback = useRef(new Playback());
  const set = (k: string, v: any) => { setPlan((p: any) => ({ ...p, [k]: v })); setErr(null); };
  const valid = !!first && !!preferredTail && plan.duration_h !== "" && Number.isFinite(Number(plan.duration_h)) && Number(plan.duration_h) >= .25 && Number(plan.duration_h) <= 40
    && plan.altitude_ft !== "" && Number.isFinite(Number(plan.altitude_ft)) && Number(plan.altitude_ft) >= 1000 && Number(plan.altitude_ft) <= 25000;
  const departure = AIRBASES.find(b => b.id === departureId) ?? AIRBASES[0];
  const recovery = AIRBASES.find(b => b.id === recoveryId) ?? AIRBASES[1] ?? AIRBASES[0];
  const missionType = MISSION_TYPES.find(t => t.profile === plan.type) ?? TYPE_BY_KEY[plan.type] ?? TYPE_BY_KEY.TRANSIT;
  const routePlan = useMemo(() => buildPlan(missionType, departure, recovery, {
    name: plan.name.trim() || missionType.label,
  }), [missionType, departure, recovery, plan.name]);
  const expansion = useMemo(() => expand(routePlan), [routePlan]);
  const routeArea = `Route: ${departure.name} (${departure.id}) → ${recovery.name} (${recovery.id})${plan.area.trim() ? ` · Area: ${plan.area.trim()}` : ""}`;
  const profile = { ...plan, name: plan.name.trim() || board.mission_types[plan.type]?.label,
    area: routeArea, duration_h: Number(plan.duration_h), altitude_ft: Number(plan.altitude_ft) };
  const submit = async () => {
    if (!valid || pending.current) return;
    pending.current = true; setBusy(true); setErr(null);
    try { onPlanned(await opsPost("/api/ops/missions", profile), preferredTail); }
    catch (e: any) { setErr(e.message); }
    finally { pending.current = false; setBusy(false); }
  };
  return <Drawer open title="Plan a mission" sub="Choose the aircraft, task, departure and recovery fields."
    onClose={() => { if (!busy) onClose(); }} footer={<>
      <Button kind="quiet" disabled={busy} onClick={onClose}>Cancel</Button>
      <Button kind="primary" disabled={!valid || busy} onClick={submit}>
        {busy ? "Saving mission…" : "Plan mission"}</Button>
    </>}>
    <div className="planning-mission-layout">
      <div className="planning-mission-fields">
        <Field label="Mission task" hint="Task presets fill the endurance, altitude and route preview.">
          <select className="input" value={plan.type} onChange={e => {
            const t = board.mission_types[e.target.value];
            setPlan({ ...plan, type: e.target.value, duration_h: t.duration_h, altitude_ft: t.altitude_ft, environment: t.environment ?? "STANDARD" });
            setErr(null);
          }}>{Object.entries(board.mission_types).map(([k, t]: any) => <option value={k} key={k}>{t.label}</option>)}</select>
        </Field>
        <Field label="Mission name" hint="Leave blank to use the task name."><input className="input" value={plan.name} onChange={e => set("name", e.target.value)} /></Field>
        <Field label="UAV" hint="This is your requested aircraft. Mission-specific eligibility is checked before assignment approval.">
          <select className="input" value={preferredTail} onChange={e => { setPreferredTail(e.target.value); setErr(null); }}>
            <option value="">Choose a UAV</option>
            {board.aircraft.map(a => <option value={a.tail} key={a.tail}>{a.tail} · {a.engine_name || a.engine_key}</option>)}
          </select>
        </Field>
        <div className="planning-fields">
          <Field label="Planned endurance (h)" hint="0.25–40 h; used for suitability, not fuel planning."><input className="input" type="number" min="0.25" max="40" step="0.25" value={plan.duration_h} onChange={e => set("duration_h", e.target.value)} /></Field>
          <Field label="Cruise altitude (ft)" hint="1,000–25,000 ft."><input className="input" type="number" min="1000" max="25000" step="100" value={plan.altitude_ft} onChange={e => set("altitude_ft", e.target.value)} /></Field>
        </div>
        <Field label="Operating conditions"><select className="input" value={plan.environment} onChange={e => set("environment", e.target.value)}>
          {board.environments.map(x => <option key={x} value={x}>{words(x)}</option>)}</select></Field>
        <Field label="Priority"><div className="segmented" role="group" aria-label="Priority">
          {["ROUTINE", "PRIORITY", "IMMEDIATE"].map(p => <button type="button" key={p} aria-pressed={plan.priority === p} onClick={() => set("priority", p)}>{words(p)}</button>)}
        </div></Field>
        <Field label="Planned launch brief (UTC)" hint="Crew coordination only; launch still needs operator checks and clearance."><input className="input" value={plan.launch_utc} placeholder="e.g. 28 Oct 0600Z" onChange={e => set("launch_utc", e.target.value)} /></Field>
      </div>
      <section className="planning-route-panel" aria-label="Mission route preview">
        <div className="planning-section-head"><h3 className="planning-title">Route</h3><span className="t-dim">{Math.round(greatCircleKm(departure.lat_deg, departure.lon_deg, recovery.lat_deg, recovery.lon_deg))} km direct</span></div>
        <div className="planning-route-fields">
          <Field label="Source / departure"><select className="input" value={departureId} onChange={e => { setDepartureId(e.target.value); setErr(null); }}>
            {AIRBASES.map(b => <option key={b.id} value={b.id}>{b.name} · {b.id}</option>)}
          </select></Field>
          <button className="planning-route-swap" type="button" aria-label="Swap source and destination" title="Swap source and destination"
            onClick={() => { setDepartureId(recoveryId); setRecoveryId(departureId); setErr(null); }}>⇄</button>
          <Field label="Destination / recovery"><select className="input" value={recoveryId} onChange={e => { setRecoveryId(e.target.value); setErr(null); }}>
            {AIRBASES.map(b => <option key={b.id} value={b.id}>{b.name} · {b.id}</option>)}
          </select></Field>
        </div>
        <div className="planning-map-preview">
          <MissionMap
            points={routePlan.points} patrols={expansion.patrols} routeLine={expansion.waypoints}
            selectedId={null} onSelect={() => {}} onAddPoint={() => {}} onMovePoint={() => {}}
            onBaseAction={(base, role) => {
              if (role === "DEPARTURE") setDepartureId(base.id);
              if (role === "RECOVERY") setRecoveryId(base.id);
            }} alternateId={routePlan.alternate_id} playback={playback.current}
            height="100%" stage="PLAN" editable={false} selectBases baseActions={["DEPARTURE", "RECOVERY"]} clickIntent="select"
          />
        </div>
        <p className="planning-map-hint">Simulation map preview. Click an airfield to set the source or destination. The line is indicative, not a validated flight plan.</p>
      </section>
    </div>
    <div className="planning-extra-fields">
      <Field label="Task area or route brief" hint="Optional briefing text saved with the mission."><input className="input" maxLength={80} value={plan.area} onChange={e => set("area", e.target.value)} /></Field>
      <Field label="Notes for the crew"><textarea className="input" value={plan.notes} onChange={e => set("notes", e.target.value)} /></Field>
    </div>
    {!preferredTail && <div className="planning-note" role="status">Choose a UAV before planning this mission.</div>}
    {(plan.duration_h === "" || !Number.isFinite(Number(plan.duration_h)) || Number(plan.duration_h) < .25 || Number(plan.duration_h) > 40
      || plan.altitude_ft === "" || !Number.isFinite(Number(plan.altitude_ft)) || Number(plan.altitude_ft) < 1000 || Number(plan.altitude_ft) > 25000)
      && <div className="planning-note" role="status">Enter an endurance of 0.25–40 h and an altitude of 1,000–25,000 ft to continue.</div>}
    <div className="planning-note"><b>Demonstration scope</b><br />Suitability uses the planned endurance. The demonstration cruise is {Math.round(board.simulated_cruise_hours * 60)} minutes of simulated engine time. Weather, fuel, payload, airspace and route feasibility are not validated by this form.</div>
    {err && <Result msg={{ ok: false, text: err }} />}
  </Drawer>;
}

export function AllotDrawer({ m, board, onClose, onDone, cancel, preferredTail }: { m: any; board: Board; onClose: () => void; onDone: (text: string, ok?: boolean) => void; cancel?: ReactNode; preferredTail?: string }) {
  const [cands, setCands] = useState<any[] | null>(null);
  const [tail, setTail] = useState(m.tail ?? preferredTail ?? "");
  const [operator, setOperator] = useState(m.operator ?? "");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const pending = useRef(false);
  useEffect(() => {
    let active = true;
    setCands(null); setErr(null);
    opsGet(`/api/ops/missions/${m.id}/candidates`).then(c => { if (active) setCands(c); }).catch(e => { if (active) setErr(e.message); });
    return () => { active = false; };
  }, [m.id, refresh]);
  const selected = cands?.find(c => c.tail === tail);
  const canApprove = !!selected?.eligible && board.operators.includes(operator) && !busy;
  const approve = async () => {
    if (!canApprove || pending.current) return;
    pending.current = true; setBusy(true); setErr(null);
    try { await opsPost(`/api/ops/missions/${m.id}/approve`, { tail, operator, note }); onDone(`${m.id} approved: ${tail} allotted to ${operator}. Operator preflight and launch clearance are still required.`); }
    catch (e: any) { setErr(e.message); }
    finally { pending.current = false; setBusy(false); }
  };
  return <Drawer open title={`${m.status === "APPROVED" ? "Re-allot" : "Assign aircraft"} · ${m.id}`} sub={m.name}
    onClose={() => { if (!busy) onClose(); }} footer={<>
      <Button kind="quiet" disabled={busy} onClick={onClose}>Close</Button>
      <Button kind="primary" disabled={!canApprove} onClick={approve}>
        {busy ? "Approving…" : !selected?.eligible ? "Select available aircraft" : !operator ? "Select operator" : "Approve assignment"}</Button>
    </>}>
    <div className="planning-section-head"><h3 className="planning-title">Choose aircraft</h3><Button disabled={busy || !cands && !err} onClick={() => setRefresh(n => n + 1)}>Refresh</Button></div>
    <p className="planning-explanation">Choose an available aircraft. Expand a row for engine details or the reason it is unavailable.</p>
    {!cands ? <Empty>{err ? "Assessment unavailable. Refresh to try again." : "Loading mission-specific aircraft assessments…"}</Empty> : cands.length === 0 ? <Empty>No aircraft are registered.</Empty> : <>
      {!cands.some(c => c.eligible) && <div className="planning-note" role="status">No aircraft can be assigned to this mission.</div>}
      <div className="planning-candidates" role="radiogroup" aria-label="Aircraft and installed engine">
        {cands.map(c => <article className={`planning-candidate ${tail === c.tail ? "is-selected" : ""}`} key={c.tail}>
          <div className="planning-candidate-main">
            <label className="planning-candidate-choice">
              <input type="radio" name={`aircraft-${m.id}`} aria-label={`Select ${c.tail}`} checked={tail === c.tail} disabled={!c.eligible} onChange={() => setTail(c.tail)} />
              <span className="planning-candidate-name"><b>{c.tail}</b><span className="t-dim">{c.engine ?? board.aircraft.find(a => a.tail === c.tail)?.engine_name ?? "Engine model unavailable"}</span></span>
            </label>
            <span className={`planning-availability ${c.eligible ? "is-available" : "is-unavailable"}`}>
              {c.eligible ? "Can assign" : "Unavailable"}
            </span>
          </div>
          <details className="planning-candidate-more">
            <summary>{c.eligible ? "More info" : "Why unavailable"}</summary>
            <Candidate c={c} aircraft={board.aircraft.find(a => a.tail === c.tail)} />
          </details>
        </article>)}
      </div>
    </>}
    <Field label="Assign operator"><select className="input" value={operator} onChange={e => setOperator(e.target.value)}><option value="">Choose an operator</option>{board.operators.map(o => <option key={o} value={o}>{o}</option>)}</select></Field>
    {board.operators.length === 0 && <div className="planning-note">No operators available. Add an operator account in Admin before assigning this mission.</div>}
    <details className="planning-optional-note">
      <summary>Optional approval note</summary>
      <Field label="Note for the record"><textarea className="input" value={note} onChange={e => setNote(e.target.value)} /></Field>
    </details>
    <p className="planning-map-hint">Eligibility is checked again when you approve. Operator preflight and launch clearance are still required.</p>
    {err && <Result msg={{ ok: false, text: err }} />}
    {cancel}
  </Drawer>;
}

function Candidate({ c, aircraft }: { c: any; aircraft?: Board["aircraft"][number] }) {
  const ass = c.assessment ?? {};
  const score = ass.success_probability;
  const scored = numeric(score) && score >= 0 && score <= 1;
  const health = c.health?.chi;
  return <div className="planning-candidate-detail">
    <div className="planning-section-head">
      <span className="t-dim">{aircraft?.twin_id ? `Engine serial ${aircraft.twin_id}` : "Engine serial unavailable"}{!c.engine_validated && " · Unvalidated engine model"}</span>
      {c.recommended && <span className="t-label">Recommended</span>}
    </div>
    <Status level={verdictLevel(ass.verdict ?? "NOT_ASSESSED")} text={`Model: ${words(ass.verdict ?? "NOT_ASSESSED")}`} />
    <div className="planning-score"><div className="planning-section-head"><span>Heuristic suitability score</span><b className="t-num">{percent(score)}</b></div>
      <div className="planning-score-track" role="img" aria-label={`Heuristic suitability score ${percent(score)}`}>{scored && <span style={{ width: `${score * 100}%` }} />}</div></div>
    <div className="planning-candidate-facts"><span>Saved health: {numeric(health) && health >= 0 && health <= 1 ? `${Math.round(health * 100)}%` : "Not assessed"}</span>
      <span>{ass.assessed_utc ? `Condition saved ${utc(ass.assessed_utc)}` : "No assessment time available"}</span></div>
    {c.problems?.length > 0 && <div><b>Unavailable because</b><ul>{c.problems.map((p: string, i: number) => <li key={i}>{p}</li>)}</ul></div>}
    {!c.eligible && !c.problems?.length && <div>This aircraft does not meet the assignment rules for this mission.</div>}
    {ass.reasons?.length > 0 && <div><b>Assessment reasons</b><ul>{ass.reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul></div>}
    {ass.recommendations?.length > 0 && <div><b>Model advice</b><ul>{ass.recommendations.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul></div>}
    {ass.verdict === "NOT_ASSESSED" && <div className="planning-note">Engine suitability is unknown. A warm, loaded engine run is needed for an assessment.</div>}
  </div>;
}
