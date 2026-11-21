/* FIGURES FOR THE HEALTH PAGE.
 *
 * One rule decides whether anything in this file gets drawn: a chart has to
 * answer an engineering question. Not "this card has a number in it, give it a
 * line". The page previously carried a sparkline per subsystem because the
 * space was there, and three of the four were unreadable -- a noisy trace with
 * no baseline, no band and no reference answers nothing, and a chart that
 * answers nothing is worse than no chart, because it looks like it does.
 *
 * So the shapes here are chosen per measurement:
 *
 *   Deviation        measured against the as-new model, on a ZERO baseline.
 *                    "Is it running away from the model, and by how much?"
 *   CylinderBalance  the cylinders side by side against their own mean and
 *                    the spread the engine allows. "Are they balanced?"
 *   AgainstBands     one value on its own certified scale. "Is this OK?"
 *   AxisBars         a vector broken into its axes. "Where is it coming from?"
 *   CompareToAsNew   measured beside the as-new figure at the same operating
 *                    point. "Better or worse than a new engine?"
 *   NoTrace          the honest answer when the data will not support any of
 *                    them. Deliberate and small, never a large empty frame.
 *
 * Nothing here computes, smooths, interpolates or extrapolates a health
 * figure. Everything is read from the snapshot as served.
 */
import type { CSSProperties, ReactNode } from "react";

const NUM: CSSProperties = { fontFamily: "var(--font-num)" };
const LABEL: CSSProperties = { fontSize: "var(--size-label)", color: "var(--ink-dim)" };

export const nz = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

/** Read a Measurement-or-plain-number node from the snapshot. */
export const readVal = (node: any): number | null =>
  nz(node && typeof node === "object" && "value" in node ? node.value : node);

/* Banding moved to lib/bands.ts, where it is a pure function with a truth
 * table behind it. The version that used to live here compared with `>=`,
 * which disagreed with the alert engine (edge_rules.py trips strictly, on
 * `>`), and had no concept of the low side at all -- so a 100 % battery was
 * painted warning-red and a dangerously low oil pressure was painted in the
 * "unavailable" grey. Re-exported so existing imports keep working. */
import { bandInk, bandOf, bandWord, isAlert, type Limit } from "../../lib/bands";
export type { Limit, Band } from "../../lib/bands";
export { bandOf, bandInk, bandWord, isAlert } from "../../lib/bands";

/* ------------------------------------------------------------------ frame */
/** A figure states what it is, in what units, and what it reads NOW.
 *  Every visual on this page goes through here, so none of them can turn up
 *  as an anonymous squiggle. */
export function Figure({ name, value, unit, note, children }: {
  name: string; value?: ReactNode; unit?: string; note?: ReactNode; children?: ReactNode;
}) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "baseline",
                    justifyContent: "space-between", gap: "var(--space-2)" }}>
        <span style={{ ...LABEL, overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>{name}</span>
        {value != null && (
          <span style={{ ...NUM, fontSize: 18, whiteSpace: "nowrap" }}>
            {value}
            {unit && <span style={{ fontSize: 16, color: "var(--ink-dim)" }}> {unit}</span>}
          </span>
        )}
      </div>
      {children && <div style={{ marginTop: 6 }}>{children}</div>}
      {note && <div style={{ fontSize: 16, color: "var(--ink-mute)", marginTop: 4,
                             lineHeight: 1.35 }}>{note}</div>}
    </div>
  );
}

/* --------------------------------------------------------------- no trace */
/** WHAT AN HONEST GAP LOOKS LIKE.
 *
 * Not a blank chart frame with a caption in it -- that reserves the height of
 * evidence and then fails to deliver any, which reads as something broken
 * rather than as something absent. One line, stated plainly, taking the room
 * one line takes. */
export function NoTrace({ what, why }: { what: string; why?: string }) {
  return (
    <div style={{ borderLeft: "2px solid var(--line)", paddingLeft: "var(--space-3)",
                  color: "var(--ink-mute)", fontSize: 16, lineHeight: 1.4 }}>
      {what}
      {why && <div style={{ marginTop: 2 }}>{why}</div>}
    </div>
  );
}

