/* MISSION SCENARIOS — problem statement section E.
 *
 *   "Engine behavior simulation during: High Altitude / Endurance mission /
 *    Hot-weather operation / Rapid throttle transitions"
 *
 * The environments were always modelled and the physics could always be run in
 * them; what was missing was a way to actually run one and get an ANSWER. A
 * scenario that produces a trace and no verdict leaves the analysis to the
 * reader, and the reader is the person who asked the question.
 *
 * So each run leads with what LIMITED the engine — the parameter that came
 * closest to its certified limit — because "what stops this aircraft flying
 * this mission" is the question actually being asked.
 */

import React, { useEffect, useState } from "react";

import { Panel } from "../components/Core";
import { api } from "../lib/api";

const TH: React.CSSProperties = {
  padding: "7px 10px",
  fontWeight: 600,
  fontSize: 16,
  color: "var(--ink-dim)",
  textAlign: "left",
};
const TD: React.CSSProperties = { padding: "8px 10px", fontSize: 16 };
const NUM: React.CSSProperties = {
  ...TD,
  fontFamily: "var(--font-num)",
  textAlign: "right",
};

/* ------------------------------------------------------------------------ *
 * Custom environment -- PS section E, "Environmental condition simulation".
 *
 * The four named cases answer that requirement for four points. This answers
 * it for any point inside the envelope the physics is validated in, which is
 * what an engineer actually asks: "can it hold this, here, on a day like this".
 *
 * The slider bounds ARE the validated envelope, and the server enforces the
 * same numbers. A control that lets an operator dial in 40,000 ft would get a
 * confident answer from a model with no standing to give one.
 * ------------------------------------------------------------------------ */

function Slider(props: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  onChange: (v: number) => void;
}) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "baseline", marginBottom: 6,
      }}>
        <span style={{
          fontSize: "var(--size-label)", color: "var(--ink-mute)",
          letterSpacing: "0.09em",
        }}>
          {props.label}
        </span>
        <span style={{
          fontFamily: "var(--font-num)", fontSize: 19, fontWeight: 700,
        }}>
          {props.value.toLocaleString()}
          <span style={{
            fontSize: "var(--size-label)", color: "var(--ink-dim)",
            marginLeft: 4,
          }}>
            {props.unit}
          </span>
        </span>
      </div>
      <input
        type="range"
        aria-label={props.label}
        min={props.min} max={props.max} step={props.step}
        value={props.value}
        onChange={(e) => props.onChange(Number(e.target.value))}
        style={{ width: "100%", accentColor: "var(--alert-advis)" }}
      />
      <div style={{
        display: "flex", justifyContent: "space-between",
        fontSize: "var(--size-label)", color: "var(--ink-mute)", marginTop: 2,
      }}>
        <span>{props.min.toLocaleString()}</span>
        <span>{props.max.toLocaleString()}</span>
      </div>
    </div>
  );
}

/* Presets are the ENV_PROFILES the physics already defines, so choosing one
   lands on the same conditions the named scenarios use rather than on numbers
   invented for the control. */
const PRESETS: { name: string; alt: number; oat: number; spd: number }[] = [
  { name: "ISA standard", alt: 15000, oat: -15, spd: 180 },
  { name: "High altitude", alt: 25000, oat: -35, spd: 200 },
  { name: "Hot weather", alt: 6000, oat: 45, spd: 135 },
  { name: "Cold weather", alt: 10000, oat: -30, spd: 170 },
];

