import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";

import {
  createSessionSnapshotBookmark,
  fetchSnapshots,
  type Message,
  type ProblemBrief,
  type RunResult,
  type Session,
  type SnapshotSummary,
} from "@shared/api";
import { DEFAULT_SUGGESTED_GEMINI_MODEL } from "@shared/geminiModelSuggestions";

import { type ProblemPanelHydration } from "../problemConfig/problemPanelHydration";
import { type EditMode, type RecentSessionRow } from "../lib/participantTypes";
import { cloneProblemBrief, isProblemBriefDirtyAfterClean } from "../problemDefinition/summary";
import { PARTICIPANT_NUMBER_KEY, SESSION_KEY, TOKEN_KEY } from "../lib/sessionKeys";
import { useParticipantSessionActions } from "./useParticipantSessionActions";
import { useParticipantSessionLifecycle } from "./useParticipantSessionLifecycle";
import { useParticipantSessionSync } from "./useParticipantSessionSync";

export function useParticipantController() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  const [participantNumber, setParticipantNumber] = useState(
    () => sessionStorage.getItem(PARTICIPANT_NUMBER_KEY) ?? "",
  );
  const [sessionId, setSessionId] = useState(() => sessionStorage.getItem(SESSION_KEY) ?? "");
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [runs, setRuns] = useState<RunResult[]>([]);
  const [lastMsgId, setLastMsgId] = useState(0);
  const [chatInput, setChatInput] = useState("");
  const [invokeModel, setInvokeModel] = useState(true);
  const [configText, setConfigText] = useState("");
  const [problemBrief, setProblemBrief] = useState<ProblemBrief | null>(null);
  const [scheduleText, setScheduleText] = useState("");
  const [activeRun, setActiveRun] = useState(0);
  const [editMode, setEditMode] = useState<EditMode>("none");
  const [configEditSnapshot, setConfigEditSnapshot] = useState("");
  const [busy, setBusy] = useState(false);
  const [syncingProblemConfig, setSyncingProblemConfig] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const optimizingRef = useRef(false);
  optimizingRef.current = optimizing;
  const [error, setError] = useState<string | null>(null);
  const [showModelDialog, setShowModelDialog] = useState(false);
  const [modelKey, setModelKey] = useState("");
  const [modelName, setModelName] = useState(DEFAULT_SUGGESTED_GEMINI_MODEL);
  const [aiPending, setAiPending] = useState(false);
  const [recentRows, setRecentRows] = useState<RecentSessionRow[]>([]);
  const [recentBusy, setRecentBusy] = useState(false);
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [snapshotsLoading, setSnapshotsLoading] = useState(false);
  const [definitionEditBaseline, setDefinitionEditBaseline] = useState<ProblemBrief | null>(null);

  const fileRef = useRef<HTMLInputElement>(null);
  const modelDialogWasOpenRef = useRef(false);
  const sessionIdRef = useRef(sessionId);
  const problemPanelHydrationRef = useRef<ProblemPanelHydration>("follow");
  const sessionRef = useRef<Session | null>(null);
  sessionRef.current = session;
  const editModeRef = useRef<EditMode>(editMode);
  editModeRef.current = editMode;
  const chatInputRef = useRef(chatInput);
  chatInputRef.current = chatInput;
  const setProblemBriefState = useCallback(
    (value: ProblemBrief | null | ((prev: ProblemBrief | null) => ProblemBrief | null)) => {
      setProblemBrief((previous) => {
        const next = typeof value === "function" ? value(previous) : value;
        return next ? cloneProblemBrief(next) : next;
      });
    },
    [],
  );

  const authed = useMemo(() => Boolean(token && sessionId), [token, sessionId]);

  const sync = useParticipantSessionSync({
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
    setProblemBrief: setProblemBriefState,
    setScheduleText,
    setLastMsgId,
    setActiveRun,
    setEditMode,
    setError,
    setRecentRows,
    setModelName,
  });

  const lifecycle = useParticipantSessionLifecycle({
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
    setProblemBrief: setProblemBriefState,
    setScheduleText,
    setActiveRun,
    setEditMode,
    setConfigEditSnapshot,
    setBusy,
    setError,
    setRecentRows,
    setRecentBusy,
    setParticipantNumber,
  });

  const enterConfigEdit = useCallback(() => {
    flushSync(() => {
      setConfigEditSnapshot(configText);
      setEditMode("config");
    });
  }, [configText]);

  const cancelConfigEdit = useCallback(() => {
    setConfigText(configEditSnapshot);
    setEditMode("none");
  }, [configEditSnapshot, setConfigText]);

  useEffect(() => {
    setDefinitionEditBaseline(null);
  }, [sessionId]);

  useEffect(() => {
    const p = session?.participant_number?.trim();
    if (!p) return;
    setParticipantNumber((prev) => {
      if (prev === p) return prev;
      sessionStorage.setItem(PARTICIPANT_NUMBER_KEY, p);
      return p;
    });
  }, [session?.participant_number]);

  const loadSnapshots = useCallback(async () => {
    if (!token || !sessionId || session?.status !== "active") return;
    setSnapshotsLoading(true);
    try {
      const list = await fetchSnapshots(sessionId, token);
      setSnapshots(list);
    } catch {
      setSnapshots([]);
    } finally {
      setSnapshotsLoading(false);
    }
  }, [token, sessionId, session?.status]);

  useEffect(() => {
    if (token && sessionId && session?.status === "active") {
      void loadSnapshots();
    } else {
      setSnapshots([]);
    }
  }, [token, sessionId, session?.status, loadSnapshots]);

  const actions = useParticipantSessionActions({
    token,
    sessionId,
    session,
    chatInputRef,
    invokeModel,
    configText,
    problemBrief,
    scheduleText,
    modelKey,
    modelName,
    problemPanelHydrationRef,
    setSession,
    setMessages,
    setRuns,
    setLastMsgId,
    setChatInput,
    setConfigText,
    setProblemBrief: setProblemBriefState,
    setActiveRun,
    setEditMode,
    setBusy,
    setSyncingProblemConfig,
    setOptimizing,
    optimizingRef,
    setError,
    setShowModelDialog,
    setModelKey,
    setAiPending,
    syncMessages: sync.syncMessages,
    syncSession: sync.syncSession,
    startEagerMessagePoll: sync.startEagerMessagePoll,
    refetchSnapshots: loadSnapshots,
  });

  const ensureDefinitionEditing = useCallback(() => {
    if (editMode !== "none") return;
    if (!problemBrief) return;
    flushSync(() => {
      setDefinitionEditBaseline(cloneProblemBrief(problemBrief));
      setEditMode("definition");
    });
  }, [editMode, problemBrief, setEditMode]);

  const cancelDefinitionEdit = useCallback(() => {
    if (definitionEditBaseline) {
      setProblemBriefState(cloneProblemBrief(definitionEditBaseline));
    }
    setDefinitionEditBaseline(null);
    setEditMode("none");
  }, [definitionEditBaseline, setProblemBriefState, setEditMode]);

  const saveDefinitionEdit = useCallback(async () => {
    const ok = await actions.saveProblemBrief();
    if (ok) setDefinitionEditBaseline(null);
  }, [actions.saveProblemBrief]);

  const isDefinitionDirty = useMemo(
    () =>
      editMode === "definition" &&
      definitionEditBaseline != null &&
      problemBrief != null &&
      isProblemBriefDirtyAfterClean(definitionEditBaseline, problemBrief),
    [definitionEditBaseline, editMode, problemBrief],
  );

  const isConfigDirty = useMemo(
    () => editMode === "config" && configText !== configEditSnapshot,
    [configEditSnapshot, configText, editMode],
  );

  const bookmarkSnapshot = useCallback(async () => {
    if (!token || !sessionId) return;
    try {
      await createSessionSnapshotBookmark(sessionId, token);
      await loadSnapshots();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Snapshot failed");
    }
  }, [loadSnapshots, sessionId, setError, token]);

  const loadConfigFromLastRun = useCallback(() => {
    const latest = runs[runs.length - 1];
    const problem = latest?.request?.problem;
    if (problem == null || typeof problem !== "object") return;
    const panel = { problem };
    const newConfig = JSON.stringify(panel, null, 2);
    setConfigText(newConfig);
    void actions.saveConfig(newConfig);
  }, [runs, setConfigText, actions.saveConfig]);

  const restoreFromSnapshot = useCallback(
    (snap: SnapshotSummary, source: "definition" | "config") => {
      setDefinitionEditBaseline(null);
      void actions.restoreFromSnapshot(snap, source);
      void loadSnapshots();
    },
    [actions.restoreFromSnapshot, loadSnapshots],
  );

  const canLoadFromLastRun = runs.length > 0 && runs[runs.length - 1]?.request?.problem != null;
  const canLoadFromSnapshot = snapshots.length > 0;

  return {
    token,
    participantNumber,
    sessionId,
    session,
    messages,
    runs,
    currentRun: runs[activeRun],
    activeRun,
    chatInput,
    invokeModel,
    configText,
    problemBrief,
    scheduleText,
    editMode,
    busy,
    syncingProblemConfig,
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
    setParticipantNumber,
    setActiveRun,
    setChatInput,
    setInvokeModel,
    setConfigText,
    setProblemBrief: setProblemBriefState,
    setScheduleText,
    setEditMode,
    setShowModelDialog,
    setModelKey,
    setModelName,
    login: lifecycle.login,
    refreshRecentSessionsList: lifecycle.refreshRecentSessionsList,
    resumePastSession: lifecycle.resumePastSession,
    startSession: lifecycle.startSession,
    sendChat: actions.sendChat,
    simulateUpload: actions.simulateUpload,
    saveConfig: actions.saveConfig,
    saveProblemBrief: actions.saveProblemBrief,
    syncProblemConfig: actions.syncProblemConfig,
    runOptimize: actions.runOptimize,
    cancelOptimize: actions.cancelOptimize,
    runEvaluateEdited: actions.runEvaluateEdited,
    saveModelSettings: actions.saveModelSettings,
    leaveSession: lifecycle.leaveSession,
    forgetRecentSession: lifecycle.forgetRecentSession,
    closeModelDialog: actions.closeModelDialog,
    enterConfigEdit,
    cancelConfigEdit,
    ensureDefinitionEditing,
    cancelDefinitionEdit,
    saveDefinitionEdit,
    isDefinitionDirty,
    isConfigDirty,
    bookmarkSnapshot,
    loadConfigFromLastRun,
    restoreFromSnapshot,
    loadSnapshots,
    snapshots,
    snapshotsLoading,
    canLoadFromLastRun,
    canLoadFromSnapshot,
  };
}
