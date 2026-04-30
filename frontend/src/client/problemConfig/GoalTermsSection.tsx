import { Fragment, type CSSProperties } from "react";

import type { BaseProblemBlock } from "./types";
import type { MarkerKind } from "./useProblemConfigDiffMarkers";
import { ConfigNumberInput, type ActivateHint } from "./controls";

// ------------------------------------------------------------------
// Extension API — consumed by problem-module frontend code (e.g. VrptwExtras.tsx)
// ------------------------------------------------------------------

export type GoalTermsKeySlot = {
  /** Completely replaces the default WeightRow (and any extras) for this key. */
  replaceRow?: () => React.ReactNode;
  /** Extra content rendered after the default WeightRow for this key. */
  appendAfterRow?: () => React.ReactNode;
};

export type GoalTermsExtension = {
  keySlots?: Record<string, GoalTermsKeySlot>;
  /** Extra rows appended after the full weight list (e.g. locked assignments, removed structural terms). */
  footerRows?: React.ReactNode;
};

// ------------------------------------------------------------------
// Exported re-usable components (for use by problem-module extensions)
// ------------------------------------------------------------------

export type GoalTermRowExports = {
  GoalTermRow: typeof GoalTermRow;
  WeightRow: typeof WeightRow;
};

export type RemovedGoalTermEntry = {
  key: string;
  value: number;
  locked: boolean;
  /** "weight" for standard goal-term rows; problem modules may add their own types. */
  type: "weight" | "shift" | "max_shift" | string;
  /**
   * For non-"weight" types: the JSON field name to write back when restoring.
   * Set by the problem-module extension; used by ProblemConfigBlocks.restoreRemovedGoalTerm.
   */
  fieldName?: string;
};

export function toggleLockedGoalTerm(list: string[], key: string): string[] {
  const next = new Set(list);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return [...next];
}

export function removeLockedGoalTerm(list: string[], key: string): string[] {
  return list.filter((entry) => entry !== key);
}

/** Same row chrome as weight terms (bold title, muted description, value + caption). */
export function GoalTermRow({
  label,
  description,
  direction,
  editable,
  value,
  min,
  max,
  step,
  valueCaption,
  onChange,
  onActivate,
  focusKey,
  markerKind,
  onToggleLock,
  onRemove,
  locked = false,
  showLock = false,
  showRemove = false,
  inputStyle,
}: {
  label: string;
  description?: string;
  direction?: "minimize" | "maximize";
  editable: boolean;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  valueCaption: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onActivate?: (event?: ActivateHint) => void;
  focusKey?: string;
  markerKind?: MarkerKind | null;
  onToggleLock?: () => void;
  onRemove?: () => void;
  locked?: boolean;
  showLock?: boolean;
  showRemove?: boolean;
  inputStyle?: CSSProperties;
}) {
  const markerClass =
    markerKind === "new"
      ? "problem-config-control-external-mark--new"
      : markerKind === "upd"
        ? "problem-config-control-external-mark--upd"
        : "";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: "0.6rem",
        padding: "0.4rem 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: "0.85rem" }} className="goal-term-row-label">
          <span>{label}</span>
          {direction === "maximize" ? (
            <span
              className="direction-badge direction-badge--maximize"
              title="This term is maximized — higher weight favors more of this objective"
              aria-label="Maximize objective"
            >
              ↑ max
            </span>
          ) : (
            <span
              className="direction-badge"
              title="This term is minimized — higher weight penalizes this objective more strongly"
              aria-label="Minimize objective"
            >
              ↓ min
            </span>
          )}
        </div>
        {description ? (
          <div className="muted" style={{ fontSize: "0.75rem", marginTop: "0.1rem" }}>
            {description}
          </div>
        ) : null}
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", flexShrink: 0 }}>
        {(showLock || showRemove) && (
          <div className="definition-inline-actions" style={{ marginBottom: "0.2rem" }}>
            {showLock && (
              <button
                type="button"
                className="definition-icon-btn"
                title={locked ? "Unlock this goal term" : "Lock this goal term"}
                aria-label={locked ? "Unlock goal term" : "Lock goal term"}
                onClick={onToggleLock}
              >
                {locked ? "🔒" : "🔓"}
              </button>
            )}
            {showRemove && (
              <button
                type="button"
                className="definition-icon-btn definition-remove-btn"
                title="Remove this goal term"
                aria-label="Remove goal term"
                onClick={onRemove}
              >
                X
              </button>
            )}
          </div>
        )}
        <ConfigNumberInput
          editable={editable}
          value={value}
          className={markerClass}
          min={min}
          max={max}
          step={step}
          onValueChange={(next) => {
            const inputEvent = {
              target: { value: next == null ? "" : String(next) },
            } as React.ChangeEvent<HTMLInputElement>;
            onChange(inputEvent);
          }}
          onActivate={onActivate}
          focusKey={focusKey}
          style={{
            width: "5.5rem",
            textAlign: "right",
            fontFamily: "monospace",
            ...inputStyle,
          }}
        />
        <span className="muted" style={{ fontSize: "0.7rem", marginTop: "0.1rem" }}>
          {valueCaption}
        </span>
      </div>
    </div>
  );
}

