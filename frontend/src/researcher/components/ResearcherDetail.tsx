import { useEffect, useState } from "react";

import { displayRunNumber, type Message, type RunResult, type Session } from "@shared/api";
import { ChatPanel } from "@shared/chat/ChatPanel";
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
  onPushGeminiKey: () => void | Promise<void>;
  onExportJson: () => void | Promise<void>;
  onTerminate: () => void | Promise<void>;
  onRemoveSession: () => void | Promise<void>;
  onSendSteer: () => void | Promise<void>;
  onRemoveRun: (run: RunResult) => void | Promise<void>;
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
  onPushGeminiKey,
  onExportJson,
  onTerminate,
  onRemoveSession,
  onSendSteer,
  onRemoveRun,
}: ResearcherDetailProps) {
  const [showModelDialog, setShowModelDialog] = useState(false);
  const [participantNumberDraft, setParticipantNumberDraft] = useState("");

  useEffect(() => {
    setShowModelDialog(false);
  }, [detail?.id]);

  useEffect(() => {
    setParticipantNumberDraft(detail?.participant_number ?? "");
  }, [detail?.id, detail?.participant_number]);

  return (
    <main className="detail">
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
            <button type="button" disabled={busy} onClick={() => void onTerminate()}>
              Terminate session
            </button>
            <button type="button" disabled={busy} onClick={() => void onRemoveSession()}>
              Delete session
            </button>
          </div>

          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <label className="muted">
              Workflow
              <select
                value={detail.workflow_mode}
                onChange={(e) => void onPatchSession({ workflow_mode: e.target.value })}
                style={{ display: "block", marginTop: "0.2rem" }}
              >
                <option value="agile">agile</option>
                <option value="waterfall">waterfall</option>
              </select>
            </label>
            <label className="muted">
              Participant number
              <div style={{ display: "flex", gap: "0.35rem", marginTop: "0.2rem" }}>
                <input
                  type="text"
                  value={participantNumberDraft}
                  disabled={busy}
                  onChange={(e) => setParticipantNumberDraft(e.target.value)}
                  placeholder="e.g. 007"
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void onPatchSession({ participant_number: participantNumberDraft })}
                >
                  Save
                </button>
              </div>
            </label>
            <label className="muted">
              <input
                type="checkbox"
                checked={detail.optimization_allowed}
                onChange={(e) => void onPatchSession({ optimization_allowed: e.target.checked })}
              />{" "}
              Allow optimization runs
            </label>
            <button type="button" disabled={busy} onClick={() => void onPushParticipantStarterPanel()}>
              Push starter problem config
            </button>
            <label className="muted">
              <input
                type="checkbox"
                checked={getOnlyActiveTerms(detail.panel_config)}
                disabled={busy}
                onChange={(e) => void onSetOnlyActiveTerms(e.target.checked)}
              />{" "}
              Only score explicitly listed objectives
            </label>
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
              messages={
                <MessageBubbleList
                  messages={messages}
                  getBubbleClassName={() => "bubble assistant"}
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
                      {new Date(run.created_at).toLocaleString()}
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
