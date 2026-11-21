/* FAULT INJECTION -- the engineer's test bench on the live engine.
 *
 * A fault is injected into the running physics; nothing is faked at the
 * display, so everything downstream -- detection, health, alerts, the
 * advisory, the checklists -- responds exactly as it would to the real thing.
 * That is why this page belongs to the engineer and to nobody who flies.
 *
 * Laid out as a list rather than a wall of equal buttons: each fault says
 * what it does, so the engineer picks by effect, not by name; the injections
 * in force sit beside the list, with the one command that clears them all.
 */

import { useEffect, useState } from "react";

import {
  type Snapshot, clearFaults, fetchFailures, fetchFaults, fetchSensorFailureOptions, injectFailure,
  injectFault, injectLaneFailure, injectSensorFailure,
} from "../../lib/api";
import { Button, ConfirmButton, Empty, Field, Result, Section } from "../../ui/kit";
import { Status, words } from "../../ui/status";

export function SimulationPage({ snap }: { snap: Snapshot }) {
  const [faults, setFaults] = useState<any[]>([]);
  const [severity, setSeverity] = useState(0.7);
  const [pending, setPending] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [opts, setOpts] = useState<{ channels: string[]; modes: string[];
    lane_items: { item: string; lane: string }[] } | null>(null);
  const [sensor, setSensor] = useState("oil_pressure");
  const [sensorMode, setSensorMode] = useState("stuck");
  const [laneItem, setLaneItem] = useState("");

  useEffect(() => { fetchFaults().then(setFaults).catch(() => setFaults([])); }, []);
  const [failures, setFailures] = useState<{ name: string; label: string; description: string }[]>([]);
  useEffect(() => { fetchFailures().then(setFailures).catch(() => setFailures([])); }, []);
  useEffect(() => {
    fetchSensorFailureOptions().then((o) => {
      setOpts(o);
      if (o.lane_items.length) setLaneItem(`${o.lane_items[0].item}|${o.lane_items[0].lane}`);
    }).catch(() => setOpts(null));
  }, []);

  const run = async (key: string, fn: () => Promise<any>, done: string) => {
    setPending(key); setMsg(null);
    try {
      const r = await fn();
      if (r?.detail) throw new Error(typeof r.detail === "string" ? r.detail : JSON.stringify(r.detail));
      setMsg({ ok: true, text: done });
    } catch (e: any) {
      setMsg({ ok: false, text: e.message ?? String(e) });
    } finally { setPending(null); }
  };

  const env: any = snap.twin.reported.environmental ?? {};
  const injected = snap.faults_injected;

  return (
    <div className="simulation-page">
      <div className="simulation-layout">
        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <Result msg={msg} />
          {failures.length > 0 && (
            <Section title="Sudden failures"
                     right={<span className="t-mute">the engine stops making power, now</span>}>
              <div className="t-dim" style={{ marginBottom: 8 }}>
                Unlike the wear faults below, these act at once. In flight the aircraft glides
                down once the engine has stopped. Two presses, because they end the sortie.
              </div>
              <table className="table">
                <tbody>
                  {failures.map((f) => (
                    <tr key={f.name}>
                      <td style={{ width: "32%" }}><b>{f.label}</b></td>
                      <td className="t-dim">{f.description}</td>
                      <td style={{ textAlign: "right" }}>
                        <ConfirmButton label="Fail" confirmLabel="Confirm: fail"
                                       disabled={pending === f.name}
                                       onConfirm={() => run(f.name, () => injectFailure(f.name),
                                         `${f.label}: injected.`)} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          )}
          <Section title="Wear faults (develop over time)"
                   right={<span className="t-mute">into the running physics; nothing is faked at the display</span>}>
            <Field label={`Severity ${severity.toFixed(2)}`}
                   hint="0.2 is a developing fault, 0.95 a severe one. It ramps in over about a minute of engine time.">
              <input type="range" min={0.2} max={0.95} step={0.05} value={severity}
                     onChange={(e) => setSeverity(parseFloat(e.target.value))} />
            </Field>
            <table className="table" style={{ marginTop: 12 }}>
              <tbody>
                {faults.map((f) => (
                  <tr key={f.mode}>
                    <td style={{ width: "32%" }}><b>{f.label ? words(f.label) : words(f.mode)}</b></td>
                    <td className="t-dim">{f.description}{f.note ? <span className="t-mute"> ({f.note})</span> : null}</td>
                    <td style={{ textAlign: "right" }}>
                      <Button disabled={!f.injectable || pending === f.mode}
                              onClick={() => run(f.mode, () => injectFault(f.mode, severity),
                                `${words(f.mode)} injected at severity ${severity.toFixed(2)}.`)}>
                        {pending === f.mode ? "Injecting…" : "Inject"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          {opts && (
            <Section title="Fail an instrument or a FADEC lane">
              <div style={{ display: "grid", gap: 16 }}>
                <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
                  <div style={{ flex: "1 1 200px" }}>
                    <Field label="Instrument">
                      <select className="input" value={sensor} onChange={(e) => setSensor(e.target.value)}>
                        {opts.channels.map((c) => <option key={c} value={c}>{words(c)}</option>)}
                      </select>
                    </Field>
                  </div>
                  <div style={{ flex: "0 1 180px" }}>
                    <Field label="How it fails">
                      <select className="input" value={sensorMode} onChange={(e) => setSensorMode(e.target.value)}
                              title="frozen: repeats its last reading exactly; stuck: stops following the engine but keeps its noise">
                        {opts.modes.map((m) => <option key={m} value={m}>{words(m)}</option>)}
                      </select>
                    </Field>
                  </div>
                  <Button disabled={pending === "sensor"}
                          onClick={() => run("sensor", () => injectSensorFailure(sensor, sensorMode),
                            `${words(sensor)} set to ${sensorMode}.`)}>Fail instrument</Button>
                </div>
                <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
                  <div style={{ flex: "1 1 260px" }}>
                    <Field label="FADEC lane item">
                      <select className="input" value={laneItem} onChange={(e) => setLaneItem(e.target.value)}>
                        {opts.lane_items.map((l) => (
                          <option key={`${l.item}|${l.lane}`} value={`${l.item}|${l.lane}`}>
                            {l.item}, lane {l.lane}</option>
                        ))}
                      </select>
                    </Field>
                  </div>
                  <Button disabled={!laneItem || pending === "lane"}
                          onClick={() => {
                            const [item, lane] = laneItem.split("|");
                            run("lane", () => injectLaneFailure(item, lane), `${item} failed on lane ${lane}.`);
                          }}>Fail lane item</Button>
                </div>
              </div>
            </Section>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <Section title="In force now"
                   right={Array.isArray(injected) && injected.length > 0 ? (
                     <ConfirmButton kind="quiet" label="Clear all" confirmLabel="Confirm: clear all"
                                    onConfirm={() => run("clear", clearFaults, "All injected faults cleared.")} />
                   ) : undefined}>
            {!Array.isArray(injected) ? <Empty>Not shown for this role.</Empty>
              : injected.length === 0 ? <Empty>None. The engine is wearing only through normal use.</Empty> : (
                <table className="table">
                  <tbody>
                    {injected.map((f: any, i: number) => (
                      <tr key={i}>
                        <td><Status level="advisory" text={words(f.mode)} bold={false} /></td>
                        <td className="num">severity {f.severity.toFixed(2)}</td>
                        <td className="num t-dim">from {f.onset_hours.toFixed(3)} h</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          </Section>
          <Section title="Conditions now">
            <dl className="dl">
              <dt>Altitude</dt><dd className="t-num">{env.altitude_ft?.value != null ? `${env.altitude_ft.value.toFixed(0)} ft` : "—"}</dd>
              <dt>Outside air</dt><dd className="t-num">{env.oat_c?.value != null ? `${env.oat_c.value.toFixed(1)} °C` : "—"}</dd>
              <dt>Ambient pressure</dt><dd className="t-num">{env.ambient_pressure_hpa != null ? `${env.ambient_pressure_hpa.toFixed(0)} hPa` : "—"}</dd>
              <dt>Airspeed</dt><dd className="t-num">{env.airspeed_kmh?.value != null ? `${env.airspeed_kmh.value.toFixed(0)} km/h` : "—"}</dd>
              <dt>Throttle</dt><dd className="t-num">{snap.twin.reported.throttle_pct?.value != null
                ? `${snap.twin.reported.throttle_pct.value.toFixed(1)} %` : "—"}</dd>
            </dl>
          </Section>
        </div>
      </div>
    </div>
  );
}
