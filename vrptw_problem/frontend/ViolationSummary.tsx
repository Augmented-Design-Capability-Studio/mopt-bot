import type { RunMetrics, RunViolations } from "@shared/api";
import type { ViolationSummaryProps } from "@problemConfig/problemModule";

/** Weight aliases that map to a specific violation/metric card. */
const TRACKABLE: {
  key: string;
  label: string;
  card: (v: RunViolations, m: RunMetrics) => { value: string; warn: boolean };
}[] = [
  {
    key: "travel_time",
    label: "Travel time",
    card: (_, m) => ({
      value: `${m.total_travel_minutes.toFixed(1)} min route time`,
      warn: false,
    }),
  },
  {
    key: "shift_overtime",
    label: "Shift overtime",
    card: (_, m) => {
      const ot = Number(m.shift_overtime_minutes ?? 0);
      return {
        value: `${ot.toFixed(1)} min past 8h cap (fleet total)`,
        warn: ot > 0,
      };
    },
  },
  {
    key: "deadline_penalty",
    label: "On-Time Delivery",
    card: (v) => ({
      value: `${v.time_window_stop_count} late · ${v.time_window_minutes_over.toFixed(0)} min`,
      warn: v.time_window_stop_count > 0,
    }),
  },
  {
    key: "capacity_penalty",
    label: "Capacity Overflow",
    card: (v) => ({
      value: `${v.capacity_units_over} units over`,
      warn: v.capacity_units_over > 0,
    }),
  },
  {
    key: "priority_penalty",
    label: "Express & priority deadlines",
    card: (v) => ({
      value: `${v.priority_deadline_misses} late`,
      warn: v.priority_deadline_misses > 0,
    }),
  },
  {
    key: "workload_balance",
    label: "Workload Variance",
    card: (_, m) => ({
      value: m.workload_variance.toFixed(1),
      warn: m.workload_variance > 5,
    }),
  },
  {
    key: "worker_preference",
    label: "Driver Preferences",
    card: (_, m) => {
      const u = m.driver_preference_penalty ?? m.driver_preference_units ?? 0;
      return {
        value: `${Number(u).toFixed(1)} preference units`,
        warn: Number(u) > 0,
      };
    },
  },
];

function weightedContributionLine(
  key: string,
  runWeights: Record<string, unknown>,
  metrics: RunMetrics,
  violations: RunViolations,
): string | null {
  switch (key) {
    case "travel_time": {
      const w = Number(runWeights["travel_time"]);
      if (!Number.isFinite(w) || w === 0) return null;
      const c = w * metrics.total_travel_minutes;
      return `+${c.toFixed(2)} to cost (${w}×${metrics.total_travel_minutes.toFixed(1)} route min)`;
    }
    case "shift_overtime": {
      const w = Number(runWeights[key]);
      if (!Number.isFinite(w)) return null;
      const ot = Number(metrics.shift_overtime_minutes ?? 0);
      const c = w * ot;
      return `+${c.toFixed(2)} to cost (${w}×${ot.toFixed(1)} overtime min)`;
    }
    case "deadline_penalty": {
      const w = Number(runWeights[key]);
      if (!Number.isFinite(w)) return null;
      const c = w * violations.time_window_minutes_over;
      return `+${c.toFixed(2)} to cost (${w}×${violations.time_window_minutes_over.toFixed(1)} min late)`;
    }
    case "capacity_penalty": {
      const w = Number(runWeights[key]);
      if (!Number.isFinite(w)) return null;
      const c = w * violations.capacity_units_over;
      return `+${c.toFixed(2)} to cost (${w}×${violations.capacity_units_over} units)`;
    }
    case "workload_balance": {
      const w = Number(runWeights[key]);
      if (!Number.isFinite(w)) return null;
      const c = w * metrics.workload_variance;
      return `+${c.toFixed(2)} to cost (${w}×${metrics.workload_variance.toFixed(2)} variance)`;
    }
    case "worker_preference": {
      const w = Number(runWeights[key]);
      if (!Number.isFinite(w)) return null;
      const u = metrics.driver_preference_penalty ?? metrics.driver_preference_units ?? 0;
      const c = w * Number(u);
      return `+${c.toFixed(2)} to cost (${w}×${Number(u).toFixed(1)} pref units)`;
    }
    case "priority_penalty": {
      const w = Number(runWeights[key]);
      if (!Number.isFinite(w)) return null;
      const c = w * violations.priority_deadline_misses;
      return `+${c.toFixed(2)} to cost (${w}×${violations.priority_deadline_misses} late orders)`;
    }
    default:
      return null;
  }
}

export function ViolationSummary({ currentRun }: ViolationSummaryProps) {
  const currentResult = currentRun.result;
  if (!currentResult) return null;

  const runProblem = (currentRun.request?.problem ?? {}) as Record<string, unknown>;
  const runWeights =
    runProblem.weights && typeof runProblem.weights === "object" && !Array.isArray(runProblem.weights)
      ? (runProblem.weights as Record<string, unknown>)
      : {};
  const activeWeightKeys = Object.keys(runWeights).filter((key) => Number.isFinite(Number(runWeights[key])));

  const { violations, metrics } = currentResult;

  const active = new Set(activeWeightKeys);
  const visibleCards = TRACKABLE.filter((t) => active.has(t.key));

  return (
    <details className="run-summary-accordion">
      <summary className="run-summary-accordion-summary">
        <span className="run-summary-label-closed">See how each goal term contributed to the total cost</span>
        <span className="run-summary-label-open">Hide cost breakdown</span>
      </summary>
      <div className="run-summary-grid">
        {visibleCards.map(({ key, label, card }) => {
          const { value, warn } = card(violations, metrics);
          const contrib = weightedContributionLine(key, runWeights, metrics, violations);
          const weight = Number(runWeights[key]);
          const weightLine = Number.isFinite(weight) ? `weight: ${weight}` : null;
          return (
            <div key={key} className={`run-summary-card${warn ? " warn" : ""}`}>
              <div className="muted">{label}</div>
              <div className="mono">{value}</div>
              {weightLine ? <div className="mono muted"> {weightLine}</div> : null}
              {contrib ? (
                <div className="mono muted" style={{ fontSize: "0.72rem", marginTop: "0.15rem" }}>
                  {contrib}
                </div>
              ) : null}
            </div>
          );
        })}

        {violations.shift_limit_penalty > 0 ? (
          <div className={`run-summary-card${violations.shift_limit_penalty > 0 ? " warn" : ""}`}>
            <div className="muted">Shift limit (hard)</div>
            <div className="mono">{violations.shift_limit_penalty.toFixed(1)} penalty units</div>
            <div className="mono muted" style={{ fontSize: "0.72rem", marginTop: "0.15rem" }}>
              +{violations.shift_limit_penalty.toFixed(2)} to total cost (hard shift penalties)
            </div>
          </div>
        ) : null}
      </div>
    </details>
  );
}
