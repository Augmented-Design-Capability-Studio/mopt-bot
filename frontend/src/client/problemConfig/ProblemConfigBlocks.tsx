import { useEffect, useMemo, useRef, useState } from "react";

import type { TestProblemMeta } from "@shared/api";

import { defaultParamsForAlgorithm } from "./algorithmCatalog";
import { BlockSection } from "./layout";
import { GoalTermsSection, type RemovedGoalTermEntry } from "./GoalTermsSection";
import { SearchStrategySection } from "./SearchStrategySection";
import { useProblemConfigDiffMarkers } from "./useProblemConfigDiffMarkers";
import { useLockedEditFocus } from "../lib/useLockedEditFocus";
import type { ActivateHint } from "./controls";

import { parseBaseProblemConfig, serializeBaseProblemConfig } from "@problemConfig/baseSerialization";
import type { BaseProblemBlock } from "@problemConfig/types";
import { getProblemModule } from "../problemRegistry";

function orderedDisplayWeightKeys(
  weights: Record<string, number>,
  definitionOrder: string[],
  showWorkerBlock: boolean,
  workerPreferenceKey: string | null,
): string[] {
  const keys = Object.keys(weights);
  if (showWorkerBlock && workerPreferenceKey && !keys.includes(workerPreferenceKey)) {
    keys.push(workerPreferenceKey);
  }
  const seen = new Set<string>();
  const out: string[] = [];
  for (const k of definitionOrder) {
    if (keys.includes(k) && !seen.has(k)) {
      out.push(k);
      seen.add(k);
    }
  }
  for (const k of keys) {
    if (!seen.has(k)) {
      out.push(k);
      seen.add(k);
    }
  }
  return out;
}

/**
 * Renders the solver configuration as structured natural-language blocks with
 * editable inputs instead of a raw JSON textarea.
 */
export type ProblemConfigBlocksProps = {
  configJson: string;
  onChange: (json: string) => void;
  editable: boolean;
  /** When not editable, first pointer interaction enters config edit mode */
  onInteractionStart?: () => void;
  /** From GET /meta/test-problems for `session.test_problem_id`; null uses empty labels. */
  problemMeta?: TestProblemMeta | null;
};

