import { parseAlgorithmParamsFromInner, serializeAlgorithmParams } from "./algorithmCatalog";
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

  const earlyStop =
    typeof inner.early_stop === "boolean" ? inner.early_stop : true;

  const algorithmStr = typeof inner.algorithm === "string" ? inner.algorithm : "";

  return {
    outerRaw,
    hasProblemKey,
    problem: {
      weights,
      locked_goal_terms: Array.isArray(inner.locked_goal_terms)
        ? inner.locked_goal_terms.filter((entry): entry is string => typeof entry === "string")
        : [],
      only_active_terms: typeof inner.only_active_terms === "boolean" ? inner.only_active_terms : true,
      algorithm: algorithmStr,
      algorithm_params: parseAlgorithmParamsFromInner(inner, algorithmStr),
      epochs: typeof inner.epochs === "number" ? inner.epochs : null,
      early_stop: earlyStop,
      early_stop_patience: typeof inner.early_stop_patience === "number" ? inner.early_stop_patience : null,
      early_stop_epsilon: typeof inner.early_stop_epsilon === "number" ? inner.early_stop_epsilon : null,
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
  problemObject.locked_goal_terms = problem.locked_goal_terms;
  problemObject.only_active_terms = problem.only_active_terms;
  if (problem.algorithm) problemObject.algorithm = problem.algorithm;
  if (problem.epochs !== null) problemObject.epochs = problem.epochs;
  else delete problemObject.epochs;
  if (!problem.early_stop) {
    problemObject.early_stop = false;
    delete problemObject.early_stop_patience;
    delete problemObject.early_stop_epsilon;
  } else {
    delete problemObject.early_stop;
    if (problem.early_stop_patience !== null) problemObject.early_stop_patience = problem.early_stop_patience;
    else delete problemObject.early_stop_patience;
    if (problem.early_stop_epsilon !== null) problemObject.early_stop_epsilon = problem.early_stop_epsilon;
    else delete problemObject.early_stop_epsilon;
  }
  if (problem.pop_size !== null) problemObject.pop_size = problem.pop_size;
  else delete problemObject.pop_size;
  if (problem.random_seed !== null) problemObject.random_seed = problem.random_seed;
  else delete problemObject.random_seed;
  if (problem.shift_hard_penalty !== null) problemObject.shift_hard_penalty = problem.shift_hard_penalty;
  else delete problemObject.shift_hard_penalty;

  problemObject.driver_preferences = problem.driver_preferences;
  problemObject.locked_assignments = problem.locked_assignments;

  const serializedAp = serializeAlgorithmParams(problem.algorithm, problem.algorithm_params);
  if (serializedAp) problemObject.algorithm_params = serializedAp;
  else delete problemObject.algorithm_params;

  const result = hasProblemKey ? { ...outerRaw, problem: problemObject } : problemObject;
  return JSON.stringify(result, null, 2);
}

export function parseActiveWeightKeys(configJson: string): string[] {
  return Object.keys(parseProblemConfig(configJson).problem.weights);
}
