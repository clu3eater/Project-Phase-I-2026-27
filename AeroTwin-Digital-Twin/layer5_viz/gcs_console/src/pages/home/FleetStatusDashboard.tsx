import { ArcGauge } from "../../components/Widgets";
import { type Aircraft } from "../../lib/ops";
import { Section, utc } from "../../ui/kit";
import { INK, Status, bandLevel, words } from "../../ui/status";
import "./fleet-status.css";

const number = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;
const hours = (v: number | null) => v == null ? "Not recorded" : `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} h`;
const fraction = (v: unknown) => {
  const n = number(v);
  return n != null && n >= 0 && n <= 1 ? n : null;
};

/** Selected-aircraft records, not the station's unrelated live telemetry.
 * Health is retained from the last assessment; no time series is fabricated. */
export function FleetStatusDashboard({ a, interval }: { a: Aircraft; interval: number }) {
  const h = a.health ?? {};
  const chi = fraction(h.chi);
  const since = number(h.hours_since_inspection);
  const period = number(interval);
  const toInspection = since != null && since >= 0 && period != null && period > 0 ? period - since : null;
  const remaining = number(h.tbo_remaining_hours);
  const total = number(h.tbo_hours);
  const tboUsed = total != null && total > 0 && remaining != null && remaining >= 0 && remaining <= total
    ? total - remaining : null;
  const sorties = number(a.sorties), runs = number(a.ground_runs);
  const activity = [
    { label: "Sorties", count: sorties != null && sorties >= 0 ? sorties : null },
    { label: "Ground runs", count: runs != null && runs >= 0 ? runs : null },
  ];
  const scale = Math.max(1, ...activity.map((x) => x.count ?? 0));
  const band = bandLevel(h.band);

  return <div className="fleet-status-dashboard" aria-label={`${a.tail} status dashboard`}>
    <div className="fleet-status-heading">
      <h2>Status dashboard</h2>
      <span className="t-mute">{h.assessed_utc ? `Health assessed ${utc(h.assessed_utc)}` : "Health assessment time unavailable"}</span>
    </div>
    <FleetReadiness a={a} />
    <div className="fleet-status-grid">
      <Section title="Engine condition">
        <div className="fleet-condition">
          <ArcGauge value={chi} label="health / 100" colour={chi == null ? "var(--ink-mute)" : INK[band]} size={180} />
          <div className="fleet-condition-facts">
            <Status level={chi == null ? "standby" : band} text={chi == null ? "Not assessed" : words(h.band) || "Assessed"} />
            <span className="t-dim">{chi == null ? "Run the engine to assess condition." : `Last assessed health ${(chi * 100).toFixed(1)}%`}</span>
            <span className="t-label">Engine hours</span>
            <strong className="t-num">{hours(number(h.engine_hours))}</strong>
            <div className="fleet-life-track" role="img" aria-label={`Overhaul allowance consumed ${tboUsed == null || total == null ? 'not recorded' : `${Math.round(tboUsed / total * 100)} percent`}`}>
              {Array.from({ length: 20 }, (_, i) => <span key={i} className={tboUsed != null && total != null && (i + 1) / 20 <= tboUsed / total ? "is-used" : ""} />)}
            </div>
            <span className="t-mute">{total != null ? `${hours(total)} overhaul allowance` : "Overhaul allowance unknown"}</span>
          </div>
        </div>
        <p className="fleet-chart-note">Saved engine assessment. Flight release is shown in the readiness cards above.</p>
      </Section>
      <Section title="Subsystem condition" right={<span className="t-mute">Health / 100</span>}>
        <div className="fleet-subsystems">
          {[["thermal", "Thermal"], ["mechanical", "Mechanical"], ["combustion", "Combustion"], ["electrical", "Electrical"]].map(([key, label]) => {
            const value = fraction(h.subsystems?.[key]);
            return <div key={key} className="fleet-subsystem">
              <ConditionRing value={value} label={label} />
              <b>{label}</b>
            </div>;
          })}
        </div>
        <p className="fleet-chart-note">Each ring is an independent health index. These are not shares of a total.</p>
      </Section>
      <Section title="Maintenance outlook">
        <MaintenanceBar label="Next inspection" remaining={toInspection} total={period}
          used={since != null && since >= 0 && toInspection != null ? since : null} />
        <MaintenanceBar label="Before overhaul" remaining={remaining} total={total} used={tboUsed} allowance />
        <p className="fleet-chart-note">Bars show the recorded allowance consumed. Overhaul may also become due at its calendar limit.</p>
      </Section>
      <Section title="Recorded activity" right={<span className="t-mute">Completed runs</span>}>
        <div className="fleet-activity" role="img" aria-label={activity.map((x) => `${x.label}: ${x.count ?? "not recorded"}`).join(", ")}>
          {activity.map((x, i) => <div className="fleet-activity-column" key={x.label}>
            <b className="t-num">{x.count ?? "—"}</b>
            <div className="fleet-activity-track"><div style={{ height: `${(x.count ?? 0) / scale * 100}%`, background: i ? "var(--phys)" : "var(--data)" }} /></div>
            <span>{x.label}</span>
            {x.count === 0 && <span className="t-mute">No completed runs</span>}
          </div>)}
        </div>
        <p className="fleet-chart-note">Aircraft log totals. Bar height compares counts, not flight duration.</p>
      </Section>
    </div>
  </div>;
}