/* ------------------------------------------------------------- deviation */
/** MEASURED AGAINST THE AS-NEW MODEL, ON A ZERO BASELINE.
 *
 * The old thermal chart drew the measurement and the model as two separate
 * lines. They sit at different levels, so the eye compares two wandering
 * curves and the thing that actually matters -- the GAP between them, which is
 * what the index scores -- has to be estimated by looking. Plotting the
 * difference puts that gap on a zero line where it can be read directly, and
 * makes "drifting away from the model" a slope instead of a widening gap
 * between two moving things.
 */
export function Deviation({ measured, model, running, unit, height = 96, digits = 1 }: {
  measured?: (number | null)[]; model?: (number | null)[];
  /* Engine speed for the same samples. The as-new model describes a RUNNING
   * engine, so subtracting it from a stopped one yields about -85 degC -- not
   * a fault, just the engine being off, and drawn as a deviation it reads as a
   * catastrophe. Those samples are masked out rather than the whole chart
   * being withheld: a session that included running time still has a real
   * trace in it, and hiding that because the aircraft is descending right now
   * would throw away the evidence the card exists to show. */
  running?: (number | null)[];
  unit: string; height?: number; digits?: number;
}) {
  const m = measured ?? [], p = model ?? [];
  const n = Math.min(m.length, p.length);
  const d: (number | null)[] = [];
  for (let i = 0; i < n; i++) {
    const a = nz(m[i]), b = nz(p[i]);
    const turning = running == null || (nz(running[i]) ?? 0) > 100;
    d.push(a != null && b != null && turning ? a - b : null);
  }
  const vals = d.filter((x): x is number => x != null);
  if (vals.length < 2) return null;

  const mag = Math.max(Math.abs(Math.min(...vals)), Math.abs(Math.max(...vals)), 1e-6);
  const span = mag * 1.25;                 // symmetric about zero, always
  const W = 600, H = height;
  const y = (v: number) => H / 2 - (v / span) * (H / 2);
  let path = "", area = "", started = false;
  d.forEach((v, i) => {
    if (v == null) { started = false; return; }
    const x = (i / Math.max(d.length - 1, 1)) * W;
    path += `${started ? "L" : "M"}${x.toFixed(1)},${y(v).toFixed(1)}`;
    area += `${started ? "L" : `M${x.toFixed(1)},${(H / 2).toFixed(1)}L`}` +
            `${x.toFixed(1)},${y(v).toFixed(1)}`;
    started = true;
  });
  const last = vals[vals.length - 1];
  const lastX = W;
  const over = Math.abs(last) > mag * 0.66;

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
           style={{ width: "100%", height: H, display: "block" }}>
        {/* the model itself -- deviation zero */}
        <line x1={0} y1={H / 2} x2={W} y2={H / 2}
              stroke="var(--phys)" strokeWidth={1} strokeDasharray="5 4"
              vectorEffect="non-scaling-stroke" />
        <path d={area + `L${lastX},${H / 2}Z`} fill="var(--line)" opacity={0.55} />
        <path d={path} fill="none" strokeWidth={2}
              stroke={over ? "var(--alert-caut)" : "var(--ink)"}
              vectorEffect="non-scaling-stroke" />
      </svg>
      <div style={{ display: "flex", justifyContent: "space-between",
                    ...LABEL, marginTop: 2 }}>
        <span style={NUM}>
          {last >= 0 ? "+" : "−"}{Math.abs(last).toFixed(digits)} {unit} now
        </span>
        <span>as-new model = 0</span>
      </div>
    </div>
  );
}

/* -------------------------------------------------------- cylinder balance */
/** ARE THE CYLINDERS BALANCED?
 *
 * CSI is defined as the spread of head temperature across the four cylinders,
 * so the honest picture of it is the four cylinders against each other -- not
 * a time series of one aggregate, which is what a generic sparkline gave and
 * which cannot show imbalance at all.
 *
 * Each bar is a cylinder's departure from the four-cylinder mean. The scale is
 * the spread the engine definition ALLOWS (parameters.<x>.spread_alert), so a
 * balanced engine draws four short stubs -- the truth -- and one cylinder
 * walking away reaches the end of its track. The cylinders are ordered by
 * bank, 1 and 3 then 2 and 4, matching the numbers drawn on the 3D model so
 * the two views can be read against each other.
 */
