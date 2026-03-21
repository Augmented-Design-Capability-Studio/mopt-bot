import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, displayRunNumber, type Message, type RunResult, type Session } from "@shared/api";
import { ChatPanel } from "@shared/ChatPanel";
import {
  DEFAULT_SUGGESTED_GEMINI_MODEL,
  GEMINI_MODEL_DATALIST_ID,
  GeminiModelDatalist,
} from "@shared/geminiModelSuggestions";

const TOKEN_KEY = "mopt_researcher_token";

export function ResearcherApp() {
  /** Value in the input; not sent to the API until "Save token". */
  const [tokenInput, setTokenInput] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  /** Bearer token used for all requests (updated only on Save). */
  const [savedToken, setSavedToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [runs, setRuns] = useState<RunResult[]>([]);
  const [steerText, setSteerText] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const [geminiModel, setGeminiModel] = useState(DEFAULT_SUGGESTED_GEMINI_MODEL);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pushKeySuccess, setPushKeySuccess] = useState<string | null>(null);

  /** Bumped when the server session may change from a mutation so in-flight GET /researcher polls are ignored. */
  const detailPollGen = useRef(0);
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selected;

  const refreshList = useCallback(async () => {
    if (!savedToken.trim()) return;
    try {
      const list = await apiFetch<Session[]>("/sessions", savedToken.trim());
      setSessions(list);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "List failed");
    }
  }, [savedToken]);

  const loadDetail = useCallback(async () => {
    if (!savedToken.trim() || !selected) return;
    const sessionId = selected;
    const gen = detailPollGen.current;
    try {
      const s = await apiFetch<Session>(`/sessions/${sessionId}/researcher`, savedToken.trim());
      if (gen !== detailPollGen.current || sessionId !== selectedRef.current) return;
      setDetail(s);
      const msgs = await apiFetch<Message[]>(
        `/sessions/${sessionId}/messages/researcher?after_id=0`,
        savedToken.trim(),
      );
      if (gen !== detailPollGen.current || sessionId !== selectedRef.current) return;
      setMessages(msgs);
      const r = await apiFetch<RunResult[]>(`/sessions/${sessionId}/runs`, savedToken.trim());
      if (gen !== detailPollGen.current || sessionId !== selectedRef.current) return;
      setRuns(r);
    } catch (e) {
      if (gen !== detailPollGen.current || sessionId !== selectedRef.current) return;
      setError(e instanceof Error ? e.message : "Load failed");
    }
  }, [savedToken, selected]);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  useEffect(() => {
    void loadDetail();
    const t = window.setInterval(() => void loadDetail(), 4000);
    return () => window.clearInterval(t);
  }, [loadDetail]);

  useEffect(() => {
    if (!detail) return;
    setGeminiModel(detail.gemini_model?.trim() || DEFAULT_SUGGESTED_GEMINI_MODEL);
  }, [detail?.id]);

  function saveToken() {
    const t = tokenInput.trim();
    sessionStorage.setItem(TOKEN_KEY, t);
    setSavedToken(t);
    setTokenInput(t);
    setError(null);
    // List refresh runs via useEffect when savedToken updates
  }

  /** Returns true only when the PATCH succeeded (callers can clear inputs safely). */
  async function patchSession(patch: Record<string, unknown>): Promise<boolean> {
    if (!savedToken.trim() || !selected) return false;
    detailPollGen.current += 1;
    setBusy(true);
    try {
      const s = await apiFetch<Session>(`/sessions/${selected}`, savedToken.trim(), {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setDetail(s);
      await refreshList();
      setError(null);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function sendSteer() {
    if (!steerText.trim() || !savedToken.trim() || !selected) return;
    const text = steerText.trim();
    const tempId = -Date.now();
    const optimistic: Message = {
      id: tempId,
      created_at: new Date().toISOString(),
      role: "researcher",
      content: text,
      visible_to_participant: false,
      kind: "chat",
    };
    setMessages((m) => [...m, optimistic]);
    setSteerText("");
    setBusy(true);
    try {
      const saved = await apiFetch<Message>(`/sessions/${selected}/steer`, savedToken.trim(), {
        method: "POST",
        body: JSON.stringify({ content: text }),
      });
      setMessages((m) => [...m.filter((x) => x.id !== tempId), saved]);
    } catch (e) {
      setMessages((m) => m.filter((x) => x.id !== tempId));
      setSteerText(text);
      setError(e instanceof Error ? e.message : "Steer failed");
    } finally {
      setBusy(false);
    }
  }

  async function terminate() {
    if (!selected || !savedToken.trim()) return;
    detailPollGen.current += 1;
    setBusy(true);
    try {
      await apiFetch(`/sessions/${selected}/terminate`, savedToken.trim(), { method: "POST" });
      await refreshList();
      await loadDetail();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Terminate failed");
    } finally {
      setBusy(false);
    }
  }

  async function removeSession() {
    if (!selected || !savedToken.trim()) return;
    if (!window.confirm("Delete this session and all logs?")) return;
    setBusy(true);
    try {
      await apiFetch(`/sessions/${selected}`, savedToken.trim(), { method: "DELETE" });
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

  async function removeRun(run: RunResult) {
    if (!selected || !savedToken.trim()) return;
    const sessionId = selected;
    if (
      !window.confirm(
        `Delete run #${displayRunNumber(run)} from this session? This removes the stored run record from the database.`,
      )
    ) {
      return;
    }
    detailPollGen.current += 1;
    setBusy(true);
    try {
      await apiFetch(`/sessions/${sessionId}/runs/${run.id}`, savedToken.trim(), { method: "DELETE" });
      const [nextDetail, nextRuns] = await Promise.all([
        apiFetch<Session>(`/sessions/${sessionId}/researcher`, savedToken.trim()),
        apiFetch<RunResult[]>(`/sessions/${sessionId}/runs`, savedToken.trim()),
      ]);
      if (sessionId !== selectedRef.current) return;
      setDetail(nextDetail);
      setRuns(nextRuns);
      await refreshList();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete run failed");
    } finally {
      setBusy(false);
    }
  }

  async function pushParticipantStarterPanel() {
    if (!savedToken.trim() || !selected) return;
    detailPollGen.current += 1;
    setBusy(true);
    try {
      const s = await apiFetch<Session>(
        `/sessions/${selected}/participant-starter-panel`,
        savedToken.trim(),
        { method: "POST" },
      );
      setDetail(s);
      await refreshList();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Push starter config failed");
    } finally {
      setBusy(false);
    }
  }

  async function exportJson() {
    if (!selected || !savedToken.trim()) return;
    try {
      const data = await apiFetch<unknown>(`/sessions/${selected}/export`, savedToken.trim());
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

  const tokenDirty = tokenInput.trim() !== savedToken.trim();

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Researcher</span>
        <div style={{ display: "flex", gap: "0.35rem", alignItems: "center", flexWrap: "wrap" }}>
          <input
            type="password"
            placeholder="Researcher token (paste, then Save)"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            style={{ minWidth: "12rem" }}
            autoComplete="off"
          />
          <button type="button" onClick={saveToken}>
            Save token
          </button>
          <button type="button" disabled={!savedToken.trim()} onClick={() => void refreshList()}>
            Refresh list
          </button>
          {tokenDirty && (
            <span className="muted" style={{ fontSize: "0.8rem" }}>
              Unsaved — click Save to use this token
            </span>
          )}
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
          {!savedToken.trim() && (
            <p className="muted">Paste <code>MOPT_RESEARCHER_SECRET</code> from your server <code>.env</code>, then click Save token.</p>
          )}
          {savedToken.trim() && !selected && <p className="muted">Select a session.</p>}
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
                <button type="button" disabled={busy} onClick={() => void pushParticipantStarterPanel()}>
                  Push starter problem config
                </button>
              </div>
              <p className="muted" style={{ fontSize: "0.8rem", margin: "0.25rem 0 0" }}>
                New participant sessions start with empty panels until you push this mediocre default (GA weights +
                modest epochs/population).
              </p>
              <div
                style={{
                  border: "1px solid var(--border)",
                  padding: "0.5rem",
                  background: "var(--panel)",
                }}
              >
                <strong className="muted">Push model key to participant session</strong>
                <p className="muted" style={{ fontSize: "0.8rem", margin: "0.35rem 0 0" }}>
                  Server status for this session:{" "}
                  <strong>{detail.gemini_key_configured ? "API key stored" : "No API key yet"}</strong>
                </p>
                {pushKeySuccess && (
                  <p className="banner-info" style={{ margin: "0.35rem 0 0", fontSize: "0.85rem" }}>
                    {pushKeySuccess}
                  </p>
                )}
                <GeminiModelDatalist />
                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", marginTop: "0.35rem" }}>
                  <input
                    type="password"
                    placeholder="Gemini API key"
                    value={geminiKey}
                    onChange={(e) => {
                      setGeminiKey(e.target.value);
                      setPushKeySuccess(null);
                    }}
                    style={{ flex: 1, minWidth: "10rem" }}
                  />
                  <input
                    value={geminiModel}
                    onChange={(e) => setGeminiModel(e.target.value)}
                    list={GEMINI_MODEL_DATALIST_ID}
                    placeholder={DEFAULT_SUGGESTED_GEMINI_MODEL}
                    autoComplete="off"
                    style={{ minWidth: "12rem", flex: "1 1 10rem" }}
                  />
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void (async () => {
                        const key = geminiKey.trim();
                        if (!key) {
                          setError("Enter a Gemini API key to push.");
                          return;
                        }
                        const ok = await patchSession({
                          gemini_api_key: key,
                          gemini_model: geminiModel.trim() || undefined,
                        });
                        if (ok) {
                          setGeminiKey("");
                          setPushKeySuccess(
                            "Key saved on the server. The participant app will show a check on the Model / API key chip after the next sync.",
                          );
                        }
                      })()
                    }
                  >
                    Push key
                  </button>
                </div>
              </div>
              <section>
                <ChatPanel
                  title="Chat (incl. steering)"
                  logStyle={{ maxHeight: "240px" }}
                  messages={
                    <>
                      {messages.map((m, i) => (
                        <div key={m.id < 0 ? `tmp-${m.id}-${i}` : m.id} className="bubble assistant">
                          <strong>
                            {m.role}
                            {!m.visible_to_participant ? " (hidden from participant)" : ""}
                          </strong>
                          <div>{m.content}</div>
                        </div>
                      ))}
                    </>
                  }
                  composer={{
                    value: steerText,
                    onChange: setSteerText,
                    onSend: sendSteer,
                    sendDisabled: busy,
                    sendLabel: "Send steer",
                    placeholder:
                      "Steering note (participant does not see). Enter to send, Shift+Enter for newline.",
                    textareaStyle: { minHeight: "2.5rem" },
                  }}
                />
              </section>
              <section>
                <div className="panel-header">Runs</div>
                {runs.length === 0 ? (
                  <div className="muted" style={{ padding: "0.45rem 0.2rem" }}>
                    No runs yet.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem", marginTop: "0.4rem" }}>
                    {runs.map((run) => (
                      <details key={run.id}>
                        <summary className="mono" style={{ cursor: "pointer" }}>
                          Run #{displayRunNumber(run)} · {run.run_type} · {run.ok ? "ok" : "error"} · cost{" "}
                          {run.cost ?? "—"} · {new Date(run.created_at).toLocaleString()}
                        </summary>
                        <div style={{ marginTop: "0.35rem" }}>
                          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "0.35rem" }}>
                            <button type="button" disabled={busy} onClick={() => void removeRun(run)}>
                              Delete run
                            </button>
                          </div>
                          <pre
                            className="mono"
                            style={{ fontSize: "0.75rem", maxHeight: "240px", overflow: "auto", margin: 0 }}
                          >
                            {JSON.stringify(run, null, 2)}
                          </pre>
                        </div>
                      </details>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
