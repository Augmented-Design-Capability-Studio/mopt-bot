import { TUTORIAL_STEP_IDS, type Session, type TutorialStepId } from "@shared/api";

import { getProblemModule } from "../client/problemRegistry";
import { DEFAULT_TUTORIAL_CONTENT } from "./defaultContent";
import type { TutorialCompletionByStepId, TutorialStep } from "./types";

export type { TutorialAction, TutorialContent, TutorialCompletionByStepId, TutorialStep } from "./types";

/**
 * Resolve tutorial step content for the active session. Default steps come
 * from `DEFAULT_TUTORIAL_CONTENT.stepsForMode`; the problem module may either
 * (a) provide a `stepOverrides(mode)` map that's shallow-merged onto each
 * default step, or (b) bypass defaults entirely with its own `stepsForMode`.
 *
 * The list of step IDs is stable across problems — only titles, bodies, and
 * per-step actions vary.
 */
export function getTutorialSteps(problemId: string | null | undefined, mode: string | undefined): TutorialStep[] {
  const module = problemId ? getProblemModule(problemId) : null;
  const content = module?.tutorialContent;

  if (content?.stepsForMode) {
    return content.stepsForMode(mode);
  }

  // DEFAULT_TUTORIAL_CONTENT always defines stepsForMode; non-null assertion
  // is safe here because we own that file.
  const defaults = DEFAULT_TUTORIAL_CONTENT.stepsForMode!(mode);
  if (!content?.stepOverrides) return defaults;

  const overrides = content.stepOverrides(mode);
  return defaults.map((step) => {
    const ov = overrides[step.id];
    return ov ? { ...step, ...ov } : step;
  });
}

export function getTutorialStepOverride(session: Session | null): TutorialStepId | null {
  const step = session?.tutorial_step_override;
  if (!step) return null;
  if (!TUTORIAL_STEP_IDS.includes(step)) return null;
  return step;
}

export function completionFromSession(session: Session | null): TutorialCompletionByStepId {
  return {
    "chat-info": Boolean(session?.tutorial_chat_started),
    "upload-files": Boolean(session?.tutorial_uploaded_files),
    "inspect-definition": Boolean(session?.tutorial_definition_tab_visited),
    "update-definition": Boolean(session?.tutorial_definition_saved),
    "inspect-config": Boolean(session?.tutorial_config_first_saved),
    "first-run": Boolean(session?.tutorial_first_run_done),
    "read-run-summary": Boolean(session?.tutorial_run_summary_read),
    "inspect-results": Boolean(session?.tutorial_results_inspected),
    "explain-run": Boolean(session?.tutorial_explain_used),
    "update-config": Boolean(session?.tutorial_config_saved),
    "second-run": Boolean(session?.tutorial_second_run_done),
    "mark-candidate": Boolean(session?.tutorial_candidate_marked),
    "third-run": Boolean(session?.tutorial_third_run_done),
    "tutorial-complete": Boolean(session?.tutorial_completed),
  };
}
