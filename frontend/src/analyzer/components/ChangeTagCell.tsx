import type { CSSProperties } from "react";

import { CHANGE_FIELDS, changeKey, effectColor, originColor } from "../lib/facets";
import type { ChangeTag, SuggestedChange } from "../lib/types";

interface ChangeTagCellProps {
  changes: ChangeTag[];
  suggested: SuggestedChange[];
  goalTermKeys: string[];
  onAdd: (change: Omit<ChangeTag, "id">) => void;
  /** Reject a suggestion for good (persisted server-side). */
  onDismiss: (change: Omit<ChangeTag, "id">) => void;
  onEdit: (id: number, change: Omit<ChangeTag, "id">) => void;
  onDelete: (id: number) => void;
}

const EMPTY: Omit<ChangeTag, "id"> = { origin: null, type: null, term: null, effect: null };

function cardStyle(origin: string | null, effect: string | null): CSSProperties {
  return {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: "0.15rem",
    padding: "0.1rem 0.25rem",
    borderRadius: 5,
    background: `${originColor(origin)}14`,
    borderLeft: `3px solid ${effectColor(effect)}`,
    border: `1px solid ${originColor(origin)}55`,
  };
}

const selStyle: CSSProperties = { fontSize: "0.68rem", maxWidth: 108, padding: 0 };

/** Effect glyph: ✓ = applied (landed in the config), ✗ = removed / declined /
 * dropped (didn't survive), ? = mentioned (raised, not yet landed). Colored by
 * the effect's palette color. */
const EFFECT_GLYPH: Record<string, string> = {
  applied: "✓",
  mentioned: "?",
  dropped: "✗",
  declined: "✗",
  removed: "✗",
};

function EffectBadge({ effect }: { effect: string | null }) {
  if (!effect || !(effect in EFFECT_GLYPH)) return null;
  return (
    <span
      title={effect}
      style={{ fontSize: "0.68rem", fontWeight: 700, color: effectColor(effect) }}
    >
      {EFFECT_GLYPH[effect]}
    </span>
  );
}

/** One field dropdown inside a change card. */
function FieldSelect({
  fieldKey,
  value,
  options,
  onChange,
}: {
  fieldKey: string;
  value: string | null;
  options: string[];
  onChange: (v: string | null) => void;
}) {
  const opts = value && !options.includes(value) ? [value, ...options] : options;
  return (
    <select
      title={fieldKey}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      style={{ ...selStyle, color: value ? undefined : "#9ca3af" }}
    >
      <option value="">{fieldKey}</option>
      {opts.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

export function ChangeTagCell({
  changes,
  suggested,
  goalTermKeys,
  onAdd,
  onDismiss,
  onEdit,
  onDelete,
}: ChangeTagCellProps) {
  const existing = new Set(changes.map(changeKey));
  const fresh = suggested.filter((s) => !existing.has(changeKey(s)));
  const termOptions = (fieldKey: string) => (fieldKey === "term" ? goalTermKeys : undefined);

  function fields(change: Omit<ChangeTag, "id">, onChange: (next: Omit<ChangeTag, "id">) => void) {
    return CHANGE_FIELDS.map((f) => (
      <FieldSelect
        key={f.key}
        fieldKey={f.label}
        value={change[f.key]}
        options={termOptions(f.key) ?? f.values}
        onChange={(v) => onChange({ ...change, [f.key]: v })}
      />
    ));
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.2rem", minWidth: 320 }}>
      {changes.map((c) => (
        <div key={c.id} style={cardStyle(c.origin, c.effect)}>
          {fields(c, (next) => onEdit(c.id, next))}
          <EffectBadge effect={c.effect} />
          <button
            type="button"
            title="remove change"
            onClick={() => onDelete(c.id)}
            style={{ border: "none", background: "none", cursor: "pointer", fontSize: "0.72rem", padding: 0 }}
          >
            ✕
          </button>
        </div>
      ))}

      {fresh.map((s) => (
        <div
          key={changeKey(s)}
          style={{
            ...cardStyle(s.origin, s.effect),
            background: "transparent",
            borderStyle: "dashed",
            opacity: 0.9,
          }}
        >
          <span
            style={{ fontSize: "0.68rem", color: "#6b7280" }}
            title={s.rationale ?? undefined}
          >
            {[s.origin, s.type, s.term, s.effect].filter(Boolean).join(" · ") || "change"}
            {s.rationale ? <span style={{ marginLeft: 3, color: "#8b5cf6", cursor: "help" }}>ℹ</span> : null}
          </span>
          <EffectBadge effect={s.effect} />
          <button
            type="button"
            title="accept suggestion"
            onClick={() => onAdd({ origin: s.origin, type: s.type, term: s.term, effect: s.effect })}
            style={{
              border: "none",
              background: "none",
              cursor: "pointer",
              fontSize: "0.72rem",
              fontWeight: 700,
              color: "#3b82f6",
              padding: 0,
            }}
          >
            ＋accept
          </button>
          <button
            type="button"
            title="dismiss suggestion (won't come back)"
            onClick={() => onDismiss({ origin: s.origin, type: s.type, term: s.term, effect: s.effect })}
            style={{
              border: "none",
              background: "none",
              cursor: "pointer",
              fontSize: "0.72rem",
              fontWeight: 700,
              color: "#dc2626",
              padding: 0,
            }}
          >
            ✕
          </button>
        </div>
      ))}

      <button
        type="button"
        onClick={() => onAdd(EMPTY)}
        style={{
          alignSelf: "flex-start",
          fontSize: "0.68rem",
          border: "1px dashed #9ca3af",
          borderRadius: 4,
          background: "none",
          cursor: "pointer",
          color: "#6b7280",
          padding: "0 0.3rem",
        }}
      >
        + change
      </button>
    </div>
  );
}
