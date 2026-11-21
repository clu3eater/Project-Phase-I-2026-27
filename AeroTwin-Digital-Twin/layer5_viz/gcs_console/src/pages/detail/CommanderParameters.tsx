import { useEffect, useRef, useState } from "react";
import { EngineModel } from "../../components/EngineModel";
import { KeyValue, Trend } from "../../components/Core";
import { type Snapshot } from "../../lib/api";
import { Button, Section } from "../../ui/kit";
import { AgainstBands, readVal } from "./HealthFigures";
import { type Limit } from "../../lib/bands";
import { EngineView, EngineMetricCard, EngineSectionTitle, type EngineIconName } from "../../ui/EngineView";
import "./commander-parameters.css";

type PartFocus = { componentId: string; n: number };
const usable = (node: any): number | null => node?.state === "INVALID" || node?.state === "MISSING" ? null : readVal(node);
function Reading({ label, node, unit, digits = 1, limit, icon, note }: {
  label: string; node: any; unit: string; digits?: number; limit?: Limit; icon: EngineIconName; note?: string;
}) {
  const value = usable(node);
  const state = node?.state && node.state !== "VALID" ? node.state : null;
  return <EngineMetricCard className="parameter-reading" title={label} icon={icon} value={value == null ? "—" : value.toFixed(digits)} unit={unit}>
    {state && <span className="parameter-value-state">{state}{node?.age_s != null ? ` · ${Math.round(node.age_s)} s old` : ""}</span>}
    {limit && <AgainstBands value={value} lim={limit} unit={unit} digits={digits} />}
    {note && <span className="t-mute">{note}</span>}
  </EngineMetricCard>;
}

