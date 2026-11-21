/* TEST RIG — the second of the three deployment contexts the PS names.
 *
 * "defence grade Ground Control Station (GCS), engine test rigs, and
 * fleet-level health monitoring infrastructures"
 *
 * A rig is judged differently from the other two. It does not predict a
 * failure in flight; it says whether the engine that just came off the bench
 * meets the numbers on its type certificate. So this is a pass/fail
 * certificate rather than a live display, and every check names the
 * measurement AND the criterion — an acceptance result an engineer cannot
 * audit is one they will not sign.
 */

import React, { useEffect, useState } from "react";

import { KeyValue, Panel } from "../components/Core";
import { fetchRigSchedules, runRig, type Snapshot } from "../lib/api";

/* A test cell is not an aircraft standing still. Modelled as one, a healthy
 * engine reaches 203 C coolant against a 120 C certified limit and would be
 * condemned for a fault it does not have. A real cell has dedicated cooling,
 * so it is stated here as an explicit property of the facility. */
const CELL_PRESETS = [
  { label: "Standard cell", temp: 25, cooling: 200 },
  { label: "Hot day (45 C)", temp: 45, cooling: 200 },
  { label: "Under-cooled cell", temp: 25, cooling: 45 },
];

const SELECT: React.CSSProperties = {
  background: "var(--bg-raised)",
  color: "var(--ink)",
  border: "1px solid var(--line)",
  borderRadius: "var(--radius)",
  padding: "7px 10px",
  fontSize: 16,
  fontFamily: "inherit",
  minWidth: 210,
};

const BUTTON: React.CSSProperties = {
  background: "var(--ref-selected)",
  color: "var(--bg-void)",
  border: "none",
  borderRadius: "var(--radius)",
  padding: "9px 18px",
  fontSize: 16,
  fontWeight: 700,
  letterSpacing: "0.04em",
  fontFamily: "inherit",
};

const TH: React.CSSProperties = { padding: "6px 10px", fontWeight: 600 };
const TD: React.CSSProperties = { padding: "7px 10px" };
const NUM: React.CSSProperties = {
  padding: "7px 10px",
  fontFamily: "var(--font-num)",
};

/* THE SIMULATOR'S TRUTH, FOR VALIDATION ONLY.
 * The wear the simulator actually applied, so a detection can be checked
 * against what was really there. A fielded aircraft has no such numbers and
 * nothing on this console decides on them -- which is why this lives on the
 * engineer's validation page and not among the measurements. */
function GroundTruthPanel({ snap }: { snap?: Snapshot }) {
  const deg: Record<string, number | null> =
    (snap?.twin?.predicted?.degradation_factors as any) ?? {};
  return (
    <Panel title="Simulator ground truth — validation only">
      <div style={{ fontSize: 16, color: "var(--ink-dim)", marginBottom: 8 }}>
        What the simulator applied. Not measured; not used for any decision.
      </div>
      {Object.entries(deg)
        .filter(([, v]) => v !== null)
        .map(([k, v]) => (
          <KeyValue key={k} k={k.replace(/_/g, " ")} v={(v as number).toFixed(3)} />
        ))}
    </Panel>
  );
}

