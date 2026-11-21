/* PROGNOSTICS -- what the twin predicts, and why.
 *
 * Three answers across the top, each a decision someone takes: how long the
 * engine has left, whether anything abnormal is being detected, and what the
 * maintenance advisory says to do. Below them, the evidence for each: what is
 * pulling health down, how the three detection tiers scored, which faults the
 * models call, and the maintenance plan that follows.
 *
 * Rules kept from the page this replaces (PRD Part 4 s7.4):
 *   - a life estimate is never shown bare: with its interval, or with the
 *     reason it cannot be given;
 *   - the system says when the detection model is less certain than its
 *     calibration floor, and which tier produced the verdict;
 *   - a fault is listed only when it reaches its own decision threshold,
 *     with how often the model is right when it calls that fault.
 */

import { type Snapshot } from "../../lib/api";
import { Callout, Empty, Section } from "../../ui/kit";
import { type Level, Status, alertLevel, words } from "../../ui/status";

const SEVERITY: Record<string, Level> = {
  EMERGENCY: "warning", WARNING: "warning", CAUTION: "caution", ADVISORY: "advisory", INFO: "normal",
};

const cap = (s: string | null | undefined) => (s ? s[0].toUpperCase() + s.slice(1) : "");

function Share({ v }: { v: number }) {
  return (
    <div style={{ height: 8, background: "var(--bg-raised)", border: "1px solid var(--line)",
                  borderRadius: 4, overflow: "hidden" }}>
      <div style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%`, height: "100%",
                    background: "var(--ink-dim)" }} />
    </div>
  );
}

export function PrognosticsPage({ snap }: { snap: Snapshot }) {
  const rul: any = snap.rul;
  const adv: any = snap.twin.advisory ?? {};
  const faults: Record<string, number> = snap.twin.predicted.fault_probability ?? {};
  const f: any = snap.fusion;
  const assessed = (snap.health as any)?.assessment?.state !== "assessing"
    && typeof (snap.health as any)?.chi === "number";
  const md = snap.twin.metadata as any;
  const tboLeft = md.tbo_hours - (md.total_flight_hours - (md.hours_at_last_overhaul ?? 0));
  const e: any = (snap as any).explanation ?? {};
  const contributions: any[] = e.health?.contributions ?? [];
  const cal: Record<string, { threshold: number; precision: number }> = f?.fault_calibration ?? {};
  const called = Object.entries(faults)
    .filter(([k, v]) => v >= (cal[k]?.threshold ?? 0.5))
    .sort((a, b) => b[1] - a[1]);
  const maint: any = (snap as any).maintenance ?? {};

  return (
    <div className="prognostics-page">
      <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: "var(--content-max)" }}>

        <div style={{ display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
                      alignItems: "stretch" }}>
          <Section title="Remaining useful life">
            {rul.reportable ? (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                  <span style={{ fontFamily: "var(--font-num)", fontSize: 36, fontWeight: 600, lineHeight: 1 }}>
                    {Math.round(rul.hours)}</span>
                  <span className="t-dim">engine hours</span>
                </div>
                <div className="t-dim" style={{ marginTop: 6 }}>
                  {Number.isFinite(rul.lower) && Number.isFinite(rul.upper)
                    ? <>between <b className="t-num" style={{ color: "var(--ink)" }}>
                        {Math.round(rul.lower)} and {Math.round(rul.upper)} h</b>,{" "}
                        {(rul.confidence * 100).toFixed(0)} % confidence</>
                    : "No calibrated interval for this estimate."}
                </div>
              </>
            ) : (
              <>
                <Status level="standby" text="Not determinable" size={18} />
                <div className="t-dim" style={{ marginTop: 6 }}>{cap(rul.reason)}</div>
              </>
            )}
            <dl className="dl" style={{ marginTop: 12 }}>
              <dt>To overhaul (TBO)</dt><dd className="t-num">{tboLeft.toFixed(1)} h</dd>
              <dt>Health decline</dt><dd className="t-num">{rul.rate_per_hour != null
                ? `${(rul.rate_per_hour * 1000).toFixed(3)} per 1,000 h` : "—"}</dd>
            </dl>
          </Section>

          <Section title="Detection">
            <Status level={alertLevel(f.level)} size={18}
                    text={`${words(f.level_name)}${f.predictive ? ", predictive" : ""}`} />
            <div className="t-dim" style={{ marginTop: 6 }}>{f.reason}</div>
            <dl className="dl" style={{ marginTop: 12 }}>
              <dt>Fused score</dt><dd className="t-num">{f.score.toFixed(3)}</dd>
            </dl>
          </Section>

          <Section title="Advisory">
            <Status level={SEVERITY[adv.severity] ?? "standby"} size={18} text={words(adv.severity ?? "INFO")} />
            <div style={{ marginTop: 6 }}>{adv.message}</div>
            <dl className="dl" style={{ marginTop: 12 }}>
              <dt>Action</dt><dd>{adv.recommended_action || "—"}</dd>
              <dt>By</dt><dd>{adv.time_to_action || "—"}</dd>
              {adv.fault_codes?.length > 0 && <><dt>Codes</dt><dd className="t-num">{adv.fault_codes.join(", ")}</dd></>}
            </dl>
          </Section>
        </div>

        <div style={{ display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))",
                      alignItems: "start" }}>
          <Section title="What is pulling health down">
            {!assessed ? <Empty>Shown once the engine has been assessed warm.</Empty>
              : contributions.length === 0 ? <Empty>Collecting data…</Empty>
              : !e.attributable ? <Empty>Nothing significant. No subsystem is contributing a measurable loss.</Empty>
              : contributions.map((c: any) => {
                const step = e.share_step_pct ?? 5;
                return (
                  <div key={c.name} style={{ padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 6 }}>
                      <b>{words(c.name)}</b>
                      <span className="t-num">{Math.round((c.share * 100) / step) * step} %</span>
                    </div>
                    <Share v={c.share} />
                    <div className="t-dim" style={{ marginTop: 4 }}>{c.detail}</div>
                  </div>
                );
              })}
          </Section>

          <Section title="How each detector scored">
            <table className="table">
              <thead><tr><th>Tier</th><th className="num">Score</th><th>Meaning</th></tr></thead>
              <tbody>
                <tr><td><b>Limits</b></td><td className="num">{f.s_rule.toFixed(2)}</td>
                  <td className="t-dim">{f.s_rule <= 0 ? "No certified limit crossed"
                    : f.s_rule >= 1 ? "A limit is being exceeded now" : "A limit is in its alert band"}</td></tr>
                <tr><td><b>Statistical</b></td><td className="num">{f.s_statistical.toFixed(2)}</td>
                  <td className="t-dim">{f.statistical_source ?? "—"}</td></tr>
                <tr><td><b>Neural</b></td><td className="num">{f.s_deep.toFixed(2)}</td>
                  <td className="t-dim">{f.deep_source ?? "—"}</td></tr>
              </tbody>
            </table>
            {f.rule_based_fallback && (
              <div style={{ marginTop: 12 }}>
                <Callout level="caution" title="Detection confidence below 55 %">
                  {f.deep_source?.startsWith("Tier-3 network")
                    ? "The network is scoring this engine but is less sure of this operating point than its "
                      + "calibration requires. The scores say how abnormal the engine looks; this says how "
                      + "well the network knows engines like it."
                    : "The trained network is not the tier that produced this score. Treat the verdict as an "
                      + "indication rather than a prediction."}
                </Callout>
              </div>
            )}
          </Section>

          <Section title="Faults the models call">
            {(snap.twin as any)?.predicted?.fault_probability_source && (
              <div className="t-mute" style={{ marginBottom: 8 }}>
                {(snap.twin as any).predicted.fault_probability_source}</div>
            )}
            {called.length === 0 ? <Empty>No fault called. Every class is below its decision threshold.</Empty> : (
              <table className="table">
                <tbody>
                  {called.map(([k, v]) => (
                    <tr key={k}>
                      <td><Status level="caution" text={words(k)} bold={false} /></td>
                      <td className="t-dim">{cal[k]
                        ? `called at ${(cal[k].threshold * 100).toFixed(0)} %, right ${(cal[k].precision * 100).toFixed(0)} % of the time`
                        : ""}</td>
                      <td className="num">{(v * 100).toFixed(0)} %</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>

          <Section title="Maintenance the twin recommends">
            {(maint.actions ?? []).length === 0 ? <Empty>{maint.summary ?? "No maintenance action indicated."}</Empty> : (
              <>
                <div className="t-dim" style={{ marginBottom: 8 }}>{maint.summary}</div>
                <table className="table">
                  <tbody>
                    {maint.actions.map((a: any) => (
                      <tr key={a.action_id}>
                        <td><Status level={SEVERITY[a.severity] ?? "advisory"} bold={false}
                                    text={`${a.action_id} ${a.name}`} />
                          <div className="t-dim" style={{ marginTop: 2 }}>{a.reason}</div></td>
                        <td className="num">{a.due_within_hours != null
                          ? `within ${a.due_within_hours.toFixed(0)} h` : "next scheduled"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="t-mute" style={{ marginTop: 8 }}>
                  Work is recorded on Engine → Maintenance plan, where its effect on health is shown.
                </div>
              </>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}
