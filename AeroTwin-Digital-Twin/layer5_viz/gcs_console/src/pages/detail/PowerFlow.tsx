/* THE DC ELECTRICAL SYSTEM, DRAWN AS A ONE-LINE DIAGRAM.
 *
 * This is a schematic, not an analytics card: two sources feed one busbar, the
 * busbar feeds the loads, and the arrows say which way the current goes. The
 * bus voltage is the headline because it is the one figure that tells an
 * operator whether the electrical system is doing its job.
 *
 * WHAT IS MEASURED, AND WHAT IS NOT. Only three things on this aircraft's DC
 * side are published: bus voltage, alternator current, and the battery
 * estimate (state of health, open-circuit volts, internal resistance). That is
 * the whole list, and the two absences below are the reason this file exists
 * rather than a generic power card:
 *
 *   LOADS CARRY NO NUMBER. The physics model splits the draw between ECU,
 *   avionics and payload, but that split is summed locally and never leaves
 *   the model -- there is no load-current sensor and no published figure. So
 *   the sink is drawn as one lumped box that says it is not instrumented. It
 *   is deliberately given no digits, no bar and no em-dash: an em-dash is the
 *   placeholder for a value that exists and is missing right now, and writing
 *   one here would promise a reading that no sensor will ever supply.
 *
 *   THERE IS NO SECOND VOLTAGE NODE. alternator_voltage is MISSING BY DESIGN:
 *   this is one regulated bus, and the alternator's output IS the bus voltage.
 *   Drawing a separate alternator voltage -- even as a dash -- would invent a
 *   node the aircraft does not have, so the alternator box states the identity
 *   instead.
 *
 * There is also no battery current, no contactor state and no bus tie, so
 * nothing here draws a switch, a breaker or a direction of battery flow. The
 * arrow out of the battery is the schematic's topology (it is a source on this
 * bus), not a claim about what it is doing this second.
 *
 * NON-ASCII CHARACTERS ARE ESCAPED. The em-dash, en-dash, middle dot and ohm
 * sign are written as \u escapes so this file survives any toolchain that
 * mangles encodings; the constants below name them so the JSX stays readable.
 */
import type { CSSProperties, ReactNode } from "react";
import { bandOf, bandInk, bandWord, type Limit, type Band } from "../../lib/bands";

const DASH = "\u2014";        // em dash: a value that exists and is absent NOW
const EN = "\u2013";          // en dash: a numeric range
const MID = " \u00b7 ";       // middle dot: separates two facts on one line
const MOHM = "m\u03a9";       // milliohms, as the API labels it

/* The published limit records for the two live electricals. A caller that has
 * the parameter table should pass it in; these are the fallbacks so the bands
 * on screen still agree with the alert engine when it has not loaded yet. */
const BUS_LIMIT: Limit = {
  normal_min: 27, normal_max: 29,
  alert_min: 26, alert_max: 30,
  critical_min: 24, critical_max: 31,
};
const ALT_LIMIT: Limit = {
  normal_min: 0, normal_max: 22,
  alert_max: 26, critical_max: 30,
};

const nz = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

const LABEL: CSSProperties = {
  fontSize: "var(--size-label)", color: "var(--ink-dim)",
  letterSpacing: "0.06em", lineHeight: 1.25,
};
const NUM: CSSProperties = {
  fontFamily: "var(--font-num)", fontVariantNumeric: "tabular-nums",
};
const LINE: CSSProperties = { fontSize: 16, lineHeight: 1.25, color: "var(--ink)" };
const MUTED: CSSProperties = { fontSize: 16, lineHeight: 1.25, color: "var(--ink-mute)" };
const WORD: CSSProperties = { fontSize: 18, lineHeight: 1.25, letterSpacing: "0.04em" };

const BOX: CSSProperties = {
  border: "1px solid var(--line)", borderRadius: "var(--radius)",
  background: "var(--bg-raised)", padding: "var(--space-2)",
  minWidth: 0, display: "flex", flexDirection: "column", gap: 2,
};

/** A measured figure's own status word. Colour never travels alone here, so a
 *  healthy reading is captioned NORMAL rather than left to the green. */
const statusWord = (b: Band): string | null =>
  bandWord(b) ?? (b === "normal" ? "NORMAL" : null);

/** Ink for that word. --state-normal is healthy status only; every other case
 *  comes from the shared band table so it cannot disagree with the alerts. */
