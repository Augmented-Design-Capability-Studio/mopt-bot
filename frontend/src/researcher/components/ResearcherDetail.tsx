import { useEffect, useMemo, useState } from "react";

import {
  displayRunNumber,
  type Message,
  type RunResult,
  type Session,
  type TestProblemMeta,
  TUTORIAL_STEP_IDS,
  type TutorialStepId,
} from "@shared/api";
import { ChatPanel } from "@shared/chat/ChatPanel";
import { parseServerDate } from "@shared/dateTime";
import { MessageBubbleList } from "@shared/chat/MessageBubbleList";
import { BackendConnectionControl } from "@shared/status/BackendConnectionControl";
import { StatusChip } from "@shared/status/StatusChip";

import { ResearcherModelKeyDialog } from "./ResearcherModelKeyDialog";

type ResearcherDetailProps = {
  savedToken: string;
  selectedId: string | null;
  detail: Session | null;
  messages: Message[];
  runs: RunResult[];
  steerText: string;
  geminiKey: string;
  geminiModel: string;
  busy: boolean;
  pushKeySuccess: string | null;
  getOnlyActiveTerms: (panel: Session["panel_config"]) => boolean;
  onSteerTextChange: (value: string) => void;
  onGeminiKeyChange: (value: string) => void;
  onGeminiModelChange: (value: string) => void;
  onClearPushKeySuccess: () => void;
  onPatchSession: (patch: Record<string, unknown>) => Promise<boolean>;
  onSetOnlyActiveTerms: (enabled: boolean) => void | Promise<void>;
  onPushParticipantStarterPanel: () => void | Promise<void>;
  onPushDummyParticipantUpload: () => void | Promise<void>;
  onPushGeminiKey: () => void | Promise<void>;
  onExportJson: () => void | Promise<void>;
  onCopySessionLink: () => void | Promise<void>;
  onResetSession: () => void | Promise<void>;
  onTerminate: () => void | Promise<void>;
  onRemoveSession: () => void | Promise<void>;
  onSendSteer: () => void | Promise<void>;
  onRemoveRun: (run: RunResult) => void | Promise<void>;
  testProblemsMeta: TestProblemMeta[];
};

