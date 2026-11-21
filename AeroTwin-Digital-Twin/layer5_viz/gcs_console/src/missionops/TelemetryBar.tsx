/* THE ENGINE INSTRUMENT BAR — one continuous strip, and it always says whose
 * numbers these are.
 *
 * Each channel is a label, a number with its unit, a thin calibrated bar and
 * the scale underneath it. No icons, no gauges, no cards: an instrument panel
 * is read by scanning one row of numbers and seeing where each one sits on its
 * own scale, which is what the bar and the ticks are for and what a picture of
 * a thermometer is not.
 *
 * TWO SOURCES, NEVER MIXED
 * ------------------------
 *   LIVE · ENGINE NOW    while the sortie is being planned. The twin's own
 *                        reported channels and the margins it publishes, which
 *                        is what the ENGINE and HEALTH pages read.
 *   FLOWN SORTIE         once a sortie exists. The FlightSample under the
 *                        playback cursor, written to the DOM by the clock.
 *
 * They are two different engines at two different moments -- one running on the
 * ramp now, one flown through a model for a route that has not happened -- so
 * putting them in one row side by side would invite the reading that the sortie
 * moved the live needle.
 *
 * WHERE THE NUMBERS COME FROM. The value, its limit and its unit are taken from
 * `snap.display.margins[]` where the twin publishes them, and from
 * `snap.twin.reported.*` otherwise, with each channel's `state` respected -- a
 * channel that is not VALID reads as a dash, never as a held number. The flown
 * side reads `FlightSample` and the certified limits from `limitsFrom()` in
 * mission/Analysis.tsx, which is the same configs/thresholds.yaml table the
 * server judged the sortie with.
 *
 * WHAT IS NOT HERE. No health index, degradation or remaining life against the
 * SORTIE: `FlightSample` carries measured channels only, and the RUL pipeline
 * runs against the real engine. HEALTH INDEX and REMAINING LIFE belong to the
 * live twin and are labelled as the live twin; the flown side carries MARGIN
 * instead -- how much of the nearest certified limit is still in hand.
 *
 * THE SCALES are fixed, not fitted to the value, because an instrument whose
 * scale moves cannot be read at a glance. They are the ranges in the reference
 * design, widened only where a real limit sits outside one (EGT is certified at
 * 950 degC, so its scale runs to 1000 rather than 750) and, for remaining life,
 * stepped up a decade at a time when the estimate is larger than the scale.
 */

import { useEffect, useMemo, useRef } from "react";

import type { FlightSample, FlightSim } from "../lib/api";
import { limitsFrom } from "../mission/Analysis";
import { Playback } from "../mission/clock";
import { fmtClock } from "../mission/plan";

export type Source = "LIVE" | "FLOWN";

/* ------------------------------------------------------------------ *
 * Scales
 * ------------------------------------------------------------------ */

interface Scale { max: number; ticks: number[]; fmt?: (n: number) => string }

const k = (n: number) => (n === 0 ? "0" : n >= 1000 ? n / 1000 + "k" : String(n));

const SCALE = {
  rpm:      { max: 6000, ticks: [0, 2000, 4000, 6000], fmt: k },
  coolant:  { max: 150, ticks: [0, 50, 100, 150] },
  cht:      { max: 300, ticks: [0, 100, 200, 300] },
  egt:      { max: 1000, ticks: [0, 250, 500, 750, 1000], fmt: k },
  oilTemp:  { max: 150, ticks: [0, 50, 100, 150] },
  oilPress: { max: 60, ticks: [0, 20, 40, 60] },
  altitude: { max: 24000, ticks: [0, 8000, 16000, 24000], fmt: k },
  clearance: { max: 5000, ticks: [0, 2500, 5000], fmt: k },
  power:    { max: 120, ticks: [0, 60, 120] },
} satisfies Record<string, Scale>;

/* REMAINING LIFE is the one quantity whose useful range is not known in
 * advance: a fresh engine has hundreds of hours and a worn one has five. The
 * scale is the reference's 0-20 h until the estimate outgrows it and then the
 * next decade up, so the bar keeps meaning without the number being clipped. */
