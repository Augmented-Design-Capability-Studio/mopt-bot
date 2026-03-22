import type { ReactNode } from "react";

import type { Message } from "@shared/api";

export function messageBubbleKey(message: Message, index: number): number | string {
  return message.id < 0 ? `tmp-${message.id}-${index}` : message.id;
}

type MessageBubbleListProps = {
  messages: Message[];
  getBubbleClassName?: (message: Message) => string;
  renderHeading?: (message: Message) => ReactNode;
  afterMessages?: ReactNode;
};

/**
 * Shared message renderer so participant and researcher views keep bubble
 * structure and optimistic-key handling in one place.
 */
export function MessageBubbleList({
  messages,
  getBubbleClassName = (message) => `bubble ${message.role === "user" ? "user" : "assistant"}`,
  renderHeading = (message) => <strong>{message.role}</strong>,
  afterMessages,
}: MessageBubbleListProps) {
  return (
    <>
      {messages.map((message, index) => (
        <div key={messageBubbleKey(message, index)} className={getBubbleClassName(message)}>
          {renderHeading(message)}
          <div>{message.content}</div>
        </div>
      ))}
      {afterMessages}
    </>
  );
}
