import { useEffect, useRef, useState } from "react";

import type { ProblemBrief, ProblemBriefItem } from "@shared/api";

const DEFINITION_MARKERS_STORAGE_KEY = "mopt:definition-diff-markers";
const DEFINITION_BASELINE_STORAGE_KEY = "mopt:definition-diff-baseline";

function valueChanged(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) !== JSON.stringify(b ?? null);
}

function readStoredMarkers(): {
  item: Record<string, "new" | "upd">;
  question: Record<string, "new" | "upd">;
} {
  try {
    const raw = sessionStorage.getItem(DEFINITION_MARKERS_STORAGE_KEY);
    if (!raw) return { item: {}, question: {} };
    const parsed = JSON.parse(raw) as {
      item?: Record<string, "new" | "upd">;
      question?: Record<string, "new" | "upd">;
    };
    return {
      item: parsed.item ?? {},
      question: parsed.question ?? {},
    };
  } catch {
    return { item: {}, question: {} };
  }
}

function readStoredBaseline(): ProblemBrief | null {
  try {
    const raw = sessionStorage.getItem(DEFINITION_BASELINE_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as ProblemBrief;
  } catch {
    return null;
  }
}

function gatheredList(items: ProblemBriefItem[]) {
  return items.filter((i) => i.kind === "gathered");
}

function assumptionList(items: ProblemBriefItem[]) {
  return items.filter((i) => i.kind === "assumption");
}

/**
 * When the definition panel is read-only, briefly highlight rows that appear new or changed
 * after an assistant/server update. Also invokes delete-trace markers when rows disappear.
 */
export function useDefinitionExternalFlash(
  problemBrief: ProblemBrief,
  editable: boolean,
  showDeletedMarker: (section: "gathered" | "assumption" | "open", index: number) => void,
) {
  const prevRef = useRef<ProblemBrief | null>(readStoredBaseline());
  const initial = readStoredMarkers();
  const [itemFlash, setItemFlash] = useState<Record<string, "new" | "upd">>(initial.item);
  const [questionFlash, setQuestionFlash] = useState<Record<string, "new" | "upd">>(initial.question);

  useEffect(() => {
    if (editable) {
      return;
    }

    const prev = prevRef.current;
    if (!prev) {
      prevRef.current = problemBrief;
      try {
        sessionStorage.setItem(DEFINITION_BASELINE_STORAGE_KEY, JSON.stringify(problemBrief));
      } catch {
        // best effort only
      }
      return;
    }
    prevRef.current = problemBrief;
    if (!valueChanged(prev, problemBrief)) return;

    const nextItems: Record<string, "new" | "upd"> = {};
    const prevById = new Map(prev.items.map((i) => [i.id, i] as const));
    for (const item of problemBrief.items) {
      if (item.kind === "system") continue;
      const o = prevById.get(item.id);
      if (!o) nextItems[item.id] = "new";
      else if (o.text !== item.text || o.status !== item.status) nextItems[item.id] = "upd";
    }

    const nextQs: Record<string, "new" | "upd"> = {};
    const pq = new Map(prev.open_questions.map((q) => [q.id, q] as const));
    for (const q of problemBrief.open_questions) {
      const o = pq.get(q.id);
      if (!o) nextQs[q.id] = "new";
      else if (
        o.text !== q.text ||
        o.status !== q.status ||
        (o.answer_text ?? "") !== (q.answer_text ?? "")
      ) {
        nextQs[q.id] = "upd";
      }
    }

    const nextItemIds = new Set(problemBrief.items.map((i) => i.id));
    for (const item of prev.items) {
      if (item.kind === "system") continue;
      if (nextItemIds.has(item.id)) continue;
      if (item.kind === "gathered") {
        const idx = gatheredList(prev.items).findIndex((i) => i.id === item.id);
        if (idx >= 0) showDeletedMarker("gathered", idx);
      } else if (item.kind === "assumption") {
        const idx = assumptionList(prev.items).findIndex((i) => i.id === item.id);
        if (idx >= 0) showDeletedMarker("assumption", idx);
      }
    }
    const nextQids = new Set(problemBrief.open_questions.map((q) => q.id));
    for (const q of prev.open_questions) {
      if (nextQids.has(q.id)) continue;
      const idx = prev.open_questions.findIndex((x) => x.id === q.id);
      if (idx >= 0) showDeletedMarker("open", idx);
    }

    // Persist markers until the next external definition update with actual diffs.
    if (Object.keys(nextItems).length > 0 || Object.keys(nextQs).length > 0) {
      setItemFlash(nextItems);
      setQuestionFlash(nextQs);
      try {
        sessionStorage.setItem(
          DEFINITION_MARKERS_STORAGE_KEY,
          JSON.stringify({ item: nextItems, question: nextQs }),
        );
      } catch {
        // best effort only
      }
    }
    try {
      sessionStorage.setItem(DEFINITION_BASELINE_STORAGE_KEY, JSON.stringify(problemBrief));
    } catch {
      // best effort only
    }
  }, [editable, problemBrief, showDeletedMarker]);

  function flashClassForItem(id: string): string {
    const k = itemFlash[id];
    if (k === "new") return "definition-item-external-mark--new";
    if (k === "upd") return "definition-item-external-mark--upd";
    return "";
  }

  function flashClassForQuestion(id: string): string {
    const k = questionFlash[id];
    if (k === "new") return "definition-item-external-mark--new";
    if (k === "upd") return "definition-item-external-mark--upd";
    return "";
  }

  function markerKindForItem(id: string): "new" | "upd" | null {
    return itemFlash[id] ?? null;
  }

  function markerKindForQuestion(id: string): "new" | "upd" | null {
    return questionFlash[id] ?? null;
  }

  return { flashClassForItem, flashClassForQuestion, markerKindForItem, markerKindForQuestion };
}
