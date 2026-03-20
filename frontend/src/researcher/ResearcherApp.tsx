import { useCallback, useEffect, useState } from "react";
import { apiFetch, type Message, type RunResult, type Session } from "@shared/api";

const TOKEN_KEY = "mopt_researcher_token";

export function ResearcherApp() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [runs, setRuns] = useState<RunResult[]>([]);
  const [steerText, setSteerText] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const [geminiModel, setGeminiModel] = useState("gemini-2.0-flash");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshList = useCallback(async () => {
    if (!token.trim()) return;
    try {
      const list = await apiFetch<Session[]>("/sessions", token.trim());
      setSessions(list);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "List failed");
    }
  }, [token]);

  const loadDetail = useCallback(async () => {
    if (!token.trim() || !selected) return;
    try {
      const s = await apiFetch<Session>(`/sessions/${selected}/researcher`, token.trim());
      setDetail(s);
      const msgs = await apiFetch<Message[]>(
        `/sessions/${selected}/messages/researcher?after_id=0`,
        token.trim(),
      );
      setMessages(msgs);
      const r = await apiFetch<RunResult[]>(`/sessions/${selected}/runs`, token.trim());
      setRuns(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed");
    }
  }, [token, selected]);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  useEffect(() => {
    void loadDetail();
    const t = window.setInterval(() => void loadDetail(), 4000);
    return () => window.clearInterval(t);
  }, [loadDetail]);

  async function saveToken() {
    sessionStorage.setItem(TOKEN_KEY, token.trim());
    setToken(token.trim());
    await refreshList();
  }

  async function patchSession(patch: Record<string, unknown>) {
    if (!token.trim() || !selected) return;
    setBusy(true);
    try {
      const s = await apiFetch<Session>(`/sessions/${selected}`, token.trim(), {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setDetail(s);
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  async function sendSteer() {
    if (!steerText.trim() || !token.trim() || !selected) return;
    setBusy(true);
    try {
      await apiFetch(`/sessions/${selected}/steer`, token.trim(), {
        method: "POST",
        body: JSON.stringify({ content: steerText.trim() }),
      });
      setSteerText("");
      await loadDetail();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Steer failed");
    } finally {
      setBusy(false);
    }
  }

  async function terminate() {
    if (!selected || !token.trim()) return;
    setBusy(true);
    try {
      await apiFetch(`/sessions/${selected}/terminate`, token.trim(), { method: "POST" });
      await refreshList();
      await loadDetail();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Terminate failed");
    } finally {
      setBusy(false);
    }
  }

  async function removeSession() {
    if (!selected || !token.trim()) return;
    if (!window.confirm("Delete this session and all logs?")) return;
    setBusy(true);
    try {
      await apiFetch(`/sessions/${selected}`, token.trim(), { method: "DELETE" });
      setSelected(null);
      setDetail(null);
      setMessages([]);
      setRuns([]);
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  async function exportJson() {
    if (!selected || !token.trim()) return;
    try {
      const data = await apiFetch<unknown>(`/sessions/${selected}/export`, token.trim());
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `session-${selected}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Researcher</span>
        <div style={{ display: "flex", gap: "0.35rem", alignItems: "center", flexWrap: "wrap" }}>
          <input
            type="password"
            placeholder="Researcher token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            style={{ minWidth: "12rem" }}
          />
          <button type="button" onClick={() => void saveToken()}>
            Save token
          </button>
          <button type="button" onClick={() => void refreshList()}>
            Refresh list
          </button>
        </div>
      </header>
      {error && <div className="banner-warn">{error}</div>}
      <div className="researcher-layout">
        <aside className="session-list">
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`session-item ${selected === s.id ? "active" : ""}`}
              role="button"
              tabIndex={0}
              onClick={() => setSelected(s.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") setSelected(s.id);
              }}
            >
              <div className="mono" style={{ fontSize: "0.75rem" }}>
                {s.id.slice(0, 8)}…
              </div>
              <div className="muted">
                {s.workflow_mode} · {s.status}
              </div>
            </div>
          ))}
        </aside>
        <main className="detail">
          {!selected && <p className="muted">Select a session.</p>}
          {selected && detail && (
            <>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
                <span className="mono">{detail.id}</span>
                <button type="button" disabled={busy} onClick={() => void exportJson()}>
                  Export JSON
                </button>
                <button type="button" disabled={busy} onClick={() => void terminate()}>
                  Terminate session
                </button>
                <button type="button" disabled={busy} onClick={() => void removeSession()}>
                  Delete session
                </button>
              </div>
              <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                <label className="muted">
                  Workflow
                  <select
                    value={detail.workflow_mode}
                    onChange={(e) => void patchSession({ workflow_mode: e.target.value })}
                    style={{ display: "block", marginTop: "0.2rem" }}
                  >
                    <option value="agile">agile</option>
                    <option value="waterfall">waterfall</option>
                  </select>
                </label>
                <label className="muted">
                  <input
                    type="checkbox"
                    checked={detail.optimization_allowed}
                    onChange={(e) => void patchSession({ optimization_allowed: e.target.checked })}
                  />{" "}
                  Allow optimization runs
                </label>
              </div>
              <div
                style={{
                  border: "1px solid var(--border)",
                  padding: "0.5rem",
                  background: "var(--panel)",
                }}
              >
                <strong className="muted">Push model key to participant session</strong>
                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", marginTop: "0.35rem" }}>
                  <input
                    type="password"
                    placeholder="Gemini API key"
                    value={geminiKey}
                    onChange={(e) => setGeminiKey(e.target.value)}
                    style={{ flex: 1, minWidth: "10rem" }}
                  />
                  <input
                    value={geminiModel}
                    onChange={(e) => setGeminiModel(e.target.value)}
                    style={{ width: "10rem" }}
                  />
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void patchSession({
                        gemini_api_key: geminiKey || undefined,
                        gemini_model: geminiModel || undefined,
                      }).then(() => setGeminiKey(""))
                    }
                  >
                    Push key
                  </button>
                </div>
              </div>
              <section>
                <div className="panel-header">Chat (incl. steering)</div>
                <div className="chat-log" style={{ maxHeight: "240px" }}>
                  {messages.map((m) => (
                    <div key={m.id} className="bubble assistant">
                      <strong>
                        {m.role}
                        {!m.visible_to_participant ? " (hidden from participant)" : ""}
                      </strong>
                      <div>{m.content}</div>
                    </div>
                  ))}
                </div>
                <div className="chat-input-row" style={{ marginTop: "0.35rem" }}>
                  <textarea
                    value={steerText}
                    onChange={(e) => setSteerText(e.target.value)}
                    placeholder="Steering note (participant does not see)"
                    style={{ minHeight: "2.5rem" }}
                  />
                  <button type="button" disabled={busy} onClick={() => void sendSteer()}>
                    Send steer
                  </button>
                </div>
              </section>
              <section>
                <div className="panel-header">Runs</div>
                <pre className="mono" style={{ fontSize: "0.75rem", maxHeight: "200px", overflow: "auto" }}>
                  {JSON.stringify(runs, null, 2)}
                </pre>
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
