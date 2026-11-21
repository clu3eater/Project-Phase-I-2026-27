/* THE LIVE ENGINE AGAINST ITS TWIN.
 *
 * The certified limit says when a value is dangerous. The twin says what the
 * value SHOULD be right now -- the as-new engine at this rpm, throttle,
 * altitude and air temperature, plus this engine's own build offset. A head
 * running 12 K hotter than its twin is a cooling fault long before it is
 * 135 degC, and that difference is the reason a digital twin exists.
 *
 * Quiet when normal: the expected value and the difference are plain text; a
 * symbol appears only when the difference reaches the thresholds the fault
 * definitions use (thresholds.yaml twin_compare). Before the engine is warm
 * and steady the difference is the operating point, not the engine, so it is
 * shown dim and not graded.
 */

import { type TwinCompare } from "../lib/api";
import { type Level, StatusSymbol } from "../ui/status";

/* Differences in the unit the reading is in. Kelvin is the engineer's
   convention for a temperature difference, but on a console that shows every
   temperature in degC, "+27 K" beside "147 °C" only raises a question. */
const UNIT: Record<string, string> = {
  degC: "°C", psi: "psi", "L/h": "L/h", bar: "bar", "m/s2": "m/s²", V: "V", deg: "°",
};

export function twinLevel(t: TwinCompare | undefined): Level | null {
  if (!t?.graded) return null;
  return t.level === "fault" ? "caution" : t.level === "degraded" ? "advisory" : null;
}

const signed = (v: number, digits = 1) =>
  `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)}`;
const unitOf = (t?: TwinCompare) => UNIT[t?.unit ?? ""] ?? t?.unit ?? "";

/** One line under a strip readout: "twin 116 · +12.0 °C". */
/* The twin is shown in EXACTLY the live reading's terms: the same parameter,
   the same unit, the same number of decimals as the readout above it, so the
   two numbers can be compared at a glance with nothing converted. */
export function TwinLine({ t, digits = 1 }: { t?: TwinCompare; digits?: number }) {
  if (!t?.available || t.expected == null || t.deviation == null) {
    return <span className="t-mute" style={{ fontSize: 16 }}>twin —</span>;
  }
  const l = twinLevel(t);
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center", fontSize: 16, whiteSpace: "nowrap",
                   color: t.graded ? "var(--ink-dim)" : "var(--ink-mute)" }}
          title={t.graded ? "Measured minus what the twin expects now"
            : "Not graded: the engine is not yet warm, loaded and steady"}>
      twin <span className="t-num">{t.expected.toFixed(digits)} {unitOf(t)}</span>
      <span aria-hidden="true">·</span>
      {l && <StatusSymbol level={l} size={12} />}
      <span className="t-num" style={{ color: l ? "var(--ink)" : undefined, fontWeight: l ? 700 : 400 }}>
        {signed(t.deviation, digits)} {unitOf(t)}
      </span>
    </span>
  );
}

/* Every parameter the problem statement lists for health monitoring (PS
   section B), in its order. RPM has no row of its own against the twin: the
   twin RUNS at the measured speed (shadow_model.py), so it has no independent
   opinion of it -- speed is judged against its limits instead, and the table
   says so rather than leaving a gap nobody can explain. Injection timing's twin
   is the FADEC's own command. */
const ROWS: [key: string, name: string, digits: number][] = [
  ["cht_max", "CHT max", 1], ["egt_max", "EGT max", 0],
  ["oil_pressure", "Oil pressure", 1], ["oil_temperature", "Oil temperature", 1],
  ["coolant_temperature", "Coolant temperature", 1], ["fuel_flow", "Fuel flow", 1],
  ["manifold_pressure", "Manifold pressure", 2], ["vibration_rms_total", "Vibration", 2],
  ["bus_voltage", "Battery / alternator bus", 2], ["injection_timing", "Injection timing (worst cylinder)", 1],
];

/** The whole comparison as a table, for the operator in flight. */
export function TwinTable({ twin, reported }: { twin?: Record<string, TwinCompare>; reported: any }) {
  if (!twin) return null;
  const rpm = reported?.rpm?.value;
  return (
    <table className="table">
      <thead>
        <tr><th>Against the twin</th><th className="num">Now</th><th className="num">Twin expects</th>
          <th className="num">Difference</th><th>Reading</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>RPM</td>
          <td className="num">{rpm != null ? `${Math.round(rpm)} rpm` : "—"}</td>
          <td className="num t-dim">Same</td>
          <td className="num t-mute">—</td>
          <td><span className="t-mute" title="The twin runs at the measured speed and predicts everything else from it">
            Twin input</span></td>
        </tr>
        {ROWS.filter(([k]) => k in twin).map(([k, name, dg]) => {
          const t = twin[k];
          const l = twinLevel(t);
          const unit = unitOf(t);
          return (
            <tr key={k}>
              <td>{name}</td>
              <td className="num">{t?.available && t.measured != null ? `${t.measured.toFixed(dg)} ${unit}` : "—"}</td>
              <td className="num t-dim">{t?.available && t.expected != null ? `${t.expected.toFixed(dg)} ${unit}` : "—"}</td>
              <td className="num">{t?.available && t.deviation != null ? `${signed(t.deviation, dg)} ${unit}` : "—"}</td>
              <td>
                {!t?.available ? <span className="t-mute">No twin value</span>
                  : !t.graded ? <span className="t-mute">Settling</span>
                  : l ? <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                      <StatusSymbol level={l} size={12} />
                      {t.level === "fault" ? "Well off the twin" : "Drifting from the twin"}</span>
                  : <span className="t-dim">As expected</span>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
