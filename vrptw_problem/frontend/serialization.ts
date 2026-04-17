/**
 * Parse and serialize the VRPTW panel config JSON (the full ProblemBlock including
 * VRPTW-specific fields: driver_preferences, max_shift_hours, locked_assignments, etc.).
 */

import { parseAlgorithmParamsFromInner, serializeAlgorithmParams } from "@problemConfig/algorithmCatalog";
import type { DriverPref, ProblemBlock } from "./types";

function normalizeOrderPriority(raw: unknown): "express" | "standard" {
  const s = typeof raw === "string" ? raw.trim().toLowerCase() : "";
  if (s === "low" || s === "normal" || s === "std" || s === "default") return "standard";
  if (s === "high" || s === "vip" || s === "priority" || s === "express_line" || s === "exp") return "express";
  if (s === "express" || s === "standard") return s;
  return "standard";
}

function parseDriverPreferences(raw: unknown): DriverPref[] {
  if (!Array.isArray(raw)) return [];
  const out: DriverPref[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
    const o = entry as Record<string, unknown>;
    if (typeof o.vehicle_idx !== "number") continue;
    const condition = typeof o.condition === "string" ? o.condition : "";
    const penalty = typeof o.penalty === "number" ? o.penalty : 0;
    const pref: DriverPref = { vehicle_idx: o.vehicle_idx, condition, penalty };
    if (typeof o.zone === "number") pref.zone = o.zone;
    if (typeof o.limit_minutes === "number") pref.limit_minutes = o.limit_minutes;
    if (typeof o.hours === "number") pref.hours = o.hours;
    if (typeof o.aggregation === "string") pref.aggregation = o.aggregation;
    if (condition === "order_priority" || condition === "express_order") {
      pref.order_priority = normalizeOrderPriority(o.order_priority);
    }
    out.push(pref);
  }
  return out;
}

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
      max_shift_hours: typeof inner.max_shift_hours === "number" ? inner.max_shift_hours : null,
      early_arrival_threshold_min: typeof inner.early_arrival_threshold_min === "number" ? inner.early_arrival_threshold_min : null,
      locked_assignments:
        inner.locked_assignments !== null &&
        typeof inner.locked_assignments === "object" &&
        !Array.isArray(inner.locked_assignments)
          ? (inner.locked_assignments as Record<string, number>)
          : {},
      driver_preferences: parseDriverPreferences(inner.driver_preferences),
      use_greedy_init: typeof inner.use_greedy_init === "boolean" ? inner.use_greedy_init : true,
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
  if (problem.max_shift_hours !== null) problemObject.max_shift_hours = problem.max_shift_hours;
  else delete problemObject.max_shift_hours;
  if (problem.early_arrival_threshold_min !== null) problemObject.early_arrival_threshold_min = problem.early_arrival_threshold_min;
  else delete problemObject.early_arrival_threshold_min;

  if (!problem.use_greedy_init) problemObject.use_greedy_init = false;
  else delete problemObject.use_greedy_init;
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
