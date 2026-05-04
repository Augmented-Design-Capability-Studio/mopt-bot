import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent, type RefObject } from "react";

import { type TutorialStepId } from "@shared/api";
import type {
  Message,
  ProblemBrief,
  RunResult,
  Session,
  SnapshotSummary,
  TestProblemMeta,
} from "@shared/api";
import { BackendConnectionControl } from "@shared/status/BackendConnectionControl";
import { StatusChip } from "@shared/status/StatusChip";
import { anchorForTutorialStep } from "../../tutorial/anchors";
import { patchForTutorialEvent, type ParticipantTutorialPatch } from "../../tutorial/events";
import { completionFromSession, getTutorialStepOverride, getTutorialSteps } from "../../tutorial/state";
import { resolveActiveTutorialStep } from "../../tutorial/transitions";
import type { TutorialAction } from "../../tutorial/types";

import { ChatSection } from "../chat/ChatSection";
import { type EditMode } from "../lib/clientTypes";
import type { ClientOpsState } from "../lib/clientOps";
import { formatProcessingError } from "../lib/processingErrors";
import { ConfigPanel } from "../problemConfig/ConfigPanel";
import { ResultsPanel } from "../results/ResultsPanel";
import { ModelSettingsDialog } from "./ModelSettingsDialog";

function workflowAccentClass(mode: string | undefined): string {
  if (mode === "agile") return "app-header--wf-agile";
  if (mode === "waterfall") return "app-header--wf-waterfall";
  if (mode === "demo") return "app-header--wf-demo";
  return "";
}

type BubbleStyle = {
  top?: number;
  left?: number;
  right?: number;
  bottom?: number;
};

type ClientShellProps = {
  sessionId: string;
  participantLabel: string;
  /** Resolved from GET /meta/test-problems for the active session id; null if unavailable. */
  testProblemMeta: TestProblemMeta | null;
  session: Session | null;
  messages: Message[];
  runs: RunResult[];
  currentRun?: RunResult;
  activeRun: number;
  chatInput: string;
  invokeModel: boolean;
  configText: string;
  problemBrief: ProblemBrief | null;
  hasUploadedData: boolean;
  scheduleText: string;
  editMode: EditMode;
  busy: boolean;
  chatBusy: boolean;
  syncingProblemConfig: boolean;
  clientOps: ClientOpsState;
  optimizing: boolean;
  error: string | null;
  showModelDialog: boolean;
  modelName: string;
  modelKey: string;
  aiPending: boolean;
  fileRef: RefObject<HTMLInputElement>;
  simulatedUploadChips: string[];
  onChatInputChange: (value: string) => void;
  onInvokeModelChange: (value: boolean) => void;
  onConfigTextChange: (value: string) => void;
  onProblemBriefChange: (value: ProblemBrief | null) => void;
  onScheduleTextChange: (value: string) => void;
  onSetActiveRun: (index: number) => void;
  onSetEditMode: (mode: EditMode) => void;
  onSetShowModelDialog: (open: boolean) => void;
  onModelNameChange: (value: string) => void;
  onModelKeyChange: (value: string) => void;
  onLeaveSession: () => void;
  onStartSession: () => void | Promise<void>;
  onSendChat: () => void | Promise<void>;
  onRequestDefinitionCleanup: () => void | Promise<void>;
  onRequestOpenQuestionCleanup: () => void | Promise<void>;
  onSimulateUpload: (fileNames: string[]) => void | Promise<void>;
  onRemoveSimulatedUploadChip: (fileName: string) => void;
  onSaveConfig: () => void | Promise<void>;
  onApplyTutorialConfigPatch?: (patch: Record<string, unknown>) => void | Promise<void>;
  onSaveDefinitionEdit: () => void | Promise<void>;
  onCancelDefinitionEdit: () => void;
  onEnsureDefinitionEditing: () => void;
  isDefinitionDirty: boolean;
  onSyncProblemConfig: () => void | Promise<void>;
  onRecoverGoalTerms?: () => void | Promise<void>;
  onEnterConfigEdit?: () => void;
  onCancelConfigEdit?: () => void;
  onLoadConfigFromLastRun?: () => void;
  onBookmarkSnapshot?: () => void | Promise<void>;
  onRestoreFromSnapshot?: (snapshot: SnapshotSummary, source: "definition" | "config") => void;
  onLoadSnapshots?: () => void | Promise<void>;
  snapshots?: SnapshotSummary[];
  snapshotsLoading?: boolean;
  canLoadFromLastRun?: boolean;
  canLoadFromSnapshot?: boolean;
  isConfigDirty?: boolean;
  onRunOptimize: () => void | Promise<void>;
  onCancelOptimize: () => void | Promise<void>;
  onRunEvaluateEdited: () => void | Promise<void>;
  onRevertEditedRun: (run: RunResult) => void | Promise<void>;
  onExplainRun: (run: RunResult) => void | Promise<void>;
  onLoadConfigFromRun: (run: RunResult) => void | Promise<void>;
  candidateRunIds: number[];
  onToggleCandidateRun: (runId: number, checked: boolean) => void;
  onCloseModelDialog: () => void;
  onSaveModelSettings: () => void | Promise<void>;
  onSetParticipantTutorialState?: (patch: ParticipantTutorialPatch) => void | Promise<void>;
};

