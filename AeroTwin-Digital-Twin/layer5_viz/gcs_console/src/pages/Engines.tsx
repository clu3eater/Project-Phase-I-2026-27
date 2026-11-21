/* ENGINES — which engine this station models, and adding another.
 *
 * "Adding an engine is a YAML file and zero code change" was the claim, and
 * there was no way to do it short of editing files on the server and setting
 * an environment variable nobody had documented -- and the one second engine
 * shipped did not run at all. This page lists every definition with what is
 * missing from it, lets the ENGINEER write a new one from the template (it is
 * checked against every key the code reads and flown for ten seconds before it
 * is kept), and lets the COMMANDER fit it to an aircraft: an engine change on
 * one airframe, since every aircraft in the squadron carries its own engine.
 */

import React, { useCallback, useEffect, useState } from "react";

import { Panel } from "../components/Core";
import { api, can } from "../lib/api";
import { ConfirmButton } from "../ui/kit";

const BTN: React.CSSProperties = {
  minHeight: 44, padding: "6px 12px", background: "transparent",
  color: "var(--ink)", border: "1px solid var(--line)",
  borderRadius: "var(--radius)", cursor: "pointer", fontSize: 16,
  fontFamily: "inherit",
};

async function problemsOf(r: Response): Promise<string> {
  const text = await r.text();
  try {
    const d = JSON.parse(text).detail;
    if (d?.problems) return d.problems.join("\n");
    return typeof d === "string" ? d : text;
  } catch {
    return text.slice(0, 400);
  }
}

