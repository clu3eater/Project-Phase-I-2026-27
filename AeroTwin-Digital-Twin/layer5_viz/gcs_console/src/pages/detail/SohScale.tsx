/* BATTERY STATE OF HEALTH, ON A SCALE THAT KNOWS WHICH WAY IS GOOD.
 *
 * THE DEFECT THIS REPLACES.
 * The battery card reused the generic "value against its limits" bar. That
 * component is built for higher-is-worse quantities -- head temperature, oil
 * temperature, vibration -- where the interesting event is a reading climbing
 * past a maximum. To get a bar out of it, the card passed critical_max: 100,
 * which is the assertion "a state of health above 100 % is a WARNING". So a
 * perfectly healthy pack rendered in warning red, captioned OVER LIMIT, while
 * the same card printed the same number in plain ink two lines above it. Two
 * contradictory verdicts on one measurement, on one card.
 *
 * The strictness fix in lib/bands.ts stopped 100 % itself tripping, but the
 * geometry was still upside down: on a higher-is-worse bar a longer bar is a
 * worse reading, and for state of health a longer bar is a better pack.
 *
 * So this figure is direction-aware and says so out loud. Good is at the top,
 * bad is at the bottom, the replacement point is marked and named, and the
 * scale is anchored well below that point rather than at zero -- a pack at 0 %
 * state of health is not a pack, and the whole decision lives in the top half.
 * The anchoring is written on the figure, because a scale that does not start
 * at zero and does not admit it is a trick.
 *
 * WHAT THIS FIGURE CANNOT DO, STATED RATHER THAN HIDDEN.
 * Pack resistance -- what state of health is estimated from -- is only visible
 * while the battery is actually supplying current. At cruise the alternator
 * carries the bus, and a good pack and a dying one read the same. So the
 * number on screen is usually the LAST real measurement, and this component
 * carries its age rather than letting a stale figure look authoritative.
 */
import { useId, type CSSProperties } from "react";

const LABEL: CSSProperties = { fontSize: "var(--size-label)", color: "var(--ink-dim)" };
const NUM: CSSProperties = { fontFamily: "var(--font-num)" };

/* After this long a pack measurement no longer describes the pack: it
 * describes the pack as it was on some earlier sortie. Shown, and marked. */
const DATED_H = 50;

/* How far below the replacement point the drawn scale starts. Derived from
 * replaceAt rather than hard-wired at 50 %, so a fleet that replaces at some
 * other figure still gets a floor below its own decision point. */
const HEADROOM = 0.1;

export interface SohScaleProps {
  /** State of health as a fraction, 0..1. Null when never measured. */
  soh: number | null;
  /** The replacement point, 0..1. At or below this, the pack comes out. */
  replaceAt?: number;
  /** Where watching starts, 0..1. Above this the pack is healthy. */
  cautionAt?: number;
  /** True only while the pack is discharging and can actually be measured. */
  observableNow?: boolean;
  /** Age of the measurement in hours, if known. */
  hoursSinceMeasured?: number | null;
  /** Why it is not observable, when it is not. */
  reason?: string | null;
}

interface Verdict { word: string; ink: string; }

/* THE COMPARISONS, AND WHY THEY SIT THIS WAY ROUND.
 *
 * Worst true statement first, as in lib/bands.ts, so a badly ordered pair of
 * thresholds cannot produce a reassuring answer. "Healthy" is strictly above
 * cautionAt, and "replace" is AT or below replaceAt: a pack that has reached
 * its replacement point has reached it. This is a maintenance limit, not an
 * alert-engine limit, so there is no strict-comparison rule to match here.
 */
function verdictOf(soh: number, replaceAt: number, cautionAt: number): Verdict {
  if (soh <= replaceAt) return { word: "REPLACE", ink: "var(--alert-warn)" };
  if (soh <= cautionAt) return { word: "MONITOR", ink: "var(--alert-caut)" };
  return { word: "HEALTHY", ink: "var(--state-normal)" };
}

/** A fraction as a percentage, without inventing precision it does not have. */
function pctText(x: number): string {
  const p = x * 100;
  return Number.isInteger(p) ? `${p}` : p.toFixed(1);
}

