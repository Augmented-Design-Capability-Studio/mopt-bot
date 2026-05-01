import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export type ChatBubbleRoleVariant = "user" | "assistant" | "researcher-hidden";
export type ChatBubbleMode = "full" | "simplified";
export type ChatBubbleTone = "info" | "success" | "warning" | "error";

type ChatBubbleTemplateProps = {
  roleVariant: ChatBubbleRoleVariant;
  mode?: ChatBubbleMode;
  heading?: ReactNode;
  markdown?: string;
  tone?: ChatBubbleTone;
  spinnerLabel?: string;
  spinnerAriaLabel?: string;
  className?: string;
  body?: ReactNode;
  trailing?: ReactNode;
  ariaLive?: "polite" | "assertive" | "off";
};

export function ChatBubbleTemplate({
  roleVariant,
  mode = "full",
  heading,
  markdown,
  tone,
  spinnerLabel,
  spinnerAriaLabel = "Loading",
  className,
  body,
  trailing,
  ariaLive,
}: ChatBubbleTemplateProps) {
  const classes = [
    "bubble",
    roleVariant,
    "bubble-template",
    mode === "simplified" ? "bubble-template--simplified" : "bubble-template--full",
    tone ? `bubble-status bubble-status--${tone}` : null,
    className ?? null,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes} {...(ariaLive ? { "aria-live": ariaLive } : {})}>
      {heading ? <div className="bubble-template-heading">{heading}</div> : null}
      {spinnerLabel ? (
        <div className="chat-pending-wrap">
          <span className="chat-spinner" role="status" aria-label={spinnerAriaLabel} />
          <span className="muted">{spinnerLabel}</span>
        </div>
      ) : null}
      {markdown !== undefined ? (
        <div className="bubble-markdown">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener" />,
              code: ({ node: _node, className: codeClassName, children, ...props }) => (
                <code className={`mono ${codeClassName ?? ""}`.trim()} {...props}>
                  {children}
                </code>
              ),
            }}
          >
            {markdown}
          </ReactMarkdown>
        </div>
      ) : null}
      {body}
      {trailing ? <div className="bubble-template-trailing">{trailing}</div> : null}
    </div>
  );
}

