import { useEffect, useRef, useState } from "react";

import type { ProblemBrief, ProblemBriefItem } from "@shared/api";

const FLASH_MS = 2300;

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
  const prevRef = useRef<ProblemBrief | null>(null);
  const [itemFlash, setItemFlash] = useState<Record<string, "new" | "upd">>({});
  const [questionFlash, setQuestionFlash] = useState<Record<string, "new" | "upd">>({});

  useEffect(() => {
    if (editable) {
      prevRef.current = problemBrief;
      setItemFlash({});
      setQuestionFlash({});
      return;
    }

    const prev = prevRef.current;
    prevRef.current = problemBrief;
    if (!prev) return;

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

    if (Object.keys(nextItems).length) setItemFlash(nextItems);
    if (Object.keys(nextQs).length) setQuestionFlash(nextQs);

    const t = window.setTimeout(() => {
      setItemFlash({});
      setQuestionFlash({});
    }, FLASH_MS);
    return () => window.clearTimeout(t);
  }, [editable, problemBrief, showDeletedMarker]);

  function flashClassForItem(id: string): string {
    const k = itemFlash[id];
    if (k === "new") return "definition-item-external-flash definition-item-external-flash--new";
    if (k === "upd") return "definition-item-external-flash definition-item-external-flash--upd";
    return "";
  }

  function flashClassForQuestion(id: string): string {
    const k = questionFlash[id];
    if (k === "new") return "definition-item-external-flash definition-item-external-flash--new";
    if (k === "upd") return "definition-item-external-flash definition-item-external-flash--upd";
    return "";
  }

  return { flashClassForItem, flashClassForQuestion };
}
