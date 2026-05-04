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

const HARD_WEIGHT = 100;
const SOFT_WEIGHTS_BY_RANK = [5, 3, 2, 1.5, 1, 0.5, 0.25];
function softWeightForRank(rankIndex: number): number {
  return SOFT_WEIGHTS_BY_RANK[Math.min(rankIndex, SOFT_WEIGHTS_BY_RANK.length - 1)] ?? 0.25;
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
  runs?: RunResult[];
  messages?: Message[];
};

export function ProblemConfigBlocks({
  configJson,
  onChange,
  editable,
  onInteractionStart,
  problemMeta = null,
  runs = [],
  messages = [],
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

  function latestCompletedRun(): RunResult | null {
    for (let i = runs.length - 1; i >= 0; i -= 1) {
      const run = runs[i];
      if (run?.ok && run.result && run.request?.problem) return run;
    }
    return null;
  }

  function contributionMagnitudeForKey(key: string, run: RunResult | null): number {
    if (!run?.result || !run.request?.problem) return 0;
    const runProblem = run.request.problem as Record<string, unknown>;
    const runWeights = (runProblem.weights ?? {}) as Record<string, unknown>;
    const w = Number(runWeights[key]);
    if (!Number.isFinite(w) || w === 0) return 0;
    const r = run.result;
    switch (key) {
      case "travel_time":
        return Math.abs(w * Number(r.metrics.total_travel_minutes ?? 0));
      case "shift_limit":
      case "shift_overtime":
        return Math.abs(w * Number(r.metrics.shift_overtime_minutes ?? 0));
      case "lateness_penalty":
        return Math.abs(w * Number(r.violations.time_window_minutes_over ?? 0));
      case "capacity_penalty":
        return Math.abs(w * Number(r.violations.capacity_units_over ?? 0));
      case "workload_balance":
        return Math.abs(w * Number(r.metrics.workload_variance ?? 0));
      case "worker_preference": {
        const prefUnits = Number(r.metrics.driver_preference_penalty ?? r.metrics.driver_preference_units ?? 0);
        return Math.abs(w * prefUnits);
      }
      case "express_miss_penalty":
        return Math.abs(w * Number(r.violations.priority_deadline_misses ?? 0));
      case "waiting_time":
        return Math.abs(w * Number((r as unknown as { metrics?: { wait_minutes_total?: number } }).metrics?.wait_minutes_total ?? 0));
      default:
        return 0;
    }
  }

  function chatEmphasisBoost(key: string): number {
    if (messages.length === 0) return 1;
    const recent = messages
      .filter((m) => m.role === "user")
      .slice(-12)
      .map((m) => m.content.toLowerCase())
      .join(" ");
    if (!recent.trim()) return 1;
    const lexicon: Record<string, RegExp> = {
      travel_time: /\b(travel|distance|fuel|route time|mileage)\b/g,
      shift_limit: /\b(shift|overtime|over[- ]?time|hours|workday|max shift)\b/g,
      lateness_penalty: /\b(deadline|late|lateness|on[- ]?time|time window|punctual)\b/g,
      capacity_penalty: /\b(capacity|overflow|overload|load limit|truck load)\b/g,
      workload_balance: /\b(balance|variance|fairness|even workload|equal routes)\b/g,
      worker_preference: /\b(preference|driver preference|worker preference|preferred)\b/g,
      express_miss_penalty: /\b(express|urgent|vip|sla|priority[-\s]?orders?|rush|critical)\b/gi,
      waiting_time: /\b(wait|idle|idling|queue)\b/g,
    };
    const matches = [...recent.matchAll(lexicon[key] ?? /$^/g)].length;
    return 1 + Math.min(0.5, matches * 0.08);
  }

  function suggestedWeightForType(key: string, type: ConstraintType, rankIndex: number): number {
    if (type === "hard") return HARD_WEIGHT;
    if (type === "custom") return problem.weights[key] ?? 1;
    const base = softWeightForRank(rankIndex >= 0 ? rankIndex : 0);
    const latestRun = latestCompletedRun();
    const ownContribution = contributionMagnitudeForKey(key, latestRun);
    const allContrib =
      displayWeightKeys.reduce((sum, k) => sum + contributionMagnitudeForKey(k, latestRun), 0) || 0;
    const contributionRatio = allContrib > 0 ? ownContribution / allContrib : 0;
    const contributionAdjust = contributionRatio > 0.45 ? 0.75 : contributionRatio < 0.08 ? 1.2 : 1;
    const typeAdjust = type === "objective" ? 1.1 : 1;
    const chatAdjust = chatEmphasisBoost(key);
    const suggested = base * contributionAdjust * typeAdjust * chatAdjust;
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
        newWeight = suggestedWeightForType(key, type, rankIndex);
        if (!newLocked.includes(key)) newLocked = [...newLocked, key];
        currentConstraintTypes[key] = "hard";
      } else {
        // custom: weight unchanged, lock it
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
      const newWeights = { ...problem.weights };
      newOrder.forEach((key, idx) => {
        const type =
          problem.constraint_types[key] ?? (problem.locked_goal_terms.includes(key) ? "custom" : "objective");
        if (type === "objective" || type === "soft") {
          newWeights[key] = suggestedWeightForType(key, type, idx);
        }
        // hard and custom weights stay unchanged
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
