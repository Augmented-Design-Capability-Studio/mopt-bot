import { useEffect } from "react";

import { LoginGate } from "./components/LoginGate";
import { ClientShell } from "./components/ClientShell";
import { useClientController } from "./hooks/useClientController";

export function ClientApp() {
  const controller = useClientController();

  useEffect(() => {
    const label = (controller.session?.participant_number ?? controller.participantNumber ?? "").trim();
    document.title = label ? `User #${label}` : "User";
  }, [controller.participantNumber, controller.session?.participant_number]);

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
    <ClientShell
      sessionId={controller.sessionId}
      participantLabel={controller.participantNumber}
      testProblemMeta={controller.testProblemMeta}
      session={controller.session}
      messages={controller.messages}
      runs={controller.runs}
      currentRun={controller.currentRun}
      activeRun={controller.activeRun}
      chatInput={controller.chatInput}
      configText={controller.configText}
      problemBrief={controller.problemBrief}
      hasUploadedData={controller.hasUploadedData}
      scheduleText={controller.scheduleText}
      editMode={controller.editMode}
      busy={controller.busy}
      chatBusy={controller.chatBusy}
      syncingProblemConfig={controller.syncingProblemConfig}
      clientOps={controller.clientOps}
      optimizing={controller.optimizing}
      error={controller.error}
      showModelDialog={controller.showModelDialog}
      modelName={controller.modelName}
      modelKey={controller.modelKey}
      aiPending={controller.aiPending}
      fileRef={controller.fileRef}
      simulatedUploadChips={controller.simulatedUploadChips}
      onChatInputChange={controller.setChatInput}
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
      onRequestOpenQuestionCleanup={controller.requestOpenQuestionCleanup}
      onSimulateUpload={controller.simulateUpload}
      onRemoveSimulatedUploadChip={controller.onRemoveSimulatedUploadChip}
      onSaveConfig={controller.saveConfig}
      onApplyTutorialConfigPatch={controller.applyTutorialConfigPatch}
      onSaveDefinitionEdit={controller.saveDefinitionEdit}
      onCancelDefinitionEdit={controller.cancelDefinitionEdit}
      onEnsureDefinitionEditing={controller.ensureDefinitionEditing}
      isDefinitionDirty={controller.isDefinitionDirty}
      onSyncProblemConfig={controller.syncProblemConfig}
      onRecoverGoalTerms={controller.recoverGoalTerms}
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
      onRevertEditedRun={controller.revertEditedRun}
      onExplainRun={controller.explainRun}
      onLoadConfigFromRun={controller.loadConfigFromRun}
      candidateRunIds={controller.candidateRunIds}
      onToggleCandidateRun={controller.toggleCandidateRun}
      onCloseModelDialog={controller.closeModelDialog}
      onSaveModelSettings={controller.saveModelSettings}
      onSetParticipantTutorialState={controller.setParticipantTutorialState}
    />
  );
}