function CustomEnvironment() {
  const [alt, setAlt] = useState(15000);
  const [oat, setOat] = useState(-15);
  const [spd, setSpd] = useState(180);
  const [thr, setThr] = useState(75);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const elapsed = useElapsed(busy);

  const run = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      const r = await api("/api/scenarios/custom", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          altitude_ft: alt, oat_c: oat, airspeed_kmh: spd,
          throttle_pct: thr, duration_s: 600,
        }),
      });
      if (!r.ok) {
        const e = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(e.detail ?? "run failed");
      }
      setResult(await r.json());
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Panel title="Environmental conditions">
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
          gap: 24, marginBottom: 18,
        }}>
          <Slider label="ALTITUDE" value={alt} min={0} max={25000} step={500}
                  unit="ft" onChange={setAlt} />
          <Slider label="AMBIENT TEMPERATURE" value={oat} min={-60} max={60}
                  step={1} unit="°C" onChange={setOat} />
          <Slider label="AIRSPEED" value={spd} min={80} max={250} step={5}
                  unit="km/h" onChange={setSpd} />
          <Slider label="THROTTLE" value={thr} min={20} max={100} step={1}
                  unit="%" onChange={setThr} />
        </div>

        <div style={{
          display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center",
        }}>
          <span style={{
            fontSize: "var(--size-label)", color: "var(--ink-mute)",
            letterSpacing: "0.09em", marginRight: 4,
          }}>
            PRESETS
          </span>
          {PRESETS.map((p) => (
            <button
              key={p.name}
              onClick={() => { setAlt(p.alt); setOat(p.oat); setSpd(p.spd); }}
              style={{
                background: "transparent", color: "var(--ink-dim)",
                border: "1px solid var(--line)", borderRadius: "var(--radius)",
                padding: "7px 13px", fontSize: 16, fontFamily: "inherit",
                cursor: "pointer", minHeight: 38,
              }}
            >
              {p.name}
            </button>
          ))}
          <div style={{ flex: 1 }} />
          {error && (
            <span style={{ fontSize: 16, color: "var(--alert-caut)" }}>
              {error}
            </span>
          )}
          <button
            onClick={run}
            disabled={busy}
            style={{
              background: "var(--ref-selected)", color: "var(--bg-void)",
              border: "none", borderRadius: "var(--radius)",
              padding: "10px 18px", fontSize: 16, fontWeight: 700,
              letterSpacing: "0.04em", fontFamily: "inherit",
              cursor: busy ? "wait" : "pointer", height: 42,
            }}
          >
            {busy ? `HOLDING ${elapsed.toFixed(0)}s` : "HOLD THIS POINT"}
          </button>
        </div>

        <div style={{
          fontSize: 16, color: "var(--ink-mute)", marginTop: 14,
        }}>
          Held for ten simulated minutes, long enough for the thermal states to
          settle. Takes about fifteen seconds to compute.
        </div>
      </Panel>

      {result && <ScenarioResult r={result} />}
    </>
  );
}

/* A run takes between twelve and fifty seconds of real physics, and a control
 * that sits silent for that long is indistinguishable from a broken one -- the
 * operator's next move is to press it again. So the wait is made VISIBLE two
 * ways: the expected cost is shown before the press, and the elapsed count runs
 * during it. Neither is a progress bar, because the server does not report
 * progress and a bar that advances on a timer is a lie about how far along the
 * work is. */
function useElapsed(running: boolean) {
  const [t, setT] = useState(0);
  useEffect(() => {
    if (!running) { setT(0); return; }
    const started = Date.now();
    const id = setInterval(() => setT((Date.now() - started) / 1000), 250);
    return () => clearInterval(id);
  }, [running]);
  return t;
}

