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

  const weightsFromLegacy =
    inner.weights !== null && typeof inner.weights === "object" && !Array.isArray(inner.weights)
      ? (inner.weights as Record<string, number>)
      : {};
  const weightsFromGoalTerms: Record<string, number> = {};
  const constraintTypesFromGoalTerms: Record<string, ConstraintType> = {};
  const rankedKeys: Array<{ key: string; rank: number }> = [];
  if (inner.goal_terms !== null && typeof inner.goal_terms === "object" && !Array.isArray(inner.goal_terms)) {
    for (const [key, entry] of Object.entries(inner.goal_terms as Record<string, unknown>)) {
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
      const e = entry as Record<string, unknown>;
      const w = e.weight;
      if (typeof w === "number" && Number.isFinite(w)) weightsFromGoalTerms[key] = w;
      const t = e.type;
      if (t === "soft" || t === "hard" || t === "custom") constraintTypesFromGoalTerms[key] = t;
      const r = e.rank;
      if (typeof r === "number" && Number.isFinite(r) && r > 0) rankedKeys.push({ key, rank: r });
    }
  }
  const weights = Object.keys(weightsFromGoalTerms).length > 0 ? weightsFromGoalTerms : weightsFromLegacy;

  const earlyStop = typeof inner.early_stop === "boolean" ? inner.early_stop : true;
  const algorithmStr = typeof inner.algorithm === "string" ? inner.algorithm : "";

  const goalTermOrderFromField = Array.isArray(inner.goal_term_order)
    ? inner.goal_term_order.filter((e): e is string => typeof e === "string")
    : null;
  const goalTermOrderFromRanks =
    rankedKeys.length > 0
      ? rankedKeys.sort((a, b) => a.rank - b.rank).map((entry) => entry.key)
      : null;
  const goalTermOrder = goalTermOrderFromRanks ?? goalTermOrderFromField;

  const constraintTypes: Record<string, ConstraintType> = {};
  if (inner.constraint_types !== null && typeof inner.constraint_types === "object" && !Array.isArray(inner.constraint_types)) {
    for (const [k, v] of Object.entries(inner.constraint_types as Record<string, unknown>)) {
      if (v === "hard" || v === "soft" || v === "custom") constraintTypes[k] = v;
    }
  }
  for (const [k, v] of Object.entries(constraintTypesFromGoalTerms)) {
    constraintTypes[k] = v;
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

  const rankByKey = new Map<string, number>();
  if (problem.goal_term_order && problem.goal_term_order.length > 0) {
    problem.goal_term_order.forEach((key, idx) => rankByKey.set(key, idx + 1));
  }
  let maxRank = rankByKey.size;
  const goalTerms: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(problem.weights)) {
    if (typeof value !== "number" || !Number.isFinite(value)) continue;
    let rank = rankByKey.get(key);
    if (rank == null) {
      maxRank += 1;
      rank = maxRank;
    }
    const explicitType = problem.constraint_types[key];
    const type: ConstraintType = explicitType ?? (problem.locked_goal_terms.includes(key) ? "custom" : "objective");
    goalTerms[key] = {
      weight: value,
      type,
      rank,
      ...(problem.locked_goal_terms.includes(key) ? { locked: true } : {}),
    };
  }
  problemObject.goal_terms = goalTerms;
  delete problemObject.weights;
  delete problemObject.constraint_types;
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

  if (problem.goal_term_order && problem.goal_term_order.length > 0) problemObject.goal_term_order = problem.goal_term_order;
  else delete problemObject.goal_term_order;

  const result = hasProblemKey ? { ...outerRaw, problem: problemObject } : problemObject;
  return JSON.stringify(result, null, 2);
}

export function parseActiveWeightKeys(configJson: string): string[] {
  return Object.keys(parseBaseProblemConfig(configJson).problem.weights);
}
