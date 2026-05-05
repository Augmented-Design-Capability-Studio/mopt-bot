import type { RunResult } from "@shared/api";
import type { TutorialContent } from "@tutorial/types";
import type { GoalTermsExtension } from "./GoalTermsSection";
import type { MarkerKind } from "./useProblemConfigDiffMarkers";
import type { ActivateHint } from "./controls";
import type { RemovedGoalTermEntry } from "./GoalTermsSection";
import type { ConstraintType } from "./types";

export type { RunResult };

/** Props passed to each problem visualization tab component. */
export type ProblemVizProps = {
  currentRun: RunResult;
};

/** A single visualization tab contributed by a problem module. */
export type ProblemVizTab = {
  id: string;
  label: string;
  component: React.ComponentType<ProblemVizProps>;
};

/** Generic props passed from ProblemConfigBlocks into buildGoalTermsExtension. */
export type GoalTermsExtensionBuilderProps = {
  configJson: string;
  workerPreferenceKey: string | null;
  editable: boolean;
  removedGoalTerms: RemovedGoalTermEntry[];
  markerKindFor: (key: string) => MarkerKind | null;
  weightCatalog: Record<string, { label: string; description: string; direction?: "minimize" | "maximize" }>;
  updateProblem: (patch: Record<string, unknown>) => void;
  runEditingAction: (action: () => void, event?: ActivateHint) => void;
  ensureEditing: (event?: ActivateHint) => void;
  rememberRemovedGoalTerm: (entry: RemovedGoalTermEntry) => void;
  restoreRemovedGoalTerm: (key: string) => void;
  constraintTypes: Record<string, ConstraintType>;
  onConstraintTypeChange: (key: string, type: ConstraintType) => void;
};

/**
 * Descriptor exported from each problem module's frontend/index.ts as `MODULE`.
 * The generic shell (ProblemConfigBlocks, ResultsPanel) calls getProblemModule(id)
 * and uses only the fields defined here — no problem-specific imports in generic code.
 */
export type ProblemModule = {
  /**
   * Optional: provide additional goal-term keys that should be visible/rankable
   * even when absent from problem.weights (for structural controls tied to a term).
   */
  getAdditionalGoalTermKeys?: (configJson: string) => string[];
  /** Optional: builds a GoalTermsExtension for the config panel. */
  buildGoalTermsExtension?: (props: GoalTermsExtensionBuilderProps) => GoalTermsExtension;
  /** Visualization tabs to offer in the results panel (in order). */
  vizTabs: ProblemVizTab[];
  /**
   * Optional: parse an edited schedule/solution JSON into solver input routes.
   * Returns null when the JSON is invalid or the problem does not support manual evaluation.
   * Presence of this method also controls whether the schedule editor is shown.
   */
  parseEvalRoutes?: (json: unknown) => number[][] | null;
  /**
   * Optional: format a plain-text violation summary from a run result for the AI chat message.
   * Returns null to omit violation details from the message.
   */
  formatRunViolationSummary?: (result: unknown) => string | null;
  /**
   * Optional: per-problem tutorial bubble content (titles, bodies, action buttons).
   * When omitted, the generic fallback in `frontend/src/tutorial/defaultContent.ts` is used.
   */
  tutorialContent?: TutorialContent;
};