export function TestRigPage({ snap }: { snap?: Snapshot } = {}) {
  const [schedules, setSchedules] = useState<any[]>([]);
  const [schedule, setSchedule] = useState("acceptance");
  const [preset, setPreset] = useState(0);
  const [live, setLive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<any>(null);

  useEffect(() => {
    fetchRigSchedules().then(setSchedules).catch(() => setSchedules([]));
  }, []);

  const chosen = schedules.find((s) => s.key === schedule);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const cell = CELL_PRESETS[preset];
      setReport(
        await runRig({
          schedule,
          cell_temperature_c: cell.temp,
          cell_cooling_kmh: cell.cooling,
          use_live_engine: live,
        }),
      );
    } catch (e: any) {
      setError(e.message ?? String(e));
      setReport(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)",
                  // minHeight 100% so the page claims the height <main>
                  // gives it, and the last panel grows into it. Without
                  // both, these pages sized to their content and left the
                  // rest of a fixed GCS display blank.
                  height: "100%", minHeight: 0 }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.6fr) minmax(0, 1fr)",
                    gap: "var(--gap)", flex: "0 0 auto" }}>
      <Panel title="Ground run">
        <div
          style={{
            fontSize: 16,
            color: "var(--ink-dim)",
            marginBottom: 14,
            maxWidth: 780,
            lineHeight: 1.55,
          }}
        >
          Judged against the type certificate. Set the cell cooling: a bench
          has no ram air, and the report says whether the cell or the engine
          was the limiting factor.
        </div>

        <div
          style={{
            display: "flex",
            gap: 24,
            flexWrap: "wrap",
            alignItems: "flex-end",
          }}
        >
          <label style={{ fontSize: 16 }}>
            <div style={{ color: "var(--ink-dim)", marginBottom: 4 }}>
              Schedule
            </div>
            <select
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              style={SELECT}
            >
              {schedules.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>

          <label style={{ fontSize: 16 }}>
            <div style={{ color: "var(--ink-dim)", marginBottom: 4 }}>
              Test cell
            </div>
            <select
              value={preset}
              onChange={(e) => setPreset(Number(e.target.value))}
              style={SELECT}
            >
              {CELL_PRESETS.map((c, i) => (
                <option key={c.label} value={i}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>

          <label
            style={{
              fontSize: 16,
              display: "flex",
              alignItems: "center",
              gap: 8,
              paddingBottom: 8,
            }}
          >
            <input
              type="checkbox"
              checked={live}
              onChange={(e) => setLive(e.target.checked)}
            />
            <span>Use the engine currently flying</span>
          </label>

          {/* A deliberate action, not a live control: PRD Part 4 section 9
              requires one for anything that changes system state, and a
              ground run takes the better part of a minute. */}
          <button
            onClick={run}
            disabled={busy}
            style={{
              ...BUTTON,
              opacity: busy ? 0.5 : 1,
              cursor: busy ? "wait" : "pointer",
            }}
          >
            {busy ? "RUNNING..." : "RUN GROUND TEST"}
          </button>
        </div>

        {chosen && (
          <div
            style={{ fontSize: 16, color: "var(--ink-dim)", marginTop: 12 }}
          >
            {chosen.description} · {(chosen.duration_s / 60).toFixed(0)} min of
            engine time across {chosen.points.length} points
            {live && " · run against the live engine's current degradation"}
          </div>
        )}

        {error && (
          <div
            style={{
              marginTop: 12,
              color: "var(--alert-warn-ink)",
              fontSize: 16,
            }}
          >
            {/* The rig refuses a schedule that would itself breach a
                time-limited rating, and says so rather than running it. */}
            {error}
          </div>
        )}
      </Panel>
      <GroundTruthPanel snap={snap} />
      </div>

      {report && <RigReport report={report} />}
    </div>
  );
}

function RigReport({ report }: { report: any }) {
  const passed: boolean = report.passed;
  const cellLimited: boolean = report.cell_limited;

  /* A cell that cannot cool has proved nothing about the engine, so the
     verdict distinguishes "this engine failed" from "this test was invalid".
     Telling those apart is the difference between a week spent on a real
     fault and a week wasted. */
  const verdict = cellLimited ? "TEST INVALID" : passed ? "PASS" : "FAIL";
  const colour = cellLimited
    ? "var(--alert-caut)"
    : passed
      ? "var(--state-normal)"
      : "var(--alert-warn)";

  return (
    <>
      <Panel
        title={`${report.schedule} — ${report.engine}`}
        right={
          <span
            style={{
              color: colour,
              fontWeight: 800,
              fontSize: 17,
              letterSpacing: "0.06em",
            }}
          >
            {verdict}
          </span>
        }
      >
        <div
          style={{ fontSize: 16, color: "var(--ink-dim)", marginBottom: 12 }}
        >
          cell {report.cell?.temperature_c} C at {report.cell?.elevation_ft} ft,
          cooling {report.cell?.cooling_kmh_equivalent} km/h-equivalent ·
          engine: {report.engine_source}
        </div>

        {report.checks?.length ? (
          <table
            style={{ width: "100%", borderCollapse: "collapse", fontSize: 16 }}
          >
            <thead>
              <tr style={{ color: "var(--ink-dim)", textAlign: "left" }}>
                <th style={TH}>check</th>
                <th style={TH}>measured</th>
                <th style={TH}>criterion</th>
                <th style={TH} />
              </tr>
            </thead>
            <tbody>
              {report.checks.map((c: any) => (
                <tr key={c.name} style={{ borderTop: "1px solid var(--line)" }}>
                  <td style={TD}>{c.name}</td>
                  <td style={{ ...TD, fontFamily: "var(--font-num)" }}>
                    {c.measured}
                  </td>
                  <td style={{ ...TD, color: "var(--ink-dim)" }}>
                    {c.criterion}
                  </td>
                  <td
                    style={{
                      ...TD,
                      fontWeight: 700,
                      color: c.passed
                        ? "var(--state-normal)"
                        : "var(--alert-warn)",
                    }}
                  >
                    {c.passed ? "PASS" : "FAIL"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ fontSize: 16, color: "var(--alert-caut)" }}>
            No acceptance criteria: an investigation run, not a pass or fail.
          </div>
        )}

        {report.notes?.map((n: string, i: number) => (
          <div
            key={i}
            style={{
              marginTop: 10,
              fontSize: 16,
              color: cellLimited ? "var(--alert-caut)" : "var(--ink-dim)",
            }}
          >
            {n}
          </div>
        ))}
      </Panel>

      <Panel grow title="Recorded points">
        <div style={{ overflowX: "auto" }}>
          <table
            style={{ width: "100%", borderCollapse: "collapse", fontSize: 16 }}
          >
            <thead>
              <tr style={{ color: "var(--ink-dim)", textAlign: "right" }}>
                <th style={{ ...TH, textAlign: "left" }}>point</th>
                <th style={TH}>thr %</th>
                <th style={TH}>rpm</th>
                <th style={TH}>kW</th>
                <th style={TH}>N·m</th>
                <th style={TH}>coolant C</th>
                <th style={TH}>EGT C</th>
                <th style={TH}>EGT split</th>
                <th style={TH}>oil psi</th>
                <th style={{ ...TH, textAlign: "left" }}>exceedances</th>
              </tr>
            </thead>
            <tbody>
              {report.points?.map((p: any) => (
                <tr
                  key={p.name}
                  style={{
                    borderTop: "1px solid var(--line)",
                    textAlign: "right",
                  }}
                >
                  <td style={{ ...TD, textAlign: "left", fontWeight: 600 }}>
                    {p.name}
                    {/* A power reading from a point where the dyno lost the
                        speed is a reading of something else. */}
                    {p.load_saturated && (
                      <span
                        style={{ color: "var(--alert-caut)", fontSize: 16 }}
                      >
                        {" "}
                        · speed not held
                      </span>
                    )}
                  </td>
                  <td style={NUM}>{p.throttle_pct}</td>
                  <td style={NUM}>
                    {p.rpm?.toFixed(0)}
                    {p.target_rpm != null && (
                      <div
                        style={{ fontSize: 16, color: "var(--ink-dim)" }}
                      >
                        target {p.target_rpm.toFixed(0)}
                      </div>
                    )}
                  </td>
                  <td style={NUM}>{p.power_kw?.toFixed(1)}</td>
                  <td style={NUM}>{p.torque_nm?.toFixed(0)}</td>
                  <td style={NUM}>{p.coolant_c?.toFixed(1)}</td>
                  <td style={NUM}>{p.egt_max_c?.toFixed(0)}</td>
                  <td style={NUM}>{p.egt_spread_c?.toFixed(0)}</td>
                  <td style={NUM}>{p.oil_pressure_psi?.toFixed(1)}</td>
                  <td
                    style={{
                      ...TD,
                      textAlign: "left",
                      color: "var(--alert-warn-ink)",
                      fontSize: 16,
                    }}
                  >
                    {p.exceedances?.join("; ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
