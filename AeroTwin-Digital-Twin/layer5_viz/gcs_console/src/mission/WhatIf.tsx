/* WHAT IF THIS FAULT HAPPENED ON THIS MISSION?
 *
 * THERE IS A REAL PATH FOR THIS AND THIS IS IT
 * --------------------------------------------
 * /api/mission/flight takes `use_live_engine`, and when it is true the server
 * flies the sortie on THE TWIN'S OWN DEGRADATION FACTORS -- the engine as it is
 * at the moment the request arrives. /api/faults/inject puts a fault into that
 * running twin. So injecting a fault and re-flying the same route is not a
 * simulation of a forecast: it is the same physics, on an engine that now has
 * the fault, and the difference between the two answers is measured rather
 * than modelled.
 *
 * WHAT THIS DOES NOT DO, AND WILL NOT PRETEND TO
 * ----------------------------------------------
 * It cannot start a fault PARTWAY THROUGH a sortie. The route simulator takes
 * the engine's state once, when the flight begins, and steps the model from
 * there; there is no hook for "and at 2 h 15 m the wastegate sticks". A control
 * offering a start waypoint would be a control that changes nothing, so there
 * is not one, and the panel says why.
 *
 * IT CHANGES LIVE STATE, WHICH IS SAID OUT LOUD
 * ---------------------------------------------
 * This is not a sandbox. The injection goes into the twin every other page is
 * watching, the health index will fall on it, and it stays until it is
 * cleared. That is the honest cost of the answer being real, and an operator is
 * told before they press it rather than after.
 */

import { useEffect, useState } from "react";
import { clearFaults, fetchFaults, injectFault } from "../lib/api";
import { Chip, Slider, ghostButton } from "./ui";

export function WhatIf(props: {
  /** snap.faults_injected -- an array, or a scope object when the role may not see it. */
  injected: any;
  onReFly: () => void;
  busy: boolean;
  /** True once a clean sortie has been flown, which is what a comparison needs. */
  haveBaseline: boolean;
}) {
  const [faults, setFaults] = useState<any[]>([]);
  const [mode, setMode] = useState<string>("");
  const [severity, setSeverity] = useState(0.7);
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { fetchFaults().then(setFaults).catch(() => setFaults([])); }, []);

  const active = Array.isArray(props.injected) ? props.injected : null;

  const injectAndFly = async () => {
    if (!mode) return;
    setPending(true); setErr("");
    try {
      await injectFault(mode, severity);
      props.onReFly();
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setPending(false);
    }
  };

  const clear = async () => {
    setPending(true); setErr("");
    try { await clearFaults(); } catch (e: any) { setErr(String(e?.message ?? e)); }
    finally { setPending(false); }
  };

  return (
    <div>
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    lineHeight: 1.55, marginBottom: "var(--space-3)",
                    borderLeft: "2px solid var(--alert-caut)", paddingLeft: 9 }}>
        This injects into the <b>running twin</b>, not into a copy of it. The
        health index will fall on it and every other page will show it, until it
        is cleared. The sortie is then re-flown on the twin's own degradation
        factors — the same <span style={{ fontFamily: "var(--font-num)" }}>
        use_live_engine</span> path an ordinary run takes.
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6,
                    marginBottom: "var(--space-4)" }}>
        {faults.map((f) => (
          <Chip key={f.mode} tone="caut" on={mode === f.mode}
                disabled={!f.injectable}
                title={f.note || f.description}
                onClick={() => setMode(mode === f.mode ? "" : f.mode)}>
            {f.label}
          </Chip>
        ))}
        {faults.length === 0 && (
          <span style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)" }}>
            No fault list available for this role.
          </span>
        )}
      </div>

      <Slider label="Severity" value={severity} min={0.2} max={0.95} step={0.05}
              unit="" display={severity.toFixed(2)} onChange={setSeverity} />

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap",
                    marginTop: "var(--space-4)" }}>
        <button onClick={injectAndFly}
                disabled={!mode || pending || props.busy}
                style={{ ...ghostButton, flex: 1, minHeight: 40, fontWeight: 700,
                         color: mode ? "var(--alert-caut)" : "var(--ink-mute)",
                         borderColor: mode ? "var(--alert-caut)" : "var(--line)",
                         cursor: pending || props.busy ? "wait"
                           : mode ? "pointer" : "not-allowed" }}>
          {pending ? "INJECTING…" : "INJECT AND RE-FLY"}
        </button>
        <button onClick={clear} disabled={pending || props.busy}
                style={{ ...ghostButton, minHeight: 40 }}>
          CLEAR FAULTS
        </button>
      </div>

      {err && (
        <div style={{ fontSize: "var(--size-label)", color: "var(--alert-caut)",
                      marginTop: 8 }}>{err}</div>
      )}

      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    marginTop: "var(--space-3)", lineHeight: 1.5 }}>
        {active === null
          ? "Injected faults are not shown for this role."
          : active.length === 0
            ? "Nothing injected. The engine is degrading only through normal wear."
            : active.map((f: any, i: number) => (
                <div key={i} style={{ color: "var(--alert-caut)" }}>
                  {f.mode.replace(/_/g, " ")} · severity {f.severity.toFixed(2)} ·
                  onset {f.onset_hours.toFixed(3)} h
                </div>
              ))}
      </div>

      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    marginTop: "var(--space-3)", lineHeight: 1.5 }}>
        {props.haveBaseline
          ? "A clean run of this route is held, so the results below will show the "
            + "difference the fault made."
          : "Fly the route clean first and the results will show the difference "
            + "the fault made against it."}
        {" "}There is no start-point control: the route simulator takes the
        engine's state once, when the flight begins, so an injected fault is
        present for the whole sortie.
      </div>
    </div>
  );
}
