import { useEffect, useState } from "react";

import type { Session, TestProblemMeta } from "@shared/api";
import { parseServerDate } from "@shared/dateTime";

type ResearcherSessionListProps = {
  sessions: Session[];
  selectedId: string | null;
  selectedIds: string[];
  onSelect: (sessionId: string) => void;
  onToggleSelect: (sessionId: string, checked: boolean) => void;
  onToggleSelectAll: (checked: boolean) => void;
  onRemoveSelected: () => void | Promise<void>;
  onCreateSession: (body: {
    participant_number: string;
    workflow_mode: string;
    test_problem_id: string;
  }) => void | Promise<void>;
  testProblemsMeta: TestProblemMeta[];
  canCreateSession: boolean;
  busy: boolean;
};

export function ResearcherSessionList({
  sessions,
  selectedId,
  selectedIds,
  onSelect,
  onToggleSelect,
  onToggleSelectAll,
  onRemoveSelected,
  onCreateSession,
  testProblemsMeta,
  canCreateSession,
  busy,
}: ResearcherSessionListProps) {
  const [createExpanded, setCreateExpanded] = useState(false);
  const [participantNumber, setParticipantNumber] = useState("");
  const [workflowMode, setWorkflowMode] = useState("waterfall");
  const [testProblemId, setTestProblemId] = useState("vrptw");

  useEffect(() => {
    if (testProblemsMeta.length === 0) return;
    setTestProblemId((current) =>
      testProblemsMeta.some((m) => m.id === current) ? current : testProblemsMeta[0].id,
    );
  }, [testProblemsMeta]);

  function formatStart(value: string): string {
    const parsed = parseServerDate(value);
    if (Number.isNaN(parsed.getTime())) return "Unknown start";
    return parsed.toLocaleString();
  }

  const allSelected = sessions.length > 0 && selectedIds.length === sessions.length;

  return (
    <aside className="session-list">
      <div className="researcher-new-session">
        <button
          type="button"
          className="researcher-new-session-toggle"
          aria-expanded={createExpanded}
          onClick={() => setCreateExpanded((open) => !open)}
        >
          <span className="researcher-new-session-toggle-chevron" aria-hidden>
            {createExpanded ? "▴" : "▾"}
          </span>
          Create session…
        </button>
        {createExpanded ? (
          <div className="researcher-new-session-body">
            <label className="researcher-new-session-label">
              Participant #
              <input
                type="text"
                value={participantNumber}
                onChange={(e) => setParticipantNumber(e.target.value)}
                placeholder="optional"
                disabled={busy || !canCreateSession}
                maxLength={64}
                autoComplete="off"
              />
            </label>
            <label className="researcher-new-session-label">
              Workflow
              <select
                value={workflowMode}
                onChange={(e) => setWorkflowMode(e.target.value)}
                disabled={busy || !canCreateSession}
              >
                <option value="waterfall">Waterfall</option>
                <option value="agile">Agile</option>
                <option value="demo">Demo</option>
              </select>
            </label>
            <label className="researcher-new-session-label">
              Test problem
              <select
                value={testProblemId}
                onChange={(e) => setTestProblemId(e.target.value)}
                disabled={busy || !canCreateSession || testProblemsMeta.length === 0}
              >
                {testProblemsMeta.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label} ({m.id})
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn-primary"
              style={{ width: "100%", marginTop: "0.35rem" }}
              disabled={busy || !canCreateSession || testProblemsMeta.length === 0}
              onClick={() =>
                void onCreateSession({
                  participant_number: participantNumber,
                  workflow_mode: workflowMode,
                  test_problem_id: testProblemId,
                })
              }
            >
              Create session
            </button>
          </div>
        ) : null}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", marginBottom: "0.6rem" }}>
        <label className="muted" style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <input
            type="checkbox"
            checked={allSelected}
            disabled={busy || sessions.length === 0}
            onChange={(e) => onToggleSelectAll(e.target.checked)}
          />
          Select all visible
        </label>
        <button type="button" disabled={busy || selectedIds.length === 0} onClick={() => void onRemoveSelected()}>
          Delete selected ({selectedIds.length})
        </button>
      </div>
      {sessions.map((session) => (
        <div
          key={session.id}
          className={`session-item ${selectedId === session.id ? "active" : ""}`}
          role="button"
          tabIndex={0}
          onClick={() => onSelect(session.id)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") onSelect(session.id);
          }}
        >
          <label
            style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.3rem" }}
            onClick={(e) => e.stopPropagation()}
          >
            <input
              type="checkbox"
              checked={selectedIds.includes(session.id)}
              disabled={busy}
              onChange={(e) => onToggleSelect(session.id, e.target.checked)}
            />
            <span className="muted" style={{ fontSize: "0.75rem" }}>
              Select
            </span>
          </label>
          <div className="mono" style={{ fontSize: "0.75rem" }}>
            {session.id.slice(0, 8)}...
          </div>
          <div className="muted">
            {session.workflow_mode} · {session.status}
          </div>
          <div className="muted">
            {session.test_problem_id} · Participant #{session.participant_number ?? "n/a"}
          </div>
          <div className="muted">Started {formatStart(session.created_at)}</div>
        </div>
      ))}
    </aside>
  );
}
