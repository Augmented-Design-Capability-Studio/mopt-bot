import type { ProblemBrief, Session } from "@shared/api";

import { WEIGHT_DISPLAY_ORDER } from "../problemConfig/metadata";
import { parseProblemConfig } from "../problemConfig/serialization";

/** Matches backend `optimization_gate.intrinsic_optimization_ready_agile`: ≥1 goal weight + algorithm. */
export function intrinsicOptimizationReadyAgile(configText: string): boolean {
  const { problem } = parseProblemConfig(configText);
  const weights = problem.weights;
  const hasWorkerWeight = "worker_preference" in weights;
  const showWorkerBlock = hasWorkerWeight || problem.driver_preferences.length > 0;
  const displayWeightKeys = WEIGHT_DISPLAY_ORDER.filter((k) => {
    if (!(k in weights)) return false;
    if (k === "worker_preference") return showWorkerBlock;
    return true;
  });

  const algo = (problem.algorithm ?? "").trim();
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
): boolean {
  const mode = (workflowMode ?? "").toLowerCase();
  if (mode === "agile") {
    return intrinsicOptimizationReadyAgile(configText);
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
): boolean {
  if (!session) return false;
  if (session.optimization_runs_blocked_by_researcher) return false;
  if (session.optimization_allowed) return true;
  return intrinsicOptimizationReady(
    session.workflow_mode,
    configText,
    problemBrief,
    session.optimization_gate_engaged ?? false,
  );
}

/** User-facing hint when Run is disabled (intrinsic gate only; session/terminated handled elsewhere). */
export function runOptimizationDisabledHint(
  session: Session | null,
  configText: string,
  problemBrief: ProblemBrief | null,
): string {
  if (!session) return "";
  if (computeCanRunOptimization(session, configText, problemBrief)) return "";
  if (session.optimization_runs_blocked_by_researcher) {
    return "The researcher has disabled the Run button for this session.";
  }
  if (session.optimization_allowed) return "";

  const mode = (session.workflow_mode ?? "").toLowerCase();
  if (mode === "agile") {
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
