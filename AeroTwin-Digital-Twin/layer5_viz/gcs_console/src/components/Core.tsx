/* The component library of PRD Part 4 section 12.
 *
 * Each of these encodes a rule that is easy to break by accident, so the rule
 * lives beside the component rather than in a document nobody re-reads.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { Measurement, fmt, isDegraded, isMissing, levelColour, levelInk } from "../lib/api";

/* ------------------------------------------------------------------------ */
/* Panel                                                                     */
/* ------------------------------------------------------------------------ */

export function Panel(props: {
  title: string;
  children: React.ReactNode;
  right?: React.ReactNode;
  grow?: boolean;
  bodyStyle?: React.CSSProperties;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);
  // Checked after every render rather than on a timer: the body re-renders
  // when the twin publishes, which is when its content can change height.
  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    setMore(el.scrollHeight - el.clientHeight - el.scrollTop > 2);
  });
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const check = () =>
      setMore(el.scrollHeight - el.clientHeight - el.scrollTop > 2);
    el.addEventListener("scroll", check);
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => { el.removeEventListener("scroll", check); ro.disconnect(); };
  }, []);
  return (
    <section
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--line)",
        borderRadius: "var(--radius-lg)",
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        flex: props.grow ? 1 : undefined,
      }}
    >
      {/* Sentence case at 18 px on the panel's own surface: a title is read,
          not scanned, and a grey band above every panel was nine more boxes
          on a dashboard that already had nine (docs/UX_REDESIGN.md s3.7). */}
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          padding: "12px 16px 4px",
        }}
      >
        <span className="t-section">{props.title}</span>
        {props.right}
      </header>
      <div ref={bodyRef} className="panel-body"
           style={{
             padding: "8px 16px 14px", minHeight: 0, flex: 1, overflow: "auto",
             ...props.bodyStyle,
           }}>
        {props.children}
      </div>
      {/* A PANEL THAT HAS MORE TO SAY MUST SAY SO.
        *
        * The body scrolls when its content does not fit, which is right -- one
        * long panel must not drag a row past the bottom of the screen. But the
        * scrollbar is an OVERLAY in current Chromium: measured on the health
        * page, this panel hid 23 px of content behind a scrollbar 0 px wide,
        * so "CHI (smoothed) 0.9217" sat sliced by the panel edge with nothing
        * to say the rest was there. Styling the scrollbar does not fix it --
        * the browser decides, and headless ignores it entirely.
        *
        * MIL-STD-1472H 5.4.3.2 requires the operator to be able to tell when
        * information is present but not displayed, so the panel states it in
        * words instead of trusting a scrollbar to appear. Drawn in --ink-mute
        * on --bg-raised: furniture, not one of the six coding colours, because
        * hidden content is not a condition of the engine. */}
      {more && (
        <div style={{ borderTop: "1px solid var(--line)",
                      color: "var(--ink-mute)", fontSize: "var(--size-label)",
                      textAlign: "center", padding: "2px 0 3px" }}>
          ▾ More below
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------------ */
/* Parameter readout                                                         */
/* ------------------------------------------------------------------------ */

/**
 * One engine parameter.
 *
 * Three rules are enforced here rather than trusted to the caller:
 *
 *  1. An invalid or missing value renders as "———", never as a number and
 *     never as the last good reading (section 7.2, remove-never-substitute).
 *  2. Colour is never the only carrier of state -- a degraded value also gets
 *     a text tag, so it survives monochrome and colour-vision deficiency
 *     (principle P4, section 13).
 *  3. The value is 30 px; the label and unit are 16 px and deliberately dim.
 *     The number is what the operator reads at a glance -- hierarchy comes
 *     from SIZE and COLOUR, not from shrinking the label below the floor.
 *     This said 13 px, which was true of the token until PRD Part 4 s5.1
 *     was applied: 16 px is the floor for labels and units too, because
 *     an operator reads a label at the same distance as the value it names.
 */
export function Readout(props: {
  label: string;
  m?: Measurement;
  unit: string;
  digits?: number;
  limit?: number;
  warnAbove?: number;
  warnBelow?: number;
  /* The engine strip's form: no box of its own (the strip is the box) and
     the limit on the value's line, so four readouts fit one 72 px row. */
  compact?: boolean;
  /* A line under the value -- the strip uses it for the twin's comparison. */
  below?: React.ReactNode;
}) {
  const missing = isMissing(props.m);
  const degraded = isDegraded(props.m);
  const v = props.m?.value ?? null;
  const state = props.m?.state;

  /* s7.1 GIVES EACH OF THE FIVE STATES A DISTINCT RENDERING, AND THREE OF
   * THEM WERE COLLAPSING INTO ONE.
   *
   * s7 opens by saying why it exists: "the most dangerous failure mode of a
   * monitoring console is a plausible-looking frozen number." What shipped
   * tagged INVALID and MISSING alike as "NO DATA" in the same grey, so an
   * operator could not tell a reading that FAILED ITS PLAUSIBILITY CHECK --
   * a sensor saying something impossible -- from one that had simply never
   * arrived. Those call for different actions.
   *
   * And a STALE value carried the word STALE but never its AGE, which s7.1
   * names explicitly: "the value SHALL be dimmed to --ink-mute AND overlaid
   * with a diagonal-hatch mark AND the age shown ('4.2 s')". Four seconds
   * stale and four minutes stale were the same word.
   */
  let colour = "var(--ink)";
  let tag = "";
  let hatch = false;
  if (state === "STALE") {
    // Dimmed, hatched and aged -- all three, per s7.1.
    colour = "var(--ink-mute)";
    hatch = true;
    const age = props.m?.age_s;
    tag = age != null ? `STALE ${age.toFixed(1)} s` : "STALE";
  } else if (state === "INVALID") {
    // Amber, because a sensor reporting the impossible is a condition the
    // operator must act on -- not merely an absence.
    colour = "var(--alert-caut)";
    tag = "INVALID";
  } else if (state === "MISSING") {
    colour = "var(--ink-mute)";
    tag = "MISSING";
  } else if (state === "SUSPECT") {
    // s7.1: "value shown with a small delta marker and its estimated bias".
    colour = "var(--alert-caut)";
    tag = "Δ SUSPECT";
  } else if (missing) {
    colour = "var(--ink-mute)";
    tag = "NO DATA";
  } else if (degraded) {
    colour = "var(--alert-caut)";
    tag = "SUSPECT";
  } else if (v !== null && props.warnAbove !== undefined && v > props.warnAbove) {
    colour = "var(--alert-warn-ink)";
    tag = "HIGH";
  } else if (v !== null && props.warnBelow !== undefined && v < props.warnBelow) {
    colour = "var(--alert-warn-ink)";
    tag = "LOW";
  }

  return (
    <div
      style={props.compact ? { minWidth: 0 } : {
        background: "var(--bg-raised)",
        border: "1px solid var(--line)",
        borderRadius: "var(--radius)",
        padding: "10px 12px",
        minWidth: 0,
      }}
    >
      <div
        style={{
          fontSize: "var(--size-label)",
          color: "var(--ink-dim)",
          letterSpacing: "0.07em",
          display: "flex",
          justifyContent: props.compact ? "flex-start" : "space-between",
          gap: props.compact ? 12 : 8,
          whiteSpace: "nowrap",
        }}
      >
        <span>{props.label}</span>
        {tag && (
          <span style={{ color: colour, fontWeight: 700 }}>{tag}</span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <span
          style={{
            fontFamily: "var(--font-num)",
            fontSize: "var(--size-readout)",
            fontVariantNumeric: "tabular-nums",
            color: colour,
            lineHeight: 1.15,
            /* s7.1's diagonal hatch. A second, non-colour channel saying the
               digits are not current -- P4 again, and the one that matters
               most, because a stale number is the failure this section of
               the standard was written about. */
            ...(hatch ? { position: "relative", paddingInline: 2 } : {}),
          }}
        >
          {fmt(props.m, props.digits ?? 1)}
          {/* s7.1's diagonal hatch, drawn as an SVG PATTERN rather than a
              repeating-linear-gradient.
              The gradient version worked and was still wrong: s3.3f forbids
              gradients "anywhere", on the grounds that they defeat the
              chrominance separation and luminance contrast the rest of s3
              depends on. The rule does not carve out the ones that happen to
              be flat, and a check that accepted "but mine is really a
              pattern" would be a check with an argument in it. So: lines.

              A second, non-colour channel saying these digits are not
              current -- P4 applied where it matters most, because a stale
              number that still looks live is the failure s7 was written
              about. */}
          {hatch && (
            <svg aria-hidden="true" style={{
              position: "absolute", inset: 0, width: "100%", height: "100%",
              pointerEvents: "none",
            }}>
              <pattern id="stale-hatch" width="6" height="6"
                       patternUnits="userSpaceOnUse"
                       patternTransform="rotate(-45)">
                <line x1="0" y1="0" x2="0" y2="6"
                      stroke="currentColor" strokeWidth="1.4" />
              </pattern>
              <rect width="100%" height="100%" fill="url(#stale-hatch)" />
            </svg>
          )}
        </span>
        <span style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)" }}>
          {props.unit}
        </span>
        {props.compact && props.limit !== undefined && (
          <span style={{ fontSize: 16, color: "var(--ink-mute)", whiteSpace: "nowrap" }}>
            {props.warnBelow !== undefined || props.label.startsWith("OIL") ? "min" : "max"}{" "}
            {Math.round(props.limit * 10) / 10}
          </span>
        )}
      </div>
      {!props.compact && props.limit !== undefined && (
        <div style={{ fontSize: 16, color: "var(--ink-mute)" }}>
          limit {props.limit}
        </div>
      )}
      {props.below && <div>{props.below}</div>}
    </div>
  );
}

/* PAGES, NOT A SCROLLBAR, FOR A LIST LONGER THAN THE SCREEN.
 *
 * The fleet roster (200 engines) and the audit log ran on inside a scrolling
 * panel with MORE BELOW under it. A page of rows with "3 / 25" and two large
 * buttons says how much there is and where the operator is in it, and nothing
 * slides out of view as it is being read. */
export function Pager(props: { page: number; pages: number; onPage: (p: number) => void }) {
  const { page, pages, onPage } = props;
  if (pages <= 1) return null;
  const b: React.CSSProperties = {
    minWidth: 44, minHeight: 36, fontSize: 16, cursor: "pointer",
    background: "var(--bg-raised)", color: "var(--ink)",
    border: "1px solid var(--line)", borderRadius: "var(--radius)",
  };
  return (
    <span style={{ display: "inline-flex", gap: 8, alignItems: "center", fontSize: 16 }}>
      <button aria-label="previous page" style={b} disabled={page <= 0}
              onClick={() => onPage(Math.max(0, page - 1))}>◀</button>
      <span style={{ fontFamily: "var(--font-num)", minWidth: 64, textAlign: "center" }}>
        {page + 1} / {pages}
      </span>
      <button aria-label="next page" style={b} disabled={page >= pages - 1}
              onClick={() => onPage(Math.min(pages - 1, page + 1))}>▶</button>
    </span>
  );
}

/* WHAT THE HEALTH FIGURES ARE, said beside them.
 *
 * The engine's condition is judged only warm, loaded and steady (thresholds
 * health.assessment). Outside that the last warm judgement is held, and before
 * the first one there is none. Without this line a held 0.95 on a stopped
 * engine reads as a live measurement, and a blank reads as a fault. */
export function AssessmentNote(props: {
  a?: { state: string; age_s: number | null; reason: string } | null;
}) {
  const a = props.a;
  if (!a || a.state === "live") return null;
  const age = a.age_s == null ? ""
    : a.age_s >= 3600 ? ` ${(a.age_s / 3600).toFixed(1)} h ago`
    : a.age_s >= 60 ? ` ${Math.round(a.age_s / 60)} min ago`
    : ` ${Math.round(a.age_s)} s ago`;
  return (
    <div title={a.reason} style={{ fontSize: 16, color: "var(--ink-mute)" }}>
      {a.state === "held"
        ? `Held from last warm running,${age}`
        : "Not assessed yet: engine not warm"}
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Master annunciators                                                       */
/* ------------------------------------------------------------------------ */

/**
 * MIL-STD-411F 5.2.7 master warning / caution.
 *
 * LIT, IT FLASHES; PRESSED, IT GOES OUT. The master is lit by a NEW alert of
 * its category and extinguished by push-to-reset, while the alert itself stays
 * in the list and a later new alert lights the master again (411F 5.1.3.5,
 * 5.1.4.5, 4.1.3.8). The server does all of that; this draws it.
 *
 * 411F 5.1.3.4 / 5.1.4.4 make the master steady-ON "unless a flashing
 * presentation is approved by the acquiring activity". It is approved for this
 * console (PRD Part 4 s4.2e, 23 Sep 2026): a steady lamp in a bar full of
 * steady text was being read past. The rates are MIL-STD-1472H 5.17.27's --
 * warning 3 Hz at 50 %, caution 1 Hz at 70 % on -- two rates 2 Hz apart, each
 * from one shared clock so every lamp of a kind flashes together. The LEGEND
 * never flashes (1472H 5.17.27.5): the lamp swaps between filled and outlined,
 * and the words are legible in both. The first version of this flashed the
 * whole lamp whatever it meant and never stopped because reset was broken
 * (HMI-04); reset works, and flashing ends with it.
 *
 * Resetting the WARNING master is a two-step action (s9.2): the first press
 * arms it for four seconds, the second confirms.
 */
export function Master(props: {
  label: string;
  active: boolean;
  colour: string;
  onAck: () => void;
  confirm?: boolean;
  /* Which flash: "warning" 3 Hz, "caution" 1 Hz. */
  kind?: "warning" | "caution";
}) {
  const fast = useFlashPhase();
  const slow = useSlowFlashPhase();
  const lit = !props.active ? false
    : props.kind === "warning" ? fast
    : props.kind === "caution" ? slow
    : true;
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = window.setTimeout(() => setArmed(false), 4000);
    return () => window.clearTimeout(t);
  }, [armed]);
  const press = () => {
    if (props.confirm && !armed) {
      setArmed(true);
      return;
    }
    setArmed(false);
    props.onAck();
  };
  return (
    <button
      onClick={press}
      disabled={!props.active}
      style={{
        /* MIL-STD-1472H: 13 mm minimum touch target; 19 mm for a critical
         * control. At 96 dpi, 19 mm is 72 px. */
        minWidth: 132,
        minHeight: 44,
        /* Never squeezed: a master that wraps onto two lines in a crowded
           status bar is a master that reads as something else. */
        flexShrink: 0,
        whiteSpace: "nowrap",
        padding: "6px 14px",
        borderRadius: "var(--radius)",
        border: `2px solid ${props.active ? props.colour : "var(--line)"}`,
        // Filled on the ON phase, outlined on the OFF phase: the lamp flashes,
        // the legend stays readable in the lamp's own colour.
        background: lit ? props.colour : "transparent",
        color: lit ? "#05070A" : props.active ? props.colour : "var(--ink-mute)",
        fontWeight: 800,
        fontSize: 16,
        letterSpacing: "0.08em",
        cursor: props.active ? "pointer" : "default",
      }}
      title={props.active ? "Acknowledge (silences, does not clear)" : "No active alert"}
    >
      {armed ? "CONFIRM RESET" : props.label}
    </button>
  );
}

/* ------------------------------------------------------------------------ */
/* Alert stack                                                               */
/* ------------------------------------------------------------------------ */

export interface AlertRow {
  rule_id: string;
  legend: string;
  level: number;
  category: string;
  advisory: string;
  value: number | null;
  limit: number | null;
  first_seen_s: number;
  /* s8.2(a): flashing is for "a *new, unacknowledged* WARNING-level alert".
   * The server has been sending this on every row from the start and nothing
   * read it, so no row ever flashed and the whole of s8.2 -- the .flash class,
   * the 3 Hz keyframes, the reduced-motion fallback -- was dead code. */
  acknowledged?: boolean;
}

/* ONE CLOCK FOR THE WHOLE CONSOLE (s8.2d).
 *
 * MIL-STD-1472H 5.17.27.4 and 411F 4.1.3.5 both require simultaneously
 * flashing items to be SYNCHRONISED, and s8.2d says how: "implemented from a
 * single shared clock, not per-component timers".
 *
 * A CSS animation cannot do this. Two rows that appear a quarter of a second
 * apart each start their own animation from zero and flash in antiphase, which
 * is precisely the "two different meanings" the standard is guarding against.
 * So the phase is computed once, here, and every flashing element on every
 * page reads the same boolean.
 *
 * 3 Hz at a 50 % duty cycle (s8.2b, s8.2c) is a half-period of 166.7 ms.
 */
const FLASH_HALF_PERIOD_MS = 1000 / 3 / 2;
let flashPhase = true;
const flashListeners = new Set<(on: boolean) => void>();
let flashTimer: number | undefined;

function reducedMotion(): boolean {
  return typeof window !== "undefined"
    && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

/** The shared annunciator phase. `true` means ON. */
export function useFlashPhase(): boolean {
  const [on, setOn] = useState(flashPhase);
  useEffect(() => {
    // s8.1d: an operator who has asked for reduced motion gets a steady lamp,
    // not a missing one -- the static outline in tokens.css carries it.
    if (reducedMotion()) { setOn(true); return; }
    flashListeners.add(setOn);
    if (flashTimer === undefined) {
      flashTimer = window.setInterval(() => {
        flashPhase = !flashPhase;
        for (const fn of flashListeners) fn(flashPhase);
      }, FLASH_HALF_PERIOD_MS);
    }
    return () => {
      flashListeners.delete(setOn);
      if (flashListeners.size === 0 && flashTimer !== undefined) {
        window.clearInterval(flashTimer);
        flashTimer = undefined;
      }
    };
  }, []);
  return on;
}

/* THE SECOND FLASH RATE, for the master CAUTION: 1 Hz, 70 % on
 * (MIL-STD-1472H 5.17.27 visual alert table; 5.17.27.3 allows two rates, at
 * least 2 Hz apart, the lower no slower than 0.8 Hz). One shared clock, for
 * the same synchronisation reason as the fast one. */
const SLOW_ON_MS = 700;
const SLOW_OFF_MS = 300;
let slowPhase = true;
const slowListeners = new Set<(on: boolean) => void>();
let slowTimer: number | undefined;

function slowTick() {
  slowPhase = !slowPhase;
  for (const fn of slowListeners) fn(slowPhase);
  slowTimer = window.setTimeout(slowTick, slowPhase ? SLOW_ON_MS : SLOW_OFF_MS);
}

/** The shared 1 Hz annunciator phase. `true` means ON. */
export function useSlowFlashPhase(): boolean {
  const [on, setOn] = useState(slowPhase);
  useEffect(() => {
    if (reducedMotion()) { setOn(true); return; }
    slowListeners.add(setOn);
    if (slowTimer === undefined) {
      slowTimer = window.setTimeout(slowTick, slowPhase ? SLOW_ON_MS : SLOW_OFF_MS);
    }
    return () => {
      slowListeners.delete(setOn);
      if (slowListeners.size === 0 && slowTimer !== undefined) {
        window.clearTimeout(slowTimer);
        slowTimer = undefined;
      }
    };
  }, []);
  return on;
}

/**
 * MIL-STD-411F 5.2.5: warnings first, then cautions, then advisories, and
 * newest first within a category. An operator scanning top-down must reach the
 * most urgent item first, whatever arrived last.
 *
 * Section 4.1.1a: a healthy engine shows NOTHING here -- not a green "all
 * systems normal" banner, which trains the eye to expect text in this region
 * and slows the detection of real text.
 */
/* THE GLYPH, WITHOUT WHICH THE ALERT STACK IS COLOUR-ONLY CODING.
 *
 * s13(a) says what an alert is coded by, and it is a list of five things:
 * "hue + glyph + legend + position + (for warnings) flash". The rows carried
 * hue, legend and position. There was no glyph, and the category word was
 * never rendered either -- so a WARNING and a CAUTION differed by the colour
 * of a 4 px bar and nothing else. Grey the alert tokens, as the s15
 * MONOCHROME TEST asks, and the two became indistinguishable.
 *
 * That is P4 ("colour is never the only channel"), s13(a) on the 8 % of men
 * with a colour-vision deficiency, and s13(b), which notes that
 * laser-protective eyewear induces selective colour blindness and therefore
 * bars colour as a sole channel in ANY operational system.
 *
 * Drawn as geometry rather than a character: s14 forbids emoji as status
 * icons, and a glyph that depends on a font is a glyph that can go missing.
 * The shapes follow the convention an operator already knows -- triangle for
 * a hazard, diamond for a caution, circle for information.
 */
function AlertGlyph({ level }: { level: number }) {
  const c = levelInk(level);
  const common = { width: 18, height: 18, viewBox: "0 0 18 18",
                   "aria-hidden": true, style: { flex: "0 0 auto", marginTop: 2 } };
  if (level >= 5) {
    return (
      <svg {...common}><title>WARNING</title>
        <path d="M9 1.5 L17 16 H1 Z" fill="none" stroke={c} strokeWidth={2}
              strokeLinejoin="round" />
        <path d="M9 6.5 v4.5" stroke={c} strokeWidth={2} strokeLinecap="round" />
        <circle cx={9} cy={13.4} r={1.1} fill={c} />
      </svg>
    );
  }
  if (level >= 3) {
    return (
      <svg {...common}><title>CAUTION</title>
        <path d="M9 1.5 L16.5 9 L9 16.5 L1.5 9 Z" fill="none" stroke={c}
              strokeWidth={2} strokeLinejoin="round" />
        <path d="M9 5.6 v4.6" stroke={c} strokeWidth={2} strokeLinecap="round" />
        <circle cx={9} cy={12.6} r={1.05} fill={c} />
      </svg>
    );
  }
  return (
    <svg {...common}><title>ADVISORY</title>
      <circle cx={9} cy={9} r={7.5} fill="none" stroke={c} strokeWidth={2} />
      <circle cx={9} cy={5.4} r={1.05} fill={c} />
      <path d="M9 8.4 v4.4" stroke={c} strokeWidth={2} strokeLinecap="round" />
    </svg>
  );
}

/* The category as a WORD, which s13(c) requires by name for advisories --
 * "cyan advisories are always accompanied by the ADVS legend to separate them
 * from green normal states" -- and which costs nothing to give all three. */
function categoryTag(level: number): string {
  return level >= 5 ? "WARN" : level >= 3 ? "CAUT" : "ADVS";
}

export function AlertStack(props: {
  alerts: AlertRow[]; overflow: number;
  /* The procedure for a row, when there is one (configs/checklists.yaml). */
  onProcedure?: (a: AlertRow) => void;
  hasProcedure?: (a: AlertRow) => boolean;
}) {
  const lit = useFlashPhase();
  const ordered = [...props.alerts].sort(
    (a, b) => b.level - a.level || b.first_seen_s - a.first_seen_s,
  );

  if (ordered.length === 0) {
    return (
      <div style={{ color: "var(--ink-mute)", fontSize: 16, padding: "6px 2px" }}>
        No active alerts.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {ordered.map((a) => (
        <div
          key={a.rule_id}
          style={{
            display: "flex",
            gap: 10,
            padding: "8px 10px",
            background: "var(--bg-raised)",
            /* s8.2(e): "Text SHALL NOT flash. The flashing element is the
               alert row's status bar / background tint, never the legend."
               So the 4 px bar carries it and the legend beside it does not
               move. s8.2(g): only a small area flashes at any time -- four
               pixels of one row is as small as this gets.
               s8.2(a): a NEW, UNACKNOWLEDGED WARNING only. A caution does not
               flash, and neither does a warning the operator has seen. */
            borderLeft: `4px solid ${levelColour(a.level)}`,
            borderLeftColor:
              a.level >= 5 && !a.acknowledged && !lit
                ? "var(--bg-raised)"
                : levelColour(a.level),
            borderRadius: "var(--radius)",
          }}
        >
          <AlertGlyph level={a.level} />
          {/* A NARROW RAIL WANTS ROWS, NOT COLUMNS.
              The value used to sit in a third column beside the legend, which
              in a 300 px Zone D left the legend two words wide and wrapped
              "CHT HIGH" onto two lines with 134.7 / 135 jammed against it.
              Category and value share the top line -- both are short and
              fixed-width -- and the legend then gets the full width it needs
              to stay on one line, which s4.4 caps at 24 characters anyway. */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              display: "flex", alignItems: "baseline", gap: 8,
              color: levelInk(a.level),
            }}>
              <span style={{
                fontSize: 16, padding: "0 5px", flex: "0 0 auto",
                border: "1px solid currentColor", borderRadius: 2,
                letterSpacing: "0.08em", fontWeight: 700,
              }}>{categoryTag(a.level)}</span>
              {a.value !== null && (
                <span style={{
                  marginLeft: "auto", flex: "0 0 auto",
                  fontFamily: "var(--font-num)",
                  fontVariantNumeric: "tabular-nums",
                  color: "var(--ink)", fontSize: 16, whiteSpace: "nowrap",
                }}>
                  {a.value.toFixed(1)}
                  {a.limit !== null && (
                    <span style={{ color: "var(--ink-mute)" }}>
                      {" / "}{a.limit.toFixed(0)}
                    </span>
                  )}
                </span>
              )}
            </div>
            <div
              style={{
                fontWeight: 700,
                /* s3.4a wants 7:1 on an alert legend; levelColour returns the
                   saturated lamp hues, which reach 4.93:1 for WARNING. */
                color: levelInk(a.level),
                letterSpacing: "0.05em",
                fontSize: 21,   /* s5.1 alert legend minimum (HMI-05) */
                marginTop: 2,
              }}
            >
              {a.legend}
            </div>
            {a.advisory && (
              <div style={{ color: "var(--ink-dim)", fontSize: 16, marginTop: 2 }}>
                {a.advisory}
              </div>
            )}
            {/* Every alert with its action (ISA-18.2): the full procedure
                is one press away, in the same place on every row. */}
            {props.onProcedure && (props.hasProcedure?.(a) ?? true) && (
              <button className="btn" style={{ marginTop: 8, minHeight: 36 }}
                      onClick={() => props.onProcedure?.(a)}>
                Procedure
              </button>
            )}
          </div>
        </div>
      ))}
      {props.overflow > 0 && (
        /* Section 4: overflow is COUNTED, never silently dropped. An operator
         * must know the list is longer than the space. */
        <div style={{ color: "var(--alert-caut)", fontSize: 16, fontWeight: 700 }}>
          +{props.overflow} MORE (not shown)
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Bar                                                                       */
/* ------------------------------------------------------------------------ */

export function Bar(props: {
  label: string;
  value: number | null;
  min: number;
  max: number;
  limit?: number;
  colour?: string;
  unit?: string;
}) {
  const v = props.value;
  const frac =
    v === null ? 0 : Math.max(0, Math.min(1, (v - props.min) / (props.max - props.min)));
  const limFrac =
    props.limit === undefined
      ? null
      : Math.max(0, Math.min(1, (props.limit - props.min) / (props.max - props.min)));

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <span
        style={{
          width: 34,
          fontSize: "var(--size-label)",
          color: "var(--ink-dim)",
          flexShrink: 0,
        }}
      >
        {props.label}
      </span>
      <div
        style={{
          flex: 1,
          height: 16,
          background: "var(--bg-void)",
          border: "1px solid var(--line)",
          borderRadius: 2,
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div
          className="bar-fill"
          style={{
            width: `${frac * 100}%`,
            height: "100%",
            background: props.colour ?? "var(--state-normal)",
            /* s8.1c(ii) caps this at 150 ms; it read 220. The class
               carries it so prefers-reduced-motion can remove it. */
          }}
        />
        {limFrac !== null && (
          /* The certified limit is drawn as a magenta bug -- the colour
           * DO-257A reserves for a reference the operator is flying to. */
          <div
            style={{
              position: "absolute",
              left: `${limFrac * 100}%`,
              top: 0,
              bottom: 0,
              width: 2,
              background: "var(--ref-selected)",
            }}
          />
        )}
      </div>
      <span
        style={{
          width: 68,
          textAlign: "right",
          fontFamily: "var(--font-num)",
          fontVariantNumeric: "tabular-nums",
          fontSize: 16,
          color: v === null ? "var(--ink-mute)" : "var(--ink)",
        }}
      >
        {v === null ? "———" : v.toFixed(1)}
        {props.unit && <span style={{ color: "var(--ink-mute)" }}> {props.unit}</span>}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Trend chart                                                               */
/* ------------------------------------------------------------------------ */

/**
 * Measured against the physics prediction.
 *
 * The prediction is a DASHED line in neutral grey. Line style carries the
 * distinction and colour only reinforces it, so the chart still reads on a
 * monochrome printout and for a red-green colour-deficient operator
 * (principle P4).
 */
export function Trend(props: {
  series: (number | null)[];
  predicted?: (number | null)[];
  colour?: string;
  height?: number;
  unit?: string;
  label?: string;
}) {
  const h = props.height ?? 120;
  const w = 600;
  const vals = props.series.filter((x): x is number => x !== null);
  const pvals = (props.predicted ?? []).filter((x): x is number => x !== null);
  const all = [...vals, ...pvals];
  if (all.length < 2) {
    return (
      <div style={{ height: h, color: "var(--ink-mute)", fontSize: 16, padding: 8 }}>
        Collecting data…
      </div>
    );
  }
  const lo = Math.min(...all);
  const hi = Math.max(...all);

  /* A FLAT SERIES IS NOT A ±1 SERIES.
   *
   * The pad used to be `(hi - lo) * 0.15 || 1`, and the `|| 1` is the whole
   * problem: when nothing has changed, `hi - lo` is 0, so the fallback put a
   * RATIO between 0 and 1 on an axis running -0.03 to 1.97. A held composite
   * health index -- 240 identical samples of 0.9698, which is what a shut-down
   * engine reports -- drew as a lone flat line adrift in an empty band, under
   * a label reading "1.0 / 1.0" because both ends rounded to the same figure.
   * The chart said nothing and looked broken saying it.
   *
   * The pad is now proportional to the DATA, not to its spread, so a flat
   * series is framed sensibly instead of being scaled into a corner, and the
   * caller is told the series is flat rather than being handed a line that
   * implies a measurement which never moved. */
  const flat = hi - lo < Math.max(Math.abs(hi), 1e-9) * 1e-6;
  const pad = flat ? Math.max(Math.abs(hi) * 0.08, 1e-6) : (hi - lo) * 0.15;
  const y0 = lo - pad;
  const y1 = hi + pad;

  /* Enough figures to distinguish the two ends. One decimal is right for a
   * cylinder head in degrees and useless for a ratio between 0 and 1. */
  const digits = Math.abs(hi) < 10 ? 3 : 1;

  const path = (data: (number | null)[]) => {
    const n = data.length;
    let d = "";
    let started = false;
    data.forEach((v, i) => {
      if (v === null) {
        started = false;
        return;
      }
      const x = (i / Math.max(n - 1, 1)) * w;
      const y = h - ((v - y0) / (y1 - y0)) * h;
      d += `${started ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
      started = true;
    });
    return d;
  };

  return (
    <div>
      {props.label && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: "var(--size-label)",
            color: "var(--ink-dim)",
            marginBottom: 4,
          }}
        >
          <span>{props.label}</span>
          {/* A range, when there is one. "0.970 / 0.970" is not a range, and
              printing it twice invites the reader to look for a difference
              that is not there -- so a flat series says so in words instead. */}
          <span>
            {flat
              ? `${hi.toFixed(digits)}${props.unit ? " " + props.unit : ""}, not changing`
              : `${hi.toFixed(digits)} / ${lo.toFixed(digits)}${props.unit ? " " + props.unit : ""}`}
          </span>
        </div>
      )}
      {/* NO CHART FOR A SERIES THAT DOES NOT MOVE.
          A straight rule drawn across an empty band is not a smaller version
          of a chart, it is a chart-shaped hole: it occupies the height of real
          evidence while carrying none, and it invites the reader to look for a
          slope that cannot be there. The line above has already said the value
          and said it is steady, which is the whole of what there is to say. */}
      {!flat && (
      <svg
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height: h, display: "block" }}
      >
        <path
          d={path(props.series)}
          fill="none"
          stroke={props.colour ?? "var(--state-normal)"}
          strokeWidth={2}
          vectorEffect="non-scaling-stroke"
        />
        {props.predicted && (
          <path
            d={path(props.predicted)}
            fill="none"
            stroke="var(--phys)"
            strokeWidth={1.5}
            strokeDasharray="6 4"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------ */

export function KeyValue(props: { k: string; v: React.ReactNode; dim?: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 12,
        padding: "5px 0",
        borderBottom: "1px solid var(--line)",
        fontSize: 16,
      }}
    >
      <span style={{ color: "var(--ink-dim)" }}>{props.k}</span>
      <span
        style={{
          fontFamily: "var(--font-num)",
          fontVariantNumeric: "tabular-nums",
          color: props.dim ? "var(--ink-mute)" : "var(--ink)",
          textAlign: "right",
        }}
      >
        {props.v}
      </span>
    </div>
  );
}
