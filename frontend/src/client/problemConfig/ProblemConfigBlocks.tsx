import {
  ALGORITHM_DESC,
  PREFERENCE_CONDITIONS,
  WEIGHT_GOAL_KEYS,
  WEIGHT_INFO,
  WEIGHT_SOFT_PENALTY_KEYS,
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
};

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
        <input
          type="number"
          min={0}
          step={0.5}
          value={problem.weights[wkey] ?? 0}
          disabled={!editable}
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

export function ProblemConfigBlocks({ configJson, onChange, editable }: ProblemConfigBlocksProps) {
  const { outerRaw, hasProblemKey, problem } = parseProblemConfig(configJson);

  const goalKeys = WEIGHT_GOAL_KEYS.filter((k) => k in problem.weights);
  const softKeys = WEIGHT_SOFT_PENALTY_KEYS.filter((k) => k in problem.weights);
  const hasWorkerWeight = "worker_preference" in problem.weights;
  const showWorkerBlock =
    hasWorkerWeight || problem.driver_preferences.length > 0;
  const wpStrength = problem.weights.worker_preference ?? 0;

  const hasSearch =
    problem.algorithm !== "" || problem.epochs !== null || problem.pop_size !== null;
  const hasHardStructural =
    Object.keys(problem.locked_assignments).length > 0 || problem.shift_hard_penalty !== null;

  const hasObjectives = goalKeys.length > 0 || softKeys.length > 0 || showWorkerBlock;

  const hasConstraints = hasHardStructural;

  if (!hasObjectives && !hasSearch && !hasConstraints) {
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
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {goalKeys.length > 0 && (
        <BlockSection title="Goal terms (routing & efficiency)">
          {goalKeys.map((key) => (
            <WeightRow key={key} wkey={key} problem={problem} editable={editable} updateProblem={updateProblem} />
          ))}
        </BlockSection>
      )}

      {softKeys.length > 0 && (
        <BlockSection title="Soft penalties (violations & lateness)">
          {softKeys.map((key) => (
            <WeightRow key={key} wkey={key} problem={problem} editable={editable} updateProblem={updateProblem} />
          ))}
        </BlockSection>
      )}

      {showWorkerBlock && (
        <BlockSection title="Worker preferences (soft)">
          <p className="muted" style={{ fontSize: "0.75rem", marginTop: 0 }}>
            One global weight scales the sum of per-rule preference cost units (not minutes of travel time). Add rules
            below; multiple workers can share the same condition (e.g. two people avoiding the same zone).
          </p>
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
              <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>
                {WEIGHT_INFO.worker_preference?.label ?? "Preference strength"}
              </div>
              <div className="muted" style={{ fontSize: "0.75rem", marginTop: "0.1rem" }}>
                {WEIGHT_INFO.worker_preference?.description}
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", flexShrink: 0 }}>
              <input
                type="number"
                min={0}
                step={0.5}
                value={wpStrength}
                disabled={!editable}
                onChange={(e) => {
                  const value = parseFloat(e.target.value);
                  updateProblem({
                    weights: {
                      ...problem.weights,
                      worker_preference: Number.isNaN(value) ? 0 : value,
                    },
                  });
                }}
                style={{ width: "5.5rem", textAlign: "right", fontFamily: "monospace" }}
              />
              <span className="muted" style={{ fontSize: "0.7rem", marginTop: "0.1rem" }}>
                weight
              </span>
            </div>
          </div>

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
              <select
                value={pref.vehicle_idx}
                disabled={!editable}
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
              </select>
              <select
                value={pref.condition}
                disabled={!editable}
                onChange={(e) => updatePreferenceAt(index, { ...pref, condition: e.target.value })}
                style={{ fontSize: "0.8rem", maxWidth: "12rem" }}
              >
                {PREFERENCE_CONDITIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <label className="muted" style={{ fontSize: "0.75rem" }}>
                penalty
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  value={pref.penalty}
                  disabled={!editable}
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
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={pref.zone ?? 4}
                    disabled={!editable}
                    onChange={(e) =>
                      updatePreferenceAt(index, { ...pref, zone: parseInt(e.target.value, 10) })
                    }
                    style={{ width: "3rem", marginLeft: "0.25rem", fontFamily: "monospace" }}
                  />
                </label>
              )}
              {(pref.condition === "order_priority" || pref.condition === "express_order") && (
                <select
                  value={pref.order_priority ?? "express"}
                  disabled={!editable}
                  onChange={(e) => updatePreferenceAt(index, { ...pref, order_priority: e.target.value })}
                  style={{ fontSize: "0.8rem" }}
                >
                  <option value="express">express</option>
                  <option value="standard">standard</option>
                </select>
              )}
              {(pref.condition === "shift_over_limit" || pref.condition === "shift_over_hours") && (
                <>
                  <label className="muted" style={{ fontSize: "0.75rem" }}>
                    limit (min)
                    <input
                      type="number"
                      min={1}
                      value={pref.limit_minutes ?? (pref.hours != null ? pref.hours * 60 : 390)}
                      disabled={!editable}
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
                </>
              )}
              {editable && (
                <button type="button" className="muted" style={{ fontSize: "0.75rem" }} onClick={() => removePreference(index)}>
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
        </BlockSection>
      )}

      {hasSearch && (
        <BlockSection title="Search Strategy">
          {problem.algorithm && (
            <FieldRow label="Algorithm">
              <select
                value={problem.algorithm}
                disabled={!editable}
                onChange={(e) => updateProblem({ algorithm: e.target.value })}
                style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
              >
                {["GA", "PSO", "SA", "SwarmSA", "ACOR"].map((algorithm) => (
                  <option key={algorithm} value={algorithm}>
                    {algorithm}
                  </option>
                ))}
              </select>
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
                <input
                  type="number"
                  min={1}
                  max={50000}
                  value={problem.epochs}
                  disabled={!editable}
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
              <input
                type="number"
                min={2}
                max={500}
                value={problem.pop_size}
                disabled={!editable}
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
                <input
                  type="number"
                  value={problem.random_seed}
                  disabled={!editable}
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
        </BlockSection>
      )}

      {hasConstraints && (
        <BlockSection title="Hard / structural constraints">
          {problem.shift_hard_penalty !== null && (
            <FieldRow label="Max shift enforcement (penalty)">
              <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <input
                  type="number"
                  min={0}
                  step={100}
                  value={problem.shift_hard_penalty}
                  disabled={!editable}
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
                    <select
                      value={workerIdx}
                      disabled={!editable}
                      onChange={(e) => updateLocked(taskKey, parseInt(e.target.value, 10))}
                      style={{ fontSize: "0.8rem" }}
                    >
                      {WORKER_NAMES.map((name, vi) => (
                        <option key={name} value={vi}>
                          {vi}: {name}
                        </option>
                      ))}
                    </select>
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
        </BlockSection>
      )}
    </div>
  );
}