export function CylinderBalance({ values, mean, spread, spreadAlert, unit,
                                 digits = 1, onPick, resolveAt }: {
  values: { n: number; v: number | null }[];
  mean: number | null; spread: number | null; spreadAlert: number | null;
  unit: string; digits?: number;
  /** Given, each cylinder becomes a control that asks for that cylinder on the
   *  3D model. The figure and the model then name the same part. */
  onPick?: (n: number) => void;
  /** The measured noise of this channel. Two cylinders closer together than
   *  this are not in a known order, so no outlier is named. */
  resolveAt?: number | null;
}) {
  const full = spreadAlert != null && spreadAlert > 0 ? spreadAlert / 2 : null;
  const devs = values.map((c) => ({
    ...c, d: c.v != null && mean != null ? c.v - mean : null,
  }));

  /* NAMING AN OUTLIER ONLY WHEN THERE IS ONE.
   *
   * This used to pick the largest deviation and always print "#N furthest out".
   * Measured on a settled engine, that verdict named a DIFFERENT cylinder on 62
   * to 73 % of frames -- three times a second -- because the four head
   * temperatures sit about 1.8 degC apart while each sensor carries about 0.8
   * degC of scatter. With the gap between first and second place smaller than
   * the noise, there is no first place; the ranking was being read out of the
   * noise, and a reader who acted on it would pull a different cylinder each
   * time they looked.
   *
   * So the outlier is named -- and highlighted -- only when it leads the next
   * cylinder by more than this channel's measured noise. Otherwise the figure
   * says the cylinders are even, which is what the data actually supports. The
   * bars and the values are unchanged either way: only the VERDICT is withheld,
   * never a reading. Exhaust gas, whose cylinders sit tens of degrees apart,
   * resolves easily and still names its outlier. */
  const ranked = devs.filter((c) => c.d != null)
    .sort((a, b) => Math.abs(b.d as number) - Math.abs(a.d as number));
  const lead = ranked[0] ?? null;
  const runnerUp = ranked[1] ?? null;
  const gap = lead != null && runnerUp != null
    ? Math.abs(lead.d as number) - Math.abs(runnerUp.d as number) : null;
  const resolved = lead != null
    && (resolveAt == null || gap == null || gap >= resolveAt);
  const worst = resolved ? lead : null;

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "auto minmax(0,1fr) auto",
                    columnGap: "var(--space-2)", rowGap: 5, alignItems: "center" }}>
        {devs.map((c) => {
          const isWorst = worst != null && c.n === worst.n && Math.abs(c.d ?? 0) > 1e-9;
          const frac = c.d == null || full == null ? 0
            : Math.max(-1, Math.min(1, c.d / full));
          const pct = Math.abs(frac) * 50;
          const label = `Cylinder ${c.n}` +
            (onPick ? " \u2014 show on the engine model" : "");
          return [
            onPick ? (
              <button key={`n${c.n}`} type="button" title={label} aria-label={label}
                      onClick={() => onPick(c.n)}
                      style={{ ...NUM, fontSize: 16, cursor: "pointer",
                               background: "transparent", padding: "0 4px",
                               border: "1px solid var(--line)",
                               borderRadius: "var(--radius)",
                               color: isWorst ? "var(--ink)" : "var(--ink-dim)" }}>
                {c.n}
              </button>
            ) : (
              <span key={`n${c.n}`} style={{ ...NUM, fontSize: 16,
                                             color: isWorst ? "var(--ink)" : "var(--ink-dim)" }}>
                {c.n}
              </span>
            ),
            <div key={`b${c.n}`}
                 style={{ position: "relative", height: 12, background: "var(--bg-raised)",
                          border: "1px solid var(--line)", borderRadius: 2 }}>
              <div style={{ position: "absolute", left: "50%", top: -2, bottom: -2,
                            width: 1, background: "var(--line)" }} />
              {c.d != null && full != null && (
                <div className="bar-fill"
                     style={{ position: "absolute", top: 1, bottom: 1,
                              left: frac >= 0 ? "50%" : `${50 - pct}%`,
                              width: `${Math.max(pct, 0.6)}%`,
                              background: isWorst ? "var(--ink)" : "var(--ink-dim)" }} />
              )}
            </div>,
            <span key={`v${c.n}`} style={{ ...NUM, fontSize: 16, textAlign: "right",
                                           color: isWorst ? "var(--ink)" : "var(--ink-dim)" }}>
              {c.v == null ? "—" : c.v.toFixed(digits)}
            </span>,
          ];
        })}
      </div>
      <div style={{ ...LABEL, marginTop: 6, display: "flex",
                    justifyContent: "space-between", gap: "var(--space-2)" }}>
        <span>
          spread <span style={NUM}>{spread == null ? "—" : spread.toFixed(digits)}</span>
          {spreadAlert != null && <> of <span style={NUM}>{spreadAlert}</span> allowed</>}
          {" "}{unit}
        </span>
        {worst?.d != null && Math.abs(worst.d) > 1e-9
          ? <span>#{worst.n} furthest out</span>
          : ranked.length > 1 && <span className="t-mute">none stands out</span>}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------- against bands */
