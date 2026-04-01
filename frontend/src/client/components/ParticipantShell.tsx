import type { RefObject } from "react";

import type { Message, ProblemBrief, RunResult, Session, SnapshotSummary } from "@shared/api";
import { BackendConnectionControl } from "@shared/status/BackendConnectionControl";
import { StatusChip } from "@shared/status/StatusChip";

import { ChatSection } from "../chat/ChatSection";
import { type EditMode } from "../lib/participantTypes";
import { ConfigPanel } from "../problemConfig/ConfigPanel";
import { ResultsPanel } from "../results/ResultsPanel";
import { ModelSettingsDialog } from "./ModelSettingsDialog";

type ParticipantShellProps = {
  sessionId: string;
  session: Session | null;
  messages: Message[];
  runs: RunResult[];
  currentRun?: RunResult;
  activeRun: number;
  chatInput: string;
  invokeModel: boolean;
  configText: string;
  problemBrief: ProblemBrief | null;
  scheduleText: string;
  editMode: EditMode;
  busy: boolean;
  syncingProblemConfig: boolean;
  optimizing: boolean;
  error: string | null;
  showModelDialog: boolean;
  modelName: string;
  modelKey: string;
  aiPending: boolean;
  fileRef: RefObject<HTMLInputElement>;
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
  onSimulateUpload: (fileNames: string[]) => void | Promise<void>;
  onSaveConfig: () => void | Promise<void>;
  onSaveDefinitionEdit: () => void | Promise<void>;
  onCancelDefinitionEdit: () => void;
  onEnsureDefinitionEditing: () => void;
  isDefinitionDirty: boolean;
  onSyncProblemConfig: () => void | Promise<void>;
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
  onCloseModelDialog: () => void;
  onSaveModelSettings: () => void | Promise<void>;
};

export function ParticipantShell({
  sessionId,
  session,
  messages,
  runs,
  currentRun,
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
  modelName,
  modelKey,
  aiPending,
  fileRef,
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
  onSimulateUpload,
  onSaveConfig,
  onSaveDefinitionEdit,
  onCancelDefinitionEdit,
  onEnsureDefinitionEditing,
  isDefinitionDirty,
  onSyncProblemConfig,
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
  onCloseModelDialog,
  onSaveModelSettings,
}: ParticipantShellProps) {
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
  const backgroundProcessingError = session?.processing?.processing_error ?? null;

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Participant</span>
        <span className="muted">
          Session {sessionId.slice(0, 8)}… · {session?.workflow_mode ?? "—"}
          {sessionTerminated ? " · ended" : ""}
          {!session?.optimization_allowed ? " · runs gated" : ""}
        </span>
        <div style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
          <StatusChip
            label="Model / API key"
            status={modelKeyStatus}
            icon={modelKeyIcon}
            title={
              modelKeyStatus === "ok"
                ? "API key is set for this session"
                : modelKeyStatus === "warn"
                  ? "No API key on the session - add one or ask the researcher"
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
            aiPending={aiPending}
            invokeModel={invokeModel}
            editMode={editMode}
            busy={busy}
            chatLocked={chatLocked}
            chatInput={chatInput}
            chatAttentionKey={chatAttentionKey}
            fileRef={fileRef}
            onInvokeModelChange={onInvokeModelChange}
            onChatInputChange={onChatInputChange}
            onSendChat={onSendChat}
            onSimulateUpload={onSimulateUpload}
          />
        </section>

        {chatFirstMode && <div className="chat-first-spacer" aria-hidden="true" />}

        {!chatFirstMode && (
          <ConfigPanel
            className={editMode === "config" || editMode === "definition" ? "panel" : panelClass("config")}
            configText={configText}
            problemBrief={problemBrief}
            editMode={editMode}
            busy={busy}
            syncingProblemConfig={syncingProblemConfig}
            backgroundBriefPending={backgroundBriefPending}
            backgroundConfigPending={backgroundConfigPending}
            backgroundProcessingError={backgroundProcessingError}
            sessionTerminated={sessionTerminated}
            onConfigTextChange={onConfigTextChange}
            onProblemBriefChange={onProblemBriefChange}
            onSetEditMode={onSetEditMode}
            onSaveConfig={onSaveConfig}
            onSaveDefinitionEdit={onSaveDefinitionEdit}
            onCancelDefinitionEdit={onCancelDefinitionEdit}
            onEnsureDefinitionEditing={onEnsureDefinitionEditing}
            isDefinitionDirty={isDefinitionDirty}
            onSyncProblemConfig={onSyncProblemConfig}
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
            sessionTerminated={sessionTerminated}
            onSetActiveRun={onSetActiveRun}
            onScheduleTextChange={onScheduleTextChange}
            onSetEditMode={onSetEditMode}
            onRunOptimize={onRunOptimize}
            onCancelOptimize={onCancelOptimize}
            onRunEvaluateEdited={onRunEvaluateEdited}
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
    </div>
  );
}
