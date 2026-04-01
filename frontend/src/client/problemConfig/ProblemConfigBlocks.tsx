import { Fragment, type CSSProperties, type ReactNode } from "react";

import {
  ALGORITHM_DESC,
  PREFERENCE_CONDITIONS,
  WEIGHT_DISPLAY_ORDER,
  WEIGHT_INFO,
  WORKER_NAMES,
} from "./metadata";
import { BlockSection, FieldRow } from "./layout";
import { parseProblemConfig, serializeProblemConfig } from "./serialization";
import type { DriverPref, ProblemBlock } from "./types";

/**
 * Renders the solver configuration as structured natural-language blocks with
 * editable inputs instead of a raw JSON textarea.
 */
export type ProblemConfigBlocksProps = {
  configJson: string;
  onChange: (json: string) => void;
  editable: boolean;
  /** When not editable, first pointer interaction enters config edit mode */
  onInteractionStart?: () => void;
};

function workerOptionLabel(vehicleIdx: number): string {
  const name = WORKER_NAMES[vehicleIdx];
  return `${vehicleIdx}: ${name}`;
}

function preferenceConditionLabel(value: string): string {
  return PREFERENCE_CONDITIONS.find((o) => o.value === value)?.label ?? value;
}

/** Locked: button mimic (same as Definition read-only). Edit: real number input. */
function ConfigNumberInput({
  editable,
  value,
  onChange,
  style,
  min,
  max,
  step,
}: {
  editable: boolean;
  value: number;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  style?: CSSProperties;
  min?: number;
  max?: number;
  step?: number;
}) {
  if (!editable) {
    const label = Number.isNaN(value) ? "—" : String(value);
    return (
      <button type="button" className="problem-config-field-mimic" style={style}>
        {label}
      </button>
    );
  }
  return (
    <input
      type="number"
      className="problem-config-input"
      min={min}
      max={max}
      step={step}
      value={Number.isNaN(value) ? "" : value}
      onChange={onChange}
      style={style}
    />
  );
}