export function ResearcherDetail({
  savedToken,
  selectedId,
  detail,
  messages,
  runs,
  steerText,
  geminiKey,
  geminiModel,
  busy,
  pushKeySuccess,
  getOnlyActiveTerms,
  onSteerTextChange,
  onGeminiKeyChange,
  onGeminiModelChange,
  onClearPushKeySuccess,
  onPatchSession,
  onSetOnlyActiveTerms,
  onPushParticipantStarterPanel,
  onPushDummyParticipantUpload,
  onPushGeminiKey,
  onExportJson,
  onCopySessionLink,
  onResetSession,
  onTerminate,
  onRemoveSession,
  onSendSteer,
  onRemoveRun,
  testProblemsMeta,
}: ResearcherDetailProps) {
  const tutorialStepLabels: Record<TutorialStepId, string> = {
    "chat-info": "Step 1 - Start in chat",
    "upload-files": "Step 2 - Upload files",
    "inspect-definition": "Step 3 - Inspect Definition",
    "update-definition": "Step 4 - Update definition",
    "inspect-config": "Step 5 - Inspect Problem Config",
    "first-run": "Step 6 - Trigger first run",
    "update-config": "Step 7 - Edit problem config",
    "second-run": "Step 8 - Run again",
  };
  const [showModelDialog, setShowModelDialog] = useState(false);
  const [participantNumberDraft, setParticipantNumberDraft] = useState("");

  useEffect(() => {
    setShowModelDialog(false);
  }, [detail?.id]);

  useEffect(() => {
    setParticipantNumberDraft(detail?.participant_number ?? "");
  }, [detail?.id, detail?.participant_number]);

  const workflowClass =
    detail?.workflow_mode === "agile"
      ? "detail--wf-agile"
      : detail?.workflow_mode === "waterfall"
        ? "detail--wf-waterfall"
        : detail?.workflow_mode === "demo"
          ? "detail--wf-demo"
          : "";
  const participantNumberChanged = participantNumberDraft !== (detail?.participant_number ?? "");

  /** Stored researcher permit — participant mutations re-sync `optimization_allowed` from intrinsic readiness. */
  const runButtonPermitOn = useMemo(() => {
    if (!detail) return false;
    return !detail.optimization_runs_blocked_by_researcher && detail.optimization_allowed;
  }, [detail]);

  return (
    <main className={workflowClass ? `detail ${workflowClass}` : "detail"}>
      {!savedToken.trim() && (
        <p className="muted">
          Paste <code>MOPT_RESEARCHER_SECRET</code> from your server <code>.env</code>, then click Save token.
        </p>
      )}
      {savedToken.trim() && !selectedId && <p className="muted">Select a session.</p>}
      {savedToken.trim() && selectedId && !detail && <p className="muted">Loading session detail...</p>}
      {selectedId && detail && (
        <>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
            <span className="mono">{detail.id}</span>
            <button type="button" disabled={busy} onClick={() => void onExportJson()}>
              Export JSON
            </button>
            <button type="button" disabled={busy} onClick={() => void onCopySessionLink()}>
              Copy session link
            </button>
            <button type="button" disabled={busy} onClick={() => void onResetSession()}>
              Reset session
            </button>
            <button type="button" disabled={busy} onClick={() => void onTerminate()}>
              Terminate session
            </button>
            <button type="button" disabled={busy} onClick={() => void onRemoveSession()}>
              Delete session
            </button>
          </div>

          <div className="researcher-controls-grid">
            <label className="muted researcher-control-group">
              Workflow
              <select
                value={detail.workflow_mode}
                onChange={(e) => void onPatchSession({ workflow_mode: e.target.value })}
                className="researcher-workflow-select"
              >
                <option value="agile">agile</option>
                <option value="waterfall">waterfall</option>
                <option value="demo">demo</option>
              </select>
            </label>

            <label className="muted researcher-control-group">
              Test problem
              <select
                value={detail.test_problem_id ?? "vrptw"}
                title="Changing mid-session can mix incompatible run artifacts; prefer new sessions when possible."
                onChange={(e) => {
                  const next = e.target.value;
                  if (
                    runs.length > 0 &&
                    next !== (detail.test_problem_id ?? "vrptw") &&
                    !window.confirm(
                      "This session already has optimization runs. Switching the test problem can mix incompatible result shapes in history. Continue?",
                    )
                  ) {
                    return;
                  }
                  void onPatchSession({ test_problem_id: next });
                }}
                className="researcher-workflow-select"
              >
                {testProblemsMeta.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label} ({p.id})
                  </option>
                ))}
              </select>
            </label>

            <label className="muted researcher-control-group">
              Participant number
              <div style={{ display: "flex", gap: "0.35rem" }}>
                <input
                  type="text"
                  value={participantNumberDraft}
                  disabled={busy}
                  onChange={(e) => setParticipantNumberDraft(e.target.value)}
                  placeholder="e.g. 007"
                  className="researcher-control-input"
                />
                <button
                  type="button"
                  disabled={busy || !participantNumberChanged}
                  className={
                    participantNumberChanged
                      ? "researcher-save-button researcher-save-button--dirty"
                      : "researcher-save-button"
                  }
                  onClick={() => void onPatchSession({ participant_number: participantNumberDraft })}
                >
                  Save
                </button>
              </div>
            </label>

            <div className="muted researcher-control-group">
              <span>More actions & settings</span>
              <div style={{ display: "flex", gap: "0.75rem", alignItems: "flex-end", flexWrap: "wrap" }}>
                <div className="researcher-action-button-column">
                  <button type="button" disabled={busy} onClick={() => void onPushParticipantStarterPanel()}>
                    Push starter problem config
                  </button>
                  <button type="button" disabled={busy} onClick={() => void onPushDummyParticipantUpload()}>
                    Push dummy files
                  </button>
                </div>
                <div className="researcher-toggle-column">
                  <label title="Sets the stored run permit on the session. Uncheck to block runs. Participant definition/chat updates re-align the permit with intrinsic readiness (waterfall open questions, etc.); check again to override until the next participant update.">
                    <input
                      type="checkbox"
                      checked={runButtonPermitOn}
                      onChange={(e) => {
                        const on = e.target.checked;
                        if (on) {
                          const hasOpenQuestions =
                            detail.workflow_mode === "waterfall" &&
                            detail.problem_brief.open_questions.some((q) => q.status === "open");
                          if (
                            hasOpenQuestions &&
                            !window.confirm(
                              "This session still has open questions in the problem definition. Enable the Run button anyway? The participant will be able to run optimization before those questions are answered.",
                            )
                          ) {
                            return;
                          }
                        }
                        void onPatchSession(
                          on
                            ? {
                                optimization_runs_blocked_by_researcher: false,
                                optimization_allowed: true,
                              }
                            : { optimization_runs_blocked_by_researcher: true },
                        );
                      }}
                    />{" "}
                    {"'Run' button available."}
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={getOnlyActiveTerms(detail.panel_config)}
                      disabled={busy}
                      onChange={(e) => void onSetOnlyActiveTerms(e.target.checked)}
                    />{" "}
                    Only score explicitly listed objectives
                  </label>
                  <label title="When enabled, the participant can see and replay tutorial bubbles for this session. If the participant dismisses, tutorial is turned off for this session. Progression is event-driven from participant actions.">
                    <input
                      type="checkbox"
                      checked={detail.participant_tutorial_enabled}
                      disabled={busy}
                      onChange={(e) =>
                        void onPatchSession(
                          e.target.checked
                            ? {
                                participant_tutorial_enabled: true,
                                tutorial_step_override: detail.tutorial_step_override ?? "chat-info",
                              }
                            : { participant_tutorial_enabled: false },
                        )
                      }
                    />{" "}
                    Show participant tutorial
                    <select
                      value={detail.tutorial_step_override ?? "chat-info"}
                      disabled={busy || !detail.participant_tutorial_enabled}
                      onChange={(e) =>
                        void onPatchSession({
                          tutorial_step_override: e.target.value,
                        })
                      }
                      className="researcher-workflow-select"
                      style={{ width: "8.5rem", minWidth: "8.5rem", marginLeft: "0.45rem" }}
                      title="Set current tutorial step. Selecting an earlier step rewinds tutorial tracking state only (chat/runs/config data are unchanged). Step 3 advances only after the participant explicitly clicks the Definition tab."
                    >
                      {TUTORIAL_STEP_IDS.map((stepId) => (
                        <option key={stepId} value={stepId}>
                          {tutorialStepLabels[stepId]}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>
            </div>
          </div>

          <p className="muted" style={{ fontSize: "0.8rem", margin: "0.25rem 0 0" }}>
            New participant sessions start with empty panels until you push this deliberately mediocre starter (sparse
            objectives and a weak search setup).
          </p>

          <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", alignItems: "center" }}>
            <StatusChip
              label="Participant model / API key"
              status={detail.gemini_key_configured ? "ok" : "warn"}
              icon={detail.gemini_key_configured ? "✓" : "⚠"}
              title={
                detail.gemini_key_configured
                  ? "The participant session already has a stored API key"
                  : "No API key is stored for this participant session yet"
              }
              onClick={() => setShowModelDialog(true)}
            />
            <BackendConnectionControl />
          </div>

          <section>
            <ChatPanel
              title="Chat (incl. steering)"
              logStyle={{ maxHeight: "240px" }}
              scrollTriggerKey={`${messages.length}-${messages[messages.length - 1]?.id ?? ""}`}
              messages={
                <MessageBubbleList
                  messages={messages}
                  mode="simplified"
                  getRoleVariant={(message) => {
                    if (message.role === "user") return "user";
                    if (message.role === "researcher" || !message.visible_to_participant) return "researcher-hidden";
                    return "assistant";
                  }}
                  getBubbleClassName={(message) =>
                    message.role === "researcher" || !message.visible_to_participant ? "bubble-researcher-hidden-note" : undefined
                  }
                  renderHeading={(message) => (
                    <strong>
                      {message.role}
                      {!message.visible_to_participant ? " (hidden from participant)" : ""}
                    </strong>
                  )}
                />
              }
              composer={{
                value: steerText,
                onChange: onSteerTextChange,
                onSend: onSendSteer,
                sendDisabled: busy,
                sendLabel: "Send steer",
                placeholder: "Steering note (participant does not see). Enter to send, Shift+Enter for newline.",
                textareaStyle: { minHeight: "2.5rem" },
              }}
            />
          </section>

          <ResearcherModelKeyDialog
            open={showModelDialog}
            configured={detail.gemini_key_configured}
            geminiKey={geminiKey}
            geminiModel={geminiModel}
            busy={busy}
            pushKeySuccess={pushKeySuccess}
            onGeminiKeyChange={(value) => {
              onGeminiKeyChange(value);
              onClearPushKeySuccess();
            }}
            onGeminiModelChange={onGeminiModelChange}
            onClose={() => setShowModelDialog(false)}
            onPush={onPushGeminiKey}
          />

          <section>
            <div className="panel-header">Runs</div>
            {runs.length === 0 ? (
              <div className="muted" style={{ padding: "0.45rem 0.2rem" }}>
                No runs yet.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem", marginTop: "0.4rem" }}>
                {runs.map((run) => (
                  <details key={run.id}>
                    <summary className="mono" style={{ cursor: "pointer" }}>
                      Run #{displayRunNumber(run)} · {run.run_type} · {run.ok ? "ok" : "error"} · cost {run.cost ?? "-"} ·{" "}
                      {parseServerDate(run.created_at).toLocaleString()}
                    </summary>
                    <div style={{ marginTop: "0.35rem" }}>
                      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "0.35rem" }}>
                        <button type="button" disabled={busy} onClick={() => void onRemoveRun(run)}>
                          Delete run
                        </button>
                      </div>
                      <pre
                        className="mono"
                        style={{ fontSize: "0.75rem", maxHeight: "240px", overflow: "auto", margin: 0 }}
                      >
                        {JSON.stringify(run, null, 2)}
                      </pre>
                    </div>
                  </details>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
