/* The four cylinders, as something you can COMPARE.
 *
 * Per-cylinder temperatures exist for one reason: to find the odd cylinder.
 * The card that was here listed four head temperatures in one column and four
 * exhaust temperatures in another, most of a panel apart, and left the
 * comparison entirely to the operator -- while the one comparative number it
 * did compute, the spread, sat alone in the header far from the values it
 * describes.
 *
 * LAID OUT LIKE THE ENGINE. The 915 iS is a boxer: 1 and 3 on one bank, 2 and
 * 4 on the other. That is also how the ignition coils are grouped
 * (COIL_1_3 / COIL_2_4) and how a misfire progresses from one cylinder to its
 * partner above magnitude 0.5. Two columns of two put this card in the same
 * arrangement as the engine beside it -- and as the cylinder numbers now drawn
 * on the 3D model -- so "cylinder 3 is hot" can be read here and pointed at
 * there without anyone having to translate between them.
 *
 * Head and exhaust for one cylinder finally sit together, and each tile
 * carries its own departure from the four-cylinder mean, which is the number
 * that actually answers "is one of them odd?".
 */
import type { CSSProperties } from "react";

/** The engine's own limit record for one parameter, as /api/engine publishes
 *  it: normal_min, normal_max, alert_max, critical_max. Nothing here invents a
 *  threshold -- every line on the bar below is a number the engine defines. */
export interface Limit {
  normal_min?: number | null;
  normal_max?: number | null;
  alert_max?: number | null;
  critical_max?: number | null;
}

export interface CylProps {
  /** head temperature for cylinder 1-4, null when not reported */
  cht: (i: number) => number | null;
  /** exhaust temperature for cylinder 1-4 */
  egt: (i: number) => number | null;
  chtLimit?: Limit | null;
  egtLimit?: Limit | null;
}

const NUM: CSSProperties = { fontFamily: "var(--font-num)" };
const LABEL: CSSProperties = { fontSize: "var(--size-label)", color: "var(--ink-dim)" };

/* WHERE THE NUMBER SITS AGAINST ITS LIMIT.
 *
 * A head temperature of 14.5 says nothing on its own unless you happen to know
 * that this engine runs 80-120 and is certified to 135. Four bare numbers left
 * the operator to supply that from memory, which is exactly the kind of thing
 * that is not supplied from memory at 3 a.m.
 *
 * The track runs 0 to the CERTIFIED LIMIT, so the right-hand end is the number
 * the engine may not exceed. Two faint ticks mark the normal band and an amber
 * tick marks the alert threshold, all read from the engine definition rather
 * than chosen here. A cold engine therefore shows a short bar well short of
 * the band -- which is the truth, not a fault -- and the fill walks up into the
 * band as it warms.
 *
 * The fill is coloured by which threshold the value has actually crossed, so
 * it never disagrees with the alert engine: below the band it is muted,
 * in-band it is ink, at alert_max it is caution amber, at critical_max warning
 * red. Colour is never the only channel -- the number beside it carries HIGH.
 */
function LimitBar({ value, lim }: { value: number | null; lim?: Limit | null }) {
  const top = lim?.critical_max ?? lim?.alert_max ?? null;
  if (top == null || top <= 0) return null;
  const at = (v: number) => Math.max(0, Math.min(100, (v / top) * 100));
  const tick = (v: number | null | undefined, colour: string, w = 1) =>
    v == null ? null : (
      <div style={{ position: "absolute", top: -2, bottom: -2, width: w,
                    left: `${at(v)}%`, background: colour }} />
    );
  const fill =
    value == null ? "transparent"
    : lim?.critical_max != null && value >= lim.critical_max ? "var(--alert-warn)"
    : lim?.alert_max != null && value >= lim.alert_max ? "var(--alert-caut)"
    : lim?.normal_min != null && value < lim.normal_min ? "var(--ink-mute)"
    : "var(--ink)";
  return (
    <div style={{ position: "relative", height: 8, marginTop: 6,
                  background: "var(--bg-raised)",
                  border: "1px solid var(--line)", borderRadius: 2 }}>
      {value != null && (
        <div className="bar-fill"
             style={{ position: "absolute", top: 1, bottom: 1, left: 1,
                      width: `calc(${at(value)}% - 2px)`, background: fill }} />
      )}
      {/* the ticks sit above the fill so the band stays readable under it */}
      {tick(lim?.normal_min, "var(--ink-dim)")}
      {tick(lim?.normal_max, "var(--ink-dim)")}
      {tick(lim?.alert_max, "var(--alert-caut)")}
    </div>
  );
}

