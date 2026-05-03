export function configChangeSummary(
  before: Record<string, unknown> | null,
  after: Record<string, unknown>,
): string {
  const beforeProblem =
    before && typeof before.problem === "object" && before.problem !== null
      ? (before.problem as Record<string, unknown>)
      : before ?? {};

  const afterProblem =
    typeof after.problem === "object" && after.problem !== null
      ? (after.problem as Record<string, unknown>)
      : after;

  const changed: string[] = [];
  const allKeys = new Set([...Object.keys(beforeProblem), ...Object.keys(afterProblem)]);

  for (const key of allKeys) {
    const previous = JSON.stringify(normalizeProblemFieldForSummary(key, beforeProblem[key]));
    const next = JSON.stringify(normalizeProblemFieldForSummary(key, afterProblem[key]));
    if (previous !== next) changed.push(key);
  }

  return changed.length === 0 ? "no settings changed" : changed.map(toParticipantLabel).join(", ");
}

/**
 * Detailed before/after summary the LLM uses to refresh affected brief rows in
 * natural language. Lists per-key transitions for goal_terms (with weights and
 * types), weights, plus scalar settings like algorithm/epochs/pop_size.
 *
 * Backwards-compatible: this is a *new* exported helper; `configChangeSummary`
 * keeps its label-list shape for existing callers.
 */
export function configChangeDetailedSummary(
  before: Record<string, unknown> | null,
  after: Record<string, unknown>,
): string {
  const beforeProblem =
    before && typeof before.problem === "object" && before.problem !== null
      ? (before.problem as Record<string, unknown>)
      : before ?? {};
  const afterProblem =
    typeof after.problem === "object" && after.problem !== null
      ? (after.problem as Record<string, unknown>)
      : after;

  const lines: string[] = [];

  const beforeGT = recordOrNull(beforeProblem.goal_terms);
  const afterGT = recordOrNull(afterProblem.goal_terms);
  if (beforeGT || afterGT) {
    const keys = new Set<string>([
      ...Object.keys(beforeGT ?? {}),
      ...Object.keys(afterGT ?? {}),
    ]);
    for (const key of [...keys].sort()) {
      const prev = beforeGT?.[key];
      const next = afterGT?.[key];
      if (prev == null && next != null) {
        lines.push(`added goal term ${key} (${formatGoalTerm(next)})`);
      } else if (prev != null && next == null) {
        lines.push(`removed goal term ${key}`);
      } else if (prev != null && next != null && JSON.stringify(prev) !== JSON.stringify(next)) {
        lines.push(`goal term ${key}: ${formatGoalTerm(prev)} → ${formatGoalTerm(next)}`);
      }
    }
  } else {
    // Fall back to plain weights map when goal_terms isn't present.
    const beforeW = recordOrNull(beforeProblem.weights);
    const afterW = recordOrNull(afterProblem.weights);
    if (beforeW || afterW) {
      const keys = new Set<string>([
        ...Object.keys(beforeW ?? {}),
        ...Object.keys(afterW ?? {}),
      ]);
      for (const key of [...keys].sort()) {
        const prev = beforeW?.[key];
        const next = afterW?.[key];
        if (prev == null && next != null) {
          lines.push(`added weight ${key}: ${formatScalar(next)}`);
        } else if (prev != null && next == null) {
          lines.push(`removed weight ${key}`);
        } else if (prev !== next) {
          lines.push(`weight ${key}: ${formatScalar(prev)} → ${formatScalar(next)}`);
        }
      }
    }
  }

  for (const key of ["algorithm", "epochs", "pop_size", "random_seed", "max_shift_hours"] as const) {
    const prev = beforeProblem[key];
    const next = afterProblem[key];
    if (prev !== next && (prev != null || next != null)) {
      lines.push(`${toParticipantLabel(key)}: ${formatScalar(prev)} → ${formatScalar(next)}`);
    }
  }

  // Boolean flags worth surfacing to the LLM.
  for (const key of ["early_stop", "use_greedy_init", "only_active_terms"] as const) {
    const prev = beforeProblem[key];
    const next = afterProblem[key];
    if (prev !== next && (prev != null || next != null)) {
      lines.push(`${toParticipantLabel(key)}: ${formatScalar(prev)} → ${formatScalar(next)}`);
    }
  }

  return lines.length === 0 ? "no settings changed" : lines.join("; ");
}

function recordOrNull(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function formatGoalTerm(value: unknown): string {
  if (!value || typeof value !== "object") return formatScalar(value);
  const obj = value as Record<string, unknown>;
  const weight = obj.weight;
  const type = obj.type;
  const parts: string[] = [];
  if (typeof type === "string" && type) parts.push(type);
  if (typeof weight === "number") parts.push(`weight ${weight}`);
  return parts.length > 0 ? parts.join(", ") : formatScalar(value);
}

function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "on" : "off";
  if (typeof value === "number" || typeof value === "string") return String(value);
  return JSON.stringify(value);
}

function normalizeProblemFieldForSummary(key: string, value: unknown): unknown {
  if (key === "only_active_terms") {
    // `true` is an implicit default and should not be called out as a discovered change.
    return value === true ? null : value ?? null;
  }
  if (key === "driver_preferences") {
    // Empty list is a neutral default in panel serialization.
    return Array.isArray(value) && value.length === 0 ? null : value ?? null;
  }
  if (key === "locked_assignments") {
    // Empty map is a neutral default in panel serialization.
    return isEmptyRecord(value) ? null : value ?? null;
  }
  return value ?? null;
}

function isEmptyRecord(value: unknown): boolean {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value as Record<string, unknown>).length === 0
  );
}

function toParticipantLabel(key: string): string {
  const labels: Record<string, string> = {
    early_stop: "Stop early on plateau",
    early_stop_patience: "Plateau patience",
    early_stop_epsilon: "Minimum score improvement",
    use_greedy_init: "Greedy initialization",
    driver_preferences: "Driver preferences",
    locked_assignments: "Locked assignments",
    only_active_terms: "Only active objectives",
    algorithm: "Algorithm",
    algorithm_params: "Algorithm settings",
    epochs: "Max iterations",
    pop_size: "Population size",
    random_seed: "Random seed",
    max_shift_hours: "Shift limit (hours)",
    weights: "Goal weights",
  };
  return labels[key] ?? key.replaceAll("_", " ");
}
