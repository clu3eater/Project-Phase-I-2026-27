/* THE BEARING / GEAR DEFECT SIGNATURE, DRAWN AS WHAT IS ACTUALLY SERVED.
 *
 * WHY THIS IS NOT AN OSCILLOSCOPE TRACE, AND MUST NEVER BECOME ONE.
 *
 * The engine really does synthesise a 10 kHz vibration waveform, and it is
 * discarded in the same statement that consumes it. It reaches no API. The
 * fastest vibration figure a client of this console can obtain is 2 Hz, which
 * is five thousand times too slow to draw a single shaft revolution. Any
 * waveform on this card would therefore be drawn from numbers this console
 * does not have -- i.e. invented -- so there is no trace here, and a later
 * change that adds one is wrong no matter how good it looks.
 *
 * WHAT IS SERVED is snapshot.twin.reported.vibration.spectral_peaks: one
 * amplitude per NAMED DEFECT ORDER, out of envelope order analysis (angular
 * resampling, spectral-kurtosis band selection, Hilbert envelope).
 *
 * THE AMPLITUDE IS DIMENSIONLESS. It is a multiple of the envelope-spectrum
 * noise floor -- "how far this order stands out of its own background". It is
 * not g, not m/s2, not Hz and not dB, and it is labelled as a multiple of the
 * floor everywhere on this card for exactly that reason. Relabelling a ratio
 * as a physical unit would be a lie that reads as precision.
 *
 * THERE IS NO FREQUENCY AXIS, BECAUSE THERE IS NO FREQUENCY IN THE PAYLOAD.
 * A real order spectrum would place BPFO at its own order (about 3.59x shaft
 * for this bearing) -- but those order positions are not served and differ per
 * engine, so an order axis here would be fabricated geometry. THE NAMES ARE
 * THE AXIS: one labelled bar per named peak, worst first, and nothing claims a
 * position it was not given.
 *
 * AND THE AGE IS PART OF THE READING. This analysis recomputes only once per
 * 60 simulated seconds, only above 300 rpm, and it is STICKY: after the engine
 * stops it keeps showing its last result, indefinitely. A clean spectrum from
 * four minutes and one shutdown ago is not a clean engine now, so past the
 * refresh interval the bars are hatched and the figure is captioned NOT
 * CURRENT -- two channels, neither of them colour alone.
 */
import type { CSSProperties } from "react";

/* Local, and deliberately not lib/bands.bandOf().
 *
 * bandOf() exists so a figure can never disagree with the alert engine, which
 * trips STRICTLY (edge_rules.py: `value > limit`), so a reading exactly ON a
 * limit raises nothing. The order analyser is a different judge with a
 * different rule: it declares a defect AT or over its threshold, inclusively.
 * Routing this through bandOf() would draw 4.00x as clear while the analyser
 * called it a defect. There is also no engine Limit record for a dimensionless
 * envelope ratio to hand it. So the one comparison this card needs is written
 * out below, inclusive, where it can be read. */
const DEFECT_AT = 4.0;

/** The analysis window, from the engine side: it refreshes once per 60 s of
 *  simulated time, and only while the engine is turning above 300 rpm. Past
 *  this, what is on screen is the last result and not the present state. */
const REFRESH_S = 60;

/** What each order name MEANS. An order code is not self-explanatory at 3 a.m.,
 *  and "BSF 5.41" is only a reading if you know what BSF is. */
const MEANING: Record<string, string> = {
  BPFO: "ball pass frequency, outer race",
  BPFI: "ball pass frequency, inner race",
  BSF: "ball spin frequency",
  FTF: "fundamental train frequency (cage)",
  GMF: "gear mesh frequency",
  FIRING: "firing order",
};

const NUM: CSSProperties = { fontFamily: "var(--font-num)" };
const LABEL: CSSProperties = { fontSize: "var(--size-label)", color: "var(--ink-dim)" };

/* label | track | amplitude | word. Fixed columns, so every bar starts and ends
   on the same two x positions and the threshold ticks line up into one
   continuous threshold line down the card. */
const COLS = "88px minmax(0, 1fr) 84px 76px";

export interface OrderSpectrumProps {
  /** defect-order name -> amplitude, as a multiple of the envelope noise
   *  floor. Dimensionless. null / undefined / empty = the analysis has not run. */
  peaks?: Record<string, number> | null;
  /** the analyser's own defect threshold, inclusive. Defaults to 4.0x floor. */
  defectAt?: number;
  /** seconds since this analysis was computed, when the API reports it. */
  ageS?: number | null;
}

const fin = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

/** Seconds, said the way the rest of the console says them. */
function clock(s: number): string {
  if (s >= 3600) return `${(s / 3600).toFixed(1)} h`;
  if (s >= 60) return `${Math.round(s / 60)} min`;
  return `${Math.round(s)} s`;
}

