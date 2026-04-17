import type { ProblemBrief, Session, TestProblemMeta } from "@shared/api";

import { parseProblemConfig } from "../problemConfig/serialization";

/**
 * Matches backend `optimization_gate.intrinsic_optimization_ready_demo`:
 * any non-empty weights dict + algorithm — problem-agnostic (works for both VRPTW and knapsack).
 */
export function intrinsicOptimizationReadyDemo(configText: string): boolean {
  try {
    const parsed = JSON.parse(configText) as Record<string, unknown>;
    const problem = (parsed.problem ?? parsed) as Record<string, unknown>;
    const weights = problem.weights;
    const hasAnyWeight =
      typeof weights === "object" && weights !== null && Object.keys(weights).length > 0;
    const algo = String((problem.algorithm as string | undefined) ?? "").trim();
    return hasAnyWeight && algo.length > 0;
  } catch {
    return false;
  }
}

/**
 * Matches backend `optimization_gate.intrinsic_optimization_ready_agile`.
 *
 * `weightDisplayKeys` is the ordered list of keys that count toward the gate — supplied from
 * `TestProblemMeta.weight_display_keys` so the check is problem-agnostic.
 * `workerPreferenceKey` names the one weight key (if any) whose inclusion requires
 * `driver_preferences` to be non-empty; pass `null` for problems without this concept.
 *
 * When `weightDisplayKeys` is empty the function falls back to any-weight logic (same as demo).
 */
export function intrinsicOptimizationReadyAgile(
  configText: string,
  weightDisplayKeys: readonly string[],
  workerPreferenceKey: string | null,
): boolean {
  const { problem } = parseProblemConfig(configText);
  const weights = problem.weights;
  const algo = (problem.algorithm ?? "").trim();

  // Fallback: if no display keys defined by the module, accept any weight (demo-style).
  if (weightDisplayKeys.length === 0) {
    return Object.keys(weights).length > 0 && algo.length > 0;
  }

  let showWorkerBlock = false;
  if (workerPreferenceKey !== null) {
    const hasWorkerWeight = workerPreferenceKey in weights;
    showWorkerBlock = hasWorkerWeight || problem.driver_preferences.length > 0;
  }

  const displayWeightKeys = weightDisplayKeys.filter((k) => {
    if (!(k in weights)) return false;
    if (workerPreferenceKey !== null && k === workerPreferenceKey && !showWorkerBlock) return false;
    return true;
  });

  return displayWeightKeys.length > 0 && algo.length > 0;
}

/** Matches backend `optimization_gate.intrinsic_optimization_ready_waterfall`. */
export function intrinsicOptimizationReadyWaterfall(
  brief: ProblemBrief,
  optimizationGateEngaged: boolean,
): boolean {
  if (!optimizationGateEngaged) return false;
  for (const q of brief.open_questions) {
    if (q.status === "open") return false;
  }
  return true;
}

export function intrinsicOptimizationReady(
  workflowMode: string | undefined,
  configText: string,
  problemBrief: ProblemBrief | null,
  optimizationGateEngaged: boolean,
  problemMeta?: TestProblemMeta | null,
): boolean {
  const mode = (workflowMode ?? "").toLowerCase();
  if (mode === "agile") {
    const wdk = problemMeta?.weight_display_keys ?? [];
    const wpk = problemMeta !== undefined && problemMeta !== null
      ? (problemMeta.worker_preference_key ?? null)
      : null;
    return intrinsicOptimizationReadyAgile(configText, wdk, wpk);
  }
  if (mode === "demo") {
    return intrinsicOptimizationReadyDemo(configText);
  }
  if (mode === "waterfall" && problemBrief) {
    return intrinsicOptimizationReadyWaterfall(problemBrief, optimizationGateEngaged);
  }
  return false;
}

/**
 * Participant may run optimization when not blocked by the researcher and either
 * the stored permit or intrinsic rules apply. Mirrors backend `can_run_optimization`.
 */
export function computeCanRunOptimization(
  session: Session | null,
  configText: string,
  problemBrief: ProblemBrief | null,
  problemMeta?: TestProblemMeta | null,
): boolean {
  if (!session) return false;
  if (session.optimization_runs_blocked_by_researcher) return false;
  if (session.optimization_allowed) return true;
  return intrinsicOptimizationReady(
    session.workflow_mode,
    configText,
    problemBrief,
    session.optimization_gate_engaged ?? false,
    problemMeta,
  );
}

/** User-facing hint when Run is disabled (intrinsic gate only; session/terminated handled elsewhere). */
export function runOptimizationDisabledHint(
  session: Session | null,
  configText: string,
  problemBrief: ProblemBrief | null,
  problemMeta?: TestProblemMeta | null,
): string {
  if (!session) return "";
  if (computeCanRunOptimization(session, configText, problemBrief, problemMeta)) return "";
  if (session.optimization_runs_blocked_by_researcher) {
    return "The researcher has disabled the Run button for this session.";
  }
  if (session.optimization_allowed) return "";

  const mode = (session.workflow_mode ?? "").toLowerCase();
  if (mode === "agile" || mode === "demo") {
    return "Add at least one objective term and choose a search algorithm in Problem Config, or ask the researcher to enable runs.";
  }
  if (mode === "waterfall") {
    if (!session.optimization_gate_engaged) {
      return "Send a chat message or wait until open questions appear in the Definition tab before optimization can run.";
    }
    if (problemBrief?.open_questions.some((q) => q.status === "open")) {
      return "Answer all open questions in the Definition tab, or ask the researcher to enable runs.";
    }
    return "Resolve open questions in the Definition tab, or ask the researcher to enable runs.";
  }
  return "Optimization is not available yet.";
}
