import { useEffect, useRef, useState } from "react";

import type { BaseProblemBlock } from "./types";

export type MarkerKind = "new" | "upd";
const CONFIG_MARKERS_STORAGE_KEY = "mopt:config-diff-markers";
const CONFIG_BASELINE_STORAGE_KEY = "mopt:config-diff-baseline";

function readStoredMarkers(): Record<string, MarkerKind> {
  try {
    const raw = sessionStorage.getItem(CONFIG_MARKERS_STORAGE_KEY);
    if (!raw) return {};
    return (JSON.parse(raw) as Record<string, MarkerKind>) ?? {};
  } catch {
    return {};
  }
}

function readStoredBaseline(): BaseProblemBlock | null {
  try {
    const raw = sessionStorage.getItem(CONFIG_BASELINE_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as BaseProblemBlock;
  } catch {
    return null;
  }
}

function valueChanged(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) !== JSON.stringify(b ?? null);
}

function classifyMarker(prevValue: unknown, nextValue: unknown): MarkerKind {
  const wasEmpty = prevValue == null;
  const isPresent = nextValue != null;
  return wasEmpty && isPresent ? "new" : "upd";
}

function computeMarkers(prev: BaseProblemBlock, next: BaseProblemBlock): Record<string, MarkerKind> {
  const markers: Record<string, MarkerKind> = {};

  const weightKeys = new Set([...Object.keys(prev.weights), ...Object.keys(next.weights)]);
  for (const key of weightKeys) {
    const prevVal = prev.weights[key];
    const nextVal = next.weights[key];
    if (!valueChanged(prevVal, nextVal) || nextVal == null) continue;
    markers[`weight:${key}`] = classifyMarker(prevVal, nextVal);
  }

  const scalarKeys: ReadonlyArray<keyof BaseProblemBlock> = [
    "algorithm",
    "epochs",
    "pop_size",
    "random_seed",
    "early_stop",
    "early_stop_patience",
    "early_stop_epsilon",
    "use_greedy_init",
  ];
  const prevAny = prev as Record<string, unknown>;
  const nextAny = next as Record<string, unknown>;
  for (const key of scalarKeys) {
    const prevVal = prevAny[key];
    const nextVal = nextAny[key];
    if (!valueChanged(prevVal, nextVal) || nextVal == null) continue;
    markers[`field:${String(key)}`] = classifyMarker(prevVal, nextVal);
  }

  const algoParamKeys = new Set([
    ...Object.keys(prev.algorithm_params ?? {}),
    ...Object.keys(next.algorithm_params ?? {}),
  ]);
  for (const key of algoParamKeys) {
    const prevVal = prev.algorithm_params?.[key];
    const nextVal = next.algorithm_params?.[key];
    if (!valueChanged(prevVal, nextVal) || nextVal == null) continue;
    markers[`algo:${key}`] = classifyMarker(prevVal, nextVal);
  }

  return markers;
}

export function useProblemConfigDiffMarkers(problem: BaseProblemBlock, editable: boolean) {
  const prevRef = useRef<BaseProblemBlock | null>(readStoredBaseline());
  const [markers, setMarkers] = useState<Record<string, MarkerKind>>(readStoredMarkers);

  useEffect(() => {
    if (editable) {
      return;
    }
    const prev = prevRef.current;
    if (!prev) {
      prevRef.current = problem;
      try {
        sessionStorage.setItem(CONFIG_BASELINE_STORAGE_KEY, JSON.stringify(problem));
      } catch {
        // best effort only
      }
      return;
    }
    prevRef.current = problem;
    if (!valueChanged(prev, problem)) return;
    const nextMarkers = computeMarkers(prev, problem);
    if (Object.keys(nextMarkers).length === 0) return;
    setMarkers(nextMarkers);
    try {
      sessionStorage.setItem(CONFIG_MARKERS_STORAGE_KEY, JSON.stringify(nextMarkers));
    } catch {
      // best effort only
    }
    try {
      sessionStorage.setItem(CONFIG_BASELINE_STORAGE_KEY, JSON.stringify(problem));
    } catch {
      // best effort only
    }
  }, [editable, problem]);

  function markerKindFor(key: string): MarkerKind | null {
    return markers[key] ?? null;
  }

  return { markerKindFor };
}

