import { useEffect, useMemo, useRef, useState } from "react";

import type { TestProblemMeta } from "@shared/api";

import { defaultParamsForAlgorithm } from "./algorithmCatalog";
import { BlockSection } from "./layout";
import { parseProblemConfig, serializeProblemConfig } from "./serialization";
import type { DriverPref, ProblemBlock } from "./types";
import { useProblemConfigDiffMarkers } from "./useProblemConfigDiffMarkers";
import { useLockedEditFocus } from "../lib/useLockedEditFocus";
import { GoalTermsSection, type RemovedGoalTermEntry } from "./GoalTermsSection";
import { WEIGHT_INFO } from "./metadata";
import { SearchStrategySection } from "./SearchStrategySection";
import type { ActivateHint } from "./controls";

function orderedDisplayWeightKeys(
  weights: Record<string, number>,
  definitionOrder: string[],
  showWorkerBlock: boolean,
): string[] {
  const keys = Object.keys(weights);
  if (showWorkerBlock && !keys.includes("worker_preference")) keys.push("worker_preference");
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
  /** From GET /meta/test-problems for `session.test_problem_id`; null uses VRPTW labels/order. */
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
  const { outerRaw, hasProblemKey, problem } = parseProblemConfig(configJson);
  const { markerKindFor } = useProblemConfigDiffMarkers(problem, editable);
  const [removedGoalTerms, setRemovedGoalTerms] = useState<RemovedGoalTermEntry[]>([]);
  useEffect(() => {
    if (editable) return;
    setRemovedGoalTerms([]);
  }, [editable]);

  const weightCatalog = useMemo(() => {
    const defs = problemMeta?.weight_definitions;
    if (defs?.length) {
      const o: Record<string, { label: string; description: string }> = {};
      for (const w of defs) {
        o[w.key] = { label: w.label, description: w.description ?? "" };
      }
      return o;
    }
    return WEIGHT_INFO;
  }, [problemMeta]);

  const definitionKeyOrder = problemMeta?.weight_definitions?.map((w) => w.key) ?? [];
  const extensionUi = problemMeta?.extension_ui ?? "vrptw_extras";

  const hasWorkerWeight = "worker_preference" in problem.weights;
  const showWorkerBlock =
    extensionUi === "vrptw_extras" && (hasWorkerWeight || problem.driver_preferences.length > 0);
  const workerPrefLocked = problem.locked_goal_terms.includes("worker_preference");
  const preferencesEditable = editable && !workerPrefLocked;

  const displayWeightKeys = orderedDisplayWeightKeys(problem.weights, definitionKeyOrder, showWorkerBlock);

  const hasSearch =
    problem.algorithm !== "" ||
    problem.epochs !== null ||
    problem.pop_size !== null ||
    problem.early_stop === false ||
    problem.early_stop_patience !== null ||
    problem.early_stop_epsilon !== null;
  const hasHardStructural =
    extensionUi === "vrptw_extras" &&
    (Object.keys(problem.locked_assignments).length > 0 || problem.max_shift_hours !== null);
  const hasSomething = displayWeightKeys.length > 0 || hasSearch || hasHardStructural;

  if (!hasSomething) {
    return (
      <p className="muted" style={{ fontSize: "0.85rem", padding: "0.35rem 0" }}>
        No solver configuration has been created yet. Use chat or the Definition tab to clarify objectives and
        constraints first, or ask the researcher to push a starter configuration.
      </p>
    );
  }

  function updateProblem(patch: Partial<ProblemBlock>) {
    let algorithm_params = problem.algorithm_params;
    if (patch.algorithm !== undefined && patch.algorithm !== problem.algorithm) {
      algorithm_params =
        patch.algorithm_params !== undefined
          ? patch.algorithm_params
          : defaultParamsForAlgorithm(patch.algorithm);
    } else if (patch.algorithm_params !== undefined) {
      algorithm_params = { ...problem.algorithm_params, ...patch.algorithm_params };
    }
    const nextProblem: ProblemBlock = { ...problem, ...patch, algorithm_params };
    onChange(serializeProblemConfig(outerRaw, hasProblemKey, nextProblem));
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
    } else if (removed.type === "max_shift") {
      updateProblem({
        max_shift_hours: removed.value,
        locked_goal_terms: removed.locked
          ? Array.from(new Set([...problem.locked_goal_terms, removed.key]))
          : problem.locked_goal_terms,
      });
    }
    setRemovedGoalTerms((current) => current.filter((entry) => entry.key !== key));
  }

  function updatePreferenceAt(index: number, pref: DriverPref) {
    const next = [...problem.driver_preferences];
    next[index] = pref;
    updateProblem({ driver_preferences: next });
  }

  function removePreference(index: number) {
    updateProblem({
      driver_preferences: problem.driver_preferences.filter((_, i) => i !== index),
    });
  }

  function addPreference() {
    const w = { ...problem.weights };
    if (w.worker_preference === undefined) w.worker_preference = 1;
    updateProblem({
      weights: w,
      driver_preferences: [
        ...problem.driver_preferences,
        { vehicle_idx: 0, condition: "avoid_zone", penalty: 1, zone: 4 },
      ],
    });
  }

  function updateLocked(taskKey: string, worker: number | "") {
    const next = { ...problem.locked_assignments };
    if (worker === "") {
      delete next[taskKey];
    } else {
      next[taskKey] = worker;
    }
    updateProblem({ locked_assignments: next });
  }

  function addLockedRow() {
    const used = new Set(Object.keys(problem.locked_assignments).map((k) => parseInt(k, 10)));
    let t = 0;
    while (used.has(t) && t < 30) t += 1;
    if (t >= 30) return;
    updateLocked(String(t), 0);
  }

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
          preferencesEditable={preferencesEditable}
          showWorkerBlock={showWorkerBlock}
          extensionUi={extensionUi}
          weightCatalog={weightCatalog}
          displayWeightKeys={displayWeightKeys}
          removedGoalTerms={removedGoalTerms}
          markerKindFor={markerKindFor}
          updateProblem={updateProblem}
          runEditingAction={runEditingAction}
          ensureEditing={ensureEditing}
          rememberRemovedGoalTerm={rememberRemovedGoalTerm}
          restoreRemovedGoalTerm={restoreRemovedGoalTerm}
          updatePreferenceAt={updatePreferenceAt}
          removePreference={removePreference}
          addPreference={addPreference}
          updateLocked={updateLocked}
          addLockedRow={addLockedRow}
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
