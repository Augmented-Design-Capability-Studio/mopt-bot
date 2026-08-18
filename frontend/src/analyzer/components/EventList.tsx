import type { CSSProperties, ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import { formatClock } from "../lib/format";
import type { ChangeTag, TimelineRow } from "../lib/types";
import { ChangeTagCell } from "./ChangeTagCell";

interface EventListProps {
  rows: TimelineRow[];
  /** Goal-term keys for this session (the change's goal-term dropdown). */
  goalTermKeys: string[];
  playhead: number;
  offsetSet: boolean;
  /** Show the video-anchored columns (vid position, video-adjusted t+). */
  videoMode: boolean;
  onSeek: (videoPos: number) => void;
  /** Create a coded change on a row. */
  onAddChange: (row: TimelineRow, change: Omit<ChangeTag, "id">) => void;
  /** Edit an existing coded change. */
  onEditChange: (annotationId: number, change: Omit<ChangeTag, "id">) => void;
  onSaveNote: (row: TimelineRow, text: string) => void;
  onDeleteAnnotation: (annotationId: number) => void;
}

function JsonCell({
  value,
  label,
  defaultOpen,
}: {
  value: string | null;
  label: string;
  defaultOpen?: boolean;
}) {
  if (!value) return <span className="muted">·</span>;
  return (
    <details open={defaultOpen}>
      <summary style={{ cursor: "pointer", fontSize: "0.75rem" }}>{label}</summary>
      <pre style={{ maxHeight: 260, overflow: "auto", fontSize: "0.72rem", whiteSpace: "pre-wrap" }}>
        {value}
      </pre>
    </details>
  );
}

function pill(color: string): CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 2,
    padding: "0.05rem 0.4rem",
    borderRadius: 999,
    border: `1px solid ${color}`,
    background: `${color}1f`,
    color,
    fontSize: "0.68rem",
    fontWeight: 700,
    whiteSpace: "nowrap",
  };
}

/** Outcome (canonical cost) badge on run rows, formulation-score badge on
 * agent-exchange rows; the session-best of each is starred and brightly tinted. */
function ScoreBadges({ r }: { r: TimelineRow }) {
  const badges: ReactNode[] = [];
  if (r.kind === "run" && r.canonical_cost != null) {
    const best = !!r.best_canonical;
    badges.push(
      <span
        key="canon"
        style={pill(best ? "#eab308" : "#9ca3af")}
        title={
          "Canonical cost — the run's schedule re-scored under the official objective (lower is better)." +
          (r.canonical_feasible === false ? " Infeasible: breaks a hard constraint on most traffic draws." : "") +
          (best ? " Best canonical result in this session." : "")
        }
      >
        {best ? "★ " : ""}canon {Math.round(r.canonical_cost).toLocaleString()}
        {r.canonical_feasible === false ? " ⚠" : ""}
      </span>,
    );
  }
  if (r.kind === "message" && r.formulation_score != null) {
    const best = !!r.best_formulation;
    badges.push(
      <span
        key="form"
        style={pill(best ? "#10b981" : "#9ca3af")}
        title={
          "Formulation score (0–11) — how well this exchange's config captures the true problem (higher is better)." +
          (best ? " Session-peak formulation." : "")
        }
      >
        {best ? "★ " : ""}form {r.formulation_score}/11
      </span>,
    );
  }
  if (!badges.length) return null;
  return <div style={{ display: "flex", gap: 4, marginBottom: "0.3rem", flexWrap: "wrap" }}>{badges}</div>;
}

