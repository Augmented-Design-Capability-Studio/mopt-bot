import type { ProblemBrief, ProblemBriefQuestion } from "@shared/api";

import { DEFINITION_NEW_ROW_PLACEHOLDER } from "./constants";

export function cloneProblemBrief(brief: ProblemBrief): ProblemBrief {
  return {
    ...brief,
    items: brief.items.map((item) => ({ ...item })),
    open_questions: brief.open_questions.map((question) => ({ ...question })),
  };
}

/** Same cleaning as PATCH /problem-brief (placeholder rows omitted). Used for dirty checks. */
export function cleanProblemBriefForCompare(brief: ProblemBrief): ProblemBrief {
  return {
    ...brief,
    goal_summary: brief.goal_summary.trim(),
    items: brief.items
      .map((item) => ({ ...item, text: item.text.trim() }))
      .filter((item) => {
        if (item.kind === "system") return true;
        if (item.text.length === 0) return false;
        if (
          (item.kind === "gathered" || item.kind === "assumption") &&
          item.text === DEFINITION_NEW_ROW_PLACEHOLDER
        ) {
          return false;
        }
        return true;
      }),
    open_questions: brief.open_questions
      .map((question) => {
        const text = question.text.trim();
        const status: ProblemBriefQuestion["status"] = question.status === "answered" ? "answered" : "open";
        const answerText = (question.answer_text ?? "").trim();
        return {
          ...question,
          text,
          status,
          answer_text: status === "answered" ? (answerText || null) : null,
        };
      })
      .filter((question) => question.text.length > 0),
  };
}

export function isProblemBriefDirtyAfterClean(baseline: ProblemBrief, current: ProblemBrief): boolean {
  return JSON.stringify(cleanProblemBriefForCompare(baseline)) !== JSON.stringify(cleanProblemBriefForCompare(current));
}

export function problemBriefChangeSummary(previous: ProblemBrief, next: ProblemBrief): string {
  const previousItemsById = new Map(previous.items.map((item) => [item.id, item] as const));
  const addedOrRemovedItemCount = Math.abs(next.items.length - previous.items.length);
  const changedRows = next.items.filter((item) => {
    const before = previousItemsById.get(item.id);
    return (
      before == null ||
      before.text !== item.text ||
      before.kind !== item.kind ||
      before.status !== item.status
    );
  }).length;
  const previousQuestionsById = new Map(previous.open_questions.map((question) => [question.id, question] as const));
  const questionDelta = Math.abs(next.open_questions.length - previous.open_questions.length);
  const changedQuestions = next.open_questions.filter((question) => {
    const before = previousQuestionsById.get(question.id);
    return (
      before == null ||
      before.text !== question.text ||
      before.status !== question.status ||
      (before.answer_text ?? "") !== (question.answer_text ?? "")
    );
  }).length;
  const goalChanged = previous.goal_summary.trim() !== next.goal_summary.trim() ? 1 : 0;
  const total = addedOrRemovedItemCount + changedRows + questionDelta + changedQuestions + goalChanged;
  if (total <= 0) return "no material changes";
  if (total === 1) return "1 brief update";
  return `${total} brief updates`;
}
