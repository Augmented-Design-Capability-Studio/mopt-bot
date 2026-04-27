import type { RefObject } from "react";

import type { Message } from "@shared/api";
import { buildProblemFileUrl } from "@shared/api";
import { ChatAiPendingBubble, ChatPanel } from "@shared/chat/ChatPanel";
import { MessageBubbleList } from "@shared/chat/MessageBubbleList";

import type { EditMode } from "../lib/participantTypes";

type ChatSectionProps = {
  messages: Message[];
  aiPending: boolean;
  invokeModel: boolean;
  editMode: EditMode;
  chatBusy: boolean;
  chatLocked: boolean;
  chatInput: string;
  chatAttentionKey?: string | number;
  fileRef: RefObject<HTMLInputElement>;
  simulatedUploadChips: string[];
  problemId?: string;
  onInvokeModelChange: (value: boolean) => void;
  onChatInputChange: (value: string) => void;
  onSendChat: () => void | Promise<void>;
  onSimulateUpload: (fileNames: string[]) => void | Promise<void>;
  onRemoveSimulatedUploadChip: (fileName: string) => void;
};

export function ChatSection({
  messages,
  aiPending,
  invokeModel,
  editMode,
  chatBusy,
  chatLocked,
  chatInput,
  chatAttentionKey,
  fileRef,
  simulatedUploadChips,
  problemId,
  onInvokeModelChange,
  onChatInputChange,
  onSendChat,
  onSimulateUpload,
  onRemoveSimulatedUploadChip,
}: ChatSectionProps) {
  const scrollTriggerKey = `${messages.length}-${messages[messages.length - 1]?.id ?? ""}-${aiPending}`;
  return (
    <ChatPanel
      title="Chat & upload"
      messages={<MessageBubbleList messages={messages} afterMessages={aiPending ? <ChatAiPendingBubble /> : null} />}
      scrollTriggerKey={scrollTriggerKey}
      betweenLogAndComposer={
        <details className="muted chat-model-details" {...(chatLocked ? { open: false } : {})}>
          <summary style={chatLocked ? { pointerEvents: "none", opacity: 0.55 } : undefined}>
            Ask model (requires API key). <span className="chat-model-state">{invokeModel ? "On" : "Off"}</span>
          </summary>
          <div className="chat-model-check-wrap">
            <input
              type="checkbox"
              checked={invokeModel}
              onChange={(e) => onInvokeModelChange(e.target.checked)}
              aria-label="Ask model (requires API key)."
              disabled={chatLocked}
            />
          </div>
        </details>
      }
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
          <div className="chat-upload-chips" aria-label="Simulated uploads">
            {simulatedUploadChips.map((name) => {
              const downloadUrl = problemId ? buildProblemFileUrl(problemId, name) : null;
              return (
                <span key={name} className="chat-upload-chip" title={name}>
                  {downloadUrl ? (
                    <a
                      href={downloadUrl}
                      download={name}
                      className="chat-upload-chip-name chat-upload-chip-link"
                      title={`Download ${name}`}
                    >
                      {name}
                    </a>
                  ) : (
                    <span className="chat-upload-chip-name">{name}</span>
                  )}
                  <button
                    type="button"
                    className="chat-upload-chip-remove"
                    aria-label={`Remove ${name} from upload list`}
                    disabled={editMode !== "none" || chatLocked}
                    onClick={() => onRemoveSimulatedUploadChip(name)}
                  >
                    ×
                  </button>
                </span>
              );
            })}
          </div>
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
