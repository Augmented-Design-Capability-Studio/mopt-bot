import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

/** Enter sends, Shift+Enter newline - used only by {@link ChatComposer}. */
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
  /** Disables Send, blocks Enter-to-send, and disables textarea if `textareaDisabled` omitted. */
  sendDisabled: boolean;
  sendLabel: string;
  placeholder: string;
  /** Extra class on the input row (for example `chat-input-locked`). */
  inputRowClassName?: string;
  /** When set, overrides disabled state on the textarea alone. */
  textareaDisabled?: boolean;
  textareaStyle?: CSSProperties;
  /** When this key changes, move focus to the composer and show a subtle pulse. */
  attentionKey?: string | number;
};

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
  attentionKey,
}: ChatComposerProps) {
  const textareaIsDisabled = textareaDisabled ?? sendDisabled;
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [attentionPulse, setAttentionPulse] = useState(false);

  useEffect(() => {
    if (attentionKey == null || textareaIsDisabled) return;
    const textarea = textareaRef.current;
    if (!textarea) return;

    const active = document.activeElement;
    if (
      active instanceof HTMLElement &&
      active !== textarea &&
      (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable)
    ) {
      return;
    }

    textarea.focus();
    setAttentionPulse(true);
    const timeoutId = window.setTimeout(() => setAttentionPulse(false), 1600);
    return () => window.clearTimeout(timeoutId);
  }, [attentionKey, textareaIsDisabled]);

  return (
    <div
      className={`chat-input-row${inputRowClassName ? ` ${inputRowClassName}` : ""}${attentionPulse ? " chat-attention-pulse" : ""}`}
    >
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => onChatSendKeyDown(e, () => void onSend(), { disabled: sendDisabled })}
        placeholder={placeholder}
        disabled={textareaIsDisabled}
        style={textareaStyle}
      />
      <button type="button" disabled={sendDisabled} onClick={() => void onSend()}>
        {sendLabel}
      </button>
    </div>
  );
}

/** Shown while the participant is waiting for a model reply. */
export function ChatAiPendingBubble() {
  return (
    <div className="bubble assistant chat-pending-ai" aria-live="polite">
      <strong>assistant</strong>
      <div className="chat-pending-wrap">
        <span className="chat-spinner" role="status" aria-label="Loading model response" />
        <span className="muted">Thinking...</span>
      </div>
    </div>
  );
}

export type ChatPanelProps = {
  title: string;
  messages: ReactNode;
  logAriaLive?: "polite" | "assertive" | "off";
  logStyle?: CSSProperties;
  betweenLogAndComposer?: ReactNode;
  footer?: ReactNode;
  composer: ChatComposerProps;
};

/**
 * Shared chat shell: panel header + body, scrollable log, optional slots, then
 * the composer row.
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
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  return (
    <>
      <div className="panel-header">{title}</div>
      <div className="panel-body">
        <div className="chat-log" aria-live={logAriaLive} style={logStyle}>
          {messages}
          <div ref={logEndRef} />
        </div>
        {betweenLogAndComposer}
        <ChatComposer {...composer} />
        {footer}
      </div>
    </>
  );
}
