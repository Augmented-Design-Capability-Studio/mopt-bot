import { parseServerDate } from "@shared/dateTime";

import type { SessionArchive } from "../lib/types";

type SessionListPanelProps = {
  sessions: SessionArchive[];
  selectedId: string | null;
  analyzedIds: Set<string>;
  onSelect: (sessionId: string) => void;
  onAnalyze: (sessionId: string) => void;
  sourceLabel: string | null;
};

function formatStart(value: string): string {
  if (!value) return "Unknown start";
  const parsed = parseServerDate(value);
  if (Number.isNaN(parsed.getTime())) return "Unknown start";
  return parsed.toLocaleString();
}

export function SessionListPanel({
  sessions,
  selectedId,
  analyzedIds,
  onSelect,
  onAnalyze,
  sourceLabel,
}: SessionListPanelProps) {
  if (sessions.length === 0) {
    return (
      <aside className="session-list">
        <p className="muted" style={{ fontSize: "0.85rem", padding: "0.5rem 0.6rem" }}>
          {sourceLabel
            ? `Loaded ${sourceLabel}, but it contains no sessions.`
            : "Load a session export (.json) or a sessions database (.db) to begin."}
        </p>
      </aside>
    );
  }

  return (
    <aside className="session-list">
      {sourceLabel ? (
        <div className="muted" style={{ fontSize: "0.75rem", marginBottom: "0.5rem" }}>
          Loaded: <span className="mono">{sourceLabel}</span> · {sessions.length} session
          {sessions.length === 1 ? "" : "s"}
        </div>
      ) : null}
      {sessions.map((archive) => {
        const session = archive.session;
        const sid = session.id;
        const analyzed = analyzedIds.has(sid);
        const isActive = selectedId === sid;
        return (
          <div
            key={sid}
            className={`session-item ${isActive ? "active" : ""}`}
            role="button"
            tabIndex={0}
            onClick={() => onSelect(sid)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") onSelect(sid);
            }}
          >
            <div className="mono" style={{ fontSize: "0.75rem" }}>
              {sid.slice(0, 8)}...
            </div>
            <div className="muted">
              {session.workflow_mode} · {session.status}
            </div>
            <div className="muted">
              {session.test_problem_id ?? "—"} · Participant #{session.participant_number ?? "n/a"}
            </div>
            <div className="muted">
              {archive.messages.length} msg · {archive.runs.length} run
              {archive.runs.length === 1 ? "" : "s"} · {archive.snapshots.length} snap
            </div>
            <div className="muted">Started {formatStart(session.created_at)}</div>
            <div style={{ marginTop: "0.35rem" }} onClick={(e) => e.stopPropagation()}>
              <button
                type="button"
                onClick={() => onAnalyze(sid)}
                style={{ width: "100%" }}
                title={analyzed ? "Re-open the analyzer pane for this session." : "Compute and view this session's analyzer pane."}
              >
                {analyzed ? "Re-analyze" : "Analyze"}
              </button>
            </div>
          </div>
        );
      })}
    </aside>
  );
}
