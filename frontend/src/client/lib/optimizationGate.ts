import type { ProblemBrief, Session, TestProblemMeta } from "@shared/api";

import { parseBaseProblemConfig } from "@problemConfig/baseSerialization";

/** True iff a companion-field value counts as "present" for the gate.
 *
 * Mirrors the default ``StudyProblemPort.companion_present`` on the backend:
 * lists are present iff non-empty; numbers are present iff strictly positive;
 * strings iff non-blank; everything else uses JS truthiness. Ports with more
 * specific predicates (e.g. a scalar that should treat 0 as valid) currently
 * have no per-port hook on the frontend — extend ``TestProblemMeta`` if/when
 * that becomes needed.
 */
function companionPresent(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "number") return value > 0;
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "object") return Object.keys(value as object).length > 0;
  return Boolean(value);
}

/** True iff the panel has at least one qualifying goal term (mode-agnostic).
 *
 * Mirrors backend ``_qualifying_goal_term_present``: non-companion keys count
 * iff their weight is set; companion-having keys count iff their companion
 * field is present (their weight alone does NOT open the gate). When the port
 * supplies no display keys, any weight counts (any-weight fallback).
 */
function qualifyingGoalTermPresent(
  inner: Record<string, unknown>,
  weights: Record<string, number>,
  weightDisplayKeys: readonly string[],
  gateConditionalCompanions: Readonly<Record<string, string>>,
): boolean {
  const weightKeys = Object.keys(weights);
  if (weightDisplayKeys.length === 0) {
    return weightKeys.length > 0;
  }
  for (const key of weightDisplayKeys) {
    const companionField = gateConditionalCompanions[key];
    if (companionField) {
      if (companionPresent(inner[companionField])) return true;
    } else if (key in weights) {
      return true;
    }
  }
  return false;
}

/**
 * Unified intrinsic gate across agile / waterfall / demo. Mirrors backend
 * ``intrinsic_optimization_ready``.
 *
 * All modes require: algorithm chosen, a qualifying goal term, and
 * ``optimizationGateEngaged``. Waterfall additionally requires no
 * open-status open questions. The only mode-driven branch is the
 * open-questions check.
 */
export function intrinsicOptimizationReady(
  workflowMode: string | undefined,
  configText: string,
  problemBrief: ProblemBrief | null,
  optimizationGateEngaged: boolean,
  problemMeta?: TestProblemMeta | null,
): boolean {
  const mode = (workflowMode ?? "").toLowerCase();
  if (mode !== "agile" && mode !== "waterfall" && mode !== "demo") return false;

  const parsed = parseBaseProblemConfig(configText);
  const { problem } = parsed;
  if (!problem.algorithm.trim()) return false;

  const inner = (parsed.hasProblemKey ? parsed.outerRaw.problem : parsed.outerRaw) as Record<string, unknown>;
  const wdk = problemMeta?.weight_display_keys ?? [];
  const gcc = problemMeta?.gate_conditional_companions ?? {};
  if (!qualifyingGoalTermPresent(inner, problem.weights, wdk, gcc)) return false;

  if (!optimizationGateEngaged) return false;

  if (mode === "waterfall") {
    if (!problemBrief) return false;
    for (const q of problemBrief.open_questions) {
      if (q.status === "open") return false;
    }
  }

  return true;
}

/**
 * Participant may run optimization when not blocked by the researcher and either
 * the stored permit or intrinsic rules apply. Mirrors backend ``can_run_optimization``.
 * Strict symmetry: every mode requires uploaded data.
 */
export function computeCanRunOptimization(
  session: Session | null,
  configText: string,
  problemBrief: ProblemBrief | null,
  hasUploadedData: boolean,
  problemMeta?: TestProblemMeta | null,
): boolean {
  if (!session) return false;
  if (!hasUploadedData) return false;
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

  // Uniform upload check across all modes.
  if (!hasUploadedData) {
    return 'Use the "Upload file(s)..." button in the chat footer to add files (simulated upload) before running optimization.';
  }

  const { problem } = parseBaseProblemConfig(configText);
  const hasSearchStrategy = problem.algorithm.trim().length > 0;
  const wdk = problemMeta?.weight_display_keys ?? [];
  const gcc = problemMeta?.gate_conditional_companions ?? {};
  const inner = (parseBaseProblemConfig(configText).hasProblemKey
    ? parseBaseProblemConfig(configText).outerRaw.problem
    : parseBaseProblemConfig(configText).outerRaw) as Record<string, unknown>;
  const hasGoalTerm = qualifyingGoalTermPresent(inner, problem.weights, wdk, gcc);
  const gateEngaged = session.optimization_gate_engaged ?? false;
  const mode = (session.workflow_mode ?? "").toLowerCase();
  const hasOpenQuestions =
    mode === "waterfall" && (problemBrief?.open_questions.some((q) => q.status === "open") ?? false);

  if (!hasGoalTerm && !hasSearchStrategy) {
    return "Add at least one goal term and choose a search strategy in Problem Config before optimization can run.";
  }
  if (!hasGoalTerm) {
    return "Add at least one goal term in Problem Config (or set a structured property like driver preferences) before optimization can run.";
  }
  if (!hasSearchStrategy) {
    return "Choose a search strategy (algorithm) in Problem Config before optimization can run.";
  }
  if (!gateEngaged) {
    return "Send a message in chat or save a change in Problem Config to engage the optimization gate.";
  }
  if (hasOpenQuestions) {
    return "Answer all open questions in the Definition tab, or ask the researcher to enable runs.";
  }
  return "Optimization is not available yet.";
}
