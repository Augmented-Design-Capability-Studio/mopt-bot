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
  // Rerank cascade handling: dragging one term in the Config tab triggers
  // ``handleReorder`` (ProblemConfigBlocks.tsx) which auto-rewrites the
  // weights of EVERY objective/soft term to the suggested value for its
  // current rank position — not just the rank-shifted ones. ``hard`` and
  // ``custom`` weights are left alone by ``handleReorder`` (see the type
  // gate inside it). So from the diff, a weight change is treated as a
  // rerank cascade when:
  //   (a) the key's rank also changed in this save, OR
  //   (b) some rank changed in this save AND the key's type is
  //       ``objective``/``soft`` (handleReorder's rewrite scope).
  // Standalone weight tunes (no rerank in the save) and weight changes on
  // ``hard``/``custom`` terms are still surfaced as active edits. Type
  // changes are always active (handleReorder never touches type). The
  // full rerank event gets one consolidated "Priority order: ..." line.
  //
  // First pass: detect whether ANY rank changed in this save so the
  // weight-suppression decision below can see the full picture.
  let anyRankChanged = false;
  if (beforeGT && afterGT) {
    for (const key of Object.keys(afterGT)) {
      const prev = beforeGT[key];
      const next = afterGT[key];
      if (prev != null && next != null && rankOf(prev) !== rankOf(next)) {
        anyRankChanged = true;
        break;
      }
    }
  }
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
        // server-derived fields (evidence_item_ids, ambiguity_note) that
        // the participant can't see or change in the panel JSON; a raw
        // stableJSON diff would surface phantom changes whenever the
        // backend rebuilt the entry.
        const prevCmp = normalizeGoalTermForCompare(prev);
        const nextCmp = normalizeGoalTermForCompare(next);
        const rankChangedHere = rankOf(prev) !== rankOf(next);
        const prevTypeRaw = (prev as Record<string, unknown>)?.type;
        const prevType = typeof prevTypeRaw === "string" ? prevTypeRaw : "";
        // Cascade suppression: ``handleReorder`` (ProblemConfigBlocks.tsx)
        // rewrites weights for ALL objective/soft terms when any rerank
        // happens, and explicitly skips ``hard``/``custom`` types. So a
        // weight change is attributable to cascade iff the save involved
        // a rerank AND the key's type falls inside that rewrite scope.
        // Hard/custom weight changes are always user-driven.
        const suppressWeightAsCascade =
          anyRankChanged && (prevType === "objective" || prevType === "soft");
        if (stableJSON(prevCmp) !== stableJSON(nextCmp)) {
          const fieldLines = goalTermFieldDiffLines(
            key, prevCmp, nextCmp,
            { suppressWeight: suppressWeightAsCascade },
          );
          if (fieldLines.length > 0) {
            lines.push(...fieldLines);
          } else if (!rankChangedHere && !suppressWeightAsCascade) {
            // Defensive fallback. The remaining difference is in a field
            // ``goalTermFieldDiffLines`` skips on purpose — currently just
            // ``properties``, which is mirrored to a top-level field that
            // the outer top-level loop diffs separately. Only emit the
            // generic whole-entry bullet when the FORMATTED view of the
            // entry actually changed; otherwise we'd surface a phantom
            // "soft, weight 1 → soft, weight 1" line on a properties-only
            // delta.
            const prevText = formatGoalTerm(prev);
            const nextText = formatGoalTerm(next);
            if (prevText !== nextText) {
              lines.push(`goal term ${key}: ${prevText} → ${nextText}`);
            }
          }
        }
      }
    }
    if (anyRankChanged && afterGT) {
      const priorityLine = renderPriorityOrderLine(afterGT);
      if (priorityLine) lines.push(priorityLine);
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

  // Generic top-level non-scalar diff. The frontend's
  // `serializeBaseProblemConfig` rebuilds `goal_terms` entries from
  // `{weight, type, rank, locked}` only — properties (`driver_preferences`,
  // `locked_assignments`, etc.) live as TOP-LEVEL fields on the panel and
  // never make it into the rebuilt goal_terms entry, so the goal-term-level
  // diff above can't reach them. Iterate any top-level key not already
  // covered by the scalar / flag / goal_terms / weights paths and emit a
  // diff bullet when it changed. Problem-agnostic: any port whose panel
  // exposes a mirrored top-level carrier (e.g. VRPTW's `driver_preferences`,
  // a future port's custom rule list) automatically gets surfaced.
  const handledKeys = new Set<string>([
    "goal_terms",
    "weights",
    "constraint_types",
    "locked_goal_terms",
    "goal_term_order",
    "algorithm",
    "algorithm_params",
    "epochs",
    "pop_size",
    "random_seed",
    "max_shift_hours",
    "early_stop",
    "early_stop_patience",
    "early_stop_epsilon",
    "use_greedy_init",
    "only_active_terms",
  ]);
  const topLevelKeys = new Set<string>([
    ...Object.keys(beforeProblem),
    ...Object.keys(afterProblem),
  ]);
  for (const key of [...topLevelKeys].sort()) {
    if (handledKeys.has(key)) continue;
    const prev = normalizeProblemFieldForSummary(key, beforeProblem[key]);
    const next = normalizeProblemFieldForSummary(key, afterProblem[key]);
    if (prev == null && next == null) continue;
    if (stableJSON(prev) === stableJSON(next)) continue;
    lines.push(`${toParticipantLabel(key)}: ${formatScalar(prev)} → ${formatScalar(next)}`);
  }

  // Bullet-list format mirrors the "Answered open questions:" chat note
  // (see useClientSessionActions.ts: ``${headerLine}\n${quoteBlock}`` with
  // ``- "Q" → "A"`` rows). The chat post wraps this with a "Config edited:"
  // header line, so the joined output sits directly under it.
  return lines.length === 0
    ? "no settings changed"
    : `\n- ${lines.join("\n- ")}`;
}

