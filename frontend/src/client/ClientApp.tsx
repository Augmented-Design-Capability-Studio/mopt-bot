import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  apiFetch,
  assertPostMessagesResponse,
  type Message,
  type RunResult,
  type Session,
} from "@shared/api";

const TOKEN_KEY = "mopt_client_token";
const SESSION_KEY = "mopt_session_id";

type EditMode = "none" | "config" | "results";

export function ClientApp() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  const [sessionId, setSessionId] = useState(() => sessionStorage.getItem(SESSION_KEY) ?? "");
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [runs, setRuns] = useState<RunResult[]>([]);
  const [lastMsgId, setLastMsgId] = useState(0);
  const [chatInput, setChatInput] = useState("");
  const [invokeModel, setInvokeModel] = useState(false);
  const [configText, setConfigText] = useState("");
  const [scheduleText, setScheduleText] = useState("");
  const [activeRun, setActiveRun] = useState(0);
  const [editMode, setEditMode] = useState<EditMode>("none");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showModelDialog, setShowModelDialog] = useState(false);
  const [modelKey, setModelKey] = useState("");
  const [modelName, setModelName] = useState("gemini-2.5-flash");
  const fileRef = useRef<HTMLInputElement>(null);

  const authed = useMemo(() => Boolean(token && sessionId), [token, sessionId]);

  const syncSession = useCallback(async () => {
    if (!token || !sessionId) return;
    try {
      const s = await apiFetch<Session>(`/sessions/${sessionId}`, token);
      setSession(s);
      if (s.panel_config) setConfigText(JSON.stringify(s.panel_config, null, 2));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 410 || e.status === 404)) {
        setSession(null);
        setSessionId("");
        sessionStorage.removeItem(SESSION_KEY);
        setError("Your session ended or was removed. Start a new session.");
      } else {
        setError(e instanceof Error ? e.message : "Sync failed");
      }
    }
  }, [token, sessionId]);

  const syncMessages = useCallback(async () => {
    if (!token || !sessionId) return;
    try {
      const list = await apiFetch<Message[]>(
        `/sessions/${sessionId}/messages?after_id=${lastMsgId}`,
        token,
      );
      if (list.length) {
        setMessages((m) => [...m, ...list]);
        setLastMsgId(list[list.length - 1]!.id);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 410) {
        setSessionId("");
        sessionStorage.removeItem(SESSION_KEY);
        setError("Your session ended. Start fresh.");
      }
    }
  }, [token, sessionId, lastMsgId]);

  const syncRuns = useCallback(async () => {
    if (!token || !sessionId) return;
    try {
      const list = await apiFetch<RunResult[]>(`/sessions/${sessionId}/runs`, token);
      setRuns((prev) => {
        if (list.length !== prev.length) {
          return list;
        }
        const changed = list.some((x, i) => x.id !== prev[i]?.id || x.ok !== prev[i]?.ok);
        return changed ? list : prev;
      });
      setActiveRun((i) => {
        const len = list.length;
        if (len === 0) return 0;
        return i >= len ? len - 1 : i;
      });
    } catch {
      /* ignore poll errors */
    }
  }, [token, sessionId]);

  useEffect(() => {
    if (!authed) return;
    void syncSession();
  }, [authed, syncSession]);

  useEffect(() => {
    if (!authed) return;
    const t = window.setInterval(() => {
      void syncMessages();
      void syncRuns();
    }, 2500);
    return () => window.clearInterval(t);
  }, [authed, syncMessages, syncRuns]);

  async function login() {
    sessionStorage.setItem(TOKEN_KEY, token.trim());
    setToken(token.trim());
    setError(null);
  }

  async function startSession() {
    if (!token.trim()) {
      setError("Enter access token first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const s = await apiFetch<Session>("/sessions", token.trim(), {
        method: "POST",
        body: JSON.stringify({}),
      });
      setSessionId(s.id);
      sessionStorage.setItem(TOKEN_KEY, token.trim());
      sessionStorage.setItem(SESSION_KEY, s.id);
      setSession(s);
      setMessages([]);
      setLastMsgId(0);
      setRuns([]);
      if (s.panel_config) setConfigText(JSON.stringify(s.panel_config, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create session");
    } finally {
      setBusy(false);
    }
  }

  async function sendChat() {
    if (!chatInput.trim() || !token || !sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const raw = await apiFetch<unknown>(`/sessions/${sessionId}/messages`, token, {
        method: "POST",
        body: JSON.stringify({ content: chatInput.trim(), invoke_model: invokeModel }),
      });
      const res = assertPostMessagesResponse(raw);
      const out = res.messages;
      setMessages((m) => [...m, ...out]);
      if (out.length) setLastMsgId(out[out.length - 1]!.id);
      if (res.panel_config != null) {
        setConfigText(JSON.stringify(res.panel_config, null, 2));
        setSession((prev) =>
          prev ? { ...prev, panel_config: res.panel_config as Session["panel_config"] } : prev,
        );
      }
      setChatInput("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Send failed");
    } finally {
      setBusy(false);
    }
  }

  async function simulateUpload() {
    if (!token || !sessionId) return;
    try {
      await apiFetch(`/sessions/${sessionId}/simulate-upload`, token, { method: "POST" });
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    }
  }

  async function saveConfig() {
    if (!token || !sessionId) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(configText) as Record<string, unknown>;
    } catch {
      setError("Configuration JSON is invalid.");
      return;
    }
    setBusy(true);
    try {
      const s = await apiFetch<Session>(`/sessions/${sessionId}/panel`, token, {
        method: "PATCH",
        body: JSON.stringify({
          panel_config: parsed,
          acknowledgement: "Saved problem settings.",
        }),
      });
      setSession(s);
      setEditMode("none");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function runOptimize() {
    if (!token || !sessionId || !session?.optimization_allowed) return;
    let panel: Record<string, unknown>;
    try {
      panel = JSON.parse(configText) as Record<string, unknown>;
    } catch {
      setError("Fix configuration JSON before running.");
      return;
    }
    const problem = (panel.problem ?? panel) as Record<string, unknown>;
    setBusy(true);
    setError(null);
    try {
      const run = await apiFetch<RunResult>(`/sessions/${sessionId}/runs`, token, {
        method: "POST",
        body: JSON.stringify({ type: "optimize", problem }),
      });
      setRuns((r) => {
        const next = [...r, run];
        setActiveRun(next.length - 1);
        return next;
      });
      void syncMessages();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run failed");
    } finally {
      setBusy(false);
    }
  }

  function parseRoutesForSolver(raw: unknown): number[][] | null {
    if (!Array.isArray(raw) || raw.length === 0) return null;
    const first = raw[0] as Record<string, unknown>;
    if (first && typeof first === "object" && "task_indices" in first) {
      const rows = [...raw] as { vehicle_index: number; task_indices: number[] }[];
      rows.sort((a, b) => a.vehicle_index - b.vehicle_index);
      return rows.map((r) => r.task_indices.map((x) => Number(x)));
    }
    return raw as number[][];
  }

  async function runEvaluateEdited() {
    if (!token || !sessionId) return;
    let routes: number[][] | null;
    try {
      routes = parseRoutesForSolver(JSON.parse(scheduleText) as unknown);
    } catch {
      setError("Schedule JSON is invalid.");
      return;
    }
    if (!routes || routes.length !== 5) {
      setError("Provide five vehicle routes (or neutral route objects from a run).");
      return;
    }
    let panel: Record<string, unknown>;
    try {
      panel = JSON.parse(configText) as Record<string, unknown>;
    } catch {
      setError("Fix configuration JSON.");
      return;
    }
    const problem = (panel.problem ?? panel) as Record<string, unknown>;
    setBusy(true);
    try {
      const run = await apiFetch<RunResult>(`/sessions/${sessionId}/runs`, token, {
        method: "POST",
        body: JSON.stringify({ type: "evaluate", problem, routes }),
      });
      setRuns((r) => {
        const next = [...r, run];
        setActiveRun(next.length - 1);
        return next;
      });
      void syncMessages();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Evaluate failed");
    } finally {
      setBusy(false);
    }
  }

  async function saveModelSettings() {
    if (!token || !sessionId) return;
    setBusy(true);
    try {
      const s = await apiFetch<Session>(`/sessions/${sessionId}/settings`, token, {
        method: "PATCH",
        body: JSON.stringify({
          gemini_api_key: modelKey || undefined,
          gemini_model: modelName || undefined,
        }),
      });
      setSession(s);
      setShowModelDialog(false);
      setModelKey("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Settings failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const r = runs[activeRun];
    if (r?.result?.schedule) {
      const sch = r.result.schedule as { routes?: unknown };
      if (sch.routes) setScheduleText(JSON.stringify(sch.routes, null, 2));
    }
  }, [activeRun, runs]);

  if (!authed) {
    return (
      <div className="app-shell">
        <header className="app-header">
          <span className="app-title">Participant</span>
        </header>
        <div className="login-panel">
          <p className="muted">
            Enter the access token for this station, then start. Workflow (e.g. agile vs waterfall) is set by the
            researcher for your session — you do not choose it here.
          </p>
          <label>
            Access token
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoComplete="off"
            />
          </label>
          <div style={{ marginTop: "1rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button type="button" onClick={() => void login()}>
              Save token
            </button>
            <button type="button" disabled={busy || !token.trim()} onClick={() => void startSession()}>
              Start session
            </button>
          </div>
          {error && <p className="banner-warn" style={{ marginTop: "1rem" }}>{error}</p>}
        </div>
      </div>
    );
  }

  const panelClass = (name: EditMode) =>
    editMode !== "none" && editMode !== name ? "panel panel-locked" : "panel";

  const currentRun = runs[activeRun];

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Participant</span>
        <span className="muted">
          Session {sessionId.slice(0, 8)}… · {session?.workflow_mode ?? "—"}
          {!session?.optimization_allowed ? " · runs gated" : ""}
        </span>
        <div style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
          <button type="button" className="chip" onClick={() => setShowModelDialog(true)}>
            Model / API key
          </button>
          <button
            type="button"
            onClick={() => {
              sessionStorage.removeItem(SESSION_KEY);
              setSessionId("");
              setSession(null);
              setMessages([]);
              setRuns([]);
            }}
          >
            Leave session
          </button>
        </div>
      </header>
      {error && <div className="banner-warn">{error}</div>}
      <div className="grid-3">
        <section className={panelClass("none")}>
          <div className="panel-header">Chat & upload</div>
          <div className="panel-body">
            <div className="chat-log" aria-live="polite">
              {messages.map((m, idx) => (
                <div
                  key={typeof m.id === "number" ? m.id : `m-${idx}`}
                  className={`bubble ${m.role === "user" ? "user" : "assistant"}`}
                >
                  <strong>{m.role}</strong>
                  <div>{m.content}</div>
                </div>
              ))}
            </div>
            <label className="muted">
              <input type="checkbox" checked={invokeModel} onChange={(e) => setInvokeModel(e.target.checked)} />{" "}
              Ask model (server key) — can update problem JSON when you ask (e.g. change weights)
            </label>
            <div className="chat-input-row">
              <textarea
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder="Message…"
                disabled={editMode !== "none"}
              />
              <button type="button" disabled={busy || editMode !== "none"} onClick={() => void sendChat()}>
                Send
              </button>
            </div>
            <div>
              <input ref={fileRef} type="file" hidden onChange={() => void simulateUpload()} />
              <button
                type="button"
                disabled={editMode !== "none"}
                onClick={() => fileRef.current?.click()}
              >
                Simulated upload
              </button>
              <span className="muted" style={{ marginLeft: "0.5rem" }}>
                (canonical scenario; no file contents used)
              </span>
            </div>
          </div>
        </section>

        <section className={editMode === "config" ? "panel" : panelClass("config")}>
          <div className="panel-header">
            Problem configuration
            {editMode === "config" && <span className="muted"> — editing</span>}
          </div>
          <div className="panel-body">
            <textarea
              className="mono"
              style={{ flex: 1, minHeight: "12rem", width: "100%" }}
              value={configText}
              onChange={(e) => setConfigText(e.target.value)}
              disabled={editMode !== "none" && editMode !== "config"}
              spellCheck={false}
            />
            <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
              {editMode !== "config" ? (
                <button type="button" onClick={() => setEditMode("config")} disabled={editMode !== "none"}>
                  Edit
                </button>
              ) : (
                <>
                  <button type="button" onClick={() => void saveConfig()} disabled={busy}>
                    Save
                  </button>
                  <button type="button" onClick={() => setEditMode("none")}>
                    Cancel
                  </button>
                </>
              )}
            </div>
          </div>
        </section>

        <section className={editMode === "results" ? "panel" : panelClass("results")}>
          <div className="panel-header">
            Results & schedule
            {editMode === "results" && <span className="muted"> — editing</span>}
          </div>
          <div className="panel-body">
            <div className="tabs">
              {runs.map((r, i) => (
                <button
                  key={r.id}
                  type="button"
                  className={`tab ${i === activeRun ? "active" : ""}`}
                  onClick={() => setActiveRun(i)}
                >
                  Run #{r.id} {r.ok ? "" : "✗"}
                </button>
              ))}
            </div>
            {currentRun && (
              <div className="mono muted">
                cost: {currentRun.cost ?? "—"} · {currentRun.ok ? "ok" : currentRun.error_message}
              </div>
            )}
            <textarea
              className="mono"
              style={{ flex: 1, minHeight: "10rem", width: "100%" }}
              value={scheduleText}
              onChange={(e) => setScheduleText(e.target.value)}
              disabled={editMode !== "none" && editMode !== "results"}
              spellCheck={false}
              placeholder='Routes JSON, e.g. [{"vehicle_index":0,"task_indices":[...]}, ...]'
            />
            <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
              <button
                type="button"
                disabled={busy || !session?.optimization_allowed || editMode !== "none"}
                onClick={() => void runOptimize()}
              >
                Run optimization
              </button>
              {editMode !== "results" ? (
                <button type="button" onClick={() => setEditMode("results")} disabled={editMode !== "none"}>
                  Edit schedule JSON
                </button>
              ) : (
                <>
                  <button type="button" disabled={busy} onClick={() => void runEvaluateEdited()}>
                    Re-score edited routes
                  </button>
                  <button type="button" onClick={() => setEditMode("none")}>
                    Done editing
                  </button>
                </>
              )}
            </div>
            {currentRun?.result?.violations != null ? (
              <pre className="mono" style={{ fontSize: "0.75rem", overflow: "auto", maxHeight: "8rem" }}>
                {JSON.stringify(currentRun.result.violations, null, 2)}
              </pre>
            ) : null}
          </div>
        </section>
      </div>

      {showModelDialog && (
        <div
          className="dialog-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="model-dlg-title"
        >
          <div className="dialog">
            <h2 id="model-dlg-title" style={{ margin: "0 0 0.5rem", fontSize: "1rem" }}>
              Model & API key
            </h2>
            <p className="muted" style={{ fontSize: "0.85rem" }}>
              Keys are stored on the server for this session (encrypted if the server is configured for it).
            </p>
            <label className="muted">
              Gemini model id
              <input
                style={{ width: "100%", marginTop: "0.2rem" }}
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
              />
            </label>
            <label className="muted" style={{ display: "block", marginTop: "0.5rem" }}>
              API key
              <input
                type="password"
                style={{ width: "100%", marginTop: "0.2rem" }}
                value={modelKey}
                onChange={(e) => setModelKey(e.target.value)}
                placeholder="Paste key (optional if researcher pushed one)"
              />
            </label>
            <div style={{ marginTop: "1rem", display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
              <button type="button" onClick={() => setShowModelDialog(false)}>
                Close
              </button>
              <button type="button" disabled={busy} onClick={() => void saveModelSettings()}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