const statusInk = (b: Band): string =>
  b === "normal" ? "var(--state-normal)" : bandInk(b);

const fmt = (v: number): string => (Number.isInteger(v) ? String(v) : v.toFixed(1));

/** The normal envelope, in words, straight off the limit record. Nothing is
 *  computed or rounded into existence, and a limit that is not published is
 *  not described. */
function normalText(lim: Limit | null | undefined, unit: string): string | null {
  const lo = nz(lim?.normal_min), hi = nz(lim?.normal_max);
  if (lo == null && hi == null) return null;
  if (lo != null && hi != null) return `normal ${fmt(lo)}${EN}${fmt(hi)} ${unit}`;
  if (lo != null) return `normal above ${fmt(lo)} ${unit}`;
  // Only reachable with hi non-null: the both-null case returned above.
  return `normal below ${fmt(hi as number)} ${unit}`;
}

/** A value, or the em-dash that stands for one that is not being reported.
 *  Never a zero: a bus that is not reporting is not a bus at 0 V. */
function Value({ v, unit, digits, size = 20, ink = "var(--ink)" }: {
  v: number | null; unit: string; digits: number; size?: number; ink?: string;
}) {
  if (v == null) {
    return (
      <span style={{ ...NUM, fontSize: size, color: "var(--ink-mute)" }}>
        {DASH}<span style={{ fontSize: 16 }}> {unit}</span>
      </span>
    );
  }
  return (
    <span style={{ ...NUM, fontSize: size, color: ink, whiteSpace: "nowrap" }}>
      {v.toFixed(digits)}
      <span style={{ fontSize: 16, color: "var(--ink-dim)" }}> {unit}</span>
    </span>
  );
}

/** A conductor into the next block. Fixed size, so the arrowhead never
 *  distorts, centred in whatever cell it is given. */
function Feed() {
  return (
    <svg width="14" height="18" viewBox="0 0 14 18" role="presentation"
         aria-hidden="true" style={{ display: "block" }}>
      <line x1="7" y1="0" x2="7" y2="11" stroke="var(--ink-dim)" strokeWidth="2" />
      <polygon points="7,18 2.5,10.5 11.5,10.5" fill="var(--ink-dim)" />
    </svg>
  );
}

function Header({ children }: { children: ReactNode }) {
  return <div style={LABEL}>{children}</div>;
}

export interface PowerFlowProps {
  busV: number | null;
  busLim?: Limit | null;
  altA: number | null;
  altLim?: Limit | null;
  battery?: {
    soh?: number | null;
    open_circuit_v?: number | null;
    internal_resistance_mohm?: number | null;
    observable_now?: boolean;
    hours_since_measured?: number | null;
    reason?: string | null;
  } | null;
}

