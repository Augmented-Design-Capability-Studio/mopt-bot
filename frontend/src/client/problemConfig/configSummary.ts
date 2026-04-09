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

  return changed.length === 0 ? "no keys changed" : changed.join(", ");
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