function recordOrNull(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function rankOf(entry: unknown): number | null {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) return null;
  const r = (entry as Record<string, unknown>).rank;
  return typeof r === "number" && Number.isFinite(r) && r > 0 ? r : null;
}

/**
 * Render a single "Priority order: ..." line summarizing the new rank
 * order. Replaces per-key "rank N → M" bullets that would otherwise
 * surface every cascade-shifted term as its own noisy line. Keys ordered
 * by their ``rank`` in ``afterGT``.
 */
function renderPriorityOrderLine(afterGT: Record<string, unknown>): string {
  const ranked: Array<{ rank: number; key: string }> = [];
  for (const [key, entry] of Object.entries(afterGT)) {
    const r = rankOf(entry);
    if (r != null) ranked.push({ rank: r, key });
  }
  if (ranked.length === 0) return "";
  ranked.sort((a, b) => a.rank - b.rank || a.key.localeCompare(b.key));
  return `Priority order: ${ranked.map((r) => r.key).join(", ")}`;
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
  options: { suppressWeight?: boolean } = {},
): string[] {
  const out: string[] = [];
  const fieldKeys = new Set<string>([...Object.keys(prev), ...Object.keys(next)]);
  for (const field of [...fieldKeys].sort()) {
    // ``properties`` is structurally unreliable here: the frontend's
    // ``serializeBaseProblemConfig`` rebuilds each goal_terms entry from
    // ``{weight, type, rank, locked}`` only — it drops ``properties``
    // entirely on save. So ``next.properties`` is always undefined for
    // edits made via the panel, and any "→ —" bullet emitted from this
    // path is misleading. The canonical edit surface for property-mirrored
    // fields (driver_preferences, max_shift_hours, locked_assignments)
    // is the top-level ``problem.<field>`` carrier, which is diffed by
    // the outer top-level loop in ``configChangeDetailedSummary``.
    if (field === "properties") continue;
    // ``rank`` is handled separately at the top level — one consolidated
    // "Priority order: ..." line per save, not a per-key bullet, because a
    // single move cascades across multiple terms.
    if (field === "rank") continue;
    // ``suppressWeight``: this key's rank also changed in the save, so its
    // weight change is treated as a rerank cascade (the frontend's
    // ``handleReorder`` auto-rewrites soft/objective weights to suggested
    // values for the new rank). The priority-order line below covers the
    // whole event; surfacing a per-key weight bullet here would be noise.
    if (field === "weight" && options.suppressWeight) continue;
    const pv = prev[field];
    const nv = next[field];
    if (stableJSON(pv) === stableJSON(nv)) continue;
    out.push(`goal term ${key}: ${field} ${formatScalar(pv)} → ${formatScalar(nv)}`);
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
