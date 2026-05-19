/** Stable JSON stringify: emits object keys in alphabetical order recursively
 *  so two objects with the same content but different key-insertion order
 *  compare equal. Used by both the high-level and detailed change summaries
 *  to avoid false-positive "changed" reports caused by backend normalization
 *  re-keying the dict (e.g. ``{weight, type, rank}`` vs ``{type, weight,
 *  rank}``). */
function stableJSON(value: unknown): string {
  return JSON.stringify(value, (_, v) => {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      const sorted: Record<string, unknown> = {};
      for (const k of Object.keys(v as Record<string, unknown>).sort()) {
        sorted[k] = (v as Record<string, unknown>)[k];
      }
      return sorted;
    }
    return v;
  });
}


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
    const previous = stableJSON(normalizeProblemFieldForSummary(key, beforeProblem[key]));
    const next = stableJSON(normalizeProblemFieldForSummary(key, afterProblem[key]));
    if (previous !== next) changed.push(key);
  }

  // ``goal_term_order`` is a derived view of ``goal_terms`` — if both changed
  // (typical when a term is added/removed/reordered), reporting both is
  // redundant. Drop the order entry when the underlying terms changed.
  if (changed.includes("goal_terms") && changed.includes("goal_term_order")) {
    const i = changed.indexOf("goal_term_order");
    if (i >= 0) changed.splice(i, 1);
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
      } else if (prev != null && next != null) {
        // Compare only the user-editable subset. The full entry carries
        // server-derived fields (rank, evidence_item_ids, ambiguity_note)
        // that the participant can't see or change in the panel JSON; a
        // raw stableJSON diff would surface phantom changes whenever the
        // backend rebuilt the entry (e.g. _rebuild_goal_terms re-stamping
        // rank). Surface granular per-field deltas so the LLM reply can
        // mirror them as bullets.
        const prevCmp = normalizeGoalTermForCompare(prev);
        const nextCmp = normalizeGoalTermForCompare(next);
        if (stableJSON(prevCmp) !== stableJSON(nextCmp)) {
          const fieldLines = goalTermFieldDiffLines(key, prevCmp, nextCmp);
          if (fieldLines.length > 0) {
            lines.push(...fieldLines);
          } else {
            // Shouldn't happen — fall back to whole-entry transition.
            lines.push(`goal term ${key}: ${formatGoalTerm(prev)} → ${formatGoalTerm(next)}`);
          }
        }
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

  // Boolean flags worth surfacing to the LLM. Normalize through the same default-handling
  // layer as `configChangeSummary` so omitted-but-default-true values don't read as phantom
  // changes (these flags are dropped from serialized JSON when they hold their default `true`).
  for (const key of ["early_stop", "use_greedy_init", "only_active_terms"] as const) {
    const prev = normalizeProblemFieldForSummary(key, beforeProblem[key]);
    const next = normalizeProblemFieldForSummary(key, afterProblem[key]);
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

/**
 * Strip server-derived fields from a goal_terms entry so the diff only
 * surfaces user-edited changes. `rank` is re-stamped by the backend on
 * every save (e.g. _rebuild_goal_terms), `evidence_item_ids` and
 * `ambiguity_note` are LLM-managed — none of these are knobs the
 * participant turns in the panel JSON.
 */
function normalizeGoalTermForCompare(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const obj = value as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  if (typeof obj.weight === "number") out.weight = obj.weight;
  if (typeof obj.type === "string" && obj.type) out.type = obj.type;
  if (typeof obj.locked === "boolean") out.locked = obj.locked;
  if (obj.properties !== undefined) {
    const props = obj.properties;
    if (props && typeof props === "object" && !Array.isArray(props)) {
      const cleaned: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(props as Record<string, unknown>)) {
        if (v === null || v === undefined) continue;
        if (Array.isArray(v) && v.length === 0) continue;
        if (typeof v === "object" && !Array.isArray(v) && Object.keys(v as object).length === 0) continue;
        cleaned[k] = v;
      }
      if (Object.keys(cleaned).length > 0) out.properties = cleaned;
    }
  }
  return out;
}

/**
 * Per-field diff lines for a goal_terms entry. Returns one line per
 * changed field (weight/type/locked, plus per-property changes under
 * `properties`). Surfaces concrete transitions like
 * "goal term value_emphasis: weight 5 → 7" instead of an opaque whole-
 * entry stableJSON diff.
 */
function goalTermFieldDiffLines(
  key: string,
  prev: Record<string, unknown>,
  next: Record<string, unknown>,
): string[] {
  const out: string[] = [];
  const fieldKeys = new Set<string>([...Object.keys(prev), ...Object.keys(next)]);
  for (const field of [...fieldKeys].sort()) {
    if (field === "properties") continue;
    const pv = prev[field];
    const nv = next[field];
    if (stableJSON(pv) === stableJSON(nv)) continue;
    out.push(`goal term ${key}: ${field} ${formatScalar(pv)} → ${formatScalar(nv)}`);
  }
  const prevProps = recordOrNull(prev.properties) ?? {};
  const nextProps = recordOrNull(next.properties) ?? {};
  const propKeys = new Set<string>([...Object.keys(prevProps), ...Object.keys(nextProps)]);
  for (const prop of [...propKeys].sort()) {
    const pv = prevProps[prop];
    const nv = nextProps[prop];
    if (stableJSON(pv) === stableJSON(nv)) continue;
    out.push(`goal term ${key}: ${prop} ${formatScalar(pv)} → ${formatScalar(nv)}`);
  }
  return out;
}

function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "on" : "off";
  if (typeof value === "number" || typeof value === "string") return String(value);
  return JSON.stringify(value);
}

function normalizeProblemFieldForSummary(key: string, value: unknown): unknown {
  if (key === "only_active_terms" || key === "early_stop" || key === "use_greedy_init") {
    // These boolean fields default to `true` in `parseBaseProblemConfig` and the serializer
    // deletes them when they are `true` (only persisting an explicit `false`). Treat
    // missing/undefined and `true` as equivalent so we don't report phantom "on → —"
    // changes when the user saved a panel that simply omits the default.
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
