import type { RefObject } from "react";

import type { Message, RunResult, Session } from "@shared/api";

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
  scheduleText: string;
  editMode: EditMode;
  busy: boolean;
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
  onScheduleTextChange: (value: string) => void;
  onSetActiveRun: (index: number) => void;
  onSetEditMode: (mode: EditMode) => void;
  onSetShowModelDialog: (open: boolean) => void;
  onModelNameChange: (value: string) => void;
  onModelKeyChange: (value: string) => void;
  onLeaveSession: () => void;
  onStartSession: () => void | Promise<void>;
  onSendChat: () => void | Promise<void>;
  onSimulateUpload: () => void | Promise<void>;
  onSaveConfig: () => void | Promise<void>;
  onRunOptimize: () => void | Promise<void>;
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
  scheduleText,
  editMode,
  busy,
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
  onRunOptimize,
  onRunEvaluateEdited,
  onCloseModelDialog,
  onSaveModelSettings,
}: ParticipantShellProps) {
  const panelClass = (name: EditMode) => (editMode !== "none" && editMode !== name ? "panel panel-locked" : "panel");

  const sessionTerminated = session?.status === "terminated";
  const chatLocked = sessionTerminated;
  const modelKeyStatus = session == null ? "neutral" : session.gemini_key_configured ? "ok" : "warn";
  const modelKeyIcon = modelKeyStatus === "ok" ? "✓" : modelKeyStatus === "warn" ? "⚠" : "○";

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
          <button
            type="button"
            className={`btn-model-key status-${modelKeyStatus}`}
            title={
              modelKeyStatus === "ok"
                ? "API key is set for this session"
                : modelKeyStatus === "warn"
                  ? "No API key on the session - add one or ask the researcher"
                  : "Session loading"
            }
            onClick={() => onSetShowModelDialog(true)}
          >
            <span className="model-key-icon" aria-hidden>
              {modelKeyIcon}
            </span>
            Model / API key
          </button>
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
      <div className="grid-3">
        <section className={panelClass("none")}>
          <ChatSection
            messages={messages}
            aiPending={aiPending}
            invokeModel={invokeModel}
            editMode={editMode}
            busy={busy}
            chatLocked={chatLocked}
            chatInput={chatInput}
            fileRef={fileRef}
            onInvokeModelChange={onInvokeModelChange}
            onChatInputChange={onChatInputChange}
            onSendChat={onSendChat}
            onSimulateUpload={onSimulateUpload}
          />
        </section>

        <ConfigPanel
          className={editMode === "config" ? "panel" : panelClass("config")}
          configText={configText}
          editMode={editMode}
          busy={busy}
          sessionTerminated={sessionTerminated}
          onConfigTextChange={onConfigTextChange}
          onSetEditMode={onSetEditMode}
          onSaveConfig={onSaveConfig}
        />

        <ResultsPanel
          className={editMode === "results" ? "panel" : panelClass("results")}
          runs={runs}
          activeRun={activeRun}
          currentRun={currentRun}
          scheduleText={scheduleText}
          editMode={editMode}
          busy={busy}
          optimizing={optimizing}
          configText={configText}
          session={session}
          sessionTerminated={sessionTerminated}
          onSetActiveRun={onSetActiveRun}
          onScheduleTextChange={onScheduleTextChange}
          onSetEditMode={onSetEditMode}
          onRunOptimize={onRunOptimize}
          onRunEvaluateEdited={onRunEvaluateEdited}
        />
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