/** ONE VALUE ON ITS OWN CERTIFIED SCALE.
 *
 * For a measurement with no session history there is nothing to plot over
 * time, but there is still a question worth answering: is this reading where
 * it should be? The engine definition carries the answer -- normal band, alert
 * and critical -- so the value is drawn on that scale rather than left as a
 * bare number, and rather than given a chart it has no data for.
 */
export function AgainstBands({ value, lim, unit, digits = 1 }: {
  value: number | null; lim?: Limit | null; unit?: string; digits?: number;
}) {
  const top = lim?.critical_max ?? lim?.alert_max ?? lim?.range?.[1] ?? null;
  if (top == null || top <= 0) return null;
  const at = (v: number) => Math.max(0, Math.min(100, (v / top) * 100));
  const band = bandOf(value, lim);
  // Keyed by ROLE, not by value: an engine may define normal_max and alert_max
  // at the same figure (this one puts both oil-pressure ticks at 72.5), and
  // keying on the number then collides.
  const tick = (role: string, v: number | null | undefined, colour: string) =>
    v == null ? null : (
      <div key={role} style={{ position: "absolute", top: -2, bottom: -2,
                               left: `${at(v)}%`, width: 1, background: colour }} />
    );
  return (
    <div>
      <div style={{ position: "relative", height: 12, background: "var(--bg-raised)",
                    border: "1px solid var(--line)", borderRadius: 2 }}>
        {value != null && (
          <div className="bar-fill"
               style={{ position: "absolute", top: 1, bottom: 1, left: 1,
                        width: `calc(${at(value)}% - 2px)`, background: bandInk(band) }} />
        )}
        {tick("nmin", lim?.normal_min, "var(--ink-dim)")}
        {tick("nmax", lim?.normal_max, "var(--ink-dim)")}
        {tick("alert", lim?.alert_max, "var(--alert-caut)")}
      </div>
      <div style={{ ...LABEL, marginTop: 3 }}>
        {/* A one-sided envelope is described as one-sided. Printing an em-dash
            for the absent bound gave "normal —3.5" on vibration, which has only
            an upper bound and read as a typo or a negative number. */}
        {lim?.normal_min != null && lim?.normal_max != null
          ? <>normal <span style={NUM}>{lim.normal_min}–{lim.normal_max}</span></>
          : lim?.normal_max != null
            ? <>normal below <span style={NUM}>{lim.normal_max}</span></>
            : lim?.normal_min != null
              ? <>normal above <span style={NUM}>{lim.normal_min}</span></>
              : <>no normal band published</>}
        {lim?.alert_max != null && <> · alert <span style={NUM}>{lim.alert_max}</span></>}
        {lim?.alert_min != null && <> · alert below <span style={NUM}>{lim.alert_min}</span></>}
        {unit ? ` ${unit}` : ""}
        {/* The word beside the colour, from the same band the fill used, so the
            two can never drift apart. */}
        {bandWord(band) && (
          <span style={{ color: isAlert(band) ? bandInk(band) : "var(--ink-dim)" }}>
            {" · "}{bandWord(band)}
          </span>
        )}
        {digits < 0 && null}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- axes */
/** WHERE THE VIBRATION IS COMING FROM.
 *
 * A single RMS total plotted over time is the one vibration picture that
 * carries no diagnosis: it is a noisy line whose every wiggle is expected. The
 * axes are the useful split -- a rise on one axis is a different fault from a
 * rise on all three -- and they are reported alongside the total.
 */
export function AxisBars({ axes, unit, digits = 2 }: {
  axes: { name: string; v: number | null }[]; unit: string; digits?: number;
}) {
  const vals = axes.map((a) => a.v).filter((v): v is number => v != null);
  if (!vals.length) return null;
  const top = Math.max(...vals) * 1.15 || 1;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "auto minmax(0,1fr) auto",
                  columnGap: "var(--space-2)", rowGap: 5, alignItems: "center" }}>
      {axes.map((a) => [
        <span key={`n${a.name}`} style={{ ...LABEL }}>{a.name}</span>,
        <div key={`b${a.name}`}
             style={{ position: "relative", height: 12, background: "var(--bg-raised)",
                      border: "1px solid var(--line)", borderRadius: 2 }}>
          {a.v != null && (
            <div className="bar-fill"
                 style={{ position: "absolute", top: 1, bottom: 1, left: 1,
                          width: `calc(${(a.v / top) * 100}% - 2px)`,
                          background: "var(--ink-dim)" }} />
          )}
        </div>,
        <span key={`v${a.name}`} style={{ ...NUM, fontSize: 16, textAlign: "right",
                                          color: "var(--ink-dim)" }}>
          {a.v == null ? "—" : a.v.toFixed(digits)}
        </span>,
      ])}
      <span />
      <span style={{ ...LABEL }}>per axis, {unit}</span>
      <span />
    </div>
  );
}

