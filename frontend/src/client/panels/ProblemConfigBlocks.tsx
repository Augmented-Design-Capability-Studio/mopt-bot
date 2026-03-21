/**
 * Renders the solver configuration as structured natural-language blocks with
 * editable inputs — instead of a raw JSON textarea.
 *
 * The component is purely display/edit: it parses `configJson`, shows sections
 * for objectives, search strategy, and constraints, and calls `onChange` with
 * updated JSON whenever the user modifies a field.
 */

import type { ReactNode } from "react";

// ─── Static metadata ──────────────────────────────────────────────────────────

/** Human-readable label and explanation for each supported weight alias. */
const WEIGHT_INFO: Record<string, { label: string; description: string }> = {
  travel_time: {
    label: "Travel Time",
    description:
      "Penalizes total time spent in transit between stops. Higher values favour shorter, faster routes.",
  },
  fuel_cost: {
    label: "Fuel & Operating Cost",
    description:
      "Penalizes fuel consumption (scaled from travel time). Higher values favour fuel-efficient routes.",
  },
  deadline_penalty: {
    label: "On-Time Delivery",
    description:
      "Penalizes arriving after a stop's allowed time window. Higher values enforce stricter punctuality.",
  },
  capacity_penalty: {
    label: "Load Capacity Limits",
    description:
      "Penalizes loading beyond a vehicle's capacity. Higher values keep loads within safe limits.",
  },
  workload_balance: {
    label: "Workload Balance",
    description:
      "Penalizes unequal shift lengths across workers. Higher values produce a fairer distribution of work.",
  },
  worker_preference: {
    label: "Worker Preferences",
    description:
      "Penalizes assigning workers to tasks or conditions they prefer to avoid. Higher values respect preferences more strongly.",
  },
  priority_penalty: {
    label: "Priority Order Deadlines",
    description:
      "Penalizes late delivery of urgent or high-priority tasks. Higher values protect critical deadlines.",
  },
};

const ALGORITHM_DESC: Record<string, string> = {
  GA: "Genetic Algorithm — evolves a population of candidate solutions through selection, crossover, and mutation.",
  PSO: "Particle Swarm — a swarm of candidates converge collaboratively toward promising search regions.",
  SA: "Simulated Annealing — cools the search gradually to escape local optima and converge to good solutions.",
  SwarmSA:
    "Swarm Simulated Annealing — combines swarm-based exploration with annealing-style cooling.",
  ACOR: "Ant Colony Optimization (Continuous) — guides search by modelling pheromone accumulation along good paths.",
};

const CONDITION_LABEL: Record<string, string> = {
  zone_d: "trips through a specific congested zone",
  express_order: "priority/express order assignments",
  shift_over_hours: "shifts exceeding a comfortable length",
};

// ─── Types ────────────────────────────────────────────────────────────────────

type DriverPref = { vehicle_idx: number; condition: string; penalty: number };

type ProblemBlock = {
  weights: Record<string, number>;
  only_active_terms: boolean;
  algorithm: string;
  epochs: number | null;
  pop_size: number | null;
  random_seed: number | null;
  shift_hard_penalty: number | null;
  locked_assignments: Record<string, number>;
  driver_preferences: DriverPref[];
};

// ─── Parse / serialize ────────────────────────────────────────────────────────

function parseProblem(json: string): {
  outerRaw: Record<string, unknown>;
  hasProblemKey: boolean;
  p: ProblemBlock;
} {
  let outerRaw: Record<string, unknown> = {};
  try {
    if (json.trim()) outerRaw = JSON.parse(json) as Record<string, unknown>;
  } catch {
    /* invalid JSON — show empty state */
  }
  const hasProblemKey =
    typeof outerRaw.problem === "object" && outerRaw.problem !== null;
  const inner = (
    hasProblemKey ? outerRaw.problem : outerRaw
  ) as Record<string, unknown>;

  const weights =
    inner.weights !== null &&
    typeof inner.weights === "object" &&
    !Array.isArray(inner.weights)
      ? (inner.weights as Record<string, number>)
      : {};

  return {
    outerRaw,
    hasProblemKey,
    p: {
      weights,
      only_active_terms: Boolean(inner.only_active_terms),
      algorithm: typeof inner.algorithm === "string" ? inner.algorithm : "",
      epochs: typeof inner.epochs === "number" ? inner.epochs : null,
      pop_size: typeof inner.pop_size === "number" ? inner.pop_size : null,
      random_seed:
        typeof inner.random_seed === "number" ? inner.random_seed : null,
      shift_hard_penalty:
        typeof inner.shift_hard_penalty === "number"
          ? inner.shift_hard_penalty
          : null,
      locked_assignments:
        inner.locked_assignments !== null &&
        typeof inner.locked_assignments === "object" &&
        !Array.isArray(inner.locked_assignments)
          ? (inner.locked_assignments as Record<string, number>)
          : {},
      driver_preferences: Array.isArray(inner.driver_preferences)
        ? (inner.driver_preferences as DriverPref[])
        : [],
    },
  };
}

