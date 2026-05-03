import type { ProblemBrief, ProblemBriefItem, ProblemBriefQuestion } from "@shared/api";

import { DEFINITION_NEW_ROW_PLACEHOLDER } from "./constants";

export function cloneProblemBrief(brief: ProblemBrief): ProblemBrief {
  return {
    ...brief,
    items: brief.items.map((item) => ({ ...item })),
    open_questions: brief.open_questions.map((question) => ({ ...question })),
  };
}

/** Trim/normalize the brief for PATCH and dirty-checks. Answered OQs are sent through
 * to the backend as-is — the server-side classifier rephrases them into gathered facts
 * (or routes hedged answers to assumptions / a simpler follow-up question). */
export function cleanProblemBriefForCompare(brief: ProblemBrief): ProblemBrief {
  return {
    ...brief,
    goal_summary: brief.goal_summary.trim(),
    run_summary: brief.run_summary.trim(),
    items: brief.items
      .map((item) => ({ ...item, text: item.text.trim() }))
      .filter((item) => {
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

function countKindDelta(
  prev: ProblemBriefItem[],
  next: ProblemBriefItem[],
  kind: ProblemBriefItem["kind"],
): number {
  const prevOfKind = prev.filter((item) => item.kind === kind);
  const nextOfKind = next.filter((item) => item.kind === kind);
  const prevById = new Map(prevOfKind.map((item) => [item.id, item] as const));
  const sizeDelta = Math.abs(nextOfKind.length - prevOfKind.length);
  const changedRows = nextOfKind.filter((item) => {
    const before = prevById.get(item.id);
    return (
      before == null ||
      before.text !== item.text ||
      before.kind !== item.kind ||
      before.source !== item.source
    );
  }).length;
  return sizeDelta + changedRows;
}

function countQuestionDelta(
  prev: ProblemBriefQuestion[],
  next: ProblemBriefQuestion[],
): number {
  const prevById = new Map(prev.map((question) => [question.id, question] as const));
  const sizeDelta = Math.abs(next.length - prev.length);
  const changedRows = next.filter((question) => {
    const before = prevById.get(question.id);
    return (
      before == null ||
      before.text !== question.text ||
      before.status !== question.status ||
      (before.answer_text ?? "") !== (question.answer_text ?? "")
    );
  }).length;
  return sizeDelta + changedRows;
}

export function problemBriefChangeSummary(previous: ProblemBrief, next: ProblemBrief): string {
  const factDelta = countKindDelta(previous.items, next.items, "gathered");
  const assumptionDelta = countKindDelta(previous.items, next.items, "assumption");
  const questionDelta = countQuestionDelta(previous.open_questions, next.open_questions);
  const goalChanged = previous.goal_summary.trim() !== next.goal_summary.trim();
  const runSummaryChanged = previous.run_summary.trim() !== next.run_summary.trim();

  const parts: string[] = [];
  if (factDelta) parts.push(`${factDelta} fact${factDelta > 1 ? "s" : ""}`);
  if (assumptionDelta) parts.push(`${assumptionDelta} assumption${assumptionDelta > 1 ? "s" : ""}`);
  if (questionDelta) parts.push(`${questionDelta} open question${questionDelta > 1 ? "s" : ""}`);
  if (goalChanged) parts.push("goal summary");
  if (runSummaryChanged) parts.push("run summary");
  if (parts.length === 0) return "no material changes";
  return parts.join(", ");
}