/* ------------------------------------------------------------- comparison */
/** MEASURED BESIDE THE AS-NEW FIGURE AT THE SAME OPERATING POINT.
 *
 * Fuel burn and thermal efficiency only mean something next to what a new
 * engine would have done here -- climb and loiter differ by more than a worn
 * engine differs from a fresh one. Two bars on one scale say that in a glance;
 * the number on its own does not, and a trend of it answers a different
 * question.
 */
export function CompareToAsNew({ now, asNew, unit, digits = 1, betterIsLower = true }: {
  now: number | null; asNew: number | null; unit: string;
  digits?: number; betterIsLower?: boolean;
}) {
  if (now == null || asNew == null) return null;
  const top = Math.max(now, asNew) * 1.12 || 1;
  const better = betterIsLower ? now < asNew : now > asNew;
  const row = (label: string, v: number, colour: string) => (
    <>
      <span style={{ ...LABEL, whiteSpace: "nowrap" }}>{label}</span>
      <div style={{ position: "relative", height: 12, background: "var(--bg-raised)",
                    border: "1px solid var(--line)", borderRadius: 2 }}>
        <div className="bar-fill"
             style={{ position: "absolute", top: 1, bottom: 1, left: 1,
                      width: `calc(${(v / top) * 100}% - 2px)`, background: colour }} />
      </div>
      <span style={{ ...NUM, fontSize: 16, textAlign: "right" }}>{v.toFixed(digits)}</span>
    </>
  );
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "auto minmax(0,1fr) auto",
                    columnGap: "var(--space-2)", rowGap: 5, alignItems: "center" }}>
        {row("measured", now, better ? "var(--ink)" : "var(--alert-caut)")}
        {row("as-new", asNew, "var(--phys)")}
      </div>
      <div style={{ ...LABEL, marginTop: 4 }}>
        {unit} · {better ? "better than" : "worse than"} as-new here
      </div>
    </div>
  );
}