export function SohScale({
  soh,
  replaceAt = 0.6,
  cautionAt = 0.8,
  observableNow,
  hoursSinceMeasured = null,
  reason = null,
}: SohScaleProps) {
  /* Called before any early return: the hatch below needs a document-unique
   * name and a hook cannot run conditionally. Non-word characters are stripped
   * because the name is dereferenced as a fragment. */
  const hatchId = `soh-dated-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;

  /* NO MEASUREMENT IS ONE LINE, NOT AN EMPTY CHART FRAME. An empty track with
   * ticks on it reads as "measured, and zero", which is the opposite of true,
   * and it takes twelve lines of room to say nothing. */
  if (soh == null || !Number.isFinite(soh)) {
    return (
      <div style={{ borderLeft: "2px solid var(--line)", paddingLeft: "var(--space-3)",
                    color: "var(--ink-mute)", fontSize: 16, lineHeight: 1.4 }}>
        State of health: never measured{reason ? ` — ${reason}` : "."}
      </div>
    );
  }

  const floor = Math.min(0.5, Math.max(0, replaceAt - HEADROOM));
  const span = 1 - floor;
  /** Position on the drawn track, as a percentage of its width. */
  const pos = (x: number) =>
    span <= 0 ? 0 : Math.max(0, Math.min(100, ((x - floor) / span) * 100));

  const v = verdictOf(soh, replaceAt, cautionAt);
  const pct = pos(soh);
  const offLow = soh < floor;
  const offHigh = soh > 1;
  const age = hoursSinceMeasured != null && Number.isFinite(hoursSinceMeasured)
    ? hoursSinceMeasured : null;
  const dated = age != null && age > DATED_H;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)",
                  minWidth: 0 }}>

      {/* ---- the figure and its word. Colour is never the only carrier. ---- */}
      <div style={{ display: "flex", alignItems: "baseline", flexWrap: "wrap",
                    gap: "var(--space-1) var(--space-3)" }}>
        <span style={LABEL}>State of health</span>
        {/* Value and unit sit a hairline apart, not a group apart. */}
        <span style={{ display: "flex", alignItems: "baseline",
                       gap: "var(--space-1)" }}>
          <span style={{ ...NUM, fontSize: 30, fontWeight: 700, lineHeight: 1,
                         color: dated ? "var(--ink-dim)" : "var(--ink)" }}>
            {pctText(soh)}
          </span>
          <span style={LABEL}>%</span>
        </span>
        <span style={{ fontSize: 21, fontWeight: 700, letterSpacing: "0.06em",
                       color: v.ink }}>
          {v.word}
        </span>
        {dated && (
          <span style={{ fontSize: 16, fontWeight: 700, letterSpacing: "0.06em",
                         color: "var(--ink-dim)" }}>
            DATED
          </span>
        )}
      </div>

      {/* ---- THE SCALE. The fill grows RIGHT as the pack gets BETTER. ----
          Anchored above zero so the region that decides anything gets the
          width; the anchoring is written underneath, not assumed. */}
      <div style={{ position: "relative", height: 18, background: "var(--bg-raised)",
                    border: "1px solid var(--line)", borderRadius: "var(--radius)",
                    marginTop: "var(--space-1)" }}>

        {/* The measurement. Hatched when dated, because a solid block of
            colour is an assertion about the pack RIGHT NOW and a figure from
            three sorties ago has not earned one. The right edge stays crisp
            either way, so the value can still be read off the scale. */}
        <div className="bar-fill"
             style={{ position: "absolute", top: 1, bottom: 1, left: 1,
                      width: `calc(${pct}% - 2px)`, overflow: "hidden",
                      background: dated ? "transparent" : v.ink,
                      borderRight: `2px solid ${v.ink}` }}>
          {dated && (
            <svg width="100%" height="100%" preserveAspectRatio="none"
                 style={{ display: "block" }}>
              <defs>
                <pattern id={hatchId} patternUnits="userSpaceOnUse"
                         width="6" height="6" patternTransform="rotate(45)">
                  <line x1="0" y1="0" x2="0" y2="6" stroke={v.ink} strokeWidth="2" />
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill={`url(#${hatchId})`} />
            </svg>
          )}
        </div>

        {/* Where watching starts: a hairline, inside the track. */}
        <div style={{ position: "absolute", top: 0, bottom: 0,
                      left: `${pos(cautionAt)}%`, width: 1,
                      background: "var(--ink-dim)" }} />

        {/* THE REPLACEMENT POINT: the one mark on this scale that decides
            something, so it is the one mark drawn past both track edges. */}
        <div style={{ position: "absolute", top: -4, bottom: -4,
                      left: `${pos(replaceAt)}%`, width: 2,
                      background: "var(--ink)" }} />
      </div>

      {/* ---- what the marks are, sitting under the marks ---- */}
      <div style={{ position: "relative", height: 22 }}>
        <span style={{ ...NUM, position: "absolute", left: `${pos(replaceAt)}%`,
                       transform: "translateX(-50%)", whiteSpace: "nowrap",
                       fontSize: 16, color: "var(--ink)" }}>
          {pctText(replaceAt)} % replace
        </span>
        <span style={{ ...NUM, position: "absolute", left: `${pos(cautionAt)}%`,
                       transform: "translateX(-50%)", whiteSpace: "nowrap",
                       fontSize: 16, color: "var(--ink-dim)" }}>
          {pctText(cautionAt)} % monitor
        </span>
      </div>

      {/* ---- the scale states its own anchoring, direction and thresholds ----
          The two thresholds are named here as well as marked on the track: if
          they are set close together their tick labels crowd each other, and a
          figure whose thresholds can become unreadable is not a figure. */}
      <div style={{ ...LABEL, lineHeight: 1.4 }}>
        Scale <span style={NUM}>{pctText(floor)}–100 %</span>, not <span style={NUM}>0–100 %</span>:
        a pack at 0 % is not a pack. Higher is better, so the pack fails towards
        the LEFT. Replace at <span style={NUM}>{pctText(replaceAt)} %</span>,
        monitor at or below <span style={NUM}>{pctText(cautionAt)} %</span>.
      </div>

      {/* ---- how old the figure is ---- */}
      {age != null ? (
        <div style={{ fontSize: 16, lineHeight: 1.4, color: "var(--ink-dim)" }}>
          Measured <span style={NUM}>{age.toFixed(1)}</span> h ago
          {dated && (
            <>
              {" — DATED, older than "}
              <span style={NUM}>{DATED_H}</span>
              {" h. It describes the pack as it was then, not as it is now."}
            </>
          )}
        </div>
      ) : (
        <div style={{ ...LABEL, lineHeight: 1.4 }}>
          Age of this measurement not reported.
        </div>
      )}

      {/* ---- OFF THE DRAWN SCALE. The bar is clamped; the figure is not. ---- */}
      {offLow && (
        <div style={{ fontSize: 16, lineHeight: 1.4, color: "var(--alert-warn)" }}>
          OFF SCALE LOW — <span style={NUM}>{pctText(soh)} %</span> is below the
          drawn floor of <span style={NUM}>{pctText(floor)} %</span>. The bar
          stops at the left end; the figure does not.
        </div>
      )}
      {offHigh && (
        <div style={{ fontSize: 16, lineHeight: 1.4, color: "var(--ink-dim)" }}>
          OFF SCALE HIGH — <span style={NUM}>{pctText(soh)} %</span> is above
          100 %. The bar stops at the right end; the figure does not.
        </div>
      )}

      {/* ---- THE LIMITATION, STATED. ---- */}
      {observableNow === false && (
        <div style={{ borderLeft: "2px solid var(--line)", paddingLeft: "var(--space-3)",
                      fontSize: 16, lineHeight: 1.4, color: "var(--ink-dim)" }}>
          NOT MEASURABLE NOW{reason ? ` — ${reason}` : "."}
          <div style={{ marginTop: "var(--space-1)" }}>
            The pack can only be measured while it is discharging. At cruise the
            alternator carries the bus, and a good pack and a dying one read the
            same. The figure above is the last real measurement, not a live one.
          </div>
        </div>
      )}
      {observableNow === true && (
        <div style={{ ...LABEL, lineHeight: 1.4 }}>
          Measurable now: the pack is discharging, so this figure is live.
        </div>
      )}
    </div>
  );
}
