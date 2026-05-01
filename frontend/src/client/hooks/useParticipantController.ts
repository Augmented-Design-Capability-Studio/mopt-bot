import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";

const _removedChipsKey = (sid: string) => `mopt_removed_chips_${sid}`;
function _loadRemovedChips(sid: string): Set<string> {
  try {
    const raw = sessionStorage.getItem(_removedChipsKey(sid));
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
  } catch { return new Set(); }
}
function _saveRemovedChip(sid: string, name: string): void {
  try {
    const s = _loadRemovedChips(sid);
    s.add(name);
    sessionStorage.setItem(_removedChipsKey(sid), JSON.stringify([...s]));
  } catch { /* ignore */ }
}
function _clearRemovedChips(sid: string): void {
  try { sessionStorage.removeItem(_removedChipsKey(sid)); } catch { /* ignore */ }
}

import {
  createSessionSnapshotBookmark,
  fetchSnapshots,
  fetchTestProblemsMeta,
  type Message,
  type ProblemBrief,
  type RunResult,
  type Session,
  type SnapshotSummary,
  type TestProblemMeta,
} from "@shared/api";


import { type ProblemPanelHydration } from "../problemConfig/problemPanelHydration";
import {
  computeCanRunOptimization,
  intrinsicOptimizationReadyAgile,
} from "../lib/optimizationGate";

import { type EditMode, type RecentSessionRow } from "../lib/participantTypes";
import { cloneProblemBrief, isProblemBriefDirtyAfterClean } from "../problemDefinition/summary";
import { PARTICIPANT_NUMBER_KEY, SESSION_KEY, TOKEN_KEY } from "../lib/sessionKeys";
import { DEFAULT_PARTICIPANT_OPS_STATE } from "../lib/participantOps";
import { hasSimulatedUploadMessage, parseFilenamesFromSimulatedUploadMessage } from "../lib/simulatedUploadMessage";
import { useParticipantSessionActions } from "./useParticipantSessionActions";
import { useParticipantSessionLifecycle } from "./useParticipantSessionLifecycle";
import { useParticipantSessionSync } from "./useParticipantSessionSync";

