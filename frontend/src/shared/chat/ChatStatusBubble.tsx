import type { ReactNode } from "react";
import { ChatBubbleTemplate, type ChatBubbleTone } from "./ChatBubbleTemplate";

type ChatStatusBubbleProps = {
  heading?: ReactNode;
  tone?: ChatBubbleTone;
  children: ReactNode;
};

export function ChatStatusBubble({ heading = "assistant", tone = "info", children }: ChatStatusBubbleProps) {
  return (
    <ChatBubbleTemplate
      roleVariant="assistant"
      tone={tone}
      heading={<strong>{heading}</strong>}
      body={<div className="bubble-markdown">{children}</div>}
    />
  );
}