export function OrderSpectrum({ peaks, defectAt, ageS }: OrderSpectrumProps) {
  const given = fin(defectAt);
  const threshold = given != null && given > 0 ? given : DEFECT_AT;

  /* Read as served. Nothing is filled in, averaged or carried over: an entry
     that is not a finite number is not a peak, and is counted out loud at the
     foot of the card rather than quietly drawn as a zero-length bar. */
  const entries = Object.entries(peaks ?? {});
  const bars = entries
    .map(([name, v]) => ({ name, amp: fin(v) }))
    .filter((b): b is { name: string; amp: number } => b.amp != null)
    .sort((a, b) => (b.amp - a.amp) || a.name.localeCompare(b.name));
  const unreported = entries.length - bars.length;

  /* THE HONEST GAP: one line, taking one line's room. An empty chart frame
     would reserve the height of evidence and then deliver none, which reads as
     a broken instrument rather than as an analysis that has not run yet. */
  if (bars.length === 0) {
    return (
      <div style={{ borderLeft: "2px solid var(--line)", paddingLeft: "var(--space-3)",
                    color: "var(--ink-mute)", fontSize: 16, lineHeight: 1.4 }}>
        No order analysis yet: it needs the engine turning above 300 rpm.
      </div>
    );
  }

  const age = fin(ageS);
  const stale = age != null && age > REFRESH_S;

  /* Scale. The top of the track is set so the threshold is always on the card
     with room past it, and the longest bar can never run off the end. */
  const top = Math.max(bars[0].amp * 1.12, threshold * 1.3);
  const at = (v: number) => Math.max(0, Math.min(100, (v / top) * 100));
  const tPct = at(threshold);
  const defects = bars.filter((b) => b.amp >= threshold);

  /* The threshold caption sits under its own tick, pulled back off the ends so
     it cannot hang outside the card. */
  const tShift = tPct > 74 ? "translateX(-100%)" : tPct < 16 ? "none" : "translateX(-50%)";

  return (
    <div style={{ minWidth: 0 }}>
      {/* WHAT IS MEASURED, IN WHAT, AND HOW OLD IT IS -- before any geometry. */}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline",
                    justifyContent: "space-between", gap: "var(--space-2)" }}>
        <span style={LABEL}>ORDER PEAKS · MULTIPLE OF ENVELOPE NOISE FLOOR</span>
        <span style={{ display: "flex", alignItems: "baseline", gap: "var(--space-2)" }}>
          {/* Only when the API actually reports an age. It does not today, and
              a line saying so on every render is noise about the payload, not
              information about the engine. */}
          {age != null && (
            <span style={{ ...NUM, fontSize: 16,
                           color: stale ? "var(--ink-dim)" : "var(--ink)" }}>
              analysed {clock(age)} ago
            </span>
          )}
          {stale && (
            <span style={{ fontSize: 16, color: "var(--ink)",
                           border: "1px solid var(--line)",
                           borderRadius: "var(--radius)", padding: "0 var(--space-1)",
                           background: "var(--bg-raised)", whiteSpace: "nowrap" }}>
              NOT CURRENT
            </span>
          )}
        </span>
      </div>

      {/* THE HEADLINE THE BARS SUPPORT, IN WORDS. Colour repeats it; it does not
          carry it. A sticky result is never painted healthy green -- an
          out-of-date all-clear is not an all-clear. */}
      <div style={{ marginTop: "var(--space-2)", fontSize: 16, lineHeight: 1.35,
                    color: defects.length > 0 ? "var(--alert-caut)"
                         : stale ? "var(--ink-dim)" : "var(--state-normal)" }}>
        {defects.length > 0
          ? `DEFECT SIGNATURE — ${defects.length} of ${bars.length} orders at or over `
            + `${threshold.toFixed(2)} × floor: ${defects.map((d) => d.name).join(", ")}`
          : `NO DEFECT ORDER — all ${bars.length} below ${threshold.toFixed(2)} × floor`}
        {stale && " (last analysis, not the present state)"}
      </div>

      {/* ONE BAR PER NAMED PEAK, WORST FIRST, so the offender is at the top and
          is found without reading every label. */}
      <div style={{ marginTop: "var(--space-3)", display: "grid",
                    rowGap: "var(--space-2)" }}>
        {bars.map((b, i) => {
          const meaning = MEANING[b.name.toUpperCase()] ?? null;
          const isDefect = b.amp >= threshold;      // inclusive: the analyser's rule
          const pid = `os-stale-hatch-${i}`;
          /* Guarded, not clamped upward: a zero or absent-length bar stays a
             zero-length bar. `calc(0% - 2px)` is a negative width, which is
             invalid CSS and lets the fill fall back to auto -- i.e. a reading
             of nothing drawn as something. The number beside it is always
             printed, so no bar is given a minimum length it has not earned. */
          const pct = at(b.amp);
          return (
            <div
              key={b.name}
              title={meaning
                ? `${b.name} — ${meaning}. ${b.amp.toFixed(2)} × envelope noise floor`
                  + `${isDefect
                      ? `, at or over the ${threshold.toFixed(2)} × defect threshold` : ""}`
                : `${b.name} — order name not in this console's table; `
                  + `${b.amp.toFixed(2)} × envelope noise floor as served`}
              style={{ display: "grid", gridTemplateColumns: COLS,
                       alignItems: "center", columnGap: "var(--space-3)" }}
            >
              <span style={{ ...NUM, fontSize: 16, color: "var(--ink)",
                             overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap" }}>
                {b.name}
              </span>

              <div style={{ position: "relative", height: 18,
                            background: "var(--bg-raised)",
                            border: "1px solid var(--line)",
                            borderRadius: "var(--radius)" }}>
                <div
                  className="bar-fill"
                  style={{ position: "absolute", top: 1, bottom: 1, left: 1,
                           width: pct <= 0 ? 0 : `calc(${pct}% - 2px)`,
                           overflow: "hidden",
                           /* --data for the GEOMETRY of a reading; amber only
                              where the analyser itself declares a defect. */
                           background: isDefect ? "var(--alert-caut)" : "var(--data)" }}
                >
                  {/* Hatch: the non-colour channel for "these bars are not
                      current". Drawn as an SVG pattern of lines, never a
                      gradient. */}
                  {stale && (
                    <svg aria-hidden="true"
                         style={{ position: "absolute", inset: 0, width: "100%",
                                  height: "100%", color: "var(--bg-panel)",
                                  pointerEvents: "none" }}>
                      <pattern id={pid} width="6" height="6"
                               patternUnits="userSpaceOnUse"
                               patternTransform="rotate(-45)">
                        <line x1="0" y1="0" x2="0" y2="6"
                              stroke="currentColor" strokeWidth="1.6" />
                      </pattern>
                      <rect width="100%" height="100%" fill={`url(#${pid})`} />
                    </svg>
                  )}
                </div>
                {/* The defect threshold, on every track at the same x, so the
                    ticks read as one line across the card. */}
                <div aria-hidden="true"
                     style={{ position: "absolute", top: -3, bottom: -3, width: 2,
                              left: `${tPct}%`, background: "var(--alert-caut)" }} />
              </div>

              <span style={{ ...NUM, fontSize: 18, textAlign: "right",
                             color: "var(--ink)", whiteSpace: "nowrap" }}>
                {b.amp.toFixed(2)}
                <span style={{ fontSize: 16, color: "var(--ink-dim)" }}> ×</span>
              </span>

              {/* THE WORD. Colour is never the only carrier of this state. */}
              <span style={{ fontSize: 16, whiteSpace: "nowrap",
                             color: isDefect ? "var(--alert-caut)" : "var(--ink-mute)" }}>
                {isDefect ? "DEFECT" : "—"}
              </span>
            </div>
          );
        })}
      </div>

      {/* THE THRESHOLD, NAMED, under the tick it belongs to. */}
      <div style={{ display: "grid", gridTemplateColumns: COLS,
                    columnGap: "var(--space-3)", marginTop: "var(--space-1)" }}>
        <span />
        <div style={{ position: "relative", height: 22 }}>
          <span style={{ ...LABEL, ...NUM, position: "absolute", left: 0, top: 0 }}>0</span>
          <span style={{ position: "absolute", left: `${tPct}%`, top: 0,
                         transform: tShift, whiteSpace: "nowrap", fontSize: 16,
                         color: "var(--alert-caut)" }}>
            defect ≥ {threshold.toFixed(2)} ×
          </span>
        </div>
        <span />
        <span />
      </div>

      {/* A CARD IS NOT THE PLACE FOR THE METHOD.
       *
       * This carried three paragraphs explaining angular resampling, the
       * Hilbert envelope, why there is no frequency axis and how often the
       * analysis reruns. All true, and all of it drove the card to 1108 px and
       * buried the six bars that are the actual figure. The method lives in
       * the file header and in the title attribute on the heading, where it is
       * one hover away; the card keeps only what changes with the data. */}
      {unreported > 0 && (
        <div style={{ marginTop: "var(--space-2)", fontSize: 16,
                      color: "var(--ink-mute)" }}>
          {unreported} further order{unreported === 1 ? "" : "s"} reported without
          an amplitude — not drawn.
        </div>
      )}
    </div>
  );
}
