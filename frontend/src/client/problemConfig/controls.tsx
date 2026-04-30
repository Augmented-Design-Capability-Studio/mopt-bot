import { useEffect, useState, type CSSProperties, type ReactNode } from "react";

export type ActivateHint = {
  caretIndex?: number;
  focusSelector?: string;
};

/** Locked: button mimic (same as Definition read-only). Edit: real number input. */
export function ConfigNumberInput({
  editable,
  value,
  onValueChange,
  onActivate,
  focusKey,
  style,
  className,
  min,
  max,
  step,
}: {
  editable: boolean;
  value: number;
  onValueChange: (value: number | null) => void;
  onActivate?: (event?: ActivateHint) => void;
  focusKey?: string;
  style?: CSSProperties;
  className?: string;
  min?: number;
  max?: number;
  step?: number;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  useEffect(() => {
    if (draft === null) return;
    if (value.toString() === draft) setDraft(null);
  }, [draft, value]);
  if (!editable) {
    const label = Number.isNaN(value) ? "—" : String(value);
    return (
      <button
        type="button"
        className={`problem-config-field-mimic${className ? ` ${className}` : ""}`}
        title="Edit..."
        style={style}
        onClick={(e) => {
          onActivate?.({
            caretIndex: e.currentTarget.textContent?.length ?? 0,
            focusSelector: focusKey ? `[data-focus-key="${focusKey}"]` : undefined,
          });
        }}
        data-focus-key={focusKey}
      >
        {label}
      </button>
    );
  }
  const shown = draft ?? (Number.isNaN(value) ? "" : String(value));
  return (
    <input
      type="number"
      className={`problem-config-input${className ? ` ${className}` : ""}`}
      min={min}
      max={max}
      step={step}
      value={shown}
      onChange={(e) => {
        const text = e.target.value;
        setDraft(text);
        const parsed = parseFloat(text);
        onValueChange(Number.isNaN(parsed) ? null : parsed);
      }}
      onBlur={(e) => {
        if (e.currentTarget.value.trim() === "") onValueChange(0);
        setDraft(null);
      }}
      data-focus-key={focusKey}
      style={style}
    />
  );
}

/** Select elements cannot be read-only; when locked, show a button that matches input fields. */
export function ConfigSelect({
  editable,
  value,
  onChange,
  displayLabel,
  onActivate,
  focusKey,
  style,
  className,
  children,
}: {
  editable: boolean;
  value: string | number;
  onChange: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  displayLabel: string;
  onActivate?: (event?: ActivateHint) => void;
  focusKey?: string;
  style?: CSSProperties;
  className?: string;
  children: ReactNode;
}) {
  if (!editable) {
    return (
      <button
        type="button"
        className={`problem-config-field-mimic problem-config-field-mimic--select${className ? ` ${className}` : ""}`}
        title="Edit..."
        style={style}
        onClick={() =>
          onActivate?.({
            focusSelector: focusKey ? `[data-focus-key="${focusKey}"]` : undefined,
          })
        }
        data-focus-key={focusKey}
      >
        {displayLabel}
      </button>
    );
  }
  return (
    <select
      className={`problem-config-select${className ? ` ${className}` : ""}`}
      value={value}
      onChange={onChange}
      style={style}
      data-focus-key={focusKey}
    >
      {children}
    </select>
  );
}
