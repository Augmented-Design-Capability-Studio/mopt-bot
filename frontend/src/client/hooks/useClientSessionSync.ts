import { useCallback, useEffect, useMemo, useRef, type MutableRefObject } from "react";

import { apiFetch, type Message, type RunResult, type Session } from "@shared/api";
import type { ProblemPanelHydration } from "../problemConfig/problemPanelHydration";
import { resolveProblemPanelFromServer } from "../problemConfig/problemPanelHydration";
import { type EditMode, type RecentSessionRow } from "../lib/clientTypes";
import { CONTENT_RESET_REV_PREFIX, SESSION_KEY } from "../lib/sessionKeys";
import {
  coerceParticipantMessages,
  isAbortError,
  isOlderSessionSnapshot,
  isSessionGoneError,
} from "../lib/sessionGuards";
import { readSessionHistory, removeSessionHistoryEntry } from "../lib/sessionHistory";
import { mergeMessageUpdate, mergeMessagesFromPoll } from "../chat/messageMerge";

const MESSAGE_POLL_MS = 4000;
const RUN_POLL_MS = 8000;
const SESSION_POLL_MS = 15000;
const EAGER_POLL_INTERVAL_MS = 2000;
const EAGER_POLL_DURATION_MS = 10000;
/** Refetch cadence for messages whose `meta.verifying` flag is still set.
 *  The async-verification pipeline typically completes in well under 10s,
 *  but the brief-update LLM call + a retry can push past that. 1.5s feels
 *  responsive without hammering the API. */
const VERIFYING_POLL_INTERVAL_MS = 1500;
/** Session GET while definition/config derivation is pending (faster than SESSION_POLL_MS). */
const PROCESSING_PENDING_SESSION_POLL_MS = 2500;
const TUTORIAL_REFRESH_SIGNAL_KEY = "mopt_participant_tutorial_refresh";

function isRunStillPending(run: RunResult): boolean {
  if (run.clientPending) return true;
  return !run.ok && run.result == null && !run.error_message;
}

type UseParticipantSessionSyncArgs = {
  token: string;
  sessionId: string;
  authed: boolean;
  lastMsgId: number;
  activeRun: number;
  /** Local message list — used to detect which assistant messages still carry
   *  `meta.verifying=true` so we can poll those specific rows for updates. */
  messages: Message[];
  /** When true, periodic run list sync is skipped (avoids ghost tabs during optimize). */
  optimizingRef: MutableRefObject<boolean>;
  runs: RunResult[];
  session: Session | null;
  showModelDialog: boolean;
  sessionIdRef: MutableRefObject<string>;
  problemPanelHydrationRef: MutableRefObject<ProblemPanelHydration>;
  sessionRef: MutableRefObject<Session | null>;
  editModeRef: MutableRefObject<EditMode>;
  modelDialogWasOpenRef: MutableRefObject<boolean>;
  setSessionId: (value: string) => void;
  setSession: (value: Session | null | ((prev: Session | null) => Session | null)) => void;
  setMessages: (value: ((prev: import("@shared/api").Message[]) => import("@shared/api").Message[]) | import("@shared/api").Message[]) => void;
  setRuns: (value: RunResult[] | ((prev: RunResult[]) => RunResult[])) => void;
  setConfigText: (value: string) => void;
  setProblemBrief: (value: import("@shared/api").ProblemBrief | null) => void;
  setScheduleText: (value: string) => void;
  setOptimizing: (value: boolean) => void;
  setLastMsgId: (value: number | ((prev: number) => number)) => void;
  setActiveRun: (value: number | ((prev: number) => number)) => void;
  setEditMode: (value: EditMode) => void;
  setError: (value: string | null) => void;
  setRecentRows: (value: RecentSessionRow[]) => void;
  setModelName: (value: string) => void;
  setEmbeddingModel: (value: string) => void;
  /** Default model from server config (.env MOPT_DEFAULT_GEMINI_MODEL); used when no session model is set. */
  defaultModel: string;
  /** Default embedding model from server config (.env MOPT_DEFAULT_EMBEDDING_MODEL). */
  defaultEmbeddingModel: string;
};

