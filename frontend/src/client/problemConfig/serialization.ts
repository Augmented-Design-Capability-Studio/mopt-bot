import type { ProblemBlock } from "./types";

type ParsedProblemConfig = {
  outerRaw: Record<string, unknown>;
  hasProblemKey: boolean;
  problem: ProblemBlock;
};

/**
 * Keeps problem JSON parsing in one place so form editing and results views use
 * the same derived shape.
 */
export function parseProblemConfig(json: string): ParsedProblemConfig {
  let outerRaw: Record<string, unknown> = {};
  try {
    if (json.trim()) outerRaw = JSON.parse(json) as Record<string, unknown>;
  } catch {
    /* invalid JSON - show empty state */
  }

  const hasProblemKey = typeof outerRaw.problem === "object" && outerRaw.problem !== null;
  const inner = (hasProblemKey ? outerRaw.problem : outerRaw) as Record<string, unknown>;

  const weights =
    inner.weights !== null && typeof inner.weights === "object" && !Array.isArray(inner.weights)
      ? (inner.weights as Record<string, number>)
      : {};

  return {
    outerRaw,
    hasProblemKey,
    problem: {
      weights,
      only_active_terms: typeof inner.only_active_terms === "boolean" ? inner.only_active_terms : true,
      algorithm: typeof inner.algorithm === "string" ? inner.algorithm : "",
      epochs: typeof inner.epochs === "number" ? inner.epochs : null,
      pop_size: typeof inner.pop_size === "number" ? inner.pop_size : null,
      random_seed: typeof inner.random_seed === "number" ? inner.random_seed : null,
      shift_hard_penalty: typeof inner.shift_hard_penalty === "number" ? inner.shift_hard_penalty : null,
      locked_assignments:
        inner.locked_assignments !== null &&
        typeof inner.locked_assignments === "object" &&
        !Array.isArray(inner.locked_assignments)
          ? (inner.locked_assignments as Record<string, number>)
          : {},
      driver_preferences: Array.isArray(inner.driver_preferences)
        ? (inner.driver_preferences as ProblemBlock["driver_preferences"])
        : [],
    },
  };
}

export function serializeProblemConfig(
  outerRaw: Record<string, unknown>,
  hasProblemKey: boolean,
  problem: ProblemBlock,
): string {
  const base = hasProblemKey ? (outerRaw.problem as Record<string, unknown>) : outerRaw;
  const problemObject: Record<string, unknown> = { ...base };

  problemObject.weights = problem.weights;
  problemObject.only_active_terms = problem.only_active_terms;
  if (problem.algorithm) problemObject.algorithm = problem.algorithm;
  if (problem.epochs !== null) problemObject.epochs = problem.epochs;
  if (problem.pop_size !== null) problemObject.pop_size = problem.pop_size;
  if (problem.random_seed !== null) problemObject.random_seed = problem.random_seed;
  if (problem.shift_hard_penalty !== null) problemObject.shift_hard_penalty = problem.shift_hard_penalty;

  const result = hasProblemKey ? { ...outerRaw, problem: problemObject } : problemObject;
  return JSON.stringify(result, null, 2);
}

export function parseActiveWeightKeys(configJson: string): string[] {
  return Object.keys(parseProblemConfig(configJson).problem.weights);
}
