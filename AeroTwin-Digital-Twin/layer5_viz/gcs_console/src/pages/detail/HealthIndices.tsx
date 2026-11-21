/* WHAT SETS THE HEALTH SCORE.
 *
 * This replaces two things that were saying the same thing without admitting
 * it: a row of four subsystem percentages, and a nine-row table of sub-indices
 * underneath. They overlapped completely, because of how the score is built.
 *
 * layer3_ai/health.py:491 -- a subsystem is the MINIMUM of its contributors:
 *
 *     thermal    = min(thi, oti)
 *     mechanical = min(mhi, lhi, rsi)
 *     electrical = ehi
 *     combustion = min(comb_hi, fshi, csi)
 *
 * so every headline percentage WAS one of the nine below it, to the decimal,
 * shown twice with nothing to say they were the same fact. Meanwhile the
 * figure that actually set each subsystem was somewhere in an unranked table
 * of nine, and at a healthy 97 % nothing carried a symbol at all, because
 * healthLevel only marks below 0.90. An engineer could read the whole page and
 * still not know which measurement was holding the engine back.
 *
 * So the duplication becomes the explanation. Each subsystem states its score,
 * the weight it carries into the composite, and WHICH index set it; its
 * contributors sit underneath, worst first, with the limiting one marked. The
 * arithmetic of the score -- minimum, then weighted sum -- is on the page
 * instead of behind it.
 *
 * The grouping is not invented here. layer3_ai/explain.py:91 keeps
 * SUBSYSTEM_INPUTS beside the estimator with a comment saying it is held there
 * "so the explanation cannot drift away from the computation it claims to
 * explain"; this mirrors it, and the weights come from health.composite_weights
 * in configs/thresholds.yaml, served on /api/engine.
 */
import type { CSSProperties } from "react";
import { StatusSymbol, healthLevel, words } from "../../ui/status";
import {
  AgainstBands, AxisBars, CylinderBalance, Deviation, Figure, NoTrace, nz, readVal,
} from "./HealthFigures";
import { useDampedRecord } from "../../lib/damp";
import { bandOf } from "../../lib/bands";
import { OrderSpectrum } from "./OrderSpectrum";
import { PowerFlow } from "./PowerFlow";

const NUM: CSSProperties = { fontFamily: "var(--font-num)" };
const LABEL: CSSProperties = { fontSize: "var(--size-label)", color: "var(--ink-dim)" };

/* Each subsystem is handed the figure its own data supports -- see
 * subsystemFigure() below. There is deliberately no generic "every index gets
 * a sparkline" path any more: three of the four it produced were unreadable,
 * because a line with no baseline, no band and no reference answers nothing.
 */
type Hist = Record<string, (number | null)[] | undefined>;

/** The nine, with what each one actually measures. */
const WHAT: Record<string, string> = {
  thi: "Head and coolant temperature against the as-new model",
  oti: "Oil temperature against the as-new model",
  mhi: "Vibration level and impulsiveness",
  lhi: "Lubrication: oil pressure for the engine speed",
  rsi: "Engine speed stability",
  ehi: "Bus voltage and alternator output",
  comb_hi: "Exhaust temperature spread (combustion evenness)",
  fshi: "Fuel system: rail pressure and flow",
  csi: "Spread of head temperature across the four cylinders",
};

const SHORT: Record<string, string> = {
  thi: "THI", oti: "OTI", mhi: "MHI", lhi: "LHI", rsi: "RSI",
  ehi: "EHI", comb_hi: "CombHI", fshi: "FSHI", csi: "CSI",
};

/* Mirrors layer3_ai/explain.py:91 SUBSYSTEM_INPUTS. */
const GROUPS: [key: string, name: string, inputs: string[]][] = [
  ["thermal", "Thermal", ["thi", "oti"]],
  ["mechanical", "Mechanical", ["mhi", "lhi", "rsi"]],
  ["electrical", "Electrical", ["ehi"]],
  ["combustion", "Combustion", ["comb_hi", "fshi", "csi"]],
];