/** Select elements cannot be read-only; when locked, show a button that matches input fields. */
function ConfigSelect({
  editable,
  value,
  onChange,
  displayLabel,
  style,
  children,
}: {
  editable: boolean;
  value: string | number;
  onChange: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  displayLabel: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  if (!editable) {
    return (
      <button type="button" className="problem-config-field-mimic" style={style}>
        {displayLabel}
      </button>
    );
  }
  return (
    <select className="problem-config-select" value={value} onChange={onChange} style={style}>
      {children}
    </select>
  );
}

function WeightRow({
  wkey,
  problem,
  editable,
  updateProblem,
}: {
  wkey: string;
  problem: ProblemBlock;
  editable: boolean;
  updateProblem: (patch: Partial<ProblemBlock>) => void;
}) {
  const info = WEIGHT_INFO[wkey];
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
        <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>{info?.label ?? wkey}</div>
        {info && (
          <div className="muted" style={{ fontSize: "0.75rem", marginTop: "0.1rem" }}>
            {info.description}
          </div>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", flexShrink: 0 }}>
        <ConfigNumberInput
          editable={editable}
          value={problem.weights[wkey] ?? 0}
          min={0}
          step={0.5}
          onChange={(e) => {
            const value = parseFloat(e.target.value);
            updateProblem({
              weights: { ...problem.weights, [wkey]: Number.isNaN(value) ? 0 : value },
            });
          }}
          style={{
            width: "5.5rem",
            textAlign: "right",
            fontFamily: "monospace",
          }}
        />
        <span className="muted" style={{ fontSize: "0.7rem", marginTop: "0.1rem" }}>
          weight
        </span>
      </div>
    </div>
  );
}

export function ProblemConfigBlocks({ configJson, onChange, editable, onInteractionStart }: ProblemConfigBlocksProps) {
  const { outerRaw, hasProblemKey, problem } = parseProblemConfig(configJson);

  const hasWorkerWeight = "worker_preference" in problem.weights;
  const showWorkerBlock = hasWorkerWeight || problem.driver_preferences.length > 0;

  const displayWeightKeys = WEIGHT_DISPLAY_ORDER.filter((k) => {
    if (k === "worker_preference") return showWorkerBlock;
    return k in problem.weights;
  });

  const hasSearch =
    problem.algorithm !== "" || problem.epochs !== null || problem.pop_size !== null;
  const hasHardStructural =
    Object.keys(problem.locked_assignments).length > 0 || problem.shift_hard_penalty !== null;

  const hasSomething = displayWeightKeys.length > 0 || hasSearch || hasHardStructural;

  if (!hasSomething) {
    return (
      <p className="muted" style={{ fontSize: "0.85rem", padding: "0.35rem 0" }}>
        No solver configuration has been created yet. Use chat or the Definition tab to clarify objectives and
        constraints first, or ask the researcher to push a starter configuration.
      </p>
    );
  }

  function updateProblem(patch: Partial<ProblemBlock>) {
    const nextProblem: ProblemBlock = { ...problem, ...patch };
    onChange(serializeProblemConfig(outerRaw, hasProblemKey, nextProblem));
  }

  function updatePreferenceAt(index: number, pref: DriverPref) {
    const next = [...problem.driver_preferences];
    next[index] = pref;
    updateProblem({ driver_preferences: next });
  }

  function removePreference(index: number) {
    updateProblem({
      driver_preferences: problem.driver_preferences.filter((_, i) => i !== index),
    });
  }

  function addPreference() {
    const w = { ...problem.weights };
    if (w.worker_preference === undefined) w.worker_preference = 1;
    updateProblem({
      weights: w,
      driver_preferences: [
        ...problem.driver_preferences,
        { vehicle_idx: 0, condition: "zone_d", penalty: 1 },
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
    updateProblem({ locked_assignments: next });
  }

  function addLockedRow() {
    const used = new Set(Object.keys(problem.locked_assignments).map((k) => parseInt(k, 10)));
    let t = 0;
    while (used.has(t) && t < 30) t += 1;
    if (t >= 30) return;
    updateLocked(String(t), 0);
  }

  return (
    <div
      className={`problem-config-blocks${editable ? "" : " problem-config-blocks--readonly"}`}
      style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
      onPointerDownCapture={() => {
        if (!editable) onInteractionStart?.();
      }}
    >
      <BlockSection title="Goal terms">
        {displayWeightKeys.map((key) =>
          key === "worker_preference" ? (
            <Fragment key={key}>
              <WeightRow wkey={key} problem={problem} editable={editable} updateProblem={updateProblem} />
              <details style={{ margin: "0.15rem 0 0", padding: "0.25rem 0" }} className="driver-pref-details">
                <summary
                  style={{
                    cursor: "pointer",
                    fontWeight: 600,
                    fontSize: "0.82rem",
                    userSelect: "none",
                  }}
                >
                  Preference rules
                </summary>
                <div style={{ marginTop: "0.4rem" }}>
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
                        editable={editable}
                        value={pref.vehicle_idx}
                        displayLabel={workerOptionLabel(pref.vehicle_idx)}
                        onChange={(e) =>
                          updatePreferenceAt(index, { ...pref, vehicle_idx: parseInt(e.target.value, 10) })
                        }
                        style={{ fontSize: "0.8rem" }}
                      >
                        {WORKER_NAMES.map((name, vi) => (
                          <option key={name} value={vi}>
                            {vi}: {name}
                          </option>
                        ))}
                      </ConfigSelect>
                      <ConfigSelect
                        editable={editable}
                        value={pref.condition}
                        displayLabel={preferenceConditionLabel(pref.condition)}
                        onChange={(e) => updatePreferenceAt(index, { ...pref, condition: e.target.value })}
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
                          editable={editable}
                          value={pref.penalty}
                          min={0}
                          step={0.5}
                          onChange={(e) => {
                            const value = parseFloat(e.target.value);
                            updatePreferenceAt(index, { ...pref, penalty: Number.isNaN(value) ? 0 : value });
                          }}
                          style={{ width: "4rem", marginLeft: "0.25rem", fontFamily: "monospace" }}
                        />
                      </label>
                      {(pref.condition === "avoid_zone" || pref.condition === "zone_d") && (
                        <label className="muted" style={{ fontSize: "0.75rem" }}>
                          zone 1–5
                          <ConfigNumberInput
                            editable={editable}
                            value={pref.zone ?? 4}
                            min={1}
                            max={5}
                            onChange={(e) =>
                              updatePreferenceAt(index, { ...pref, zone: parseInt(e.target.value, 10) })
                            }
                            style={{ width: "3rem", marginLeft: "0.25rem", fontFamily: "monospace" }}
                          />
                        </label>
                      )}
                      {(pref.condition === "order_priority" || pref.condition === "express_order") && (
                        <ConfigSelect
                          editable={editable}
                          value={pref.order_priority ?? "express"}
                          displayLabel={pref.order_priority ?? "express"}
                          onChange={(e) => updatePreferenceAt(index, { ...pref, order_priority: e.target.value })}
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
                            editable={editable}
                            value={pref.limit_minutes ?? (pref.hours != null ? pref.hours * 60 : 390)}
                            min={1}
                            onChange={(e) => {
                              const v = parseFloat(e.target.value);
                              updatePreferenceAt(index, {
                                ...pref,
                                limit_minutes: Number.isNaN(v) ? 390 : v,
                                hours: undefined,
                              });
                            }}
                            style={{ width: "4.5rem", marginLeft: "0.25rem", fontFamily: "monospace" }}
                          />
                        </label>
                      )}
                      {editable && (
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
                  {editable && (
                    <button type="button" style={{ marginTop: "0.25rem", fontSize: "0.8rem" }} onClick={addPreference}>
                      + Add preference rule
                    </button>
                  )}
                </div>
              </details>
            </Fragment>
          ) : (
            <WeightRow key={key} wkey={key} problem={problem} editable={editable} updateProblem={updateProblem} />
          ),
        )}

        {hasHardStructural && (
          <>
            {problem.shift_hard_penalty !== null && (
              <FieldRow label="Max shift enforcement (penalty)">
                <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                  <ConfigNumberInput
                    editable={editable}
                    value={problem.shift_hard_penalty}
                    min={0}
                    step={100}
                    onChange={(e) => {
                      const value = parseFloat(e.target.value);
                      updateProblem({
                        shift_hard_penalty: Number.isNaN(value) ? 0 : value,
                      });
                    }}
                    style={{ width: "8rem", fontFamily: "monospace" }}
                  />
                  <span className="muted" style={{ fontSize: "0.75rem" }}>
                    Large cost units applied per worker when a shift exceeds the platform maximum — strongly discourages
                    overtime.
                  </span>
                </div>
              </FieldRow>
            )}

            {Object.keys(problem.locked_assignments).length > 0 && (
              <FieldRow label="Fixed task → worker assignments">
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
                        onChange={(e) => updateLocked(taskKey, parseInt(e.target.value, 10))}
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
            {editable && Object.keys(problem.locked_assignments).length < 30 && (
              <button type="button" style={{ fontSize: "0.8rem" }} onClick={addLockedRow}>
                + Add locked assignment
              </button>
            )}
          </>
        )}

        {hasSearch && (
          <>
            <div style={{ marginTop: "0.75rem", fontWeight: 600, fontSize: "0.82rem" }}>Search strategy</div>
            {problem.algorithm && (
              <FieldRow label="Algorithm">
                <ConfigSelect
                  editable={editable}
                  value={problem.algorithm}
                  displayLabel={problem.algorithm}
                  onChange={(e) => updateProblem({ algorithm: e.target.value })}
                  style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
                >
                  {["GA", "PSO", "SA", "SwarmSA", "ACOR"].map((algorithm) => (
                    <option key={algorithm} value={algorithm}>
                      {algorithm}
                    </option>
                  ))}
                </ConfigSelect>
                {ALGORITHM_DESC[problem.algorithm] && (
                  <div className="muted" style={{ fontSize: "0.75rem", marginTop: "0.25rem" }}>
                    {ALGORITHM_DESC[problem.algorithm]}
                  </div>
                )}
              </FieldRow>
            )}

            {problem.epochs !== null && (
              <FieldRow label="Iterations">
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <ConfigNumberInput
                    editable={editable}
                    value={problem.epochs}
                    min={1}
                    max={50000}
                    onChange={(e) => {
                      const value = parseInt(e.target.value);
                      updateProblem({ epochs: Number.isNaN(value) ? 1 : Math.max(1, value) });
                    }}
                    style={{ width: "6rem", fontFamily: "monospace" }}
                  />
                  <span className="muted" style={{ fontSize: "0.75rem" }}>
                    {problem.epochs < 100 ? "quick (may not fully converge)" : problem.epochs < 500 ? "moderate" : "thorough"}
                  </span>
                </div>
              </FieldRow>
            )}

            {problem.pop_size !== null && (
              <FieldRow label="Population / swarm size">
                <ConfigNumberInput
                  editable={editable}
                  value={problem.pop_size}
                  min={2}
                  max={500}
                  onChange={(e) => {
                    const value = parseInt(e.target.value);
                    updateProblem({ pop_size: Number.isNaN(value) ? 2 : Math.max(2, value) });
                  }}
                  style={{ width: "6rem", fontFamily: "monospace" }}
                />
              </FieldRow>
            )}

            {problem.random_seed !== null && (
              <FieldRow label="Random seed">
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <ConfigNumberInput
                    editable={editable}
                    value={problem.random_seed}
                    onChange={(e) => {
                      const value = parseInt(e.target.value);
                      updateProblem({ random_seed: Number.isNaN(value) ? 0 : value });
                    }}
                    style={{ width: "6rem", fontFamily: "monospace" }}
                  />
                  <span className="muted" style={{ fontSize: "0.75rem" }}>
                    fix to reproduce results
                  </span>
                </div>
              </FieldRow>
            )}
          </>
        )}
      </BlockSection>
    </div>
  );
}
