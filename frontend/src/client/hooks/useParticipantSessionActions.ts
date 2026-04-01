import { useCallback, useRef, type MutableRefObject } from "react";

import {
  apiFetch,
  displayRunNumber,
  normalizePostMessagesResponse,
  sessionPanelToConfigText,
  type Message,
  type ProblemBrief,
  type ProblemBriefQuestion,
  type RunResult,
  type Session,
  type SnapshotSummary,
} from "@shared/api";

import { mergeMessagesFromPost } from "../chat/messageMerge";
import { configChangeSummary } from "../problemConfig/configSummary";
import { DEFINITION_NEW_ROW_PLACEHOLDER } from "../problemDefinition/constants";
import { cloneProblemBrief, problemBriefChangeSummary } from "../problemDefinition/summary";
import type { ProblemPanelHydration } from "../problemConfig/problemPanelHydration";
import { parseRoutesForSolver } from "../results/schedule";

type UseParticipantSessionActionsArgs = {
  token: string;
  participantNumber?: string;
  sessionId: string;
  session: Session | null;
  chatInputRef: MutableRefObject<string>;
  invokeModel: boolean;
  configText: string;
  problemBrief: ProblemBrief | null;
  scheduleText: string;
  modelKey: string;
  modelName: string;
  problemPanelHydrationRef: MutableRefObject<ProblemPanelHydration>;
  setSession: (value: Session | null | ((prev: Session | null) => Session | null)) => void;
  setMessages: (value: Message[] | ((prev: Message[]) => Message[])) => void;
  setRuns: (value: RunResult[] | ((prev: RunResult[]) => RunResult[])) => void;
  setLastMsgId: (value: number | ((prev: number) => number)) => void;
  setChatInput: (value: string) => void;
  setConfigText: (value: string) => void;
  setProblemBrief: (value: ProblemBrief | null | ((prev: ProblemBrief | null) => ProblemBrief | null)) => void;
  setActiveRun: (value: number | ((prev: number) => number)) => void;
  setEditMode: (value: import("../lib/participantTypes").EditMode) => void;
  setBusy: (value: boolean) => void;
  setSyncingProblemConfig: (value: boolean) => void;
  setOptimizing: (value: boolean) => void;
  setError: (value: string | null) => void;
  setShowModelDialog: (value: boolean) => void;
  setModelKey: (value: string) => void;
  setAiPending: (value: boolean) => void;
  syncMessages: () => Promise<void>;
  syncSession: () => Promise<void>;
  startEagerMessagePoll: () => void;
  refetchSnapshots?: () => void | Promise<void>;
};

type SaveProblemBriefOptions = {
  chatNote?: string;
};

type PostContextMessageOptions = {
  skipHiddenBriefUpdate?: boolean;
};

