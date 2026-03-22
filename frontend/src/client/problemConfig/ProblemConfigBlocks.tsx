import { ALGORITHM_DESC, CONDITION_LABEL, WEIGHT_INFO } from "./metadata";
import { BlockSection, FieldRow } from "./layout";
import { parseProblemConfig, serializeProblemConfig } from "./serialization";
import type { ProblemBlock } from "./types";

/**
 * Renders the solver configuration as structured natural-language blocks with
 * editable inputs instead of a raw JSON textarea.
 */
export type ProblemConfigBlocksProps = {
  configJson: string;
  onChange: (json: string) => void;
  editable: boolean;
};

export function ProblemConfigBlocks({
  configJson,
  onChange,
  editable,
}: ProblemConfigBlocksProps) {
  const { outerRaw, hasProblemKey, problem } = parseProblemConfig(configJson);

  const weightKeys = Object.keys(problem.weights);
  const hasObjectives = weightKeys.length > 0;
  const hasSearch = problem.algorithm !== "" || problem.epochs !== null || problem.pop_size !== null;
  const hasConstraints =
    Object.keys(problem.locked_assignments).length > 0 ||
    problem.driver_preferences.length > 0 ||
    problem.shift_hard_penalty !== null;

  if (!hasObjectives && !hasSearch && !hasConstraints) {
    return (
      <p className="muted" style={{ fontSize: "0.85rem", padding: "0.35rem 0" }}>
        No solver configuration has been created yet. Use chat or the Definition tab to clarify objectives and
        constraints first, or ask the researcher to push a starter configuration.
      </p>
    );
  }

  function updateProblem(patch: Partial<ProblemBlock>) {
    // Keep every form row working against one typed problem object before it is
    // written back to JSON.
    const nextProblem: ProblemBlock = { ...problem, ...patch };
    onChange(serializeProblemConfig(outerRaw, hasProblemKey, nextProblem));
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {hasObjectives && (
        <BlockSection title="Optimization Objectives">
          {weightKeys.map((key) => {
            const info = WEIGHT_INFO[key];
            return (
              <div
                key={key}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "0.6rem",
                  padding: "0.4rem 0",
                  borderBottom: "1px solid var(--border)",
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>{info?.label ?? key}</div>
                  {info && (
                    <div className="muted" style={{ fontSize: "0.75rem", marginTop: "0.1rem" }}>
                      {info.description}
                    </div>
                  )}
                </div>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "flex-end",
                    flexShrink: 0,
                  }}
                >
                  <input
                    type="number"
                    min={0}
                    step={0.5}
                    value={problem.weights[key]}
                    disabled={!editable}
                    onChange={(e) => {
                      const value = parseFloat(e.target.value);
                      updateProblem({
                        weights: { ...problem.weights, [key]: Number.isNaN(value) ? 0 : value },
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
          })}
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
        <BlockSection title="Constraints & Preferences">
          {problem.shift_hard_penalty !== null && (
            <FieldRow label="Shift limit enforcement">
              <span className="muted" style={{ fontSize: "0.8rem" }}>
                Workers who exceed their maximum shift length incur a penalty of{" "}
                <strong style={{ fontFamily: "monospace" }}>{problem.shift_hard_penalty.toLocaleString()}</strong> cost
                units - strongly discouraging overtime.
              </span>
            </FieldRow>
          )}

          {Object.keys(problem.locked_assignments).length > 0 && (
            <FieldRow label="Fixed task assignments">
              <div style={{ display: "flex", flexDirection: "column", gap: "0.15rem" }}>
                {Object.entries(problem.locked_assignments).map(([orderIdx, workerIdx]) => (
                  <span key={orderIdx} className="muted" style={{ fontSize: "0.8rem" }}>
                    Task #{orderIdx} must be handled by Worker {workerIdx}
                  </span>
                ))}
              </div>
            </FieldRow>
          )}

          {problem.driver_preferences.length > 0 && (
            <FieldRow label="Worker preferences (soft)">
              <div style={{ display: "flex", flexDirection: "column", gap: "0.15rem" }}>
                {problem.driver_preferences.map((pref, index) => (
                  <span key={index} className="muted" style={{ fontSize: "0.8rem" }}>
                    Worker {pref.vehicle_idx}: prefers to avoid {CONDITION_LABEL[pref.condition] ?? pref.condition}
                    {" - "}
                    <span style={{ fontFamily: "monospace" }}>+{pref.penalty}</span> penalty per occurrence
                  </span>
                ))}
              </div>
            </FieldRow>
          )}
        </BlockSection>
      )}
    </div>
  );
}
