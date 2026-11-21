import type { ReactNode } from "react";
import "./engine-view.css";

const paths = {
  temperature: "M10 5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0V5M12 8v9",
  wave: "M2 12h4l2-6 4 12 3-12 3 6h4",
  power: "m14 2-9 12h6l-1 8 9-12h-6l1-8Z",
  fuel: "M5 4h9v16H5V4Zm0 7h9m0-5 4 3v7a2 2 0 0 0 4 0v-5l-3-3",
  timing: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 4v5l4 2",
  combustion: "M13 3c1 5-5 6-4 10 1-1 3-2 3-4 5 3 6 6 4 9-3 5-11 2-10-3 0-5 5-6 7-12Z",
  health: "M3 12h4l2-5 4 10 2-5h6",
  systems: "M3 4h7v7H3V4Zm11 0h7v7h-7V4ZM3 15h7v6H3v-6Zm11 0h7v6h-7v-6Z",
};
export type EngineIconName = keyof typeof paths;
export function EngineIcon({ name }: { name: EngineIconName }) {
  return <svg className="engine-icon" width="26" height="26" viewBox="0 0 24 24" aria-hidden="true"><path d={paths[name]} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
export function EngineSectionTitle({ icon, children }: { icon: EngineIconName; children: ReactNode }) {
  return <span className="engine-section-title"><EngineIcon name={icon} />{children}</span>;
}

export function EngineView({ title, description, children, enabled = true }: { title: string; description: string; children: ReactNode; enabled?: boolean }) {
  if (!enabled) return <>{children}</>;
  return <div className="engine-view">
    <header className="engine-view-heading"><h2>{title}</h2><p>{description}</p></header>
    <div className="engine-view-content">{children}</div>
  </div>;
}

export function EngineMetricCard({ title, icon, value, unit, children, className = "", label }: {
  title: string; icon: EngineIconName; value: ReactNode; unit?: string; children?: ReactNode; className?: string; label?: string;
}) {
  return <section className={`engine-metric-card ${className}`} aria-label={label}>
    <div className="engine-metric-label"><EngineIcon name={icon} /><b>{title}</b></div>
    <div className="engine-metric-value t-num">{value}{unit && <span> {unit}</span>}</div>
    {children}
  </section>;
}