/* THE MEASURED NOISE OF THE PER-CYLINDER CHANNELS, in degC.
 *
 * Taken with the engine settled, where nothing is happening and so every
 * change in a reading is scatter: head temperature moved about 0.8 degC
 * frame to frame and exhaust gas about 5 (re-measured -- 3 was too tight, and
 * at ambient the four exhaust probes read 13 degC apart with the engine cold,
 * which is scatter and nothing else). These do double duty -- they are
 * the display deadband, and they are the resolution below which the figure
 * declines to name an outlier, because a lead smaller than the noise is not
 * a lead. Both uses want the same number, so it is written once. */
const CYL_NOISE = { cht: 0.8, egt: 5.0 } as const;

const num = (v: unknown): number | null => (typeof v === "number" ? v : null);

/** A Measurement's state word, when it carries one. Damping must snap on a
 *  change of state, so the two can never disagree by a frame. */
const stateOf = (node: any): string | null =>
  node && typeof node === "object" && typeof node.state === "string" ? node.state : null;

/* The bar runs the band that matters, not 0-100 %.
 *
 * A health index spends its whole working life between about 0.7 and 1.0, so a
 * bar drawn from zero puts every reading in the last third and shows nothing.
 * Anchored at 0.5 instead, the part of the scale an engineer actually
 * distinguishes gets the whole track. Below 0.5 the engine is being grounded
 * and the exact figure has stopped mattering. */
const FLOOR = 0.5;

function Bar({ v }: { v: number | null }) {
  const lvl = healthLevel(v);
  const pct = v == null ? 0 : Math.max(0, Math.min(1, (v - FLOOR) / (1 - FLOOR))) * 100;
  return (
    <div style={{ position: "relative", height: 8, background: "var(--bg-raised)",
                  border: "1px solid var(--line)", borderRadius: 2, minWidth: 80 }}>
      {v != null && (
        <div className="bar-fill"
             style={{ position: "absolute", top: 1, bottom: 1, left: 1,
                      width: `calc(${pct}% - 2px)`,
                      background: lvl === "warning" ? "var(--alert-warn)"
                                : lvl === "caution" ? "var(--alert-caut)"
                                : "var(--ink)" }} />
      )}
    </div>
  );
}

/* ONE SUBSYSTEM, AS AN INSTRUMENT.
 *
 * Four of these sit side by side. The frame is identical across all four --
 * name, score, what set it, its indices -- so they read as one system; the
 * FIGURE at the bottom is whatever that subsystem's data can actually support,
 * because forcing the same chart on all four is how the page ended up with
 * three meaningless traces.
 */
