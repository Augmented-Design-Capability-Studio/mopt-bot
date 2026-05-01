import type { ProblemBrief, Session, TestProblemMeta } from "@shared/api";

import { parseBaseProblemConfig } from "@problemConfig/baseSerialization";

/**
 * Matches backend `optimization_gate.intrinsic_optimization_ready_demo`:
 * any non-empty weights dict + algorithm — problem-agnostic (works for both VRPTW and knapsack).
 */
export function intrinsicOptimizationReadyDemo(configText: string): boolean {
  try {
    const { problem } = parseBaseProblemConfig(configText);
    return Object.keys(problem.weights).length > 0 && problem.algorithm.trim().length > 0;
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
  const { outerRaw, hasProblemKey, problem } = parseBaseProblemConfig(configText);
  const weights = problem.weights;
  const algo = (problem.algorithm ?? "").trim();

  // Fallback: if no display keys defined by the module, accept any weight (demo-style).
  if (weightDisplayKeys.length === 0) {
    return Object.keys(weights).length > 0 && algo.length > 0;
  }

  let showWorkerBlock = false;
  if (workerPreferenceKey !== null) {
    const hasWorkerWeight = workerPreferenceKey in weights;
    // driver_preferences is VRPTW-specific; access via raw JSON to stay problem-agnostic
    const inner = (hasProblemKey ? outerRaw.problem : outerRaw) as Record<string, unknown>;
    const hasDriverPrefs = Array.isArray(inner.driver_preferences) && inner.driver_preferences.length > 0;
    showWorkerBlock = hasWorkerWeight || hasDriverPrefs;
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
  configText: string,
): boolean {
  const { problem } = parseBaseProblemConfig(configText);
  const hasGoalTerm = Object.keys(problem.weights).length > 0;
  const hasSearchStrategy = problem.algorithm.trim().length > 0;
  if (!hasGoalTerm && !hasSearchStrategy) return false;
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
    return intrinsicOptimizationReadyWaterfall(problemBrief, optimizationGateEngaged, configText);
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
  hasUploadedData: boolean,
  problemMeta?: TestProblemMeta | null,
): boolean {
  if (!session) return false;
  const mode = (session.workflow_mode ?? "").toLowerCase();
  if ((mode === "agile" || mode === "demo") && !hasUploadedData) return false;
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
  hasUploadedData: boolean,
  problemMeta?: TestProblemMeta | null,
): string {
  if (!session) return "";
  if (computeCanRunOptimization(session, configText, problemBrief, hasUploadedData, problemMeta)) return "";
  if (session.optimization_runs_blocked_by_researcher) {
    return "The researcher has disabled the Run button for this session.";
  }
  if (session.optimization_allowed) return "";

  const mode = (session.workflow_mode ?? "").toLowerCase();
  if (mode === "agile" || mode === "demo") {
    if (!hasUploadedData) {
      return 'Use the "Upload file(s)..." button in the chat footer to add files (simulated upload) before running optimization.';
    }
    return "Add at least one objective term and choose a search algorithm in Problem Config, or ask the researcher to enable runs.";
  }
  if (mode === "waterfall") {
    const { problem } = parseBaseProblemConfig(configText);
    const hasGoalTerm = Object.keys(problem.weights).length > 0;
    const hasSearchStrategy = problem.algorithm.trim().length > 0;
    const hasWaterfallConfig = hasGoalTerm || hasSearchStrategy;
    const hasOpenQuestions = problemBrief?.open_questions.some((q) => q.status === "open") ?? false;

    if (!hasWaterfallConfig && hasOpenQuestions) {
      return "Add at least one goal term or choose a search strategy in Problem Config, then answer all open questions in the Definition tab.";
    }
    if (!hasWaterfallConfig) {
      return "Add at least one goal term or choose a search strategy in Problem Config before optimization can run.";
    }
    if (!session.optimization_gate_engaged) {
      return "Send a chat message or wait until open questions appear in the Definition tab before optimization can run.";
    }
    if (hasOpenQuestions) {
      return "Answer all open questions in the Definition tab, or ask the researcher to enable runs.";
    }
    return "Resolve open questions in the Definition tab, or ask the researcher to enable runs.";
  }
  return "Optimization is not available yet.";
}
