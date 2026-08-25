import type { CSSProperties } from "react";
import { useState } from "react";

import { REASON_VALUES } from "../lib/facets";
import type { OutcomeDelta, ReasonSuggestion, TimelineRow } from "../lib/types";

/** Improvement-REASON labeling cell — run rows (why the canonical cost moved
 * vs the previous run) and formulation-jump exchanges. Accepted reasons live in
 * ONE `reason` annotation per row ({reasons: [...], note}); suggestions come
 * from the deterministic evidence and the (separate) LLM verification cache. */

interface ReasonCellProps {
  row: TimelineRow;
  /** Persist the row's reason set (empty list deletes the annotation). */
  onSave: (row: TimelineRow, reasons: string[], note: string | null) => void;
  /** Reject a suggested reason for good (persisted server-side). */
  onDismiss: (row: TimelineRow, reason: string) => void;
}

const SOURCE_COLOR: Record<string, string> = {
  auto: "#0369a1", // mechanical evidence
  llm: "#8b5cf6", // LLM-only verdict
  "auto+llm": "#059669", // both agree — strongest signal
};

function chip(color: string, solid: boolean): CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 2,
    padding: "0.02rem 0.3rem",
    margin: "0.06rem 0.12rem 0.06rem 0",
    borderRadius: 6,
    border: `1px ${solid ? "solid" : "dashed"} ${color}`,
    background: solid ? `${color}22` : "transparent",
    color,
    fontSize: "0.68rem",
    fontWeight: 600,
    whiteSpace: "nowrap",
  };
}

function fmtDelta(v: number): string {
  return (v > 0 ? "+" : "") + Math.round(v).toLocaleString();
}

/** Compact Δ-vs-previous-run evidence line (run rows only). */
export function OutcomeDeltaLine({ delta }: { delta: OutcomeDelta }) {
  const parts: string[] = [];
  if (delta.cost_delta != null) parts.push(`Δcost ${fmtDelta(delta.cost_delta)}`);
  if (delta.feasible_from != null && delta.feasible_from !== delta.feasible_to) {
    parts.push(delta.feasible_to ? "→ feasible ✓" : "→ INFEASIBLE");
  }
  for (const mv of delta.movers.slice(0, 3)) parts.push(`${mv.term} ${fmtDelta(mv.delta)}`);
  if (!parts.length) return null;
  return (
    <div
      className="muted"
      style={{ fontSize: "0.68rem", marginTop: "0.15rem" }}
      title="Change vs the PREVIOUS run: total canonical cost, feasibility, and the goal terms whose cost contribution moved most"
    >
      {parts.join(" · ")}
    </div>
  );
}

export function ReasonCell({ row, onSave, onDismiss }: ReasonCellProps) {
  const accepted = row.reasons?.reasons ?? [];
  const note = row.reasons?.note ?? "";
  const [noteDraft, setNoteDraft] = useState<string | null>(null);
  const suggestions = (row.reason_suggestions ?? []).filter((s) => !accepted.includes(s.reason));

  function save(nextReasons: string[], nextNote: string | null) {
    onSave(row, nextReasons, nextNote && nextNote.trim() ? nextNote.trim() : null);
  }

  return (
    <div style={{ minWidth: 170, maxWidth: 230 }}>
      {accepted.length === 1 && accepted[0] === "feasibility-fix" ? (
        <span
          title="feasibility-fix is an outcome qualifier — pair it with the causal change that produced feasibility (weight-rebalance, term-type-change, …)"
          style={{ color: "#d97706", fontSize: "0.72rem", fontWeight: 700, marginRight: 3, cursor: "help" }}
        >
          ⚠
        </span>
      ) : null}
      {accepted.map((r) => (
        <span key={r} style={chip("#111827", true)}>
          {r}
          <button
            type="button"
            title="remove reason"
            onClick={() => save(accepted.filter((x) => x !== r), note)}
            style={{ border: "none", background: "none", cursor: "pointer", padding: 0, fontSize: "0.68rem" }}
          >
            ✕
          </button>
        </span>
      ))}
      {suggestions.map((s: ReasonSuggestion) => (
        <span
          key={s.reason}
          style={chip(SOURCE_COLOR[s.source] ?? "#6b7280", false)}
          title={
            (s.source === "auto"
              ? "mechanical evidence"
              : s.source === "llm"
                ? "LLM verdict"
                : "mechanical + LLM agree") + (s.rationale ? ` — ${s.rationale}` : "")
          }
        >
          <button
            type="button"
            title="accept reason"
            onClick={() => save([...accepted, s.reason], note)}
            style={{ border: "none", background: "none", cursor: "pointer", padding: 0,
                     color: "inherit", fontSize: "0.68rem", fontWeight: 600 }}
          >
            ＋{s.reason}
            {s.source !== "auto" ? "✨" : ""}
          </button>
          <button
            type="button"
            title="reject suggestion (won't come back)"
            onClick={() => onDismiss(row, s.reason)}
            style={{ border: "none", background: "none", cursor: "pointer", padding: 0,
                     color: "#dc2626", fontSize: "0.68rem", fontWeight: 700 }}
          >
            ✕
          </button>
        </span>
      ))}
      <select
        value=""
        title="add a reason manually"
        onChange={(e) => {
          if (e.target.value && !accepted.includes(e.target.value)) save([...accepted, e.target.value], note);
        }}
        style={{ fontSize: "0.66rem", maxWidth: 90, color: "#9ca3af" }}
      >
        <option value="">+ reason…</option>
        {REASON_VALUES.filter((r) => !accepted.includes(r)).map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
      {accepted.length ? (
        <input
          value={noteDraft ?? note}
          placeholder="why? (note)"
          onChange={(e) => setNoteDraft(e.target.value)}
          onBlur={() => {
            if (noteDraft != null && noteDraft !== note) save(accepted, noteDraft);
            setNoteDraft(null);
          }}
          style={{ width: "100%", fontSize: "0.68rem", marginTop: "0.15rem" }}
        />
      ) : null}
    </div>
  );
}