export function useClientSessionSync({
  token,
  sessionId,
  authed,
  lastMsgId,
  activeRun,
  messages,
  optimizingRef,
  runs,
  session,
  showModelDialog,
  sessionIdRef,
  problemPanelHydrationRef,
  sessionRef,
  editModeRef,
  modelDialogWasOpenRef,
  setSessionId,
  setSession,
  setMessages,
  setRuns,
  setConfigText,
  setProblemBrief,
  setScheduleText,
  setOptimizing,
  setLastMsgId,
  setActiveRun,
  setEditMode,
  setError,
  setRecentRows,
  setModelName,
  setEmbeddingModel,
  defaultModel,
  defaultEmbeddingModel,
}: UseParticipantSessionSyncArgs) {
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId, sessionIdRef]);

  const invalidateRemovedSession = useCallback(
    (message: string) => {
      const goneId = sessionIdRef.current;
      if (goneId) removeSessionHistoryEntry(goneId);
      sessionStorage.removeItem(SESSION_KEY);
      sessionIdRef.current = "";
      setSessionId("");
      setSession(null);
      setMessages([]);
      setRuns([]);
      setConfigText("");
      setProblemBrief(null);
      setScheduleText("");
      setLastMsgId(0);
      setEditMode("none");
      problemPanelHydrationRef.current = "follow";
      setError(message);
    },
    [
      problemPanelHydrationRef,
      sessionIdRef,
      setConfigText,
      setEditMode,
      setError,
      setLastMsgId,
      setMessages,
      setProblemBrief,
      setRuns,
      setScheduleText,
      setSession,
      setSessionId,
    ],
  );

  const syncSession = useCallback(
    async (signal?: AbortSignal) => {
      if (!token || !sessionId) return;
      const requestedId = sessionId;
      try {
        const nextSession = await apiFetch<Session>(`/sessions/${requestedId}`, token, { signal });
        if (sessionIdRef.current !== requestedId) return;
        if (signal?.aborted) return;
        if (isOlderSessionSnapshot(nextSession, sessionRef.current)) return;

        const revKey = `${CONTENT_RESET_REV_PREFIX}${requestedId}`;
        const serverRev = nextSession.content_reset_revision ?? 0;
        const prevRaw = sessionStorage.getItem(revKey);
        if (prevRaw !== null) {
          const prev = Number(prevRaw);
          if (Number.isFinite(serverRev) && serverRev > prev) {
            sessionStorage.setItem(revKey, String(serverRev));
            window.location.reload();
            return;
          }
        }
        sessionStorage.setItem(revKey, String(serverRev));

        setSession(nextSession);
        const resolved = resolveProblemPanelFromServer(problemPanelHydrationRef.current, nextSession.panel_config);
        problemPanelHydrationRef.current = resolved.mode;
        if (editModeRef.current !== "definition") {
          setProblemBrief(nextSession.problem_brief);
        }
        if (editModeRef.current !== "config" && resolved.text !== undefined) {
          setConfigText(resolved.text);
        }
        setError(null);
      } catch (error) {
        if (isAbortError(error)) return;
        if (sessionIdRef.current !== requestedId) return;
        if (isSessionGoneError(error)) {
          invalidateRemovedSession(
            "This session was deleted or is no longer available. Your access token is still saved below - start a new session when you are ready.",
          );
        } else {
          setError(error instanceof Error ? error.message : "Sync failed");
        }
      }
    },
    [
      editModeRef,
      invalidateRemovedSession,
      problemPanelHydrationRef,
      sessionId,
      sessionIdRef,
      sessionRef,
      setConfigText,
      setError,
      setSession,
      setProblemBrief,
      token,
    ],
  );

  const syncMessages = useCallback(async () => {
    if (!token || !sessionId) return;
    const requestedId = sessionId;
    try {
      const list = await apiFetch<unknown>(`/sessions/${requestedId}/messages?after_id=${lastMsgId}`, token);
      if (sessionIdRef.current !== requestedId) return;
      const nextMessages = coerceParticipantMessages(list);
      if (nextMessages.length) {
        const maxIncoming = nextMessages[nextMessages.length - 1]!.id;
        const hasRunPending = nextMessages.some((m) => m.kind === "run_pending");
        if (hasRunPending) {
          setOptimizing(true);
        }
        setMessages((current) => mergeMessagesFromPoll(current, nextMessages));
        setLastMsgId((previous) => Math.max(previous, maxIncoming));
        // Pull a fresh session snapshot too so processing state (brief/config "pending")
        // becomes visible immediately. Otherwise, when a new user message lands via
        // polling (e.g. researcher pushed dummy files / simulated upload), the chat
        // pending-spinner only updates on the slower session poll cadence.
        void syncSessionRef.current();
      }
    } catch (error) {
      if (sessionIdRef.current !== requestedId) return;
      if (isSessionGoneError(error)) {
        invalidateRemovedSession(
          "This session was deleted or is no longer available. Your access token is still saved below - start a new session when you are ready.",
        );
      }
    }
  }, [invalidateRemovedSession, lastMsgId, sessionId, sessionIdRef, setLastMsgId, setMessages, setOptimizing, token]);

  // Always holds the latest syncMessages so the eager-poll timer doesn't
  // capture a stale closure from when it was started.
  const syncMessagesRef = useRef(syncMessages);
  syncMessagesRef.current = syncMessages;
  const syncSessionRef = useRef(syncSession);
  syncSessionRef.current = syncSession;
  const eagerTimerRef = useRef<number | null>(null);

  const startEagerMessagePoll = useCallback(() => {
    if (eagerTimerRef.current !== null) window.clearInterval(eagerTimerRef.current);
    const startedAt = Date.now();
    eagerTimerRef.current = window.setInterval(() => {
      if (Date.now() - startedAt >= EAGER_POLL_DURATION_MS) {
        window.clearInterval(eagerTimerRef.current!);
        eagerTimerRef.current = null;
        return;
      }
      void syncMessagesRef.current();
      void syncSessionRef.current();
    }, EAGER_POLL_INTERVAL_MS);
  }, []);

  const syncRuns = useCallback(async () => {
    if (!token || !sessionId) return;
    if (optimizingRef.current && runs.some((r) => r.clientPending)) return;
    const requestedId = sessionId;
    try {
      const list = await apiFetch<unknown>(`/sessions/${requestedId}/runs`, token);
      if (sessionIdRef.current !== requestedId) return;
      if (!Array.isArray(list)) return;
      const nextRuns = list as RunResult[];
      const hasNewRun = nextRuns.length > runs.length;
      setRuns((previous) => {
        if (nextRuns.length !== previous.length) return nextRuns;
        const changed = nextRuns.some((run, index) => run.id !== previous[index]?.id || run.ok !== previous[index]?.ok);
        return changed ? nextRuns : previous;
      });
      setActiveRun((previous) => {
        if (nextRuns.length === 0) return 0;
        if (hasNewRun) return nextRuns.length - 1;
        return previous >= nextRuns.length ? nextRuns.length - 1 : previous;
      });
      const hasPendingRun = nextRuns.some(isRunStillPending);
      if (hasPendingRun) setOptimizing(true);
      else if (optimizingRef.current) setOptimizing(false);
    } catch (error) {
      if (sessionIdRef.current !== requestedId) return;
      if (isSessionGoneError(error)) {
        invalidateRemovedSession(
          "This session was deleted or is no longer available. Your access token is still saved below - start a new session when you are ready.",
        );
      }
    }
  }, [invalidateRemovedSession, optimizingRef, runs, sessionId, sessionIdRef, setActiveRun, setOptimizing, setRuns, token]);

  useEffect(() => {
    if (!authed) return;
    const abortController = new AbortController();
    void syncSession(abortController.signal);
    return () => abortController.abort();
  }, [authed, syncSession]);

  useEffect(() => {
    if (!authed) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void syncMessages();
    }, MESSAGE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [authed, syncMessages]);

  useEffect(() => {
    if (!authed) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void syncRuns();
    }, RUN_POLL_MS);
    return () => window.clearInterval(timer);
  }, [authed, syncRuns]);

  useEffect(() => {
    if (!authed) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void syncSession();
    }, SESSION_POLL_MS);
    return () => window.clearInterval(timer);
  }, [authed, syncSession]);

  useEffect(() => {
    if (!authed) return;
    const pending =
      session?.processing?.brief_status === "pending" || session?.processing?.config_status === "pending";
    if (!pending) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void syncSession();
    }, PROCESSING_PENDING_SESSION_POLL_MS);
    return () => window.clearInterval(timer);
  }, [
    authed,
    session?.processing?.brief_status,
    session?.processing?.config_status,
    syncSession,
  ]);

  // Refresh assistant messages whose `meta.verifying` flag is still set.
  // The standard incremental message poll (`?after_id=`) won't see in-place
  // updates because the id is already known. We poll each verifying message
  // by id until the flag clears (or the message disappears).
  const verifyingMessageIds = useMemo(
    () => messages
      .filter((m) => m.role !== "user" && m.meta?.verifying === true && m.id >= 0)
      .map((m) => m.id),
    [messages],
  );
  useEffect(() => {
    if (!authed || !token || !sessionId) return;
    if (verifyingMessageIds.length === 0) return;
    const requestedSessionId = sessionId;
    const refresh = async () => {
      if (document.visibilityState !== "visible") return;
      await Promise.all(
        verifyingMessageIds.map(async (id) => {
          try {
            const updated = await apiFetch<Message>(
              `/sessions/${requestedSessionId}/messages/${id}`,
              token,
            );
            if (sessionIdRef.current !== requestedSessionId) return;
            setMessages((current) => mergeMessageUpdate(current, updated));
          } catch {
            // Swallow — the message may have been deleted or the session is gone;
            // the next poll cycle (or a session-gone error elsewhere) will handle it.
          }
        }),
      );
    };
    void refresh();
    const timer = window.setInterval(refresh, VERIFYING_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [authed, sessionId, sessionIdRef, setMessages, token, verifyingMessageIds]);

  useEffect(() => {
    if (!authed) {
      setRecentRows(readSessionHistory().map((entry) => ({ id: entry.id, history: entry })));
    }
  }, [authed, setRecentRows]);

  useEffect(() => {
    if (session?.status === "terminated") setEditMode("none");
  }, [session?.status, setEditMode]);

  useEffect(() => {
    if (showModelDialog && token && sessionId) void syncSession();
  }, [sessionId, showModelDialog, syncSession, token]);

  useEffect(() => {
    if (showModelDialog && !modelDialogWasOpenRef.current) {
      const model = session?.gemini_model?.trim();
      // Fall back to server's configured default (from .env) so the dialog
      // pre-selects the right model even when the session has no stored model.
      setModelName(model || defaultModel);
      const embedding = session?.embedding_model?.trim();
      setEmbeddingModel(embedding || defaultEmbeddingModel);
    }
    modelDialogWasOpenRef.current = showModelDialog;
  }, [
    defaultModel,
    defaultEmbeddingModel,
    modelDialogWasOpenRef,
    session,
    setModelName,
    setEmbeddingModel,
    showModelDialog,
  ]);

  useEffect(() => {
    if (!authed) return;
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        void syncSession();
        void syncMessages();
        void syncRuns();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [authed, syncMessages, syncRuns, syncSession]);

  useEffect(() => {
    if (!authed) return;
    const onStorage = (event: StorageEvent) => {
      if (event.key !== TUTORIAL_REFRESH_SIGNAL_KEY || !event.newValue) return;
      try {
        const payload = JSON.parse(event.newValue) as { session_id?: string };
        if (!payload?.session_id) return;
        if (payload.session_id !== sessionIdRef.current) return;
        void syncSession();
      } catch {
        // ignore malformed storage payloads
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [authed, sessionIdRef, syncSession]);

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
  }, [activeRun, runs, setScheduleText]);

  return {
    invalidateRemovedSession,
    syncSession,
    syncMessages,
    syncRuns,
    startEagerMessagePoll,
  };
}
