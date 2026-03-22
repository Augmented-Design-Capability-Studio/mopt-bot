import type { Session } from "@shared/api";

type ResearcherSessionListProps = {
  sessions: Session[];
  selectedId: string | null;
  selectedIds: string[];
  onSelect: (sessionId: string) => void;
  onToggleSelect: (sessionId: string, checked: boolean) => void;
  onToggleSelectAll: (checked: boolean) => void;
  onRemoveSelected: () => void | Promise<void>;
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
  busy,
}: ResearcherSessionListProps) {
  function formatStart(value: string): string {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return "Unknown start";
    return parsed.toLocaleString();
  }

  const allSelected = sessions.length > 0 && selectedIds.length === sessions.length;

  return (
    <aside className="session-list">
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
          <div className="muted">Participant #{session.participant_number ?? "n/a"}</div>
          <div className="muted">Started {formatStart(session.created_at)}</div>
        </div>
      ))}
    </aside>
  );
}
