import { useCallback, useRef, type MutableRefObject } from "react";

import {
  apiFetch,
  displayRunNumber,
  normalizePostMessagesResponse,
  sessionPanelToConfigText,
  type Message,
  type ProblemBrief,
  type RunResult,
  type Session,
  type SnapshotSummary,
  type TestProblemMeta,
} from "@shared/api";
import { parseServerDate } from "@shared/dateTime";
import { patchForTutorialEvent, type ParticipantTutorialPatch } from "../../tutorial/events";

import { mergeMessagesFromPost } from "../chat/messageMerge";
import { computeCanRunOptimization } from "../lib/optimizationGate";
import { configChangeSummary } from "../problemConfig/configSummary";
import { DEFINITION_CLEANUP_CHAT_MESSAGE } from "../problemDefinition/constants";
import { cleanProblemBriefForCompare, cloneProblemBrief, problemBriefChangeSummary } from "../problemDefinition/summary";
import type { ProblemPanelHydration } from "../problemConfig/problemPanelHydration";
import { getProblemModule } from "../problemRegistry";
import type { ParticipantOpsState } from "../lib/participantOps";
import { buildSimulatedUploadMessage } from "../lib/simulatedUploadMessage";

function maxCommittedRunNumber(existing: RunResult[]): number {
  let max = 0;
  for (const r of existing) {
    if (r.clientPending) continue;
    const n =
      typeof r.run_number === "number" && Number.isFinite(r.run_number) && r.run_number > 0 ? r.run_number : 0;
    if (n > max) max = n;
  }
  return max;
}

function makeOptimisticOptimizeRun(problem: Record<string, unknown>, existing: RunResult[]): RunResult {
  return {
    id: -Math.abs(Date.now()),
    run_number: maxCommittedRunNumber(existing) + 1,
    created_at: new Date().toISOString(),
    run_type: "optimize",
    ok: false,
    cost: null,
    reference_cost: null,
    error_message: null,
    request: { type: "optimize", problem },
    result: null,
    clientPending: true,
  };
}

function extractRoutesFromRun(run: RunResult): number[][] | null {
  const rows = run.result?.schedule?.routes;
  if (!Array.isArray(rows)) return null;
  const out: number[][] = [];
  for (const row of rows) {
    if (!row || !Array.isArray(row.task_indices)) return null;
    out.push(row.task_indices.map((v) => Number(v)).filter((v) => Number.isFinite(v)));
  }
  return out.length > 0 ? out : null;
}

function coerceRoutesPayload(raw: unknown): number[][] | null {
  if (!Array.isArray(raw)) return null;
  if (raw.every((row) => Array.isArray(row))) {
    const out = (raw as unknown[][]).map((row) =>
      row.map((v) => Number(v)).filter((v) => Number.isFinite(v)),
    );
    return out.length > 0 ? out : null;
  }
  const out: number[][] = [];
  for (const row of raw) {
    if (!row || typeof row !== "object") return null;
    const taskIndices = (row as { task_indices?: unknown }).task_indices;
    if (!Array.isArray(taskIndices)) return null;
    out.push(taskIndices.map((v) => Number(v)).filter((v) => Number.isFinite(v)));
  }
  return out.length > 0 ? out : null;
}

