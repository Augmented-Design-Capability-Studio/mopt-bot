import { useEffect, useMemo, useRef, useState } from "react";

import type { Message, RunResult, TestProblemMeta } from "@shared/api";

import { defaultParamsForAlgorithm } from "./algorithmCatalog";
import { BlockSection } from "./layout";
import { GoalTermsSection, type RemovedGoalTermEntry } from "./GoalTermsSection";
import { SearchStrategySection } from "./SearchStrategySection";
import { useProblemConfigDiffMarkers } from "./useProblemConfigDiffMarkers";
import { useLockedEditFocus } from "../lib/useLockedEditFocus";
import type { ActivateHint } from "./controls";

import { parseBaseProblemConfig, serializeBaseProblemConfig } from "@problemConfig/baseSerialization";
import type { BaseProblemBlock, ConstraintType } from "@problemConfig/types";
import { getProblemModule } from "../problemRegistry";

// Type-tier base weights. The participant picks a *type* (objective/soft/hard)
// and the weight is derived from it — a clean 1/10/100 penalty hierarchy: a unit
// of the objective costs 1, breaking a soft constraint ~10×, a hard one ~100×.
// "custom" is the manual escape hatch (the participant types the number).
const TIER_BASE_WEIGHT: Record<"objective" | "soft" | "hard", number> = {
  objective: 1,
  soft: 10,
  hard: 100,
};

// Rank applies a small SYMMETRIC nudge around the tier base so reordering
// produces small, visible shifts in BOTH directions (higher rank → up, lower
// rank → down) without ever crossing into another tier. Centered on the middle
// rank: top term ×(1+RANK_NUDGE), bottom ×(1−RANK_NUDGE), middle ×1. The ±10%
// band stays well inside the 10× gap between tiers, so a nudged hard term
// (90–110) never collides with a nudged soft term (9–11).
const RANK_NUDGE = 0.1;
function rankNudgeFactor(rankIndex: number, count: number): number {
  if (count <= 1 || rankIndex < 0) return 1;
  const mid = (count - 1) / 2;
  return 1 + RANK_NUDGE * ((mid - rankIndex) / mid);
}

