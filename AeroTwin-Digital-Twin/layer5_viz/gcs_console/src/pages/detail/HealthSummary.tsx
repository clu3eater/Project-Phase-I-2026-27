import { AssessmentNote } from "../../components/Core";
import { ArcGauge } from "../../components/Widgets";
import { Section } from "../../ui/kit";
import { INK, Status, bandLevel, healthLevel, words } from "../../ui/status";
import { EngineMetricCard, EngineSectionTitle } from "../../ui/EngineView";
import "./health-summary.css";

const systems = [
  { key: "thermal", label: "Thermal", note: "Temperature condition", icon: "temperature" },
  { key: "mechanical", label: "Mechanical", note: "Lubrication and vibration", icon: "wave" },
  { key: "combustion", label: "Combustion", note: "Combustion condition", icon: "combustion" },
  { key: "electrical", label: "Electrical", note: "Electrical system condition", icon: "power" },
] as const;
const fraction = (v: unknown): number | null => typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1 ? v : null;

export function HealthSummary({ chi, h, instruction }: { chi: number | null; h: any; instruction: string }) {
  const value = fraction(chi);
  const level = value == null ? "standby" : bandLevel(h.band);
  return <div className="health-visual-summary">
    <Section title={<EngineSectionTitle icon="health">Engine health</EngineSectionTitle>}>
      <div className="health-visual-headline">
        <ArcGauge value={value} label="health / 100" size={200} colour={INK[level]} />
        <div className="health-visual-verdict">
          <Status level={level} size={22} text={value == null ? "Not assessed yet" : words(h.band) || "Assessed"} />
          <p>{value == null ? "Condition is assessed when the engine is warm, loaded and steady." : instruction || "Review the system condition below."}</p>
          <AssessmentNote a={h.assessment} />
          <span className="t-mute">Engine condition index; not a mission success probability or flight release.</span>
        </div>
      </div>
    </Section>
    <div className="health-system-cards" aria-label="Health by system">
      {systems.map(system => {
        // Withhold stale subsystem figures until an overall assessment exists.
        const score = value == null ? null : fraction(h[system.key]);
        const status = score == null ? "standby" : healthLevel(score) ?? "normal";
        return <EngineMetricCard className="health-system-card" title={system.label} icon={system.icon}
          label={`${system.label} condition`} value={score == null ? "—" : (score * 100).toFixed(1)} unit={score == null ? undefined : "%"}>
          <div className="health-system-track" role="img" aria-label={`${system.label} health ${score == null ? "not assessed" : `${(score * 100).toFixed(1)} percent`}`}>
            {score != null && <span style={{ width: `${score * 100}%`, background: INK[status] }} />}
          </div>
          <Status level={status} text={score == null ? "Not assessed" : status === "normal" ? "Within health band" : status === "caution" ? "Needs attention" : "Low health"} bold={false} />
          <span className="t-mute">{system.note}</span>
        </EngineMetricCard>;
      })}
    </div>
  </div>;
}
