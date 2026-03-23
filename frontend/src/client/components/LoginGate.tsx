import type { RecentSessionRow } from "../lib/participantTypes";
import { BackendConnectionControl } from "@shared/status/BackendConnectionControl";

type LoginGateProps = {
  token: string;
  participantNumber: string;
  busy: boolean;
  error: string | null;
  recentBusy: boolean;
  recentRows: RecentSessionRow[];
  onTokenChange: (value: string) => void;
  onParticipantNumberChange: (value: string) => void;
  onLogin: () => void | Promise<void>;
  onStartSession: () => void | Promise<void>;
  onRefreshRecentSessions: () => void | Promise<void>;
  onResumeSession: (id: string) => void | Promise<void>;
  onForgetSession: (id: string) => void;
};

export function LoginGate({
  token,
  participantNumber,
  busy,
  error,
  recentBusy,
  recentRows,
  onTokenChange,
  onParticipantNumberChange,
  onLogin,
  onStartSession,
  onRefreshRecentSessions,
  onResumeSession,
  onForgetSession,
}: LoginGateProps) {
  function formatStartTime(value?: string): string {
    if (!value) return "Start time unknown";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return "Start time unknown";
    return `Started ${parsed.toLocaleString()}`;
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Participant</span>
        <div style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
          <BackendConnectionControl />
        </div>
      </header>
      <div className="login-panel">
        {error && (
          <p className="banner-warn" style={{ marginBottom: "1rem" }}>
            {error}
          </p>
        )}
        <p className="muted">
          Enter the access token for this station, then start. Workflow (for example agile vs waterfall) is set by the
          researcher for your session - you do not choose it here.
        </p>
        <label>
          Participant number
          <input
            type="text"
            value={participantNumber}
            onChange={(e) => onParticipantNumberChange(e.target.value)}
            placeholder="Optional, e.g. 007"
            autoComplete="off"
          />
        </label>
        <label>
          Access token
          <input
            type="password"
            value={token}
            onChange={(e) => onTokenChange(e.target.value)}
            autoComplete="off"
          />
        </label>
        <div
          style={{
            marginTop: "1rem",
            display: "flex",
            gap: "0.5rem",
            flexWrap: "wrap",
          }}
        >
          <button
            type="button"
            onClick={() => {
              onLogin();
              void onRefreshRecentSessions();
            }}
          >
            Save token
          </button>
          <button type="button" disabled={busy || !token.trim()} onClick={() => void onStartSession()}>
            Start session
          </button>
        </div>
        <details style={{ marginTop: "1.25rem" }} className="login-recent-sessions">
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>Past sessions on this browser</summary>
          <p className="muted" style={{ fontSize: "0.85rem", marginTop: "0.5rem" }}>
            Session ids are stored only on this device (not by IP on the server). Enter your participant number and
            save token to also see sessions from other devices. You still need the same access token to open them.
            Anyone with this browser profile can see these entries.
          </p>
          <div
            style={{
              marginTop: "0.5rem",
              display: "flex",
              gap: "0.5rem",
              flexWrap: "wrap",
            }}
          >
            <button
              type="button"
              disabled={recentBusy || !token.trim()}
              onClick={() => void onRefreshRecentSessions()}
            >
              {recentBusy ? "Checking..." : "Refresh list"}
            </button>
          </div>
          {recentRows.length === 0 ? (
            <p className="muted" style={{ marginTop: "0.75rem", fontSize: "0.9rem" }}>
              None yet - they appear after you start or leave a session.
            </p>
          ) : (
            <ul
              className="recent-session-list"
              style={{
                listStyle: "none",
                padding: 0,
                marginTop: "0.75rem",
                maxHeight: "14rem",
                overflow: "auto",
              }}
            >
              {recentRows.map((row) => (
                <li
                  key={row.id}
                  style={{
                    border: "1px solid var(--border)",
                    padding: "0.5rem 0.65rem",
                    marginBottom: "0.35rem",
                    borderRadius: "4px",
                    fontSize: "0.85rem",
                  }}
                >
                  <div className="mono" style={{ wordBreak: "break-all" }}>
                    {row.id.slice(0, 8)}...{row.id.slice(-4)}
                  </div>
                  <div className="muted">
                    Participant #{row.session?.participant_number ?? row.history?.participant_number ?? "n/a"}
                  </div>
                  <div className="muted">
                    {formatStartTime(row.session?.created_at ?? row.history?.created_at)}
                  </div>
                  {row.error ? (
                    <span className="muted">{row.error}</span>
                  ) : row.session ? (
                    <div className="muted">
                      {row.session.workflow_mode} · {row.session.status}
                      {row.session.status === "terminated" ? " (read-only)" : ""}
                    </div>
                  ) : (
                    <span className="muted">
                      Optional: Refresh list to show status - Resume still works if the id is valid.
                    </span>
                  )}
                  <div
                    style={{
                      marginTop: "0.35rem",
                      display: "flex",
                      gap: "0.35rem",
                      flexWrap: "wrap",
                    }}
                  >
                    <button
                      type="button"
                      disabled={busy || !token.trim() || Boolean(row.error)}
                      onClick={() => void onResumeSession(row.id)}
                    >
                      Resume
                    </button>
                    <button type="button" disabled={busy} onClick={() => onForgetSession(row.id)}>
                      Forget
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </details>
      </div>
    </div>
  );
}