function orderedDisplayWeightKeys(
  weights: Record<string, number>,
  definitionOrder: string[],
  showWorkerBlock: boolean,
  workerPreferenceKey: string | null,
  goalTermOrder: string[] | null,
): string[] {
  const keys = Object.keys(weights);
  if (showWorkerBlock && workerPreferenceKey && !keys.includes(workerPreferenceKey)) {
    keys.push(workerPreferenceKey);
  }
  const primaryOrder = goalTermOrder && goalTermOrder.length > 0 ? goalTermOrder : definitionOrder;
  const seen = new Set<string>();
  const out: string[] = [];
  for (const k of primaryOrder) {
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
  /** Accepted for call-site compatibility but no longer used: weight suggestion
   * is now a pure function of (type, rank), with no run/chat-derived inputs. */
  runs?: RunResult[];
  messages?: Message[];
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
  const mod = getProblemModule(problemId);

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
    problem.goal_term_order,
  );
  const additionalGoalTermKeys = mod.getAdditionalGoalTermKeys?.(configJson) ?? [];
  for (const extraKey of additionalGoalTermKeys) {
    if (!displayWeightKeys.includes(extraKey)) displayWeightKeys.push(extraKey);
  }

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
        No solver setup has been created yet. Use chat or the Definition tab to clarify priorities and rules first,
        or ask the researcher to push a starter setup.
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

  // Weight is a deterministic function of (type, rank): the type sets the tier
  // (1/10/100) and rank applies a small symmetric nudge. No hidden inputs —
  // earlier versions also folded in the last run's cost share and a regex
  // keyword-match on chat messages, which made the number unexplainable and
  // moved weights behind the participant's back. The agent still retunes
  // explicitly after runs (visible + attributed); this surface just derives a
  // clean starting/edited value from the type and order the participant set.
  function suggestedWeightForType(key: string, type: ConstraintType, rankIndex: number): number {
    if (type === "custom") return problem.weights[key] ?? 1;
    const base = TIER_BASE_WEIGHT[type] ?? TIER_BASE_WEIGHT.objective;
    const suggested = base * rankNudgeFactor(rankIndex, displayWeightKeys.length);
    return Math.max(0.1, Math.round(suggested * 100) / 100);
  }

  function ensureEditing(event?: ActivateHint) {
    if (editable) return;
    markLockedInteraction(
      event?.focusSelector ?? ".problem-config-input, .problem-config-select",
      event?.caretIndex,
      event?.openSelectOnEdit,
    );
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

  function handleConstraintTypeChange(key: string, type: ConstraintType) {
    runEditingAction(() => {
      const currentConstraintTypes = { ...problem.constraint_types };
      const rankIndex = displayWeightKeys.indexOf(key);
      let newWeight = problem.weights[key] ?? 0;
      let newLocked = [...problem.locked_goal_terms];

      if (type === "objective" || type === "soft") {
        // Both are agent-managed; "objective" removes the explicit tag (it's the default)
        newWeight = suggestedWeightForType(key, type, rankIndex);
        newLocked = newLocked.filter((k) => k !== key);
        delete currentConstraintTypes[key]; // "objective" is implicit; "soft" stored below
        if (type === "soft") currentConstraintTypes[key] = "soft";
      } else if (type === "hard") {
        // Hard sits in the top tier (~100) but is still rank-nudged, so a hard
        // term can move up or down a little with its priority. Don't auto-lock —
        // leave the existing lock state alone (user can lock manually if they want).
        newWeight = suggestedWeightForType(key, type, rankIndex);
        currentConstraintTypes[key] = "hard";
      } else {
        // custom: weight unchanged, lock it (custom = user-managed weight,
        // and the lock flag protects it from any future automation paths).
        if (!newLocked.includes(key)) newLocked = [...newLocked, key];
        currentConstraintTypes[key] = "custom";
      }

      updateProblem({
        weights: { ...problem.weights, [key]: newWeight },
        locked_goal_terms: newLocked,
        constraint_types: currentConstraintTypes,
      });
    });
  }

  function handleReorder(newOrder: string[]) {
    runEditingAction(() => {
      const prevOrder = displayWeightKeys;
      const count = newOrder.length;
      const newWeights = { ...problem.weights };
      newOrder.forEach((key, newIdx) => {
        // Lock and type are independent: don't infer "custom" from a locked
        // term. A locked term's value is protected; custom is user-managed.
        const type = problem.constraint_types[key] ?? "objective";
        if (type === "custom" || problem.locked_goal_terms.includes(key)) return;
        // Re-apply ONLY the rank component, RELATIVE to the current weight —
        // never reset to the tier base. The deterministic tier×nudge is just a
        // STARTING seed (set when the participant picks a type); the agent and
        // participant are free to move a weight far from it, and those free /
        // significant adjustments must survive a reorder. So we swap out the old
        // rank factor and swap in the new one (objective/soft/hard alike), which
        // shifts the weight a little with its priority without clobbering the
        // magnitude. Falls back to a fresh seed only when there's no usable
        // current value.
        const current = problem.weights[key];
        if (!Number.isFinite(current)) {
          newWeights[key] = suggestedWeightForType(key, type, newIdx);
          return;
        }
        const prevIdx = prevOrder.indexOf(key);
        const prevFactor = rankNudgeFactor(prevIdx, count);
        const nextFactor = rankNudgeFactor(newIdx, count);
        newWeights[key] =
          Math.max(0.1, Math.round((current as number) * (nextFactor / prevFactor) * 100) / 100);
      });
      updateProblem({
        goal_term_order: newOrder,
        weights: newWeights,
      });
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
        // Bring back any child fields the parent cleared on removal (e.g. VRPTW
        // driver_preferences captured at remove time).
        ...(removed.restorePatch ?? {}),
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
    constraintTypes: problem.constraint_types,
    onConstraintTypeChange: handleConstraintTypeChange,
  });

  return (
    <div
      ref={rootRef}
      className={`problem-config-blocks${editable ? "" : " problem-config-blocks--readonly"}`}
      style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
    >
      <BlockSection title="Goal terms">
        <p className="muted goal-terms-helper-text">
          Drag to set a priority order. The ranking is a hint — actual influence on cost also depends on each term's scale.
        </p>
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
          constraintTypes={problem.constraint_types}
          onConstraintTypeChange={handleConstraintTypeChange}
          onReorder={handleReorder}
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
