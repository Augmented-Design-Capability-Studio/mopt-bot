import type { Session } from "@shared/api";

type ResearcherSessionListProps = {
  sessions: Session[];
  selectedId: string | null;
  onSelect: (sessionId: string) => void;
};

export function ResearcherSessionList({
  sessions,
  selectedId,
  onSelect,
}: ResearcherSessionListProps) {
  return (
    <aside className="session-list">
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
          <div className="mono" style={{ fontSize: "0.75rem" }}>
            {session.id.slice(0, 8)}...
          </div>
          <div className="muted">
            {session.workflow_mode} · {session.status}
          </div>
        </div>
      ))}
    </aside>
  );
}
