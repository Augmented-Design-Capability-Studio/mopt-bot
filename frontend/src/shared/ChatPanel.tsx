import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";

/** Enter sends, Shift+Enter newline — used only by {@link ChatComposer} in this module. */
function onChatSendKeyDown(
  e: ReactKeyboardEvent<HTMLTextAreaElement>,
  onSend: () => void,
  options?: { disabled?: boolean },
): void {
  if (e.key !== "Enter" || e.shiftKey) return;
  if (options?.disabled) return;
  e.preventDefault();
  onSend();
}

export type ChatComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void | Promise<void>;
  /** Disables Send, blocks Enter-to-send, and disables textarea if `textareaDisabled` omitted */
  sendDisabled: boolean;
  sendLabel: string;
  placeholder: string;
  /** Extra class on the input row (e.g. `chat-input-locked`) */
  inputRowClassName?: string;
  /** When set, overrides disabled state on the textarea alone (e.g. allow typing while busy) */
  textareaDisabled?: boolean;
  textareaStyle?: CSSProperties;
};

/**
 * Shared textarea + Send row: Enter sends, Shift+Enter newline.
 */
export function ChatComposer({
  value,
  onChange,
  onSend,
  sendDisabled,
  sendLabel,
  placeholder,
  inputRowClassName,
  textareaDisabled,
  textareaStyle,
}: ChatComposerProps) {
  const taDisabled = textareaDisabled ?? sendDisabled;
  return (
    <div className={`chat-input-row${inputRowClassName ? ` ${inputRowClassName}` : ""}`}>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) =>
          onChatSendKeyDown(e, () => void onSend(), { disabled: sendDisabled })
        }
        placeholder={placeholder}
        disabled={taDisabled}
        style={textareaStyle}
      />
      <button type="button" disabled={sendDisabled} onClick={() => void onSend()}>
        {sendLabel}
      </button>
    </div>
  );
}

/** Shown while the participant is waiting for a model reply (invoke model on). */
export function ChatAiPendingBubble() {
  return (
    <div className="bubble assistant chat-pending-ai" aria-live="polite">
      <strong>assistant</strong>
      <div className="chat-pending-wrap">
        <span className="chat-spinner" role="status" aria-label="Loading model response" />
        <span className="muted">Thinking…</span>
      </div>
    </div>
  );
}

export type ChatPanelProps = {
  title: string;
  /** Message bubbles (or any content) inside `.chat-log` */
  messages: ReactNode;
  logAriaLive?: "polite" | "assertive" | "off";
  logStyle?: CSSProperties;
  /** Inserted after the log, before the composer (e.g. participant “ask model” block) */
  betweenLogAndComposer?: ReactNode;
  /** Inserted after the composer (e.g. upload row) */
  footer?: ReactNode;
  composer: ChatComposerProps;
};

/**
 * Shared chat shell: panel header + body, scrollable log, optional slots, then {@link ChatComposer}.
 */
export function ChatPanel({
  title,
  messages,
  logAriaLive = "polite",
  logStyle,
  betweenLogAndComposer,
  footer,
  composer,
}: ChatPanelProps) {
  return (
    <>
      <div className="panel-header">{title}</div>
      <div className="panel-body">
        <div className="chat-log" aria-live={logAriaLive} style={logStyle}>
          {messages}
        </div>
        {betweenLogAndComposer}
        <ChatComposer {...composer} />
        {footer}
      </div>
    </>
  );
}
