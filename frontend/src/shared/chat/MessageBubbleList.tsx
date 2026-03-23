import { memo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Message } from "@shared/api";

export function messageBubbleKey(message: Message, index: number): number | string {
  return message.id < 0 ? `tmp-${message.id}-${index}` : message.id;
}

const defaultGetBubbleClassName = (message: Message) =>
  `bubble ${message.role === "user" ? "user" : "assistant"}`;
const defaultRenderHeading = (message: Message) => <strong>{message.role}</strong>;

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
export const MessageBubbleList = memo(function MessageBubbleList({
  messages,
  getBubbleClassName = defaultGetBubbleClassName,
  renderHeading = defaultRenderHeading,
  afterMessages,
}: MessageBubbleListProps) {
  return (
    <>
      {messages.map((message, index) => (
        <div key={messageBubbleKey(message, index)} className={getBubbleClassName(message)}>
          {renderHeading(message)}
          <div className="bubble-markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener" />,
                code: ({ node: _node, className, children, ...props }) => (
                  <code className={`mono ${className ?? ""}`.trim()} {...props}>
                    {children}
                  </code>
                ),
              }}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        </div>
      ))}
      {afterMessages}
    </>
  );
});
