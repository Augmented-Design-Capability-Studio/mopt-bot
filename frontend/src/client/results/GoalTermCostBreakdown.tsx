import type { GoalTermContribution, RunResult } from "@shared/api";

type GoalTermCostBreakdownProps = {
  currentRun: RunResult;
};

function formatNumber(n: number, fractionDigits = 2): string {
  if (!Number.isFinite(n)) return "-";
  return n.toFixed(fractionDigits);
}

function formatMetric(row: GoalTermContribution): string {
  const value = formatNumber(row.metric_value, Math.abs(row.metric_value) >= 100 ? 1 : 2);
  return row.metric_unit ? `${value} ${row.metric_unit}` : value;
}

function formatContribution(row: GoalTermContribution): string {
  const cost = formatNumber(row.weighted_cost);
  const sign = row.weighted_cost >= 0 ? "+" : "";
  const metric = formatNumber(row.metric_value, Math.abs(row.metric_value) >= 100 ? 1 : 2);
  return `${sign}${cost} to cost (${row.weight}×${metric}${row.metric_unit ? " " + row.metric_unit : ""})`;
}

/** Per-goal-term cost-contribution accordion. Renders only terms the participant's
 *  config submitted (filtering happens backend-side). Hidden when the run has no
 *  contributions or the field is absent. */
export function GoalTermCostBreakdown({ currentRun }: GoalTermCostBreakdownProps) {
  const rows = currentRun.result?.goal_term_contributions;
  if (!rows || rows.length === 0) return null;

  return (
    <details className="run-summary-accordion">
      <summary className="run-summary-accordion-summary">
        <span className="run-summary-label-closed">See how each goal term contributed to the total cost</span>
        <span className="run-summary-label-open">Hide cost breakdown</span>
      </summary>
      <div className="run-summary-grid">
        {rows.map((row) => {
          const warn = row.weighted_cost > 0 && row.weight > 0 && row.metric_value > 0;
          return (
            <div key={row.key} className={`run-summary-card${warn ? " warn" : ""}`}>
              <div className="muted">{row.label}</div>
              <div className="mono">{formatMetric(row)}</div>
              <div className="mono muted">weight: {row.weight}</div>
              <div className="mono muted" style={{ fontSize: "0.72rem", marginTop: "0.15rem" }}>
                {formatContribution(row)}
              </div>
            </div>
          );
        })}
      </div>
    </details>
  );
}
