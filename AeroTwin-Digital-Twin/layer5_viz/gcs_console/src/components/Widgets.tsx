/* Dashboard widgets, laid out to the plate in ui/.
 *
 * Every one of these renders MEASURED values. The reference plate carries
 * plausible-looking mock numbers -- among them a cylinder-head temperature of
 * 135 degC shown as NOMINAL, which on this engine is the certified limit and
 * would be a WARNING. Copying a mockup's numbers into a health monitor is how
 * a demonstration ends up asserting something untrue about an engine, so the
 * layout is taken from the plate and the data never is.
 */

import React from "react";

/* ------------------------------------------------------------------------ *
 * Arc gauge
 * ------------------------------------------------------------------------ */

export function ArcGauge(props: {
  value: number | null;          // 0..1
  label: string;
  caption?: string;
  colour: string;
  size?: number;
}) {
  const size = props.size ?? 190;
  const r = size / 2 - 16;
  const cx = size / 2;
  const cy = size / 2 + 6;
  // A 240-degree sweep, not a full circle: the ends are visibly open, so the
  // gauge cannot be misread as a pie showing proportions of a whole.
  const START = 150;
  const SWEEP = 240;

  const pt = (deg: number) => {
    const a = (deg * Math.PI) / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };
  const arc = (from: number, to: number) => {
    const [x1, y1] = pt(from);
    const [x2, y2] = pt(to);
    const large = Math.abs(to - from) > 180 ? 1 : 0;
    return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
  };

  const v = props.value == null ? null : Math.max(0, Math.min(1, props.value));

  return (
    <div style={{ position: "relative", width: size, height: size * 0.82 }}>
      <svg width={size} height={size * 0.82} viewBox={`0 0 ${size} ${size * 0.82}`}
           role="img" aria-label={`${props.label} ${v == null ? "unavailable" : Math.round(v * 100)}`}>
        <path d={arc(START, START + SWEEP)} fill="none"
              stroke="var(--bg-raised)" strokeWidth="13" strokeLinecap="round" />
        {v != null && v > 0 && (
          <path d={arc(START, START + SWEEP * v)} fill="none"
                stroke={props.colour} strokeWidth="13" strokeLinecap="round" />
        )}
      </svg>
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        paddingTop: 10, pointerEvents: "none",
      }}>
        <div style={{
          fontFamily: "var(--font-num)", fontSize: 44, fontWeight: 700,
          lineHeight: 1, color: props.colour,
        }}>
          {/* s7.2: a value that is not there is dashes, never a zero -- a
              health index of 0 and an unavailable one must not look alike. */}
          {v == null ? "———" : Math.round(v * 100)}
        </div>
        <div style={{ fontSize: 16, color: "var(--ink-mute)", marginTop: 4 }}>
          {props.label}
        </div>
        {props.caption && (
          <div style={{
            fontSize: 16, fontWeight: 700, letterSpacing: "0.06em",
            marginTop: 6, color: props.colour,
          }}>
            {props.caption}
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------ *
 * Parameter tile with sparkline
 * ------------------------------------------------------------------------ */

export function Sparkline(props: {
  series: (number | null)[];
  colour: string;
  width?: number;
  height?: number;
}) {
  const w = props.width ?? 150;
  const h = props.height ?? 30;
  const pts = props.series.filter((x): x is number => x != null);
  if (pts.length < 2) {
    return <div style={{ height: h }} aria-hidden="true" />;
  }
  const lo = Math.min(...pts);
  const hi = Math.max(...pts);
  const span = hi - lo || 1;
  const step = w / (pts.length - 1);
  const d = pts
    .map((v, i) => `${i === 0 ? "M" : "L"} ${(i * step).toFixed(1)} ${(h - ((v - lo) / span) * (h - 4) - 2).toFixed(1)}`)
    .join(" ");
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`}
         preserveAspectRatio="none" aria-hidden="true">
      <path d={d} fill="none" stroke={props.colour} strokeWidth="1.6"
            strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function ParamTile(props: {
  label: string;
  value: number | null;
  unit: string;
  digits?: number;
  series?: (number | null)[];
  /* The limit that makes the number a decision rather than a reading. */
  limit?: number | null;
  minimum?: boolean;
  colour?: string;
  compact?: boolean;
}) {
  const d = props.digits ?? 0;
  const missing = props.value == null;
  const exceeded =
    !missing && props.limit != null &&
    (props.minimum ? props.value! < props.limit : props.value! > props.limit);
  const colour = exceeded ? "var(--alert-warn-ink)"
    : (props.colour ?? "var(--state-normal)");

  return (
    <div style={{
      background: "var(--bg-raised)",
      border: `1px solid ${exceeded ? "var(--alert-warn)" : "var(--line)"}`,
      borderRadius: "var(--radius)",
      padding: props.compact ? "6px 10px 4px" : "11px 13px 8px",
      minWidth: 0,
    }}>
      <div style={{
        fontSize: "var(--size-label)", color: "var(--ink-mute)",
        letterSpacing: "0.09em", marginBottom: props.compact ? 3 : 4,
      }}>
        {props.label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
        <span style={{
          fontFamily: "var(--font-num)", fontSize: props.compact ? 26 : 30, fontWeight: 700,
          lineHeight: 1, color: exceeded ? "var(--alert-warn-ink)" : "var(--ink)",
        }}>
          {missing ? "———" : props.value!.toFixed(d)}
        </span>
        <span style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)" }}>
          {props.unit}
        </span>
      </div>
      {/* Word as well as colour, always (s14). */}
      {exceeded && (
        <div style={{
          fontSize: "var(--size-label)", color: "var(--alert-warn-ink)",
          fontWeight: 700, marginTop: 4,
        }}>
          {props.minimum ? "BELOW LIMIT" : "OVER LIMIT"}
        </div>
      )}
      {props.series && (
        <div style={{ marginTop: props.compact ? 3 : 6 }}>
          <Sparkline
            series={props.series}
            colour={colour}
            height={props.compact ? 16 : undefined}
          />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------ *
 * Indicator bar
 * ------------------------------------------------------------------------ */

export function IndicatorBar(props: {
  label: string;
  value: number | null;        // 0..1
}) {
  const v = props.value;
  // The same cut-offs as the HEALTH page and the configured chi bands: GOOD
  // from 0.80, the maintenance threshold at 0.60. At 0.85 / 0.70 here, 0.75
  // was amber on the dashboard and green one click later (HMI-07).
  const colour = v == null ? "var(--ink-mute)"
    : v >= 0.80 ? "var(--state-normal)"
      : v >= 0.60 ? "var(--alert-caut)" : "var(--alert-warn-ink)";
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "128px 1fr 52px",
      gap: 12, alignItems: "center", marginBottom: 8,
    }}>
      <span style={{ fontSize: 16, textTransform: "capitalize" }}>
        {props.label.replace(/_/g, " ")}
      </span>
      <div style={{
        height: 8, background: "var(--bg-raised)", borderRadius: 4,
        overflow: "hidden",
      }}>
        <div style={{
          width: `${v == null ? 0 : Math.max(0, Math.min(1, v)) * 100}%`,
          height: "100%", background: colour,
        }} />
      </div>
      <span style={{
        fontFamily: "var(--font-num)", fontSize: 16, textAlign: "right",
        color: v == null ? "var(--ink-mute)" : "var(--ink)",
      }}>
        {v == null ? "———" : `${Math.round(v * 100)}%`}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------------ *
 * Key-value row
 * ------------------------------------------------------------------------ */

export function StatRow(props: {
  label: string;
  value: React.ReactNode;
  colour?: string;
}) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "baseline",
      gap: 14, padding: "7px 0",
      borderBottom: "1px solid var(--line)",
    }}>
      <span style={{ fontSize: 16, color: "var(--ink-dim)" }}>{props.label}</span>
      <span style={{
        fontSize: 16, fontWeight: 700, textAlign: "right",
        color: props.colour ?? "var(--ink)",
        fontFamily: "var(--font-num)",
      }}>
        {props.value}
      </span>
    </div>
  );
}