function ConditionRing({ value, label }: { value: number | null; label: string }) {
  return <div className="fleet-ring" role="img" aria-label={`${label} health ${value == null ? "not assessed" : `${(value * 100).toFixed(1)} percent`}`}>
    <svg viewBox="0 0 120 120" aria-hidden="true">
      <circle cx="60" cy="60" r="50" className="fleet-ring-track" />
      {value != null && <circle cx="60" cy="60" r="50" className="fleet-ring-value" pathLength="100"
        strokeDasharray={`${value * 100} 100`} transform="rotate(-90 60 60)" />}
    </svg>
    <span className="t-num">{value == null ? "—" : `${(value * 100).toFixed(1)}%`}</span>
    {value == null && <span className="t-mute">Not assessed</span>}
  </div>;
}

export function FleetReadiness({ a }: { a: Aircraft }) {
  const limited = a.limitations?.max_mission_hours != null || a.limitations?.max_altitude_ft != null;
  const checks = [
    { label: "Maintenance release", symbol: a.released ? "check" : "!", level: a.released ? "normal" : "standby",
      title: a.released ? "Release signed" : "Awaiting release", detail: a.released ? `Signed by ${a.release_by ?? 'maintenance'} · ${utc(a.release_utc)}${a.release_note ? ` · ${a.release_note}` : ''}` : "Maintenance sign-off required before flight." },
    { label: "Operating envelope", symbol: limited ? "!" : "check", level: limited ? "caution" : "standby",
      title: limited ? "Limited operations" : "No recorded limitations", detail: limited ? [a.limitations.max_mission_hours != null ? `Endurance ≤ ${a.limitations.max_mission_hours} h` : '', a.limitations.max_altitude_ft != null ? `Altitude ≤ ${Number(a.limitations.max_altitude_ft).toLocaleString()} ft` : '', a.limitations.note].filter(Boolean).join(' · ') : "Subject to aircraft status and flight release." },
    { label: "Mission assignment", symbol: a.mission ? "→" : "—", level: a.mission ? "advisory" : "standby",
      title: a.mission ? a.mission.id : "Not allotted", detail: a.mission ? `${a.mission.name ?? ''} · ${words(a.mission.status)}` : "No mission assigned to this aircraft." },
  ];
  return <section className="fleet-readiness" aria-label="Airworthiness and mission readiness">
    {checks.map(c => <div className="fleet-readiness-card" key={c.label}>
      <span className="fleet-readiness-symbol" aria-hidden="true">{c.symbol === "check" ? <svg width="24" height="24" viewBox="0 0 24 24"><path d="M5 12l4 4L19 6" fill="none" stroke="currentColor" strokeWidth="2" /></svg> : c.symbol}</span>
      <div><div className="t-label">{c.label}</div><Status level={c.level as "normal" | "standby" | "caution" | "advisory"} text={c.title} />
        <p className="t-dim">{c.detail}</p></div>
    </div>)}
    {a.pending_maintenance.length > 0 && <div className="fleet-pending">Awaiting engine run: {a.pending_maintenance.map(p => p.action_id).join(', ')}. Applied at the next engine run.</div>}
  </section>;
}

function MaintenanceBar({ label, remaining, total, used, allowance = false }: {
  label: string; remaining: number | null; total: number | null; used: number | null; allowance?: boolean;
}) {
  const due = remaining != null && remaining <= 0;
  const near = remaining != null && remaining > 0 && remaining < 10;
  const chartable = used != null && total != null && total > 0;
  const width = chartable ? Math.max(0, Math.min(100, used / total * 100)) : null;
  const text = remaining == null ? "Not recorded" : due
    ? remaining < 0 ? `${hours(Math.abs(remaining))} overdue` : "Due now"
    : `${hours(remaining)} remaining`;
  return <div className="fleet-maintenance">
    <div className="fleet-chart-label"><span>{label}</span>
      <Status level={remaining == null ? "standby" : due || near ? "caution" : "normal"} text={text} bold={false} />
    </div>
    <div className="fleet-meter" role="img" aria-label={`${label}: ${text}${chartable ? `, ${hours(used)} used of ${hours(total)}` : ", progress unavailable"}`}>
      {width != null && <span style={{ width: `${width}%`, background: due || near ? "var(--alert-caut)" : "var(--data)" }} />}
    </div>
    <div className="fleet-chart-label t-mute"><span>{chartable ? `${hours(used)} ${allowance ? "allowance consumed" : "used"}` : "Progress unavailable"}</span><span>{total != null && total > 0 ? `${hours(total)} interval` : "Interval unknown"}</span></div>
  </div>;
}
