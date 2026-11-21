/* HEALTH -- the engine's condition, ISA-101 Level 2 for the engine.
 *
 * One answer at the top (how healthy is it, and what should be done), the
 * four subsystems beside it, then the evidence in the order an engineer
 * checks it: the nine sub-indices, the trend, fuel efficiency, the battery.
 *
 * Quiet when normal: every figure is ink; a symbol appears only on a figure
 * that needs looking at. The page scrolls as one document instead of nine
 * boxes each clipping its own content behind "more below".
 *
 * The condition is judged only warm, loaded and steady (thresholds.yaml
 * health.assessment). Before the first such judgement there is no condition
 * to show and none is invented; after it, a stopped engine shows the last
 * judgement, said to be held.
 */

import { useState } from "react";
import { Trend } from "../../components/Core";
import { type Snapshot } from "../../lib/api";
import { type Aircraft } from "../../lib/ops";
import { Button, Empty, Section, Stat, utc } from "../../ui/kit";
import { EngineView } from "../../ui/EngineView";
import { HealthSummary } from "./HealthSummary";
import { Status, healthLevel, words } from "../../ui/status";
import { useDamped, useDampedRecord } from "../../lib/damp";
import { HealthIndices } from "./HealthIndices";
import { CompareToAsNew, Figure, NoTrace } from "./HealthFigures";
import { SohScale } from "./SohScale";

/* THE BATTERY, HELD ONCE FOR THE WHOLE PAGE.
 *
 * Pack state of health is an estimate over many samples and pack resistance is
 * a fitted quantity; neither can genuinely move twice a second, yet measured on
 * a settled engine the state-of-health figure rewrote on 45 % of frames and
 * resistance on 65 %.
 *
 * It is held HERE rather than inside the Battery card because the same pack
 * resistance is printed in two places -- the Battery card and the power-flow
 * schematic, which reads the battery straight off the snapshot. Damping it in
 * the card alone left the schematic's copy moving on 72 % of frames while the
 * card beside it sat still: one number, two figures, disagreeing. Two
 * independent holds would not fix that either, since they can adopt on
 * different frames. One hold, placed above both consumers, and the held pack is
 * put back on the snapshot so every reader downstream sees the same numbers.
 *
 * The verdict word (HEALTHY / MONITOR / REPLACE) is the snap key, so a pack
 * crossing its replacement point is shown at once. */
function useHeldBattery(snap: Snapshot): Snapshot {
  const raw: any = (snap as any).battery ?? null;
  const verdict = raw?.soh == null ? null
    : raw.soh < 0.3 ? "warning" : raw.soh < 0.6 ? "caution" : "normal";
  const d = useDampedRecord({
    soh: { value: raw?.soh, deadband: 0.005, band: verdict },
    ri: { value: raw?.internal_resistance_mohm, deadband: 1.0 },
    ocv: { value: raw?.open_circuit_v, deadband: 0.02 },
    conf: { value: raw?.confidence, deadband: 0.02 },
  });
  if (!raw) return snap;
  return {
    ...(snap as any),
    battery: {
      ...raw,
      soh: d.soh ?? raw.soh,
      internal_resistance_mohm: d.ri ?? raw.internal_resistance_mohm,
      open_circuit_v: d.ocv ?? raw.open_circuit_v,
      confidence: d.conf ?? raw.confidence,
    },
  } as Snapshot;
}

