/* THE OPERATOR'S DASHBOARD — problem statement section F.
 *
 * Governed by docs/WHO_READS_THIS_SCREEN.md; laid out to the plate in ui/.
 *
 * WHAT IS TAKEN FROM THE PLATE AND WHAT IS NOT
 * --------------------------------------------
 * The LAYOUT is: an arc gauge over a status list, parameter tiles with
 * sparklines, an alert list, indicator bars, and summary panels below.
 *
 * The DATA never is. The plate carries plausible mock numbers — among them a
 * cylinder-head temperature of 135 degC labelled NOMINAL, which on this engine
 * is the certified limit and would be a WARNING. Copying a mockup's numbers
 * into a health monitor is how a demonstration ends up asserting something
 * untrue about an engine.
 *
 * Three panels on the plate have no honest source here and are replaced rather
 * than faked:
 *
 *   "Fault distribution" as a donut of 12 counted faults — we have per-mode
 *   PROBABILITIES, not a fault history to count. Replaced by the per-fault
 *   time-to-action forecast, which is what PS section C actually asks for.
 *
 *   "Reliability 94 %" as a bare percentage — replaced by the mission Go/No-Go
 *   verdicts, which is the same question answered in a form an operator can
 *   act on.
 *
 *   "Engine efficiency 91 %" — our efficiency figure is BSFC deterioration
 *   against the as-new twin, which is near zero on a healthy engine and is not
 *   a percentage of anything. It is shown as what it is.
 *
 * EVERY SLOW NUMBER COMES FROM `snap.display`
 * --------------------------------------------
 * Smoothed, quantised and held still upstream. Raw health, RUL and efficiency
 * move on every frame and are unreadable on a dashboard; the engineer's pages
 * keep reading the raw values, where the noise is data.
 */

import React, { useEffect, useState } from "react";

import { Trend } from "../components/Core";
import { ArcGauge, StatRow } from "../components/Widgets";
import { can, levelColour, levelName, type Snapshot } from "../lib/api";
import { type Aircraft } from "../lib/ops";

import { Button, Section, utc } from "../ui/kit";
import { INK, bandLevel, healthLevel } from "../ui/status";
import { EngineView, EngineIcon, EngineMetricCard } from "../ui/EngineView";

const VERDICT_COLOUR: Record<string, string> = {
  GO: "var(--state-normal)",
  GO_WITH_LIMITS: "var(--alert-caut)",
  NO_GO: "var(--alert-warn)",
};

const withheld = (d: any) => Boolean(d) && d.authorised === false;

function Card(props: {
  scope: string;
  title: string;
  onOpen?: () => void;
  openLabel?: string;
  children: React.ReactNode;
  minHeight?: number;
  bodyStyle?: React.CSSProperties;
}) {
  if (!can(props.scope)) return null;
  return <Section style={{height: "100%", boxSizing: "border-box"}}
    title={<span className="engine-section-title"><EngineIcon name={props.title.includes("health") ? "health" : props.title.includes("parameters") ? "systems" : props.title.includes("trend") ? "wave" : "timing"} />{props.title}</span>}
    right={props.onOpen && <Button kind="quiet" onClick={props.onOpen}>{props.openLabel ?? (props.title === "Real-time parameters" ? "View parameters" : props.title.includes("health") ? "View health" : "View more")} →</Button>}>
      <div className="engine-card-body" style={props.bodyStyle}>{props.children}</div>
    </Section>;
}

