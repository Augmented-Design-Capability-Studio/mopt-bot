/**
 * Mirrors backend/app/algorithm_catalog.py and vrptw_problem/optimizer.py.
 * Keep keys and defaults aligned when the solver changes.
 */
export const DEFAULT_EPOCHS = 100;
export const DEFAULT_POP_SIZE = 50;

export const ALLOWED_ALGORITHM_PARAMS: Record<string, readonly string[]> = {
  GA: ["pc", "pm"],
  PSO: ["c1", "c2", "w"],
  SA: ["temp_init", "cooling_rate"],
  SwarmSA: [
    "max_sub_iter",
    "t0",
    "t1",
    "move_count",
    "mutation_rate",
    "mutation_step_size",
    "mutation_step_size_damp",
  ],
  ACOR: ["sample_count", "intent_factor", "zeta"],
};

export const DEFAULT_ALGORITHM_PARAMS: Record<string, Record<string, number>> = {
  GA: { pc: 0.9, pm: 0.05 },
  PSO: { c1: 2.05, c2: 2.05, w: 0.4 },
  SA: { temp_init: 100, cooling_rate: 0.99 },
  SwarmSA: {
    max_sub_iter: 5,
    t0: 1000,
    t1: 1,
    move_count: 5,
    mutation_rate: 0.1,
    mutation_step_size: 0.1,
    mutation_step_size_damp: 0.99,
  },
  ACOR: { sample_count: 25, intent_factor: 0.5, zeta: 1.0 },
};

/** Short labels + hints for the structured config UI. */
export const ALGORITHM_PARAM_FIELD_META: Record<
  string,
  Record<string, { label: string; description: string; step?: number; min?: number; max?: number }>
> = {
  GA: {
    pc: {
      label: "Crossover rate (pc)",
      description: "Probability of blending two parent solutions each generation.",
      step: 0.05,
      min: 0,
      max: 1,
    },
    pm: {
      label: "Mutation rate (pm)",
      description: "Probability of randomly tweaking a candidate each generation.",
      step: 0.01,
      min: 0,
      max: 1,
    },
  },
  PSO: {
    c1: {
      label: "Cognitive coefficient (c1)",
      description: "Pull toward each particle’s own best position.",
      step: 0.05,
    },
    c2: {
      label: "Social coefficient (c2)",
      description: "Pull toward the swarm’s global best position.",
      step: 0.05,
    },
    w: {
      label: "Inertia weight (w)",
      description: "How much each particle keeps its previous velocity.",
      step: 0.05,
      min: 0,
      max: 2,
    },
  },
  SA: {
    temp_init: {
      label: "Initial temperature",
      description: "Starting temperature for simulated annealing.",
      step: 1,
      min: 0.001,
    },
    cooling_rate: {
      label: "Cooling rate",
      description: "Multiplicative cooling per epoch (closer to 1 = slower cooling).",
      step: 0.01,
      min: 0.001,
      max: 0.9999,
    },
  },
  SwarmSA: {
    max_sub_iter: { label: "Max sub-iterations", description: "Inner loop depth per epoch.", step: 1, min: 1 },
    t0: { label: "Temperature t0", description: "High temperature bound.", step: 1, min: 0.001 },
    t1: { label: "Temperature t1", description: "Low temperature bound.", step: 0.01, min: 0.001 },
    move_count: { label: "Move count", description: "Moves per temperature step.", step: 1, min: 1 },
    mutation_rate: {
      label: "Mutation rate",
      description: "Probability of mutation in the swarm layer.",
      step: 0.05,
      min: 0,
      max: 1,
    },
    mutation_step_size: {
      label: "Mutation step size",
      description: "Scale of random perturbations.",
      step: 0.05,
      min: 0,
    },
    mutation_step_size_damp: {
      label: "Mutation step damping",
      description: "Factor applied to step size over time (0–1).",
      step: 0.01,
      min: 0.001,
      max: 0.9999,
    },
  },
  ACOR: {
    sample_count: { label: "Sample count", description: "Ants / samples per iteration.", step: 1, min: 1 },
    intent_factor: {
      label: "Intent factor",
      description: "Exploration vs exploitation balance for the colony.",
      step: 0.05,
      min: 0,
      max: 1,
    },
    zeta: { label: "Zeta", description: "Pheromone emphasis parameter.", step: 0.05, min: 0 },
  },
};

export function defaultParamsForAlgorithm(algorithm: string): Record<string, number> {
  const d = DEFAULT_ALGORITHM_PARAMS[algorithm];
  return d ? { ...d } : {};
}

function valuesClose(a: number, b: number): boolean {
  const fa = Number(a);
  const fb = Number(b);
  if (!Number.isFinite(fa) || !Number.isFinite(fb)) return false;
  return Math.abs(fa - fb) <= 1e-9 * Math.max(1, Math.abs(fb));
}

/** Merge JSON overrides onto catalog defaults for the selected algorithm. */
export function parseAlgorithmParamsFromInner(
  inner: Record<string, unknown>,
  algorithm: string,
): Record<string, number> {
  const defaults = defaultParamsForAlgorithm(algorithm);
  const allowed = ALLOWED_ALGORITHM_PARAMS[algorithm];
  if (!allowed?.length) return {};
  const out = { ...defaults };
  const raw = inner.algorithm_params;
  if (typeof raw === "object" && raw !== null && !Array.isArray(raw)) {
    const o = raw as Record<string, unknown>;
    for (const k of allowed) {
      const v = o[k];
      if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
      else if (typeof v === "string" && v.trim() !== "") {
        const n = parseFloat(v);
        if (!Number.isNaN(n)) out[k] = n;
      }
    }
  }
  return out;
}

/** Persist only non-default values so JSON stays minimal; backend merges defaults at solve time. */
export function serializeAlgorithmParams(
  algorithm: string,
  params: Record<string, number>,
): Record<string, number> | undefined {
  const allowed = ALLOWED_ALGORITHM_PARAMS[algorithm];
  const defaults = defaultParamsForAlgorithm(algorithm);
  if (!allowed?.length) return undefined;
  const ap: Record<string, number> = {};
  for (const k of allowed) {
    const v = params[k];
    if (typeof v !== "number" || !Number.isFinite(v)) continue;
    const d = defaults[k];
    if (d !== undefined && valuesClose(v, d)) continue;
    ap[k] = v;
  }
  return Object.keys(ap).length > 0 ? ap : undefined;
}