export function EventList({
  rows,
  goalTermKeys,
  playhead,
  offsetSet,
  videoMode,
  onSeek,
  onAddChange,
  onEditChange,
  onSaveNote,
  onDeleteAnnotation,
}: EventListProps) {
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(() => new Set());
  const activeRowRef = useRef<HTMLTableRowElement | null>(null);

  function toggleExpanded(key: string) {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const activeIndex = useMemo(() => {
    if (!offsetSet || !videoMode) return -1;
    let idx = -1;
    for (let i = 0; i < rows.length; i += 1) {
      const vp = rows[i].video_pos;
      if (vp != null && vp <= playhead) idx = i;
      else if (vp != null && vp > playhead) break;
    }
    return idx;
  }, [rows, playhead, offsetSet, videoMode]);

  useEffect(() => {
    activeRowRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeIndex]);

  const isManual = (r: TimelineRow) => r.annotation_id != null;

  return (
    <div style={{ overflow: "auto", flex: 1, minHeight: 0 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
        <thead>
          <tr style={{ textAlign: "left", position: "sticky", top: 0, background: "var(--bg, #fff)" }}>
            <th>t</th>
            {videoMode ? <th>t+</th> : null}
            {videoMode ? <th>vid</th> : null}
            <th>type</th>
            <th>label</th>
            <th>summary</th>
            <th>def Δ</th>
            <th>cfg Δ</th>
            <th>run</th>
            <th>coding — changes (origin · type · goal term · effect)</th>
            <th>note</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const key = `${r.kind}:${r.row_ref ?? r.annotation_id ?? i}`;
            const manual = isManual(r);
            const active = i === activeIndex;
            // Captured ✓/✗ is meaningful wherever we derived config state:
            // snapshot rows and assistant chat turns (which carry pre_turn_state).
            const capturedKnown = r.kind === "snapshot" || r.kind === "message";
            return (
              <tr
                key={key}
                ref={active ? activeRowRef : undefined}
                style={{
                  borderTop: "1px solid var(--border, #eee)",
                  background: active
                    ? "rgba(59,130,246,0.15)"
                    : manual && r.color
                      ? `${r.color}22`
                      : r.best_canonical
                        ? "rgba(234,179,8,0.12)"
                        : r.best_formulation
                          ? "rgba(16,185,129,0.10)"
                          : undefined,
                  cursor: videoMode && r.video_pos != null ? "pointer" : "default",
                }}
                onClick={() => {
                  if (videoMode && r.video_pos != null) onSeek(r.video_pos);
                }}
              >
                <td style={{ whiteSpace: "nowrap" }}>{r.t_rel != null ? formatClock(r.t_rel) : "·"}</td>
                {videoMode ? (
                  <td style={{ whiteSpace: "nowrap" }} className="muted">
                    {r.time_since_start != null ? formatClock(r.time_since_start) : "·"}
                  </td>
                ) : null}
                {videoMode ? (
                  <td style={{ whiteSpace: "nowrap" }} className="muted">
                    {r.video_pos != null ? formatClock(r.video_pos) : "·"}
                  </td>
                ) : null}
                <td>
                  {manual && r.color ? (
                    <span style={{ color: r.color, fontWeight: 600 }}>{r.event_type}</span>
                  ) : (
                    r.event_type
                  )}
                </td>
                <td>{r.label}</td>
                {(() => {
                  const summary = r.summary ?? "";
                  const expanded = active || expandedKeys.has(key);
                  const hasState = !!(r.problem_def || r.problem_config);
                  const prompt = r.user_prompt ?? "";
                  const longText =
                    summary.length + prompt.length > 140 || summary.includes("\n") || prompt.includes("\n");
                  const canExpand = longText || hasState;
                  return (
                    <td style={{ maxWidth: 340 }}>
                      <ScoreBadges r={r} />
                      {r.user_prompt ? (
                        // The user's own words are always shown in full — never
                        // truncated — so no information is lost in the exchange.
                        <div
                          style={{
                            marginBottom: "0.3rem",
                            padding: "0.15rem 0.4rem",
                            borderLeft: "3px solid #3b82f6",
                            background: "rgba(59,130,246,0.06)",
                            whiteSpace: "pre-wrap",
                          }}
                        >
                          <span style={{ fontWeight: 600, color: "#3b82f6", fontSize: "0.72rem" }}>user ▸ </span>
                          {r.user_prompt}
                        </div>
                      ) : null}
                      <div
                        style={{
                          maxHeight: expanded ? "none" : 60,
                          overflow: "hidden",
                          whiteSpace: "pre-wrap",
                        }}
                      >
                        {r.user_prompt ? (
                          <span style={{ fontWeight: 600, color: "#8b5cf6", fontSize: "0.72rem" }}>agent ▸ </span>
                        ) : null}
                        {summary}
                      </div>
                      {canExpand ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleExpanded(key);
                          }}
                          style={{
                            marginTop: "0.15rem",
                            border: "1px solid #3b82f6",
                            borderRadius: 4,
                            background: "rgba(59,130,246,0.08)",
                            cursor: "pointer",
                            fontSize: "0.72rem",
                            fontWeight: 600,
                            color: "#3b82f6",
                            padding: "0.05rem 0.4rem",
                          }}
                        >
                          {expanded
                            ? "▲ collapse"
                            : hasState
                              ? "▼ expand (message + problem state)"
                              : "▼ expand"}
                        </button>
                      ) : null}
                      {expanded && hasState ? (
                        <div style={{ marginTop: "0.35rem", display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                          <JsonCell value={r.problem_def} label="problem def (this turn)" defaultOpen />
                          <JsonCell value={r.problem_config} label="config (this turn)" defaultOpen />
                        </div>
                      ) : null}
                    </td>
                  );
                })()}
                <td style={{ maxWidth: 140 }}>
                  <JsonCell value={r.definition_change} label="def" />
                </td>
                <td style={{ maxWidth: 140 }}>
                  <JsonCell value={r.config_change} label="cfg" />
                </td>
                <td style={{ maxWidth: 140 }}>
                  <JsonCell value={r.latest_run} label="result" />
                </td>
                <td onClick={(e) => e.stopPropagation()}>
                  {r.codeable ? (
                    <ChangeTagCell
                      changes={r.changes}
                      suggested={r.suggested_changes}
                      goalTermKeys={goalTermKeys}
                      capturedTerms={r.captured_terms}
                      capturedKnown={capturedKnown}
                      onAdd={(change) => onAddChange(r, change)}
                      onEdit={onEditChange}
                      onDelete={onDeleteAnnotation}
                    />
                  ) : (
                    <span className="muted">·</span>
                  )}
                </td>
                <td style={{ minWidth: 140 }} onClick={(e) => e.stopPropagation()}>
                  {editingKey === key ? (
                    <input
                      autoFocus
                      value={noteDraft}
                      onChange={(e) => setNoteDraft(e.target.value)}
                      onBlur={() => {
                        onSaveNote(r, noteDraft);
                        setEditingKey(null);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          onSaveNote(r, noteDraft);
                          setEditingKey(null);
                        } else if (e.key === "Escape") {
                          setEditingKey(null);
                        }
                      }}
                      style={{ width: "100%", fontSize: "0.78rem" }}
                    />
                  ) : (
                    <span
                      style={{ cursor: "text", color: r.note ? undefined : "#999" }}
                      onClick={() => {
                        setEditingKey(key);
                        setNoteDraft(r.note ?? "");
                      }}
                    >
                      {r.note ?? "add note…"}
                    </span>
                  )}
                </td>
                <td onClick={(e) => e.stopPropagation()}>
                  {manual && r.annotation_id != null ? (
                    <button
                      type="button"
                      title="delete"
                      onClick={() => onDeleteAnnotation(r.annotation_id!)}
                      style={{ fontSize: "0.75rem", cursor: "pointer" }}
                    >
                      ✕
                    </button>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
