/**
 * VRPTW-specific UI blocks for the problem config panel.
 *
 * Exports `buildVrptwGoalTermsExtension(props)` which returns a GoalTermsExtension
 * consumed by the generic GoalTermsSection. This keeps all VRPTW-specific rendering
 * (driver preferences, max-shift threshold, locked assignments)
 * and all VRPTW-specific state mutations co-located with the vrptw_problem module.
 *
 * ProblemConfigBlocks passes only generic props (configJson, editable, callbacks) —
 * no VRPTW types, field names, or derived state leak into the generic shell.
 */

import { Fragment } from "react";

import type { GoalTermsExtension, RemovedGoalTermEntry } from "@problemConfig/GoalTermsSection";
import { toggleLockedGoalTerm, removeLockedGoalTerm, WeightRow } from "@problemConfig/GoalTermsSection";
import type { MarkerKind } from "@problemConfig/useProblemConfigDiffMarkers";
import { ConfigNumberInput, ConfigSelect, type ActivateHint } from "@problemConfig/controls";
import { FieldRow } from "@problemConfig/layout";

import {
  DELIVERY_ZONES,
  MAX_SHIFT_HOURS_INFO,
  PREFERENCE_CONDITIONS,
  WORKER_NAMES,
  zoneLabelFromId,
} from "./metadata";
import type { DriverPref, ProblemBlock } from "./types";
import { parseProblemConfig } from "./serialization";

// ------------------------------------------------------------------
// Internal helpers
// ------------------------------------------------------------------

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
  if (pref.condition === "avoid_zone") bits.push(`zone ${zoneLabelFromId(pref.zone)}`);
  if (pref.condition === "order_priority") {
    bits.push(String(pref.order_priority ?? "express"));
  }
  bits.push(`penalty ${pref.penalty}`);
  return bits.join(" · ");
}

// ------------------------------------------------------------------
// Props type — only generic data from ProblemConfigBlocks
// ------------------------------------------------------------------

export type VrptwGoalTermsExtensionProps = {
  /** Raw config JSON — VrptwExtras parses VRPTW-specific fields (driver_preferences, etc.) internally. */
  configJson: string;
  /** From problemMeta.worker_preference_key; null for problems without this concept. */
  workerPreferenceKey: string | null;
  editable: boolean;
  removedGoalTerms: RemovedGoalTermEntry[];
  markerKindFor: (key: string) => MarkerKind | null;
  weightCatalog: Record<string, { label: string; description: string; direction?: "minimize" | "maximize" }>;
  /** Generic update callback — accepts both base and VRPTW-specific patches. */
  updateProblem: (patch: Record<string, unknown>) => void;
  runEditingAction: (action: () => void, event?: ActivateHint) => void;
  ensureEditing: (event?: ActivateHint) => void;
  rememberRemovedGoalTerm: (entry: RemovedGoalTermEntry) => void;
  /** Provided by ProblemConfigBlocks; handles "weight" and fieldName-based restoration. */
  restoreRemovedGoalTerm: (key: string) => void;
};

// ------------------------------------------------------------------
// Internal component prop types
// ------------------------------------------------------------------

type WorkerPreferenceExtrasProps = {
  problem: ProblemBlock;
  preferencesEditable: boolean;
  markerKindFor: (key: string) => MarkerKind | null;
  runEditingAction: (action: () => void, event?: ActivateHint) => void;
  ensureEditing: (event?: ActivateHint) => void;
  updatePreferenceAt: (index: number, pref: DriverPref) => void;
  removePreference: (index: number) => void;
  addPreference: () => void;
};

type MaxShiftHoursDetailsProps = {
  problem: ProblemBlock;
  editable: boolean;
  markerKindFor: (key: string) => MarkerKind | null;
  updateProblem: (patch: Record<string, unknown>) => void;
  runEditingAction: (action: () => void, event?: ActivateHint) => void;
  ensureEditing: (event?: ActivateHint) => void;
  rememberRemovedGoalTerm: (entry: RemovedGoalTermEntry) => void;
};

type VrptwFooterRowsProps = {
  problem: ProblemBlock;
  editable: boolean;
  showWorkerBlock: boolean;
  removedGoalTerms: RemovedGoalTermEntry[];
  markerKindFor: (key: string) => MarkerKind | null;
  runEditingAction: (action: () => void, event?: ActivateHint) => void;
  restoreRemovedGoalTerm: (key: string) => void;
  updateLocked: (taskKey: string, worker: number | "") => void;
  addLockedRow: () => void;
};

// ------------------------------------------------------------------
// Per-key extras
// ------------------------------------------------------------------

