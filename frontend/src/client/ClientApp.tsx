import { LoginGate } from "./components/LoginGate";
import { ParticipantShell } from "./components/ParticipantShell";
import { useParticipantController } from "./hooks/useParticipantController";

export function ClientApp() {
  const controller = useParticipantController();

  if (!controller.authed) {
    return (
      <LoginGate
        token={controller.token}
        participantNumber={controller.participantNumber}
        pendingUrlSessionId={controller.pendingUrlSessionId}
        busy={controller.busy}
        error={controller.error}
        recentBusy={controller.recentBusy}
        recentRows={controller.recentRows}
        onTokenChange={controller.setToken}
        onParticipantNumberChange={controller.setParticipantNumber}
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
      participantLabel={controller.participantNumber}
      testProblemMeta={controller.testProblemMeta}
      session={controller.session}
      messages={controller.messages}
      runs={controller.runs}
      currentRun={controller.currentRun}
      activeRun={controller.activeRun}
      chatInput={controller.chatInput}
      invokeModel={controller.invokeModel}
      configText={controller.configText}
      problemBrief={controller.problemBrief}
      scheduleText={controller.scheduleText}
      editMode={controller.editMode}
      busy={controller.busy}
      chatBusy={controller.chatBusy}
      syncingProblemConfig={controller.syncingProblemConfig}
      participantOps={controller.participantOps}
      optimizing={controller.optimizing}
      error={controller.error}
      showModelDialog={controller.showModelDialog}
      modelName={controller.modelName}
      modelKey={controller.modelKey}
      aiPending={controller.aiPending}
      fileRef={controller.fileRef}
      simulatedUploadChips={controller.simulatedUploadChips}
      onChatInputChange={controller.setChatInput}
      onInvokeModelChange={controller.setInvokeModel}
      onConfigTextChange={controller.setConfigText}
      onProblemBriefChange={controller.setProblemBrief}
      onScheduleTextChange={controller.setScheduleText}
      onSetActiveRun={controller.setActiveRun}
      onSetEditMode={controller.setEditMode}
      onSetShowModelDialog={controller.setShowModelDialog}
      onModelNameChange={controller.setModelName}
      onModelKeyChange={controller.setModelKey}
      onLeaveSession={controller.leaveSession}
      onStartSession={controller.startSession}
      onSendChat={controller.sendChat}
      onRequestDefinitionCleanup={controller.requestDefinitionCleanup}
      onSimulateUpload={controller.simulateUpload}
      onRemoveSimulatedUploadChip={controller.onRemoveSimulatedUploadChip}
      onSaveConfig={controller.saveConfig}
      onSaveDefinitionEdit={controller.saveDefinitionEdit}
      onCancelDefinitionEdit={controller.cancelDefinitionEdit}
      onEnsureDefinitionEditing={controller.ensureDefinitionEditing}
      isDefinitionDirty={controller.isDefinitionDirty}
      onSyncProblemConfig={controller.syncProblemConfig}
      onEnterConfigEdit={controller.enterConfigEdit}
      onCancelConfigEdit={controller.cancelConfigEdit}
      onLoadConfigFromLastRun={controller.loadConfigFromLastRun}
      onBookmarkSnapshot={controller.bookmarkSnapshot}
      onRestoreFromSnapshot={controller.restoreFromSnapshot}
      onLoadSnapshots={controller.loadSnapshots}
      snapshots={controller.snapshots}
      snapshotsLoading={controller.snapshotsLoading}
      canLoadFromLastRun={controller.canLoadFromLastRun}
      canLoadFromSnapshot={controller.canLoadFromSnapshot}
      isConfigDirty={controller.isConfigDirty}
      onRunOptimize={controller.runOptimize}
      onCancelOptimize={controller.cancelOptimize}
      onRunEvaluateEdited={controller.runEvaluateEdited}
      onCloseModelDialog={controller.closeModelDialog}
      onSaveModelSettings={controller.saveModelSettings}
    />
  );
}