export function ScenariosPage() {
  const [list, setList] = useState<any[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const elapsed = useElapsed(busy !== null);

  useEffect(() => {
    api("/api/scenarios")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("unavailable"))))
      .then(setList)
      .catch(() => setError("scenarios unavailable"));
  }, []);

  const run = async (key: string) => {
    setBusy(key);
    setError(null);
    setResult(null);
    try {
      const r = await api(`/api/scenarios/${key}`, { method: "POST" });
      if (!r.ok) throw new Error("scenario failed");
      setResult(await r.json());
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)" }}>
      <Panel title="Engine behaviour under mission and environmental conditions">
        <div
          style={{
            fontSize: 16,
            color: "var(--ink-dim)",
            marginBottom: 16,
            maxWidth: 820,
            lineHeight: 1.55,
          }}
        >
          Each case is judged against the type certificate. The verdict names
          the limiting parameter.
        </div>

        {error && (
          <div style={{ fontSize: 16, color: "var(--alert-caut)" }}>{error}</div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {list.map((s) => (
            <div
              key={s.key}
              style={{
                display: "grid",
                gridTemplateColumns: "230px 1fr 180px",
                gap: 14,
                alignItems: "start",
                padding: "12px 14px",
                background: "var(--bg-raised)",
                borderRadius: "var(--radius)",
              }}
            >
              <div>
                <div style={{ fontWeight: 700, fontSize: 16 }}>{s.name}</div>
                <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>
                  {(s.duration_s / 60).toFixed(0)} min flown · {s.phases} phases
                </div>
                {s.compute_s != null && (
                  <div style={{ fontSize: 16, color: "var(--ink-mute)" }}>
                    ~{Math.round(s.compute_s)} s to compute
                  </div>
                )}
              </div>
              {/* What the scenario is actually testing, so the result can be
                  read against an intention rather than in isolation. */}
              <div
                style={{
                  fontSize: 16,
                  color: "var(--ink-dim)",
                  lineHeight: 1.5,
                }}
              >
                {s.question}
              </div>
              <button
                onClick={() => run(s.key)}
                disabled={busy !== null}
                style={{
                  background: "var(--ref-selected)",
                  color: "var(--bg-void)",
                  border: "none",
                  borderRadius: "var(--radius)",
                  padding: "9px 14px",
                  fontSize: 16,
                  fontWeight: 700,
                  letterSpacing: "0.04em",
                  fontFamily: "inherit",
                  cursor: busy ? "wait" : "pointer",
                  opacity: busy && busy !== s.key ? 0.4 : 1,
                  height: 42,
                }}
              >
                {busy === s.key ? `FLYING ${elapsed.toFixed(0)}s` : "RUN"}
              </button>
            </div>
          ))}
        </div>
      </Panel>

      {result && <ScenarioResult r={result} />}

      <CustomEnvironment />
    </div>
  );
}

function ScenarioResult({ r }: { r: any }) {
  const failed = (r.exceedances ?? []).length > 0;

  return (
    <>
      <Panel
        title={`${r.name} — verdict`}
        right={
          <span
            style={{
              fontWeight: 800,
              fontSize: 17,
              letterSpacing: "0.06em",
              color: failed ? "var(--alert-caut)" : "var(--ink)",
            }}
          >
            {failed ? "OUTSIDE LIMITS" : "WITHIN LIMITS"}
          </span>
        }
      >
        <div style={{ fontSize: 16, marginBottom: 14 }}>
          Limiting parameter:{" "}
          <span style={{ fontWeight: 700 }}>{r.limiting}</span>
          {r.limiting_margin_pct != null && (
            <span style={{ color: "var(--ink-dim)" }}>
              {" "}
              — {r.limiting_margin_pct.toFixed(1)}% margin remaining
            </span>
          )}
        </div>

        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={TH}>limited parameter</th>
              <th style={{ ...TH, textAlign: "right" }}>worst reached</th>
              <th style={{ ...TH, textAlign: "right" }}>certified limit</th>
              <th style={{ ...TH, textAlign: "right" }}>margin</th>
              <th style={TH} />
            </tr>
          </thead>
          <tbody>
            {(r.limits ?? []).map((l: any) => (
              <tr key={l.name} style={{ borderTop: "1px solid var(--line)" }}>
                <td style={TD}>{l.name}</td>
                <td style={NUM}>
                  {l.worst} {l.unit}
                </td>
                <td style={NUM}>
                  {l.limit} {l.unit}
                </td>
                <td
                  style={{
                    ...NUM,
                    color: l.exceeded ? "var(--alert-caut)" : "var(--ink)",
                  }}
                >
                  {l.margin_pct > 0 ? "+" : ""}
                  {l.margin_pct}%
                </td>
                {/* Word as well as colour (§14). */}
                <td
                  style={{
                    ...TD,
                    fontWeight: 700,
                    color: l.exceeded ? "var(--alert-caut)" : "var(--ink-dim)",
                  }}
                >
                  {l.exceeded ? "EXCEEDED" : "ok"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {r.exceedances?.map((e: string, i: number) => (
          <div
            key={i}
            style={{ marginTop: 10, fontSize: 16, color: "var(--alert-caut)" }}
          >
            {e}
          </div>
        ))}

        <div
          style={{
            fontSize: 16,
            color: "var(--ink-mute)",
            marginTop: 14,
            maxWidth: 820,
            lineHeight: 1.5,
          }}
        >
          {r.question}
        </div>
      </Panel>

      <Panel title="Recorded trace">
        <div style={{ overflowX: "auto", maxHeight: 420, overflowY: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={TH}>phase</th>
                <th style={{ ...TH, textAlign: "right" }}>t (s)</th>
                <th style={{ ...TH, textAlign: "right" }}>alt ft</th>
                <th style={{ ...TH, textAlign: "right" }}>OAT C</th>
                <th style={{ ...TH, textAlign: "right" }}>thr %</th>
                <th style={{ ...TH, textAlign: "right" }}>rpm</th>
                <th style={{ ...TH, textAlign: "right" }}>CHT</th>
                <th style={{ ...TH, textAlign: "right" }}>coolant</th>
                <th style={{ ...TH, textAlign: "right" }}>EGT</th>
                <th style={{ ...TH, textAlign: "right" }}>oil C</th>
                <th style={{ ...TH, textAlign: "right" }}>oil bar</th>
              </tr>
            </thead>
            <tbody>
              {(r.samples ?? [])
                .filter((_: any, i: number) => i % 4 === 0)
                .map((s: any, i: number) => (
                  <tr key={i} style={{ borderTop: "1px solid var(--line)" }}>
                    <td style={TD}>{s.phase}</td>
                    <td style={NUM}>{s.t_s}</td>
                    <td style={NUM}>{s.altitude_ft}</td>
                    <td style={NUM}>{s.oat_c}</td>
                    <td style={NUM}>{s.throttle_pct}</td>
                    <td style={NUM}>{s.rpm}</td>
                    <td style={NUM}>{s.cht_max}</td>
                    <td style={NUM}>{s.coolant}</td>
                    <td style={NUM}>{s.egt_max}</td>
                    <td style={NUM}>{s.oil_temperature}</td>
                    <td style={NUM}>{s.oil_pressure_bar}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