export function PowerFlow({ busV, busLim, altA, altLim, battery }: PowerFlowProps) {
  const bLim = busLim ?? BUS_LIMIT;
  const aLim = altLim ?? ALT_LIMIT;

  const v = nz(busV);
  const a = nz(altA);
  const vBand = bandOf(v, bLim);
  const aBand = bandOf(a, aLim);

  const soh = nz(battery?.soh);
  const ocv = nz(battery?.open_circuit_v);
  const ri = nz(battery?.internal_resistance_mohm);
  const age = nz(battery?.hours_since_measured);
  const observable = battery?.observable_now === true;
  const reason = battery?.reason ?? null;

  /* NOTHING TO DRAW IS SAID IN ONE LINE. A schematic with a dash in every box
   * is a frame pretending to be evidence; if not one electrical figure is
   * being reported, that is a sentence, and it takes a sentence's room. */
  if (v == null && a == null && soh == null && ocv == null && ri == null) {
    return (
      <div style={{ borderLeft: "2px solid var(--line)", paddingLeft: "var(--space-3)",
                    color: "var(--ink-mute)", fontSize: 16, lineHeight: 1.4 }}>
        No electrical measurement in this snapshot.
        <div style={{ marginTop: 2 }}>
          {reason ?? "Bus voltage, alternator current and the battery estimate are all absent."}
        </div>
      </div>
    );
  }

  const vWord = statusWord(vBand);
  const aWord = statusWord(aBand);
  const busNormal = normalText(bLim, "V");
  const altNormal = normalText(aLim, "A");

  return (
    <div style={{ display: "flex", flexDirection: "column", minWidth: 0,
                  color: "var(--ink)" }}>

      {/* --------------------------------------------------- the two sources */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                    gap: "var(--space-2)", alignItems: "stretch", minWidth: 0 }}>

        {/* BATTERY. Pack resistance is only visible while the pack is actually
            supplying current, so the age of the measurement is part of the
            reading and is shown beside it rather than left implied. */}
        <div style={BOX}>
          <Header>BATTERY</Header>
          <div style={{ whiteSpace: "nowrap" }}>
            <Value v={soh == null ? null : soh * 100} unit="%" digits={0} />
            <span style={{ ...LABEL, marginLeft: "var(--space-1)" }}>SOH</span>
          </div>
          <div style={{ ...LINE, ...NUM, whiteSpace: "nowrap" }}>
            {ocv == null
              ? <span style={{ color: "var(--ink-mute)" }}>{DASH} V oc</span>
              : <>{ocv.toFixed(2)}<span style={{ color: "var(--ink-dim)" }}> V oc</span></>}
          </div>
          <div style={{ ...LINE, ...NUM, whiteSpace: "nowrap" }}>
            {ri == null
              ? <span style={{ color: "var(--ink-mute)" }}>{DASH} {MOHM} int</span>
              : <>{ri.toFixed(1)}<span style={{ color: "var(--ink-dim)" }}> {MOHM} int</span></>}
          </div>
          <div style={MUTED}>
            {observable ? "measuring now" : "not observable now"}
            {age != null && `${MID}${age.toFixed(1)} h old`}
          </div>
          {!observable && reason && <div style={MUTED}>{reason}</div>}
        </div>

        {/* ALTERNATOR. Current is measured. Its OUTPUT VOLTAGE IS THE BUS --
            one regulated node -- so there is no second voltage to show here
            and no dash standing in for one. */}
        <div style={BOX}>
          <Header>ALTERNATOR</Header>
          <div>
            <Value v={a} unit="A" digits={1} ink={bandInk(aBand)} />
          </div>
          {aWord && <div style={{ ...WORD, color: statusInk(aBand) }}>{aWord}</div>}
          {altNormal && <div style={MUTED}>{altNormal}</div>}
          {/* The identity, stated, in place of the voltage node that does not
              exist. One line, because it is one fact and the card is 330 px
              tall; the reasoning is in the file header. */}
          <div style={MUTED}>output volts = bus</div>
        </div>
      </div>

      {/* Both sources land on the busbar. The arrows sit in the same two-column
          grid as the boxes, so each one stays under the block it leaves. */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                    gap: "var(--space-2)", justifyItems: "center" }}>
        <Feed />
        <Feed />
      </div>

      {/* ------------------------------------------------------ the DC busbar */}
      <div style={{ ...BOX, gap: "var(--space-1)" }}>
        {/* The busbar itself, drawn the way a one-line diagram draws it: one
            heavy conductor that everything else connects to. */}
        <div style={{ height: 3, background: "var(--ink)", marginBottom: 2 }} />
        <div style={{ display: "flex", alignItems: "baseline",
                      justifyContent: "space-between", gap: "var(--space-2)",
                      flexWrap: "wrap", minWidth: 0 }}>
          <Header>DC BUS</Header>
          <Value v={v} unit="V" digits={1} size={30} ink={bandInk(vBand)} />
        </div>
        <div style={{ display: "flex", alignItems: "baseline",
                      justifyContent: "space-between", gap: "var(--space-2)",
                      flexWrap: "wrap", minWidth: 0 }}>
          <span style={MUTED}>{busNormal ?? "no published limit"}</span>
          {vWord
            ? <span style={{ ...WORD, color: statusInk(vBand) }}>{vWord}</span>
            : <span style={MUTED}>not reported</span>}
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "center" }}>
        <Feed />
      </div>

      {/* ---------------------------------------------------------- the sink */}
      {/* NO NUMBER GOES IN THIS BOX. See the file header: the per-consumer
          split is summed inside the physics model and never published, and
          there is no load-current sensor to publish it. */}
      <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius)",
                    padding: "var(--space-2)", minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", flexWrap: "wrap",
                      gap: "var(--space-2)", minWidth: 0 }}>
          <Header>LOADS</Header>
          <span style={MUTED}>ECU, avionics, payload</span>
        </div>
        <div style={MUTED}>load current is not separately instrumented</div>
      </div>
    </div>
  );
}
