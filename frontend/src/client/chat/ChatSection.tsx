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
}: ChatSectionProps) {
  const scrollTriggerKey = `${messages.length}-${messages[messages.length - 1]?.id ?? ""}-${aiPending}`;
  const uploadDisplayText = "Uploaded file(s):";
  return (
    <ChatPanel
      title="Chat & upload"
      logDataAnchor="chat-log"
      messages={
        <MessageBubbleList
          messages={messages}
          renderMessageMarkdown={(message) =>
            parseFilenamesFromSimulatedUploadMessage(message.content) ? uploadDisplayText : message.content
          }
          renderSupplemental={(message) => {
            const fileNames = parseFilenamesFromSimulatedUploadMessage(message.content);
            if (!fileNames || fileNames.length === 0) return null;
            return <UploadFileChips fileNames={fileNames} problemId={problemId} className="chat-upload-chips--bubble" />;
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
