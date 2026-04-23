import { useMemo, useState } from "react";
import type { ProblemVizProps } from "@problemConfig/problemModule";

type ItemRow = {
  id: number;
  weight: number;
  value: number;
  selected: boolean;
};

type SortKey = "id" | "weight" | "value" | "density" | "selected";
type SortDirection = "asc" | "desc";

export function KnapsackSelectionViz({ currentRun }: ProblemVizProps) {
  const visualization = currentRun.result?.visualization;
  if (!visualization) {
    return <div className="muted">No visualization data available for this run.</div>;
  }

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

  const [sortKey, setSortKey] = useState<SortKey>("selected");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  const selectedCount = rows.filter((r) => r.selected).length;
  const sortedRows = useMemo(() => {
    const compareByKey = (a: ItemRow, b: ItemRow, key: SortKey): number => {
      if (key === "selected") return Number(a.selected) - Number(b.selected);
      if (key === "density") {
        const densityA = a.weight > 0 ? a.value / a.weight : Number.NEGATIVE_INFINITY;
        const densityB = b.weight > 0 ? b.value / b.weight : Number.NEGATIVE_INFINITY;
        return densityA - densityB;
      }
      if (key === "id") return a.id - b.id;
      if (key === "weight") return a.weight - b.weight;
      return a.value - b.value;
    };

    const sorted = [...rows].sort((a, b) => {
      const diff = compareByKey(a, b, sortKey);
      if (diff !== 0) return sortDirection === "asc" ? diff : -diff;
      return a.id - b.id;
    });

    return sorted;
  }, [rows, sortDirection, sortKey]);

  const handleSort = (nextKey: SortKey) => {
    if (sortKey === nextKey) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextKey);
    setSortDirection(nextKey === "selected" ? "desc" : "asc");
  };

  const sortLabel = (key: SortKey): string => {
    if (sortKey !== key) return "↕";
    return sortDirection === "asc" ? "↑" : "↓";
  };
  const hasCapacityAndWeight = capacity != null && totalWeight != null;
  const usageRaw = hasCapacityAndWeight && capacity > 0 ? (totalWeight / capacity) * 100 : null;
  const usagePct = usageRaw != null ? Math.max(0, Math.min(usageRaw, 100)) : null;
  const isOverCapacity = hasCapacityAndWeight ? totalWeight > capacity : false;

  return (
    <div className="knapsack-viz" style={{ marginTop: "0.5rem" }}>
      {feasible != null ? (
        <div
          style={{
            marginBottom: "0.6rem",
            padding: "0.6rem 0.75rem",
            borderRadius: "8px",
            border: `1px solid ${feasible ? "rgba(47, 128, 90, 0.7)" : "rgba(190, 60, 60, 0.75)"}`,
            background: feasible ? "rgba(47, 128, 90, 0.16)" : "rgba(190, 60, 60, 0.16)",
          }}
        >
          <div className="mono" style={{ fontSize: "0.95rem", fontWeight: 700 }}>
            {feasible ? "FEASIBLE" : "INFEASIBLE"}
          </div>
          <div style={{ fontSize: "0.8rem", marginTop: "0.2rem" }}>
            {feasible ? "Total weight is within capacity." : "Total weight exceeds capacity."}
          </div>
        </div>
      ) : null}

      {hasCapacityAndWeight && usagePct != null ? (
        <div style={{ marginBottom: "0.65rem" }}>
          <div
            style={{
              width: "100%",
              height: "9px",
              borderRadius: "999px",
              background: "rgba(255, 255, 255, 0.08)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${usagePct}%`,
                height: "100%",
                borderRadius: "999px",
                background: isOverCapacity ? "rgba(190, 60, 60, 0.95)" : "rgba(47, 128, 90, 0.95)",
              }}
            />
          </div>
          <div className="mono muted" style={{ fontSize: "0.72rem", marginTop: "0.2rem" }}>
            {totalWeight.toFixed(1)} / {capacity.toFixed(1)} ({usageRaw != null ? usageRaw.toFixed(1) : "0.0"}%)
          </div>
        </div>
      ) : null}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "0.45rem", marginBottom: "0.6rem" }}>
        <div style={{ border: "1px solid var(--border)", borderRadius: "6px", padding: "0.35rem 0.45rem" }}>
          <div className="muted" style={{ fontSize: "0.68rem" }}>Capacity</div>
          <div className="mono" style={{ fontSize: "0.82rem" }}>{capacity != null ? capacity.toFixed(1) : "n/a"}</div>
        </div>
        <div style={{ border: "1px solid var(--border)", borderRadius: "6px", padding: "0.35rem 0.45rem" }}>
          <div className="muted" style={{ fontSize: "0.68rem" }}>Packed Weight</div>
          <div className="mono" style={{ fontSize: "0.82rem" }}>{totalWeight != null ? totalWeight.toFixed(1) : "n/a"}</div>
        </div>
        <div style={{ border: "1px solid var(--border)", borderRadius: "6px", padding: "0.35rem 0.45rem" }}>
          <div className="muted" style={{ fontSize: "0.68rem" }}>Total Value</div>
          <div className="mono" style={{ fontSize: "0.82rem" }}>{totalValue != null ? totalValue.toFixed(1) : "n/a"}</div>
        </div>
        <div style={{ border: "1px solid var(--border)", borderRadius: "6px", padding: "0.35rem 0.45rem" }}>
          <div className="muted" style={{ fontSize: "0.68rem" }}>Selected</div>
          <div className="mono" style={{ fontSize: "0.82rem" }}>{selectedCount} / {rows.length}</div>
        </div>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table className="mono" style={{ width: "100%", fontSize: "0.78rem", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border)" }}>
              <th style={{ padding: "0.25rem 0.4rem" }}>
                <button type="button" onClick={() => handleSort("id")} style={{ all: "unset", cursor: "pointer" }}>
                  Item {sortLabel("id")}
                </button>
              </th>
              <th style={{ padding: "0.25rem 0.4rem", textAlign: "right" }}>
                <button type="button" onClick={() => handleSort("weight")} style={{ all: "unset", cursor: "pointer" }}>
                  Weight {sortLabel("weight")}
                </button>
              </th>
              <th style={{ padding: "0.25rem 0.4rem", textAlign: "right" }}>
                <button type="button" onClick={() => handleSort("value")} style={{ all: "unset", cursor: "pointer" }}>
                  Value {sortLabel("value")}
                </button>
              </th>
              <th style={{ padding: "0.25rem 0.4rem", textAlign: "right" }}>
                <button type="button" onClick={() => handleSort("density")} style={{ all: "unset", cursor: "pointer" }}>
                  Value/Wt. Ratio {sortLabel("density")}
                </button>
              </th>
              <th style={{ padding: "0.25rem 0.4rem" }}>
                <button type="button" onClick={() => handleSort("selected")} style={{ all: "unset", cursor: "pointer" }}>
                  Selected {sortLabel("selected")}
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((r, idx) => (
              <tr
                key={r.id}
                style={{
                  borderBottom: "1px solid var(--border)",
                  background: r.selected
                    ? "rgba(80, 160, 120, 0.16)"
                    : idx % 2 === 1
                      ? "rgba(255, 255, 255, 0.02)"
                      : undefined,
                }}
              >
                <td style={{ padding: "0.2rem 0.4rem" }}>{r.id}</td>
                <td style={{ padding: "0.2rem 0.4rem", textAlign: "right" }}>{r.weight.toFixed(1)}</td>
                <td style={{ padding: "0.2rem 0.4rem", textAlign: "right" }}>{r.value.toFixed(1)}</td>
                <td style={{ padding: "0.2rem 0.4rem", textAlign: "right" }}>
                  {r.weight > 0 ? (r.value / r.weight).toFixed(2) : "n/a"}
                </td>
                <td style={{ padding: "0.2rem 0.4rem" }}>
                  <span
                    style={{
                      display: "inline-block",
                      minWidth: "2.2rem",
                      textAlign: "center",
                      borderRadius: "999px",
                      padding: "0.05rem 0.42rem",
                      background: r.selected ? "rgba(47, 128, 90, 0.25)" : "rgba(120, 120, 120, 0.2)",
                    }}
                  >
                    {r.selected ? "yes" : "no"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 ? (
        <p className="muted">No items found in visualization payload. Check solver output format.</p>
      ) : null}
    </div>
  );
}
