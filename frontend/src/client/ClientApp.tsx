import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  apiFetch,
  normalizePostMessagesResponse,
  sessionPanelToConfigText,
  type Message,
  type RunResult,
  type Session,
} from "@shared/api";
import { ChatAiPendingBubble, ChatPanel } from "@shared/ChatPanel";
import {
  DEFAULT_SUGGESTED_GEMINI_MODEL,
  GEMINI_MODEL_DATALIST_ID,
  GeminiModelDatalist,
} from "@shared/geminiModelSuggestions";
import {
  readSessionHistory,
  removeSessionHistoryEntry,
  upsertSessionHistoryFromServer,
} from "./sessionHistory";

const TOKEN_KEY = "mopt_client_token";
const SESSION_KEY = "mopt_session_id";

type EditMode = "none" | "config" | "results";

/**
 * How GET /sessions should update the problem-configuration textarea:
 * - follow: always mirror server `panel_config` (resume session, or after first real panel exists).
 * - empty_until_server_panel: keep empty while server panel is empty; then mirror like `follow`.
 */
type ProblemPanelHydration = "follow" | "empty_until_server_panel";

/** When `text` is omitted, leave the problem textarea unchanged (avoids wiping drafts while the server panel is still empty). */
function resolveProblemPanelFromServer(
  mode: ProblemPanelHydration,
  panel: Session["panel_config"],
): { text?: string; mode: ProblemPanelHydration } {
  const text = sessionPanelToConfigText(panel);
  if (mode === "empty_until_server_panel") {
    if (text !== "") {
      return { text, mode: "follow" };
    }
    return { mode: "empty_until_server_panel" };
  }
  return { text, mode: "follow" };
}

function isSessionGoneError(e: unknown): e is ApiError {
  return e instanceof ApiError && (e.status === 404 || e.status === 410);
}

function isAbortError(e: unknown): boolean {
  return (
    (typeof DOMException !== "undefined" && e instanceof DOMException && e.name === "AbortError") ||
    (e instanceof Error && e.name === "AbortError")
  );
}

/** Drop out-of-order GET /sessions/:id results so a slow poll cannot overwrite newer session state (e.g. API key flag). */
function isOlderSessionSnapshot(incoming: Session, prev: Session | null): boolean {
  if (!prev || prev.id !== incoming.id) return false;
  return Date.parse(incoming.updated_at) < Date.parse(prev.updated_at);
}

function coerceParticipantMessages(list: unknown): Message[] {
  if (!Array.isArray(list)) return [];
  return list.filter(
    (x): x is Message =>
      x !== null &&
      typeof x === "object" &&
      typeof (x as Message).id === "number",
  );
}

type RecentSessionRow = {
  id: string;
  session?: Session;
  error?: string;
};

