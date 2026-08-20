import type { CSSProperties, ReactNode } from "react";

import type { ConfigDiff, ConfigFieldChange } from "../lib/types";

/** Graphic rendering of a row's structured config diff: one small chip per
 * changed goal term / solver knob, instead of a raw JSON dump. Tooltips carry
 * the exact values; the full config JSON stays in the row's expand. */

function chip(color: string): CSSProperties {
  return {
    display: "inline-block",
    padding: "0.05rem 0.35rem",
    margin: "0.06rem 0.12rem 0.06rem 0",
    borderRadius: 6,
    border: `1px solid ${color}55`,
    background: `${color}18`,
    color,
    fontSize: "0.68rem",
    fontWeight: 600,
    whiteSpace: "nowrap",
  };
}

const TERM_COLOR = "#b45309"; // amber — a field of an existing term changed
const ADD_COLOR = "#059669"; // green — term added
const REMOVE_COLOR = "#dc2626"; // red — term removed
const ALGO_COLOR = "#7c3aed"; // violet — algorithm switched
const PARAM_COLOR = "#0369a1"; // blue — solver knob tuned
const OTHER_COLOR = "#6b7280"; // gray — unmodeled panel change

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Short field label inside a term chip: `w 80→160`, `hard`, `r 2→1`, `detail ✎`. */
function fieldPart(c: ConfigFieldChange): string {
  switch (c.field) {
    case "weight":
      return `w ${fmt(c.from)}→${fmt(c.to)}`;
    case "type":
      return `${fmt(c.from)}→${fmt(c.to)}`;
    case "rank":
      return `r ${fmt(c.from)}→${fmt(c.to)}`;
    case "properties":
      return "detail ✎";
    default:
      return `${c.field} ${fmt(c.from)}→${fmt(c.to)}`;
  }
}

export function ConfigDiffChips({ diff }: { diff: ConfigDiff | null }) {
  if (!diff) return <span className="muted">·</span>;
  const chips: ReactNode[] = [];

  for (const a of diff.added ?? []) {
    const bits = [
      a.weight != null ? `w${fmt(a.weight)}` : null,
      a.type ?? null,
      a.rank != null ? `r${fmt(a.rank)}` : null,
    ].filter(Boolean);
    chips.push(
      <span key={`add:${a.term}`} style={chip(ADD_COLOR)} title={`goal term added: ${a.term}${bits.length ? ` (${bits.join(", ")})` : ""}`}>
        + {a.term}
      </span>,
    );
  }
  for (const t of diff.removed ?? []) {
    chips.push(
      <span key={`rm:${t}`} style={chip(REMOVE_COLOR)} title={`goal term removed: ${t}`}>
        − {t}
      </span>,
    );
  }
  for (const t of diff.terms ?? []) {
    const parts = t.changes.map(fieldPart).join(" · ");
    const detail = t.changes
      .map((c) => `${c.field}: ${fmt(c.from)} → ${fmt(c.to)}`)
      .join("\n");
    chips.push(
      <span key={`t:${t.term}`} style={chip(TERM_COLOR)} title={`${t.term}\n${detail}`}>
        {t.term} · {parts}
      </span>,
    );
  }
  if (diff.algorithm) {
    chips.push(
      <span key="algo" style={chip(ALGO_COLOR)} title="search algorithm switched (params reset to the new solver's defaults)">
        algo {fmt(diff.algorithm.from)}→{fmt(diff.algorithm.to)}
      </span>,
    );
  }
  for (const p of diff.params ?? []) {
    const isObj = typeof p.from === "object" || typeof p.to === "object";
    chips.push(
      <span key={`p:${p.field}`} style={chip(PARAM_COLOR)} title={`${p.field}: ${fmt(p.from)} → ${fmt(p.to)}`}>
        {isObj ? `${p.field} ✎` : `${p.field} ${fmt(p.from)}→${fmt(p.to)}`}
      </span>,
    );
  }
  if (diff.other) {
    chips.push(
      <span key="other" style={chip(OTHER_COLOR)} title="config changed outside the modeled fields">
        cfg ✎
      </span>,
    );
  }

  if (!chips.length) return <span className="muted">·</span>;
  return <div style={{ display: "flex", flexWrap: "wrap", maxWidth: 190 }}>{chips}</div>;
}
