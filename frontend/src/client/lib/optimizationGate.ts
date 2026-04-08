import type { ProblemBrief, Session } from "@shared/api";

import { WEIGHT_DISPLAY_ORDER } from "../problemConfig/metadata";
import { parseProblemConfig } from "../problemConfig/serialization";

/** Matches backend `optimization_gate.intrinsic_optimization_ready_agile`. */
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

  const hasSearch =
    problem.algorithm !== "" ||
    problem.epochs !== null ||
    problem.pop_size !== null ||
    problem.early_stop === false ||
    problem.early_stop_patience !== null ||
    problem.early_stop_epsilon !== null;
  const hasHardStructural =
    Object.keys(problem.locked_assignments).length > 0 || problem.shift_hard_penalty !== null;

  return displayWeightKeys.length > 0 || hasSearch || hasHardStructural;
}

function waterfallClarificationMilestoneMet(brief: ProblemBrief): boolean {
  if (brief.goal_summary.trim() !== "") return true;
  return brief.items.some((item) => item.kind !== "system");
}

/** Matches backend `intrinsic_optimization_ready_waterfall`. */
export function intrinsicOptimizationReadyWaterfall(brief: ProblemBrief): boolean {
  const questions = brief.open_questions;
  for (const q of questions) {
    if (q.status === "open") return false;
  }
  if (questions.length === 0) {
    return waterfallClarificationMilestoneMet(brief);
  }
  return true;
}

export function intrinsicOptimizationReady(
  workflowMode: string | undefined,
  configText: string,
  problemBrief: ProblemBrief | null,
): boolean {
  const mode = (workflowMode ?? "").toLowerCase();
  if (mode === "agile") {
    return intrinsicOptimizationReadyAgile(configText);
  }
  if (mode === "waterfall" && problemBrief) {
    return intrinsicOptimizationReadyWaterfall(problemBrief);
  }
  return false;
}

/**
 * Participant may run optimization when the researcher enabled override OR intrinsic rules pass.
 * Mirrors backend `can_run_optimization`.
 */
export function computeCanRunOptimization(
  session: Session | null,
  configText: string,
  problemBrief: ProblemBrief | null,
): boolean {
  if (!session) return false;
  if (session.optimization_allowed) return true;
  return intrinsicOptimizationReady(session.workflow_mode, configText, problemBrief);
}

/** User-facing hint when Run is disabled (intrinsic gate only; session/terminated handled elsewhere). */
export function runOptimizationDisabledHint(
  session: Session | null,
  configText: string,
  problemBrief: ProblemBrief | null,
): string {
  if (!session) return "";
  if (computeCanRunOptimization(session, configText, problemBrief)) return "";
  if (session.optimization_allowed) return "";

  const mode = (session.workflow_mode ?? "").toLowerCase();
  if (mode === "agile") {
    return "Add at least one objective term or solver setting in Problem Config, or ask the researcher to enable runs.";
  }
  if (mode === "waterfall") {
    if (problemBrief?.open_questions.some((q) => q.status === "open")) {
      return "Answer all open questions in the Definition tab, or ask the researcher to enable runs.";
    }
    return "Finish clarifying the problem (goal or gathered facts) and resolve open questions, or ask the researcher to enable runs.";
  }
  return "Optimization is not available yet.";
}
