/* ONE STATUS VOCABULARY FOR THE WHOLE CONSOLE.
 *
 * Astro UXDS (US Space Force ground systems): every status is a colour AND a
 * shape, from one fixed set, and an aggregate takes the highest. The console
 * used a different colour recipe on every page -- green chips, amber borders,
 * cyan text -- so the same word could look three ways and a green "fine"
 * competed for attention with an amber "look at me".
 *
 * Six statuses. Normal is the quietest thing on the screen: its symbol is
 * green, its TEXT is ordinary ink (dark cockpit). Colour on text is kept for
 * advisory, caution and warning, which are the only statuses that ask for
 * attention. Shape carries the status without colour (P4, monochrome and
 * colour-vision deficiency).
 */

export type Level = "off" | "standby" | "normal" | "advisory" | "caution" | "warning";

const ORDER: Level[] = ["off", "standby", "normal", "advisory", "caution", "warning"];

export function worst(...levels: Level[]): Level {
  return levels.reduce((a, b) => (ORDER.indexOf(b) > ORDER.indexOf(a) ? b : a), "off");
}

/* Fill carries the hue, edge carries the contrast (theme/tokens.css). The
 * quiet states are drawn in the neutral greys and need no split. */
const FILL: Record<Level, string> = {
  off: "var(--ink-mute)",
  standby: "var(--ink-dim)",
  normal: "var(--sym-normal-fill)",
  advisory: "var(--sym-advis-fill)",
  caution: "var(--sym-caut-fill)",
  warning: "var(--sym-warn-fill)",
};
const EDGE: Record<Level, string> = {
  off: "var(--ink-mute)",
  standby: "var(--ink-dim)",
  normal: "var(--sym-normal-edge)",
  advisory: "var(--sym-advis-edge)",
  caution: "var(--sym-caut-edge)",
  warning: "var(--sym-warn-edge)",
};

/** Text colour for a status word: ink for the quiet ones. */
export const INK: Record<Level, string> = {
  off: "var(--ink-mute)",
  standby: "var(--ink-dim)",
  normal: "var(--ink)",
  advisory: "var(--alert-advis)",
  caution: "var(--alert-caut)",
  warning: "var(--alert-warn-ink)",
};

/** The symbol: dash, ring, dot, diamond, triangle, square. */
export function StatusSymbol({ level, size = 14 }: { level: Level; size?: number }) {
  const c = FILL[level];
  const e = { stroke: EDGE[level], strokeWidth: 1.4, strokeLinejoin: "round" as const };
  const s = size;
  return (
    <svg width={s} height={s} viewBox="0 0 14 14" aria-hidden="true"
         style={{ flex: "0 0 auto", display: "block" }}>
      {level === "off" && <rect x="2" y="6" width="10" height="2.4" rx="1" fill={c} />}
      {level === "standby" && <circle cx="7" cy="7" r="4.6" fill="none" stroke={c} strokeWidth="2" />}
      {level === "normal" && <circle cx="7" cy="7" r="5" fill={c} {...e} />}
      {level === "advisory" && <path d="M7 1.4 12.6 7 7 12.6 1.4 7z" fill={c} {...e} />}
      {level === "caution" && <path d="M7 1.6 12.8 12.3H1.2z" fill={c} {...e} />}
      {level === "warning" && <rect x="1.8" y="1.8" width="10.4" height="10.4" fill={c} {...e} />}
    </svg>
  );
}

/** Symbol plus word. The word is the status; the symbol makes it scannable. */
export function Status(props: { level: Level; text: string; size?: number; bold?: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8,
                   color: INK[props.level], fontWeight: props.bold === false ? 500 : 700,
                   fontSize: props.size ?? 16, whiteSpace: "nowrap" }}>
      <StatusSymbol level={props.level} size={Math.max(12, (props.size ?? 16) - 2)} />
      {props.text}
    </span>
  );
}

// --- mappings from the system's own words -------------------------------

export function aircraftLevel(status: string): Level {
  switch (status) {
    case "SERVICEABLE": return "normal";
    case "UNSERVICEABLE": return "caution";
    case "AWAITING INSPECTION": return "standby";
    case "FLYING": case "ENGINE RUNNING": case "GROUND RUN": case "ON GCS":
      return "advisory";
    default: return "off";
  }
}

export function missionLevel(status: string): Level {
  switch (status) {
    case "PLANNED": return "standby";
    case "APPROVED": return "normal";
    case "PREFLIGHT": case "ENGINE_RUNNING": case "AIRBORNE": case "RTB": case "ABORTING":
      return "advisory";
    case "AWAITING_DEBRIEF": return "standby";
    default: return "off";
  }
}

export function severityLevel(sev: string): Level {
  switch (sev) {
    case "ADVISORY": return "advisory";
    case "CAUTION": return "caution";
    case "WARNING": case "EMERGENCY": return "warning";
    default: return "standby";
  }
}

export function verdictLevel(v: string | null | undefined): Level {
  switch (v) {
    case "GO": return "normal";
    case "GO_WITH_LIMITS": return "caution";
    case "NO_GO": return "warning";
    default: return "standby";
  }
}

export function bandLevel(band: string | null | undefined): Level {
  switch (band) {
    case "EXCELLENT": case "GOOD": return "normal";
    case "FAIR": case "POOR": return "caution";
    case "DEGRADED": case "CRITICAL": case "UNSAFE": return "warning";
    default: return "standby";
  }
}

/** Alert level 1-5 (GREEN..RED) onto the vocabulary. */
export function alertLevel(level: number): Level {
  return level >= 5 ? "warning" : level >= 3 ? "caution" : level === 2 ? "advisory" : "normal";
}

/** Sentence case from the system's enum words, keeping the acronyms a
 *  squadron reads as acronyms ("On GCS", not "On gcs"). */
const ACRONYMS = /\b(gcs|rtb|nff|isr|tbo|egt|cht|utc|nogo)\b/g;
export const words = (s: string | null | undefined) =>
  (s ?? "").replace(/_/g, " ").toLowerCase().replace(ACRONYMS, (a) => a.toUpperCase())
    .replace(/^./, (c) => c.toUpperCase());

/** A 0-1 health figure as a percentage, quiet when it is fine: a symbol
 *  appears only when the value needs looking at (>= 0.9 normal, then
 *  caution, then warning below 0.75). */
export function healthLevel(v: number | null | undefined): Level | null {
  if (v == null) return null;
  return v >= 0.9 ? null : v >= 0.75 ? "caution" : "warning";
}

export function Pct({ v, digits = 1 }: { v: number | null | undefined; digits?: number }) {
  const l = healthLevel(v);
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
      {l && <StatusSymbol level={l} size={12} />}
      {v == null ? "—" : `${(v * 100).toFixed(digits)} %`}
    </span>
  );
}