type UseParticipantSessionActionsArgs = {
  token: string;
  hasUploadedData: boolean;
  participantNumber?: string;
  sessionId: string;
  session: Session | null;
  chatInputRef: MutableRefObject<string>;
  invokeModel: boolean;
  configText: string;
  problemBrief: ProblemBrief | null;
  problemMeta?: TestProblemMeta | null;
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
  optimizingRef: MutableRefObject<boolean>;
  setError: (value: string | null) => void;
  setShowModelDialog: (value: boolean) => void;
  setModelKey: (value: string) => void;
  setAiPending: (value: boolean) => void;
  setParticipantOps: (value: ParticipantOpsState | ((prev: ParticipantOpsState) => ParticipantOpsState)) => void;
  runs: RunResult[];
  activeRun: number;
  candidateRunIds: number[];
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
  hasUploadedData,
  participantNumber: _participantNumber,
  sessionId,
  session,
  chatInputRef,
  invokeModel,
  configText,
  problemBrief,
  problemMeta,
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
  optimizingRef,
  setError,
  setShowModelDialog,
  setModelKey,
  setAiPending,
  setParticipantOps,
  runs,
  activeRun,
  candidateRunIds,
  syncMessages,
  syncSession,
  startEagerMessagePoll,
  refetchSnapshots,
}: UseParticipantSessionActionsArgs) {
  const savingProblemBriefRef = useRef(false);
  const syncingProblemConfigRef = useRef(false);
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

  const requestDefinitionCleanup = useCallback(async () => {
    await postContextMessage(DEFINITION_CLEANUP_CHAT_MESSAGE, invokeModel);
  }, [invokeModel, postContextMessage]);

  const runOpenQuestionCleanupRequest = useCallback(async () => {
    return apiFetch<Session>(`/sessions/${sessionId}/cleanup-open-questions`, token, {
      method: "POST",
      body: JSON.stringify({ infer_resolved: true }),
    });
  }, [sessionId, token]);

  const requestOpenQuestionCleanup = useCallback(async () => {
    if (!token || !sessionId || session?.status === "terminated") return;
    setParticipantOps((prev) => ({ ...prev, cleaningOpenQuestions: true }));
    try {
      const nextSession = await runOpenQuestionCleanupRequest();
      setSession(nextSession);
      setProblemBrief(cloneProblemBrief(nextSession.problem_brief));
    } catch (error) {
      setError(error instanceof Error ? error.message : "Open-question cleanup failed");
    } finally {
      setParticipantOps((prev) => ({ ...prev, cleaningOpenQuestions: false }));
    }
  }, [runOpenQuestionCleanupRequest, session?.status, sessionId, setError, setParticipantOps, setProblemBrief, setSession, token]);

  const setParticipantTutorialState = useCallback(
    async (patch: ParticipantTutorialPatch): Promise<void> => {
      if (!token || !sessionId) return;
      try {
        const nextSession = await apiFetch<Session>(`/sessions/${sessionId}/participant-tutorial`, token, {
          method: "PATCH",
          body: JSON.stringify(patch),
        });
        setSession(nextSession);
      } catch (error) {
        setError(error instanceof Error ? error.message : "Could not update tutorial setting");
      }
    },
    [sessionId, setError, setSession, token],
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
    setParticipantOps((prev) => ({ ...prev, sendingChat: true }));
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
      const tutorialPatch = patchForTutorialEvent("chat-started", session);
      if (tutorialPatch) void setParticipantTutorialState(tutorialPatch);
      if (invokeModel) startEagerMessagePoll();
    } catch (error) {
      setMessages((current) => current.filter((message) => message.id !== tempUserId));
      setChatInput(text);
      setError(error instanceof Error ? error.message : "Send failed");
    } finally {
      setParticipantOps((prev) => ({ ...prev, sendingChat: false }));
      setBusy(false);
      setAiPending(false);
    }
  }, [
    applyProcessingFromResponse,
    applyPanelConfigFromResponse,
    applyProblemBriefFromResponse,
    chatInputRef,
    invokeModel,
    session?.participant_tutorial_enabled,
    session?.tutorial_chat_started,
    session?.status,
    sessionId,
    setAiPending,
    setBusy,
    setChatInput,
    setError,
    setLastMsgId,
    setMessages,
    setParticipantOps,
    setParticipantTutorialState,
    startEagerMessagePoll,
    token,
  ]);

  const simulateUpload = useCallback(
    async (fileNames: string[]) => {
      if (!token || !sessionId) return;
      await postContextMessage(buildSimulatedUploadMessage(fileNames), invokeModel);
      const tutorialPatch = patchForTutorialEvent("files-uploaded", session);
      if (tutorialPatch) void setParticipantTutorialState(tutorialPatch);
      try {
        await apiFetch(`/sessions/${sessionId}/simulate-upload`, token, { method: "POST" });
        setError(null);
      } catch (error) {
        setError(error instanceof Error ? error.message : "Upload failed");
      }
    },
    [invokeModel, postContextMessage, session?.participant_tutorial_enabled, sessionId, setError, setParticipantTutorialState, token],
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
    const acknowledgement = "";
    setBusy(true);
    setParticipantOps((prev) => ({ ...prev, savingConfig: true }));
    try {
      const nextSession = await apiFetch<Session>(`/sessions/${sessionId}/panel`, token, {
        method: "PATCH",
        body: JSON.stringify({ panel_config: parsed, acknowledgement }),
      });
      setSession(nextSession);
      setEditMode("none");
      problemPanelHydrationRef.current = "follow";
      setConfigText(sessionPanelToConfigText(nextSession.panel_config));
      setProblemBrief(cloneProblemBrief(nextSession.problem_brief));
      const tutorialPatch = patchForTutorialEvent("config-saved", nextSession);
      if (tutorialPatch) void setParticipantTutorialState(tutorialPatch);
      if (invokeModel) {
        void postContextMessage(
          `I manually updated the problem configuration. Changed settings: ${changedKeys}. Please acknowledge in 1-2 short sentences, use participant-friendly names, and keep the impact explanation concise.`,
          true,
          { skipHiddenBriefUpdate: true },
        );
      }
      void refetchSnapshots?.();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Save failed");
    } finally {
      setParticipantOps((prev) => ({ ...prev, savingConfig: false }));
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
    setParticipantOps,
    setProblemBrief,
    setSession,
    setParticipantTutorialState,
    token,
  ]);

  const saveProblemBrief = useCallback(async (overrideBrief?: ProblemBrief, options?: SaveProblemBriefOptions) => {
    const baseBrief = overrideBrief ?? problemBrief;
    if (!token || !sessionId || !baseBrief) return false;
    if (savingProblemBriefRef.current) return false;
    const cleanedBrief = cleanProblemBriefForCompare(baseBrief);
    const previousBrief = session?.problem_brief;
    if (!previousBrief) return false;
    const changedSummary = problemBriefChangeSummary(previousBrief, cleanedBrief);
    const acknowledgement = `Problem definition saved (${changedSummary}).`;
    savingProblemBriefRef.current = true;
    setBusy(true);
    setParticipantOps((prev) => ({ ...prev, savingDefinition: true }));
    try {
      const nextSession = await apiFetch<Session>(`/sessions/${sessionId}/problem-brief`, token, {
        method: "PATCH",
        body: JSON.stringify({
          problem_brief: cleanedBrief,
          acknowledgement,
        }),
      });
      setSession(nextSession);
      setEditMode("none");
      problemPanelHydrationRef.current = "follow";
      setConfigText(sessionPanelToConfigText(nextSession.panel_config));
      setProblemBrief(cloneProblemBrief(nextSession.problem_brief));
      const tutorialPatch = patchForTutorialEvent("definition-saved", nextSession);
      if (tutorialPatch) void setParticipantTutorialState(tutorialPatch);
      if (invokeModel) {
        const chatMessage = options?.chatNote?.trim()
          ? options.chatNote.trim()
          : `I just manually updated the problem definition. Summary: ${changedSummary}. Please acknowledge the updated gathered info and assumptions. If the definition is now specific enough to justify a solver configuration change, mention that briefly; otherwise stay focused on clarifying the definition.`;
        void postContextMessage(chatMessage, true, {
          skipHiddenBriefUpdate: !options?.chatNote?.trim(),
        });
      }
      void refetchSnapshots?.();
      void syncSession();
      return true;
    } catch (error) {
      setError(error instanceof Error ? error.message : "Save failed");
      return false;
    } finally {
      savingProblemBriefRef.current = false;
      setParticipantOps((prev) => ({ ...prev, savingDefinition: false }));
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
    setParticipantOps,
    setProblemBrief,
    setSession,
    setParticipantTutorialState,
    syncSession,
    token,
  ]);

  const formatSnapshotTime = (iso: string) => {
    try {
      const d = parseServerDate(iso);
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
      setParticipantOps((prev) => ({ ...prev, restoringSnapshot: true }));
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
        setParticipantOps((prev) => ({ ...prev, restoringSnapshot: false }));
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
      setParticipantOps,
      setProblemBrief,
      setSession,
      token,
    ],
  );

  const syncProblemConfig = useCallback(async () => {
    if (!token || !sessionId || !problemBrief) return;
    if (syncingProblemConfigRef.current) return;
    if (session?.processing?.brief_status === "pending" || session?.processing?.config_status === "pending") {
      setError("A background definition/config update is still running. Wait for it to settle, then sync again.");
      return;
    }
    const cleanedBrief = cleanProblemBriefForCompare(problemBrief);
    syncingProblemConfigRef.current = true;
    setSyncingProblemConfig(true);
    setParticipantOps((prev) => ({ ...prev, syncingConfig: true }));
    setError(null);
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 30000);
    try {
      const nextSession = await apiFetch<Session>(`/sessions/${sessionId}/problem-brief`, token, {
        method: "PATCH",
        signal: controller.signal,
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
      if (error instanceof Error && error.name === "AbortError") {
        setError("Sync timed out after 30s. You can continue chatting and retry sync.");
      } else {
        setError(error instanceof Error ? error.message : "Sync failed");
      }
    } finally {
      window.clearTimeout(timeoutId);
      syncingProblemConfigRef.current = false;
      setParticipantOps((prev) => ({ ...prev, syncingConfig: false }));
      setSyncingProblemConfig(false);
    }
  }, [
    problemBrief,
    problemPanelHydrationRef,
    session?.processing?.brief_status,
    session?.processing?.config_status,
    sessionId,
    setConfigText,
    setError,
    setParticipantOps,
    setSyncingProblemConfig,
    setProblemBrief,
    setSession,
    token,
  ]);

  const runOptimize = useCallback(
    async (options?: { agileAutorunStorageKey?: string }): Promise<void> => {
    if (!token || !sessionId || !computeCanRunOptimization(session, configText, problemBrief, hasUploadedData, problemMeta)) return;
    let panel: Record<string, unknown>;
    try {
      panel = JSON.parse(configText) as Record<string, unknown>;
    } catch {
      setError("Fix configuration JSON before running.");
      return;
    }
    const agileKey = options?.agileAutorunStorageKey;
    if (agileKey && typeof sessionStorage !== "undefined") {
      try {
        sessionStorage.setItem(agileKey, "1");
      } catch {
        /* private mode */
      }
    }
    const problem = (panel.problem ?? panel) as Record<string, unknown>;
    const candidateSeeds = runs
      .filter((run) => candidateRunIds.includes(run.id))
      .map((run) => {
        const routes = extractRoutesFromRun(run);
        if (!routes) return null;
        return { source_run_id: run.id, routes };
      })
      .filter((v): v is { source_run_id: number; routes: number[][] } => v !== null);
    optimizingRef.current = true;
    setBusy(true);
    setOptimizing(true);
    setError(null);
    setRuns((current) => {
      const base = current.filter((r) => !r.clientPending);
      const pending = makeOptimisticOptimizeRun(problem, base);
      const next = [...base, pending];
      setActiveRun(next.length - 1);
      return next;
    });
    try {
      const run = await apiFetch<RunResult>(`/sessions/${sessionId}/runs`, token, {
        method: "POST",
        body: JSON.stringify({
          type: "optimize",
          problem,
          candidate_seed_run_ids: candidateSeeds.map((seed) => seed.source_run_id),
          candidate_seeds: candidateSeeds,
        }),
      });
      setRuns((current) => {
        const idx = current.findIndex((r) => r.clientPending);
        if (idx < 0) {
          const next = [...current, run];
          setActiveRun(next.length - 1);
          return next;
        }
        const next = [...current];
        next[idx] = run;
        return next;
      });
      void syncMessages();
      void refetchSnapshots?.();
      if (invokeModel && run.ok) {
        const module = getProblemModule(session?.test_problem_id ?? "");
        const violationSummary = module.formatRunViolationSummary?.(run.result) ?? "—";
        void postContextMessage(
          `Run #${displayRunNumber(run)} just completed - cost ${run.cost?.toFixed(2) ?? "?"} (${violationSummary}). Give a very brief interpretation in 1-2 short sentences using plain language and suggest at most one next adjustment.`,
          true,
          { skipHiddenBriefUpdate: true },
        );
      }
      if (run.ok) {
        const tutorialPatch = patchForTutorialEvent("run-completed", session);
        if (tutorialPatch) void setParticipantTutorialState(tutorialPatch);
      }
    } catch (error) {
      setRuns((current) => {
        const filtered = current.filter((r) => !r.clientPending);
        setActiveRun((ar) => (filtered.length === 0 ? 0 : Math.min(ar, filtered.length - 1)));
        return filtered;
      });
      setError(error instanceof Error ? error.message : "Run failed");
    } finally {
      optimizingRef.current = false;
      setBusy(false);
      setOptimizing(false);
    }
    },
    [
    candidateRunIds,
    configText,
    invokeModel,
    optimizingRef,
    postContextMessage,
    refetchSnapshots,
    problemBrief,
    runs,
    session,
    sessionId,
    hasUploadedData,
    setActiveRun,
    setBusy,
    setError,
    setOptimizing,
    setRuns,
    setParticipantTutorialState,
    syncMessages,
    token,
    ],
  );

  const runEvaluateEdited = useCallback(async () => {
    if (!token || !sessionId) return;
    const module = getProblemModule(session?.test_problem_id ?? "");
    if (!module.parseEvalRoutes) return;
    let routes: number[][] | null;
    try {
      routes = module.parseEvalRoutes(JSON.parse(scheduleText) as unknown);
    } catch {
      setError("Schedule JSON is invalid.");
      return;
    }
    if (!routes || routes.length === 0) {
      setError("Schedule JSON did not produce valid routes.");
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
    const targetRun = runs[activeRun];
    if (!targetRun) {
      setError("No active run selected.");
      return;
    }
    setBusy(true);
    try {
      const run = await apiFetch<RunResult>(`/sessions/${sessionId}/runs/${targetRun.id}/evaluate-edit`, token, {
        method: "POST",
        body: JSON.stringify({ problem, routes }),
      });
      setRuns((current) => {
        const next = current.map((r) => (r.id === run.id ? run : r));
        return next;
      });
      setEditMode("none");
      void syncMessages();
      void refetchSnapshots?.();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Evaluate failed");
    } finally {
      setBusy(false);
    }
  }, [activeRun, configText, refetchSnapshots, runs, scheduleText, session, sessionId, setBusy, setEditMode, setError, setRuns, syncMessages, token]);

  const revertEditedRun = useCallback(async (run: RunResult) => {
    if (!token || !sessionId) return;
    const result = run.result as Record<string, unknown> | null;
    const original = (result?.original_snapshot as Record<string, unknown> | undefined)?.result as Record<string, unknown> | undefined;
    const originalSchedule = original?.schedule as { routes?: unknown } | undefined;
    const routes = coerceRoutesPayload(originalSchedule?.routes);
    if (!routes) {
      setError("No original snapshot available to revert.");
      return;
    }
    const runProblem = run.request?.problem;
    const problem =
      runProblem && typeof runProblem === "object"
        ? (runProblem as Record<string, unknown>)
        : (() => {
            try {
              const panel = JSON.parse(configText) as Record<string, unknown>;
              return (panel.problem ?? panel) as Record<string, unknown>;
            } catch {
              return {};
            }
          })();
    setBusy(true);
    try {
      const updated = await apiFetch<RunResult>(`/sessions/${sessionId}/runs/${run.id}/evaluate-edit`, token, {
        method: "POST",
        body: JSON.stringify({ problem, routes }),
      });
      setRuns((current) => current.map((r) => (r.id === updated.id ? updated : r)));
      setEditMode("none");
      void syncMessages();
      void refetchSnapshots?.();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Revert failed");
    } finally {
      setBusy(false);
    }
  }, [configText, refetchSnapshots, sessionId, setBusy, setEditMode, setError, setRuns, syncMessages, token]);

  const explainRun = useCallback(async (run: RunResult) => {
    if (!token || !sessionId || session?.status === "terminated") return;
    const runNo = displayRunNumber(run);
    const runCost = run.cost == null ? "?" : run.cost.toFixed(2);
    const violationSummary = getProblemModule(session?.test_problem_id ?? "").formatRunViolationSummary?.(run.result) ?? "—";
    await postContextMessage(
      `Please explain Run #${runNo} in plain language for the participant. Include: (1) strengths, (2) likely local-improvement opportunities they may notice, (3) why a metaheuristic can still return this solution under current trade-offs, and (4) one or two concrete next-run adjustments. Context: cost=${runCost}, violations=${violationSummary}.`,
      true,
    );
  }, [postContextMessage, session?.status, session?.test_problem_id, sessionId, token]);

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
      await apiFetch<{ signalled: boolean }>(`/sessions/${sessionId}/optimization/cancel`, token, {
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
    requestDefinitionCleanup,
    requestOpenQuestionCleanup,
    simulateUpload,
    saveConfig,
    saveProblemBrief,
    syncProblemConfig,
    restoreFromSnapshot,
    runOptimize,
    runEvaluateEdited,
    revertEditedRun,
    explainRun,
    cancelOptimize,
    saveModelSettings,
    closeModelDialog,
    setParticipantTutorialState,
  };
}