export function useParticipantController() {
  const [savedToken, setSavedToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  const [pendingUrlSessionId, setPendingUrlSessionId] = useState(() => {
    if (typeof window === "undefined") return "";
    const raw = new URLSearchParams(window.location.search).get("session");
    return (raw ?? "").trim();
  });
  const [lastAutoResumeKey, setLastAutoResumeKey] = useState("");
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  const [participantNumber, setParticipantNumber] = useState(
    () => sessionStorage.getItem(PARTICIPANT_NUMBER_KEY) ?? "",
  );
  const [sessionId, setSessionId] = useState(() => sessionStorage.getItem(SESSION_KEY) ?? "");
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [runs, setRuns] = useState<RunResult[]>([]);
  const [candidateRunIds, setCandidateRunIds] = useState<number[]>([]);
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
  const [participantOps, setParticipantOps] = useState(DEFAULT_PARTICIPANT_OPS_STATE);
  const [optimizing, setOptimizing] = useState(false);
  const optimizingRef = useRef(false);
  optimizingRef.current = optimizing;
  const [error, setError] = useState<string | null>(null);
  const [showModelDialog, setShowModelDialog] = useState(false);
  const [modelKey, setModelKey] = useState("");

  const [modelName, setModelName] = useState("");
  const [aiPending, setAiPending] = useState(false);
  const [recentRows, setRecentRows] = useState<RecentSessionRow[]>([]);
  const [recentBusy, setRecentBusy] = useState(false);
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [snapshotsLoading, setSnapshotsLoading] = useState(false);
  const [definitionEditBaseline, setDefinitionEditBaseline] = useState<ProblemBrief | null>(null);

  const fileRef = useRef<HTMLInputElement>(null);
  const [simulatedUploadChips, setSimulatedUploadChips] = useState<string[]>([]);
  const processedUploadMessageIdsRef = useRef<Set<number>>(new Set());
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

  const authed = useMemo(() => Boolean(savedToken && sessionId), [savedToken, sessionId]);

  const [testProblemsMeta, setTestProblemsMeta] = useState<TestProblemMeta[]>([]);

  useEffect(() => {
    if (!authed) {
      setTestProblemsMeta([]);
      return;
    }
    let cancelled = false;
    void fetchTestProblemsMeta()
      .then((list) => {
        if (!cancelled) setTestProblemsMeta(list);
      })
      .catch(() => {
        if (!cancelled) setTestProblemsMeta([]);
      });
    return () => {
      cancelled = true;
    };
  }, [authed]);

  const testProblemMeta = useMemo(() => {
    const id = (session?.test_problem_id ?? "vrptw").trim().toLowerCase();
    return testProblemsMeta.find((m) => m.id === id) ?? null;
  }, [session?.test_problem_id, testProblemsMeta]);

  const sync = useParticipantSessionSync({
    token: savedToken,
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
    setOptimizing,
    setLastMsgId,
    setActiveRun,
    setEditMode,
    setError,
    setRecentRows,
    setModelName,
  });

  const lifecycle = useParticipantSessionLifecycle({
    token: savedToken,
    tokenInput: token,
    participantNumber,
    session,
    sessionIdRef,
    problemPanelHydrationRef,
    setToken: setSavedToken,
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

  useEffect(() => {
    if (!pendingUrlSessionId) return;
    if (!savedToken.trim()) return;
    if (busy) return;
    if (sessionId === pendingUrlSessionId) {
      setPendingUrlSessionId("");
      setLastAutoResumeKey("");
      return;
    }
    const key = `${pendingUrlSessionId}::${savedToken.trim()}`;
    if (lastAutoResumeKey === key) return;
    setLastAutoResumeKey(key);
    void (async () => {
      const ok = await lifecycle.resumePastSession(pendingUrlSessionId);
      if (ok) {
        setPendingUrlSessionId("");
        setLastAutoResumeKey("");
      }
    })();
  }, [busy, lastAutoResumeKey, lifecycle, pendingUrlSessionId, savedToken, sessionId]);

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
    setParticipantOps(DEFAULT_PARTICIPANT_OPS_STATE);
    setSimulatedUploadChips([]);
    setCandidateRunIds([]);
    processedUploadMessageIdsRef.current = new Set();
    if (sessionId) _clearRemovedChips(sessionId);
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    const removed = _loadRemovedChips(sessionId);
    for (const m of messages) {
      if (m.role !== "user" || processedUploadMessageIdsRef.current.has(m.id)) continue;
      const names = parseFilenamesFromSimulatedUploadMessage(m.content);
      if (!names?.length) continue;
      processedUploadMessageIdsRef.current.add(m.id);
      setSimulatedUploadChips((prev) => {
        const next = [...prev];
        for (const n of names) {
          if (!next.includes(n) && !removed.has(n)) next.push(n);
        }
        return next;
      });
    }
  }, [messages, sessionId]);

  useEffect(() => {
    const validIds = new Set(runs.map((run) => run.id));
    setCandidateRunIds((prev) => prev.filter((id) => validIds.has(id)));
  }, [runs]);

  const removeSimulatedUploadChip = useCallback((fileName: string) => {
    if (sessionId) _saveRemovedChip(sessionId, fileName);
    setSimulatedUploadChips((prev) => prev.filter((n) => n !== fileName));
  }, [sessionId]);

  const hasUploadedData = useMemo(
    () => messages.some((m) => m.role === "user" && hasSimulatedUploadMessage(m.content)),
    [messages],
  );

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
    if (!savedToken || !sessionId || session?.status !== "active") return;
    setSnapshotsLoading(true);
    try {
      const list = await fetchSnapshots(sessionId, savedToken);
      setSnapshots(list);
    } catch {
      setSnapshots([]);
    } finally {
      setSnapshotsLoading(false);
    }
  }, [savedToken, sessionId, session?.status]);

  useEffect(() => {
    if (savedToken && sessionId && session?.status === "active") {
      void loadSnapshots();
    } else {
      setSnapshots([]);
    }
  }, [savedToken, sessionId, session?.status, loadSnapshots]);

  const agileAutorunStorageKey = sessionId ? `mopt-agile-autorun-dispatched:${sessionId}` : "";

  const actions = useParticipantSessionActions({
    token: savedToken,
    hasUploadedData,
    sessionId,
    session,
    chatInputRef,
    invokeModel,
    configText,
    problemBrief,
    problemMeta: testProblemMeta,
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
    setParticipantOps,
    runs,
    activeRun,
    candidateRunIds,
    syncMessages: sync.syncMessages,
    syncSession: sync.syncSession,
    startEagerMessagePoll: sync.startEagerMessagePoll,
    refetchSnapshots: loadSnapshots,
  });

  useEffect(() => {
    if (session?.workflow_mode !== "agile" || session.status !== "active") return;
    if (!agileAutorunStorageKey) return;
    if (busy || optimizing || aiPending) return;
    const processing = session.processing;
    if (!processing) return;
    if (processing.brief_status === "pending" || processing.config_status === "pending") return;
    // Auto-run should only use settled Definition/config state.
    if (processing.brief_status === "failed" || processing.config_status === "failed") return;
    if (editMode !== "none") return;
    if (!testProblemMeta) return;
    if (!intrinsicOptimizationReadyAgile(
      configText,
      testProblemMeta.weight_display_keys,
      testProblemMeta.worker_preference_key ?? null,
    )) return;
    if (!computeCanRunOptimization(session, configText, problemBrief, hasUploadedData, testProblemMeta)) return;
    const hasCommittedOptimize = runs.some((r) => !r.clientPending && r.run_type === "optimize");
    if (hasCommittedOptimize) return;
    try {
      if (typeof sessionStorage !== "undefined" && sessionStorage.getItem(agileAutorunStorageKey)) return;
    } catch {
      /* private mode */
    }
    void actions.runOptimize({ agileAutorunStorageKey });
  }, [
    actions.runOptimize,
    agileAutorunStorageKey,
    busy,
    aiPending,
    configText,
    editMode,
    optimizing,
    problemBrief,
    hasUploadedData,
    runs,
    session,
    testProblemMeta,
  ]);

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
    if (!savedToken || !sessionId) return;
    try {
      await createSessionSnapshotBookmark(sessionId, savedToken);
      await loadSnapshots();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Snapshot failed");
    }
  }, [loadSnapshots, savedToken, sessionId, setError]);

  const startSession = useCallback(async () => {
    await lifecycle.startSession(token);
  }, [lifecycle, token]);

  const resumePastSession = useCallback(async (id: string) => {
    await lifecycle.resumePastSession(id, token);
  }, [lifecycle, token]);

  const loadConfigFromLastRun = useCallback(() => {
    const latest = runs[runs.length - 1];
    const problem = latest?.request?.problem;
    if (problem == null || typeof problem !== "object") return;
    const panel = { problem };
    const newConfig = JSON.stringify(panel, null, 2);
    setConfigText(newConfig);
    void actions.saveConfig(newConfig);
  }, [runs, setConfigText, actions.saveConfig]);

  const loadConfigFromRun = useCallback((run: RunResult) => {
    const problem = run?.request?.problem;
    if (problem == null || typeof problem !== "object") return;
    const panel = { problem };
    const newConfig = JSON.stringify(panel, null, 2);
    setConfigText(newConfig);
    void actions.saveConfig(newConfig);
  }, [actions.saveConfig, setConfigText]);

  const toggleCandidateRun = useCallback((runId: number, checked: boolean) => {
    setCandidateRunIds((prev) => {
      if (checked) {
        if (prev.includes(runId)) return prev;
        return [...prev, runId];
      }
      return prev.filter((id) => id !== runId);
    });
  }, []);

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
  const chatBusy = participantOps.sendingChat;

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
    hasUploadedData,
    scheduleText,
    editMode,
    busy,
    chatBusy,
    syncingProblemConfig,
    participantOps,
    optimizing,
    error,
    showModelDialog,
    modelKey,
    modelName,
    aiPending,
    recentRows,
    recentBusy,
    pendingUrlSessionId,
    authed,
    testProblemMeta,
    fileRef,
    simulatedUploadChips,
    onRemoveSimulatedUploadChip: removeSimulatedUploadChip,
    setToken: (value: string) => {
      setToken(value);
      if (error) setError(null);
    },
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
    resumePastSession,
    startSession,
    sendChat: actions.sendChat,
    requestDefinitionCleanup: actions.requestDefinitionCleanup,
    requestOpenQuestionCleanup: actions.requestOpenQuestionCleanup,
    simulateUpload: actions.simulateUpload,
    saveConfig: actions.saveConfig,
    saveProblemBrief: actions.saveProblemBrief,
    syncProblemConfig: actions.syncProblemConfig,
    runOptimize: actions.runOptimize,
    cancelOptimize: actions.cancelOptimize,
    runEvaluateEdited: actions.runEvaluateEdited,
    revertEditedRun: actions.revertEditedRun,
    explainRun: actions.explainRun,
    saveModelSettings: actions.saveModelSettings,
    leaveSession: lifecycle.leaveSession,
    forgetRecentSession: lifecycle.forgetRecentSession,
    closeModelDialog: actions.closeModelDialog,
    setParticipantTutorialState: actions.setParticipantTutorialState,
    enterConfigEdit,
    cancelConfigEdit,
    ensureDefinitionEditing,
    cancelDefinitionEdit,
    saveDefinitionEdit,
    isDefinitionDirty,
    isConfigDirty,
    bookmarkSnapshot,
    loadConfigFromLastRun,
    loadConfigFromRun,
    candidateRunIds,
    toggleCandidateRun,
    restoreFromSnapshot,
    loadSnapshots,
    snapshots,
    snapshotsLoading,
    canLoadFromLastRun,
    canLoadFromSnapshot,
  };
}
