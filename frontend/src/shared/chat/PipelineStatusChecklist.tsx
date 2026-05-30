import { useState, type ReactNode } from "react";
import type {
  PipelineIssueMeta,
  PipelineStageMeta,
  PipelineStatusMeta,
} from "@shared/api";

type PipelineStatusChecklistProps = {
  status: PipelineStatusMeta;
  /** Click handler for the "Retry" action when the pipeline is paused. */
  onRetry?: () => void | Promise<void>;
  /** Click handler for the "Revert" action when the pipeline is paused. */
  onRevert?: () => void | Promise<void>;
  /** Click handler for the "Keep chatting" action — typically scrolls focus
   *  to the chat input so the participant can type a fresh message. */
  onKeepChatting?: () => void | Promise<void>;
  /** True while one of the action buttons is mid-flight. */
  actionBusy?: boolean;
};

/** Shared per-message status checklist rendered below a Pipeline assistant
 *  bubble. Each stage row reflects its current state; failed/paused rows
 *  surface the plain-English issue list. On pause, an action row with
 *  Retry / Revert / Keep chatting buttons appears. */
export function PipelineStatusChecklist({
  status,
  onRetry,
  onRevert,
  onKeepChatting,
  actionBusy = false,
}: PipelineStatusChecklistProps) {
  const [expanded, setExpanded] = useState(false);
  if (!status || !Array.isArray(status.stages) || status.stages.length === 0) {
    return null;
  }
  const paused = status.paused_stage && status.paused_stage.length > 0;
  // Collapsed view: surface only the most informative stage rather than the
  // full checklist. Priority order: paused (action needed) → in_progress (live
  // spinner) → failed (mid-retry) → last terminal stage (success / skipped) so
  // the row still conveys "done" once the pipeline settles.
  // Expanded view: render every stage so participants can audit the full
  // pipeline state when they want detail. Toggle persists per-message via
  // local component state — short-lived since the message itself unmounts
  // after the conversation scrolls / a new session loads.
  const focusStage = pickFocusStage(status.stages, status.paused_stage ?? null);
  const visibleStages = expanded ? status.stages : focusStage ? [focusStage] : [];
  const canToggle = status.stages.length > 1;
  // A step can fail, retry, and then succeed — leaving the collapsed view
  // (which shows only the settled focus row) looking spotless. Surface the
  // retry across all stages so the collapsed record stays honest. Expanded
  // view doesn't need it: each retried stage shows its own "(retried)" badge.
  const retriedCount = status.stages.filter((stage) => stage.retried).length;
  return (
    <div className="pipeline-status" aria-live="polite" data-bubble-pipeline>
      {visibleStages.length > 0 ? (
        <ul className="pipeline-status__list">
          {visibleStages.map((stage) => (
            <PipelineStageRow key={stage.name} stage={stage} />
          ))}
        </ul>
      ) : null}
      {!expanded && retriedCount > 0 ? (
        <div className="pipeline-status__retry-note">
          ↺ {retriedCount === 1 ? "1 step needed a retry" : `${retriedCount} steps needed a retry`}
        </div>
      ) : null}
      {canToggle ? (
        <button
          type="button"
          className="pipeline-status__toggle"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
        >
          <span className="pipeline-status__toggle-caret" aria-hidden="true">
            {expanded ? "▾" : "▸"}
          </span>
          {expanded ? "Hide pipeline steps" : `Show all ${status.stages.length} pipeline steps`}
        </button>
      ) : null}
      {status.inline_followup ? (
        <div className="pipeline-status__followup">{status.inline_followup}</div>
      ) : null}
      {paused ? (
        <div className="pipeline-status__actions" role="group" aria-label="Pipeline actions">
          {onRetry ? (
            <button
              type="button"
              className="pipeline-status__btn pipeline-status__btn--primary"
              disabled={actionBusy}
              onClick={() => void onRetry()}
            >
              {actionBusy ? "Retrying..." : "Retry"}
            </button>
          ) : null}
          {onRevert ? (
            <button
              type="button"
              className="pipeline-status__btn"
              disabled={actionBusy}
              onClick={() => void onRevert()}
            >
              Revert
            </button>
          ) : null}
          {onKeepChatting ? (
            <button
              type="button"
              className="pipeline-status__btn pipeline-status__btn--ghost"
              disabled={actionBusy}
              onClick={() => void onKeepChatting()}
            >
              Keep chatting
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function pickFocusStage(
  stages: PipelineStageMeta[],
  pausedStage: string | null,
): PipelineStageMeta | null {
  if (stages.length === 0) return null;
  if (pausedStage) {
    const found = stages.find((s) => s.name === pausedStage);
    if (found) return found;
  }
  const inProgress = stages.find((s) => s.state === "in_progress");
  if (inProgress) return inProgress;
  const failed = stages.find((s) => s.state === "failed");
  if (failed) return failed;
  // No active stage — show the last stage that actually ran. Prefer non-skipped
  // terminal rows (success/paused/failed) so basic messages don't surface "—
  // Verifying config" as the headline; only fall back to a skipped row if
  // nothing else ran.
  for (let i = stages.length - 1; i >= 0; i -= 1) {
    const s = stages[i];
    if (s && s.state !== "pending" && s.state !== "skipped") return s;
  }
  for (let i = stages.length - 1; i >= 0; i -= 1) {
    const s = stages[i];
    if (s && s.state !== "pending") return s;
  }
  return stages[0] ?? null;
}

function PipelineStageRow({ stage }: { stage: PipelineStageMeta }) {
  // During a retry leg, the runner flips `drafting` (and any future retried
  // stage) back to `in_progress` to re-run the LLM with verifier feedback.
  // With the collapsed view the user sees the SAME "Drafting reply" label
  // as the initial draft, which feels like the pipeline is stuck — swap in a
  // retry-specific label so the live state is honest.
  const isRetryLeg = stage.state === "in_progress" && stage.retried;
  const label = isRetryLeg
    ? stageRetryLabel(stage.name)
    : stage.label ?? stageDefaultLabel(stage.name);
  const stateClass = `pipeline-stage--${stage.state}`;
  return (
    <li className={`pipeline-stage ${stateClass}`}>
      <span className="pipeline-stage__indicator" aria-hidden>
        {stageGlyph(stage.state)}
      </span>
      <div className="pipeline-stage__body">
        <div className="pipeline-stage__title">
          <span className="pipeline-stage__label">{label}</span>
          {stage.retried && !isRetryLeg ? (
            <span className="pipeline-stage__retried" title="Retried once after first failure">
              (retried)
            </span>
          ) : null}
        </div>
        {Array.isArray(stage.details) && stage.details.length > 0 ? (
          <StageDetails
            details={stage.details}
            summary={stage.name === "applying" ? "What changed" : "Details"}
          />
        ) : null}
        {Array.isArray(stage.issues) && stage.issues.length > 0 ? (
          <IssueList issues={stage.issues} />
        ) : null}
      </div>
    </li>
  );
}

function stageGlyph(state: PipelineStageMeta["state"]): ReactNode {
  switch (state) {
    case "success":
      return "✓";
    case "failed":
      return "↺"; // mid-retry indicator
    case "paused":
      return "⚠";
    case "skipped":
      return "—";
    case "in_progress":
      return <span className="chat-spinner pipeline-stage__spinner" role="status" aria-label="In progress" />;
    case "pending":
    default:
      return "○";
  }
}

function stageDefaultLabel(name: PipelineStageMeta["name"]): string {
  switch (name) {
    case "drafting":
      return "Drafting reply";
    case "verifying_brief":
      return "Verifying intent & definition";
    case "applying":
      return "Applying changes";
    case "deriving_config":
      return "Deriving config";
    case "verifying_config":
      return "Verifying config";
  }
}

function stageRetryLabel(name: PipelineStageMeta["name"]): string {
  switch (name) {
    case "drafting":
      return "Re-checking reply...";
    case "verifying_brief":
      return "Re-verifying intent & definition...";
    case "applying":
      return "Re-applying changes...";
    case "deriving_config":
      return "Re-deriving config...";
    case "verifying_config":
      return "Re-verifying config...";
  }
}

/** Nested, collapsed-by-default detail list for a stage (e.g. the "what
 *  changed" rows on "Applying changes"). Keeps the checklist quiet by default
 *  while letting a curious participant drill in for the specifics — the
 *  second level of the "sub-list within list" disclosure. */
function StageDetails({ details, summary }: { details: string[]; summary: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="pipeline-stage__details">
      <button
        type="button"
        className="pipeline-stage__details-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="pipeline-stage__details-caret" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
        {open ? "Hide" : `${summary} (${details.length})`}
      </button>
      {open ? (
        <ul className="pipeline-stage__details-list">
          {details.map((detail, idx) => (
            <li key={idx} className="pipeline-stage__detail">
              {detail}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function IssueList({ issues }: { issues: PipelineIssueMeta[] }) {
  return (
    <ul className="pipeline-stage__issues">
      {issues.map((issue, idx) => (
        <li key={`${issue.category}-${idx}`} className={`pipeline-issue pipeline-issue--${issue.severity ?? "error"}`}>
          {issue.message || issue.category}
        </li>
      ))}
    </ul>
  );
}
