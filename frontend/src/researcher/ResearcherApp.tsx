import { useEffect } from "react";

import { ResearcherDetail } from "./components/ResearcherDetail";
import { ResearcherHeader } from "./components/ResearcherHeader";
import { ResearcherSessionList } from "./components/ResearcherSessionList";
import { useResearcherController } from "./hooks/useResearcherController";

export function ResearcherApp() {
  const researcher = useResearcherController();

  useEffect(() => {
    const label = (researcher.detail?.participant_number ?? "").trim();
    document.title = label ? `Researcher #${label}` : "Researcher";
  }, [researcher.detail?.participant_number]);

  return (
    <div className="app-shell">
      <ResearcherHeader
        tokenInput={researcher.tokenInput}
        savedToken={researcher.savedToken}
        tokenDirty={researcher.tokenDirty}
        onTokenInputChange={researcher.setTokenInput}
        onSaveToken={researcher.saveToken}
        onRefreshList={researcher.refreshList}
      />
      {researcher.error && <div className="banner-warn">{researcher.error}</div>}
      {researcher.notice && <div className="muted">{researcher.notice}</div>}
      <div className="researcher-layout">
        <ResearcherSessionList
          sessions={researcher.sessions}
          selectedId={researcher.selected}
          selectedIds={researcher.selectedIds}
          onSelect={researcher.setSelected}
          onToggleSelect={researcher.toggleSessionSelected}
          onToggleSelectAll={researcher.toggleAllSessionsSelected}
          onRemoveSelected={researcher.removeSelectedSessions}
          onCreateSession={researcher.createNewSession}
          testProblemsMeta={researcher.testProblemsMeta}
          canCreateSession={Boolean(researcher.savedToken.trim())}
          busy={researcher.busy}
        />
        <ResearcherDetail
          savedToken={researcher.savedToken}
          selectedId={researcher.selected}
          detail={researcher.detail}
          messages={researcher.messages}
          runs={researcher.runs}
          steerText={researcher.steerText}
          geminiKey={researcher.geminiKey}
          geminiModel={researcher.geminiModel}
          busy={researcher.busy}
          pushKeySuccess={researcher.pushKeySuccess}
          getOnlyActiveTerms={researcher.getOnlyActiveTerms}
          onSteerTextChange={researcher.setSteerText}
          onGeminiKeyChange={researcher.setGeminiKey}
          onGeminiModelChange={researcher.setGeminiModel}
          onClearPushKeySuccess={() => researcher.setPushKeySuccess(null)}
          onPatchSession={researcher.patchSession}
          onSetOnlyActiveTerms={researcher.setOnlyActiveTerms}
          onPushParticipantStarterPanel={researcher.pushParticipantStarterPanel}
          onPushDummyParticipantUpload={researcher.pushDummyParticipantUpload}
          onPushGeminiKey={researcher.pushGeminiKey}
          onExportJson={researcher.exportJson}
          onCopySessionLink={researcher.copySessionLink}
          onResetSession={researcher.resetSession}
          onTerminate={researcher.terminate}
          onRemoveSession={researcher.removeSession}
          onSendSteer={researcher.sendSteer}
          onRemoveRun={researcher.removeRun}
          testProblemsMeta={researcher.testProblemsMeta}
        />
      </div>
    </div>
  );
}
