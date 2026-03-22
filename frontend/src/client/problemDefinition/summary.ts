import type { ProblemBrief } from "@shared/api";

export function cloneProblemBrief(brief: ProblemBrief): ProblemBrief {
  return {
    ...brief,
    items: brief.items.map((item) => ({ ...item })),
    open_questions: brief.open_questions.map((question) => ({ ...question })),
  };
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
    return before == null || before.text !== question.text;
  }).length;
  const goalChanged = previous.goal_summary.trim() !== next.goal_summary.trim() ? 1 : 0;
  const total = addedOrRemovedItemCount + changedRows + questionDelta + changedQuestions + goalChanged;
  if (total <= 0) return "no material changes";
  if (total === 1) return "1 brief update";
  return `${total} brief updates`;
}