export function EnginesPage() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [yaml, setYaml] = useState("");
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const author = can("write:engines");
  const admin = can("admin:fleet");
  const [fitTo, setFitTo] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    api("/api/engines")
      .then(async (r) => { if (!r.ok) throw new Error("engine list unavailable"); return r.json(); })
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const startFrom = async (source: string | null) => {
    const r = await api(source ? `/api/engines/${source}/yaml` : "/api/engines/template");
    if (r.ok) {
      let text = await r.text();
      // Copying an engine should inherit from it, not duplicate all of it.
      if (source) text = `extends: ${source}\n# Only what differs from ${source} needs to be below.\n`
        + "identity:\n  display_name: \"New engine (unvalidated)\"\n  validated: false\n";
      setYaml(text);
      setResult(null);
    }
  };

  const save = async (dryRun: boolean) => {
    setBusy(true);
    setResult(null);
    try {
      const r = await api("/api/engines", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ engine_key: key, yaml_text: yaml, dry_run: dryRun }),
      });
      if (!r.ok) throw new Error(await problemsOf(r));
      setResult({ ok: true, text: dryRun
        ? `${key}: complete, and runs in the virtual engine. Not saved (check only).`
        : `${key} saved. ${admin ? "Fit it to an aircraft below." : "A commander can now fit it to an aircraft."}` });
      if (!dryRun) load();
    } catch (e: any) {
      setResult({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const fit = async (k: string) => {
    const tail = fitTo[k] ?? data.aircraft[0];
    setBusy(true);
    try {
      const r = await api(`/api/ops/aircraft/${tail}/engine`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ engine_key: k }),
      });
      if (!r.ok) throw new Error(await problemsOf(r));
      if (tail === data.active_tail) {
        // Limits, identity and scales are loaded once per page load; the
        // aircraft on the station now has another engine, so reload.
        window.location.reload();
        return;
      }
      setResult({ ok: true, text: `${k} fitted to ${tail}.` });
      load();
    } catch (e: any) {
      setResult({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };

  if (error) return <Panel title="Engines"><div style={{ color: "var(--alert-caut)" }}>{error}</div></Panel>;
  if (!data) return <Panel title="Engines"><div style={{ color: "var(--ink-dim)" }}>ACQUIRING</div></Panel>;

  return (
    <div className="engine-definitions-layout">
      <Panel title="Engine definitions" grow>
        {data.engines.map((e: any) => {
          const running = e.key === data.running;
          return (
            <div key={e.key} style={{
              marginBottom: 10, padding: "10px 12px", background: "var(--bg-raised)",
              borderRadius: "var(--radius)",
              borderLeft: `4px solid ${running ? "var(--state-normal)"
                : e.usable ? "var(--line)" : "var(--alert-warn)"}`,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8,
                            fontSize: 17, fontWeight: 700 }}>
                <span>{e.display_name}</span>
                <span style={{ color: running ? "var(--state-normal)" : "var(--ink-dim)",
                               fontSize: 16 }}>
                  {running ? "ON GCS NOW" : e.usable ? "READY" : "INCOMPLETE"}
                </span>
              </div>
              <div style={{ fontSize: 16, color: "var(--ink-dim)", marginTop: 2 }}>
                {e.key} · {e.ignition === "COMPRESSION" ? "diesel" : "spark ignition"}
                {e.extends?.length ? ` · extends ${e.extends.join(" → ")}` : ""}
                {!e.validated && (
                  <span style={{ color: "var(--alert-caut)" }}> · UNVALIDATED (placeholder data)</span>
                )}
              </div>
              {e.problems?.length > 0 && (
                <ul style={{ margin: "6px 0 0 18px", padding: 0, fontSize: 16,
                             color: "var(--alert-warn)" }}>
                  {e.problems.slice(0, 8).map((p: string) => <li key={p}>{p}</li>)}
                  {e.problems.length > 8 && <li>…and {e.problems.length - 8} more</li>}
                </ul>
              )}
              <div style={{ fontSize: 16, marginTop: 4 }}>
                Fitted to: {(data.fitted?.[e.key] ?? []).join(", ") || "no aircraft"}
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                {admin && e.usable && (
                  <>
                    <select style={{ ...BTN, minWidth: 120 }} aria-label={`Aircraft for ${e.key}`}
                            value={fitTo[e.key] ?? data.aircraft[0]}
                            onChange={(ev) => setFitTo({ ...fitTo, [e.key]: ev.target.value })}>
                      {data.aircraft.map((t: string) => <option key={t} value={t}>{t}</option>)}
                    </select>
                    {/* Two presses, not a pop-up (s9.2): the aircraft is
                        unreleased until it has been ground-run and inspected,
                        and its new engine starts with no hours. */}
                    <ConfirmButton label="Fit to aircraft" disabled={busy}
                                   confirmLabel={`Confirm: fit to ${fitTo[e.key] ?? data.aircraft[0]}`}
                                   onConfirm={() => fit(e.key)} />
                  </>
                )}
                {author && (
                  <button style={BTN} onClick={() => startFrom(e.key)}>
                    NEW ENGINE BASED ON THIS
                  </button>
                )}
              </div>
            </div>
          );
        })}
        <div style={{ fontSize: 16, color: "var(--ink-mute)", marginTop: 6, lineHeight: 1.5 }}>
          Files live in configs/engines/. On the server:{" "}
          <code>python run.py --list-engines</code>,{" "}
          <code>--check-engine KEY</code>; fit an engine to an aircraft in
          configs/fleet.yaml.
        </div>
      </Panel>

      <Panel title="Add an engine" grow>
        {!author ? (
          <div style={{ fontSize: 16, color: "var(--ink-mute)" }}>
            Engine definitions are written by the ENGINEER role.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, height: "100%" }}>
            <div style={{ fontSize: 16, color: "var(--ink-dim)", lineHeight: 1.5 }}>
              Start from the template or from an existing engine. Anything the file
              does not state is inherited from the engine named in <code>extends:</code>.
              Limits that differ for this engine go under <code>thresholds_override:</code>.
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button style={BTN} onClick={() => startFrom(null)}>START FROM TEMPLATE</button>
              <input
                aria-label="Engine key"
                placeholder="engine key, e.g. rotax_912is"
                value={key}
                onChange={(e) => setKey(e.target.value.toLowerCase())}
                style={{ flex: "1 1 200px", minHeight: 44, padding: "6px 10px",
                         background: "var(--bg-panel)", color: "var(--ink)",
                         border: "1px solid var(--line)", borderRadius: "var(--radius)",
                         fontSize: 16, fontFamily: "var(--font-num)" }} />
            </div>
            <textarea
              aria-label="Engine definition YAML"
              value={yaml}
              onChange={(e) => setYaml(e.target.value)}
              spellCheck={false}
              style={{ flex: 1, minHeight: 260, padding: 10, resize: "vertical",
                       background: "var(--bg-panel)", color: "var(--ink)",
                       border: "1px solid var(--line)", borderRadius: "var(--radius)",
                       fontSize: 16, fontFamily: "var(--font-num)", lineHeight: 1.4 }} />
            <div style={{ display: "flex", gap: 8 }}>
              <button style={BTN} disabled={busy || !key || !yaml} onClick={() => save(true)}>
                CHECK
              </button>
              <button style={BTN} disabled={busy || !key || !yaml} onClick={() => save(false)}>
                CHECK AND SAVE
              </button>
            </div>
            {result && (
              <div role="status" style={{
                whiteSpace: "pre-wrap", fontSize: 16, padding: "8px 12px",
                borderRadius: "var(--radius)",
                border: `1px solid ${result.ok ? "var(--state-normal)" : "var(--alert-warn)"}`,
                color: result.ok ? "var(--state-normal)" : "var(--alert-warn)",
              }}>
                {result.text}
              </div>
            )}
          </div>
        )}
      </Panel>
    </div>
  );
}
