export interface ComparisonItem {
  label: string;
  value: number | null | undefined;
  display?: string;
}

/** A small responsive horizontal bar chart for values already shown on a page. */
export function ComparisonChart(props: {
  label: string;
  items: ComparisonItem[];
  max?: number;
  format?: (value: number) => string;
  tone?: "health" | "neutral";
}) {
  const max = props.max ?? 100;
  const format = props.format ?? ((value: number) => `${Math.round(value)}%`);
  return (
    <figure className="comparison-chart" aria-label={props.label}>
      <figcaption className="comparison-chart-title">{props.label}</figcaption>
      <div className="comparison-chart-axis" aria-hidden="true">
        <span>0</span><span>{format(max / 2)}</span><span>{format(max)}</span>
      </div>
      <div className="comparison-chart-rows">
        {props.items.map((item) => {
          const known = typeof item.value === "number" && Number.isFinite(item.value);
          const value = known ? Math.max(0, Math.min(max, item.value!)) : null;
          const level = props.tone === "neutral" ? "neutral"
            : value == null ? "unknown" : value < max * 0.75 ? "warning"
            : value < max * 0.9 ? "caution" : "normal";
          return (
            <div className="comparison-chart-row" key={item.label}>
              <span className="comparison-chart-label" title={item.label}>{item.label}</span>
              <div className="comparison-chart-track" role="meter"
                   aria-label={item.label} aria-valuemin={0} aria-valuemax={max}
                   aria-valuenow={value ?? undefined}
                   aria-valuetext={value == null ? "Not assessed" : format(value)}>
                {value != null && value > 0 && <span className={`comparison-chart-bar is-${level}`}
                  style={{ width: `${(value / max) * 100}%` }} />}
              </div>
              <span className="comparison-chart-value">{value == null ? "—" : item.display ?? format(value)}</span>
            </div>
          );
        })}
      </div>
    </figure>
  );
}
