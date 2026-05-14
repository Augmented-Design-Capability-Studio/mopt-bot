import type { RefObject } from "react";

import type { Message } from "@shared/api";
import { ChatAiPendingBubble, ChatPanel } from "@shared/chat/ChatPanel";
import { ChatStatusBubble } from "@shared/chat/ChatStatusBubble";
import { MessageBubbleList } from "@shared/chat/MessageBubbleList";
import { UploadFileChips } from "@shared/chat/UploadFileChips";
import { parseFilenamesFromSimulatedUploadMessage } from "../lib/simulatedUploadMessage";

import type { EditMode } from "../lib/clientTypes";

type ChatSectionProps = {
  messages: Message[];
  aiPending: boolean;
  aiPendingLabel?: string;
  editMode: EditMode;
  chatBusy: boolean;
  chatLocked: boolean;
  chatInput: string;
  chatAttentionKey?: string | number;
  fileRef: RefObject<HTMLInputElement>;
  simulatedUploadChips: string[];
  problemId?: string;
  onChatInputChange: (value: string) => void;
  onSendChat: () => void | Promise<void>;
  onSimulateUpload: (fileNames: string[]) => void | Promise<void>;
  onRemoveSimulatedUploadChip: (fileName: string) => void;
  processingErrorMessage?: string | null;
  onRetrySync?: () => void | Promise<void>;
  retryBusy?: boolean;
  /** Click handler for the inline Run button rendered on run-invitation bubbles. */
  onRunOptimize?: () => void | Promise<void>;
  /** True when the participant can actually click Run right now (panel gate satisfied). */
  runReady?: boolean;
  /** Tooltip explaining why Run is unavailable; surfaced on the bubble button too. */
  runDisabledHint?: string;
};

export function ChatSection({
  messages,
  aiPending,
  aiPendingLabel,
  editMode,
  chatBusy,
  chatLocked,
  chatInput,
  chatAttentionKey,
  fileRef,
  simulatedUploadChips,
  problemId,
  onChatInputChange,
  onSendChat,
  onSimulateUpload,
  onRemoveSimulatedUploadChip,
  processingErrorMessage,
  onRetrySync,
  retryBusy = false,
  onRunOptimize,
  runReady = false,
  runDisabledHint,
}: ChatSectionProps) {
  const scrollTriggerKey = `${messages.length}-${messages[messages.length - 1]?.id ?? ""}-${aiPending}`;
  const uploadDisplayText = "Uploaded file(s):";
  // Identify the most-recent assistant run-invitation so only the freshest
  // invite carries an inline Run button. Older invites stay as text — the
  // panel Run button always works for catch-up clicks. The button is
  // hidden once *any* run message lands after the invitation: that means
  // a run has already been kicked off in response, so re-clicking would
  // be confusing if the participant scrolls back. ``run_pending`` covers
  // the "starting now..." placeholder; ``run`` covers the final summary;
  // ``panel`` covers the saved-config acknowledgement that doesn't apply
  // here but harmlessly fits the same "agent did something concrete
  // after the invite" semantic.
  let lastInvitationMessageId: number | null = null;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (!msg) continue;
    if (msg.meta?.is_run_invitation) {
      lastInvitationMessageId = msg.id;
      break;
    }
    if (msg.kind === "run" || msg.kind === "run_pending") {
      // A run already started or finished after the latest invitation —
      // don't surface the inline button anywhere. The participant uses
      // the panel Run button (or sends a new chat) for the next attempt.
      break;
    }
  }
  return (
    <ChatPanel
      title="Chat & upload"
      logDataAnchor="chat-log"
      messages={
        <MessageBubbleList
          messages={messages}
          getBubbleClassName={(message) =>
            message.role !== "user" && message.meta?.verifying
              ? "bubble--verifying"
              : undefined
          }
          renderMessageMarkdown={(message) =>
            parseFilenamesFromSimulatedUploadMessage(message.content) ? uploadDisplayText : message.content
          }
          renderSupplemental={(message) => {
            const fileNames = parseFilenamesFromSimulatedUploadMessage(message.content);
            const showRunButton =
              onRunOptimize !== undefined
              && message.id === lastInvitationMessageId
              && message.role !== "user";
            const uploadChips =
              fileNames && fileNames.length > 0
                ? <UploadFileChips fileNames={fileNames} problemId={problemId} className="chat-upload-chips--bubble" />
                : null;
            const runButton = showRunButton
              ? (
                <div className="chat-bubble-run">
                  <button
                    type="button"
                    className="chat-bubble-run__button"
                    disabled={!runReady}
                    title={runReady ? undefined : runDisabledHint}
                    onClick={() => void onRunOptimize?.()}
                  >
                    Run optimization
                  </button>
                </div>
              )
              : null;
            // "Verified after re-check" — surfaced when the backend's
            // pre-release probe re-asked the model this turn to reconcile a
            // commitment / gate mismatch. Tiny inline badge so participants
            // can see the system intervened without it dominating the reply.
            const verifiedBadge = message.meta?.verified_after_retry && message.role !== "user"
              ? (
                <div
                  className="chat-bubble-verified"
                  title="The system asked the agent to recheck its draft against the run-button gate before sending."
                >
                  <span aria-hidden="true">✓</span> Verified after re-check
                </div>
              )
              : null;
            if (!uploadChips && !runButton && !verifiedBadge) return null;
            return (
              <>
                {uploadChips}
                {runButton}
                {verifiedBadge}
              </>
            );
          }}
          afterMessages={
            <>
              {aiPending ? <ChatAiPendingBubble label={aiPendingLabel} /> : null}
              {processingErrorMessage ? (
                <ChatStatusBubble tone="error">
                  <p>{processingErrorMessage}</p>
                  {onRetrySync ? (
                    <button type="button" onClick={() => void onRetrySync()} disabled={retryBusy}>
                      {retryBusy ? "Retrying..." : "Retry sync"}
                    </button>
                  ) : null}
                </ChatStatusBubble>
              ) : null}
            </>
          }
        />
      }
      scrollTriggerKey={scrollTriggerKey}
      footer={
        <div className="chat-upload-footer">
          <input
            ref={fileRef}
            type="file"
            multiple
            hidden
            onChange={() => {
              const files = fileRef.current?.files;
              const names = files ? Array.from(files).map((f) => f.name) : [];
              if (fileRef.current) fileRef.current.value = "";
              if (names.length > 0) void onSimulateUpload(names);
            }}
          />
          <button
            type="button"
            data-tutorial-anchor="upload-button"
            disabled={editMode !== "none" || chatLocked}
            onClick={() => fileRef.current?.click()}
          >
            Upload file(s)...
          </button>
          <UploadFileChips
            fileNames={simulatedUploadChips}
            problemId={problemId}
            removable
            removeDisabled={editMode !== "none" || chatLocked}
            onRemove={onRemoveSimulatedUploadChip}
          />
        </div>
      }
      composer={{
        value: chatInput,
        onChange: onChatInputChange,
        onSend: onSendChat,
        sendDisabled: chatBusy || editMode !== "none" || chatLocked,
        textareaDisabled: chatBusy || editMode !== "none" || chatLocked,
        sendLabel: "Send",
        placeholder: "Message... (Enter to send, Shift+Enter for newline)",
        inputRowClassName: chatLocked ? "chat-input-locked" : undefined,
        attentionKey: chatAttentionKey,
        textareaDataAnchor: "chat-composer",
      }}
    />
  );
}
