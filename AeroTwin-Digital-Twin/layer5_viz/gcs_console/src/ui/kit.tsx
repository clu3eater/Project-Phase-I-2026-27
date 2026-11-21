/* The console's building blocks -- docs/UX_REDESIGN.md section 7.
 *
 * Every screen is built from these, so it looks and behaves the same way
 * wherever a person meets it: one filled primary action per view, secondary
 * tasks in a drawer that never covers the status bar or the engine strip,
 * two-step confirmation for commands that move an aircraft or an engine,
 * and an empty state that is one quiet line instead of a panel of blanks.
 */

import React, { Component, useEffect, useRef, useState } from "react";

import { type Level, Status } from "./status";

// ---------------------------------------------------------------- buttons

type Kind = "primary" | "secondary" | "quiet";

export function Button(props: {
  kind?: Kind; large?: boolean; disabled?: boolean; onClick?: () => void;
  children: React.ReactNode; title?: string; type?: "button" | "submit";
  ariaLabel?: string;
  ariaExpanded?: boolean; ariaControls?: string;
}) {
  const cls = ["btn", props.kind === "primary" ? "btn-primary"
    : props.kind === "quiet" ? "btn-quiet" : "", props.large ? "btn-lg" : ""]
    .filter(Boolean).join(" ");
  return (
    <button type={props.type ?? "button"} className={cls} disabled={props.disabled}
            onClick={props.onClick} title={props.title} aria-label={props.ariaLabel}
            aria-expanded={props.ariaExpanded} aria-controls={props.ariaControls}>
      {props.children}
    </button>
  );
}

/** A command that moves an aircraft or an engine: first press arms it for
 *  four seconds, the second carries it out (Part 4 s9.2). No pop-up. */
export function ConfirmButton(props: {
  label: string; confirmLabel?: string; kind?: Kind; large?: boolean;
  disabled?: boolean; onConfirm: () => void | Promise<void>;
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = window.setTimeout(() => setArmed(false), 4000);
    return () => window.clearTimeout(t);
  }, [armed]);
  const cls = ["btn", armed ? "btn-armed" : props.kind === "primary" ? "btn-primary"
    : props.kind === "quiet" ? "btn-quiet" : "", props.large ? "btn-lg" : ""]
    .filter(Boolean).join(" ");
  return (
    <button type="button" className={cls} disabled={props.disabled || busy}
            onClick={async () => {
              if (!armed) { setArmed(true); return; }
              setArmed(false); setBusy(true);
              try { await props.onConfirm(); } finally { setBusy(false); }
            }}>
      {busy ? "Working…" : armed ? (props.confirmLabel ?? `Confirm: ${props.label}`) : props.label}
    </button>
  );
}

// ---------------------------------------------------------------- frame

export interface Tab { id: string; label: string; count?: number | null }

/** A workspace page: title, one line of context, actions, tabs, body. */
export function Workspace(props: {
  title: string; sub?: React.ReactNode; actions?: React.ReactNode;
  tabs?: Tab[]; tab?: string; onTab?: (id: string) => void;
  fixed?: boolean; children: React.ReactNode;
  /* One row: the views as tabs (or the title, for a single view) with the
     context line at its right. For the detailed pages, which need every
     pixel of height and are already named by the workspace tab above. */
  compact?: boolean;
}) {
  if (props.compact) {
    return (
      <div className="ws">
        <div className="ws-bar">
          {props.tabs && props.tabs.length > 1 ? (
            <div role="tablist" style={{ display: "flex", gap: 4, overflowX: "auto" }}>
              {props.tabs.map((t) => (
                <button key={t.id} role="tab" className="tab" aria-selected={t.id === props.tab}
                        onClick={() => props.onTab?.(t.id)}>{t.label}</button>
              ))}
            </div>
          ) : <div className="t-section" style={{ padding: "0 4px 10px" }}>{props.title}</div>}
          <div style={{ flex: 1 }} />
          {props.sub && <div className="ws-sub ellipsis" style={{ padding: "0 4px 10px", margin: 0 }}>{props.sub}</div>}
        </div>
        <div className={props.fixed ? "ws-body-fixed" : "ws-body"}>{props.children}</div>
      </div>
    );
  }
  return (
    <div className="ws">
      <div className="ws-head">
        <div className="ws-head-text">
          <div className="t-title">{props.title}</div>
          {props.sub && <div className="ws-sub">{props.sub}</div>}
        </div>
        {props.actions && <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {props.actions}</div>}
      </div>
      {props.tabs && props.tabs.length > 1 && (
        <div className="tabs" role="tablist">
          {props.tabs.map((t) => (
            <button key={t.id} role="tab" className="tab" aria-selected={t.id === props.tab}
                    onClick={() => props.onTab?.(t.id)}>
              {t.label}{t.count ? <span className="count">{t.count}</span> : null}
            </button>
          ))}
        </div>
      )}
      <div className={props.fixed ? "ws-body-fixed" : "ws-body"}>{props.children}</div>
    </div>
  );
}

