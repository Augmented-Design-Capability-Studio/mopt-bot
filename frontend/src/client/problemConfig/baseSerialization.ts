/**
 * Generic parse/serialize for BaseProblemBlock.
 * Works for any problem module — no problem-specific fields.
 * VRPTW-specific serialization lives in vrptw_problem/frontend/serialization.ts.
 * Knapsack serialization lives in knapsack_problem/frontend/serialization.ts.
 */

import { parseAlgorithmParamsFromInner, serializeAlgorithmParams } from "./algorithmCatalog";
import type { BaseProblemBlock, ConstraintType } from "./types";

export type ParsedBaseProblemConfig = {
  outerRaw: Record<string, unknown>;
  hasProblemKey: boolean;
  problem: BaseProblemBlock;
};

export function parseBaseProblemConfig(json: string): ParsedBaseProblemConfig {
  let outerRaw: Record<string, unknown> = {};
  try {
    if (json.trim()) outerRaw = JSON.parse(json) as Record<string, unknown>;
  } catch {
    /* invalid JSON — show empty state */
  }

  const hasProblemKey = typeof outerRaw.problem === "object" && outerRaw.problem !== null;
  const inner = (hasProblemKey ? outerRaw.problem : outerRaw) as Record<string, unknown>;

  const weights =
    inner.weights !== null && typeof inner.weights === "object" && !Array.isArray(inner.weights)
      ? (inner.weights as Record<string, number>)
      : {};

  const earlyStop = typeof inner.early_stop === "boolean" ? inner.early_stop : true;
  const algorithmStr = typeof inner.algorithm === "string" ? inner.algorithm : "";

  const goalTermOrder = Array.isArray(inner.goal_term_order)
    ? inner.goal_term_order.filter((e): e is string => typeof e === "string")
    : null;

  const constraintTypes: Record<string, ConstraintType> = {};
  if (inner.constraint_types !== null && typeof inner.constraint_types === "object" && !Array.isArray(inner.constraint_types)) {
    for (const [k, v] of Object.entries(inner.constraint_types as Record<string, unknown>)) {
      if (v === "hard" || v === "soft" || v === "custom") constraintTypes[k] = v;
    }
  }

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
      use_greedy_init: typeof inner.use_greedy_init === "boolean" ? inner.use_greedy_init : true,
      goal_term_order: goalTermOrder && goalTermOrder.length > 0 ? goalTermOrder : null,
      constraint_types: constraintTypes,
    },
  };
}

export function serializeBaseProblemConfig(
  outerRaw: Record<string, unknown>,
  hasProblemKey: boolean,
  problem: BaseProblemBlock,
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
  if (!problem.use_greedy_init) problemObject.use_greedy_init = false;
  else delete problemObject.use_greedy_init;

  const serializedAp = serializeAlgorithmParams(problem.algorithm, problem.algorithm_params);
  if (serializedAp) problemObject.algorithm_params = serializedAp;
  else delete problemObject.algorithm_params;

  if (problem.goal_term_order && problem.goal_term_order.length > 0) {
    problemObject.goal_term_order = problem.goal_term_order;
  } else {
    delete problemObject.goal_term_order;
  }
  if (problem.constraint_types && Object.keys(problem.constraint_types).length > 0) {
    problemObject.constraint_types = problem.constraint_types;
  } else {
    delete problemObject.constraint_types;
  }

  const result = hasProblemKey ? { ...outerRaw, problem: problemObject } : problemObject;
  return JSON.stringify(result, null, 2);
}

export function parseActiveWeightKeys(configJson: string): string[] {
  return Object.keys(parseBaseProblemConfig(configJson).problem.weights);
}
