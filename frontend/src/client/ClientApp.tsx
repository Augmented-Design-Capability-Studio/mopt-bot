import { LoginGate } from "./components/LoginGate";
import { ParticipantShell } from "./components/ParticipantShell";
import { useParticipantController } from "./hooks/useParticipantController";

export function ClientApp() {
  const controller = useParticipantController();

  if (!controller.authed) {
    return (
      <LoginGate
        token={controller.token}
        busy={controller.busy}
        error={controller.error}
        recentBusy={controller.recentBusy}
        recentRows={controller.recentRows}
        onTokenChange={controller.setToken}
        onLogin={controller.login}
        onStartSession={controller.startSession}
        onRefreshRecentSessions={controller.refreshRecentSessionsList}
        onResumeSession={controller.resumePastSession}
        onForgetSession={controller.forgetRecentSession}
      />
    );
  }

  return (
    <ParticipantShell
      sessionId={controller.sessionId}
      session={controller.session}
      messages={controller.messages}
      runs={controller.runs}
      currentRun={controller.currentRun}
      activeRun={controller.activeRun}
      chatInput={controller.chatInput}
      invokeModel={controller.invokeModel}
      configText={controller.configText}
      scheduleText={controller.scheduleText}
      editMode={controller.editMode}
      busy={controller.busy}
      optimizing={controller.optimizing}
      error={controller.error}
      showModelDialog={controller.showModelDialog}
      modelName={controller.modelName}
      modelKey={controller.modelKey}
      aiPending={controller.aiPending}
      fileRef={controller.fileRef}
      onChatInputChange={controller.setChatInput}
      onInvokeModelChange={controller.setInvokeModel}
      onConfigTextChange={controller.setConfigText}
      onScheduleTextChange={controller.setScheduleText}
      onSetActiveRun={controller.setActiveRun}
      onSetEditMode={controller.setEditMode}
      onSetShowModelDialog={controller.setShowModelDialog}
      onModelNameChange={controller.setModelName}
      onModelKeyChange={controller.setModelKey}
      onLeaveSession={controller.leaveSession}
      onStartSession={controller.startSession}
      onSendChat={controller.sendChat}
      onSimulateUpload={controller.simulateUpload}
      onSaveConfig={controller.saveConfig}
      onRunOptimize={controller.runOptimize}
      onRunEvaluateEdited={controller.runEvaluateEdited}
      onCloseModelDialog={controller.closeModelDialog}
      onSaveModelSettings={controller.saveModelSettings}
    />
  );
}