function useMediaQuery(q: string): boolean {
  const get = () => typeof window !== "undefined" && !!window.matchMedia?.(q).matches;
  const [on, setOn] = useState(get);
  useEffect(() => {
    const m = window.matchMedia?.(q);
    if (!m) return;
    const f = () => setOn(m.matches);
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, [q]);
  return on;
}

export function OverviewPage({
  snap,
  go,
  canGo,
  aircraft,
  airborne,
}: {
  snap: Snapshot;
  aircraft: Aircraft | null;
  airborne: boolean;
  go: (page: string) => void;
  /* Whether this role has the page a card drills into. A card whose
     detail the role cannot open shows no button, rather than one that
     does nothing. */
  canGo?: (page: string) => boolean;
}) {
  const open = (p: string) => (canGo ? canGo(p) : true) ? () => go(p) : undefined;
  const r: any = snap.twin?.reported ?? {};
  const rows: any[] = snap.twin?.alerts?.active ?? [];
  const rul: any = snap.rul ?? {};
  const surv: any = (snap as any).survival ?? {};
  const mission: any = snap.mission ?? {};
  const maint: any = snap.maintenance ?? {};
  const health: any = snap.health ?? {};
  const d: any = (snap as any).display ?? {};
  const assessment = d.assessment ?? health.assessment ?? {};
  const hasCurrentAssessment = ["live", "held"].includes(assessment.state)
    && typeof health.chi === "number" && Number.isFinite(health.chi);
  const savedHealth: any = aircraft?.health ?? {};
  const shownHealth: any = hasCurrentAssessment ? health : savedHealth;
  const chi = hasCurrentAssessment
    ? (typeof d.chi === "number" && Number.isFinite(d.chi) ? d.chi : health.chi)
    : (typeof savedHealth.chi === "number" && Number.isFinite(savedHealth.chi) ? savedHealth.chi : null);
  const band = hasCurrentAssessment ? (d.band ?? health.band) : savedHealth.band;
  const subsystems: any = shownHealth.subsystems ?? shownHealth;
  const assessedUtc = savedHealth.assessed_utc ?? null;
  const healthProvenance = assessment.state === "live" && hasCurrentAssessment
    ? (airborne ? "Live warm, loaded assessment" : "Live assessment during a ground run")
    : chi != null
      ? `Last warm, loaded assessment${assessedUtc ? ` · ${utc(assessedUtc)}` : " · time unavailable"}`
      : "No qualifying assessment recorded yet";
  const forecasts: any[] = (Array.isArray((snap as any).fault_forecast) ? (snap as any).fault_forecast : [])
    .filter((f: any) => f && f.reportable);

  const v = (m: any) => (m && m.state === "VALID" ? m.value : null);
  // Zone D's alert rail is hidden below 1500 px (theme/tokens.css); only then
  // does the overview carry its own alert card.
  const railHidden = useMediaQuery("(max-width: 1500px)");

  return (
    /* One shared, auto-height dashboard grid for every role. The columns
       reflow to the available work area and the workspace handles vertical
       overflow, so cards keep their full content instead of clipping it. */
    <EngineView title="Engine overview" description={`Condition and live engine readings · ${airborne ? "in flight" : "on the ground"}`}>
    <div className="overview-dashboard">
        {/* ---- engine health overview ---------------------------------- */}
        <Card scope="read:health" title="Engine health"
              onOpen={open("HEALTH")} minHeight={272}>
          <div style={{
            display: "flex", gap: 20, alignItems: "center", flexWrap: "wrap",
          }}>
            <ArcGauge
              value={chi}
              label="health / 100"
              caption={band ?? ""}
              size={200}
              colour={INK[bandLevel(band)]}
            />
            <div style={{ flex: 1, minWidth: 190 }}>
              <StatRow label="Condition" value={chi == null ? "Not assessed" : (band ?? "Assessed")} />
              <div className="t-dim" aria-live="polite">{healthProvenance}</div>
              {chi == null && <div className="t-mute" style={{ marginTop: 8 }}>
                Health is assessed only when the engine is warm, loaded and steady. A parked engine keeps its last recorded assessment.
              </div>}
              {chi != null && assessment.state !== "live" && <div className="t-mute" style={{ marginTop: 8 }}>
                {airborne ? "The twin is holding the last assessed condition while this flight continues." : "No new health score is inferred from cold, idle readings."}
              </div>}
              {hasCurrentAssessment && <StatRow
                label="Trend"
                value={d.chi_direction === "falling" ? "DECLINING"
                  : d.chi_direction === "rising" ? "IMPROVING"
                    : d.chi_direction === "steady" ? "STEADY" : "———"}
                colour={d.chi_direction === "falling"
                  ? "var(--alert-caut)" : undefined}
              />}
              {hasCurrentAssessment && can("read:prognostics") && (
                <StatRow
                  label="Life remaining"
                  value={d.rul_hours == null ? "not yet"
                    : rul.decision_floor_hours != null
                      && Math.round(rul.decision_floor_hours) < d.rul_hours
                      ? `${d.rul_hours} h · plan ${Math.round(rul.decision_floor_hours)} h`
                      : `${d.rul_hours} h`}
                />
              )}
              {hasCurrentAssessment && <StatRow
                label="Extra fuel burn"
                value={d.bsfc_deterioration_pct == null ? "———"
                  : `${d.bsfc_deterioration_pct > 0 ? "+" : ""}${d.bsfc_deterioration_pct}%`}
              />}
              {/* The instruction, last and unmissable: it is the only line
                  here that tells the operator to DO something. */}
              <div style={{
                marginTop: 12, fontSize: 17, fontWeight: 700, lineHeight: 1.4,
              }}>
                {hasCurrentAssessment ? (d.instruction ?? "Review the condition and alerts.") : chi == null
                  ? airborne ? "Health will appear once the twin records a warm, loaded assessment."
                    : "Run the engine warm and under load to record condition."
                  : airborne ? "The current flight is using the last recorded engine condition."
                    : "Use this recorded condition for ground planning."}
              </div>
            </div>
          </div>
        </Card>

        {/* ---- real-time parameters ------------------------------------ */}
        <Card scope="read:telemetry" title={`Current engine readings · ${airborne ? "in flight" : "on the ground"}`}
              onOpen={open("ENGINE")} openLabel="View parameters" minHeight={272}
              bodyStyle={{ overflow: "hidden", padding: 8 }}>
          {/* THE CHANNELS THE TOP BAR DOES NOT CARRY. This card used to lead
              with RPM, CHT, EGT and oil pressure -- the four readouts already
              fixed in Zone B above it -- and ran to seven tiles in three rows
              in a card with room for two, so the last row hid behind MORE
              BELOW. Six channels, three by two, none of them shown twice. */}
          <div className="engine-overview-metrics">
            {[
              {title:"Coolant",node:r.coolant_temperature,unit:"°C",icon:"temperature" as const,digits:1},
              {title:"Oil temperature",node:r.oil_temperature,unit:"°C",icon:"temperature" as const,digits:1},
              {title:"Fuel flow",node:r.fuel_flow,unit:"L/h",icon:"fuel" as const,digits:1},
              {title:"Manifold pressure",node:r.manifold_pressure,unit:"bar",icon:"fuel" as const,digits:2},
              {title:"Vibration",node:{value:r.vibration?.rms_total,state:"VALID"},unit:"m/s²",icon:"wave" as const,digits:2},
              {title:"Bus voltage",node:r.electrical?.bus_voltage,unit:"V",icon:"power" as const,digits:1},
            ].map(metric => {
              const value = v(metric.node);
              return <EngineMetricCard key={metric.title} title={metric.title} icon={metric.icon} unit={metric.unit}
                value={typeof value === "number" && Number.isFinite(value) ? value.toFixed(metric.digits) : "—"}>
                {metric.node?.state && metric.node.state !== "VALID" && <span className="t-mute">{metric.node.state}</span>}
              </EngineMetricCard>;
            })}
          </div>
        </Card>

        {/* ---- active alerts ------------------------------------------- */}
        {railHidden && <Card scope="read:alerts" title="Active alerts"
              onOpen={open("ENGINE")} openLabel="Detail" minHeight={272}>
          {rows.length === 0 ? (
            /* s4.1.1a: a healthy engine says nothing, and says so in words --
               an empty box reads as a broken panel, not as calm. */
            <div style={{ fontSize: 20, fontWeight: 600 }}>
              No active alerts
              <div style={{
                fontSize: 16, color: "var(--ink-dim)", marginTop: 8,
                fontWeight: 400,
              }}>
                Every parameter is inside its limit.
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {/* s5.2.5: warnings above cautions above advisories, most
                  recent first — the same order AlertStack uses, because two
                  screens ranking the same alerts differently teach the
                  operator to distrust both. */}
              {[...rows]
                .sort((a, b) => b.level - a.level || b.first_seen_s - a.first_seen_s)
                .slice(0, 5)
                .map((a: any) => (
                  <div key={a.rule_id} style={{
                    display: "grid", gridTemplateColumns: "9px 1fr auto",
                    gap: 10, alignItems: "start",
                  }}>
                    <span aria-hidden="true" style={{
                      width: 9, height: 9, borderRadius: 9, marginTop: 6,
                      background: levelColour(a.level),
                    }} />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 21, fontWeight: 700 }}>
                        {a.legend}
                      </div>
                      {a.advisory && (
                        <div style={{
                          fontSize: 16, color: "var(--ink-dim)", marginTop: 2,
                        }}>
                          {a.advisory}
                        </div>
                      )}
                    </div>
                    <span style={{
                      fontSize: "var(--size-label)", fontWeight: 700,
                      letterSpacing: "0.05em", color: levelColour(a.level),
                      whiteSpace: "nowrap",
                    }}>
                      {levelName(a.level)}
                    </span>
                  </div>
                ))}
              {rows.length > 5 && (
                <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>
                  +{rows.length - 5} more
                </div>
              )}
            </div>
          )}
        </Card>}

        {/* ---- subsystem indicators ------------------------------------ */}
        <Card scope="read:health" title="Subsystem health"
              onOpen={open("HEALTH")} minHeight={236}>
          <div className="engine-overview-metrics">{[
            {key:"thermal",label:"Thermal",icon:"temperature" as const},
            {key:"mechanical",label:"Mechanical",icon:"wave" as const},
            {key:"combustion",label:"Combustion",icon:"combustion" as const},
            {key:"electrical",label:"Electrical",icon:"power" as const},
          ].map(system => {
            const raw = subsystems[system.key];
            const score = typeof raw === "number" && Number.isFinite(raw) && raw >= 0 && raw <= 1 ? raw : null;
            return <EngineMetricCard key={system.key} title={system.label} icon={system.icon} value={score == null ? "—" : (score * 100).toFixed(1)} unit={score == null ? undefined : "%"}>
              <div className="engine-score-track" role="img" aria-label={`${system.label} health ${score == null ? "not assessed" : `${(score * 100).toFixed(1)} percent`}`}>
                {score != null && <span style={{width:`${score * 100}%`,background:INK[healthLevel(score) ?? "normal"]}} />}
              </div>
            </EngineMetricCard>;
          })}</div>
          <div style={{
            fontSize: 16, color: "var(--ink-mute)", marginTop: 6,
          }}>
            Each is the worst of its sub-indices, not their average.
          </div>
        </Card>

        {/* ---- remaining useful life ----------------------------------- */}
        <Card scope="read:prognostics" title="Remaining useful life"
              onOpen={open("PROGNOSTICS")} minHeight={236}>
          {d.rul_hours == null ? (
            <div style={{ fontSize: 19, color: "var(--ink-dim)" }}>
              Not enough wear yet to predict.
              <div style={{ fontSize: 16, color: "var(--ink-mute)", marginTop: 8 }}>
                {rul.reason}
              </div>
            </div>
          ) : (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{
                  fontFamily: "var(--font-num)", fontSize: 36, fontWeight: 700,
                  lineHeight: 1,
                }}>
                  {d.rul_hours}
                </span>
                <span style={{ fontSize: 18, color: "var(--ink-dim)" }}>hours</span>
              </div>
              {/* s7.4a: the interval travels with the number. Measured
                  coverage on unseen engines is 84–87 % (DEV-105), so the
                  range is the honest half of the prediction. */}
              {/* The interval must belong to the number above it (HMI-06).
                  The physics interval is shown only when physics is the
                  source; the network has no calibrated interval yet, and the
                  card says so instead of borrowing one. */}
              {rul.source !== "lstm" && rul.lower != null && rul.upper != null ? (
                <div style={{ fontSize: 16, color: "var(--ink-dim)", marginTop: 8 }}>
                  could be {Math.round(rul.lower)}–{Math.round(rul.upper)} h
                </div>
              ) : (
                <div style={{ fontSize: 16, color: "var(--ink-dim)", marginTop: 8 }}>
                  network estimate — no calibrated interval
                </div>
              )}
              {rul.decision_floor_hours != null && (
                <div style={{ fontSize: 16, color: "var(--ink-dim)", marginTop: 4 }}>
                  mission and maintenance plan on {Math.round(rul.decision_floor_hours)} h
                </div>
              )}
              {rul.rate_per_hour != null && (
                <div style={{ fontSize: 16, color: "var(--ink-dim)", marginTop: 4 }}>
                  consuming {rul.rate_per_hour.toFixed(2)}× nominal life per hour
                </div>
              )}
            </>
          )}
        </Card>

        {/* ---- will it survive the sortie ------------------------------
            The same question the card above answers, in the form that is
            accurate. Hours-remaining sits near its information ceiling on
            this data; the probability does not, which is why both are shown
            and why this one is worded as the decision rather than as a
            measurement. */}
        <Card scope="read:prognostics" title="Risk this sortie"
              onOpen={open("PROGNOSTICS")} minHeight={236}>
          {!surv.available ? (
            <div style={{ fontSize: 19, color: "var(--ink-dim)" }}>
              Not available.
              <div style={{ fontSize: 16, color: "var(--ink-mute)", marginTop: 8 }}>
                {surv.reason}
              </div>
            </div>
          ) : (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{
                  fontFamily: "var(--font-num)", fontSize: 36, fontWeight: 700,
                  lineHeight: 1,
                  // MIL-STD-411F levels: a one-in-four chance of losing the
                  // engine inside 50 h is a CAUTION -- attention required
                  // before the next launch -- not a WARNING, which is
                  // reserved for something needing action right now.
                  color: (surv.next_sortie_risk ?? 0) >= 0.25
                    ? "var(--alert-caut)" : undefined,
                }}>
                  {Math.round((surv.next_sortie_risk ?? 0) * 100)}%
                </span>
                <span style={{ fontSize: 18, color: "var(--ink-dim)" }}>
                  chance of failure within 50 flight hours
                </span>
              </div>
              <div style={{ fontSize: 16, color: "var(--ink-dim)", marginTop: 10 }}>
                {["12h", "25h", "50h"].map((h) => (
                  <span key={h} style={{ marginRight: 18 }}>
                    {h.replace("h", " h")}{" "}
                    <span style={{ fontFamily: "var(--font-num)", color: "var(--ink)" }}>
                      {surv.horizons?.[h] == null
                        ? "--"
                        : `${Math.round(surv.horizons[h] * 100)}%`}
                    </span>
                    {/* A horizon held at a shorter one's figure is marked, so
                        two identical numbers read as the correction they are
                        rather than as a copied placeholder. */}
                    {surv.held_monotonic?.includes(h) && (
                      <span style={{ color: "var(--ink-mute)" }}>{" ≥"}</span>
                    )}
                  </span>
                ))}
              </div>
              {surv.held_monotonic?.length > 0 && (
                <div style={{ fontSize: 16, color: "var(--ink-mute)", marginTop: 4 }}>
                  ≥ held at the shorter horizon&apos;s figure: each horizon has
                  its own calibrated head, and a longer window cannot be safer
                  than the shorter one it contains.
                </div>
              )}
              {/* A probability built from a handful of readings has a noisy
                  level and spread. Saying so is cheaper than withholding it. */}
              {surv.samples != null && surv.samples < 120 && (
                <div style={{ fontSize: 16, color: "var(--ink-mute)", marginTop: 8 }}>
                  settling: {surv.samples} readings into this sortie
                </div>
              )}
            </>
          )}
        </Card>

        {/* ---- degradation trend --------------------------------------- */}
        <Card scope="read:health" title="Degradation trend"
              onOpen={open("HEALTH")} minHeight={236}>
          {snap.history?.chi ? (
            <Trend series={snap.history.chi as (number | null)[]}
                   label="composite health index" height={140} />
          ) : (
            <div style={{ fontSize: 16, color: "var(--ink-mute)" }}>
              Collecting…
            </div>
          )}
        </Card>

        {/* ---- per-fault time to action -------------------------------- *
         * The plate shows a donut of counted faults. We have per-mode
         * PROBABILITIES and forecasts, not a fault history to count -- and
         * PS section C asks for prediction, which this is.                */}
        <Card scope="read:prognostics" title="Faults needing action"
              onOpen={open("PROGNOSTICS")} minHeight={220}>
          {forecasts.length === 0 ? (
            <div style={{ fontSize: 20, fontWeight: 600 }}>
              None forecast
              <div style={{
                fontSize: 16, color: "var(--ink-dim)", marginTop: 8,
                fontWeight: 400,
              }}>
                No monitored fault is trending towards its action threshold.
              </div>
            </div>
          ) : (
            forecasts.slice(0, 5).map((f: any) => (
              <StatRow
                key={f.mode}
                label={f.mode.replace(/_/g, " ")}
                value={`${Math.round(f.hours_to_action)} h`}
                colour={f.hours_to_action < 25 ? "var(--alert-caut)" : undefined}
              />
            ))
          )}
        </Card>

        {/* ---- mission readiness --------------------------------------- */}
        <Card scope="read:mission" title={airborne ? "Current flight" : "Mission readiness"}
              onOpen={open("MISSION")} openLabel={airborne ? "Mission details" : "Go / No-Go"} minHeight={220}>
          {airborne ? (
            <>
              <StatRow label="Aircraft" value={aircraft?.tail ?? snap.twin.metadata.aircraft_id ?? "—"} />
              <StatRow label="Mission" value={aircraft?.mission?.id ?? aircraft?.mission?.name ?? "Active flight"} />
              <StatRow label="Status" value={aircraft?.mission?.status ?? aircraft?.status ?? "In flight"} />
              <StatRow label="Flight phase" value={typeof r.environmental?.flight_phase === "number"
                ? (["Ground", "Start-up", "Taxi", "Take-off", "Climb", "Cruise", "Descent", "Landing"][r.environmental.flight_phase] ?? "—") : "—"} />
              <StatRow label="Elapsed" value={typeof snap.sortie?.flight_time_s === "number"
                ? `${Math.floor(snap.sortie.flight_time_s / 60)} min` : "—"} />
            </>
          ) : withheld(snap.mission) || !mission.profiles?.length ? (
            <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>
              No mission assessment available.
            </div>
          ) : (
            <>
              {mission.profiles.map((p: any) => (
                <StatRow key={p.profile} label={p.profile}
                         value={p.verdict.replace(/_/g, " ")}
                         colour={VERDICT_COLOUR[p.verdict]} />
              ))}
              {mission.limiting_subsystem && (
                <div style={{
                  fontSize: 16, color: "var(--ink-mute)", marginTop: 8,
                }}>
                  limiting subsystem: {mission.limiting_subsystem}
                </div>
              )}
            </>
          )}
        </Card>

        {/* ---- maintenance --------------------------------------------- */}
        <Card scope="read:advisory" title="Maintenance due"
              onOpen={open("PROGNOSTICS")} minHeight={220}>
          {withheld(snap.maintenance) || !maint.actions?.length ? (
            <div style={{ fontSize: 20, fontWeight: 600 }}>
              Nothing due
              <div style={{
                fontSize: 16, color: "var(--ink-dim)", marginTop: 8,
                fontWeight: 400,
              }}>
                No maintenance action is currently advised.
              </div>
            </div>
          ) : (
            <>
              <div style={{ fontSize: 21, fontWeight: 700, marginBottom: 10 }}>
                {maint.actions[0].name}
              </div>
              {maint.actions[0].due_within_hours != null && (
                <StatRow label="Due within"
                         value={`${Math.round(maint.actions[0].due_within_hours)} flight h`} />
              )}
              {maint.actions[0].cost_inr != null && (
                <StatRow label="Cost"
                         value={`Rs ${maint.actions[0].cost_inr.toLocaleString()}`} />
              )}
              {maint.actions.length > 1 && (
                <div style={{
                  fontSize: 16, color: "var(--ink-dim)", marginTop: 8,
                }}>
                  +{maint.actions.length - 1} more on the plan
                </div>
              )}
            </>
          )}
        </Card>
    </div>
    </EngineView>
  );
}
