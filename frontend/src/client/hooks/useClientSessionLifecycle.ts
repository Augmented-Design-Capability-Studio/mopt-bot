import { useCallback, type MutableRefObject } from "react";

import {
  ApiError,
  apiFetch,
  fetchSessionsForParticipant,
  sessionPanelToConfigText,
  type ProblemBrief,
  type RunResult,
  type Session,
} from "@shared/api";

import type { ProblemPanelHydration } from "../problemConfig/problemPanelHydration";
import type { RecentSessionRow } from "../lib/clientTypes";
import { PARTICIPANT_NUMBER_KEY, SESSION_KEY, TOKEN_KEY } from "../lib/sessionKeys";
import { coerceParticipantMessages } from "../lib/sessionGuards";
import type { ClientSessionHistoryEntry } from "../lib/sessionHistory";
import { readSessionHistory, removeSessionHistoryEntry, upsertSessionHistoryFromServer } from "../lib/sessionHistory";

type UseParticipantSessionLifecycleArgs = {
  token: string;
  tokenInput: string;
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
  setEditMode: (value: import("../lib/clientTypes").EditMode) => void;
  setConfigEditSnapshot: (value: string) => void;
  setBusy: (value: boolean) => void;
  setError: (value: string | null) => void;
  setRecentRows: (value: RecentSessionRow[]) => void;
  setRecentBusy: (value: boolean) => void;
  setParticipantNumber: (value: string) => void;
};

export function useClientSessionLifecycle({
  token,
  tokenInput,
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
  setParticipantNumber,
}: UseParticipantSessionLifecycleArgs) {
  const login = useCallback(() => {
    const trimmed = tokenInput.trim();
    sessionStorage.setItem(TOKEN_KEY, trimmed);
    setToken(trimmed);
    const pn = participantNumber.trim();
    if (pn) {
      sessionStorage.setItem(PARTICIPANT_NUMBER_KEY, pn);
    }
    setError(null);
  }, [participantNumber, setError, setToken, tokenInput]);

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
      const idToRow = new Map<string, RecentSessionRow>();
      for (const entry of entries) {
        try {
          const currentSession = await apiFetch<Session>(`/sessions/${entry.id}`, trimmed);
          upsertSessionHistoryFromServer(currentSession);
          idToRow.set(entry.id, { id: entry.id, session: currentSession, history: entry });
        } catch (error) {
          if (error instanceof ApiError && (error.status === 404 || error.status === 410)) {
            removeSessionHistoryEntry(entry.id);
          } else {
            idToRow.set(entry.id, {
              id: entry.id,
              history: entry,
              error: error instanceof Error ? error.message : "Could not load",
            });
          }
        }
      }
      const pn = participantNumber.trim();
      if (pn) {
        const serverSessions = await fetchSessionsForParticipant(pn, trimmed);
        for (const s of serverSessions) {
          if (!idToRow.has(s.id)) {
            upsertSessionHistoryFromServer(s);
            const entry: ClientSessionHistoryEntry = {
              id: s.id,
              created_at: s.created_at,
              updated_at: s.updated_at,
              status: s.status,
              workflow_mode: s.workflow_mode,
              participant_number: s.participant_number,
            };
            idToRow.set(s.id, { id: s.id, session: s, history: entry });
          }
        }
      }
      const next = Array.from(idToRow.values()).sort((a, b) => {
        const aAt = a.session?.updated_at ?? a.history?.updated_at ?? "";
        const bAt = b.session?.updated_at ?? b.history?.updated_at ?? "";
        return bAt.localeCompare(aAt);
      });
      setRecentRows(next);
    } finally {
      setRecentBusy(false);
    }
  }, [participantNumber, setError, setRecentBusy, setRecentRows, token]);

  const resumePastSession = useCallback(async (resumeId: string, tokenOverride?: string): Promise<boolean> => {
    const trimmed = (tokenOverride ?? token).trim();
    if (!trimmed) {
      setError("Save your access token first.");
      return false;
    }
    setBusy(true);
    setError(null);
    try {
      const nextSession = await apiFetch<Session>(`/sessions/${resumeId}`, trimmed);
      sessionIdRef.current = resumeId;
      setSessionId(resumeId);
      setToken(trimmed);
      sessionStorage.setItem(TOKEN_KEY, trimmed);
      sessionStorage.setItem(SESSION_KEY, resumeId);
      setSession(nextSession);
      const resumedPn = (nextSession.participant_number ?? "").trim();
      if (resumedPn) {
        sessionStorage.setItem(PARTICIPANT_NUMBER_KEY, resumedPn);
        setParticipantNumber(resumedPn);
      }
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
      return true;
    } catch (error) {
      if (error instanceof ApiError && (error.status === 404 || error.status === 410)) {
        removeSessionHistoryEntry(resumeId);
        setRecentRows(readSessionHistory().map((entry) => ({ id: entry.id, history: entry })));
        setError("That session no longer exists; removed from this browser list.");
      } else {
        setError(error instanceof Error ? error.message : "Could not open session");
      }
      return false;
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
    setToken,
    token,
    setParticipantNumber,
  ]);

  const startSession = useCallback(async (tokenOverride?: string) => {
    const trimmed = (tokenOverride ?? token).trim();
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
      setToken(trimmed);
      sessionStorage.setItem(TOKEN_KEY, trimmed);
      sessionStorage.setItem(SESSION_KEY, nextSession.id);
      setSession(nextSession);
      const createdPn = (nextSession.participant_number ?? "").trim() || participantNumber.trim();
      if (createdPn) {
        sessionStorage.setItem(PARTICIPANT_NUMBER_KEY, createdPn);
        setParticipantNumber(createdPn);
      }
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
    setToken,
    token,
    participantNumber,
    setParticipantNumber,
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
