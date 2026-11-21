/* The small parts the Mission Simulator is assembled from.
 *
 * Nothing here introduces a colour, a typeface or a size. Every value is a
 * token out of theme/tokens.css, because the console's palette is normative
 * (PRD Part 4 s3.2) and a page that invents its own greys is a page that has
 * quietly left the standard. What these add is HIERARCHY: a section that can
 * be folded away, a chip that reads as a choice rather than a button, a
 * readout that separates the number from its unit -- the things the old
 * mission page did with rows of identical boxes.
 */

import { useState, type CSSProperties, type ReactNode } from "react";

/* ------------------------------------------------------------------ *
 * Section -- progressive disclosure inside the builder
 * ------------------------------------------------------------------ */

export function Section(props: {
  title: string;
  hint?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  /** A section with nothing to configure yet still says it is there. */
  muted?: boolean;
  /* LOCKED MEANS LOCKED, AND THE BROWSER ENFORCES IT.
   * The body is a disabled `fieldset`, which disables every control inside it
   * natively -- inputs, selects and buttons, including ones added later -- and
   * takes them out of the tab order as well. The HEADER stays live, because a
   * locked mission is still one an operator needs to be able to open and read.
   * A lock implemented by hiding the controls, or by an `onChange` that quietly
   * returns, is a lock that the next control added to the panel is not behind. */
  locked?: boolean;
  /* THE SECTION THAT TAKES WHAT IS LEFT.
   * One section in the builder holds a list that grows -- the route -- and the
   * rest are fixed forms. Letting the whole panel scroll means the list can be
   * pushed off the bottom by the forms above it, which is how the thing the
   * operator is editing ends up being the thing they cannot see. This one
   * takes the remaining height and scrolls inside itself instead, so its
   * heading never leaves the panel. */
  grow?: boolean;
}) {
  const [open, setOpen] = useState(props.defaultOpen ?? true);
  const head = (
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          display: "flex", alignItems: "center", gap: 8, width: "100%",
          padding: "10px var(--space-4)", background: "transparent",
          border: "none", cursor: "pointer", textAlign: "left",
          color: props.muted ? "var(--ink-mute)" : "var(--ink-dim)",
          fontFamily: "var(--font-ui)", fontSize: "var(--size-label)",
          letterSpacing: "0.1em", fontWeight: 600,
        }}
      >
        <span style={{ display: "inline-block", width: 9, textAlign: "center",
                       transition: "transform 140ms ease",
                       transform: open ? "rotate(90deg)" : "none",
                       color: "var(--ink-mute)" }}>›</span>
        {props.title.toUpperCase()}
        <span style={{ marginLeft: "auto", display: "flex", alignItems: "center",
                       gap: 8, letterSpacing: 0, fontWeight: 400 }}>
          {props.right}
          {props.locked && <LockGlyph />}
        </span>
      </button>
  );

  const hint = props.hint && (
    <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                  lineHeight: 1.5, marginBottom: "var(--space-3)" }}>
      {props.hint}
    </div>
  );

  if (props.grow) {
    return (
      <div style={{ borderBottom: "1px solid var(--line)", display: "flex",
                    flexDirection: "column",
                    /* A FLOOR, so that a panel whose other sections are all
                       open cannot squeeze this one to nothing -- which is the
                       failure the growing section exists to prevent. Below the
                       floor the panel scrolls, as it did before. */
                    minHeight: open ? 196 : 0,
                    flex: open ? "1 1 auto" : "0 0 auto" }}>
        {head}
        {open && (
          <fieldset disabled={props.locked}
                    className={"panel-body" + (props.locked ? " ms-locked" : "")}
                    style={{ flex: 1, minHeight: 0, overflowY: "auto",
                             overflowX: "hidden", margin: 0, border: "none",
                             minWidth: 0,
                             padding: "0 var(--space-4) var(--space-4)" }}>
            {hint}
            {props.children}
          </fieldset>
        )}
      </div>
    );
  }

  return (
    <div style={{ borderBottom: "1px solid var(--line)", flex: "0 0 auto" }}>
      {head}
      {/* 0fr -> 1fr animates a height the browser had to measure anyway, which
          is the one way to collapse a box of unknown height without a
          hardcoded pixel figure that will be wrong on the next change. */}
      <div className="ms-collapse" style={{ gridTemplateRows: open ? "1fr" : "0fr" }}>
        <div style={{ minHeight: 0, overflow: "hidden" }}>
          <fieldset disabled={props.locked}
                    className={props.locked ? "ms-locked" : undefined}
                    style={{ padding: "0 var(--space-4) var(--space-4)", margin: 0,
                             border: "none", minWidth: 0 }}>
            {hint}
            {props.children}
          </fieldset>
        </div>
      </div>
    </div>
  );
}

export function LockGlyph({ colour }: { colour?: string }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true"
         stroke={colour ?? "var(--alert-caut)"} strokeWidth="2.2"
         strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="10" width="16" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

/* ------------------------------------------------------------------ *
 * Chip -- one of a small set of choices
 * ------------------------------------------------------------------ */

export function Chip(props: {
  on?: boolean; onClick?: () => void; title?: string; children: ReactNode;
  tone?: "advis" | "caut" | "normal";
  disabled?: boolean;
}) {
  const tone = props.tone ?? "advis";
  const hue = tone === "caut" ? "var(--alert-caut)"
    : tone === "normal" ? "var(--state-normal)" : "var(--alert-advis)";
  return (
    <button
      onClick={props.onClick} title={props.title} disabled={props.disabled}
      aria-pressed={props.on}
      className="ms-chip"
      style={{
        padding: "6px 11px", minHeight: 32,
        fontSize: "var(--size-label)", fontFamily: "var(--font-ui)",
        letterSpacing: "0.04em",
        borderRadius: "var(--radius)",
        border: "1px solid " + (props.on ? hue : "var(--line)"),
        background: props.on ? "color-mix(in srgb, " + hue + " 16%, transparent)"
                             : "var(--bg-raised)",
        color: props.disabled ? "var(--ink-mute)" : props.on ? hue : "var(--ink-dim)",
        cursor: props.disabled ? "not-allowed" : "pointer",
        whiteSpace: "nowrap",
      }}
    >
      {props.children}
    </button>
  );
}

/* ------------------------------------------------------------------ *
 * Field -- a labelled control
 * ------------------------------------------------------------------ */

export function Field(props: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label style={{ display: "block", minWidth: 0 }}>
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    letterSpacing: "0.09em", marginBottom: 5 }}>
        {props.label.toUpperCase()}
      </div>
      {props.children}
      {props.hint && (
        <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                      marginTop: 4, lineHeight: 1.45 }}>{props.hint}</div>
      )}
    </label>
  );
}

