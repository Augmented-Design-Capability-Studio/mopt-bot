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
    const previous = JSON.stringify(beforeProblem[key] ?? null);
    const next = JSON.stringify(afterProblem[key] ?? null);
    if (previous !== next) changed.push(key);
  }

  return changed.length === 0 ? "no keys changed" : changed.join(", ");
}
