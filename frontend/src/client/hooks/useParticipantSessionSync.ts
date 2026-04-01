import { useCallback, useEffect, useRef, type MutableRefObject } from "react";

import { apiFetch, type RunResult, type Session } from "@shared/api";
import type { ProblemPanelHydration } from "../problemConfig/problemPanelHydration";
import { resolveProblemPanelFromServer } from "../problemConfig/problemPanelHydration";
import { type EditMode, type RecentSessionRow } from "../lib/participantTypes";
import { SESSION_KEY } from "../lib/sessionKeys";
import {
  coerceParticipantMessages,
  isAbortError,
  isOlderSessionSnapshot,
  isSessionGoneError,
} from "../lib/sessionGuards";
import { readSessionHistory, removeSessionHistoryEntry } from "../lib/sessionHistory";
import { mergeMessagesFromPoll } from "../chat/messageMerge";

const MESSAGE_POLL_MS = 4000;
const RUN_POLL_MS = 8000;
const SESSION_POLL_MS = 15000;
const EAGER_POLL_INTERVAL_MS = 2000;
const EAGER_POLL_DURATION_MS = 10000;

type UseParticipantSessionSyncArgs = {
  token: string;
  sessionId: string;
  authed: boolean;
  lastMsgId: number;
  activeRun: number;
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
  setLastMsgId: (value: number | ((prev: number) => number)) => void;
  setActiveRun: (value: number | ((prev: number) => number)) => void;
  setEditMode: (value: EditMode) => void;
  setError: (value: string | null) => void;
  setRecentRows: (value: RecentSessionRow[]) => void;
  setModelName: (value: string) => void;
};

export function useParticipantSessionSync({
  token,
  sessionId,
  authed,
  lastMsgId,
  activeRun,
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
  setLastMsgId,
  setActiveRun,
  setEditMode,
  setError,
  setRecentRows,
  setModelName,
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
        setMessages((current) => mergeMessagesFromPoll(current, nextMessages));
        setLastMsgId((previous) => Math.max(previous, maxIncoming));
      }
    } catch (error) {
      if (sessionIdRef.current !== requestedId) return;
      if (isSessionGoneError(error)) {
        invalidateRemovedSession(
          "This session was deleted or is no longer available. Your access token is still saved below - start a new session when you are ready.",
        );
      }
    }
  }, [invalidateRemovedSession, lastMsgId, sessionId, sessionIdRef, setLastMsgId, setMessages, token]);

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
    if (optimizingRef.current) return;
    const requestedId = sessionId;
    try {
      const list = await apiFetch<unknown>(`/sessions/${requestedId}/runs`, token);
      if (sessionIdRef.current !== requestedId) return;
      if (!Array.isArray(list)) return;
      const nextRuns = list as RunResult[];
      setRuns((previous) => {
        if (nextRuns.length !== previous.length) return nextRuns;
        const changed = nextRuns.some((run, index) => run.id !== previous[index]?.id || run.ok !== previous[index]?.ok);
        return changed ? nextRuns : previous;
      });
      setActiveRun((previous) => {
        if (nextRuns.length === 0) return 0;
        return previous >= nextRuns.length ? nextRuns.length - 1 : previous;
      });
    } catch (error) {
      if (sessionIdRef.current !== requestedId) return;
      if (isSessionGoneError(error)) {
        invalidateRemovedSession(
          "This session was deleted or is no longer available. Your access token is still saved below - start a new session when you are ready.",
        );
      }
    }
  }, [invalidateRemovedSession, optimizingRef, sessionId, sessionIdRef, setActiveRun, setRuns, token]);

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
      if (model) setModelName(model);
    }
    modelDialogWasOpenRef.current = showModelDialog;
  }, [modelDialogWasOpenRef, session, setModelName, showModelDialog]);

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