export function CommanderParameters({ snap, limits, partFocus }: { snap: Snapshot; limits: any; partFocus?: PartFocus | null }) {
  const [expanded, setExpanded] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [focus, setFocus] = useState<PartFocus | null>(null);
  const [technical, setTechnical] = useState(false);
  const modelCard = useRef<HTMLDivElement>(null);
  const focusSequence = useRef(0);
  const r: any = snap.twin.reported;
  const p = limits?.parameters ?? {};
  const engineOff = usable(r.rpm) === 0;
  useEffect(() => {
    if (partFocus) {
      focusSequence.current += 1;
      setFocus({ componentId: partFocus.componentId, n: focusSequence.current });
      setExpanded(true);
    }
  }, [partFocus?.n]);
  useEffect(() => {
    if (!expanded) return;
    modelCard.current?.scrollIntoView({ block: "nearest" });
    const escape = (e: KeyboardEvent) => { if (e.key === "Escape") setExpanded(false); };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [expanded]);
  const showCylinder = (i: number) => {
    focusSequence.current += 1;
    setFocus({ componentId: `ROTAX_915IS_CYLINDER_0${i}`, n: focusSequence.current });
    setExpanded(true);
    modelCard.current?.scrollIntoView({ block: "nearest" });
  };
  return <EngineView title="Engine parameters" description="Measured telemetry, cylinder temperatures and detected faults."><div className="commander-parameters">
    <div className={`commander-parameter-grid${expanded ? " model-expanded" : ""}`}>
      <div className="parameter-model-card" ref={modelCard}>
        <Section title={<EngineSectionTitle icon="systems">Engine — detected faults on the part</EngineSectionTitle>} right={<Button onClick={() => setExpanded(v => !v)} ariaExpanded={expanded} ariaControls="commander-engine-view">{expanded ? "Collapse engine" : "Expand engine"}</Button>}>
          <div className="parameter-model-hint t-dim">{picked ? picked.replace(/^ROTAX_915IS_/, "").replace(/_/g, " ") : "Select a part to identify it. Drag to rotate; scroll over the model to zoom."}</div>
          <div id="commander-engine-view" className="commander-engine-view">
            <EngineModel snap={snap} onSelect={setPicked} focusPart={focus} />
          </div>
          <div className="t-mute">Highlights show faults detected by the twin. They do not show every injected fault. {expanded && "Press Escape to collapse."}</div>
        </Section>
      </div>
      <div className="parameter-data-column">
        <Section title={<EngineSectionTitle icon="temperature">Cylinder temperatures</EngineSectionTitle>} right={<span className="t-dim">°C · head and exhaust</span>}>
          <div className="parameter-cylinder-summary">
            <span>Head spread <b className="t-num">{readVal(r.cht?.spread)?.toFixed(1) ?? "—"} °C</b></span>
            <span>Exhaust spread <b className="t-num">{readVal(r.egt?.spread)?.toFixed(0) ?? "—"} °C</b></span>
          </div>
          {engineOff && <p className="t-dim">Engine off. Cold temperatures are not a running-engine health assessment.</p>}
          <div className="commander-cylinder-grid">
            {[1, 3, 2, 4].map(i => <div className="commander-cylinder-card" key={i}>
              <div className="parameter-cylinder-title"><span className="parameter-cylinder-number">{i}</span><b>Cylinder {i}</b>
                <Button kind="quiet" onClick={() => showCylinder(i)}>Show on engine</Button></div>
              <Reading label="Cylinder head" node={r.cht?.[`cyl_${i}`]} unit="°C" limit={p.cht} icon="temperature" />
              <Reading label="Exhaust gas" node={r.egt?.[`cyl_${i}`]} unit="°C" digits={0} limit={p.egt} icon="temperature" />
            </div>)}
          </div>
        </Section>
        <Section title={<EngineSectionTitle icon="systems">Engine systems</EngineSectionTitle>} right={<span className="t-mute">Current telemetry</span>}>
          <div className="commander-system-grid">
            <Reading label="Oil temperature" node={r.oil_temperature} unit="°C" limit={p.oil_temperature} icon="temperature" />
            <Reading label="Fuel flow" node={r.fuel_flow} unit="L/h" limit={p.fuel_flow} icon="fuel" />
            <Reading label="Manifold pressure" node={r.manifold_pressure} unit="bar" digits={2} limit={p.manifold_pressure} icon="fuel" />
            <Reading label="Vibration" node={r.vibration?.rms_total} unit="m/s²" digits={2} limit={p.vibration_rms_total} icon="wave" />
            <Reading label="Bus voltage" node={r.electrical?.bus_voltage} unit="V" limit={p.bus_voltage} icon="power" />
            <Reading label="Alternator current" node={r.electrical?.alternator_current} unit="A" limit={p.alternator_current} icon="power" />
            <Reading label="Injection timing" node={r.timing?.injection_deviation_max} unit="°" digits={2} icon="timing" note="Deviation from commanded timing" />
            <Reading label="Ignition timing" node={r.timing?.ignition_deviation_max} unit="°" digits={2} icon="timing" note="Deviation from commanded timing" />
            <Reading label="Injector duty" node={r.timing?.injector_duty_pct} unit="%" icon="fuel" />
            <Reading label="Knock retard" node={r.timing?.knock_retard_deg} unit="°" icon="timing" />
          </div>
        </Section>
      </div>
    </div>
    <Section title={<EngineSectionTitle icon="wave">Vibration and model comparison</EngineSectionTitle>} right={<Button kind="quiet" ariaExpanded={technical} ariaControls="parameter-technical-details" onClick={() => setTechnical(v => !v)}>{technical ? "View less −" : "View more +"}</Button>}>
      {!technical ? <span className="t-dim">Inspect vibration orders and differences from the as-new model.</span> : <div id="parameter-technical-details" className="parameter-technical-grid">
        <div><h3 className="t-section">Vibration — order analysis</h3>
          {Object.keys(r.vibration?.spectral_peaks ?? {}).length ? <>
            {Object.entries(r.vibration.spectral_peaks).map(([key, value]) => <KeyValue key={key} k={key} v={typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)} × floor` : "not available"} />)}
            <KeyValue k="Dominant frequency" v={readVal(r.vibration?.dominant_frequency_hz) == null ? "not available" : `${readVal(r.vibration.dominant_frequency_hz)?.toFixed(1)} Hz`} />
            {engineOff && <p className="t-mute">Engine off. These order-analysis values may be retained from the previous run.</p>}
          </> : <p className="t-mute">No order analysis yet. It runs in stabilised cruise, above idle.</p>}
        </div>
        <div><h3 className="t-section">Measured vs as-new model</h3>
          {(snap.twin.simulated?.outside_manufacturer_data ?? []).map((reason: string, i: number) => <p className="t-dim" key={i}>Outside manufacturer data: {reason}</p>)}
          <Trend series={snap.history.cht} predicted={snap.history.cht_pred} label="Head temperature — measured / model" unit="°C" height={140} />
          {[["Cylinder head", "cht", "°C"], ["Coolant", "coolant", "°C"], ["Exhaust gas", "egt", "°C"], ["Oil pressure", "oil_pressure", "psi"], ["Fuel flow", "fuel_flow", "L/h"]].map(([label, key, unit]) => {
            const res = snap.twin.residuals?.[key];
            const value = res?.usable ? readVal(res.mean_delta) : null;
            return <KeyValue key={key} k={label} v={value == null ? "not available" : `${value >= 0 ? "+" : ""}${value.toFixed(2)} ${unit}`} />;
          })}
        </div>
      </div>}
    </Section>
  </div></EngineView>;
}
