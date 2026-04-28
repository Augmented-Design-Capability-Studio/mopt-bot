import type { TutorialStepId } from "@shared/api";

import type { TutorialCompletionByStepId, TutorialStep } from "./state";

export function nextStepFrom(startId: TutorialStepId | null, steps: TutorialStep[], completion: TutorialCompletionByStepId): TutorialStep | null {
  const startIndex = startId ? steps.findIndex((step) => step.id === startId) : 0;
  const scopedSteps = startIndex >= 0 ? steps.slice(startIndex) : steps;
  return scopedSteps.find((step) => !completion[step.id]) ?? null;
}

export function resolveActiveTutorialStep(
  steps: TutorialStep[],
  completion: TutorialCompletionByStepId,
  stepOverride: TutorialStepId | null,
): TutorialStep | null {
  if (steps.length === 0) return null;
  if (!stepOverride) return nextStepFrom(null, steps, completion);
  const current = steps.find((step) => step.id === stepOverride) ?? null;
  if (!current) return nextStepFrom(null, steps, completion);
  if (!completion[current.id]) return current;
  return nextStepFrom(current.id, steps, completion) ?? current;
}
