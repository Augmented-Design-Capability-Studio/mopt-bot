import { useState, type CSSProperties } from "react";

import type { BaseProblemBlock, ConstraintType } from "./types";
import type { MarkerKind } from "./useProblemConfigDiffMarkers";
import { ConfigNumberInput, ConfigSelect, type ActivateHint } from "./controls";

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

// ------------------------------------------------------------------
// ConstraintTypeSelect — shown in place of weight input
// ------------------------------------------------------------------

const CONSTRAINT_TYPE_OPTIONS: { id: ConstraintType; label: string }[] = [
  { id: "objective", label: "Obj" },
  { id: "soft", label: "Soft" },
  { id: "hard", label: "Hard" },
  { id: "custom", label: "Custom" },
];

function ConstraintTypeSelect({
  editable,
  constraintType,
  onChange,
  onActivate,
  focusKey,
}: {
  editable: boolean;
  constraintType: ConstraintType;
  onChange?: (type: ConstraintType) => void;
  onActivate?: (event?: ActivateHint) => void;
  focusKey?: string;
}) {
  return (
    <ConfigSelect
      editable={editable}
      value={constraintType}
      displayLabel={CONSTRAINT_TYPE_OPTIONS.find((o) => o.id === constraintType)?.label ?? "Obj"}
      onChange={(e) => onChange?.(e.target.value as ConstraintType)}
      onActivate={onActivate}
      focusKey={focusKey}
      className={`constraint-type-select constraint-type-select--${constraintType}`}
      style={{ minWidth: "4.4rem", textAlign: "right", fontSize: "0.8rem" }}
    >
      {CONSTRAINT_TYPE_OPTIONS.map(({ id, label }) => (
        <option key={id} value={id}>
          {label}
        </option>
      ))}
    </ConfigSelect>
  );
}

