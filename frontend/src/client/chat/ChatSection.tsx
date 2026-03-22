import type { RefObject } from "react";

import type { Message } from "@shared/api";
import { ChatAiPendingBubble, ChatPanel } from "@shared/chat/ChatPanel";
import { MessageBubbleList } from "@shared/chat/MessageBubbleList";

import type { EditMode } from "../lib/participantTypes";

type ChatSectionProps = {
  messages: Message[];
  aiPending: boolean;
  invokeModel: boolean;
  editMode: EditMode;
  busy: boolean;
  chatLocked: boolean;
  chatInput: string;
  fileRef: RefObject<HTMLInputElement>;
  onInvokeModelChange: (value: boolean) => void;
  onChatInputChange: (value: string) => void;
  onSendChat: () => void | Promise<void>;
  onSimulateUpload: () => void | Promise<void>;
};

export function ChatSection({
  messages,
  aiPending,
  invokeModel,
  editMode,
  busy,
  chatLocked,
  chatInput,
  fileRef,
  onInvokeModelChange,
  onChatInputChange,
  onSendChat,
  onSimulateUpload,
}: ChatSectionProps) {
  return (
    <ChatPanel
      title="Chat & upload"
      messages={<MessageBubbleList messages={messages} afterMessages={aiPending && <ChatAiPendingBubble />} />}
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
        <div>
          <input ref={fileRef} type="file" hidden onChange={() => void onSimulateUpload()} />
          <button
            type="button"
            disabled={editMode !== "none" || chatLocked}
            onClick={() => fileRef.current?.click()}
          >
            Upload file(s)...
          </button>
        </div>
      }
      composer={{
        value: chatInput,
        onChange: onChatInputChange,
        onSend: onSendChat,
        sendDisabled: busy || editMode !== "none" || chatLocked,
        textareaDisabled: busy || editMode !== "none" || chatLocked,
        sendLabel: "Send",
        placeholder: "Message... (Enter to send, Shift+Enter for newline)",
        inputRowClassName: chatLocked ? "chat-input-locked" : undefined,
      }}
    />
  );
}