export function ClientApp() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  const [sessionId, setSessionId] = useState(() => sessionStorage.getItem(SESSION_KEY) ?? "");
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [runs, setRuns] = useState<RunResult[]>([]);
  const [lastMsgId, setLastMsgId] = useState(0);
  const [chatInput, setChatInput] = useState("");
  const [invokeModel, setInvokeModel] = useState(true);
  const [configText, setConfigText] = useState("");
  const [scheduleText, setScheduleText] = useState("");
  const [activeRun, setActiveRun] = useState(0);
  const [editMode, setEditMode] = useState<EditMode>("none");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showModelDialog, setShowModelDialog] = useState(false);
  const [modelKey, setModelKey] = useState("");
  const [modelName, setModelName] = useState(DEFAULT_SUGGESTED_GEMINI_MODEL);
  /** Waiting for Gemini after sending with “invoke model” on */
  const [aiPending, setAiPending] = useState(false);
  const [recentRows, setRecentRows] = useState<RecentSessionRow[]>([]);
  const [recentBusy, setRecentBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const modelDialogWasOpenRef = useRef(false);
  /** Guards against stale sync responses after Leave / Start session (in-flight fetch). */
  const sessionIdRef = useRef(sessionId);
  const problemPanelHydrationRef = useRef<ProblemPanelHydration>("follow");
  const sessionRef = useRef<Session | null>(null);
  sessionRef.current = session;
  const editModeRef = useRef<EditMode>(editMode);
  editModeRef.current = editMode;
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  const authed = useMemo(() => Boolean(token && sessionId), [token, sessionId]);

  const invalidateRemovedSession = useCallback((message: string) => {
    const goneId = sessionIdRef.current;
    if (goneId) removeSessionHistoryEntry(goneId);
    sessionStorage.removeItem(SESSION_KEY);
    sessionIdRef.current = "";
    setSessionId("");
    setSession(null);
    setMessages([]);
    setRuns([]);
    setConfigText("");
    setScheduleText("");
    setLastMsgId(0);
    setEditMode("none");
    problemPanelHydrationRef.current = "follow";
    setError(message);
  }, []);

  const syncSession = useCallback(async (signal?: AbortSignal) => {
    if (!token || !sessionId) return;
    const requestedId = sessionId;
    try {
      const s = await apiFetch<Session>(`/sessions/${requestedId}`, token, { signal });
      if (sessionIdRef.current !== requestedId) return;
      if (signal?.aborted) return;
      if (isOlderSessionSnapshot(s, sessionRef.current)) return;
      setSession(s);
      const resolved = resolveProblemPanelFromServer(problemPanelHydrationRef.current, s.panel_config);
      problemPanelHydrationRef.current = resolved.mode;
      if (editModeRef.current !== "config" && resolved.text !== undefined) {
        setConfigText(resolved.text);
      }
      setError(null);
    } catch (e) {
      if (isAbortError(e)) return;
      if (sessionIdRef.current !== requestedId) return;
      if (isSessionGoneError(e)) {
        invalidateRemovedSession(
          "This session was deleted or is no longer available. Your access token is still saved below — start a new session when you are ready.",
        );
      } else {
        setError(e instanceof Error ? e.message : "Sync failed");
      }
    }
  }, [token, sessionId, invalidateRemovedSession]);

  const syncMessages = useCallback(async () => {
    if (!token || !sessionId) return;
    const requestedId = sessionId;
    const afterId = lastMsgId;
    try {
      const list = await apiFetch<unknown>(
        `/sessions/${requestedId}/messages?after_id=${afterId}`,
        token,
      );
      if (sessionIdRef.current !== requestedId) return;
      if (!Array.isArray(list)) return;
      const next = list.filter(
        (x): x is Message =>
          x !== null &&
          typeof x === "object" &&
          typeof (x as Message).id === "number",
      );
      if (next.length) {
        const maxIncoming = next[next.length - 1]!.id;
        setMessages((m) => {
          const seen = new Set(m.map((x) => x.id));
          const toAdd = next.filter((msg) => !seen.has(msg.id));
          if (!toAdd.length) {
            return m;
          }
          return [...m, ...toAdd];
        });
        setLastMsgId((prev) => Math.max(prev, maxIncoming));
      }
    } catch (e) {
      if (sessionIdRef.current !== requestedId) return;
      if (isSessionGoneError(e)) {
        invalidateRemovedSession(
          "This session was deleted or is no longer available. Your access token is still saved below — start a new session when you are ready.",
        );
      }
    }
  }, [token, sessionId, lastMsgId, invalidateRemovedSession]);

  const syncRuns = useCallback(async () => {
    if (!token || !sessionId) return;
    const requestedId = sessionId;
    try {
      const list = await apiFetch<unknown>(`/sessions/${requestedId}/runs`, token);
      if (sessionIdRef.current !== requestedId) return;
      if (!Array.isArray(list)) return;
      const nextRuns = list as RunResult[];
      setRuns((prev) => {
        if (nextRuns.length !== prev.length) {
          return nextRuns;
        }
        const changed = nextRuns.some((x, i) => x.id !== prev[i]?.id || x.ok !== prev[i]?.ok);
        return changed ? nextRuns : prev;
      });
      setActiveRun((i) => {
        const len = nextRuns.length;
        if (len === 0) return 0;
        return i >= len ? len - 1 : i;
      });
    } catch (e) {
      if (sessionIdRef.current !== requestedId) return;
      if (isSessionGoneError(e)) {
        invalidateRemovedSession(
          "This session was deleted or is no longer available. Your access token is still saved below — start a new session when you are ready.",
        );
      }
    }
  }, [token, sessionId, invalidateRemovedSession]);

  useEffect(() => {
    if (!authed) return;
    const ac = new AbortController();
    void syncSession(ac.signal);
    return () => ac.abort();
  }, [authed, syncSession]);

  useEffect(() => {
    if (!authed) return;
    const t = window.setInterval(() => {
      void syncSession();
      void syncMessages();
      void syncRuns();
    }, 1500);
    return () => window.clearInterval(t);
  }, [authed, syncSession, syncMessages, syncRuns]);

  useEffect(() => {
    if (!authed) {
      setRecentRows(readSessionHistory().map((e) => ({ id: e.id })));
    }
  }, [authed]);

  useEffect(() => {
    if (session?.status === "terminated") setEditMode("none");
  }, [session?.status]);

  useEffect(() => {
    if (showModelDialog && token && sessionId) void syncSession();
  }, [showModelDialog, token, sessionId, syncSession]);

  useEffect(() => {
    if (showModelDialog && !modelDialogWasOpenRef.current) {
      const m = session?.gemini_model?.trim();
      if (m) setModelName(m);
    }
    modelDialogWasOpenRef.current = showModelDialog;
  }, [showModelDialog, session]);

  useEffect(() => {
    if (!authed) return;
    const onVisible = () => {
      if (document.visibilityState === "visible") void syncSession();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [authed, syncSession]);

  async function login() {
    sessionStorage.setItem(TOKEN_KEY, token.trim());
    setToken(token.trim());
    setError(null);
  }

  const refreshRecentSessionsList = useCallback(async () => {
    const t = token.trim();
    if (!t) {
      setError("Save your access token first.");
      return;
    }
    setRecentBusy(true);
    setError(null);
    try {
      const entries = readSessionHistory();
      const next: RecentSessionRow[] = [];
      for (const e of entries) {
        try {
          const s = await apiFetch<Session>(`/sessions/${e.id}`, t);
          upsertSessionHistoryFromServer(s);
          next.push({ id: e.id, session: s });
        } catch (err) {
          if (err instanceof ApiError && (err.status === 404 || err.status === 410)) {
            removeSessionHistoryEntry(e.id);
          } else {
            next.push({
              id: e.id,
              error: err instanceof Error ? err.message : "Could not load",
            });
          }
        }
      }
      setRecentRows(next);
    } finally {
      setRecentBusy(false);
    }
  }, [token]);

  async function resumePastSession(resumeId: string) {
    const t = token.trim();
    if (!t) {
      setError("Save your access token first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const s = await apiFetch<Session>(`/sessions/${resumeId}`, t);
      sessionIdRef.current = resumeId;
      setSessionId(resumeId);
      sessionStorage.setItem(TOKEN_KEY, t);
      sessionStorage.setItem(SESSION_KEY, resumeId);
      setSession(s);
      problemPanelHydrationRef.current = "follow";
      setConfigText(sessionPanelToConfigText(s.panel_config));
      setMessages([]);
      setLastMsgId(0);
      setRuns([]);
      setActiveRun(0);
      setScheduleText("");
      setEditMode("none");
      setChatInput("");

      const rawMsgs = await apiFetch<unknown>(`/sessions/${resumeId}/messages?after_id=0`, t);
      const msgs = coerceParticipantMessages(rawMsgs);
      setMessages(msgs);
      if (msgs.length) setLastMsgId(msgs[msgs.length - 1]!.id);

      const rawRuns = await apiFetch<unknown>(`/sessions/${resumeId}/runs`, t);
      const runList = Array.isArray(rawRuns) ? (rawRuns as RunResult[]) : [];
      setRuns(runList);
      setActiveRun(runList.length ? runList.length - 1 : 0);

      upsertSessionHistoryFromServer(s);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 410)) {
        removeSessionHistoryEntry(resumeId);
        setRecentRows(readSessionHistory().map((en) => ({ id: en.id })));
        setError("That session no longer exists; removed from this browser list.");
      } else {
        setError(e instanceof Error ? e.message : "Could not open session");
      }
    } finally {
      setBusy(false);
    }
  }

  async function startSession() {
    if (!token.trim()) {
      setError("Enter access token first.");
      return;
    }
    sessionIdRef.current = "";
    setBusy(true);
    setError(null);
    setEditMode("none");
    setChatInput("");
    setConfigText("");
    setScheduleText("");
    try {
      const s = await apiFetch<Session>("/sessions", token.trim(), {
        method: "POST",
        body: JSON.stringify({}),
      });
      sessionIdRef.current = s.id;
      setSessionId(s.id);
      sessionStorage.setItem(TOKEN_KEY, token.trim());
      sessionStorage.setItem(SESSION_KEY, s.id);
      setSession(s);
      setMessages([]);
      setLastMsgId(0);
      setRuns([]);
      setScheduleText("");
      setConfigText("");
      problemPanelHydrationRef.current = "empty_until_server_panel";
      upsertSessionHistoryFromServer(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create session");
    } finally {
      setBusy(false);
    }
  }

  async function sendChat() {
    if (!chatInput.trim() || !token || !sessionId || session?.status === "terminated") return;
    const text = chatInput.trim();
    const tempUserId = -Date.now();
    const optimisticUser: Message = {
      id: tempUserId,
      created_at: new Date().toISOString(),
      role: "user",
      content: text,
      visible_to_participant: true,
      kind: "chat",
    };
    setMessages((m) => [...m, optimisticUser]);
    setChatInput("");
    setError(null);
    setBusy(true);
    setAiPending(invokeModel);
    try {
      const raw = await apiFetch<unknown>(`/sessions/${sessionId}/messages`, token, {
        method: "POST",
        body: JSON.stringify({ content: text, invoke_model: invokeModel }),
      });
      const res = normalizePostMessagesResponse(raw);
      const out = res.messages;
      setMessages((m) => [...m.filter((x) => x.id >= 0), ...out]);
      if (out.length) setLastMsgId(out[out.length - 1]!.id);
      if (res.panel_config != null) {
        problemPanelHydrationRef.current = "follow";
        setConfigText(sessionPanelToConfigText(res.panel_config as Session["panel_config"]));
        setSession((prev) =>
          prev ? { ...prev, panel_config: res.panel_config as Session["panel_config"] } : prev,
        );
      }
    } catch (e) {
      setMessages((m) => m.filter((x) => x.id !== tempUserId));
      setChatInput(text);
      setError(e instanceof Error ? e.message : "Send failed");
    } finally {
      setBusy(false);
      setAiPending(false);
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
      const raw = configText.trim();
      parsed = raw === "" ? {} : (JSON.parse(raw) as Record<string, unknown>);
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
      problemPanelHydrationRef.current = "follow";
      setConfigText(sessionPanelToConfigText(s.panel_config));
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
    const submittedKey = modelKey.trim();
    setBusy(true);
    try {
      const s = await apiFetch<Session>(`/sessions/${sessionId}/settings`, token, {
        method: "PATCH",
        body: JSON.stringify({
          gemini_api_key: modelKey || undefined,
          gemini_model: modelName || undefined,
        }),
      });
      setSession({
        ...s,
        gemini_key_configured:
          submittedKey.length > 0 ? true : Boolean(s.gemini_key_configured),
      });
      setShowModelDialog(false);
      setModelKey("");
      void syncSession();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Settings failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (runs.length === 0) {
      setScheduleText("");
      return;
    }
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
          {error && (
            <p className="banner-warn" style={{ marginBottom: "1rem" }}>
              {error}
            </p>
          )}
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
          <details style={{ marginTop: "1.25rem" }} className="login-recent-sessions">
            <summary style={{ cursor: "pointer", fontWeight: 600 }}>
              Past sessions on this browser
            </summary>
            <p className="muted" style={{ fontSize: "0.85rem", marginTop: "0.5rem" }}>
              Session ids are stored only on this device (not by IP on the server). You still need the same access
              token to open them. Anyone with this browser profile can see these entries.
            </p>
            <div style={{ marginTop: "0.5rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <button
                type="button"
                disabled={recentBusy || !token.trim()}
                onClick={() => void refreshRecentSessionsList()}
              >
                {recentBusy ? "Checking…" : "Refresh list"}
              </button>
            </div>
            {recentRows.length === 0 ? (
              <p className="muted" style={{ marginTop: "0.75rem", fontSize: "0.9rem" }}>
                None yet — they appear after you start or leave a session.
              </p>
            ) : (
              <ul
                className="recent-session-list"
                style={{ listStyle: "none", padding: 0, marginTop: "0.75rem", maxHeight: "14rem", overflow: "auto" }}
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
                      {row.id.slice(0, 8)}…{row.id.slice(-4)}
                    </div>
                    {row.error ? (
                      <span className="muted">{row.error}</span>
                    ) : row.session ? (
                      <div className="muted">
                        {row.session.workflow_mode} · {row.session.status}
                        {row.session.status === "terminated" ? " (read-only)" : ""}
                      </div>
                    ) : (
                      <span className="muted">Optional: Refresh list to show status — Resume still works if the id is valid.</span>
                    )}
                    <div style={{ marginTop: "0.35rem", display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                      <button
                        type="button"
                        disabled={busy || !token.trim() || Boolean(row.error)}
                        onClick={() => void resumePastSession(row.id)}
                      >
                        Resume
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          removeSessionHistoryEntry(row.id);
                          setRecentRows(readSessionHistory().map((e) => ({ id: e.id })));
                        }}
                      >
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

  const panelClass = (name: EditMode) =>
    editMode !== "none" && editMode !== name ? "panel panel-locked" : "panel";

  const currentRun = runs[activeRun];
  const sessionTerminated = session?.status === "terminated";
  const chatLocked = sessionTerminated;
  const modelKeyStatus =
    session == null ? "neutral" : session.gemini_key_configured ? "ok" : "warn";
  const modelKeyIcon = modelKeyStatus === "ok" ? "✓" : modelKeyStatus === "warn" ? "⚠" : "○";

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Participant</span>
        <span className="muted">
          Session {sessionId.slice(0, 8)}… · {session?.workflow_mode ?? "—"}
          {sessionTerminated ? " · ended" : ""}
          {!session?.optimization_allowed ? " · runs gated" : ""}
        </span>
        <div style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
          <button
            type="button"
            className={`btn-model-key status-${modelKeyStatus}`}
            title={
              modelKeyStatus === "ok"
                ? "API key is set for this session"
                : modelKeyStatus === "warn"
                  ? "No API key on the session — add one or ask the researcher"
                  : "Session loading"
            }
            onClick={() => setShowModelDialog(true)}
          >
            <span className="model-key-icon" aria-hidden>
              {modelKeyIcon}
            </span>
            Model / API key
          </button>
          <button
            type="button"
            onClick={() => {
              if (session) upsertSessionHistoryFromServer(session);
              sessionStorage.removeItem(SESSION_KEY);
              setSessionId("");
              setSession(null);
              setMessages([]);
              setRuns([]);
              setConfigText("");
              setScheduleText("");
              problemPanelHydrationRef.current = "follow";
              setError(null);
            }}
          >
            Leave session
          </button>
        </div>
      </header>
      {sessionTerminated && (
        <div className="banner-info" role="status">
          <span>
            This session was ended by the researcher. You can still read chat and runs below. Start a new session
            when you are ready to continue.
          </span>
          <button type="button" disabled={busy} onClick={() => void startSession()}>
            Start new session
          </button>
        </div>
      )}
      {error && !sessionTerminated && <div className="banner-warn">{error}</div>}
      <div className="grid-3">
        <section className={panelClass("none")}>
          <ChatPanel
            title="Chat & upload"
            messages={
              <>
                {messages.map((m, idx) => (
                  <div
                    key={m.id < 0 ? `tmp-${m.id}-${idx}` : m.id}
                    className={`bubble ${m.role === "user" ? "user" : "assistant"}`}
                  >
                    <strong>{m.role}</strong>
                    <div>{m.content}</div>
                  </div>
                ))}
                {aiPending && <ChatAiPendingBubble />}
              </>
            }
            betweenLogAndComposer={
              <details className="muted chat-model-details" {...(chatLocked ? { open: false } : {})}>
                <summary style={chatLocked ? { pointerEvents: "none", opacity: 0.55 } : undefined}>
                  Ask model (requires API key).{" "}
                  <span className="chat-model-state">{invokeModel ? "On" : "Off"}</span>
                </summary>
                <div className="chat-model-check-wrap">
                  <input
                    type="checkbox"
                    checked={invokeModel}
                    onChange={(e) => setInvokeModel(e.target.checked)}
                    aria-label="Ask model (requires API key)."
                    disabled={chatLocked}
                  />
                </div>
              </details>
            }
            footer={
              <div>
                <input ref={fileRef} type="file" hidden onChange={() => void simulateUpload()} />
                <button
                  type="button"
                  disabled={editMode !== "none" || chatLocked}
                  onClick={() => fileRef.current?.click()}
                >
                  Simulated upload
                </button>
                <span className="muted" style={{ marginLeft: "0.5rem" }}>
                  (canonical scenario; no file contents used)
                </span>
              </div>
            }
            composer={{
              value: chatInput,
              onChange: setChatInput,
              onSend: sendChat,
              sendDisabled: busy || editMode !== "none" || chatLocked,
              textareaDisabled: editMode !== "none" || chatLocked,
              sendLabel: "Send",
              placeholder: "Message… (Enter to send, Shift+Enter for newline)",
              inputRowClassName: chatLocked ? "chat-input-locked" : undefined,
            }}
          />
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
              disabled={sessionTerminated || (editMode !== "none" && editMode !== "config")}
              spellCheck={false}
              placeholder="Metaheuristic / solver control panel (JSON): problem definition, algorithm parameters, and stopping criteria. Start empty — paste, edit, or receive updates from the conversation / researcher when provided."
            />
            <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
              {editMode !== "config" ? (
                <button
                  type="button"
                  onClick={() => setEditMode("config")}
                  disabled={editMode !== "none" || sessionTerminated}
                >
                  Edit
                </button>
              ) : (
                <>
                  <button type="button" onClick={() => void saveConfig()} disabled={busy || sessionTerminated}>
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
              disabled={sessionTerminated || (editMode !== "none" && editMode !== "results")}
              spellCheck={false}
              placeholder="Run optimization to populate routes, or paste JSON once a problem configuration exists."
            />
            <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
              <button
                type="button"
                disabled={
                  busy || !session?.optimization_allowed || editMode !== "none" || sessionTerminated
                }
                onClick={() => void runOptimize()}
              >
                Run optimization
              </button>
              {editMode !== "results" ? (
                <button
                  type="button"
                  onClick={() => setEditMode("results")}
                  disabled={editMode !== "none" || sessionTerminated}
                >
                  Edit schedule JSON
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    disabled={busy || sessionTerminated}
                    onClick={() => void runEvaluateEdited()}
                  >
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
            <GeminiModelDatalist />
            <label className="muted">
              Gemini model id
              <input
                style={{ width: "100%", marginTop: "0.2rem" }}
                list={GEMINI_MODEL_DATALIST_ID}
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder={DEFAULT_SUGGESTED_GEMINI_MODEL}
                autoComplete="off"
              />
            </label>
            <p className="muted" style={{ fontSize: "0.75rem", margin: "0.25rem 0 0" }}>
              Pick a suggestion or type any model id your key supports.
            </p>
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
              <button
                type="button"
                onClick={() => {
                  setShowModelDialog(false);
                  void syncSession();
                }}
              >
                Close
              </button>
              <button
                type="button"
                disabled={busy || sessionTerminated}
                onClick={() => void saveModelSettings()}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