// ------------------------------------------------------------------
// GoalTermRow — no rank badge or drag handle (those live in the outer wrapper)
// ------------------------------------------------------------------

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
  constraintType,
  onConstraintTypeChange,
  constraintFocusKey,
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
  constraintType?: ConstraintType;
  onConstraintTypeChange?: (type: ConstraintType) => void;
  constraintFocusKey?: string;
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
        gap: "0.45rem",
        padding: "0.4rem 0",
      }}
    >
      {/* Center: label + description */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: "0.85rem" }} className="goal-term-row-label">
          <span className="goal-term-row-label-text">
            {label}
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
                className="direction-badge direction-badge--minimize"
                title="This term is minimized — higher weight penalizes this objective more strongly"
                aria-label="Minimize objective"
              >
                ↓ min
              </span>
            )}
          </span>
        </div>
        {description ? (
          <div className="muted" style={{ fontSize: "0.75rem", marginTop: "0.1rem" }}>
            {description}
          </div>
        ) : null}
      </div>

      {/* Right: lock/remove + type + optional custom input + resolved value */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", flexShrink: 0 }}>
        {(showLock || showRemove) && (
          <div className="definition-inline-actions" style={{ marginBottom: "0.2rem" }}>
            {showLock && (
              <button
                type="button"
                className={`definition-icon-btn${locked ? " definition-icon-btn--locked" : " definition-icon-btn--unlocked"}`}
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
        {constraintType ? (
          <ConstraintTypeSelect
            editable={editable}
            constraintType={constraintType}
            onChange={onConstraintTypeChange}
            onActivate={onActivate}
            focusKey={constraintFocusKey}
          />
        ) : null}
        {constraintType === "custom" || constraintType == null ? (
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
              width: "3.5rem",
              textAlign: "right",
              fontFamily: "monospace",
              marginTop: constraintType ? "0.25rem" : 0,
              ...inputStyle,
            }}
          />
        ) : null}
        <span className="muted" style={{ fontSize: "0.7rem", marginTop: "0.1rem" }}>
          {valueCaption}: {value.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------
// WeightRow
// ------------------------------------------------------------------

export function WeightRow({
  wkey,
  problem,
  editable,
  weightCatalog,
  updateProblem,
  onActivate,
  markerKind,
  onRememberRemoved,
  constraintType,
  onConstraintTypeChange,
}: {
  wkey: string;
  problem: BaseProblemBlock;
  editable: boolean;
  weightCatalog: Record<string, { label: string; description: string; direction?: "minimize" | "maximize" }>;
  updateProblem: (patch: Record<string, unknown>) => void;
  onActivate?: (event?: ActivateHint) => void;
  markerKind?: MarkerKind | null;
  onRememberRemoved?: (entry: RemovedGoalTermEntry) => void;
  constraintType?: ConstraintType;
  onConstraintTypeChange?: (type: ConstraintType) => void;
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
      showLock={constraintType == null}
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
        const nextConstraintTypes = { ...problem.constraint_types };
        delete nextConstraintTypes[wkey];
        const nextOrder = problem.goal_term_order ? problem.goal_term_order.filter((k) => k !== wkey) : null;
        updateProblem({
          weights: nextWeights,
          locked_goal_terms: removeLockedGoalTerm(problem.locked_goal_terms, wkey),
          constraint_types: nextConstraintTypes,
          goal_term_order: nextOrder,
        });
      }}
      constraintType={constraintType}
      onConstraintTypeChange={onConstraintTypeChange}
      constraintFocusKey={`constraint-${wkey}`}
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
  /** Per-key constraint mode (objective/soft/hard/custom). */
  constraintTypes: Record<string, ConstraintType>;
  /** Called when user changes a term's constraint type. Always enters edit mode. */
  onConstraintTypeChange: (key: string, type: ConstraintType) => void;
  /** Called when user drags to reorder goal terms. Always enters edit mode. */
  onReorder: (newOrder: string[]) => void;
};

function reorderKeys(arr: string[], from: string, to: string, insertBefore: boolean): string[] {
  const result = arr.filter((k) => k !== from);
  const toIdx = result.indexOf(to);
  if (toIdx === -1) return arr;
  result.splice(insertBefore ? toIdx : toIdx + 1, 0, from);
  return result;
}

/** Infer effective constraint type: explicit > locked-without-type > objective default. */
function effectiveType(
  key: string,
  constraintTypes: Record<string, ConstraintType>,
  lockedGoalTerms: string[],
): ConstraintType {
  const explicit = constraintTypes[key];
  if (explicit) return explicit;
  if (lockedGoalTerms.includes(key)) return "custom";
  return "objective";
}

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
  constraintTypes,
  onConstraintTypeChange,
  onReorder,
}: GoalTermsSectionProps) {
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [dragOverKey, setDragOverKey] = useState<string | null>(null);
  const [dragOverTop, setDragOverTop] = useState(true);

  return (
    <>
      {displayWeightKeys.map((key, rankIndex) => {
        const slot = extension?.keySlots?.[key];
        const ctype = effectiveType(key, constraintTypes, problem.locked_goal_terms);
        const isBeingDragged = dragKey === key;
        const isDragOver = dragOverKey === key && !isBeingDragged;

        const wrapperClass =
          "goal-term-row-wrapper" +
          (isBeingDragged ? " goal-term-row-wrapper--dragging" : "") +
          (isDragOver && dragOverTop ? " goal-term-row-wrapper--drag-over-top" : "") +
          (isDragOver && !dragOverTop ? " goal-term-row-wrapper--drag-over-bottom" : "");

        const dragHandlers = {
          draggable: "true" as const,
          onDragStart: (e: React.DragEvent) => {
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", key);
            setDragKey(key);
          },
          onDragEnd: () => {
            setDragKey(null);
            setDragOverKey(null);
          },
          onDragOver: (e: React.DragEvent) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            const rect = e.currentTarget.getBoundingClientRect();
            const newTop = e.clientY < rect.top + rect.height / 2;
            if (dragOverKey !== key || dragOverTop !== newTop) {
              setDragOverKey(key);
              setDragOverTop(newTop);
            }
          },
          onDragLeave: (e: React.DragEvent) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node)) {
              setDragOverKey(null);
            }
          },
          onDrop: (e: React.DragEvent) => {
            e.preventDefault();
            const fromKey = e.dataTransfer.getData("text/plain") || dragKey;
            if (!fromKey || fromKey === key) {
              setDragKey(null);
              setDragOverKey(null);
              return;
            }
            const newOrder = reorderKeys(displayWeightKeys, fromKey, key, dragOverTop);
            onReorder(newOrder);
            setDragKey(null);
            setDragOverKey(null);
          },
        };

        const leftCol = (
          <div className="goal-term-row-left-col">
            <span className="goal-term-rank-badge" aria-label={`Priority ${rankIndex + 1}`}>
              {rankIndex + 1}
            </span>
            <span className="goal-term-drag-handle" aria-hidden="true" title="Drag to reorder">
              ⠿
            </span>
          </div>
        );

        if (slot?.replaceRow) {
          return (
            <div key={key} className={wrapperClass} {...dragHandlers}>
              {leftCol}
              <div className="goal-term-row-content">{slot.replaceRow()}</div>
            </div>
          );
        }

        return (
          <div key={key} className={wrapperClass} {...dragHandlers}>
            {leftCol}
            <div className="goal-term-row-content">
              <WeightRow
                wkey={key}
                problem={problem}
                editable={editable}
                weightCatalog={weightCatalog}
                updateProblem={(patch) => runEditingAction(() => updateProblem(patch))}
                onActivate={(event) => ensureEditing(event)}
                markerKind={markerKindFor(`weight:${key}`)}
                onRememberRemoved={rememberRemovedGoalTerm}
                constraintType={ctype}
                onConstraintTypeChange={(type) => onConstraintTypeChange(key, type)}
              />
              {slot?.appendAfterRow?.() ?? null}
            </div>
          </div>
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