function Subsystem({ name, inputs, score, weight, h, figure }: {
  name: string; inputs: string[]; score: number | null;
  weight: number | null; h: Record<string, unknown>; figure: React.ReactNode;
}) {
  const rows = inputs
    .map((k) => ({ k, v: num(h[k]) }))
    .sort((a, b) => (a.v ?? 2) - (b.v ?? 2));
  // The subsystem IS its worst contributor, so the first row after the sort is
  // the one that set it -- named rather than left to be found.
  const limiter = rows.find((r) => r.v != null) ?? null;
  const lvl = healthLevel(score);

  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius-lg)",
                  padding: "var(--space-3) var(--space-4)", minWidth: 0,
                  display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      <div style={{ display: "flex", alignItems: "baseline",
                    justifyContent: "space-between", gap: "var(--space-2)" }}>
        <span style={{ fontWeight: 700, fontSize: 20 }}>{name}</span>
        <span style={{ ...NUM, fontSize: 28, display: "inline-flex",
                       alignItems: "center", gap: 6,
                       color: lvl === "warning" ? "var(--alert-warn)"
                            : lvl === "caution" ? "var(--alert-caut)" : "var(--ink)" }}>
          {lvl && <StatusSymbol level={lvl} size={14} />}
          {score == null ? "—" : (score * 100).toFixed(1)}
          <span style={{ fontSize: 16, color: "var(--ink-dim)" }}>%</span>
        </span>
      </div>

      <Bar v={score} />

      <div style={{ display: "flex", justifyContent: "space-between",
                    gap: "var(--space-2)", ...LABEL }}>
        <span>
          {limiter && inputs.length > 1 ? `set by ${SHORT[limiter.k]}` : "single measurement"}
        </span>
        {weight != null && <span style={NUM}>weight {weight.toFixed(2)}</span>}
      </div>

      {/* The contributors, worst first. Only the one that set the subsystem is
          marked; the rest are context, and dimming them is how the page says
          so. A rule rather than another box -- the panel already has a border. */}
      <div style={{ borderTop: "1px solid var(--line)", paddingTop: "var(--space-2)",
                    display: "grid", gridTemplateColumns: "auto minmax(0, 1fr) auto",
                    columnGap: "var(--space-3)", rowGap: 3, alignItems: "baseline" }}>
        {rows.map(({ k, v }) => {
          const sets = limiter != null && k === limiter.k && inputs.length > 1;
          return [
            <span key={`n${k}`} style={{ fontSize: 16, fontWeight: sets ? 700 : 400,
                                         color: sets ? "var(--ink)" : "var(--ink-dim)" }}>
              {SHORT[k]}
            </span>,
            <span key={`w${k}`} title={WHAT[k]}
                  style={{ fontSize: 16, color: "var(--ink-dim)", overflow: "hidden",
                           textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {WHAT[k]}
            </span>,
            <span key={`v${k}`} style={{ ...NUM, fontSize: 16, textAlign: "right",
                                         color: sets ? "var(--ink)" : "var(--ink-dim)" }}>
              {v == null ? "—" : `${(v * 100).toFixed(1)} %`}
            </span>,
          ];
        })}
      </div>

      {/* Flowing straight on from the indices, not pushed to the foot of the
          card. Pinned to the bottom, a subsystem with less to say -- thermal
          has two indices where mechanical has three -- opened a hole in the
          middle of its card. Slack at the bottom edge of a bordered panel
          reads as spacing; slack in the middle reads as something missing. */}
      <div style={{ paddingTop: "var(--space-3)",
                    display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        {figure}
      </div>
    </div>
  );
}

/* WHICH FIGURE EACH SUBSYSTEM GETS, AND WHY.
 *
 * Decided by what the snapshot actually carries, not by a wish to fill the
 * card. Where a subsystem has no plottable history, it gets its measurements
 * on their certified scales instead -- which answers a real question -- and
 * says plainly that there is no session trace.
 */
function subsystemFigure(key: string, snap: any, limits: any,
                         onFocusPart?: (componentId: string) => void,
                         damped?: Record<string, number | null>): React.ReactNode {
  const r = snap?.twin?.reported ?? {};
  const hist: Hist = snap?.history ?? {};
  const par = limits?.parameters ?? {};

  /* A COMPARISON AGAINST THE MODEL IS ONLY A COMPARISON WHILE IT IS RUNNING.
   *
   * The as-new shadow model describes a warm, loaded engine. Subtract it from
   * a cold one and the answer is -85 degC, which is not a fault, it is the
   * engine being switched off -- and shown as a deviation chart it reads as a
   * catastrophe. The condition is not invented here: the estimator publishes
   * `health.assessment.state`, which is "live" only when its own gate is met
   * ("the oil at or above 50 degC and the engine above 2300 rpm"), and it
   * carries the reason with it. Direct readings -- vibration, the bus, the
   * cylinders -- are true whatever the engine is doing and stay. */
  const assess = snap?.health?.assessment ?? null;
  const modelLive = assess == null || assess.state === "live";

  if (key === "thermal") {
    // THI and OTI are both scored AGAINST THE AS-NEW MODEL, so the deviation
    // from that model is the quantity, not the raw temperature.
    const dev = (
      <Figure name="Head temperature vs as-new model" >
        <Deviation measured={hist.cht} model={hist.cht_pred} running={hist.rpm}
                   unit="°C" height={92} />
      </Figure>
    );
    // A sample counts only if the measurement, the model AND a turning engine
    // are all present for it -- the same mask the chart applies.
    const haveDev = (hist.cht ?? []).some((v, i) =>
      v != null && (hist.cht_pred ?? [])[i] != null && ((hist.rpm ?? [])[i] ?? 0) > 100);
    if (!haveDev && !modelLive) {
      return (
        <NoTrace what="Comparison against the as-new model is not being made."
                 why={assess?.reason
                   ? String(assess.reason).replace(/^engine not warm and loaded: /, "")
                   : "The model describes a warm, loaded engine."} />
      );
    }
    return haveDev ? dev : (
      <NoTrace what="No session trace for head temperature."
               why="The as-new comparison needs both the measurement and the model." />
    );
  }

  if (key === "mechanical") {
    const vb = r.vibration ?? {};
    // Damped for display; see the note in HealthIndices for the deadbands.
    const axes = [
      { name: "X", v: damped?.vibX ?? readVal(vb.rms_x) },
      { name: "Y", v: damped?.vibY ?? readVal(vb.rms_y) },
      { name: "Z", v: damped?.vibZ ?? readVal(vb.rms_z) },
    ];
    const total = damped?.vibTotal ?? readVal(vb.rms_total);
    const kurt = damped?.kurtosis ?? readVal(vb.kurtosis);
    const domHz = readVal(vb.dominant_frequency_hz);
    const oilP = damped?.oilP ?? readVal(r.oil_pressure);
    const rpm = readVal(r.rpm);
    const peaks = (vb.spectral_peaks ?? null) as Record<string, number> | null;

    /* THE ORDER ANALYSIS IS PERIODIC AND STICKY, AND THAT HAS TO BE SAID.
     *
     * It recomputes once per 60 simulated seconds and only while the engine is
     * turning above 300 rpm (live.py:1881-1885), and it KEEPS its last result
     * afterwards. So on a stopped engine the bearing signature on screen is
     * whatever the engine was doing when it was last running -- perfectly real,
     * and not current. Below the analyser's own rpm floor the card says so;
     * there is no age field in the payload to quote, so it states the condition
     * rather than inventing a number of seconds. */
    const orderRefreshing = rpm != null && rpm > 300;

    return (
      <>
        <Figure name="Bearing and gear orders"
                value={peaks && Object.keys(peaks).length ? undefined : "—"}
                note={peaks && Object.keys(peaks).length && !orderRefreshing
                  ? "Held from the last run: the analysis only recomputes above 300 rpm."
                  : undefined}>
          <OrderSpectrum peaks={peaks} />
        </Figure>

        {axes.some((a) => a.v != null) ? (
          <Figure name="Vibration" value={total == null ? "—" : total.toFixed(2)} unit="m/s²"
                  note={kurt == null && domHz == null ? undefined : (
                    <>
                      {kurt != null && <>impulsiveness (kurtosis) <b style={NUM}>{kurt.toFixed(2)}</b></>}
                      {kurt != null && domHz != null && " · "}
                      {domHz != null && <>dominant <b style={NUM}>{domHz.toFixed(0)}</b> Hz</>}
                    </>
                  )}>
            {/* Banded now that the limits have been found: parameters.vibration_rms
                carries normal 3.5, alert 5.0, critical 8.0 m/s2, annotated in
                thresholds.yaml as ISO 10816 class practice. An earlier pass
                reported these as absent -- it had looked under `vibration`. */}
            {par.vibration_rms && (
              <div style={{ marginBottom: "var(--space-2)" }}>
                <AgainstBands value={total} lim={par.vibration_rms} unit="m/s²" />
              </div>
            )}
            <AxisBars axes={axes} unit="m/s²" />
          </Figure>
        ) : (
          <NoTrace what="No vibration breakdown reported." />
        )}

        {oilP != null && par.oil_pressure && (
          <Figure name="Oil pressure" value={oilP.toFixed(1)} unit="psi">
            <AgainstBands value={oilP} lim={par.oil_pressure} unit="psi" />
          </Figure>
        )}
      </>
    );
  }

  if (key === "electrical") {
    /* A POWER-FLOW SCHEMATIC, NOT A PAIR OF BARS.
     *
     * EHI is scored from the bus, and the bus keeps no session history, so
     * there is nothing to plot over time -- but there is a system to draw.
     * Battery and alternator both feed one regulated DC bus, which feeds the
     * loads; that shape is the answer to "where is the power coming from",
     * which two isolated readings could not give.
     *
     * The bus band is parameters.battery_voltage, and using it here is not an
     * assumption: recorder.py:135 maps the parameter `battery_voltage` onto
     * ("electrical", "bus_voltage"), and live.py:1792 publishes the same node
     * under that name. They are provably one node. An earlier pass left the
     * bus unbanded for want of this evidence.
     *
     * What is NOT drawn with a number: any load. No ECU, avionics, payload or
     * bus-load current is published anywhere -- the physics model sums the
     * split locally and never serialises it -- so the loads box carries no
     * figure. Nor is there a second voltage node: alternator_voltage is
     * MISSING by design, because the alternator's regulated output IS the bus.
     */
    const el = r.electrical ?? {};
    return (
      <PowerFlow
        busV={damped?.busV ?? readVal(el.bus_voltage)}
        busLim={par.battery_voltage ?? null}
        altA={damped?.altA ?? readVal(el.alternator_current)}
        altLim={par.alternator_current ?? null}
        battery={snap?.battery ?? null}
      />
    );
  }

  if (key === "combustion") {
    // CSI is the SPREAD across the cylinders, so the cylinders against each
    // other is the picture -- a time series of one aggregate cannot show
    // imbalance at all.
    const cylinders = (grp: string) => {
      const node = r[grp] ?? {};
      return Object.keys(node)
        .filter((k) => /^cyl_\d+$/.test(k))
        .sort()
        .map((k) => ({
          n: Number(k.slice(4)),
          // The damped figure, so the digits, the bars, the mean and the
          // worst-cylinder verdict are all one consistent set.
          v: damped?.[`${grp}_${k.slice(4)}`] ?? readVal(node[k]),
        }));
    };
    const out: React.ReactNode[] = [];
    for (const [grp, label, unit, digits] of
         [["cht", "Head temperature by cylinder", "°C", 1],
          ["egt", "Exhaust temperature by cylinder", "°C", 0]] as const) {
      const cyls = cylinders(grp);
      if (!cyls.length || !cyls.some((c) => c.v != null)) continue;
      const vals = cyls.map((c) => c.v).filter((v): v is number => v != null);
      // Held in its own right; see the note where the spec is built.
      const mean = damped?.[`${grp}_mean`]
        ?? (vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null);
      const node = r[grp] ?? {};
      // Bank order: 1 and 3, then 2 and 4 -- the same order the numbers are
      // drawn on the 3D model, so the two can be read against each other.
      const order = [...cyls].sort((a, b) => (b.n % 2) - (a.n % 2) || a.n - b.n);
      out.push(
        <Figure key={grp} name={label}
                value={mean != null ? mean.toFixed(digits) : "—"} unit={`${unit} mean`}>
          <CylinderBalance values={order} mean={mean}
                           spread={damped?.[`${grp}_spread`] ?? nz(node.spread)}
                           spreadAlert={nz(par[grp]?.spread_alert)}
                           unit={unit} digits={digits}
                           resolveAt={CYL_NOISE[grp]}
                           onPick={onFocusPart
                             ? (n) => onFocusPart(`ROTAX_915IS_CYLINDER_0${n}`)
                             : undefined} />
        </Figure>,
      );
    }
    return out.length ? <>{out}</> : <NoTrace what="No per-cylinder temperatures reported." />;
  }

  return null;
}

export function HealthIndices({ h, snap, limits, onFocusPart }: {
  h: Record<string, unknown>;
  snap: any;
  limits: any;
  onFocusPart?: (componentId: string) => void;
}) {
  const weights: Record<string, number> | null = limits?.composite_weights ?? null;

  /* HOLDING THE NOISY DIGITS STILL.
   *
   * Every deadband here was MEASURED, not chosen. With the engine running at
   * 5471 rpm and CHT at 115 degC, each printed number on this page was sampled
   * at 4 Hz and its frame-to-frame step recorded; the median step of a reading
   * that is not actually moving IS its noise. What that showed:
   *
   *   ENGINE HEALTH %      churned on 76 % of frames
   *   the four subsystem % churned on 72-91 %
   *   cylinder EGT / CHT   churned on 86-92 %, median step 4.0 / 0.7 degC
   *   "#N furthest out"    named a DIFFERENT cylinder on 72-78 % of frames
   *   kurtosis             95 %, median step 0.18
   *
   * A deadband just above the noise step stops that dead and costs nothing:
   * real movement on these channels is far larger than their noise, so it
   * crosses in the frame it happens. Each value also snaps instantly, deadband
   * ignored, when its BAND or its value-state changes -- so a figure can still
   * never disagree with the alert engine, which is this file's standing rule.
   * Each deadband sits at or above the channel's own declared `resolution`
   * (/api/engine parameters), which is the finest step the sensor claims.
   *
   * TWO DEPARTURES FROM THE PLAN, both because measurement contradicted it.
   * The plan said to bypass `chi` and `alternator_current` as low
   * signal-to-noise. Measured, those are two of the worst offenders -- chi is
   * the headline number on the page and its tenth digit moved three times a
   * second on a steady cruise, and the alternator field churned while printing
   * 0.0 A. Bypassing them produced exactly the defect the item exists to
   * prevent. Both are damped, at 0.2 pp and 0.3 A: below anything actionable.
   *
   * The plan also kept the per-cylinder temperatures undamped, on the argument
   * that they are a COMPARISON and damping members independently could misstate
   * it. Measuring showed that reasoning protected the wrong thing: undamped,
   * the cylinder block was the noisiest region of the page, and the derived
   * verdict "#3 furthest out" re-elected a different worst cylinder three times
   * a second. They are damped now, and -- the part that makes it honest -- the
   * mean, the deviations, the bar lengths and the worst-cylinder verdict are
   * all derived FROM the damped values inside CylinderBalance, so the figure is
   * internally consistent rather than a damped set judged against a live mean.
   * The published spread is still the API's own number, shown as served. */
  const rr = snap?.twin?.reported ?? {};
  const pp = limits?.parameters ?? {};
  const vbr = rr.vibration ?? {};
  const elr = rr.electrical ?? {};
  const rawVib = readVal(vbr.rms_total);
  const rawOil = readVal(rr.oil_pressure);
  const rawBus = readVal(elr.bus_voltage);
  const rawAlt = readVal(elr.alternator_current);

  /* The cylinders, built rather than typed out: the set of reported cylinders
   * is the snapshot's to decide, and useDampedRecord forgets a key that stops
   * being supplied, so a cylinder that drops out and returns is re-adopted
   * fresh instead of coming back as a figure from minutes ago. */
  const cylSpecs: Record<string, any> = {};
  for (const [grp, dead] of [["cht", CYL_NOISE.cht], ["egt", CYL_NOISE.egt]] as const) {
    const node = rr[grp] ?? {};
    for (const k of Object.keys(node)) {
      if (!/^cyl_\d+$/.test(k)) continue;
      const v = readVal(node[k]);
      cylSpecs[`${grp}_${k.slice(4)}`] = {
        value: v, deadband: dead, state: stateOf(node[k]),
        band: bandOf(v, pp[grp]),
      };
    }
    // The spread is the API's own number, held at the same width as the
    // cylinders it summarises so the two cannot drift apart on screen.
    cylSpecs[`${grp}_spread`] = { value: readVal(node.spread), deadband: dead };

    /* THE MEAN IS HELD IN ITS OWN RIGHT, NOT AVERAGED FROM HELD CYLINDERS.
     *
     * Averaging four independently held values AMPLIFIES churn instead of
     * damping it: the average moves whenever ANY member adopts, so four
     * cylinders each settling on 55 % of frames produced a mean that moved on
     * 81 % of them -- the noisiest number in the whole card, derived entirely
     * from quiet ones. Measured before and after, that is the single largest
     * remaining source of movement on the page.
     *
     * So the mean is computed from the RAW cylinders and then held at the same
     * width as they are. It is a held version of the true mean rather than the
     * average of four held numbers, which is both steadier and a fairer
     * statement of the quantity. The consequence, stated plainly: the printed
     * mean can sit up to one deadband away from the average of the four printed
     * values. That is the correct trade -- the mean is a summary to be read,
     * not an arithmetic check on the four figures beside it. */
    const raws = Object.keys(node)
      .filter((k) => /^cyl_\d+$/.test(k))
      .map((k) => readVal(node[k]))
      .filter((v): v is number => v != null);
    cylSpecs[`${grp}_mean`] = {
      value: raws.length ? raws.reduce((x, y) => x + y, 0) / raws.length : null,
      deadband: dead,
    };
  }

  const damped = useDampedRecord({
    ...cylSpecs,
    vibTotal: { value: rawVib, deadband: 0.1, state: stateOf(vbr.rms_total),
                band: bandOf(rawVib, pp.vibration_rms) },
    vibX: { value: readVal(vbr.rms_x), deadband: 0.1, state: stateOf(vbr.rms_x) },
    vibY: { value: readVal(vbr.rms_y), deadband: 0.1, state: stateOf(vbr.rms_y) },
    vibZ: { value: readVal(vbr.rms_z), deadband: 0.1, state: stateOf(vbr.rms_z) },
    kurtosis: { value: readVal(vbr.kurtosis), deadband: 0.3,
                state: stateOf(vbr.kurtosis) },
    oilP: { value: rawOil, deadband: 0.5, state: stateOf(rr.oil_pressure),
            band: bandOf(rawOil, pp.oil_pressure) },
    busV: { value: rawBus, deadband: 0.4, state: stateOf(elr.bus_voltage),
            band: bandOf(rawBus, pp.battery_voltage) },
    altA: { value: rawAlt, deadband: 0.3, state: stateOf(elr.alternator_current),
            band: bandOf(rawAlt, pp.alternator_current) },
  });
  return (
    <div className="hx-drivers">
      {GROUPS.map(([key, name, inputs]) => (
        <Subsystem key={key} name={name} inputs={inputs} score={num(h[key])}
                   weight={weights ? weights[key] ?? null : null}
                   h={h} figure={subsystemFigure(key, snap, limits, onFocusPart, damped)} />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ scale */
/* WHERE THE SCORE SITS, AND HOW MUCH ROOM IS LEFT.
 *
 * "93.6 %, Excellent" is two facts and neither is the one an engineer acts on.
 * What matters is the distance to the next band down -- the point at which the
 * instruction changes from "no action required" to "monitor", and then to a
 * maintenance interval. A bare percentage hides that entirely; a scale with the
 * band boundaries on it cannot.
 *
 * The bands are the seven in configs/thresholds.yaml (health.chi_bands), served
 * on /api/engine, drawn at their own boundaries rather than at pretty round
 * numbers chosen here. The fill takes the level of the band it lands in, so it
 * agrees with the word beside it and with the alert engine.
 */
export function BandScale({ chi, bands, level }: {
  chi: number;
  bands: { min: number; label: string }[] | null;
  level: "normal" | "caution" | "warning";
}) {
  const sorted = (bands ?? []).slice().sort((a, b) => b.min - a.min);
  const edges = sorted.map((b) => b.min).filter((m) => m > 0 && m < 1).sort((a, b) => a - b);
  const colour = level === "warning" ? "var(--alert-warn)"
               : level === "caution" ? "var(--alert-caut)" : "var(--ink)";

  /* HOW FAR IT CAN FALL BEFORE THE ORDERS CHANGE.
   *
   * The band a score sits in decides the instruction -- "no action required"
   * becomes "monitor", then a maintenance interval. So the number worth
   * printing beside the scale is not the score again, it is the DISTANCE to
   * the edge below it, because that is the point at which somebody has to do
   * something. It is the one figure here that answers "how much room do I
   * have", and nothing on the page carried it before. */
  const cur = sorted.findIndex((b) => chi >= b.min);
  const current = cur >= 0 ? sorted[cur] : null;
  const next = cur >= 0 && cur + 1 < sorted.length ? sorted[cur + 1] : null;
  // The room is to the floor of the CURRENT band; the band named is the one it
  // would fall into on the way through. "3.6 above Excellent" was the first
  // attempt and it says the wrong thing -- 93.6 is not above Excellent, it IS
  // Excellent, with 3.6 to give before it is Good.
  const room = current ? (chi - current.min) * 100 : null;

  return (
    <div>
      <div style={{ position: "relative", height: 18, background: "var(--bg-raised)",
                    border: "1px solid var(--line)", borderRadius: 2 }}>
        <div className="bar-fill"
             style={{ position: "absolute", top: 1, bottom: 1, left: 1,
                      width: `calc(${Math.max(0, Math.min(1, chi)) * 100}% - 2px)`,
                      background: colour }} />
        {/* Every band edge, cut THROUGH the fill in the panel colour so it
            reads as a gap on the dark side and as a rule on the light side.
            Drawn in --line, the edges vanished into the fill exactly where the
            score was, which is the half of the scale that matters. */}
        {edges.map((m) => (
          <div key={m} style={{ position: "absolute", top: 0, bottom: 0,
                                left: `${m * 100}%`, width: 2, marginLeft: -1,
                                background: "var(--bg-panel)" }} />
        ))}
      </div>
      <div style={{ position: "relative", height: 20, marginTop: 2 }}>
        {edges.map((m) => (
          <span key={m} style={{ ...NUM, position: "absolute", left: `${m * 100}%`,
                                 transform: "translateX(-50%)", fontSize: 16,
                                 color: "var(--ink-mute)" }}>
            {Math.round(m * 100)}
          </span>
        ))}
      </div>
      {room != null && next && (
        <div style={{ fontSize: 16, color: "var(--ink-dim)", marginTop: 2 }}>
          <span style={NUM}>{room.toFixed(1)}</span> to give before {words(next.label)}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------- health by system */
/* FOUR SYSTEMS, 100 = FULL.
 *
 * This used to be "what it is costing, out of 100": one stacked bar whose
 * slices were weighted and whose GAPS were the degradation, captioned with
 * negative numbers -- thermal -0.7, electrical -0.3. The arithmetic was
 * right and the reading was wrong. A negative number is read as a fault, so
 * electrical at 98.8 % healthy announced itself as "-0.3" and looked like a
 * problem; and because each slice was only as wide as its weight, a subsystem
 * could not be compared with its neighbour by length.
 *
 * Now each system gets a full-width bar where 100 is full health, sorted worst
 * first. The degradation figure survives to the right, in muted ink, because
 * it answers a real second question -- how much this system is taking off the
 * composite, which is weight-dependent and not the same as how healthy it is.
 *
 * THE ARITHMETIC IS UNCHANGED. Same `h`, same `weights`, same
 * `w * (1 - v) * 100`. Only which number leads.
 */
export function SystemHealth({ h, weights }:
  { h: Record<string, unknown>; weights: Record<string, number> | null }) {
  if (!weights) return null;
  const parts = GROUPS
    .map(([key, name]) => ({ key, name, w: weights[key], v: num(h[key]) }))
    .filter((p) => typeof p.w === "number" && p.w > 0);
  if (!parts.length) return null;

  // Worst first: the subsystem holding the engine back should not have to be
  // found by comparing four bars of similar length.
  const ordered = [...parts].sort((a, b) => (a.v ?? 2) - (b.v ?? 2));

  return (
    <div style={{ display: "grid", gridTemplateColumns: "auto minmax(0, 1fr) auto auto",
                  columnGap: "var(--space-3)", rowGap: 6, alignItems: "center" }}>
      {ordered.map((p) => {
        const lvl = healthLevel(p.v);
        const pct = p.v == null ? null : p.v * 100;
        // Unchanged arithmetic, kept as the secondary reading: weight x the
        // shortfall is the number of points this subsystem takes off chi.
        const lost = p.v == null ? null : p.w * (1 - p.v) * 100;
        const ink = lvl === "warning" ? "var(--alert-warn)"
                  : lvl === "caution" ? "var(--alert-caut)"
                  : "var(--state-normal)";
        return [
          <span key={`n${p.key}`} style={{ fontSize: 16, color: "var(--ink-dim)",
                                           whiteSpace: "nowrap" }}>
            {p.name}
          </span>,
          <div key={`b${p.key}`}
               title={`${p.name}: ${pct == null ? "no reading" : pct.toFixed(1) + " % of full"}` +
                      (lost == null ? "" : `, taking ${lost.toFixed(1)} off the composite`)}
               style={{ position: "relative", height: 14, background: "var(--bg-raised)",
                        border: "1px solid var(--line)", borderRadius: 2 }}>
            {pct != null && (
              <div className="bar-fill"
                   style={{ position: "absolute", top: 1, bottom: 1, left: 1,
                            width: `calc(${Math.max(0, Math.min(100, pct))}% - 2px)`,
                            background: ink }} />
            )}
          </div>,
          <span key={`v${p.key}`} style={{ ...NUM, fontSize: 18, textAlign: "right",
                                           color: lvl ? ink : "var(--ink)" }}>
            {pct == null ? "\u2014" : pct.toFixed(1)}
            <span style={{ fontSize: 16, color: "var(--ink-dim)" }}> %</span>
          </span>,
          // The degradation figure stays, demoted to where it belongs: useful
          // once you already know which system to look at, and misleading as
          // the headline -- "-0.3" reads as a fault on a system that is 98.8 %
          // healthy and merely carries a fifth of the weight.
          <span key={`d${p.key}`} style={{ ...NUM, fontSize: 16, textAlign: "right",
                                           color: "var(--ink-mute)", whiteSpace: "nowrap" }}>
            {lost == null ? "" : `\u2212${lost.toFixed(1)}`}
          </span>,
        ];
      })}
    </div>
  );
}
