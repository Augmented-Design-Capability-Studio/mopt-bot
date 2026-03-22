import { useCallback, useMemo, useRef, useState } from "react";

import { type Message, type ProblemBrief, type RunResult, type Session } from "@shared/api";
import { DEFAULT_SUGGESTED_GEMINI_MODEL } from "@shared/geminiModelSuggestions";

import { type ProblemPanelHydration } from "../problemConfig/problemPanelHydration";
import { type EditMode, type RecentSessionRow } from "../lib/participantTypes";
import { cloneProblemBrief } from "../problemDefinition/summary";
import { SESSION_KEY, TOKEN_KEY } from "../lib/sessionKeys";
import { useParticipantSessionActions } from "./useParticipantSessionActions";
import { useParticipantSessionLifecycle } from "./useParticipantSessionLifecycle";
import { useParticipantSessionSync } from "./useParticipantSessionSync";

export function useParticipantController() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  const [participantNumber, setParticipantNumber] = useState("");
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
  const problemPanelHydrationRef = useRef<ProblemPanelHydration>("follow");
  const sessionRef = useRef<Session | null>(null);
  sessionRef.current = session;
  const editModeRef = useRef<EditMode>(editMode);
  editModeRef.current = editMode;
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
    setBusy,
    setError,
    setRecentRows,
    setRecentBusy,
  });

  const actions = useParticipantSessionActions({
    token,
    sessionId,
    session,
    chatInput,
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
    setOptimizing,
    setError,
    setShowModelDialog,
    setModelKey,
    setAiPending,
    syncMessages: sync.syncMessages,
    syncSession: sync.syncSession,
  });

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
    runEvaluateEdited: actions.runEvaluateEdited,
    saveModelSettings: actions.saveModelSettings,
    leaveSession: lifecycle.leaveSession,
    forgetRecentSession: lifecycle.forgetRecentSession,
    closeModelDialog: actions.closeModelDialog,
  };
}
