/* FLEET — PRD Part 4 §11, screen 6: "twin roster sorted by RUL ascending,
 * readiness summary". The third of the three deployment contexts the problem
 * statement names.
 *
 * A GCS asks how THIS engine is. A fleet asks which engine to work on first,
 * and how many aircraft can fly on Thursday. Those are scheduling questions,
 * so this is a roster ordered by urgency rather than a wall of gauges.
 *
 * Design rules this page is bound by:
 *   §11 screen 6  — sorted by RUL ascending. A planner reads top-down and
 *                   stops when the day is full; any other order puts the
 *                   engine that can wait above the one that cannot.
 *   §7.4a         — every RUL carries its interval. A bare RUL is forbidden.
 *   §14           — no colour-only status. Every readiness band carries a
 *                   WORD, so the roster reads identically in monochrome and
 *                   to an operator with a colour-vision deficiency.
 *   §14           — no emoji, no pills, no gradients, nothing below 16 px.
 */

import React, { useEffect, useState } from "react";

import { Pager, Panel } from "../components/Core";
// `api` and not bare fetch: the browser attaches no Authorization
// header on its own, so a raw fetch reaches the server anonymous and
// comes back "authentication required" -- which reads to the operator
// as a broken page rather than as a missing token.
import { api } from "../lib/api";

interface FleetEngine {
  engine_id: number;
  tail: string;
  flight_hours: number;
  hours_to_tbo: number;
  chi: number | null;
  rul_hours: number | null;
  rul_lower: number | null;
  rul_upper: number | null;
  status: string;
  limiting_subsystem: string;
  limiting_value: number | null;
  faults: string[];
  censored: boolean;
}

/* Readiness bands. The colour is redundant with the word, never a substitute
 * for it. Amber and red stay reserved for their alerting meanings (§3.3a), so
 * AVAILABLE is deliberately NOT green — green means "system on and normal",
 * and a roster row is not an annunciator. */
const STATUS_STYLE: Record<string, { colour: string; mark: string }> = {
  GROUNDED: { colour: "var(--alert-warn)", mark: "▮▮▮" },
  "MAINTENANCE DUE": { colour: "var(--alert-caut)", mark: "▮▮" },
  MONITOR: { colour: "var(--alert-advis)", mark: "▮" },
  AVAILABLE: { colour: "var(--ink)", mark: "" },
  UNKNOWN: { colour: "var(--ink-mute)", mark: "?" },
};

const TH: React.CSSProperties = {
  padding: "7px 10px",
  fontWeight: 600,
  fontSize: 16,
  color: "var(--ink-dim)",
};
const TD: React.CSSProperties = { padding: "8px 10px", fontSize: 16 };
const NUM: React.CSSProperties = {
  ...TD,
  fontFamily: "var(--font-num)",
  textAlign: "right",
};

