export function parseRoutesForSolver(raw: unknown): number[][] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null;

  const first = raw[0] as Record<string, unknown>;
  if (first && typeof first === "object" && "task_indices" in first) {
    const rows = [...raw] as { vehicle_index: number; task_indices: number[] }[];
    rows.sort((a, b) => a.vehicle_index - b.vehicle_index);
    return rows.map((row) => row.task_indices.map((taskIndex) => Number(taskIndex)));
  }

  return raw as number[][];
}
