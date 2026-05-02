import type { TutorialStepId } from "@shared/api";

/**
 * Optional action button rendered inside a tutorial bubble.
 *
 * The discriminated union keeps the registry boundary clean: a per-problem
 * tutorial module declares actions as plain data, and the bubble dispatcher in
 * `ParticipantShell` is the single place that knows how to execute each kind.
 * Adding a new kind is a two-file change (this type + the dispatcher).
 */
export type TutorialAction =
  /** Replace the chat composer's current value with `payload`. One-click cold start. */
  | { kind: "fill-chat-input"; label: string; payload: string }
  /** Copy `payload` to the system clipboard. */
  | { kind: "copy-clipboard"; label: string; payload: string }
  /** Switch the middle panel to a specific tab. */
  | { kind: "switch-tab"; label: string; target: "definition" | "config" }
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
 * Per-problem tutorial content surface. Problem modules export this on their
 * `ProblemModule.tutorialContent`. The generic frontend tutorial machinery
 * calls `stepsForMode(workflowMode)` and renders the returned steps.
 */
export type TutorialContent = {
  stepsForMode: (mode: string | undefined) => TutorialStep[];
};