export function FleetPage() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("ALL");
  const [page, setPage] = useState(0);
  // A new filter starts at the top of its list.
  useEffect(() => setPage(0), [filter]);

  useEffect(() => {
    api("/api/fleet")
      .then(async (r) => {
        if (!r.ok) {
          const e = await r.json().catch(() => ({ detail: r.statusText }));
          throw new Error(e.detail ?? "fleet unavailable");
        }
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  if (error) {
    return (
      <Panel title="Fleet">
        <div style={{ fontSize: 16, color: "var(--alert-caut)" }}>{error}</div>
      </Panel>
    );
  }
  if (!data) {
    /* A static ACQUIRING state, not a shimmer loader (§14, §8.1b). */
    return (
      <Panel title="Fleet">
        <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>ACQUIRING</div>
      </Panel>
    );
  }

  const s = data.summary;
  const engines: FleetEngine[] = data.engines;
  const matching =
    filter === "ALL" ? engines : engines.filter((e) => e.status === filter);
  // Rows per page: what the roster panel holds at 1920x1080 without hiding any.
  const PAGE = 8;
  const pages = Math.max(1, Math.ceil(matching.length / PAGE));
  const pg = Math.min(page, pages - 1);
  const shown = matching.slice(pg * PAGE, pg * PAGE + PAGE);

  const bands = ["GROUNDED", "MAINTENANCE DUE", "MONITOR", "AVAILABLE"];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)",
                  // minHeight 100% so the page claims the height <main>
                  // gives it, and the last panel grows into it. Without
                  // both, these pages sized to their content and left the
                  // rest of a fixed GCS display blank.
                  height: "100%", minHeight: 0 }}>
      <Panel
        title="Readiness"
        right={
          <span style={{ fontSize: 16, color: "var(--ink-dim)" }}>
            {s.total} engines
          </span>
        }
      >
        <div
          style={{
            display: "flex",
            gap: 32,
            flexWrap: "wrap",
            alignItems: "flex-start",
          }}
        >
          <div>
            <div
              style={{
                fontFamily: "var(--font-num)",
                fontSize: 32,
                fontWeight: 700,
                lineHeight: 1.1,
              }}
            >
              {s.mission_capable_pct}%
            </div>
            <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>
              mission capable ({s.mission_capable} of {s.total})
            </div>
          </div>

          {bands.map((b) => {
            const n = s.by_status?.[b] ?? 0;
            const st = STATUS_STYLE[b];
            return (
              <button
                key={b}
                onClick={() => setFilter(filter === b ? "ALL" : b)}
                style={{
                  background:
                    filter === b ? "var(--bg-raised)" : "transparent",
                  border: `1px solid ${
                    filter === b ? "var(--ink-dim)" : "var(--line)"
                  }`,
                  borderRadius: "var(--radius)",
                  padding: "8px 14px",
                  cursor: "pointer",
                  fontFamily: "inherit",
                  textAlign: "left",
                  color: "var(--ink)",
                }}
              >
                <div
                  style={{
                    fontFamily: "var(--font-num)",
                    fontSize: 20,
                    fontWeight: 700,
                    color: st.colour,
                  }}
                >
                  {n}
                </div>
                {/* The word, not just the colour (§14). */}
                <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>
                  {st.mark ? `${st.mark} ` : ""}
                  {b}
                </div>
              </button>
            );
          })}

          <div>
            <div
              style={{
                fontFamily: "var(--font-num)",
                fontSize: 20,
                fontWeight: 700,
              }}
            >
              {s.median_rul_hours ?? "—"} h
            </div>
            <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>
              median remaining life
            </div>
          </div>
        </div>

        {/* Provenance, stated rather than implied. This is a recorded fleet,
            not a live feed of a hundred aircraft, and the console says so. */}
        <div
          style={{
            fontSize: 16,
            color: "var(--ink-mute)",
            marginTop: 16,
            maxWidth: 820,
            lineHeight: 1.5,
          }}
        >
          {data.source}
        </div>
      </Panel>

      <Panel grow
        title="Roster — ordered by remaining life, soonest first"
        right={
          <span style={{ display: "inline-flex", gap: 12, alignItems: "center" }}>
          <Pager page={pg} pages={pages} onPage={setPage} />
          {filter !== "ALL" ? (
            <button
              onClick={() => setFilter("ALL")}
              style={{
                background: "transparent",
                border: "1px solid var(--line)",
                borderRadius: "var(--radius)",
                color: "var(--ink-dim)",
                padding: "4px 10px",
                fontSize: 16,
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              SHOWING {filter} — CLEAR
            </button>
          ) : null}
          </span>
        }
      >
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ ...TH, textAlign: "left" }}>tail</th>
                <th style={{ ...TH, textAlign: "left" }}>status</th>
                <th style={{ ...TH, textAlign: "right" }}>
                  remaining life
                  <div style={{ fontSize: 16, fontWeight: 400 }}>
                    95% interval
                  </div>
                </th>
                <th style={{ ...TH, textAlign: "right" }}>CHI</th>
                <th style={{ ...TH, textAlign: "right" }}>hours</th>
                <th style={{ ...TH, textAlign: "right" }}>to TBO</th>
                <th style={{ ...TH, textAlign: "left" }}>limiting</th>
                <th style={{ ...TH, textAlign: "left" }}>faults present</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((e) => {
                const st = STATUS_STYLE[e.status] ?? STATUS_STYLE.UNKNOWN;
                return (
                  <tr
                    key={e.engine_id}
                    style={{ borderTop: "1px solid var(--line)" }}
                  >
                    <td style={{ ...TD, fontWeight: 600 }}>{e.tail}</td>
                    <td style={{ ...TD, color: st.colour, fontWeight: 700 }}>
                      {st.mark ? `${st.mark} ` : ""}
                      {e.status}
                    </td>
                    <td style={NUM}>
                      {/* AT OR PAST THE MAINTENANCE POINT, SAID IN WORDS.
                          Printed as numbers this read "0 h" over "0 – 0" --
                          a zero-width interval that looked like a broken
                          estimate rather than an engine already due. */}
                      {e.rul_hours != null && e.rul_hours <= 0
                        ? <span style={{ color: "var(--alert-caut)", fontWeight: 700 }}>OVERDUE</span>
                        : e.rul_hours != null ? `${e.rul_hours} h` : "— — —"}
                      {/* §7.4a: the interval is not optional. */}
                      {e.rul_lower != null && e.rul_upper != null
                        && !(e.rul_hours != null && e.rul_hours <= 0) && (
                        <div
                          style={{ fontSize: 16, color: "var(--ink-dim)" }}
                        >
                          {e.rul_lower} – {e.rul_upper}
                        </div>
                      )}
                    </td>
                    <td style={NUM}>{e.chi != null ? e.chi.toFixed(3) : "— — —"}</td>
                    <td style={NUM}>{e.flight_hours}</td>
                    <td style={NUM}>{e.hours_to_tbo}</td>
                    <td style={TD}>
                      {e.limiting_subsystem || "—"}
                      {e.limiting_value != null && (
                        <span style={{ color: "var(--ink-dim)" }}>
                          {" "}
                          {e.limiting_value.toFixed(2)}
                        </span>
                      )}
                    </td>
                    <td style={{ ...TD, color: "var(--ink-dim)" }}>
                      {e.faults.length
                        ? e.faults.map((f) => f.replace(/_/g, " ")).join(", ")
                        : "none"}
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