export function WeightRow({
  wkey,
  problem,
  editable,
  weightCatalog,
  updateProblem,
  onActivate,
  markerKind,
  onRememberRemoved,
}: {
  wkey: string;
  problem: BaseProblemBlock;
  editable: boolean;
  weightCatalog: Record<string, { label: string; description: string; direction?: "minimize" | "maximize" }>;
  updateProblem: (patch: Record<string, unknown>) => void;
  onActivate?: (event?: ActivateHint) => void;
  markerKind?: MarkerKind | null;
  onRememberRemoved?: (entry: RemovedGoalTermEntry) => void;
}) {
  const info = weightCatalog[wkey];
  const isLocked = problem.locked_goal_terms.includes(wkey);
  return (
    <GoalTermRow
      label={info?.label ?? wkey}
      description={info?.description}
      direction={info?.direction}
      editable={editable}
      value={problem.weights[wkey] ?? 0}
      min={0}
      step={0.5}
      valueCaption="weight"
      onChange={(e) => {
        const value = parseFloat(e.target.value);
        if (Number.isNaN(value)) return;
        updateProblem({
          weights: { ...problem.weights, [wkey]: value },
        });
      }}
      onActivate={onActivate}
      focusKey={`weight-${wkey}`}
      markerKind={markerKind}
      locked={isLocked}
      showLock
      showRemove={!!onRememberRemoved}
      onToggleLock={() => {
        updateProblem({ locked_goal_terms: toggleLockedGoalTerm(problem.locked_goal_terms, wkey) });
      }}
      onRemove={() => {
        onRememberRemoved?.({
          key: wkey,
          value: typeof problem.weights[wkey] === "number" ? problem.weights[wkey]! : 0,
          locked: problem.locked_goal_terms.includes(wkey),
          type: "weight",
        });
        const nextWeights = { ...problem.weights };
        delete nextWeights[wkey];
        updateProblem({
          weights: nextWeights,
          locked_goal_terms: removeLockedGoalTerm(problem.locked_goal_terms, wkey),
        });
      }}
    />
  );
}

// ------------------------------------------------------------------
// GoalTermsSection
// ------------------------------------------------------------------

type GoalTermsSectionProps = {
  problem: BaseProblemBlock;
  editable: boolean;
  weightCatalog: Record<string, { label: string; description: string; direction?: "minimize" | "maximize" }>;
  displayWeightKeys: string[];
  removedGoalTerms: RemovedGoalTermEntry[];
  markerKindFor: (key: string) => MarkerKind | null;
  updateProblem: (patch: Record<string, unknown>) => void;
  runEditingAction: (action: () => void, event?: ActivateHint) => void;
  ensureEditing: (event?: ActivateHint) => void;
  rememberRemovedGoalTerm: (entry: RemovedGoalTermEntry) => void;
  restoreRemovedGoalTerm: (key: string) => void;
  /** Problem-module extension: per-key overrides and a footer row slot. */
  extension?: GoalTermsExtension;
};

export function GoalTermsSection({
  problem,
  editable,
  weightCatalog,
  displayWeightKeys,
  removedGoalTerms,
  markerKindFor,
  updateProblem,
  runEditingAction,
  ensureEditing,
  rememberRemovedGoalTerm,
  restoreRemovedGoalTerm,
  extension,
}: GoalTermsSectionProps) {
  return (
    <>
      {displayWeightKeys.map((key) => {
        const slot = extension?.keySlots?.[key];
        if (slot?.replaceRow) {
          return <Fragment key={key}>{slot.replaceRow()}</Fragment>;
        }
        return (
          <Fragment key={key}>
            <WeightRow
              wkey={key}
              problem={problem}
              editable={editable}
              weightCatalog={weightCatalog}
              updateProblem={(patch) => runEditingAction(() => updateProblem(patch))}
              onActivate={(event) => ensureEditing(event)}
              markerKind={markerKindFor(`weight:${key}`)}
              onRememberRemoved={rememberRemovedGoalTerm}
            />
            {slot?.appendAfterRow?.() ?? null}
          </Fragment>
        );
      })}

      {extension?.footerRows ?? null}

      {removedGoalTerms
        .filter((entry) => entry.type === "weight")
        .map((entry) => (
          <div
            key={`removed-${entry.key}`}
            className="definition-item definition-item-removed"
            role="button"
            tabIndex={0}
            onClick={() => runEditingAction(() => restoreRemovedGoalTerm(entry.key))}
          >
            <div className="definition-item-meta">
              <span className="entry-diff-marker entry-diff-marker--removed">-</span>
              <span className="muted">{weightCatalog[entry.key]?.label ?? entry.key} (removed)</span>
              <button
                type="button"
                className="definition-icon-btn definition-restore-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  runEditingAction(() => restoreRemovedGoalTerm(entry.key));
                }}
              >
                R
              </button>
            </div>
          </div>
        ))}
    </>
  );
}