function serializeProblem(
  outerRaw: Record<string, unknown>,
  hasProblemKey: boolean,
  p: ProblemBlock,
): string {
  const base = hasProblemKey
    ? (outerRaw.problem as Record<string, unknown>)
    : outerRaw;
  const problemObj: Record<string, unknown> = { ...base };

  problemObj.weights = p.weights;
  problemObj.only_active_terms = p.only_active_terms;
  if (p.algorithm) problemObj.algorithm = p.algorithm;
  if (p.epochs !== null) problemObj.epochs = p.epochs;
  if (p.pop_size !== null) problemObj.pop_size = p.pop_size;
  if (p.random_seed !== null) problemObj.random_seed = p.random_seed;
  if (p.shift_hard_penalty !== null)
    problemObj.shift_hard_penalty = p.shift_hard_penalty;

  const result = hasProblemKey
    ? { ...outerRaw, problem: problemObj }
    : problemObj;
  return JSON.stringify(result, null, 2);
}

// ─── Main component ───────────────────────────────────────────────────────────

export type ProblemConfigBlocksProps = {
  /** Current panel JSON string (may be empty or invalid while loading). */
  configJson: string;
  /** Called with the updated JSON whenever the user changes a field. */
  onChange: (json: string) => void;
  /** When false, all inputs are read-only. */
  editable: boolean;
};

