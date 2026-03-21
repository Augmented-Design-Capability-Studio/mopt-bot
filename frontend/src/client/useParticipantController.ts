import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  apiFetch,
  displayRunNumber,
  normalizePostMessagesResponse,
  sessionPanelToConfigText,
  type Message,
  type RunResult,
  type Session,
} from "@shared/api";
import { DEFAULT_SUGGESTED_GEMINI_MODEL } from "@shared/geminiModelSuggestions";

import { configChangeSummary } from "./configSummary";
import { mergeMessagesFromPoll, mergeMessagesFromPost } from "./messageMerge";
import {
  type ProblemPanelHydration,
  resolveProblemPanelFromServer,
} from "./problemPanelHydration";
import { type EditMode, type RecentSessionRow } from "./participantTypes";
import { parseRoutesForSolver } from "./schedule";
import {
  coerceParticipantMessages,
  isAbortError,
  isOlderSessionSnapshot,
  isSessionGoneError,
} from "./sessionGuards";
import {
  readSessionHistory,
  removeSessionHistoryEntry,
  upsertSessionHistoryFromServer,
} from "./sessionHistory";

const TOKEN_KEY = "mopt_client_token";
const SESSION_KEY = "mopt_session_id";

export function useParticipantController() {
  const [token, setToken] = useState(
    () => sessionStorage.getItem(TOKEN_KEY) ?? "",
  );
  const [sessionId, setSessionId] = useState(
    () => sessionStorage.getItem(SESSION_KEY) ?? "",
  );
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
  const [optimizing, setOptimizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showModelDialog, setShowModelDialog] = useState(false);
  const [modelKey, setModelKey] = useState("");
  const [modelName, setModelName] = useState(DEFAULT_SUGGESTED_GEMINI_MODEL);
  const [aiPending, setAiPending] = useState(false);
  const [recentRows, setRecentRows] = useState<RecentSessionRow[]>([]);
  const [recentBusy, setRecentBusy] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);
  const modelDialogWasOpenRef = useRef(false);
  const sessionIdRef = useRef(sessionId);
  const problemPanelHydrationRef =
    useRef<ProblemPanelHydration>("follow");
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

  const syncSession = useCallback(
    async (signal?: AbortSignal) => {
      if (!token || !sessionId) return;
      const requestedId = sessionId;
      try {
        const s = await apiFetch<Session>(`/sessions/${requestedId}`, token, {
          signal,
        });
        if (sessionIdRef.current !== requestedId) return;
        if (signal?.aborted) return;
        if (isOlderSessionSnapshot(s, sessionRef.current)) return;
        setSession(s);
        const resolved = resolveProblemPanelFromServer(
          problemPanelHydrationRef.current,
          s.panel_config,
        );
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
    },
    [invalidateRemovedSession, sessionId, token],
  );

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
      const next = coerceParticipantMessages(list);
      if (next.length) {
        const maxIncoming = next[next.length - 1]!.id;
        setMessages((m) => mergeMessagesFromPoll(m, next));
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
  }, [invalidateRemovedSession, lastMsgId, sessionId, token]);

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
        const changed = nextRuns.some(
          (x, i) => x.id !== prev[i]?.id || x.ok !== prev[i]?.ok,
        );
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
  }, [invalidateRemovedSession, sessionId, token]);

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
  }, [authed, syncMessages, syncRuns, syncSession]);

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
  }, [sessionId, showModelDialog, syncSession, token]);

  useEffect(() => {
    if (showModelDialog && !modelDialogWasOpenRef.current) {
      const model = session?.gemini_model?.trim();
      if (model) setModelName(model);
    }
    modelDialogWasOpenRef.current = showModelDialog;
  }, [session, showModelDialog]);

  useEffect(() => {
    if (!authed) return;
    const onVisible = () => {
      if (document.visibilityState === "visible") void syncSession();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [authed, syncSession]);

  useEffect(() => {
    if (runs.length === 0) {
      setScheduleText("");
      return;
    }
    const run = runs[activeRun];
    if (run?.result?.schedule) {
      const schedule = run.result.schedule as { routes?: unknown };
      if (schedule.routes) {
        setScheduleText(JSON.stringify(schedule.routes, null, 2));
      }
    }
  }, [activeRun, runs]);

  async function login() {
    sessionStorage.setItem(TOKEN_KEY, token.trim());
    setToken(token.trim());
    setError(null);
  }

  const refreshRecentSessionsList = useCallback(async () => {
    const trimmed = token.trim();
    if (!trimmed) {
      setError("Save your access token first.");
      return;
    }
    setRecentBusy(true);
    setError(null);
    try {
      const entries = readSessionHistory();
      const next: RecentSessionRow[] = [];
      for (const entry of entries) {
        try {
          const s = await apiFetch<Session>(`/sessions/${entry.id}`, trimmed);
          upsertSessionHistoryFromServer(s);
          next.push({ id: entry.id, session: s });
        } catch (err) {
          if (err instanceof ApiError && (err.status === 404 || err.status === 410)) {
            removeSessionHistoryEntry(entry.id);
          } else {
            next.push({
              id: entry.id,
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
    const trimmed = token.trim();
    if (!trimmed) {
      setError("Save your access token first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const s = await apiFetch<Session>(`/sessions/${resumeId}`, trimmed);
      sessionIdRef.current = resumeId;
      setSessionId(resumeId);
      sessionStorage.setItem(TOKEN_KEY, trimmed);
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

      const rawMsgs = await apiFetch<unknown>(
        `/sessions/${resumeId}/messages?after_id=0`,
        trimmed,
      );
      const msgs = coerceParticipantMessages(rawMsgs);
      setMessages(msgs);
      if (msgs.length) setLastMsgId(msgs[msgs.length - 1]!.id);

      const rawRuns = await apiFetch<unknown>(`/sessions/${resumeId}/runs`, trimmed);
      const runList = Array.isArray(rawRuns) ? (rawRuns as RunResult[]) : [];
      setRuns(runList);
      setActiveRun(runList.length ? runList.length - 1 : 0);

      upsertSessionHistoryFromServer(s);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 410)) {
        removeSessionHistoryEntry(resumeId);
        setRecentRows(readSessionHistory().map((entry) => ({ id: entry.id })));
        setError("That session no longer exists; removed from this browser list.");
      } else {
        setError(e instanceof Error ? e.message : "Could not open session");
      }
    } finally {
      setBusy(false);
    }
  }

  async function startSession() {
    const trimmed = token.trim();
    if (!trimmed) {
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
      const s = await apiFetch<Session>("/sessions", trimmed, {
        method: "POST",
        body: JSON.stringify({}),
      });
      sessionIdRef.current = s.id;
      setSessionId(s.id);
      sessionStorage.setItem(TOKEN_KEY, trimmed);
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

  async function postContextMessage(content: string, withModel: boolean) {
    if (!token || !sessionId || session?.status === "terminated") return;
    const tempId = -Date.now() - Math.random();
    const optimistic: Message = {
      id: tempId,
      created_at: new Date().toISOString(),
      role: "user",
      content,
      visible_to_participant: true,
      kind: "chat",
    };
    setMessages((m) => [...m, optimistic]);
    setAiPending(withModel);
    try {
      const raw = await apiFetch<unknown>(`/sessions/${sessionId}/messages`, token, {
        method: "POST",
        body: JSON.stringify({ content, invoke_model: withModel }),
      });
      const res = normalizePostMessagesResponse(raw);
      const out = res.messages;
      setMessages((m) => mergeMessagesFromPost(m, out));
      if (out.length) setLastMsgId(out[out.length - 1]!.id);
      if (res.panel_config != null) {
        problemPanelHydrationRef.current = "follow";
        setConfigText(sessionPanelToConfigText(res.panel_config));
        setSession((prev) =>
          prev ? { ...prev, panel_config: res.panel_config } : prev,
        );
      }
    } catch {
      setMessages((m) => m.filter((x) => x.id !== tempId));
    } finally {
      setAiPending(false);
    }
  }

  async function sendChat() {
    if (!chatInput.trim() || !token || !sessionId || session?.status === "terminated") {
      return;
    }
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
      setMessages((m) => mergeMessagesFromPost(m, out));
      if (out.length) setLastMsgId(out[out.length - 1]!.id);
      if (res.panel_config != null) {
        problemPanelHydrationRef.current = "follow";
        setConfigText(sessionPanelToConfigText(res.panel_config));
        setSession((prev) =>
          prev ? { ...prev, panel_config: res.panel_config } : prev,
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
      await apiFetch(`/sessions/${sessionId}/simulate-upload`, token, {
        method: "POST",
      });
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
    const previousPanel = session?.panel_config ?? null;
    const changedKeys = configChangeSummary(previousPanel, parsed);
    const acknowledgement = `Problem configuration saved (changed: ${changedKeys}).`;
    setBusy(true);
    try {
      const s = await apiFetch<Session>(`/sessions/${sessionId}/panel`, token, {
        method: "PATCH",
        body: JSON.stringify({
          panel_config: parsed,
          acknowledgement,
        }),
      });
      setSession(s);
      problemPanelHydrationRef.current = "follow";
      setConfigText(sessionPanelToConfigText(s.panel_config));
      setEditMode("none");
      if (invokeModel) {
        await postContextMessage(
          `I just manually updated the problem configuration. Changed fields: ${changedKeys}. Please acknowledge the change and briefly explain the expected impact on the solver.`,
          true,
        );
      }
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
    setOptimizing(true);
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
      if (invokeModel && run.ok) {
        const violations = (run.result as Record<string, unknown> | null | undefined)
          ?.violations as Record<string, unknown> | undefined;
        const violationSummary = violations
          ? [
              violations.time_window_stop_count
                ? `${violations.time_window_stop_count} time-window stops late`
                : "",
              violations.priority_deadline_misses
                ? `${violations.priority_deadline_misses} priority misses`
                : "",
              violations.capacity_units_over
                ? `${violations.capacity_units_over} units over capacity`
                : "",
            ]
              .filter(Boolean)
              .join(", ") || "no violations"
          : "unknown";
        await postContextMessage(
          `Run #${displayRunNumber(run)} just completed — cost ${run.cost?.toFixed(2) ?? "?"} (${violationSummary}). Please interpret these results, compare to any previous runs, and suggest what to adjust next.`,
          true,
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run failed");
    } finally {
      setBusy(false);
      setOptimizing(false);
    }
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

  function leaveSession() {
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
  }

  function forgetRecentSession(id: string) {
    removeSessionHistoryEntry(id);
    setRecentRows(readSessionHistory().map((e) => ({ id: e.id })));
  }

  function closeModelDialog() {
    setShowModelDialog(false);
    void syncSession();
  }

  return {
    token,
    sessionId,
    session,
    messages,
    runs,
    currentRun: runs[activeRun],
    activeRun,
    chatInput,
    invokeModel,
    configText,
    scheduleText,
    editMode,
    busy,
    optimizing,
    error,
    showModelDialog,
    modelKey,
    modelName,
    aiPending,
    recentRows,
    recentBusy,
    authed,
    fileRef,
    setToken,
    setActiveRun,
    setChatInput,
    setInvokeModel,
    setConfigText,
    setScheduleText,
    setEditMode,
    setShowModelDialog,
    setModelKey,
    setModelName,
    login,
    refreshRecentSessionsList,
    resumePastSession,
    startSession,
    sendChat,
    simulateUpload,
    saveConfig,
    runOptimize,
    runEvaluateEdited,
    saveModelSettings,
    leaveSession,
    forgetRecentSession,
    closeModelDialog,
  };
}
