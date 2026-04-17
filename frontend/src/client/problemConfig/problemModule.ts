import type { RunResult } from "@shared/api";
import type { GoalTermsExtension } from "./GoalTermsSection";
import type { MarkerKind } from "./useProblemConfigDiffMarkers";
import type { ActivateHint } from "./controls";
import type { RemovedGoalTermEntry } from "./GoalTermsSection";

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

/** Props passed to the problem module's ViolationSummary component, if provided. */
export type ViolationSummaryProps = {
  currentRun: RunResult;
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
};

/**
 * Descriptor exported from each problem module's frontend/index.ts as `MODULE`.
 * The generic shell (ProblemConfigBlocks, ResultsPanel) calls getProblemModule(id)
 * and uses only the fields defined here — no problem-specific imports in generic code.
 */
export type ProblemModule = {
  /** Optional: builds a GoalTermsExtension for the config panel. */
  buildGoalTermsExtension?: (props: GoalTermsExtensionBuilderProps) => GoalTermsExtension;
  /** Visualization tabs to offer in the results panel (in order). */
  vizTabs: ProblemVizTab[];
  /** Optional: problem-specific violation/metric summary rendered above the viz tabs. */
  ViolationSummary?: React.ComponentType<ViolationSummaryProps>;
};
