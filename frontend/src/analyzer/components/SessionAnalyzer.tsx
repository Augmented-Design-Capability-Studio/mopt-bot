import { useMemo, useState } from "react";

import { buildTimelineFromArchive } from "../lib/timeline";
import type { SessionArchive } from "../lib/types";

type SessionAnalyzerProps = {
  archive: SessionArchive;
};

type Tab = "timeline" | "raw";

function findRecord<T extends { id: number | string }>(items: T[] | undefined, id: unknown): T | null {
  if (!Array.isArray(items)) return null;
  return items.find((item) => item.id === id) ?? null;
}

export function SessionAnalyzer({ archive }: SessionAnalyzerProps) {
  const [tab, setTab] = useState<Tab>("timeline");
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);

  const timelineRows = useMemo(() => buildTimelineFromArchive(archive), [archive]);
  const rawText = useMemo(() => JSON.stringify(archive, null, 2), [archive]);

  const header = useMemo(() => {
    const sess = archive.session;
    return {
      ver: archive.export_schema_version,
      sid: sess.id,
      mc: archive.messages.length,
      rc: archive.runs.length,
      sc: archive.snapshots.length,
      tc: timelineRows.length,
      participant: sess.participant_number ?? "—",
      workflow: sess.workflow_mode,
      problem: sess.test_problem_id ?? "—",
    };
  }, [archive, timelineRows.length]);

  const detailJson = useMemo(() => {
    if (selectedIdx === null) return null;
    const row = timelineRows[selectedIdx];
    if (!row) return null;
    if (row.kind === "message") {
      const hit = findRecord(archive.messages, row.ref?.message_id);
      return hit ? JSON.stringify(hit, null, 2) : null;
    }
    if (row.kind === "snapshot") {
      const hit = findRecord(archive.snapshots, row.ref?.snapshot_id);
      return hit ? JSON.stringify(hit, null, 2) : null;
    }
    if (row.kind === "run") {
      const hit = findRecord(archive.runs, row.ref?.run_id);
      return hit ? JSON.stringify(hit, null, 2) : null;
    }
    return null;
  }, [selectedIdx, archive, timelineRows]);

  return (
    <section style={{ flex: 1, minWidth: 0 }}>
      <div className="mono muted" style={{ fontSize: "0.78rem", marginBottom: "0.5rem", lineHeight: 1.5 }}>
        session_id={header.sid} · participant=#{header.participant} · workflow={header.workflow} · problem={header.problem}
        <br />
        export_schema_version={String(header.ver)} · messages={header.mc} · runs={header.rc} · snapshots={header.sc} ·
        timeline_rows={header.tc}
      </div>
      <div className="tabs" style={{ marginBottom: "0.5rem" }}>
        <button type="button" className={`tab ${tab === "timeline" ? "active" : ""}`} onClick={() => setTab("timeline")}>
          Timeline
        </button>
        <button type="button" className={`tab ${tab === "raw" ? "active" : ""}`} onClick={() => setTab("raw")}>
          Raw JSON
        </button>
      </div>

      {tab === "raw" ? (
        <pre
          className="mono"
          style={{
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            maxHeight: "70vh",
            overflow: "auto",
            fontSize: "0.75rem",
            padding: "0.5rem",
            border: "1px solid var(--border)",
            borderRadius: 2,
            background: "var(--bg)",
          }}
        >
          {rawText}
        </pre>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <div
            style={{
              maxHeight: "42vh",
              overflow: "auto",
              border: "1px solid var(--border)",
              borderRadius: 2,
              background: "var(--bg)",
            }}
          >
            <table
              className="mono"
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: "0.72rem",
              }}
            >
              <thead
                style={{
                  position: "sticky",
                  top: 0,
                  background: "var(--bg)",
                  borderBottom: "1px solid var(--border)",
                  zIndex: 1,
                }}
              >
                <tr>
                  <th style={{ textAlign: "left", padding: "0.35rem 0.5rem" }}>Time</th>
                  <th style={{ textAlign: "left", padding: "0.35rem 0.5rem" }}>Type</th>
                  <th style={{ textAlign: "left", padding: "0.35rem 0.5rem" }}>Label</th>
                  <th style={{ textAlign: "left", padding: "0.35rem 0.5rem" }}>Summary</th>
                </tr>
              </thead>
              <tbody>
                {timelineRows.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="muted" style={{ padding: "0.5rem" }}>
                      No timeline rows (empty session or unrecognized format).
                    </td>
                  </tr>
                ) : (
                  timelineRows.map((row, idx) => (
                    <tr
                      key={`${row.kind}-${row.at}-${idx}`}
                      onClick={() => setSelectedIdx(selectedIdx === idx ? null : idx)}
                      style={{
                        cursor: "pointer",
                        background: selectedIdx === idx ? "rgba(127,127,127,0.12)" : undefined,
                        borderBottom: "1px solid var(--border)",
                      }}
                    >
                      <td style={{ padding: "0.3rem 0.5rem", verticalAlign: "top", whiteSpace: "nowrap" }}>{row.at}</td>
                      <td style={{ padding: "0.3rem 0.5rem", verticalAlign: "top" }}>{row.kind}</td>
                      <td style={{ padding: "0.3rem 0.5rem", verticalAlign: "top" }}>{row.label}</td>
                      <td style={{ padding: "0.3rem 0.5rem", verticalAlign: "top", wordBreak: "break-word" }}>
                        {row.payload_summary}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {detailJson ? (
            <div>
              <div className="muted" style={{ fontSize: "0.78rem", marginBottom: "0.25rem" }}>
                Selected row (full message / snapshot / run record)
              </div>
              <pre
                className="mono"
                style={{
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  maxHeight: "28vh",
                  overflow: "auto",
                  fontSize: "0.72rem",
                  padding: "0.5rem",
                  border: "1px solid var(--border)",
                  borderRadius: 2,
                  background: "var(--bg)",
                  margin: 0,
                }}
              >
                {detailJson}
              </pre>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