export function Section(props: {
  title?: React.ReactNode; right?: React.ReactNode; children: React.ReactNode;
  flat?: boolean; style?: React.CSSProperties;
}) {
  return (
    <section className={props.flat ? "card-flat" : "card"} style={props.style}>
      {(props.title || props.right) && (
        <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                      marginBottom: 12, flexWrap: "wrap" }}>
          <div className="t-section" style={{ flex: 1 }}>{props.title}</div>
          {props.right}
        </div>
      )}
      {props.children}
    </section>
  );
}

// ---------------------------------------------------------------- drawer

/** Secondary work slides over the WORK AREA only (Part 4 s6.2d). */
export function Drawer(props: {
  open: boolean; title: string; sub?: React.ReactNode; onClose: () => void;
  footer?: React.ReactNode; children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!props.open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") props.onClose(); };
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, select, textarea, button")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [props.open]);
  if (!props.open) return null;
  return (
    <>
      <div className="drawer-scrim" onClick={props.onClose} />
      <aside className="drawer" role="dialog" aria-label={props.title} ref={ref}>
        <div className="drawer-head">
          <div style={{ flex: 1 }}>
            <div className="t-title">{props.title}</div>
            {props.sub && <div className="ws-sub">{props.sub}</div>}
          </div>
          <Button kind="quiet" onClick={props.onClose} ariaLabel="Close">Close</Button>
        </div>
        <div className="drawer-body">{props.children}</div>
        {props.footer && <div className="drawer-foot">{props.footer}</div>}
      </aside>
    </>
  );
}

// ---------------------------------------------------------------- forms

export function Field(props: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span>{props.label}</span>
      {props.children}
      {props.hint && <em className="t-mute" style={{ fontStyle: "normal" }}>{props.hint}</em>}
    </label>
  );
}

// ---------------------------------------------------------------- feedback

/** The outcome of an action, stated where it was taken. Stays until the
 *  next action: nothing self-dismisses (Part 4 s14). */
export function Result({ msg }: { msg: { ok: boolean; text: string } | null }) {
  if (!msg) return null;
  return (
    <div role="status" className="well" style={{ display: "flex", gap: 10,
                                                 alignItems: "flex-start" }}>
      <Status level={msg.ok ? "normal" : "caution"} text={msg.ok ? "Done" : "Not done"} />
      <span style={{ flex: 1 }}>{msg.text}</span>
    </div>
  );
}

export function Callout(props: { level: Level; title: string; children?: React.ReactNode }) {
  return (
    <div className="well" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <Status level={props.level} text={props.title} />
      {props.children && <div className="t-body">{props.children}</div>}
    </div>
  );
}

export function Empty(props: { children: React.ReactNode }) {
  return <div className="t-body t-mute" style={{ padding: "8px 0" }}>{props.children}</div>;
}

// ---------------------------------------------------------------- time

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const two = (n: number) => String(n).padStart(2, "0");

/** One way of writing a time everywhere: "25 Sep 11:11Z". Always UTC, always
 *  marked Z, because a squadron runs on one clock whatever the browser's is. */
export function utc(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s.endsWith("Z") || /[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`);
  if (Number.isNaN(d.getTime())) return s;
  return `${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())}Z`;
}

// ---------------------------------------------------------------- stepper

export function Stepper({ steps, at }: { steps: string[]; at: number }) {
  return (
    <div className="stepper" aria-label="progress">
      {steps.map((s, i) => (
        <React.Fragment key={s}>
          {i > 0 && <span className={`step-line${i <= at ? " done" : ""}`} />}
          <span className={`step ${i < at ? "step-done" : i === at ? "step-now" : ""}`}
                aria-current={i === at ? "step" : undefined}>
            <span className="step-dot">{i + 1}</span>{s}
          </span>
        </React.Fragment>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- stats

/** A labelled figure. Secondary size (22 px); the engine strip carries the
 *  30 px primary readouts (Part 4 s5.1). */
export function Stat(props: { label: string; value: React.ReactNode; unit?: string;
                              sub?: React.ReactNode; colour?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div className="t-label">{props.label}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 4 }}>
        <span style={{ fontFamily: "var(--font-num)", fontSize: 22, fontWeight: 600,
                       color: props.colour ?? "var(--ink)" }}>{props.value}</span>
        {props.unit && <span className="t-dim">{props.unit}</span>}
      </div>
      {props.sub && <div className="t-mute" style={{ fontSize: 16, marginTop: 2 }}>{props.sub}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- safety net

/** One page failing must never blank the console. The HEALTH page did, for
 *  every role, whenever the aircraft was parked -- one null reached toFixed
 *  and React unmounted the status bar, the engine strip and the alerts with
 *  it. Now the page shows this, and everything around it keeps running. */
export class PageBoundary extends Component<{ name: string; children: React.ReactNode },
                                            { error: string | null }> {
  state = { error: null as string | null };
  static getDerivedStateFromError(e: unknown) {
    return { error: e instanceof Error ? e.message : String(e) };
  }
  componentDidUpdate(prev: { name: string }) {
    if (prev.name !== this.props.name && this.state.error) this.setState({ error: null });
  }
  render() {
    if (this.state.error) {
      return (
        <div className="card" style={{ margin: 16 }}>
          <Status level="caution" text={`${this.props.name} could not be shown`} />
          <div className="t-body t-dim" style={{ marginTop: 8 }}>
            The rest of the console is unaffected. Details: {this.state.error}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