export function ClientShell({
  sessionId,
  participantLabel,
  testProblemMeta,
  session,
  messages,
  runs,
  currentRun,
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
  clientOps,
  optimizing,
  error,
  showModelDialog,
  modelName,
  modelKey,
  aiPending,
  fileRef,
  simulatedUploadChips,
  onChatInputChange,
  onInvokeModelChange,
  onConfigTextChange,
  onProblemBriefChange,
  onScheduleTextChange,
  onSetActiveRun,
  onSetEditMode,
  onSetShowModelDialog,
  onModelNameChange,
  onModelKeyChange,
  onLeaveSession,
  onStartSession,
  onSendChat,
  onRequestDefinitionCleanup,
  onRequestOpenQuestionCleanup,
  onSimulateUpload,
  onRemoveSimulatedUploadChip,
  onSaveConfig,
  onApplyTutorialConfigPatch,
  onSaveDefinitionEdit,
  onCancelDefinitionEdit,
  onEnsureDefinitionEditing,
  isDefinitionDirty,
  onSyncProblemConfig,
  onRecoverGoalTerms,
  onEnterConfigEdit,
  onCancelConfigEdit,
  onLoadConfigFromLastRun,
  onBookmarkSnapshot,
  onRestoreFromSnapshot,
  onLoadSnapshots,
  snapshots,
  snapshotsLoading,
  canLoadFromLastRun,
  canLoadFromSnapshot,
  isConfigDirty,
  onRunOptimize,
  onCancelOptimize,
  onRunEvaluateEdited,
  onRevertEditedRun,
  onExplainRun,
  onLoadConfigFromRun,
  candidateRunIds,
  onToggleCandidateRun,
  onCloseModelDialog,
  onSaveModelSettings,
  onSetParticipantTutorialState,
}: ClientShellProps) {
  const panelClass = (name: EditMode) => (editMode !== "none" && editMode !== name ? "panel panel-locked" : "panel");

  const sessionTerminated = session?.status === "terminated";
  const chatLocked = sessionTerminated;
  const chatFirstMode = !chatLocked && editMode === "none" && messages.length === 0;
  const shouldNudgeChat = chatFirstMode && !showModelDialog;
  const chatAttentionKey = shouldNudgeChat ? `${sessionId}:new-session-chat-focus` : undefined;
  const modelKeyStatus = session == null ? "neutral" : session.gemini_key_configured ? "ok" : "warn";
  const modelKeyIcon = modelKeyStatus === "ok" ? "✓" : modelKeyStatus === "warn" ? "⚠" : "○";
  const backgroundBriefPending = session?.processing?.brief_status === "pending";
  const backgroundConfigPending = session?.processing?.config_status === "pending";
  const backgroundProcessingPending = backgroundBriefPending || backgroundConfigPending;
  const chatPending = aiPending || backgroundProcessingPending || optimizing;
  const chatPendingLabel = optimizing
    ? "Running optimization..."
    : aiPending
      ? "Thinking..."
      : backgroundProcessingPending
        ? "Updating definition and configuration..."
        : "Working...";
  const backgroundProcessingError = session?.processing?.processing_error ?? null;
  const backgroundProcessingErrorMessage = formatProcessingError(backgroundProcessingError);
  const accentClass = workflowAccentClass(session?.workflow_mode);
  const inDemoMode = (session?.workflow_mode ?? "").toLowerCase() === "demo";
  const serverPn = (session?.participant_number ?? "").trim();
  const localPn = participantLabel.trim();
  const displayParticipant = serverPn || localPn;
  // Demo mode reuses the tutorial guardrails server-side (see backend
  // `is_tutorial_active`) but never shows bubbles to the participant.
  const tutorialEnabled =
    Boolean(session?.participant_tutorial_enabled) && !sessionTerminated && !inDemoMode;
  const [showTutorial, setShowTutorial] = useState(false);
  const [bubbleStyle, setBubbleStyle] = useState<BubbleStyle>({ right: 16, bottom: 16 });
  const [bubblePinned, setBubblePinned] = useState(false);
  const [tabSwitchRequest, setTabSwitchRequest] = useState<{ nonce: number; target: "definition" | "config" } | null>(null);
  const bubbleRef = useRef<HTMLElement | null>(null);
  const dragStateRef = useRef<{ pointerId: number; dx: number; dy: number } | null>(null);
  const prevTutorialOverrideRef = useRef<TutorialStepId | null>(null);

  const completedByStepId = useMemo(() => completionFromSession(session), [session]);
  const tutorialSteps = useMemo(
    () => getTutorialSteps(session?.test_problem_id, session?.workflow_mode),
    [session?.test_problem_id, session?.workflow_mode],
  );
  const tutorialSessionStepId = useMemo(() => getTutorialStepOverride(session), [session]);
  const activeTutorialStep = useMemo(
    () => resolveActiveTutorialStep(tutorialSteps, completedByStepId, tutorialSessionStepId),
    [completedByStepId, tutorialSessionStepId, tutorialSteps],
  );
  const tutorialDone = activeTutorialStep == null;

  const activeTutorialAnchor = useMemo(() => {
    if (!activeTutorialStep) return null;
    return anchorForTutorialStep(activeTutorialStep.id, editMode);
  }, [activeTutorialStep, editMode]);

  // Bubble visibility is now driven entirely by the researcher toggle plus
  // step progression. There is no participant-side dismiss affordance — the
  // wrap-up step's "Got it!" button is the only user-driven way to end the
  // tutorial, and it does so by flipping `participant_tutorial_enabled` off.
  useEffect(() => {
    if (!tutorialEnabled || tutorialDone) {
      setShowTutorial(false);
      return;
    }
    setShowTutorial(true);
  }, [tutorialDone, tutorialEnabled]);

  useEffect(() => {
    if (!tutorialEnabled || !showTutorial || !activeTutorialAnchor) {
      setBubbleStyle({ right: 16, bottom: 16 });
      return;
    }
    if (bubblePinned) return;
    const computePosition = () => {
      const target = document.querySelector<HTMLElement>(`[data-tutorial-anchor="${activeTutorialAnchor}"]`);
      const bubble = bubbleRef.current;
      if (!target || !bubble) {
        setBubbleStyle({ right: 16, bottom: 16 });
        return;
      }
      const rect = target.getBoundingClientRect();
      const viewportW = window.innerWidth;
      const viewportH = window.innerHeight;
      const bubbleW = bubble.offsetWidth || 340;
      const bubbleH = bubble.offsetHeight || 120;
      const margin = 10;
      const targetGap = 18;
      let left = rect.right + targetGap;
      let top = rect.top;

      // Prefer placing to the right of target; fallback left when there is not enough room.
      if (left + bubbleW > viewportW - margin) {
        left = rect.left - bubbleW - targetGap;
      }
      // If horizontal placement is still clipped, clamp and place below target with offset.
      if (left < margin || left + bubbleW > viewportW - margin) {
        left = Math.max(margin, Math.min(rect.left, viewportW - bubbleW - margin));
        top = rect.bottom + targetGap;
      }
      // If below is clipped, place above with offset.
      if (top + bubbleH > viewportH - margin) {
        top = rect.top - bubbleH - targetGap;
      }
      // Final viewport clamp.
      top = Math.max(margin, Math.min(top, viewportH - bubbleH - margin));
      left = Math.max(margin, Math.min(left, viewportW - bubbleW - margin));
      setBubbleStyle({ left, top });
    };

    computePosition();
    window.addEventListener("resize", computePosition);
    window.addEventListener("scroll", computePosition, true);
    return () => {
      window.removeEventListener("resize", computePosition);
      window.removeEventListener("scroll", computePosition, true);
    };
  }, [activeTutorialAnchor, bubblePinned, showTutorial, tutorialEnabled]);

  useEffect(() => {
    // Step changes should re-anchor to the new focus target rather than preserving dragged pin position.
    setBubblePinned(false);
  }, [activeTutorialAnchor]);

  useEffect(() => {
    const prev = prevTutorialOverrideRef.current;
    const next = tutorialSessionStepId;
    // Researcher selected a new step: surface the bubble at that step.
    if (tutorialEnabled && next && next !== prev) {
      setShowTutorial(true);
    }
    prevTutorialOverrideRef.current = next;
  }, [tutorialEnabled, tutorialSessionStepId]);

  useEffect(() => {
    if (!tutorialEnabled || !activeTutorialStep) return;
    if (tutorialSessionStepId === activeTutorialStep.id) return;
    void onSetParticipantTutorialState?.({ tutorial_step_override: activeTutorialStep.id });
  }, [activeTutorialStep, onSetParticipantTutorialState, tutorialEnabled, tutorialSessionStepId]);

  useEffect(() => {
    if (!tutorialEnabled || !showTutorial || !activeTutorialAnchor) return;
    const target = document.querySelector<HTMLElement>(`[data-tutorial-anchor="${activeTutorialAnchor}"]`);
    if (!target) return;
    target.classList.add("tutorial-target-highlight");
    return () => target.classList.remove("tutorial-target-highlight");
  }, [activeTutorialAnchor, showTutorial, tutorialEnabled]);

  const handleSaveDefinitionEdit = useCallback(async () => {
    await onSaveDefinitionEdit();
  }, [onSaveDefinitionEdit]);

  const handleSaveConfig = useCallback(async () => {
    await onSaveConfig();
  }, [onSaveConfig]);

  const handleBubblePointerDown = useCallback((e: PointerEvent<HTMLElement>) => {
    const bubble = bubbleRef.current;
    if (!bubble) return;
    const rect = bubble.getBoundingClientRect();
    dragStateRef.current = {
      pointerId: e.pointerId,
      dx: e.clientX - rect.left,
      dy: e.clientY - rect.top,
    };
    bubble.setPointerCapture(e.pointerId);
    setBubblePinned(true);
  }, []);

  const handleBubblePointerMove = useCallback((e: PointerEvent<HTMLElement>) => {
    const drag = dragStateRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const bubble = bubbleRef.current;
    if (!bubble) return;
    const bubbleW = bubble.offsetWidth || 340;
    const bubbleH = bubble.offsetHeight || 120;
    const margin = 8;
    const left = Math.max(margin, Math.min(e.clientX - drag.dx, window.innerWidth - bubbleW - margin));
    const top = Math.max(margin, Math.min(e.clientY - drag.dy, window.innerHeight - bubbleH - margin));
    setBubbleStyle({ left, top });
  }, []);

  const handleBubblePointerUp = useCallback((e: PointerEvent<HTMLElement>) => {
    const drag = dragStateRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const bubble = bubbleRef.current;
    if (bubble?.hasPointerCapture(e.pointerId)) {
      bubble.releasePointerCapture(e.pointerId);
    }
    dragStateRef.current = null;
  }, []);

  const handleTutorialAction = useCallback(
    (action: TutorialAction) => {
      switch (action.kind) {
        case "fill-chat-input":
          onChatInputChange(action.payload);
          break;
        case "copy-clipboard":
          if (typeof navigator !== "undefined" && navigator.clipboard) {
            void navigator.clipboard.writeText(action.payload).catch(() => {
              // Clipboard write rejected (permissions, insecure context); silently no-op.
            });
          }
          break;
        case "switch-tab":
          setTabSwitchRequest((prev) => ({ nonce: (prev?.nonce ?? 0) + 1, target: action.target }));
          break;
        case "apply-config-patch":
          if (onApplyTutorialConfigPatch) {
            void onApplyTutorialConfigPatch(action.patch);
          }
          break;
        case "acknowledge-step": {
          // Dynamic-keyed patch: the flag name is decided by the per-problem
          // tutorial step. The discriminated union keeps `flag` as a plain
          // string here, but the backend ignores unknown fields, so a typo
          // becomes a silent no-op rather than a crash.
          const patch = { [action.flag]: true } as ParticipantTutorialPatch;
          void onSetParticipantTutorialState?.(patch);
          break;
        }
        case "complete-tutorial":
          // Mark wrap-up acknowledged AND turn the bubble off in one patch so the
          // bubble doesn't briefly re-appear at the wrap-up step before the
          // completion flag round-trips from the backend.
          void onSetParticipantTutorialState?.({
            tutorial_completed: true,
            participant_tutorial_enabled: false,
          });
          break;
      }
    },
    [onApplyTutorialConfigPatch, onChatInputChange, onSetParticipantTutorialState],
  );

  return (
    <div className="app-shell">
      <header className={accentClass ? `app-header ${accentClass}` : "app-header"}>
        <div className="app-header-title-cluster">
          <span className="app-title">
            User
            {displayParticipant ? (
              <span className="participant-header-number" title="User number for this session">
                {" "}
                #{displayParticipant}
              </span>
            ) : null}
          </span>
          {inDemoMode ? (
            <span
              className="participant-demo-chip"
              title="Demo mode: agent output is constrained for predictable demonstrations. Tutorial bubbles are hidden in this mode."
            >
              Demo mode
            </span>
          ) : null}
        </div>
        <span className="muted">
          Session {sessionId.slice(0, 8)}…{sessionTerminated ? " · ended" : ""}
        </span>
        <div style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
          <StatusChip
            label="Assistant settings"
            status={modelKeyStatus}
            icon={modelKeyIcon}
            title={
              modelKeyStatus === "ok"
                ? "Assistant key is set for this session"
                : modelKeyStatus === "warn"
                  ? "No assistant key on this session - add one or ask the researcher"
                  : "Session loading"
            }
            onClick={() => onSetShowModelDialog(true)}
          />
          <BackendConnectionControl />
          <button type="button" onClick={onLeaveSession}>
            Leave session
          </button>
        </div>
      </header>
      {sessionTerminated && (
        <div className="banner-info" role="status">
          <span>
            This session was ended by the researcher. You can still read chat and runs below. Start a new session when
            you are ready to continue.
          </span>
          <button type="button" disabled={busy} onClick={() => void onStartSession()}>
            Start new session
          </button>
        </div>
      )}
      {error && !sessionTerminated && <div className="banner-warn">{error}</div>}
      <div className={chatFirstMode ? "grid-3 grid-chat-only" : "grid-3"}>
        <section className={panelClass("none")}>
          <ChatSection
            messages={messages}
            aiPending={chatPending}
            aiPendingLabel={chatPendingLabel}
            invokeModel={invokeModel}
            editMode={editMode}
            chatBusy={chatBusy}
            chatLocked={chatLocked}
            chatInput={chatInput}
            chatAttentionKey={chatAttentionKey}
            fileRef={fileRef}
            simulatedUploadChips={simulatedUploadChips}
            problemId={session?.test_problem_id ?? undefined}
            onInvokeModelChange={onInvokeModelChange}
            onChatInputChange={onChatInputChange}
            onSendChat={onSendChat}
            onSimulateUpload={onSimulateUpload}
            onRemoveSimulatedUploadChip={onRemoveSimulatedUploadChip}
            processingErrorMessage={backgroundProcessingErrorMessage}
            onRetrySync={onSyncProblemConfig}
            retryBusy={syncingProblemConfig || backgroundProcessingPending}
          />
        </section>

        {chatFirstMode && <div className="chat-first-spacer" aria-hidden="true" />}

        {!chatFirstMode && (
          <ConfigPanel
            className={editMode === "config" || editMode === "definition" ? "panel" : panelClass("config")}
            configText={configText}
            problemBrief={problemBrief}
            editMode={editMode}
            invokeModel={invokeModel}
            busy={busy}
            syncingProblemConfig={syncingProblemConfig}
            clientOps={clientOps}
            backgroundBriefPending={backgroundBriefPending}
            backgroundConfigPending={backgroundConfigPending}
            backgroundProcessingError={backgroundProcessingError}
            sessionTerminated={sessionTerminated}
            session={session}
            testProblemMeta={testProblemMeta}
            runs={runs}
            messages={messages}
            onConfigTextChange={onConfigTextChange}
            onProblemBriefChange={onProblemBriefChange}
            onSetEditMode={onSetEditMode}
            onSaveConfig={handleSaveConfig}
            onSaveDefinitionEdit={handleSaveDefinitionEdit}
            onCancelDefinitionEdit={onCancelDefinitionEdit}
            onEnsureDefinitionEditing={onEnsureDefinitionEditing}
            isDefinitionDirty={isDefinitionDirty}
            onRequestDefinitionCleanup={onRequestDefinitionCleanup}
            onRequestOpenQuestionCleanup={onRequestOpenQuestionCleanup}
            onSyncProblemConfig={onSyncProblemConfig}
            onRecoverGoalTerms={onRecoverGoalTerms}
            onEnterConfigEdit={onEnterConfigEdit}
            onCancelConfigEdit={onCancelConfigEdit}
            onLoadConfigFromLastRun={onLoadConfigFromLastRun}
            onBookmarkSnapshot={onBookmarkSnapshot}
            onRestoreFromSnapshot={onRestoreFromSnapshot}
            onLoadSnapshots={onLoadSnapshots}
            snapshots={snapshots}
            snapshotsLoading={snapshotsLoading}
            canLoadFromLastRun={canLoadFromLastRun}
            canLoadFromSnapshot={canLoadFromSnapshot}
            isConfigDirty={isConfigDirty}
            onUserTabClick={(tab) => {
              const tutorialPatch =
                tab === "definition"
                  ? patchForTutorialEvent("definition-tab-clicked", session)
                  : tab === "config"
                    ? patchForTutorialEvent("config-tab-clicked", session)
                    : null;
              if (tutorialPatch) void onSetParticipantTutorialState?.(tutorialPatch);
            }}
            tabSwitchNonce={tabSwitchRequest?.nonce}
            tabSwitchTarget={tabSwitchRequest?.target}
          />
        )}

        {!chatFirstMode && (
          <ResultsPanel
            className={editMode === "results" ? "panel" : panelClass("results")}
            runs={runs}
            activeRun={activeRun}
            currentRun={currentRun}
            scheduleText={scheduleText}
            editMode={editMode}
            busy={busy}
            optimizing={optimizing}
            session={session}
            configText={configText}
            problemBrief={problemBrief}
            hasUploadedData={hasUploadedData}
            problemMeta={testProblemMeta}
            sessionTerminated={sessionTerminated}
            onSetActiveRun={onSetActiveRun}
            onScheduleTextChange={onScheduleTextChange}
            onSetEditMode={onSetEditMode}
            onRunOptimize={onRunOptimize}
            onCancelOptimize={onCancelOptimize}
            onRunEvaluateEdited={onRunEvaluateEdited}
            onRevertEditedRun={onRevertEditedRun}
            onExplainRun={onExplainRun}
            onLoadConfigFromRun={onLoadConfigFromRun}
            candidateRunIds={candidateRunIds}
            onToggleCandidateRun={onToggleCandidateRun}
            onTutorialEvent={(event) => {
              const patch = patchForTutorialEvent(event, session);
              if (patch) void onSetParticipantTutorialState?.(patch);
            }}
          />
        )}
      </div>

      <ModelSettingsDialog
        open={showModelDialog}
        modelName={modelName}
        modelKey={modelKey}
        busy={busy}
        sessionTerminated={sessionTerminated}
        onModelNameChange={onModelNameChange}
        onModelKeyChange={onModelKeyChange}
        onClose={onCloseModelDialog}
        onSave={onSaveModelSettings}
      />
      {tutorialEnabled && showTutorial && activeTutorialStep ? (
        <aside
          ref={bubbleRef}
          className="participant-tutorial-bubble"
          role="status"
          aria-live="polite"
          style={bubbleStyle}
          onPointerDown={handleBubblePointerDown}
          onPointerMove={handleBubblePointerMove}
          onPointerUp={handleBubblePointerUp}
          onPointerCancel={handleBubblePointerUp}
        >
          <div className="participant-tutorial-head">
            <div className="participant-tutorial-title">{activeTutorialStep.title}</div>
          </div>
          <p>{activeTutorialStep.body}</p>
          {activeTutorialStep.actions && activeTutorialStep.actions.length > 0 ? (
            <div className="participant-tutorial-actions">
              {activeTutorialStep.actions.map((action, idx) => (
                <button
                  key={`${action.kind}-${idx}`}
                  type="button"
                  className="participant-tutorial-action-btn"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => handleTutorialAction(action)}
                >
                  {action.label}
                </button>
              ))}
            </div>
          ) : null}
          <div className="participant-tutorial-drag-hint" aria-hidden="true">
            Drag this bubble to move it
          </div>
        </aside>
      ) : null}
    </div>
  );
}
