import { Fragment, type CSSProperties } from "react";

import { SHIFT_HARD_PENALTY_INFO, WEIGHT_INFO, WORKER_NAMES, PREFERENCE_CONDITIONS } from "./metadata";
import { FieldRow } from "./layout";
import type { DriverPref, ProblemBlock } from "./types";
import type { MarkerKind } from "./useProblemConfigDiffMarkers";
import { ConfigNumberInput, ConfigSelect, type ActivateHint } from "./controls";

export type RemovedGoalTermEntry = { key: string; value: number; locked: boolean; type: "weight" | "shift" };

function workerOptionLabel(vehicleIdx: number): string {
  const name = WORKER_NAMES[vehicleIdx];
  return `${vehicleIdx}: ${name}`;
}

function preferenceConditionLabel(value: string): string {
  return PREFERENCE_CONDITIONS.find((o) => o.value === value)?.label ?? value;
}

function driverPreferencePeekLine(pref: DriverPref): string {
  const name = WORKER_NAMES[pref.vehicle_idx];
  const worker = `${pref.vehicle_idx}: ${name ?? "?"}`;
  const cond = preferenceConditionLabel(pref.condition);
  const bits: string[] = [worker, cond];
  if (pref.condition === "avoid_zone" || pref.condition === "zone_d") bits.push(`zone ${pref.zone ?? "?"}`);
  if (pref.condition === "order_priority" || pref.condition === "express_order") {
    bits.push(String(pref.order_priority ?? "express"));
  }
  bits.push(`penalty ${pref.penalty}`);
  return bits.join(" · ");
}

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
function GoalTermRow({
  label,
  description,
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
          {markerKind ? (
            <span
              className={`entry-diff-marker ${markerKind === "new" ? "entry-diff-marker--new" : "entry-diff-marker--upd"}`}
              title={markerKind === "new" ? "New agent update" : "Updated by agent"}
              aria-label={markerKind === "new" ? "New agent update" : "Updated by agent"}
            >
              {markerKind === "new" ? "+" : "Δ"}
            </span>
          ) : null}
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

function WeightRow({
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
  problem: ProblemBlock;
  editable: boolean;
  weightCatalog: Record<string, { label: string; description: string }>;
  updateProblem: (patch: Partial<ProblemBlock>) => void;
  onActivate?: (event?: ActivateHint) => void;
  markerKind?: MarkerKind | null;
  onRememberRemoved?: (entry: RemovedGoalTermEntry) => void;
}) {
  const info = weightCatalog[wkey] ?? WEIGHT_INFO[wkey];
  const isLocked = problem.locked_goal_terms.includes(wkey);
  return (
    <GoalTermRow
      label={info?.label ?? wkey}
      description={info?.description}
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
      showRemove
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

type GoalTermsSectionProps = {
  problem: ProblemBlock;
  editable: boolean;
  /** When false, preference-rule rows are read-only (e.g. worker_preference weight is locked). */
  preferencesEditable: boolean;
  showWorkerBlock: boolean;
  extensionUi: string;
  weightCatalog: Record<string, { label: string; description: string }>;
  displayWeightKeys: string[];
  removedGoalTerms: RemovedGoalTermEntry[];
  markerKindFor: (key: string) => MarkerKind | null;
  updateProblem: (patch: Partial<ProblemBlock>) => void;
  runEditingAction: (action: () => void, event?: ActivateHint) => void;
  ensureEditing: (event?: ActivateHint) => void;
  rememberRemovedGoalTerm: (entry: RemovedGoalTermEntry) => void;
  restoreRemovedGoalTerm: (key: string) => void;
  updatePreferenceAt: (index: number, pref: DriverPref) => void;
  removePreference: (index: number) => void;
  addPreference: () => void;
  updateLocked: (taskKey: string, worker: number | "") => void;
  addLockedRow: () => void;
};

export function GoalTermsSection({
  problem,
  editable,
  preferencesEditable,
  showWorkerBlock,
  extensionUi,
  weightCatalog,
  displayWeightKeys,
  removedGoalTerms,
  markerKindFor,
  updateProblem,
  runEditingAction,
  ensureEditing,
  rememberRemovedGoalTerm,
  restoreRemovedGoalTerm,
  updatePreferenceAt,
  removePreference,
  addPreference,
  updateLocked,
  addLockedRow,
}: GoalTermsSectionProps) {
  const hasHardStructural =
    extensionUi === "vrptw_extras" &&
    (Object.keys(problem.locked_assignments).length > 0 || problem.shift_hard_penalty !== null);
  const rules = problem.driver_preferences;
  const preferencePeekText =
    rules.length === 0
      ? "No preference rules"
      : rules.length === 1
        ? driverPreferencePeekLine(rules[0]!)
        : `${driverPreferencePeekLine(rules[0]!)} (+${rules.length - 1} more)`;
  return (
    <>
      {displayWeightKeys.map((key) =>
        key === "worker_preference" && extensionUi === "vrptw_extras" ? (
          <Fragment key={key}>
            <WeightRow
              wkey={key}
              problem={problem}
              editable={editable}
              weightCatalog={weightCatalog}
              updateProblem={(patch) => runEditingAction(() => updateProblem(patch))}
              onActivate={(event) => ensureEditing(event)}
            />
            <details className="driver-pref-details">
              <summary
                style={{
                  cursor: "pointer",
                  fontWeight: 600,
                  fontSize: "0.82rem",
                  userSelect: "none",
                }}
              >
                <span className="field-row-label">
                  Preference rules
                  {markerKindFor("field:driver_preferences") ? (
                    <span
                      className={`entry-diff-marker ${markerKindFor("field:driver_preferences") === "new" ? "entry-diff-marker--new" : "entry-diff-marker--upd"}`}
                      title={markerKindFor("field:driver_preferences") === "new" ? "New agent update" : "Updated by agent"}
                      aria-label={markerKindFor("field:driver_preferences") === "new" ? "New agent update" : "Updated by agent"}
                    >
                      {markerKindFor("field:driver_preferences") === "new" ? "+" : "Δ"}
                    </span>
                  ) : null}
                </span>
              </summary>
              <div className="driver-pref-peek muted" aria-hidden>
                {preferencePeekText}
              </div>
              <div className="driver-pref-rules" style={{ marginTop: "0.4rem" }}>
                {problem.driver_preferences.map((pref, index) => (
                  <div
                    key={index}
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "0.35rem",
                      alignItems: "center",
                      padding: "0.35rem 0",
                      borderBottom: "1px solid var(--border)",
                    }}
                  >
                    <ConfigSelect
                      editable={preferencesEditable}
                      value={pref.vehicle_idx}
                      displayLabel={workerOptionLabel(pref.vehicle_idx)}
                      onChange={(e) =>
                        runEditingAction(() =>
                          updatePreferenceAt(index, { ...pref, vehicle_idx: parseInt(e.target.value, 10) }),
                        )
                      }
                      onActivate={(hint) => ensureEditing(hint)}
                      focusKey={`pref-${index}-vehicle`}
                      style={{ fontSize: "0.8rem" }}
                    >
                      {WORKER_NAMES.map((name, vi) => (
                        <option key={name} value={vi}>
                          {vi}: {name}
                        </option>
                      ))}
                    </ConfigSelect>
                    <ConfigSelect
                      editable={preferencesEditable}
                      value={pref.condition}
                      displayLabel={preferenceConditionLabel(pref.condition)}
                      onChange={(e) =>
                        runEditingAction(() => updatePreferenceAt(index, { ...pref, condition: e.target.value }))
                      }
                      onActivate={(hint) => ensureEditing(hint)}
                      focusKey={`pref-${index}-condition`}
                      style={{ fontSize: "0.8rem", maxWidth: "12rem" }}
                    >
                      {PREFERENCE_CONDITIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </ConfigSelect>
                    <label className="muted" style={{ fontSize: "0.75rem" }}>
                      penalty
                      <ConfigNumberInput
                        editable={preferencesEditable}
                        value={pref.penalty}
                        min={0}
                        step={0.5}
                        onValueChange={(value) => {
                          if (value == null) return;
                          runEditingAction(() => updatePreferenceAt(index, { ...pref, penalty: value }));
                        }}
                        onActivate={(hint) => ensureEditing(hint)}
                        focusKey={`pref-${index}-penalty`}
                        style={{ width: "4rem", marginLeft: "0.25rem", fontFamily: "monospace" }}
                      />
                    </label>
                    {(pref.condition === "avoid_zone" || pref.condition === "zone_d") && (
                      <label className="muted" style={{ fontSize: "0.75rem" }}>
                        zone
                        <ConfigSelect
                          editable={preferencesEditable}
                          value={pref.zone ?? 4}
                          displayLabel={String.fromCharCode(64 + (pref.zone ?? 4))}
                          onChange={(e) =>
                            runEditingAction(() => updatePreferenceAt(index, { ...pref, zone: parseInt(e.target.value, 10) }))
                          }
                          onActivate={(hint) => ensureEditing(hint)}
                          focusKey={`pref-${index}-zone`}
                          style={{ width: "4rem", marginLeft: "0.25rem", fontFamily: "monospace" }}
                        >
                          <option value={1}>A</option>
                          <option value={2}>B</option>
                          <option value={3}>C</option>
                          <option value={4}>D</option>
                          <option value={5}>E</option>
                        </ConfigSelect>
                      </label>
                    )}
                    {(pref.condition === "order_priority" || pref.condition === "express_order") && (
                      <ConfigSelect
                        editable={preferencesEditable}
                        value={pref.order_priority ?? "express"}
                        displayLabel={pref.order_priority ?? "express"}
                        onChange={(e) =>
                          runEditingAction(() => updatePreferenceAt(index, { ...pref, order_priority: e.target.value }))
                        }
                        onActivate={(hint) => ensureEditing(hint)}
                        focusKey={`pref-${index}-order-priority`}
                        style={{ fontSize: "0.8rem" }}
                      >
                        <option value="express">express</option>
                        <option value="standard">standard</option>
                      </ConfigSelect>
                    )}
                    {(pref.condition === "shift_over_limit" || pref.condition === "shift_over_hours") && (
                      <label className="muted" style={{ fontSize: "0.75rem" }}>
                        limit (min)
                        <ConfigNumberInput
                          editable={preferencesEditable}
                          value={pref.limit_minutes ?? (pref.hours != null ? pref.hours * 60 : 390)}
                          min={1}
                          onValueChange={(v) => {
                            if (v == null) return;
                            runEditingAction(() =>
                              updatePreferenceAt(index, {
                                ...pref,
                                limit_minutes: v <= 0 ? 390 : v,
                                hours: undefined,
                              }),
                            );
                          }}
                          onActivate={(hint) => ensureEditing(hint)}
                          focusKey={`pref-${index}-limit-minutes`}
                          style={{ width: "4.5rem", marginLeft: "0.25rem", fontFamily: "monospace" }}
                        />
                      </label>
                    )}
                    {preferencesEditable && (
                      <button
                        type="button"
                        className="muted"
                        style={{ fontSize: "0.75rem" }}
                        onClick={() => removePreference(index)}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                ))}
                {preferencesEditable && (
                  <button type="button" style={{ marginTop: "0.25rem", fontSize: "0.8rem" }} onClick={() => runEditingAction(addPreference)}>
                    + Add preference rule
                  </button>
                )}
              </div>
            </details>
          </Fragment>
        ) : (
          <WeightRow
            key={key}
            wkey={key}
            problem={problem}
            editable={editable}
            weightCatalog={weightCatalog}
            updateProblem={(patch) => runEditingAction(() => updateProblem(patch))}
            onActivate={(event) => ensureEditing(event)}
            markerKind={markerKindFor(`weight:${key}`)}
            onRememberRemoved={rememberRemovedGoalTerm}
          />
        ),
      )}

      {hasHardStructural && (
        <>
          {problem.shift_hard_penalty !== null && (
            <GoalTermRow
              label={SHIFT_HARD_PENALTY_INFO.label}
              description={SHIFT_HARD_PENALTY_INFO.description}
              editable={editable}
              value={problem.shift_hard_penalty}
              min={0}
              step={100}
              valueCaption="penalty"
              onChange={(e) => {
                const value = parseFloat(e.target.value);
                if (Number.isNaN(value)) return;
                updateProblem({
                  shift_hard_penalty: value,
                });
              }}
              onActivate={(hint) => ensureEditing(hint)}
              focusKey="shift-hard-penalty"
              markerKind={markerKindFor("field:shift_hard_penalty")}
              locked={problem.locked_goal_terms.includes("shift_hard_penalty")}
              showLock
              showRemove
              onToggleLock={() =>
                runEditingAction(() => {
                  updateProblem({
                    locked_goal_terms: toggleLockedGoalTerm(problem.locked_goal_terms, "shift_hard_penalty"),
                  });
                })
              }
              onRemove={() =>
                runEditingAction(() => {
                  rememberRemovedGoalTerm({
                    key: "shift_hard_penalty",
                    value: problem.shift_hard_penalty ?? 0,
                    locked: problem.locked_goal_terms.includes("shift_hard_penalty"),
                    type: "shift",
                  });
                  updateProblem({
                    shift_hard_penalty: null,
                    locked_goal_terms: removeLockedGoalTerm(problem.locked_goal_terms, "shift_hard_penalty"),
                  });
                })
              }
            />
          )}
          {removedGoalTerms
            .filter((entry) => entry.type === "shift")
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
                  <span className="muted">{SHIFT_HARD_PENALTY_INFO.label} (removed)</span>
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

          {Object.keys(problem.locked_assignments).length > 0 && (
            <FieldRow label="Fixed task → worker assignments" markerKind={markerKindFor("field:locked_assignments")}>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                {Object.entries(problem.locked_assignments).map(([taskKey, workerIdx]) => (
                  <div key={taskKey} style={{ display: "flex", alignItems: "center", gap: "0.35rem", flexWrap: "wrap" }}>
                    <span className="muted" style={{ fontSize: "0.8rem" }}>
                      Task #{taskKey} →
                    </span>
                    <ConfigSelect
                      editable={editable}
                      value={workerIdx}
                      displayLabel={workerOptionLabel(workerIdx)}
                      onChange={(e) => runEditingAction(() => updateLocked(taskKey, parseInt(e.target.value, 10)))}
                      onActivate={(hint) => ensureEditing(hint)}
                      focusKey={`locked-assignment-${taskKey}`}
                      style={{ fontSize: "0.8rem" }}
                    >
                      {WORKER_NAMES.map((name, vi) => (
                        <option key={name} value={vi}>
                          {vi}: {name}
                        </option>
                      ))}
                    </ConfigSelect>
                    {editable && (
                      <button
                        type="button"
                        className="muted"
                        style={{ fontSize: "0.75rem" }}
                        onClick={() => updateLocked(taskKey, "")}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </FieldRow>
          )}
          {editable && showWorkerBlock && Object.keys(problem.locked_assignments).length < 30 && (
            <button type="button" style={{ fontSize: "0.8rem" }} onClick={() => runEditingAction(addLockedRow)}>
              + Add locked assignment
            </button>
          )}
        </>
      )}
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
              <span className="muted">{weightCatalog[entry.key]?.label ?? WEIGHT_INFO[entry.key]?.label ?? entry.key} (removed)</span>
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