function lifeScale(h: number): Scale {
  const max = [20, 50, 100, 250, 500, 1000, 2500].find((m) => h <= m) ?? 5000;
  return { max, ticks: [0, max / 2, max], fmt: (n) => (n >= 1000 ? k(n) : String(n)) };
}

/* ------------------------------------------------------------------ *
 * One instrument
 * ------------------------------------------------------------------ */

const LABEL: React.CSSProperties = {
  fontSize: "var(--size-label)", color: "var(--ink-dim)", fontWeight: 600,
  letterSpacing: "0.09em", whiteSpace: "nowrap",
  overflow: "hidden", textOverflow: "ellipsis",
};

const VALUE: React.CSSProperties = {
  fontFamily: "var(--font-num)", fontSize: 21, fontWeight: 700,
  color: "var(--ink)", whiteSpace: "nowrap", lineHeight: 1.1,
};

const UNIT: React.CSSProperties = {
  fontSize: "var(--size-label)", color: "var(--ink-mute)", whiteSpace: "nowrap",
};

/* THE SCALE UNDER EACH BAR IS TEXT, and s5.1's 16 px floor is explicit that
   it covers labels and units, not only values: an operator reads the scale at
   the same distance as the number above it. At the working width the four
   labels of a 0-50-100-150 scale measure about 87 px across a 128 px track,
   so they fit; `sparse` still drops the middle pair on a narrow band, where
   they would not. */
const TICK: React.CSSProperties = {
  position: "absolute", top: 0, fontSize: "var(--size-label)", lineHeight: 1,
  fontFamily: "var(--font-num)", color: "var(--ink-mute)", whiteSpace: "nowrap",
};

/** The calibrated bar: a track with its scale marked on it, a fill, and where
 *  there is a certified limit, a mark showing where on the scale it falls. */
