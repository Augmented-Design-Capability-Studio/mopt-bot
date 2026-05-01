function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Extract run-time weights from either legacy `problem.weights` or
 * newer `problem.goal_terms[term].weight` shapes.
 */
export function extractRunWeights(problem: unknown): Record<string, number> {
  if (!isRecord(problem)) return {};

  const fromWeights = problem.weights;
  if (isRecord(fromWeights)) {
    const out: Record<string, number> = {};
    for (const [key, value] of Object.entries(fromWeights)) {
      const n = Number(value);
      if (Number.isFinite(n)) out[key] = n;
    }
    if (Object.keys(out).length > 0) return out;
  }

  const fromGoalTerms = problem.goal_terms;
  if (!isRecord(fromGoalTerms)) return {};
  const out: Record<string, number> = {};
  for (const [key, entry] of Object.entries(fromGoalTerms)) {
    if (!isRecord(entry)) continue;
    const n = Number(entry.weight);
    if (Number.isFinite(n)) out[key] = n;
  }
  return out;
}
