/* THE MAP TOOLS — what a click on the ground means.
 *
 * The map has always had one behaviour: click open ground, get a waypoint.
 * That is the right default and it stays the default. What it could not do is
 * be READ without being edited -- every click while looking at the terrain
 * dropped a point -- and it could not place a patrol area anywhere except the
 * midpoint of the longest leg.
 *
 * Three tools, named, with the consequence of a click printed under them. Not
 * an icon rail: a glyph an operator has to learn is a glyph they get wrong
 * once, and the words are 16 px because everything in this console is.
 *
 * It sits where the state pill used to. The state has moved to the command
 * bar, where it is visible on every tab and with the dock collapsed, so this
 * corner was free.
 */

export type Tool = "SELECT" | "WAYPOINT" | "PATROL";

const HINT: Record<Tool, string> = {
  SELECT: "click to select · drag to pan · drag a point to move it",
  WAYPOINT: "click open ground to add a waypoint before the recovery field",
  PATROL: "click open ground to place a patrol area there",
};

/* THE LABELS ARE NOT OPTIONAL.
 * They were hidden below the page's `compact` width, which is a property of
 * the whole band and not of this corner of the map -- on a 1366 panel the map
 * is still a thousand pixels wide and had three unlabelled glyphs on it. A
 * tool whose name is only in a tooltip is a tool an operator gets wrong once. */
export function Palette(props: {
  tool: Tool;
  onTool: (t: Tool) => void;
  /** Locked missions have no tools: the route belongs to the flown sortie. */
  locked: boolean;
}) {
  if (props.locked) return null;
  return (
    <div style={{ position: "absolute", left: 56, top: 10, maxWidth: "62%",
                  pointerEvents: "auto", display: "flex",
                  flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
      <div style={{ display: "flex", gap: 1, background: "var(--line)",
                    border: "1px solid var(--line)",
                    borderRadius: "var(--radius)", overflow: "hidden" }}>
        {(["SELECT", "WAYPOINT", "PATROL"] as Tool[]).map((t) => {
          const on = props.tool === t;
          return (
            <button key={t} onClick={() => props.onTool(t)} className="mo-tool"
                    aria-pressed={on} title={HINT[t]}
                    style={{ display: "flex", alignItems: "center", gap: 7,
                             height: 32, padding: "0 12px", border: "none",
                             cursor: "pointer", whiteSpace: "nowrap",
                             fontFamily: "var(--font-ui)",
                             fontSize: "var(--size-label)", fontWeight: 700,
                             letterSpacing: "0.07em",
                             background: on
                               ? "color-mix(in srgb, var(--alert-advis) 18%, var(--bg-panel))"
                               : "color-mix(in srgb, var(--bg-panel) 92%, transparent)",
                             color: on ? "var(--alert-advis)" : "var(--ink-dim)" }}>
              <Glyph tool={t} />
              {t}
            </button>
          );
        })}
      </div>
      {/* s14: no blur backdrop -- an opaque panel with a hairline edge. */}
      <div style={{ padding: "3px 9px", borderRadius: "var(--radius)",
                      background: "var(--bg-panel)",
                      border: "1px solid var(--line)",
                      fontSize: "var(--size-label)", color: "var(--ink-mute)",
                      whiteSpace: "nowrap", overflow: "hidden",
                    textOverflow: "ellipsis", maxWidth: "100%" }}>
        {HINT[props.tool]}
      </div>
    </div>
  );
}

function Glyph({ tool }: { tool: Tool }) {
  const common = { width: 14, height: 14, viewBox: "0 0 24 24",
                   fill: "none", stroke: "currentColor", strokeWidth: 2,
                   strokeLinecap: "round" as const,
                   strokeLinejoin: "round" as const,
                   "aria-hidden": true };
  if (tool === "SELECT") {
    return <svg {...common}><path d="M5 3l7 17 2.5-6.5L21 11z" /></svg>;
  }
  if (tool === "WAYPOINT") {
    return (
      <svg {...common}>
        <path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z" />
        <circle cx="12" cy="10" r="2.2" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="8" strokeDasharray="3.5 3" />
      <circle cx="12" cy="12" r="1.6" />
    </svg>
  );
}