function WorkerPreferenceExtras({
  problem,
  preferencesEditable,
  markerKindFor,
  runEditingAction,
  ensureEditing,
  updatePreferenceAt,
  removePreference,
  addPreference,
}: WorkerPreferenceExtrasProps) {
  const rules = problem.driver_preferences;
  const preferencePeekText =
    rules.length === 0
      ? "No preference rules"
      : rules.length === 1
        ? driverPreferencePeekLine(rules[0]!)
        : `${driverPreferencePeekLine(rules[0]!)} (+${rules.length - 1} more)`;

  return (
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
            {pref.condition === "avoid_zone" && (
              <label className="muted" style={{ fontSize: "0.75rem" }}>
                zone
                <ConfigSelect
                  editable={preferencesEditable}
                  value={pref.zone ?? 4}
                  displayLabel={zoneLabelFromId(pref.zone ?? 4)}
                  onChange={(e) =>
                    runEditingAction(() => updatePreferenceAt(index, { ...pref, zone: parseInt(e.target.value, 10) }))
                  }
                  onActivate={(hint) => ensureEditing(hint)}
                  focusKey={`pref-${index}-zone`}
                  style={{ width: "4rem", marginLeft: "0.25rem", fontFamily: "monospace" }}
                >
                  {DELIVERY_ZONES.map((zone) => (
                    <option key={zone.id} value={zone.id}>
                      {zone.label}
                    </option>
                  ))}
                </ConfigSelect>
              </label>
            )}
            {pref.condition === "order_priority" && (
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
            {pref.condition === "shift_over_limit" && (
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
  );
}

function MaxShiftHoursDetails({
  problem,
  editable,
  markerKindFor,
  updateProblem,
  runEditingAction,
  ensureEditing,
  rememberRemovedGoalTerm,
}: MaxShiftHoursDetailsProps) {
  if (problem.max_shift_hours === null) return null;

  return (
    <details className="driver-pref-details" open>
      <summary
        style={{
          cursor: "pointer",
          fontWeight: 600,
          fontSize: "0.82rem",
          userSelect: "none",
        }}
      >
        <span className="field-row-label">
          {MAX_SHIFT_HOURS_INFO.label} threshold
          {markerKindFor("field:max_shift_hours") ? (
            <span
              className={`entry-diff-marker ${markerKindFor("field:max_shift_hours") === "new" ? "entry-diff-marker--new" : "entry-diff-marker--upd"}`}
              title={markerKindFor("field:max_shift_hours") === "new" ? "New agent update" : "Updated by agent"}
              aria-label={markerKindFor("field:max_shift_hours") === "new" ? "New agent update" : "Updated by agent"}
            >
              {markerKindFor("field:max_shift_hours") === "new" ? "+" : "Δ"}
            </span>
          ) : null}
        </span>
      </summary>
      <div className="driver-pref-peek muted" aria-hidden>
        {problem.max_shift_hours} hours
      </div>
      <div style={{ marginTop: "0.4rem", marginBottom: "0.4rem" }}>
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
            <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>{MAX_SHIFT_HOURS_INFO.label}</div>
            <div className="muted" style={{ fontSize: "0.75rem", marginTop: "0.1rem" }}>
              {MAX_SHIFT_HOURS_INFO.description}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", flexShrink: 0 }}>
            <div className="definition-inline-actions" style={{ marginBottom: "0.2rem" }}>
              <button
                type="button"
                className="definition-icon-btn"
                title={problem.locked_goal_terms.includes("max_shift_hours") ? "Unlock this goal term" : "Lock this goal term"}
                aria-label={problem.locked_goal_terms.includes("max_shift_hours") ? "Unlock goal term" : "Lock goal term"}
                onClick={() =>
                  runEditingAction(() => {
                    updateProblem({
                      locked_goal_terms: toggleLockedGoalTerm(problem.locked_goal_terms, "max_shift_hours"),
                    });
                  })
                }
              >
                {problem.locked_goal_terms.includes("max_shift_hours") ? "🔒" : "🔓"}
              </button>
              <button
                type="button"
                className="definition-icon-btn definition-remove-btn"
                title="Remove this goal term"
                aria-label="Remove goal term"
                onClick={() =>
                  runEditingAction(() => {
                    rememberRemovedGoalTerm({
                      key: "max_shift_hours",
                      value: problem.max_shift_hours ?? 8.0,
                      locked: problem.locked_goal_terms.includes("max_shift_hours"),
                      type: "max_shift",
                      fieldName: "max_shift_hours",
                    });
                    updateProblem({
                      max_shift_hours: null,
                      locked_goal_terms: removeLockedGoalTerm(problem.locked_goal_terms, "max_shift_hours"),
                    });
                  })
                }
              >
                X
              </button>
            </div>
            <ConfigNumberInput
              editable={editable}
              value={problem.max_shift_hours}
              min={0}
              step={0.5}
              onValueChange={(value) => {
                if (value == null) return;
                updateProblem({ max_shift_hours: value });
              }}
              onActivate={(hint) => ensureEditing(hint)}
              focusKey="max-shift-hours"
              style={{ width: "4rem", textAlign: "right", fontFamily: "monospace" }}
            />
            <span className="muted" style={{ fontSize: "0.7rem", marginTop: "0.1rem" }}>hours</span>
          </div>
        </div>
      </div>
    </details>
  );
}

function VrptwFooterRows({
  problem,
  editable,
  showWorkerBlock,
  removedGoalTerms,
  markerKindFor,
  runEditingAction,
  restoreRemovedGoalTerm,
  updateLocked,
  addLockedRow,
}: VrptwFooterRowsProps) {
  const hasHardStructural =
    Object.keys(problem.locked_assignments).length > 0 ||
    removedGoalTerms.some((e) => e.type === "max_shift");

  if (!hasHardStructural) return null;

  return (
    <>
      {removedGoalTerms
        .filter((entry) => entry.type === "max_shift")
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
              <span className="muted">{MAX_SHIFT_HOURS_INFO.label} (removed)</span>
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
                  onActivate={(hint) => {
                    void hint;
                  }}
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
  );
}

// ------------------------------------------------------------------
// Public API
// ------------------------------------------------------------------

/**
 * Build the VRPTW-specific GoalTermsExtension.
 *
 * All VRPTW-specific fields are parsed from `configJson` internally.
 * All VRPTW-specific mutation callbacks are defined internally and closed over the parsed state.
 * ProblemConfigBlocks receives only generic props — no VRPTW types or field names leak out.
 */
export function buildVrptwGoalTermsExtension(p: VrptwGoalTermsExtensionProps): GoalTermsExtension {
  // Parse VRPTW-specific fields from the raw config JSON.
  const { problem } = parseProblemConfig(p.configJson);

  // Derived state — all VRPTW-specific, computed here rather than in ProblemConfigBlocks.
  const workerPrefLocked = p.workerPreferenceKey
    ? problem.locked_goal_terms.includes(p.workerPreferenceKey)
    : false;
  const preferencesEditable = p.editable && !workerPrefLocked;
  const hasWorkerWeight = p.workerPreferenceKey ? p.workerPreferenceKey in problem.weights : false;
  const showWorkerBlock = hasWorkerWeight || problem.driver_preferences.length > 0;

  // VRPTW-specific mutation helpers — all defined internally.
  function updatePreferenceAt(index: number, pref: DriverPref) {
    const next = [...problem.driver_preferences];
    next[index] = pref;
    p.updateProblem({ driver_preferences: next });
  }

  function removePreference(index: number) {
    p.updateProblem({
      driver_preferences: problem.driver_preferences.filter((_, i) => i !== index),
    });
  }

  function addPreference() {
    const w = { ...problem.weights };
    if (p.workerPreferenceKey && w[p.workerPreferenceKey] === undefined) w[p.workerPreferenceKey] = 1;
    p.updateProblem({
      weights: w,
      driver_preferences: [
        ...problem.driver_preferences,
        { vehicle_idx: 0, condition: "avoid_zone", penalty: 1, zone: 4 },
      ],
    });
  }

  function updateLocked(taskKey: string, worker: number | "") {
    const next = { ...problem.locked_assignments };
    if (worker === "") {
      delete next[taskKey];
    } else {
      next[taskKey] = worker;
    }
    p.updateProblem({ locked_assignments: next });
  }

  function addLockedRow() {
    const used = new Set(Object.keys(problem.locked_assignments).map((k) => parseInt(k, 10)));
    let t = 0;
    while (used.has(t) && t < 30) t += 1;
    if (t >= 30) return;
    updateLocked(String(t), 0);
  }

  return {
    keySlots: {
      worker_preference: {
        replaceRow: () => (
          <Fragment>
            <WeightRow
              wkey="worker_preference"
              problem={problem}
              editable={p.editable}
              weightCatalog={p.weightCatalog}
              updateProblem={(patch) => p.runEditingAction(() => p.updateProblem(patch))}
              onActivate={(event) => p.ensureEditing(event)}
            />
            {showWorkerBlock && (
              <WorkerPreferenceExtras
                problem={problem}
                preferencesEditable={preferencesEditable}
                markerKindFor={p.markerKindFor}
                runEditingAction={p.runEditingAction}
                ensureEditing={p.ensureEditing}
                updatePreferenceAt={updatePreferenceAt}
                removePreference={removePreference}
                addPreference={addPreference}
              />
            )}
          </Fragment>
        ),
      },
      waiting_time: {},
      shift_limit: {
        appendAfterRow: () => (
          <MaxShiftHoursDetails
            problem={problem}
            editable={p.editable}
            markerKindFor={p.markerKindFor}
            updateProblem={p.updateProblem}
            runEditingAction={p.runEditingAction}
            ensureEditing={p.ensureEditing}
            rememberRemovedGoalTerm={p.rememberRemovedGoalTerm}
          />
        ),
      },
    },
    footerRows: (
      <VrptwFooterRows
        problem={problem}
        editable={p.editable}
        showWorkerBlock={showWorkerBlock}
        removedGoalTerms={p.removedGoalTerms}
        markerKindFor={p.markerKindFor}
        runEditingAction={p.runEditingAction}
        restoreRemovedGoalTerm={p.restoreRemovedGoalTerm}
        updateLocked={updateLocked}
        addLockedRow={addLockedRow}
      />
    ),
  };
}
