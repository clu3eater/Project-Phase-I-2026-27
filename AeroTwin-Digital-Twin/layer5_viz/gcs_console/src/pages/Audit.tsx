/* AUDIT — PRD Part 4 §11, screen 7: "append-only log view (Commander only)".
 *
 * The word that does the work is APPEND-ONLY. A log that is merely appended to
 * is not append-only: anyone who can write the file can rewrite the middle of
 * it. Each entry carries the SHA-256 hash of the entry before it, so altering
 * or deleting any record breaks every hash after it.
 *
 * This screen therefore leads with the integrity verdict, not with the
 * entries. A log presented without evidence that it is intact is just a list
 * of claims, and the operator has no way to tell the difference.
 *
 * AUTHZ_DENY is shown like any other event, and is usually the interesting
 * one: an audit log that records only what succeeded is not an audit log.
 */

import React, { useEffect, useState } from "react";

import { Pager, Panel } from "../components/Core";
import { api } from "../lib/api";

const EVENT_STYLE: Record<string, { colour: string; mark: string }> = {
  AUTH: { colour: "var(--ink)", mark: "●" },
  AUTHZ_DENY: { colour: "var(--alert-caut)", mark: "▲" },
  STATE_MUTATION: { colour: "var(--alert-advis)", mark: "◆" },
  ALERT_GENERATED: { colour: "var(--alert-caut)", mark: "▲" },
  ALERT_ACK: { colour: "var(--ink)", mark: "○" },
  MODEL_UPDATE: { colour: "var(--alert-advis)", mark: "◆" },
  MAINTENANCE_ACTION: { colour: "var(--alert-advis)", mark: "◆" },
  THRESHOLD_CHANGE: { colour: "var(--alert-caut)", mark: "▲" },
  ENGINE_CONFIG: { colour: "var(--alert-advis)", mark: "◆" },
  ENGINE_CHANGE: { colour: "var(--alert-caut)", mark: "▲" },
  USER_ADMIN: { colour: "var(--alert-caut)", mark: "▲" },
};

const TH: React.CSSProperties = {
  padding: "7px 10px",
  fontWeight: 600,
  fontSize: 16,
  color: "var(--ink-dim)",
  textAlign: "left",
};
const TD: React.CSSProperties = { padding: "8px 10px", fontSize: 16 };

export function AuditPage() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  useEffect(() => {
    api("/api/audit")
      .then(async (r) => {
        if (r.status === 403) throw new Error("This view is Commander only.");
        if (!r.ok) throw new Error("audit log unavailable");
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  if (error) {
    return (
      <Panel title="Audit">
        <div style={{ fontSize: 16, color: "var(--alert-caut)" }}>{error}</div>
      </Panel>
    );
  }
  if (!data) {
    return (
      <Panel title="Audit">
        <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>ACQUIRING</div>
      </Panel>
    );
  }

  const ok = data.integrity?.ok;
  const all: any[] = [...(data.entries ?? [])].reverse();
  // Rows per page: what the log panel holds at 1920x1080 without hiding any.
  const PAGE = 12;
  const pages = Math.max(1, Math.ceil(all.length / PAGE));
  const pg = Math.min(page, pages - 1);
  const entries = all.slice(pg * PAGE, pg * PAGE + PAGE);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)",
                  // minHeight 100% so the page claims the height <main>
                  // gives it, and the last panel grows into it. Without
                  // both, these pages sized to their content and left the
                  // rest of a fixed GCS display blank.
                  height: "100%", minHeight: 0 }}>
      {/* The verdict first. An intact chain is a claim that has to be shown to
          have been checked, and a broken one has to be impossible to miss. */}
      <Panel title="Chain integrity">
        <div style={{ display: "flex", gap: 30, alignItems: "baseline", flexWrap: "wrap" }}>
          <span
            style={{
              fontSize: 21,
              fontWeight: 800,
              letterSpacing: "0.06em",
              color: ok ? "var(--ink)" : "var(--alert-warn)",
            }}
          >
            {ok ? "INTACT" : "BROKEN"}
          </span>
          <span style={{ fontSize: 16, color: "var(--ink-dim)" }}>
            {data.integrity?.entries} entries · {data.integrity?.reason}
            {data.integrity?.broken_at != null &&
              ` · first break at entry ${data.integrity.broken_at}`}
          </span>
        </div>
        <div
          style={{
            fontSize: 16,
            color: "var(--ink-mute)",
            marginTop: 14,
            maxWidth: 820,
            lineHeight: 1.5,
          }}
        >
          Hash-chained: altering any record breaks every hash after it.
          Recorded: {(data.events_recorded ?? []).join(", ")}.
        </div>
      </Panel>

      <Panel grow
        title="Log — most recent first"
        right={
          <span style={{ display: "inline-flex", gap: 12, alignItems: "center" }}>
            <span style={{ fontSize: 16, color: "var(--ink-dim)" }}>
              {all.length} entries
            </span>
            <Pager page={pg} pages={pages} onPage={setPage} />
          </span>
        }
      >
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ ...TH, textAlign: "right" }}>seq</th>
                <th style={TH}>time (UTC)</th>
                <th style={TH}>event</th>
                <th style={TH}>subject</th>
                <th style={TH}>role</th>
                <th style={TH}>detail</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => {
                const st = EVENT_STYLE[e.event] ?? {
                  colour: "var(--ink)",
                  mark: "·",
                };
                return (
                  <tr key={e.seq} style={{ borderTop: "1px solid var(--line)" }}>
                    <td
                      style={{
                        ...TD,
                        textAlign: "right",
                        fontFamily: "var(--font-num)",
                        color: "var(--ink-dim)",
                      }}
                    >
                      {e.seq}
                    </td>
                    <td style={{ ...TD, fontFamily: "var(--font-num)" }}>
                      {e.utc?.replace("T", " ").replace("+00:00", "")}
                    </td>
                    {/* Glyph AND word, never colour alone (§14). */}
                    <td style={{ ...TD, color: st.colour, fontWeight: 600 }}>
                      {st.mark} {e.event}
                    </td>
                    <td style={TD}>{e.subject}</td>
                    <td style={{ ...TD, color: "var(--ink-dim)" }}>{e.role}</td>
                    <td style={{ ...TD, color: "var(--ink-dim)" }}>
                      {Object.entries(e.detail ?? {})
                        .map(([k, v]) => `${k}=${v}`)
                        .join("  ") || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