export function useParticipantSessionActions({
  token,
  participantNumber: _participantNumber,
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
  setProblemBrief,
  setActiveRun,
  setEditMode,
  setBusy,
  setSyncingProblemConfig,
  setOptimizing,
  setError,
  setShowModelDialog,
  setModelKey,
  setAiPending,
  syncMessages,
  syncSession,
  startEagerMessagePoll,
  refetchSnapshots,
}: UseParticipantSessionActionsArgs) {
  const savingProblemBriefRef = useRef(false);
  const applyPanelConfigFromResponse = useCallback(
    (panelConfig: Session["panel_config"] | null | undefined) => {
      if (panelConfig == null) return;
      problemPanelHydrationRef.current = "follow";
      setConfigText(sessionPanelToConfigText(panelConfig));
      setSession((previous) => (previous ? { ...previous, panel_config: panelConfig } : previous));
    },
    [problemPanelHydrationRef, setConfigText, setSession],
  );

  const applyProblemBriefFromResponse = useCallback(
    (nextProblemBrief: ProblemBrief | null | undefined) => {
      if (nextProblemBrief == null) return;
      setProblemBrief(cloneProblemBrief(nextProblemBrief));
      setSession((previous) => (previous ? { ...previous, problem_brief: cloneProblemBrief(nextProblemBrief) } : previous));
    },
    [setProblemBrief, setSession],
  );

  const applyProcessingFromResponse = useCallback(
    (processing: Session["processing"] | null | undefined) => {
      if (processing == null) return;
      setSession((previous) => (previous ? { ...previous, processing } : previous));
    },
    [setSession],
  );

  const postContextMessage = useCallback(
    async (content: string, withModel: boolean, messageOptions?: PostContextMessageOptions) => {
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
      setMessages((current) => [...current, optimistic]);
      setAiPending(withModel);
      try {
        const raw = await apiFetch<unknown>(`/sessions/${sessionId}/messages`, token, {
          method: "POST",
          body: JSON.stringify({
            content,
            invoke_model: withModel,
            skip_hidden_brief_update: messageOptions?.skipHiddenBriefUpdate ?? false,
          }),
        });
        const response = normalizePostMessagesResponse(raw);
        const outgoing = response.messages;
        setMessages((current) => mergeMessagesFromPost(current, outgoing));
        if (outgoing.length) setLastMsgId(outgoing[outgoing.length - 1]!.id);
        applyPanelConfigFromResponse(response.panel_config);
        applyProblemBriefFromResponse(response.problem_brief);
        applyProcessingFromResponse(response.processing);
        if (withModel) startEagerMessagePoll();
      } catch {
        setMessages((current) => current.filter((message) => message.id !== tempId));
      } finally {
        setAiPending(false);
      }
    },
    [
      applyProcessingFromResponse,
      applyPanelConfigFromResponse,
      applyProblemBriefFromResponse,
      session?.status,
      sessionId,
      setAiPending,
      setLastMsgId,
      setMessages,
      startEagerMessagePoll,
      token,
    ],
  );

  const sendChat = useCallback(async () => {
    const text = (chatInputRef.current ?? "").trim();
    if (!text || !token || !sessionId || session?.status === "terminated") return;
    const tempUserId = -Date.now();
    const optimisticUser: Message = {
      id: tempUserId,
      created_at: new Date().toISOString(),
      role: "user",
      content: text,
      visible_to_participant: true,
      kind: "chat",
    };
    setMessages((current) => [...current, optimisticUser]);
    setChatInput("");
    setError(null);
    setBusy(true);
    setAiPending(invokeModel);
    try {
      const raw = await apiFetch<unknown>(`/sessions/${sessionId}/messages`, token, {
        method: "POST",
        body: JSON.stringify({
          content: text,
          invoke_model: invokeModel,
          skip_hidden_brief_update: false,
        }),
      });
      const response = normalizePostMessagesResponse(raw);
      const outgoing = response.messages;
      setMessages((current) => mergeMessagesFromPost(current, outgoing));
      if (outgoing.length) setLastMsgId(outgoing[outgoing.length - 1]!.id);
      applyPanelConfigFromResponse(response.panel_config);
      applyProblemBriefFromResponse(response.problem_brief);
      applyProcessingFromResponse(response.processing);
      if (invokeModel) startEagerMessagePoll();
    } catch (error) {
      setMessages((current) => current.filter((message) => message.id !== tempUserId));
      setChatInput(text);
      setError(error instanceof Error ? error.message : "Send failed");
    } finally {
      setBusy(false);
      setAiPending(false);
    }
  }, [
    applyProcessingFromResponse,
    applyPanelConfigFromResponse,
    applyProblemBriefFromResponse,
    chatInputRef,
    invokeModel,
    session?.status,
    sessionId,
    setAiPending,
    setBusy,
    setChatInput,
    setError,
    setLastMsgId,
    setMessages,
    startEagerMessagePoll,
    token,
  ]);

  const simulateUpload = useCallback(
    async (fileNames: string[]) => {
      if (!token || !sessionId) return;
      const fileList = fileNames.join(", ");
      await postContextMessage(`I'm uploading the following file(s): ${fileList}`, invokeModel);
      try {
        await apiFetch(`/sessions/${sessionId}/simulate-upload`, token, { method: "POST" });
        setError(null);
      } catch (error) {
        setError(error instanceof Error ? error.message : "Upload failed");
      }
    },
    [invokeModel, postContextMessage, sessionId, setError, token],
  );

  const saveConfig = useCallback(async (overrideConfig?: string) => {
    if (!token || !sessionId) return;
    const textToSave = overrideConfig !== undefined ? overrideConfig : configText;
    let parsed: Record<string, unknown>;
    try {
      const raw = textToSave.trim();
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
      const nextSession = await apiFetch<Session>(`/sessions/${sessionId}/panel`, token, {
        method: "PATCH",
        body: JSON.stringify({
          panel_config: parsed,
          acknowledgement,
        }),
      });
      setSession(nextSession);
      problemPanelHydrationRef.current = "follow";
      setConfigText(sessionPanelToConfigText(nextSession.panel_config));
      setProblemBrief(cloneProblemBrief(nextSession.problem_brief));
      setEditMode("none");
      if (invokeModel) {
        await postContextMessage(
          `I just manually updated the problem configuration. Changed fields: ${changedKeys}. Please acknowledge the change and briefly explain the expected impact on the solver.`,
          true,
          { skipHiddenBriefUpdate: true },
        );
      }
      void refetchSnapshots?.();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }, [
    configText,
    invokeModel,
    postContextMessage,
    problemPanelHydrationRef,
    refetchSnapshots,
    session?.panel_config,
    sessionId,
    setBusy,
    setConfigText,
    setEditMode,
    setError,
    setProblemBrief,
    setSession,
    token,
  ]);

  const saveProblemBrief = useCallback(async (overrideBrief?: ProblemBrief, options?: SaveProblemBriefOptions) => {
    const baseBrief = overrideBrief ?? problemBrief;
    if (!token || !sessionId || !baseBrief) return;
    if (savingProblemBriefRef.current) return;
    const cleanedBrief: ProblemBrief = {
      ...baseBrief,
      goal_summary: baseBrief.goal_summary.trim(),
      items: baseBrief.items
        .map((item) => ({ ...item, text: item.text.trim() }))
        .filter((item) => {
          if (item.kind === "system") return true;
          if (item.text.length === 0) return false;
          if (
            (item.kind === "gathered" || item.kind === "assumption") &&
            item.text === DEFINITION_NEW_ROW_PLACEHOLDER
          ) {
            return false;
          }
          return true;
        }),
      open_questions: baseBrief.open_questions
        .map((question) => {
          const text = question.text.trim();
          const status: ProblemBriefQuestion["status"] = question.status === "answered" ? "answered" : "open";
          const answerText = (question.answer_text ?? "").trim();
          return {
            ...question,
            text,
            status,
            answer_text: status === "answered" ? (answerText || null) : null,
          };
        })
        .filter((question) => question.text.length > 0),
    };
    const previousBrief = session?.problem_brief;
    if (!previousBrief) return;
    const changedSummary = problemBriefChangeSummary(previousBrief, cleanedBrief);
    const acknowledgement = `Problem definition saved (${changedSummary}).`;
    savingProblemBriefRef.current = true;
    setBusy(true);
    try {
      const nextSession = await apiFetch<Session>(`/sessions/${sessionId}/problem-brief`, token, {
        method: "PATCH",
        body: JSON.stringify({
          problem_brief: cleanedBrief,
          acknowledgement,
        }),
      });
      setSession(nextSession);
      problemPanelHydrationRef.current = "follow";
      setConfigText(sessionPanelToConfigText(nextSession.panel_config));
      setProblemBrief(cloneProblemBrief(nextSession.problem_brief));
      setEditMode("none");
      if (invokeModel) {
        const chatMessage = options?.chatNote?.trim()
          ? options.chatNote.trim()
          : `I just manually updated the problem definition. Summary: ${changedSummary}. Please acknowledge the updated gathered info and assumptions. If the definition is now specific enough to justify a solver configuration change, mention that briefly; otherwise stay focused on clarifying the definition.`;
        await postContextMessage(chatMessage, true, {
          skipHiddenBriefUpdate: !options?.chatNote?.trim(),
        });
      }
      void refetchSnapshots?.();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Save failed");
    } finally {
      savingProblemBriefRef.current = false;
      setBusy(false);
    }
  }, [
    invokeModel,
    postContextMessage,
    problemPanelHydrationRef,
    problemBrief,
    refetchSnapshots,
    session?.problem_brief,
    sessionId,
    setBusy,
    setConfigText,
    setEditMode,
    setError,
    setProblemBrief,
    setSession,
    token,
    problemBrief,
  ]);

  const formatSnapshotTime = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  const restoreFromSnapshot = useCallback(
    async (snapshot: SnapshotSummary, source: "definition" | "config") => {
      if (!token || !sessionId || session?.status === "terminated") return;
      const timeStr = formatSnapshotTime(snapshot.created_at);
      setBusy(true);
      try {
        if (source === "definition") {
          const brief = snapshot.problem_brief;
          if (!brief || typeof brief !== "object") {
            setError("Snapshot has no definition data.");
            return;
          }
          const acknowledgement = `Restored definition from snapshot (${timeStr}).`;
          const nextSession = await apiFetch<Session>(`/sessions/${sessionId}/problem-brief`, token, {
            method: "PATCH",
            body: JSON.stringify({ problem_brief: brief, acknowledgement }),
          });
          setSession(nextSession);
          problemPanelHydrationRef.current = "follow";
          setConfigText(sessionPanelToConfigText(nextSession.panel_config));
          setProblemBrief(cloneProblemBrief(nextSession.problem_brief));
          setEditMode("none");
          if (invokeModel) {
            await postContextMessage(
              `I just restored the problem definition from a snapshot (${timeStr}). Please acknowledge the restored gathered info and assumptions.`,
              true,
              { skipHiddenBriefUpdate: true },
            );
          }
        } else {
          const panel = snapshot.panel_config;
          if (!panel || typeof panel !== "object") {
            setError("Snapshot has no config data.");
            return;
          }
          const acknowledgement = `Restored config from snapshot (${timeStr}).`;
          const nextSession = await apiFetch<Session>(`/sessions/${sessionId}/panel`, token, {
            method: "PATCH",
            body: JSON.stringify({ panel_config: panel, acknowledgement }),
          });
          setSession(nextSession);
          problemPanelHydrationRef.current = "follow";
          setConfigText(sessionPanelToConfigText(nextSession.panel_config));
          setProblemBrief(cloneProblemBrief(nextSession.problem_brief));
          setEditMode("none");
          if (invokeModel) {
            await postContextMessage(
              `I just restored the problem configuration from a snapshot (${timeStr}). Please acknowledge the change and briefly explain the expected impact on the solver.`,
              true,
              { skipHiddenBriefUpdate: true },
            );
          }
        }
      } catch (error) {
        setError(error instanceof Error ? error.message : "Restore failed");
      } finally {
        setBusy(false);
      }
    },
    [
      invokeModel,
      postContextMessage,
      problemPanelHydrationRef,
      session?.status,
      sessionId,
      setBusy,
      setConfigText,
      setEditMode,
      setError,
      setProblemBrief,
      setSession,
      token,
    ],
  );

  const syncProblemConfig = useCallback(async () => {
    if (!token || !sessionId || !problemBrief) return;
    const cleanedBrief: ProblemBrief = {
      ...problemBrief,
      goal_summary: problemBrief.goal_summary.trim(),
      items: problemBrief.items
        .map((item) => ({ ...item, text: item.text.trim() }))
        .filter((item) => {
          if (item.kind === "system") return true;
          if (item.text.length === 0) return false;
          if (
            (item.kind === "gathered" || item.kind === "assumption") &&
            item.text === DEFINITION_NEW_ROW_PLACEHOLDER
          ) {
            return false;
          }
          return true;
        }),
      open_questions: problemBrief.open_questions
        .map((question) => {
          const text = question.text.trim();
          const status: ProblemBriefQuestion["status"] = question.status === "answered" ? "answered" : "open";
          const answerText = (question.answer_text ?? "").trim();
          return {
            ...question,
            text,
            status,
            answer_text: status === "answered" ? (answerText || null) : null,
          };
        })
        .filter((question) => question.text.length > 0),
    };
    setBusy(true);
    setSyncingProblemConfig(true);
    setError(null);
    try {
      const nextSession = await apiFetch<Session>(`/sessions/${sessionId}/problem-brief`, token, {
        method: "PATCH",
        body: JSON.stringify({
          problem_brief: cleanedBrief,
          acknowledgement: "Problem config synced from the saved definition.",
        }),
      });
      setSession(nextSession);
      problemPanelHydrationRef.current = "follow";
      setConfigText(sessionPanelToConfigText(nextSession.panel_config));
      setProblemBrief(cloneProblemBrief(nextSession.problem_brief));
    } catch (error) {
      setError(error instanceof Error ? error.message : "Sync failed");
    } finally {
      setSyncingProblemConfig(false);
      setBusy(false);
    }
  }, [
    problemPanelHydrationRef,
    sessionId,
    setBusy,
    setConfigText,
    setError,
    setSyncingProblemConfig,
    problemBrief,
    setProblemBrief,
    setSession,
    token,
  ]);

  const runOptimize = useCallback(async () => {
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
      setRuns((current) => {
        const next = [...current, run];
        setActiveRun(next.length - 1);
        return next;
      });
      void syncMessages();
      void refetchSnapshots?.();
      if (invokeModel && run.ok) {
        const violations = (run.result as Record<string, unknown> | null | undefined)?.violations as
          | Record<string, unknown>
          | undefined;
        const violationSummary = violations
          ? [
              violations.time_window_stop_count ? `${violations.time_window_stop_count} time-window stops late` : "",
              violations.priority_deadline_misses ? `${violations.priority_deadline_misses} priority misses` : "",
              violations.capacity_units_over ? `${violations.capacity_units_over} units over capacity` : "",
            ].filter(Boolean).join(", ") || "no violations"
          : "unknown";
        void postContextMessage(
          `Run #${displayRunNumber(run)} just completed - cost ${run.cost?.toFixed(2) ?? "?"} (${violationSummary}). Please interpret these results, compare to any previous runs, and suggest what to adjust next.`,
          true,
        );
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "Run failed");
    } finally {
      setBusy(false);
      setOptimizing(false);
    }
  }, [
    configText,
    invokeModel,
    postContextMessage,
    refetchSnapshots,
    session?.optimization_allowed,
    sessionId,
    setActiveRun,
    setBusy,
    setError,
    setOptimizing,
    setRuns,
    syncMessages,
    token,
  ]);

  const runEvaluateEdited = useCallback(async () => {
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
      setRuns((current) => {
        const next = [...current, run];
        setActiveRun(next.length - 1);
        return next;
      });
      void syncMessages();
      void refetchSnapshots?.();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Evaluate failed");
    } finally {
      setBusy(false);
    }
  }, [configText, refetchSnapshots, scheduleText, sessionId, setActiveRun, setBusy, setError, setRuns, syncMessages, token]);

  const saveModelSettings = useCallback(async () => {
    if (!token || !sessionId) return;
    const submittedKey = modelKey.trim();
    setBusy(true);
    try {
      const nextSession = await apiFetch<Session>(`/sessions/${sessionId}/settings`, token, {
        method: "PATCH",
        body: JSON.stringify({
          gemini_api_key: modelKey || undefined,
          gemini_model: modelName || undefined,
        }),
      });
      setSession({
        ...nextSession,
        gemini_key_configured: submittedKey.length > 0 ? true : Boolean(nextSession.gemini_key_configured),
      });
      setShowModelDialog(false);
      setModelKey("");
      void syncSession();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Settings failed");
    } finally {
      setBusy(false);
    }
  }, [modelKey, modelName, sessionId, setBusy, setError, setModelKey, setSession, setShowModelDialog, syncSession, token]);


  const cancelOptimize = useCallback(async () => {
    if (!token || !sessionId) return;
    setError(null);
    try {
      await apiFetch<{ signalled: boolean }>(`/sessions/${sessionId}/runs/cancel`, token, {
        method: "POST",
      });
    } catch (error) {
      setError(error instanceof Error ? error.message : "Cancel failed");
    }
  }, [sessionId, setError, token]);

  const closeModelDialog = useCallback(() => {
    setShowModelDialog(false);
    void syncSession();
  }, [setShowModelDialog, syncSession]);

  return {
    sendChat,
    simulateUpload,
    saveConfig,
    saveProblemBrief,
    syncProblemConfig,
    restoreFromSnapshot,
    runOptimize,
    runEvaluateEdited,
    cancelOptimize,
    saveModelSettings,
    closeModelDialog,
  };
}
