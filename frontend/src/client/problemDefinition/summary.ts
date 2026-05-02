import type { ProblemBrief, ProblemBriefItem, ProblemBriefQuestion } from "@shared/api";

import { DEFINITION_NEW_ROW_PLACEHOLDER } from "./constants";

function gatheredTextDedupKey(text: string): string {
  return text.trim().toLowerCase();
}

function sentenceStart(s: string): string {
  const t = s.trim();
  if (!t) return t;
  return t.length > 1 ? t[0].toUpperCase() + t.slice(1) : t.toUpperCase();
}

function ensureTerminator(s: string): string {
  let t = s.trim();
  if (!t) return t;
  if (!".!?".includes(t[t.length - 1])) t += ".";
  return sentenceStart(t);
}

/** Mirrors backend `problem_brief._format_answered_open_question_gathered` for PATCH parity. */
function formatPromotedOqGathered(question: string, answer: string): string {
  const a = (answer ?? "").trim();
  if (!a) return "";
  const q = (question ?? "").trim();
  const combined = q ? `${q} — ${a}` : a;
  return ensureTerminator(combined);
}

/** Move answered open questions (with non-empty answer) into gathered items; drop from open_questions. */
export function promoteAnsweredOpenQuestionsToGathered(brief: ProblemBrief): ProblemBrief {
  const seenGathered = new Set(
    brief.items.filter((i) => i.kind === "gathered").map((i) => gatheredTextDedupKey(i.text)),
  );
  const items: ProblemBriefItem[] = [...brief.items];
  const open_questions: ProblemBriefQuestion[] = [];

  for (const question of brief.open_questions) {
    const answerText = (question.answer_text ?? "").trim();
    const isAnswered = question.status === "answered" && answerText.length > 0;
    if (!isAnswered) {
      open_questions.push(question);
      continue;
    }
    const qText = question.text.trim();
    const combined = formatPromotedOqGathered(qText, answerText);
    const key = gatheredTextDedupKey(combined);
    if (!seenGathered.has(key)) {
      seenGathered.add(key);
      items.push({
        id: `item-gathered-from-question-${question.id}`,
        text: combined,
        kind: "gathered",
        source: "user",
      });
    }
  }

  return { ...brief, items, open_questions };
}

export function cloneProblemBrief(brief: ProblemBrief): ProblemBrief {
  return {
    ...brief,
    items: brief.items.map((item) => ({ ...item })),
    open_questions: brief.open_questions.map((question) => ({ ...question })),
  };
}

/** Same cleaning as PATCH /problem-brief (placeholder rows omitted). Used for dirty checks. */
export function cleanProblemBriefForCompare(brief: ProblemBrief): ProblemBrief {
  const trimmed: ProblemBrief = {
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
  return promoteAnsweredOpenQuestionsToGathered(trimmed);
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
