/**
 * Parse and serialize the VRPTW panel config JSON (the full ProblemBlock including
 * VRPTW-specific fields: driver_preferences, max_shift_hours, locked_assignments, etc.).
 */

import { parseAlgorithmParamsFromInner, serializeAlgorithmParams } from "@problemConfig/algorithmCatalog";
import type { DriverPref, ProblemBlock } from "./types";
import { parseZoneValue } from "./metadata";

const LEGACY_CONDITION_MAP: Record<string, string> = {
  zone_d: "avoid_zone",
  express_order: "order_priority",
  shift_over_hours: "shift_over_limit",
};

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
    const rawCondition = typeof o.condition === "string" ? o.condition.trim().toLowerCase() : "";
    const condition = LEGACY_CONDITION_MAP[rawCondition] ?? rawCondition;
    const penalty = typeof o.penalty === "number" ? o.penalty : 0;
    const pref: DriverPref = { vehicle_idx: o.vehicle_idx, condition, penalty };
    if (condition === "avoid_zone") {
      if (rawCondition === "zone_d") {
        pref.zone = 4;
      } else {
        const parsedZone =
          parseZoneValue(o.zone) ?? parseZoneValue(o.zone_letter) ?? parseZoneValue(o.zone_name);
        if (parsedZone != null) pref.zone = parsedZone;
      }
    }
    if (typeof o.limit_minutes === "number") pref.limit_minutes = o.limit_minutes;
    if (condition === "shift_over_limit" && typeof o.hours === "number" && pref.limit_minutes == null) {
      pref.limit_minutes = o.hours * 60;
    }
    if (typeof o.aggregation === "string") pref.aggregation = o.aggregation;
    if (condition === "order_priority") {
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

  // Goal-terms is the canonical persisted form (sanitize_panel_weights strips `weights` and
  // `constraint_types`). Fall back to legacy `weights` only when goal_terms is absent —
  // otherwise VRPTW-specific blocks (worker_preference extras, max-shift threshold, locked
  // assignments) would never see the keys the user just configured.
  const goalTermsRaw =
    inner.goal_terms !== null && typeof inner.goal_terms === "object" && !Array.isArray(inner.goal_terms)
      ? (inner.goal_terms as Record<string, unknown>)
      : null;
  const weightsFromGoalTerms: Record<string, number> = {};
  const constraintTypesFromGoalTerms: Record<string, import("@problemConfig/types").ConstraintType> = {};
  let driverPrefsFromGoalTerms: unknown = undefined;
  let maxShiftHoursFromGoalTerms: number | null = null;
  if (goalTermsRaw) {
    for (const [key, raw] of Object.entries(goalTermsRaw)) {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
      const entry = raw as Record<string, unknown>;
      const w = entry.weight;
      if (typeof w === "number" && Number.isFinite(w)) weightsFromGoalTerms[key] = w;
      const t = entry.type;
      if (t === "soft" || t === "hard" || t === "custom") constraintTypesFromGoalTerms[key] = t;
      const props = entry.properties;
      if (props && typeof props === "object" && !Array.isArray(props)) {
        const propObj = props as Record<string, unknown>;
        if (key === "worker_preference" && Array.isArray(propObj.driver_preferences)) {
          driverPrefsFromGoalTerms = propObj.driver_preferences;
        }
        if (key === "shift_limit" && typeof propObj.max_shift_hours === "number") {
          maxShiftHoursFromGoalTerms = propObj.max_shift_hours;
        }
      }
    }
  }

  const weightsFromLegacy =
    inner.weights !== null && typeof inner.weights === "object" && !Array.isArray(inner.weights)
      ? (inner.weights as Record<string, number>)
      : {};
  const weights =
    Object.keys(weightsFromGoalTerms).length > 0 ? weightsFromGoalTerms : weightsFromLegacy;

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
      max_shift_hours:
        typeof inner.max_shift_hours === "number"
          ? inner.max_shift_hours
          : maxShiftHoursFromGoalTerms,
      locked_assignments:
        inner.locked_assignments !== null &&
        typeof inner.locked_assignments === "object" &&
        !Array.isArray(inner.locked_assignments)
          ? (inner.locked_assignments as Record<string, number>)
          : {},
      driver_preferences: parseDriverPreferences(
        Array.isArray(inner.driver_preferences) ? inner.driver_preferences : driverPrefsFromGoalTerms,
      ),
      use_greedy_init: typeof inner.use_greedy_init === "boolean" ? inner.use_greedy_init : true,
      goal_term_order: Array.isArray(inner.goal_term_order)
        ? (inner.goal_term_order as string[]).filter((e): e is string => typeof e === "string")
        : null,
      constraint_types: (() => {
        const fromInner =
          inner.constraint_types !== null &&
          typeof inner.constraint_types === "object" &&
          !Array.isArray(inner.constraint_types)
            ? (inner.constraint_types as Record<string, import("@problemConfig/types").ConstraintType>)
            : {};
        return { ...fromInner, ...constraintTypesFromGoalTerms };
      })(),
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
  delete problemObject.early_arrival_threshold_min;

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