/* The banks, in the order they sit on the engine. */
const BANKS = [1, 3, 2, 4];

/** Mean of the reported cylinders, or null when none are. */
function mean(read: (i: number) => number | null): number | null {
  const v = [1, 2, 3, 4].map(read).filter((x): x is number => x != null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

const DASH = "———";

export function Cylinders(p: CylProps) {
  const cm = mean(p.cht);
  return (
    <div style={{ display: "grid", height: "100%", minHeight: 0,
                  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                  gridTemplateRows: "repeat(2, minmax(0, 1fr))",
                  gap: "var(--space-2)" }}>
      {BANKS.map((i) => {
        const c = p.cht(i), e = p.egt(i);
        const ca = p.chtLimit?.alert_max, ea = p.egtLimit?.alert_max;
        const cHi = c != null && ca != null && c > ca;
        const eHi = e != null && ea != null && e > ea;
        const dev = c != null && cm != null ? c - cm : null;
        return (
          <div key={i}
               style={{ border: "1px solid var(--line)",
                        borderRadius: "var(--radius)",
                        padding: "var(--space-2) var(--space-3)",
                        display: "flex", flexDirection: "column",
                        justifyContent: "center", gap: 2, minWidth: 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "baseline", gap: "var(--space-2)" }}>
              <span style={LABEL}>CYL {i}</span>
              {/* Departure from the four-cylinder mean: the comparison the
                  spread figure in the header only summarises. */}
              <span style={{ ...NUM, fontSize: 16, color: "var(--ink-mute)" }}>
                {dev == null ? "" : `${dev >= 0 ? "+" : "−"}${Math.abs(dev).toFixed(1)}`}
              </span>
            </div>

            {/* HIGH is spelled out, not just coloured. Colour on its own is
                not a coding channel here -- every other alert on this console
                carries a word as well, and a value over its limit must survive
                being read on a monochrome display.
                It is pushed to the right of its own line rather than run on
                after the unit: inline, the longer string wrapped, which pushed
                the bar down a line and broke the alignment across the row --
                exactly on the tiles an operator is scanning hardest. */}
            <div style={{ display: "flex", alignItems: "baseline",
                          justifyContent: "space-between", gap: "var(--space-2)",
                          whiteSpace: "nowrap", minWidth: 0 }}>
              <span style={{ ...NUM, fontSize: "var(--size-readout)", lineHeight: 1.1,
                             color: cHi ? "var(--alert-caut)" : "var(--ink)" }}>
                {c?.toFixed(1) ?? DASH}
                <span style={{ fontSize: 16, color: cHi ? "var(--alert-caut)" : "var(--ink-dim)" }}>
                  {" °C head"}
                </span>
              </span>
              {cHi && <span style={{ ...LABEL, color: "var(--alert-caut)" }}>HIGH</span>}
            </div>
            <LimitBar value={c} lim={p.chtLimit} />

            <div style={{ display: "flex", alignItems: "baseline",
                          justifyContent: "space-between", gap: "var(--space-2)",
                          whiteSpace: "nowrap", minWidth: 0 }}>
              <span style={{ ...NUM, fontSize: 20,
                             color: eHi ? "var(--alert-caut)" : "var(--ink-dim)" }}>
                {e?.toFixed(0) ?? DASH}
                <span style={{ fontSize: 16 }}>{" °C exhaust"}</span>
              </span>
              {eHi && <span style={{ ...LABEL, color: "var(--alert-caut)" }}>HIGH</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