export const inputStyle: CSSProperties = {
  width: "100%", minWidth: 0, minHeight: 36, padding: "7px 10px",
  background: "var(--bg-void)", color: "var(--ink)",
  border: "1px solid var(--line)", borderRadius: "var(--radius)",
  fontSize: "var(--size-body)", fontFamily: "var(--font-ui)",
  transition: "border-color 140ms ease",
};

export const numStyle: CSSProperties = {
  ...inputStyle, fontFamily: "var(--font-num)", textAlign: "right",
};

/* ------------------------------------------------------------------ *
 * Slider -- value on the right, bounds underneath
 * ------------------------------------------------------------------ */

export function Slider(props: {
  label: string; value: number; min: number; max: number; step: number;
  unit: string; onChange: (v: number) => void;
  /** Shown instead of the raw number where the number needs a sign or a word. */
  display?: string;
}) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline", marginBottom: 4 }}>
        <span style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                       letterSpacing: "0.09em" }}>
          {props.label.toUpperCase()}
        </span>
        <span style={{ fontFamily: "var(--font-num)", fontSize: 18, fontWeight: 700 }}>
          {props.display ?? props.value.toLocaleString()}
          <span style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                         marginLeft: 4, fontWeight: 400 }}>{props.unit}</span>
        </span>
      </div>
      <input type="range" aria-label={props.label}
             min={props.min} max={props.max} step={props.step} value={props.value}
             onChange={(e) => props.onChange(Number(e.target.value))}
             style={{ width: "100%", accentColor: "var(--alert-advis)" }} />
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Stat -- a number with its label, for the summary strips
 * ------------------------------------------------------------------ */

export function Stat(props: {
  k: string; v: ReactNode; unit?: string; tone?: string; wide?: boolean;
  title?: string;
}) {
  return (
    <div title={props.title} style={{ minWidth: 0 }}>
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    letterSpacing: "0.07em", whiteSpace: "nowrap",
                    overflow: "hidden", textOverflow: "ellipsis" }}>
        {props.k.toUpperCase()}
      </div>
      <div style={{ fontFamily: props.wide ? "var(--font-ui)" : "var(--font-num)",
                    fontSize: props.wide ? 16 : 19, fontWeight: 600,
                    color: props.tone ?? "var(--ink)", lineHeight: 1.25,
                    whiteSpace: "nowrap", overflow: "hidden",
                    textOverflow: "ellipsis" }}>
        {props.v}
        {props.unit && (
          <span style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                         marginLeft: 3, fontWeight: 400 }}>{props.unit}</span>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Primary action
 * ------------------------------------------------------------------ */

export function PrimaryButton(props: {
  onClick: () => void; disabled?: boolean; busy?: boolean; children: ReactNode;
  tone?: "advis" | "caut";
}) {
  const hue = props.tone === "caut" ? "var(--alert-caut)" : "var(--alert-advis)";
  return (
    <button
      onClick={props.onClick} disabled={props.disabled}
      className="ms-primary"
      style={{
        width: "100%", minHeight: 46, border: "1px solid " + hue,
        borderRadius: "var(--radius)",
        background: props.disabled ? "var(--bg-raised)"
          : "color-mix(in srgb, " + hue + " 18%, var(--bg-raised))",
        color: props.disabled ? "var(--ink-mute)" : hue,
        fontSize: 17, fontWeight: 700, letterSpacing: "0.07em",
        fontFamily: "var(--font-ui)",
        cursor: props.disabled ? "not-allowed" : props.busy ? "wait" : "pointer",
        display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
      }}
    >
      {props.busy && <span className="ms-spin" aria-hidden="true" />}
      {props.children}
    </button>
  );
}

export const ghostButton: CSSProperties = {
  minHeight: 34, padding: "6px 12px", background: "var(--bg-raised)",
  color: "var(--ink-dim)", border: "1px solid var(--line)",
  borderRadius: "var(--radius)", cursor: "pointer",
  fontSize: "var(--size-label)", fontFamily: "var(--font-ui)",
  letterSpacing: "0.04em", transition: "color 140ms ease, border-color 140ms ease",
};

/* ------------------------------------------------------------------ *
 * Empty state -- what to do, rather than a blank rectangle
 * ------------------------------------------------------------------ */

export function Empty(props: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center",
                  justifyContent: "center", height: "100%", minHeight: 120,
                  textAlign: "center", padding: "var(--space-5)", gap: 8 }}>
      {props.icon && <div style={{ color: "var(--ink-mute)", opacity: 0.7 }}>{props.icon}</div>}
      <div style={{ fontSize: 17, color: "var(--ink-dim)", letterSpacing: "0.05em" }}>
        {props.title}
      </div>
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    lineHeight: 1.55, maxWidth: 480 }}>
        {props.children}
      </div>
    </div>
  );
}
