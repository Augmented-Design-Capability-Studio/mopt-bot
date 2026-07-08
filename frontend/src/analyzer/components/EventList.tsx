import { useEffect, useMemo, useRef, useState } from "react";

import { formatClock } from "../lib/format";
import type { TimelineRow } from "../lib/types";

const CODE_COLORS = ["#ef4444", "#f59e0b", "#10b981", "#3b82f6", "#8b5cf6", "#ec4899"];

interface EventListProps {
  rows: TimelineRow[];
  playhead: number;
  offsetSet: boolean;
  onSeek: (videoPos: number) => void;
  onAddCode: (label: string, color: string) => void;
  onSaveNote: (row: TimelineRow, text: string) => void;
  onDeleteAnnotation: (annotationId: number) => void;
}

function JsonCell({ value, label }: { value: string | null; label: string }) {
  if (!value) return <span className="muted">·</span>;
  return (
    <details>
      <summary style={{ cursor: "pointer", fontSize: "0.75rem" }}>{label}</summary>
      <pre style={{ maxHeight: 220, overflow: "auto", fontSize: "0.72rem", whiteSpace: "pre-wrap" }}>
        {value}
      </pre>
    </details>
  );
}

export function EventList({
  rows,
  playhead,
  offsetSet,
  onSeek,
  onAddCode,
  onSaveNote,
  onDeleteAnnotation,
}: EventListProps) {
  const [codeLabel, setCodeLabel] = useState("");
  const [codeColor, setCodeColor] = useState(CODE_COLORS[0]);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const activeRowRef = useRef<HTMLTableRowElement | null>(null);

  const activeIndex = useMemo(() => {
    if (!offsetSet) return -1;
    let idx = -1;
    for (let i = 0; i < rows.length; i += 1) {
      const vp = rows[i].video_pos;
      if (vp != null && vp <= playhead) idx = i;
      else if (vp != null && vp > playhead) break;
    }
    return idx;
  }, [rows, playhead, offsetSet]);

  useEffect(() => {
    activeRowRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeIndex]);

  const isManual = (r: TimelineRow) => r.annotation_id != null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", minHeight: 0 }}>
      <div style={{ display: "flex", gap: "0.35rem", alignItems: "center", flexWrap: "wrap" }}>
        <input
          type="text"
          placeholder="coded action label…"
          value={codeLabel}
          onChange={(e) => setCodeLabel(e.target.value)}
          style={{ fontSize: "0.8rem", minWidth: 180 }}
        />
        {CODE_COLORS.map((c) => (
          <button
            key={c}
            type="button"
            title={c}
            onClick={() => setCodeColor(c)}
            style={{
              width: 18,
              height: 18,
              borderRadius: 4,
              background: c,
              border: codeColor === c ? "2px solid #111" : "1px solid #999",
              cursor: "pointer",
            }}
          />
        ))}
        <button
          type="button"
          style={{ fontSize: "0.8rem", padding: "0.25rem 0.5rem" }}
          disabled={!codeLabel.trim()}
          onClick={() => {
            onAddCode(codeLabel.trim(), codeColor);
            setCodeLabel("");
          }}
        >
          Add coded action @ {formatClock(playhead)}
        </button>
      </div>

      <div style={{ overflow: "auto", flex: 1, minHeight: 0 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
          <thead>
            <tr style={{ textAlign: "left", position: "sticky", top: 0, background: "var(--bg, #fff)" }}>
              <th>t+</th>
              <th>vid</th>
              <th>type</th>
              <th>label</th>
              <th>summary</th>
              <th>def Δ</th>
              <th>cfg Δ</th>
              <th>run</th>
              <th>note</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const key = `${r.kind}:${r.row_ref ?? r.annotation_id ?? i}`;
              const manual = isManual(r);
              const active = i === activeIndex;
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
                        : undefined,
                    cursor: r.video_pos != null ? "pointer" : "default",
                  }}
                  onClick={() => {
                    if (r.video_pos != null) onSeek(r.video_pos);
                  }}
                >
                  <td style={{ whiteSpace: "nowrap" }}>{formatClock(r.time_since_start)}</td>
                  <td style={{ whiteSpace: "nowrap" }} className="muted">
                    {r.video_pos != null ? formatClock(r.video_pos) : "·"}
                  </td>
                  <td>
                    {manual && r.color ? (
                      <span style={{ color: r.color, fontWeight: 600 }}>{r.event_type}</span>
                    ) : (
                      r.event_type
                    )}
                  </td>
                  <td>{r.label}</td>
                  <td style={{ maxWidth: 320 }}>
                    <div style={{ maxHeight: active ? "none" : 60, overflow: "hidden" }}>{r.summary}</div>
                  </td>
                  <td style={{ maxWidth: 140 }}>
                    <JsonCell value={r.definition_change} label="def" />
                  </td>
                  <td style={{ maxWidth: 140 }}>
                    <JsonCell value={r.config_change} label="cfg" />
                  </td>
                  <td style={{ maxWidth: 140 }}>
                    <JsonCell value={r.latest_run} label="result" />
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
    </div>
  );
}