export function ProblemConfigBlocks({
  configJson,
  onChange,
  editable,
  onInteractionStart,
  problemMeta = null,
}: ProblemConfigBlocksProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const { markLockedInteraction } = useLockedEditFocus({
    rootRef,
    editable,
    focusSelector: ".problem-config-input, .problem-config-select",
  });
  const { outerRaw, hasProblemKey, problem } = parseBaseProblemConfig(configJson);
  const { markerKindFor } = useProblemConfigDiffMarkers(problem, editable);
  const [removedGoalTerms, setRemovedGoalTerms] = useState<RemovedGoalTermEntry[]>([]);
  useEffect(() => {
    if (editable) return;
    setRemovedGoalTerms([]);
  }, [editable]);

  // Weight labels and order come from the backend's GET /meta/test-problems response.
  // No problem-specific fallback here — each problem module configures its own weight_definitions.
  const weightCatalog = useMemo(() => {
    const defs = problemMeta?.weight_definitions;
    if (defs?.length) {
      const o: Record<string, { label: string; description: string; direction?: "minimize" | "maximize" }> = {};
      for (const w of defs) {
        o[w.key] = { label: w.label, description: w.description ?? "", direction: w.direction };
      }
      return o;
    }
    return {} as Record<string, { label: string; description: string; direction?: "minimize" | "maximize" }>;
  }, [problemMeta]);

  const definitionKeyOrder = problemMeta?.weight_definitions?.map((w) => w.key) ?? [];
  const workerPreferenceKey = problemMeta?.worker_preference_key ?? null;
  const problemId = problemMeta?.id ?? "";

  // showWorkerBlock: show the worker_preference key in the weight list when either
  // the key is present in problem.weights OR driver_preferences are configured.
  // Access driver_preferences from outerRaw since BaseProblemBlock does not include it.
  const innerRaw = (hasProblemKey ? outerRaw.problem : outerRaw) as Record<string, unknown>;
  const showWorkerBlock =
    workerPreferenceKey !== null &&
    ((workerPreferenceKey in problem.weights) ||
      (Array.isArray(innerRaw.driver_preferences) && (innerRaw.driver_preferences as unknown[]).length > 0));

  const displayWeightKeys = orderedDisplayWeightKeys(
    problem.weights,
    definitionKeyOrder,
    showWorkerBlock,
    workerPreferenceKey,
  );

  const hasSearch =
    problem.algorithm !== "" ||
    problem.epochs !== null ||
    problem.pop_size !== null ||
    problem.early_stop === false ||
    problem.early_stop_patience !== null ||
    problem.early_stop_epsilon !== null;
  const hasSomething = displayWeightKeys.length > 0 || hasSearch;

  if (!hasSomething) {
    return (
      <p className="muted" style={{ fontSize: "0.85rem", padding: "0.35rem 0" }}>
        No solver configuration has been created yet. Use chat or the Definition tab to clarify objectives and
        constraints first, or ask the researcher to push a starter configuration.
      </p>
    );
  }

  function updateProblem(patch: Record<string, unknown>) {
    const algoPatch = patch.algorithm as string | undefined;
    const paramsPatch = patch.algorithm_params as Record<string, number> | undefined;
    let algorithm_params = problem.algorithm_params;
    if (algoPatch !== undefined && algoPatch !== problem.algorithm) {
      algorithm_params =
        paramsPatch !== undefined ? paramsPatch : defaultParamsForAlgorithm(algoPatch);
    } else if (paramsPatch !== undefined) {
      algorithm_params = { ...problem.algorithm_params, ...paramsPatch };
    }
    const nextProblem: BaseProblemBlock = {
      ...problem,
      ...(patch as Partial<BaseProblemBlock>),
      algorithm_params,
    };
    // Merge all patch fields (including non-base, problem-module-specific ones) into outerRaw
    // so serializeBaseProblemConfig preserves them unchanged in the output JSON.
    const updatedOuterRaw = hasProblemKey
      ? { ...outerRaw, problem: { ...(outerRaw.problem as Record<string, unknown>), ...patch } }
      : { ...outerRaw, ...patch };
    onChange(serializeBaseProblemConfig(updatedOuterRaw, hasProblemKey, nextProblem));
  }

  function ensureEditing(event?: ActivateHint) {
    if (editable) return;
    markLockedInteraction(event?.focusSelector ?? ".problem-config-input, .problem-config-select", event?.caretIndex);
    onInteractionStart?.();
  }

  function runEditingAction(action: () => void, event?: ActivateHint) {
    if (!editable) ensureEditing(event);
    action();
  }

  function rememberRemovedGoalTerm(entry: RemovedGoalTermEntry) {
    setRemovedGoalTerms((current) => {
      if (current.some((row) => row.key === entry.key)) return current;
      return [...current, entry];
    });
  }

  function restoreRemovedGoalTerm(key: string) {
    const removed = removedGoalTerms.find((entry) => entry.key === key);
    if (!removed) return;
    if (removed.type === "weight") {
      updateProblem({
        weights: { ...problem.weights, [removed.key]: removed.value },
        locked_goal_terms: removed.locked
          ? Array.from(new Set([...problem.locked_goal_terms, removed.key]))
          : problem.locked_goal_terms,
      });
    } else if (removed.fieldName) {
      // Non-weight removable field — uses fieldName stored by the problem-module extension.
      updateProblem({
        [removed.fieldName]: removed.value,
        locked_goal_terms: removed.locked
          ? Array.from(new Set([...problem.locked_goal_terms, removed.key]))
          : problem.locked_goal_terms,
      });
    }
    setRemovedGoalTerms((current) => current.filter((entry) => entry.key !== key));
  }

  // Build the problem-specific GoalTermsExtension via the registry.
  // No problem-specific imports — the registry resolves them by problemId.
  const mod = getProblemModule(problemId);
  const extension = mod.buildGoalTermsExtension?.({
    configJson,
    workerPreferenceKey,
    editable,
    removedGoalTerms,
    markerKindFor,
    weightCatalog,
    updateProblem,
    runEditingAction,
    ensureEditing,
    rememberRemovedGoalTerm,
    restoreRemovedGoalTerm,
  });

  return (
    <div
      ref={rootRef}
      className={`problem-config-blocks${editable ? "" : " problem-config-blocks--readonly"}`}
      style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
    >
      <BlockSection title="Goal terms">
        <GoalTermsSection
          problem={problem}
          editable={editable}
          weightCatalog={weightCatalog}
          displayWeightKeys={displayWeightKeys}
          removedGoalTerms={removedGoalTerms}
          markerKindFor={markerKindFor}
          updateProblem={updateProblem}
          runEditingAction={runEditingAction}
          ensureEditing={ensureEditing}
          rememberRemovedGoalTerm={rememberRemovedGoalTerm}
          restoreRemovedGoalTerm={restoreRemovedGoalTerm}
          extension={extension}
        />
      </BlockSection>

      {hasSearch ? (
        <BlockSection title="Search strategy">
          <SearchStrategySection
            problem={problem}
            editable={editable}
            markerKindFor={markerKindFor}
            updateProblem={updateProblem}
            runEditingAction={runEditingAction}
            ensureEditing={ensureEditing}
          />
        </BlockSection>
      ) : null}
    </div>
  );
}