export function HealthPage({ snap: rawSnap, limits, aircraft, onFocusPart }: {
  snap: Snapshot; limits: any;
  aircraft: Aircraft | null;
  /** Ask for an engine component on the 3D model, which lives on the
   *  Parameters view. Provided by the shell, which also does the move. */
  onFocusPart?: (componentId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const snap = useHeldBattery(rawSnap);
  const rawH = snap.health as any;
  const assessment = snap.display?.assessment ?? rawH.assessment ?? {};
  const savedHealth: any = aircraft?.health ?? {};
  const hasCurrentAssessment = ["live", "held"].includes(assessment.state)
    && typeof rawH.chi === "number" && Number.isFinite(rawH.chi);
  const selectedHealth: any = hasCurrentAssessment ? rawH
    : { ...savedHealth, ...(savedHealth.subsystems ?? {}) };
  const recordedAt = savedHealth.assessed_utc ? utc(savedHealth.assessed_utc) : null;
  const rawChi = typeof selectedHealth.chi === "number" ? selectedHealth.chi : null;
  const band = rawChi == null ? undefined : limits?.chi_bands?.find((b: any) => rawChi >= b.min);
  /* THE HEADLINE NUMBER, HELD STILL.
   *
   * Measured on a steady cruise, "ENGINE HEALTH 97.4 %" rewrote its tenth digit
   * on 76 % of frames -- three times a second -- and so did the "7.4 to give
   * before Good" line derived from it. Health does not change three times a
   * second; that is noise arriving through the score. 0.2 pp is below any
   * actionable resolution, and the band word is computed from the RAW score and
   * passed as the snap key, so the instant the score crosses a band edge the
   * displayed figure snaps to it and the two can never disagree. */
  const chi = useDamped(rawChi, { deadband: 0.002, band: band?.label ?? null });

  /* THE FOUR SUBSYSTEM INDICES, DAMPED ONCE AND SHARED.
   *
   * Measured, these rewrote on 72-91 % of frames, and because the health-by-
   * system list is sorted worst-first, noise also kept RESHUFFLING the order of
   * two subsystems sitting a tenth of a point apart.
   *
   * Damped here rather than inside each consumer: the same subsystem number is
   * printed both in the health-by-system list and on its own driver card, and
   * two independent holds on one source can adopt on different frames and so
   * print two different figures for the same thing on the same page. One hold,
   * one number, passed to both. The level word (healthy / caution / warning) is
   * the snap key, so a subsystem changing state is shown at once. */
  const dSub = useDampedRecord({
    thermal: { value: typeof selectedHealth.thermal === "number" ? selectedHealth.thermal : null,
               deadband: 0.002, band: healthLevel(selectedHealth.thermal) ?? "ok" },
    mechanical: { value: typeof selectedHealth.mechanical === "number" ? selectedHealth.mechanical : null,
                  deadband: 0.002, band: healthLevel(selectedHealth.mechanical) ?? "ok" },
    electrical: { value: typeof selectedHealth.electrical === "number" ? selectedHealth.electrical : null,
                  deadband: 0.002, band: healthLevel(selectedHealth.electrical) ?? "ok" },
    combustion: { value: typeof selectedHealth.combustion === "number" ? selectedHealth.combustion : null,
                  deadband: 0.002, band: healthLevel(selectedHealth.combustion) ?? "ok" },
  });
  const h: any = {
    ...selectedHealth,
    assessment: hasCurrentAssessment ? assessment : rawChi != null ? {
      state: "held", age_s: null,
      reason: `Last warm, loaded assessment${recordedAt ? ` recorded ${recordedAt}` : "; time unavailable"}.`,
    } : assessment,
    ...(dSub.thermal != null ? { thermal: dSub.thermal } : {}),
    ...(dSub.mechanical != null ? { mechanical: dSub.mechanical } : {}),
    ...(dSub.electrical != null ? { electrical: dSub.electrical } : {}),
    ...(dSub.combustion != null ? { combustion: dSub.combustion } : {}),
  };

  /* TELL THE OPERATOR WHAT TO DO, NOT WHICH BRANCH THE LOGIC TOOK.
   *
   * This used to render `band.action`, which is the machine token -- "none",
   * "monitor", "maintain_within_25h" -- so a healthy engine displayed the bare
   * word "None" under its band, with no label, reading like a bug. Every band
   * in configs/thresholds.yaml carries `instruction` right beside `action`,
   * with a comment saying why they live together: `action` "is the machine
   * token the advisory logic branches on", `instruction` "is what the OPERATOR
   * is told to do". The instruction is the one for a screen. */
  const instruction: string = band?.instruction
    ?? (band?.action ? words(String(band.action).replace(/_/g, " ")) : "")
    ?? "";

  return (
    /* NO --content-max HERE, AND THAT IS DELIBERATE.
     *
     * The token holds prose to a readable measure and seven other pages want
     * it. This one is an instrument panel: its longest string is "Head and
     * coolant temperature against the as-new model", and the things that want
     * room are scales, bars and traces. Measured at the zoom this station is
     * actually run at -- 80 %, so a 2400x1310 viewport and a 2064 px work area
     * -- the 1480 px cap was throwing away 584 px of width while the content
     * stopped 314 px short of the bottom: about half the work area empty. The
     * cap goes; the token stays exactly as it is for everyone else. */
    <EngineView title="Engine health" description="Condition, system health and recorded trend.">
    <div className="health-page" style={{ minWidth: 0 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        <HealthSummary chi={chi} h={h} instruction={instruction} />
        {assessment.state !== "live" && chi != null && <div className="t-dim">
          Last warm, loaded assessment · {recordedAt ?? "recording time unavailable"}
        </div>}

        {/* BAND 2 -- the four subsystems, across the full width.
            Each one carries the measurement its score was made from, which is
            what turns the rest of the screen from empty into evidence. They
            fall to 2x2 on a narrower station without anything being told to. */}
        <Section title="What sets this score" right={<Button kind="quiet" onClick={() => setExpanded(v => !v)}
          ariaExpanded={expanded} ariaControls="health-score-details">{expanded ? "View less" : "View more"} {expanded ? "−" : "+"}</Button>}>
          {!expanded && <div className="t-dim">View the measurements, score weights and supporting evidence.</div>}
          {expanded && <div id="health-score-details">{chi == null ? <Empty>Shown once the engine has been assessed.</Empty>
            : !hasCurrentAssessment ? <Empty>The saved record includes the composite and subsystem scores. Per-channel evidence is available during the current engine session.</Empty>
            : <HealthIndices h={h} snap={snap} limits={limits}
                             onFocusPart={onFocusPart} />}</div>}
        </Section>

        {/* BAND 3 -- the session trend and the two standing measurements, side
            by side rather than stacked in a narrow column where each kept a
            third of its own box empty. */}
        {/* Natural heights, not stretched to the tallest. Stretching made the
            two standing measurements 61 % empty to match the trend card next to
            them, which is the fault this pass exists to remove -- a ragged
            bottom edge is the honest shape of three cards with different
            amounts to say. */}
        <div style={{ display: "grid", gap: "var(--space-3)", alignItems: "start",
                      gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))" }}>
          <Section title="Trend">
            {/* The chart belongs with the onset and CUSUM figures it supports.
                A held engine no longer spends a band saying nothing -- Trend
                states a flat series in words and draws no chart at all. */}
            {chi != null && (
              <div style={{ marginBottom: "var(--space-3)" }}>
                <Trend series={snap.history.chi.map(v => typeof v === "number" && Number.isFinite(v) ? v * 100 : null)}
                       unit="%" label="Health, this session"
                       height={150} colour="var(--ink-dim)" />
              </div>
            )}
            {expanded && <dl className="dl">
              <dt>Degradation onset</dt>
              <dd className="t-num">{snap.trend.onset_hours != null
                ? `${(snap.trend.onset_hours as number).toFixed(2)} engine h` : "Not detected"}</dd>
              <dt>CUSUM</dt>
              <dd className="t-num">{(snap.trend.cusum as number)?.toFixed(3) ?? "—"}</dd>
              <dt>Health, smoothed</dt>
              <dd className="t-num">{typeof snap.trend.chi_ema === "number" && chi != null
                ? `${((snap.trend.chi_ema as number) * 100).toFixed(1)} %` : "—"}</dd>
            </dl>}
            {!expanded && <p className="t-dim">A held assessment reflects the last warm, loaded engine run.</p>}
          </Section>
          {expanded && <Efficiency snap={snap} />}
          {expanded && <Battery snap={snap} />}
        </div>
      </div>
    </div>
    </EngineView>
  );
}

/* Fuel efficiency against the as-new engine at the same operating point
 * (PS section F). The deterioration, not the absolute figure: climb and
 * loiter differ by more than a worn engine differs from a new one. Fuel flow
 * is measured; shaft power is the twin's estimate, since the aircraft has no
 * torque sensor. */
function Efficiency({ snap }: { snap: Snapshot }) {
  const raw: any = (snap as any).efficiency ?? {};
  /* Fuel burn is an integrated quantity and moves slowly; measured, specific
   * fuel use still rewrote on 89 % of frames and thermal efficiency on 63 %.
   * Deadbands are a tenth of a percentage point and half a gram -- finer than
   * anything these figures are read to. */
  const d = useDampedRecord({
    bsfc: { value: raw.bsfc_g_per_kwh, deadband: 0.5 },
    thermal: { value: raw.thermal_efficiency, deadband: 0.001 },
    det: { value: raw.bsfc_deterioration_pct, deadband: 0.2 },
    excess: { value: raw.excess_fuel_lph, deadband: 0.02 },
  });
  const e: any = {
    ...raw,
    bsfc_g_per_kwh: d.bsfc ?? raw.bsfc_g_per_kwh,
    thermal_efficiency: d.thermal ?? raw.thermal_efficiency,
    excess_fuel_lph: d.excess ?? raw.excess_fuel_lph,
  };
  const det: number | null = d.det ?? (raw.bsfc_deterioration_pct ?? null);
  return (
    <Section title="Fuel efficiency" right={<span className="t-mute">fuel flow measured, power estimated</span>}>
      {e.bsfc_g_per_kwh == null ? (
        <NoTrace what="Not available at this operating point."
                 why={e.reason ?? undefined} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
          <Stat label="Fuel burn vs as-new"
                value={det == null ? "—" : det > 10
                  ? <Status level="caution" text={`+${det.toFixed(1)} %`} size={20} />
                  : `${det > 0 ? "+" : ""}${det.toFixed(1)} %`}
                sub={e.excess_fuel_lph != null
                  ? `${e.excess_fuel_lph > 0 ? "+" : ""}${e.excess_fuel_lph.toFixed(2)} L/h at this power` : undefined} />
          {/* Two bars on one scale rather than two numbers in a list: the
              question is whether this engine is burning more than a new one
              WOULD HAVE at the same operating point, and that is a comparison,
              not a reading. A trend of it answers something else. */}
          <Figure name="Specific fuel use" value={e.bsfc_g_per_kwh.toFixed(1)} unit="g/kWh">
            <CompareToAsNew now={e.bsfc_g_per_kwh} asNew={e.bsfc_as_new_g_per_kwh}
                            unit="g/kWh" digits={1} betterIsLower />
          </Figure>
          {e.thermal_efficiency != null && (
            <Figure name="Thermal efficiency"
                    value={(100 * e.thermal_efficiency).toFixed(1)} unit="%">
              <CompareToAsNew now={100 * e.thermal_efficiency}
                              asNew={e.thermal_as_new != null ? 100 * e.thermal_as_new : null}
                              unit="%" digits={1} betterIsLower={false} />
            </Figure>
          )}
        </div>
      )}
    </Section>
  );
}

/* Battery state of health. Pack resistance is only visible while the battery
 * is supplying current; at cruise the alternator carries the bus and a new
 * pack and a dying one read the same. So the last real measurement is shown
 * with its age, and the panel says when the pack is not observable. */
function Battery({ snap }: { snap: Snapshot }) {
  // Already held, once, in HealthPage -- see useHeldBattery.
  const b: any = (snap as any).battery ?? {};
  const soh: number | null = b.soh ?? null;
  const age: number | null = b.hours_since_measured ?? null;
  const level = soh == null ? null : soh < 0.3 ? "warning" : soh < 0.6 ? "caution" : null;
  return (
    <Section title="Battery"
             right={<span className="t-mute">{b.observable_now ? "measuring now" : "not observable at this power"}</span>}>
      {soh == null ? (
        <NoTrace what="No measurement yet." why={b.reason ?? undefined} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
          <Stat label="State of health"
                value={level ? <Status level={level} text={`${(soh * 100).toFixed(0)} %`} size={20} />
                  : `${(soh * 100).toFixed(0)} %`}
                sub={age != null ? `measured ${age.toFixed(1)} h ago${age > 50 ? ", dated" : ""}` : undefined} />
          {/* A pack is judged against the end of its service life, not against
              zero -- a battery at 0 % state of health is not a battery. The
              scale runs from the 60 % replacement point so the part of it that
              decides anything gets the room, and the figure is drawn rather
              than left in a list where 96 % and 61 % look equally fine. */}
          {/* A DIRECTION-AWARE SCALE, BECAUSE HIGHER IS BETTER HERE.
              This was AgainstBands, which is built for higher-is-worse
              quantities like temperature and current. Handed critical_max:100
              it painted a perfectly healthy 100 % pack in warning red and
              captioned it OVER LIMIT -- while the Stat directly above called
              the same number healthy. Two verdicts, one value. */}
          <SohScale soh={soh} observableNow={b.observable_now}
                    hoursSinceMeasured={age} reason={b.reason ?? null} />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: "var(--space-2) var(--space-3)" }}>
            <Figure name="Internal resistance"
                    value={b.internal_resistance_mohm != null
                      ? b.internal_resistance_mohm.toFixed(1) : "—"} unit="mΩ" />
            <Figure name="Open-circuit voltage"
                    value={b.open_circuit_v != null ? b.open_circuit_v.toFixed(2) : "—"} unit="V" />
            <Figure name="Confidence"
                    value={b.confidence != null ? b.confidence.toFixed(2) : "—"} />
            <Figure name="Samples" value={b.samples ?? "—"} />
          </div>
          {!b.observable_now && b.reason && (
            <NoTrace what="Not observable at this power." why={b.reason} />
          )}
        </div>
      )}
    </Section>
  );
}
