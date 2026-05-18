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

/** Direction-aware delta for one items[] kind: distinguishes added /
 *  removed / edited rows so the synthetic chat note can say
 *  *"1 fact removed"* instead of the ambiguous *"1 fact"*. */
type KindDelta = { added: number; removed: number; edited: number };

function kindDelta(
  prev: ProblemBriefItem[],
  next: ProblemBriefItem[],
  kind: ProblemBriefItem["kind"],
): KindDelta {
  const prevOfKind = prev.filter((item) => item.kind === kind);
  const nextOfKind = next.filter((item) => item.kind === kind);
  const prevById = new Map(prevOfKind.map((item) => [item.id, item] as const));
  const nextById = new Map(nextOfKind.map((item) => [item.id, item] as const));
  let added = 0;
  let edited = 0;
  for (const item of nextOfKind) {
    const before = prevById.get(item.id);
    if (before == null) {
      added += 1;
      continue;
    }
    if (
      before.text !== item.text ||
      before.kind !== item.kind ||
      before.source !== item.source
    ) {
      edited += 1;
    }
  }
  const removed = prevOfKind.filter((item) => !nextById.has(item.id)).length;
  return { added, removed, edited };
}

/** Direction-aware OQ delta. ``answered`` counts OQs whose status flipped
 *  from open → answered this save (the participant typed something).
 *  ``edited`` covers text-only tweaks on existing OQs. */
type QuestionDelta = {
  added: number;
  removed: number;
  edited: number;
  answered: number;
};

function questionDelta(
  prev: ProblemBriefQuestion[],
  next: ProblemBriefQuestion[],
): QuestionDelta {
  const prevById = new Map(prev.map((question) => [question.id, question] as const));
  const nextById = new Map(next.map((question) => [question.id, question] as const));
  let added = 0;
  let edited = 0;
  let answered = 0;
  for (const question of next) {
    const before = prevById.get(question.id);
    if (before == null) {
      added += 1;
      continue;
    }
    const wasAnswered = before.status === "answered";
    const nowAnswered = question.status === "answered" && (question.answer_text ?? "").trim().length > 0;
    if (!wasAnswered && nowAnswered) {
      answered += 1;
      continue;
    }
    if (
      before.text !== question.text ||
      before.status !== question.status ||
      (before.answer_text ?? "") !== (question.answer_text ?? "")
    ) {
      edited += 1;
    }
  }
  const removed = prev.filter((question) => !nextById.has(question.id)).length;
  return { added, removed, edited, answered };
}

export type BriefChangeDelta = {
  facts: KindDelta;
  assumptions: KindDelta;
  questions: QuestionDelta;
  goalSummaryChanged: boolean;
  runSummaryChanged: boolean;
};

export function computeBriefChangeDelta(
  previous: ProblemBrief,
  next: ProblemBrief,
): BriefChangeDelta {
  return {
    facts: kindDelta(previous.items, next.items, "gathered"),
    assumptions: kindDelta(previous.items, next.items, "assumption"),
    questions: questionDelta(previous.open_questions, next.open_questions),
    goalSummaryChanged: previous.goal_summary.trim() !== next.goal_summary.trim(),
    runSummaryChanged: previous.run_summary.trim() !== next.run_summary.trim(),
  };
}

function pluralize(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

function formatKindParts(delta: KindDelta, singular: string, plural: string): string[] {
  const out: string[] = [];
  if (delta.added) out.push(`${pluralize(delta.added, singular, plural)} added`);
  if (delta.removed) out.push(`${pluralize(delta.removed, singular, plural)} removed`);
  if (delta.edited) out.push(`${pluralize(delta.edited, singular, plural)} edited`);
  return out;
}

function formatQuestionParts(delta: QuestionDelta): string[] {
  const out: string[] = [];
  if (delta.added) out.push(`${pluralize(delta.added, "open question", "open questions")} added`);
  if (delta.removed) out.push(`${pluralize(delta.removed, "open question", "open questions")} removed`);
  if (delta.edited) out.push(`${pluralize(delta.edited, "open question", "open questions")} edited`);
  // `answered` counts are not surfaced here — the OQ-answered branch of
  // the chat note shows the literal quotes instead, which is richer.
  return out;
}

/** Human-readable summary of every direction in one phrase. Used as the
 *  trailing ``Summary: …`` clause on synthetic chat notes. */
export function problemBriefChangeSummary(previous: ProblemBrief, next: ProblemBrief): string {
  const delta = computeBriefChangeDelta(previous, next);
  const parts: string[] = [
    ...formatKindParts(delta.facts, "fact", "facts"),
    ...formatKindParts(delta.assumptions, "assumption", "assumptions"),
    ...formatQuestionParts(delta.questions),
  ];
  if (delta.goalSummaryChanged) parts.push("goal summary edited");
  if (delta.runSummaryChanged) parts.push("run summary edited");
  if (parts.length === 0) return "no material changes";
  return parts.join(", ");
}
