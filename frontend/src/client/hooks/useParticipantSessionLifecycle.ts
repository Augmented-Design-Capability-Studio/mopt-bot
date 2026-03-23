import { useCallback, type MutableRefObject } from "react";

import {
  ApiError,
  apiFetch,
  sessionPanelToConfigText,
  type ProblemBrief,
  type RunResult,
  type Session,
} from "@shared/api";

import type { ProblemPanelHydration } from "../problemConfig/problemPanelHydration";
import type { RecentSessionRow } from "../lib/participantTypes";
import { SESSION_KEY, TOKEN_KEY } from "../lib/sessionKeys";
import { coerceParticipantMessages } from "../lib/sessionGuards";
import { readSessionHistory, removeSessionHistoryEntry, upsertSessionHistoryFromServer } from "../lib/sessionHistory";

type UseParticipantSessionLifecycleArgs = {
  token: string;
  participantNumber: string;
  session: Session | null;
  sessionIdRef: MutableRefObject<string>;
  problemPanelHydrationRef: MutableRefObject<ProblemPanelHydration>;
  setToken: (value: string) => void;
  setSessionId: (value: string) => void;
  setSession: (value: Session | null) => void;
  setMessages: (value: import("@shared/api").Message[]) => void;
  setRuns: (value: RunResult[]) => void;
  setLastMsgId: (value: number) => void;
  setChatInput: (value: string) => void;
  setConfigText: (value: string) => void;
  setProblemBrief: (value: ProblemBrief | null) => void;
  setScheduleText: (value: string) => void;
  setActiveRun: (value: number) => void;
  setEditMode: (value: import("../lib/participantTypes").EditMode) => void;
  setConfigEditSnapshot: (value: string) => void;
  setBusy: (value: boolean) => void;
  setError: (value: string | null) => void;
  setRecentRows: (value: RecentSessionRow[]) => void;
  setRecentBusy: (value: boolean) => void;
};