function Bar(props: {
  scale?: Scale;
  /** Live: the fraction and hue now. Flown: written per frame through the ref. */
  fill?: { frac: number; hue: string };
  fillRef?: (el: HTMLDivElement | null) => void;
  limit?: number | null;
  /** A status bar has no scale: it is full width and the fill IS the reading. */
  status?: boolean;
  /** Narrow: the scale keeps its marks but labels only its two ends, because
   *  four numbers in 112 px is four numbers touching each other. */
  sparse?: boolean;
}) {
  const s = props.scale;
  const pct = (n: number) => (s ? Math.max(0, Math.min(1, n / s.max)) * 100 : 0);
  /* CLAMPED HERE, ONCE. A channel reading below its zero -- a cold-soaked
   * coolant on the ramp reads a few degrees under -- produced a negative
   * width, which CSS discards, and the fill then took the width of its track:
   * an empty instrument drawn as a full one. */
  const frac = props.fill ? Math.max(0, Math.min(1, props.fill.frac)) : 0;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
      <div style={{ position: "relative", height: props.status ? 9 : 8,
                    borderRadius: 2, background: "var(--bg-raised)",
                    border: "1px solid var(--line)", overflow: "hidden" }}>
        <div className="mo-bar" ref={props.fillRef}
             style={{ height: "100%", minWidth: frac > 0 ? 3 : 0,
                      width: (frac * 100).toFixed(1) + "%",
                      background: props.fill?.hue ?? "var(--state-normal)" }} />
        {/* The scale, marked on the track the way an instrument face is. */}
        {s && s.ticks.slice(1, -1).map((t) => (
          <div key={t} style={{ position: "absolute", top: 0, bottom: 0, width: 1,
                                left: pct(t) + "%", background: "var(--line)" }} />
        ))}
        {/* Where the certified limit falls on this scale. */}
        {s && props.limit != null && props.limit > 0 && props.limit <= s.max && (
          <div title={"certified limit " + props.limit}
               style={{ position: "absolute", top: 0, bottom: 0, width: 2,
                        left: pct(props.limit) + "%",
                        background: "var(--ink-mute)", opacity: 0.85 }} />
        )}
      </div>
      {s && (
        <div style={{ position: "relative", height: 17 }} aria-hidden="true">
          {s.ticks.map((t, i) => {
            const last = i === s.ticks.length - 1;
            if (props.sparse && i !== 0 && !last) return null;
            return (
              <span key={t} style={{ ...TICK, left: pct(t) + "%",
                                     transform: i === 0 ? "none"
                                       : last ? "translateX(-100%)"
                                       : "translateX(-50%)" }}>
                {(s.fmt ?? String)(t)}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Instrument(props: {
  k: string; title?: string; children: React.ReactNode;
  scale?: Scale; fill?: { frac: number; hue: string };
  fillRef?: (el: HTMLDivElement | null) => void;
  limit?: number | null; status?: boolean; min?: number; sparse?: boolean;
  /** The first instrument in the row has the source block's rule to its left. */
  first?: boolean;
}) {
  return (
    /* ONE PANEL, NOT A ROW OF CARDS: the groups are separated by a hairline
       and nothing else -- no box, no fill, no shadow. */
    <div title={props.title}
         style={{ flex: "1 1 0", minWidth: props.min ?? 128, display: "flex",
                  flexDirection: "column", gap: 2,
                  paddingLeft: props.first ? 0 : "var(--space-3)", paddingRight: 2,
                  borderLeft: props.first ? undefined : "1px solid var(--line)" }}>
      <div style={LABEL}>{props.k.toUpperCase()}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4, minWidth: 0,
                    marginBottom: 3 }}>
        {props.children}
      </div>
      <Bar scale={props.scale} fill={props.fill} fillRef={props.fillRef}
           limit={props.limit} status={props.status} sparse={props.sparse} />
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * The bar
 * ------------------------------------------------------------------ */

export function TelemetryBar(props: {
  source: Source;
  snap: any;
  pb: Playback;
  sim: FlightSim | null;
  engine: any;
  /** Under about 1150 px the instruments tighten before the row scrolls. */
  compact: boolean;
}) {
  const flown = props.source === "FLOWN" && !!props.sim && props.pb.samples.length > 0;
  return (
    <div className={flown ? "mo-live" : undefined}
         style={{ display: "flex", alignItems: "stretch", gap: "var(--space-3)",
                  minWidth: 0, height: "100%" }}>
      <Source_ live={!flown} pb={props.pb} snap={props.snap} />
      <div style={{ width: 1, background: "var(--line)", flex: "0 0 auto" }} />
      {/* THE ROW SCROLLS RATHER THAN CRAMPING. Below the width the instruments
          need, the strip slides instead of shrinking its digits past reading
          size -- the numbers are the instrument. */}
      <div className="mo-instruments"
           style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "flex-start",
                    gap: "var(--space-4)", overflowX: "auto", overflowY: "hidden",
                    scrollbarWidth: "thin" }}>
        {flown
          ? <Flown pb={props.pb} sim={props.sim!} engine={props.engine}
                   compact={props.compact} />
          : <Live snap={props.snap} compact={props.compact} />}
      </div>
    </div>
  );
}

/* Whose numbers, and from when. */
function Source_(props: { live: boolean; pb: Playback; snap: any }) {
  const clock = useRef<HTMLDivElement>(null);
  const phase = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (props.live) return;
    return props.pb.subscribe((t) => {
      const s = props.pb.samples[props.pb.indexAt(t)];
      if (clock.current) clock.current.textContent = "T+ " + fmtClock(t);
      if (phase.current && s) {
        phase.current.textContent =
          s.leg && s.leg !== s.phase ? s.phase + " · " + s.leg : s.phase;
      }
    });
  }, [props.pb, props.live]);

  const age = props.snap?.twin?.reported?.rpm?.age_s;
  return (
    <div className="mo-state"
         style={{ flex: "0 0 auto", width: 172, display: "flex",
                  flexDirection: "column", gap: 3, paddingRight: "var(--space-3)",
                  overflow: "hidden" }}>
      <div style={{ fontSize: "var(--size-label)", fontWeight: 700,
                    letterSpacing: "0.08em", whiteSpace: "nowrap",
                    color: props.live ? "var(--state-normal)" : "var(--alert-advis)" }}>
        {props.live ? "LIVE · ENGINE NOW" : "FLOWN SORTIE"}
      </div>
      {props.live ? (
        <>
          <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                        whiteSpace: "nowrap" }}>
            {typeof age === "number" ? "the twin, " + age.toFixed(1) + " s old"
                                     : "the twin"}
          </div>
          <div style={{ fontFamily: "var(--font-num)", fontSize: "var(--size-label)",
                        color: "var(--ink-mute)", whiteSpace: "nowrap" }}>
            {props.snap?.wall_utc ?? ""}
          </div>
        </>
      ) : (
        <>
          <div ref={clock} className="mo-num"
               style={{ fontFamily: "var(--font-num)", fontSize: 18, fontWeight: 700,
                        whiteSpace: "nowrap" }}>T+ 0:00:00</div>
          <div ref={phase} style={{ fontSize: "var(--size-label)",
                                    color: "var(--ink-mute)", whiteSpace: "nowrap",
                                    overflow: "hidden", textOverflow: "ellipsis" }} />
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * LIVE — the twin as it is running now
 * ------------------------------------------------------------------ */

interface Margin { name: string; value: number; limit: number; margin: number;
                   unit: string; exceeded: boolean; }

/* WHICH WAY THE LIMIT RUNS, TAKEN FROM THE DATA. The twin publishes `margin`
 * as the headroom that is left, so it is (limit - value) for a ceiling such as
 * coolant temperature and (value - limit) for a floor such as oil pressure.
 * Comparing the two tells the console which kind it is holding without it
 * keeping a second opinion about any certified number. */
function isFloor(m: Margin): boolean {
  return Math.abs(m.margin - (m.value - m.limit))
       < Math.abs(m.margin - (m.limit - m.value));
}

/** Colour from the limit, never from a threshold invented here. */
function hueFor(m: Margin | undefined, value: number | null): string {
  if (value == null) return "var(--ink-mute)";
  if (!m || !m.limit) return "var(--state-normal)";
  if (m.exceeded) return "var(--alert-warn)";
  const used = isFloor(m) ? m.limit / Math.max(value, 1e-3) : value / m.limit;
  return used > 0.85 ? "var(--alert-caut)" : "var(--state-normal)";
}

function Live(props: { snap: any; compact: boolean }) {
  const rep = props.snap?.twin?.reported ?? {};
  const disp = props.snap?.display ?? {};
  const margins: Margin[] = Array.isArray(disp.margins) ? disp.margins : [];
  const min = props.compact ? 112 : 128;

  const by = (re: RegExp) => margins.find((m) => re.test(m.name));

  /* A channel that is not VALID reads as a dash with its reason on hover.
   * Holding the last good number would be a console lying about the present. */
  const rpm = rep.rpm;
  const rpmOk = rpm?.state === "VALID" && typeof rpm?.value === "number";
  const rpmV = rpmOk ? rpm.value : null;

  const chi: number | null = typeof disp.chi === "number" ? disp.chi : null;
  const band: string = typeof disp.band === "string" ? disp.band : "";
  /* THE BANDING IS THE TWIN'S, NOT THE CONSOLE'S. It publishes the word; the
   * colour follows the word rather than a second opinion about the number. */
  const chiHue = /POOR|CRITICAL|SEVERE|BAD/i.test(band) ? "var(--alert-warn)"
    : /FAIR|MODERATE|DEGRAD/i.test(band) ? "var(--alert-caut)"
    : band ? "var(--state-normal)" : "var(--ink-mute)";

  const rul: number | null = typeof disp.rul_hours === "number" ? disp.rul_hours : null;
  const rulScale = lifeScale(rul ?? 20);
  const rulHue = rul == null ? "var(--ink-mute)"
    : rul <= 20 ? "var(--alert-caut)" : "var(--state-normal)";

  return (
    <>
      <Instrument k="rpm" min={min} first sparse={props.compact} scale={SCALE.rpm}
                  fill={{ frac: (rpmV ?? 0) / SCALE.rpm.max,
                          hue: "var(--state-normal)" }}
                  title={rpmOk ? "engine speed, as reported by the twin"
                               : (rpm?.reason || "not reported")}>
        <span className="mo-num" style={VALUE}>
          {rpmV != null ? Math.round(rpmV).toLocaleString() : "—"}
        </span>
        <span style={UNIT}>rpm</span>
      </Instrument>

      <Channel k="coolant" min={min} sparse={props.compact} scale={SCALE.coolant}
               m={by(/coolant/i)} fallback={rep.coolant_temperature} unit="°C" />
      <Channel k="cyl head" min={min} sparse={props.compact} scale={SCALE.cht}
               m={by(/cyl/i)} fallback={rep.cht_max} unit="°C" />
      <Channel k="egt" min={min} sparse={props.compact} scale={SCALE.egt}
               m={by(/egt|exhaust/i)} fallback={rep.egt_max} unit="°C" />
      <Channel k="oil temp" min={min} sparse={props.compact} scale={SCALE.oilTemp}
               m={by(/oil temp/i)} fallback={rep.oil_temperature} unit="°C" />
      <Channel k="oil press" min={min} sparse={props.compact} scale={SCALE.oilPress}
               m={by(/oil press/i)} fallback={rep.oil_pressure} unit="psi" />

      {/* THE TWO SLOW QUANTITIES, and they belong to the live engine only. */}
      <Instrument k="health index" min={min} status sparse={props.compact}
                  fill={{ frac: chi ?? 0, hue: chiHue }}
                  title={"Composite health index of the engine running now"
                         + (band ? " — the twin calls this " + band : "")}>
        <span className="mo-num" style={{ ...VALUE, color: chi == null ? "var(--ink)" : chiHue }}>
          {chi != null ? chi.toFixed(2) : "—"}
        </span>
        {band && <span style={{ ...UNIT, letterSpacing: "0.06em" }}>{band}</span>}
      </Instrument>

      <Instrument k="remaining life" min={min} sparse={props.compact} scale={rulScale}
                  fill={{ frac: (rul ?? 0) / rulScale.max, hue: rulHue }}
                  title={"Remaining useful life of the live engine, from the twin's "
                         + "own estimator. Scale in hours."}>
        <span className="mo-num" style={VALUE}>
          {rul != null ? rul.toFixed(1) : "—"}
        </span>
        <span style={UNIT}>h</span>
      </Instrument>
    </>
  );
}

/** One published channel: the margin entry where the twin has one, the raw
 *  reported channel where it does not, and a dash where it is not valid. */
function Channel(props: {
  k: string; min: number; scale: Scale; unit: string; sparse: boolean;
  m: Margin | undefined; fallback: any;
}) {
  const m = props.m;
  const raw = props.fallback;
  const ok = m != null || (raw?.state === "VALID" && typeof raw?.value === "number");
  const value: number | null = m ? m.value : ok ? raw.value : null;
  const limit: number | null = m ? m.limit : null;
  const exceeded = !!m?.exceeded;
  const hue = hueFor(m, value);

  return (
    <Instrument k={props.k} min={props.min} sparse={props.sparse}
                scale={props.scale} limit={limit}
                fill={{ frac: (value ?? 0) / props.scale.max, hue }}
                title={value == null ? (raw?.reason || "not reported")
                  : props.k + " " + value + " " + props.unit
                    + (limit ? " against a limit of " + limit + " — "
                        + (exceeded ? "EXCEEDED"
                           : Math.abs(m!.margin).toFixed(1) + " " + props.unit + " in hand")
                      : "")}>
      <span className="mo-num"
            style={{ ...VALUE, color: exceeded ? "var(--alert-warn)" : "var(--ink)" }}>
        {value == null ? "—"
          : Math.abs(value) >= 100 ? Math.round(value).toLocaleString()
          : value.toFixed(1)}
      </span>
      <span style={UNIT}>{props.unit}</span>
    </Instrument>
  );
}

/* ------------------------------------------------------------------ *
 * FLOWN — the sortie, at the cursor
 * ------------------------------------------------------------------ */

interface FlownCell {
  k: string; unit?: string; dp?: number; secondary?: boolean;
  get: (s: FlightSample) => number;
  scale?: Scale;
  /** The certified limit this cell is measured against, by `limitsFrom()` key.
   *  Named rather than guessed, and absent where there is no single limit --
   *  engine speed has none here on purpose, because its limit depends on the
   *  phase and the server's event list is the authority on it. */
  limitKey?: string;
  /** For a quantity that is spent rather than limited: the fraction left. */
  ofStart?: boolean;
  warn?: (s: FlightSample, sim: FlightSim) => boolean;
  title?: string;
}

/* The unit each limit is quoted in, so MARGIN can say what it is counting. */
const LIMIT_UNIT: Record<string, string> = {
  cht_c: "°C", coolant_c: "°C", egt_c: "°C", oil_temp_c: "°C",
  oil_press_psi: "psi", vibration_rms: "m/s²",
};

const FLOWN: FlownCell[] = [
  { k: "altitude", unit: "ft", get: (s) => s.altitude_ft, scale: SCALE.altitude,
    title: "pressure altitude at this instant of the sortie" },
  { k: "clearance", unit: "ft", secondary: true, get: (s) => s.clearance_ft,
    scale: SCALE.clearance, warn: (s) => s.clearance_ft < 1000,
    title: "height above the ground beneath the aircraft" },
  { k: "power", unit: "kW", dp: 1, secondary: true, get: (s) => s.power_kw,
    scale: SCALE.power, title: "shaft power the model is making" },
  { k: "rpm", unit: "rpm", get: (s) => s.rpm, scale: SCALE.rpm, title: "engine speed" },
  { k: "cyl head", unit: "°C", get: (s) => s.cht_c, scale: SCALE.cht,
    limitKey: "cht_c", warn: (s) => s.cht_c >= 120, title: "hottest cylinder head" },
  { k: "egt", unit: "°C", get: (s) => s.egt_c, scale: SCALE.egt,
    limitKey: "egt_c", warn: (s) => s.egt_c >= 900, title: "hottest exhaust gas" },
  { k: "oil temp", unit: "°C", get: (s) => s.oil_temp_c, scale: SCALE.oilTemp,
    limitKey: "oil_temp_c", warn: (s) => s.oil_temp_c >= 125, title: "oil temperature" },
  { k: "fuel left", unit: "L", dp: 1, get: (s) => s.fuel_remaining_l, ofStart: true,
    warn: (s, sim) => s.fuel_remaining_l < sim.reserve_l,
    title: "usable fuel remaining; caution below the planned reserve" },
];

function Flown(props: { pb: Playback; sim: FlightSim; engine: any; compact: boolean }) {
  const cells = useMemo(
    () => FLOWN.filter((c) => !(props.compact && c.secondary)), [props.compact]);
  const limits = useMemo(() => limitsFrom(props.engine), [props.engine]);
  const min = props.compact ? 112 : 128;

  /* What was on board when the engine was started: the fuel instrument is
   * calibrated to the load this sortie actually took off with. */
  const start = props.pb.samples[0]?.fuel_remaining_l ?? 0;
  const fuelScale: Scale = useMemo(() => {
    const m = Math.max(10, Math.ceil(start / 10) * 10);
    return { max: m, ticks: [0, m / 2, m] };
  }, [start]);

  const val = useRef<(HTMLSpanElement | null)[]>([]);
  const bar = useRef<(HTMLDivElement | null)[]>([]);
  const marginVal = useRef<HTMLSpanElement>(null);
  const marginWho = useRef<HTMLSpanElement>(null);
  const marginBar = useRef<HTMLDivElement | null>(null);

  /* ONE DOM WRITE PER CELL PER FRAME, and no React render: the clock owns this
   * row while a sortie is playing. Same contract as TelemetryStrip. */
  useEffect(() => props.pb.subscribe((t) => {
    const s = props.pb.samples[props.pb.indexAt(t)];
    if (!s) return;
    const load = props.pb.samples[0]?.fuel_remaining_l ?? 0;
    cells.forEach((c, i) => {
      const v = c.get(s);
      const el = val.current[i];
      if (el) {
        el.textContent = c.dp != null ? v.toFixed(c.dp) : Math.round(v).toLocaleString();
        el.style.color = c.warn?.(s, props.sim) ? "var(--alert-caut)" : "var(--ink)";
      }
      const b = bar.current[i];
      if (!b) return;
      const span = c.ofStart ? Math.max(10, Math.ceil(load / 10) * 10) : c.scale?.max ?? 0;
      b.style.width = span > 0
        ? (Math.max(0, Math.min(1, v / span)) * 100).toFixed(1) + "%" : "0%";
      if (c.ofStart) {
        b.style.background = c.warn?.(s, props.sim) ? "var(--alert-caut)"
                                                    : "var(--state-normal)";
        return;
      }
      const lim = c.limitKey ? limits.find((l) => l.key === c.limitKey) : null;
      if (!lim) {
        b.style.background = c.warn?.(s, props.sim) ? "var(--alert-caut)"
                                                    : "var(--state-normal)";
        return;
      }
      const used = lim.upper ? v / lim.limit : lim.limit / Math.max(v, 1e-3);
      b.style.background = used > 1 ? "var(--alert-warn)"
        : used > 0.85 ? "var(--alert-caut)" : "var(--state-normal)";
    });

    /* THE SLOW NUMBER THE SORTIE DOES NOT HAVE. Not health, not RUL -- how much
     * of the nearest certified limit is left, and which one it is. */
    let worst: { label: string; frac: number; left: number; unit: string } | null = null;
    for (const l of limits) {
      const v = l.get(s);
      const frac = l.upper ? v / l.limit : l.limit / Math.max(v, 1e-3);
      const left = l.upper ? l.limit - v : v - l.limit;
      if (!worst || frac > worst.frac) {
        worst = { label: l.label, frac, left, unit: LIMIT_UNIT[l.key] ?? "" };
      }
    }
    if (worst) {
      if (marginVal.current) {
        marginVal.current.textContent = worst.left.toFixed(worst.left < 10 ? 1 : 0);
        marginVal.current.style.color = worst.frac >= 1 ? "var(--alert-warn)"
          : worst.frac > 0.85 ? "var(--alert-caut)" : "var(--ink)";
      }
      if (marginWho.current) marginWho.current.textContent = worst.unit + " · " + worst.label;
      if (marginBar.current) {
        const f = Math.max(0, Math.min(1, worst.frac));
        marginBar.current.style.width = (f * 100).toFixed(1) + "%";
        marginBar.current.style.background = f >= 1 ? "var(--alert-warn)"
          : f > 0.85 ? "var(--alert-caut)" : "var(--state-normal)";
      }
    }
  }), [props.pb, props.sim, cells, limits]);

  return (
    <>
      {cells.map((c, i) => (
        <Instrument key={c.k} k={c.k} min={min} title={c.title} first={i === 0}
                    sparse={props.compact}
                    scale={c.ofStart ? fuelScale : c.scale}
                    limit={c.limitKey
                      ? limits.find((l) => l.key === c.limitKey)?.limit ?? null : null}
                    fillRef={(el) => { bar.current[i] = el; }}>
          <span className="mo-num" ref={(el) => { val.current[i] = el; }}
                style={VALUE}>—</span>
          {c.unit && <span style={UNIT}>{c.unit}</span>}
        </Instrument>
      ))}

      <Instrument k="margin" min={min} status sparse={props.compact} fillRef={(el) => { marginBar.current = el; }}
                  title={"How much of the nearest certified limit is still in hand, "
                         + "against the same configs/thresholds.yaml table the server "
                         + "judged this sortie with. The sortie carries no health or "
                         + "RUL of its own."}>
        <span className="mo-num" ref={marginVal} style={VALUE}>—</span>
        <span ref={marginWho} style={{ ...UNIT, minWidth: 0, overflow: "hidden",
                                       textOverflow: "ellipsis" }} />
      </Instrument>
    </>
  );
}
