import type { RunVisualization } from "@shared/api";

type ItemRow = {
  id: number;
  weight: number;
  value: number;
  selected: boolean;
};

export function KnapsackSelectionViz({ visualization }: { visualization: RunVisualization }) {
  const payload = visualization.payload ?? {};
  const items = Array.isArray(payload.items) ? (payload.items as unknown[]) : [];
  const capacity = typeof payload.capacity === "number" ? payload.capacity : null;
  const totalWeight = typeof payload.total_weight === "number" ? payload.total_weight : null;
  const totalValue = typeof payload.total_value === "number" ? payload.total_value : null;
  const feasible = typeof payload.feasible === "boolean" ? payload.feasible : null;

  const rows: ItemRow[] = items
    .map((raw) => {
      if (raw === null || typeof raw !== "object") return null;
      const o = raw as Record<string, unknown>;
      const id = typeof o.id === "number" ? o.id : Number(o.id);
      const weight = typeof o.weight === "number" ? o.weight : Number(o.weight);
      const value = typeof o.value === "number" ? o.value : Number(o.value);
      const selected = Boolean(o.selected);
      if (!Number.isFinite(id) || !Number.isFinite(weight) || !Number.isFinite(value)) return null;
      return { id, weight, value, selected };
    })
    .filter((r): r is ItemRow => r !== null);

  return (
    <div className="knapsack-viz" style={{ marginTop: "0.5rem" }}>
      <div className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.35rem" }}>
        {capacity != null ? (
          <>
            Capacity <span className="mono">{capacity}</span>
            {totalWeight != null ? (
              <>
                {" "}
                · packed weight <span className="mono">{totalWeight.toFixed(1)}</span>
              </>
            ) : null}
            {totalValue != null ? (
              <>
                {" "}
                · total value <span className="mono">{totalValue.toFixed(1)}</span>
              </>
            ) : null}
            {feasible != null ? (
              <>
                {" "}
                · <span className="mono">{feasible ? "feasible" : "infeasible"}</span>
              </>
            ) : null}
          </>
        ) : (
          "Knapsack selection"
        )}
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="mono" style={{ width: "100%", fontSize: "0.78rem", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border)" }}>
              <th style={{ padding: "0.25rem 0.4rem" }}>#</th>
              <th style={{ padding: "0.25rem 0.4rem" }}>w</th>
              <th style={{ padding: "0.25rem 0.4rem" }}>v</th>
              <th style={{ padding: "0.25rem 0.4rem" }}>sel</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.id}
                style={{
                  borderBottom: "1px solid var(--border)",
                  background: r.selected ? "rgba(80, 160, 120, 0.12)" : undefined,
                }}
              >
                <td style={{ padding: "0.2rem 0.4rem" }}>{r.id}</td>
                <td style={{ padding: "0.2rem 0.4rem" }}>{r.weight}</td>
                <td style={{ padding: "0.2rem 0.4rem" }}>{r.value}</td>
                <td style={{ padding: "0.2rem 0.4rem" }}>{r.selected ? "1" : "0"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 ? <p className="muted">No item rows in visualization payload.</p> : null}
    </div>
  );
}