export function useParticipantSessionLifecycle({
  token,
  participantNumber,
  session,
  sessionIdRef,
  problemPanelHydrationRef,
  setToken,
  setSessionId,
  setSession,
  setMessages,
  setRuns,
  setLastMsgId,
  setChatInput,
  setConfigText,
  setProblemBrief,
  setScheduleText,
  setActiveRun,
  setEditMode,
  setConfigEditSnapshot,
  setBusy,
  setError,
  setRecentRows,
  setRecentBusy,
}: UseParticipantSessionLifecycleArgs) {
  const login = useCallback(() => {
    sessionStorage.setItem(TOKEN_KEY, token.trim());
    setToken(token.trim());
    setError(null);
  }, [setError, setToken, token]);

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
          const currentSession = await apiFetch<Session>(`/sessions/${entry.id}`, trimmed);
          upsertSessionHistoryFromServer(currentSession);
          next.push({ id: entry.id, session: currentSession, history: entry });
        } catch (error) {
          if (error instanceof ApiError && (error.status === 404 || error.status === 410)) {
            removeSessionHistoryEntry(entry.id);
          } else {
            next.push({
              id: entry.id,
              history: entry,
              error: error instanceof Error ? error.message : "Could not load",
            });
          }
        }
      }
      setRecentRows(next);
    } finally {
      setRecentBusy(false);
    }
  }, [setError, setRecentBusy, setRecentRows, token]);

  const resumePastSession = useCallback(async (resumeId: string) => {
    const trimmed = token.trim();
    if (!trimmed) {
      setError("Save your access token first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const nextSession = await apiFetch<Session>(`/sessions/${resumeId}`, trimmed);
      sessionIdRef.current = resumeId;
      setSessionId(resumeId);
      sessionStorage.setItem(TOKEN_KEY, trimmed);
      sessionStorage.setItem(SESSION_KEY, resumeId);
      setSession(nextSession);
      problemPanelHydrationRef.current = "follow";
      setConfigText(sessionPanelToConfigText(nextSession.panel_config));
      setProblemBrief(nextSession.problem_brief);
      setMessages([]);
      setLastMsgId(0);
      setRuns([]);
      setActiveRun(0);
      setScheduleText("");
      setEditMode("none");
      setConfigEditSnapshot("");
      setChatInput("");

      const rawMessages = await apiFetch<unknown>(`/sessions/${resumeId}/messages?after_id=0`, trimmed);
      const messages = coerceParticipantMessages(rawMessages);
      setMessages(messages);
      if (messages.length) setLastMsgId(messages[messages.length - 1]!.id);

      const rawRuns = await apiFetch<unknown>(`/sessions/${resumeId}/runs`, trimmed);
      const runList = Array.isArray(rawRuns) ? (rawRuns as RunResult[]) : [];
      setRuns(runList);
      setActiveRun(runList.length ? runList.length - 1 : 0);

      upsertSessionHistoryFromServer(nextSession);
    } catch (error) {
      if (error instanceof ApiError && (error.status === 404 || error.status === 410)) {
        removeSessionHistoryEntry(resumeId);
        setRecentRows(readSessionHistory().map((entry) => ({ id: entry.id, history: entry })));
        setError("That session no longer exists; removed from this browser list.");
      } else {
        setError(error instanceof Error ? error.message : "Could not open session");
      }
    } finally {
      setBusy(false);
    }
  }, [
    problemPanelHydrationRef,
    sessionIdRef,
    setActiveRun,
    setBusy,
    setChatInput,
    setConfigText,
    setEditMode,
    setError,
    setLastMsgId,
    setMessages,
    setProblemBrief,
    setRecentRows,
    setRuns,
    setScheduleText,
    setSession,
    setSessionId,
    token,
  ]);

  const startSession = useCallback(async () => {
    const trimmed = token.trim();
    if (!trimmed) {
      setError("Enter access token first.");
      return;
    }
    sessionIdRef.current = "";
    setBusy(true);
    setError(null);
    setEditMode("none");
    setConfigEditSnapshot("");
    setChatInput("");
    setConfigText("");
    setProblemBrief(null);
    setScheduleText("");
    try {
      const nextSession = await apiFetch<Session>("/sessions", trimmed, {
        method: "POST",
        body: JSON.stringify({
          participant_number: participantNumber.trim() || undefined,
        }),
      });
      sessionIdRef.current = nextSession.id;
      setSessionId(nextSession.id);
      sessionStorage.setItem(TOKEN_KEY, trimmed);
      sessionStorage.setItem(SESSION_KEY, nextSession.id);
      setSession(nextSession);
      setMessages([]);
      setLastMsgId(0);
      setRuns([]);
      setScheduleText("");
      setConfigText("");
      setProblemBrief(nextSession.problem_brief);
      problemPanelHydrationRef.current = "empty_until_server_panel";
      upsertSessionHistoryFromServer(nextSession);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not create session");
    } finally {
      setBusy(false);
    }
  }, [
    problemPanelHydrationRef,
    sessionIdRef,
    setBusy,
    setChatInput,
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
    token,
    participantNumber,
  ]);

  const leaveSession = useCallback(() => {
    if (session) upsertSessionHistoryFromServer(session);
    sessionStorage.removeItem(SESSION_KEY);
    setSessionId("");
    setSession(null);
    setMessages([]);
    setRuns([]);
    setConfigEditSnapshot("");
    setConfigText("");
    setProblemBrief(null);
    setScheduleText("");
    problemPanelHydrationRef.current = "follow";
    setError(null);
  }, [
    problemPanelHydrationRef,
    session,
    setConfigEditSnapshot,
    setConfigText,
    setError,
    setMessages,
    setProblemBrief,
    setRuns,
    setScheduleText,
    setSession,
    setSessionId,
  ]);

  const forgetRecentSession = useCallback((id: string) => {
    removeSessionHistoryEntry(id);
    setRecentRows(readSessionHistory().map((entry) => ({ id: entry.id, history: entry })));
  }, [setRecentRows]);

  return {
    login,
    refreshRecentSessionsList,
    resumePastSession,
    startSession,
    leaveSession,
    forgetRecentSession,
  };
}
