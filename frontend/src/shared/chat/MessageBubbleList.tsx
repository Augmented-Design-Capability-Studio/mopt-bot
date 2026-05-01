import { memo, type ReactNode } from "react";

import type { Message } from "@shared/api";
import { ChatBubbleTemplate, type ChatBubbleMode, type ChatBubbleRoleVariant } from "./ChatBubbleTemplate";

export function messageBubbleKey(message: Message, index: number): number | string {
  return message.id < 0 ? `tmp-${message.id}-${index}` : message.id;
}

const defaultRoleVariant = (message: Message): ChatBubbleRoleVariant =>
  message.role === "user" ? "user" : "assistant";
const defaultRenderHeading = (message: Message) => <strong>{message.role}</strong>;

type MessageBubbleListProps = {
  messages: Message[];
  mode?: ChatBubbleMode;
  getRoleVariant?: (message: Message) => ChatBubbleRoleVariant;
  getBubbleClassName?: (message: Message) => string | undefined;
  renderHeading?: (message: Message) => ReactNode;
  renderMessageMarkdown?: (message: Message) => string;
  renderSupplemental?: (message: Message) => ReactNode;
  afterMessages?: ReactNode;
};

/**
 * Shared message renderer so participant and researcher views keep bubble
 * structure and optimistic-key handling in one place.
 */
export const MessageBubbleList = memo(function MessageBubbleList({
  messages,
  mode = "full",
  getRoleVariant = defaultRoleVariant,
  getBubbleClassName,
  renderHeading = defaultRenderHeading,
  renderMessageMarkdown = (message) => message.content,
  renderSupplemental,
  afterMessages,
}: MessageBubbleListProps) {
  return (
    <>
      {messages.map((message, index) => (
        <ChatBubbleTemplate
          key={messageBubbleKey(message, index)}
          roleVariant={getRoleVariant(message)}
          mode={mode}
          className={getBubbleClassName?.(message)}
          heading={renderHeading(message)}
          markdown={renderMessageMarkdown(message)}
          trailing={renderSupplemental?.(message)}
        />
      ))}
      {afterMessages}
    </>
  );
});
