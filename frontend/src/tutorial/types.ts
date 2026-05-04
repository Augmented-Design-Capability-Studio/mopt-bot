import type { TutorialStepId } from "@shared/api";

/**
 * Optional action button rendered inside a tutorial bubble.
 *
 * The discriminated union keeps the registry boundary clean: a per-problem
 * tutorial module declares actions as plain data, and the bubble dispatcher in
 * `ClientShell` is the single place that knows how to execute each kind.
 * Adding a new kind is a two-file change (this type + the dispatcher).
 */
export type TutorialAction =
  /** Replace the chat composer's current value with `payload`. One-click cold start. */
  | { kind: "fill-chat-input"; label: string; payload: string }
  /** Copy `payload` to the system clipboard. */
  | { kind: "copy-clipboard"; label: string; payload: string }
  /** Switch the middle panel to a specific tab. */
  | { kind: "switch-tab"; label: string; target: "definition" | "config" }
  /**
   * Deep-merge `patch` into the current panel `problem` config and save. Used
   * by per-problem tutorials to script a controlled run progression (e.g.
   * an intentionally infeasible Run 1 followed by a feasible Run 2).
   *
   * `patch` is a partial `problem` object — for example
   * `{ weights: { capacity_overflow: 100 }, constraint_types: { capacity_overflow: "hard" } }`.
   * Top-level keys in `patch` shallow-replace the corresponding key in the
   * panel's `problem` object; nested object values (`weights`, `constraint_types`,
   * `algorithm_params`, `goal_terms`) are deep-merged so unrelated fields are
   * preserved.
   */
  | { kind: "apply-config-patch"; label: string; patch: Record<string, unknown> }
  /**
   * Mark a specific tutorial flag true to advance from a step that has no
   * naturally-fired completion event (e.g. "read the assistant's reply"). The
   * dispatcher applies the flag patch via the participant tutorial state API.
   * Use sparingly — most steps should advance on real user actions.
   */
  | { kind: "acknowledge-step"; label: string; flag: string }
  /** Mark the tutorial as completed and turn the bubble off. Only used by the wrap-up step. */
  | { kind: "complete-tutorial"; label: string };

export type TutorialStep = {
  id: TutorialStepId;
  title: string;
  body: string;
  actions?: TutorialAction[];
};

export type TutorialCompletionByStepId = Record<TutorialStepId, boolean>;

/**
 * Per-step partial used by problem modules that only want to tweak a few
 * default steps. `id` is implicit (the map key); only `title`, `body`, and
 * `actions` can be overridden — anchors and completion gating stay default.
 */
export type TutorialStepOverride = Partial<Pick<TutorialStep, "title" | "body" | "actions">>;

/**
 * Per-problem tutorial content surface. Problem modules export this on their
 * `ProblemModule.tutorialContent`. Two strategies, in priority order:
 *
 *   1. `stepOverrides(mode)` — recommended. Returns a partial map keyed by
 *      `TutorialStepId`. The generic machinery starts from
 *      `DEFAULT_TUTORIAL_CONTENT.stepsForMode(mode)` and shallow-merges each
 *      override onto the matching default step. Steps you don't override stay
 *      as the default.
 *   2. `stepsForMode(mode)` — escape hatch. Returns the full step array; used
 *      as-is. Use this only when you need structurally different content
 *      (extra steps, reordering, etc.) that overrides cannot express.
 *
 * If both are present, `stepsForMode` wins.
 */
export type TutorialContent = {
  stepsForMode?: (mode: string | undefined) => TutorialStep[];
  stepOverrides?: (
    mode: string | undefined,
  ) => Partial<Record<TutorialStepId, TutorialStepOverride>>;
};
