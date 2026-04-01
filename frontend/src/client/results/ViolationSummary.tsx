import type { RunMetrics, RunViolations } from "@shared/api";

/** Weight aliases that map to a specific violation/metric card. */
const TRACKABLE: {
  key: string;
  label: string;
  card: (v: RunViolations, m: RunMetrics) => { value: string; warn: boolean };
}[] = [
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
    label: "Priority Misses",
    card: (v) => ({
      value: `${v.priority_deadline_misses} missed`,
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
];

type ViolationSummaryProps = {
  violations: RunViolations;
  metrics: RunMetrics;
  referenceCost: number | null;
  runtimeSeconds: number;
  /** Keys from `problem.weights` that the participant has explicitly configured. */
  activeWeightKeys: string[];
};

export function ViolationSummary({
  violations,
  metrics,
  referenceCost,
  runtimeSeconds,
  activeWeightKeys,
}: ViolationSummaryProps) {
  const active = new Set(activeWeightKeys);
  const visibleCards = TRACKABLE.filter((t) => active.has(t.key));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
      {/* ── Active weighted terms (from configured weights) ── */}
      <div className="run-summary-grid">
        {visibleCards.map(({ key, label, card }) => {
          const { value, warn } = card(violations, metrics);
          return (
            <div
              key={key}
              className={`run-summary-card${warn ? " warn" : ""}`}
            >
              <div className="muted">{label}</div>
              <div className="mono">{value}</div>
            </div>
          );
        })}

        {/* Cost / runtime always shown */}
        <div className="run-summary-card">
          <div className="muted">Cost · runtime</div>
          <div className="mono">
            {referenceCost != null ? referenceCost.toFixed(2) : "—"} ·{" "}
            {runtimeSeconds.toFixed(1)}s
          </div>
        </div>
      </div>
    </div>
  );
}