export function ProblemConfigBlocks({
  configJson,
  onChange,
  editable,
}: ProblemConfigBlocksProps) {
  const { outerRaw, hasProblemKey, p } = parseProblem(configJson);

  const weightKeys = Object.keys(p.weights);
  const hasObjectives = weightKeys.length > 0;
  const hasSearch =
    p.algorithm !== "" || p.epochs !== null || p.pop_size !== null;
  const hasConstraints =
    Object.keys(p.locked_assignments).length > 0 ||
    p.driver_preferences.length > 0 ||
    p.shift_hard_penalty !== null;

  if (!hasObjectives && !hasSearch && !hasConstraints) {
    return (
      <p className="muted" style={{ fontSize: "0.85rem", padding: "0.35rem 0" }}>
        No configuration yet. Chat with the assistant to define objectives and
        solver parameters, or ask the researcher to push a starter configuration.
      </p>
    );
  }

  function update(patch: Partial<ProblemBlock>) {
    const next: ProblemBlock = { ...p, ...patch };
    onChange(serializeProblem(outerRaw, hasProblemKey, next));
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {/* ── OPTIMIZATION OBJECTIVES ── */}
      {hasObjectives && (
        <BlockSection title="Optimization Objectives">
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
              fontSize: "0.78rem",
              marginBottom: "0.5rem",
              cursor: editable ? "pointer" : "default",
            }}
            className="muted"
          >
            <input
              type="checkbox"
              checked={p.only_active_terms}
              disabled={!editable}
              onChange={(e) => update({ only_active_terms: e.target.checked })}
            />
            Only score the objectives listed here; treat all others as zero
          </label>

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
                  <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>
                    {info?.label ?? key}
                  </div>
                  {info && (
                    <div
                      className="muted"
                      style={{ fontSize: "0.75rem", marginTop: "0.1rem" }}
                    >
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
                    value={p.weights[key]}
                    disabled={!editable}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      update({
                        weights: { ...p.weights, [key]: isNaN(v) ? 0 : v },
                      });
                    }}
                    style={{
                      width: "5.5rem",
                      textAlign: "right",
                      fontFamily: "monospace",
                    }}
                  />
                  <span
                    className="muted"
                    style={{ fontSize: "0.7rem", marginTop: "0.1rem" }}
                  >
                    weight
                  </span>
                </div>
              </div>
            );
          })}
        </BlockSection>
      )}

      {/* ── SEARCH STRATEGY ── */}
      {hasSearch && (
        <BlockSection title="Search Strategy">
          {p.algorithm && (
            <FieldRow label="Algorithm">
              <select
                value={p.algorithm}
                disabled={!editable}
                onChange={(e) => update({ algorithm: e.target.value })}
                style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
              >
                {["GA", "PSO", "SA", "SwarmSA", "ACOR"].map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
              {ALGORITHM_DESC[p.algorithm] && (
                <div
                  className="muted"
                  style={{ fontSize: "0.75rem", marginTop: "0.25rem" }}
                >
                  {ALGORITHM_DESC[p.algorithm]}
                </div>
              )}
            </FieldRow>
          )}

          {p.epochs !== null && (
            <FieldRow label="Iterations">
              <div
                style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}
              >
                <input
                  type="number"
                  min={1}
                  max={50000}
                  value={p.epochs}
                  disabled={!editable}
                  onChange={(e) => {
                    const v = parseInt(e.target.value);
                    update({ epochs: isNaN(v) ? 1 : Math.max(1, v) });
                  }}
                  style={{ width: "6rem", fontFamily: "monospace" }}
                />
                <span className="muted" style={{ fontSize: "0.75rem" }}>
                  {p.epochs < 100
                    ? "quick (may not fully converge)"
                    : p.epochs < 500
                      ? "moderate"
                      : "thorough"}
                </span>
              </div>
            </FieldRow>
          )}

          {p.pop_size !== null && (
            <FieldRow label="Population / swarm size">
              <input
                type="number"
                min={2}
                max={500}
                value={p.pop_size}
                disabled={!editable}
                onChange={(e) => {
                  const v = parseInt(e.target.value);
                  update({ pop_size: isNaN(v) ? 2 : Math.max(2, v) });
                }}
                style={{ width: "6rem", fontFamily: "monospace" }}
              />
            </FieldRow>
          )}

          {p.random_seed !== null && (
            <FieldRow label="Random seed">
              <div
                style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}
              >
                <input
                  type="number"
                  value={p.random_seed}
                  disabled={!editable}
                  onChange={(e) => {
                    const v = parseInt(e.target.value);
                    update({ random_seed: isNaN(v) ? 0 : v });
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

      {/* ── CONSTRAINTS & PREFERENCES ── */}
      {hasConstraints && (
        <BlockSection title="Constraints & Preferences">
          {p.shift_hard_penalty !== null && (
            <FieldRow label="Shift limit enforcement">
              <span className="muted" style={{ fontSize: "0.8rem" }}>
                Workers who exceed their maximum shift length incur a penalty of{" "}
                <strong style={{ fontFamily: "monospace" }}>
                  {p.shift_hard_penalty.toLocaleString()}
                </strong>{" "}
                cost units — strongly discouraging overtime.
              </span>
            </FieldRow>
          )}

          {Object.keys(p.locked_assignments).length > 0 && (
            <FieldRow label="Fixed task assignments">
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.15rem",
                }}
              >
                {Object.entries(p.locked_assignments).map(
                  ([orderIdx, workerIdx]) => (
                    <span
                      key={orderIdx}
                      className="muted"
                      style={{ fontSize: "0.8rem" }}
                    >
                      Task #{orderIdx} must be handled by Worker {workerIdx}
                    </span>
                  ),
                )}
              </div>
            </FieldRow>
          )}

          {p.driver_preferences.length > 0 && (
            <FieldRow label="Worker preferences (soft)">
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.15rem",
                }}
              >
                {p.driver_preferences.map((pref, i) => (
                  <span key={i} className="muted" style={{ fontSize: "0.8rem" }}>
                    Worker {pref.vehicle_idx}: prefers to avoid{" "}
                    {CONDITION_LABEL[pref.condition] ?? pref.condition}
                    {" — "}
                    <span style={{ fontFamily: "monospace" }}>
                      +{pref.penalty}
                    </span>{" "}
                    penalty per occurrence
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

// ─── Layout helpers ───────────────────────────────────────────────────────────

function BlockSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: "0.68rem",
          textTransform: "uppercase",
          letterSpacing: "0.07em",
          fontWeight: 700,
          color: "var(--fg-muted, #666)",
          marginBottom: "0.35rem",
          paddingBottom: "0.25rem",
          borderBottom: "2px solid var(--border)",
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

function FieldRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.2rem",
        padding: "0.35rem 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div
        style={{
          fontSize: "0.7rem",
          color: "var(--fg-muted, #666)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        {label}
      </div>
      <div>{children}</div>
    </div>
  );
}
