import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type MouseEvent } from "react";

import type { ProblemBrief, ProblemBriefItem, ProblemBriefQuestion, RunSummaryEntry } from "@shared/api";

import { DEFINITION_NEW_ROW_PLACEHOLDER } from "./constants";
import { useDefinitionExternalFlash } from "./useDefinitionExternalFlash";
import { useLockedEditFocus } from "../lib/useLockedEditFocus";

export type DefinitionPanelProps = {
  problemBrief: ProblemBrief;
  /** True while global definition edit mode is active */
  editable: boolean;
  sessionTerminated: boolean;
  openQuestionsBusy?: boolean;
  /** OQ ids whose answer is being rephrased + bucket-routed by the backend.
   *  Each such card shows a spinning shield and locks input until the response settles. */
  processingOqIds?: ReadonlySet<string>;
  /** When `waterfall`, the Assumptions section is hidden (runs are gated on open questions). */
  workflowMode?: string | null;
  onChange: (value: ProblemBrief) => void;
  /** Enter definition edit mode (no-op if already editing another panel mode) */
  onEnsureDefinitionEditing: () => void;
  suppressTransientMarkers?: boolean;
};

type DefinitionSectionProps = {
  title: string;
  description: string;
  items: ProblemBriefItem[];
  editable: boolean;
  sessionTerminated: boolean;
  onEnsureDefinitionEditing: (preferredFocusSelector?: string, preferredCaretIndex?: number) => void;
  onAddItem: () => void;
  onUpdateItemText: (id: string, text: string) => void;
  onRemoveItem: (id: string, index: number) => void;
  deletedMarkerIndex: number | null;
  onTextareaInput: (e: FormEvent<HTMLTextAreaElement>) => void;
  rowExtraClassName?: (item: ProblemBriefItem) => string;
  removedItems?: Array<{ id: string; text: string; index: number }>;
  onRestoreItem?: (id: string) => void;
  suppressTransientMarkers?: boolean;
  /** When set (Assumptions section), show the green ✓ next to remove to promote a row to gathered info. */
  onPromoteItem?: (id: string) => void;
  /** When set (Gathered section), show a lock toggle on rows tied to a goal term.
   *  Locking freezes the term so the agent can't change it without asking first
   *  — the same lock as the Problem Config goal-term lock (one lock per concept).
   *  Reads `goal_key` from the row; no-op for rows without one. */
  onToggleItemLock?: (goalKey: string, nextLocked: boolean) => void;
  /** Goal-term keys currently locked (drives the toggle's on/off state). */
  lockedGoalKeys?: ReadonlySet<string>;
  collapsed?: boolean;
  onToggle?: () => void;
};

function makeId(prefix: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID().slice(0, 10)}`;
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.round(Math.random() * 1_000_000)}`;
}

function updateItems(
  problemBrief: ProblemBrief,
  mapper: (items: ProblemBriefItem[]) => ProblemBriefItem[],
): ProblemBrief {
  return {
    ...problemBrief,
    items: mapper(problemBrief.items),
  };
}

function isPlaceholderItem(item: ProblemBriefItem): boolean {
  return (
    (item.kind === "gathered" || item.kind === "assumption") && item.text === DEFINITION_NEW_ROW_PLACEHOLDER
  );
}

function estimatedCaretIndexFromClick(text: string, event: MouseEvent<HTMLButtonElement>): number {
  const width = Math.max(1, event.currentTarget.clientWidth);
  const x = Math.max(0, Math.min(width, event.nativeEvent.offsetX));
  return Math.round((x / width) * text.length);
}

function DefinitionSection({
  title,
  description,
  items,
  editable,
  sessionTerminated,
  onEnsureDefinitionEditing,
  onAddItem,
  onUpdateItemText,
  onRemoveItem,
  deletedMarkerIndex,
  onTextareaInput,
  rowExtraClassName,
  removedItems = [],
  onRestoreItem,
  suppressTransientMarkers = false,
  onPromoteItem,
  onToggleItemLock,
  lockedGoalKeys,
  collapsed = false,
  onToggle,
}: DefinitionSectionProps) {
  const locked = sessionTerminated || !editable;
  const rowMinHeight = "3rem";

  return (
    <section className="definition-section">
      {onToggle ? (
        <button
          type="button"
          className={`definition-section-toggle ${collapsed ? "is-collapsed" : ""}`.trim()}
          onClick={onToggle}
          aria-expanded={!collapsed}
        >
          <span>{title}</span>
          <span className="definition-section-toggle-meta">
            <span className="definition-count">{items.length}</span>
            <span className="definition-section-chevron" aria-hidden="true">{collapsed ? "▶" : "▼"}</span>
          </span>
        </button>
      ) : (
        <div className="definition-section-heading">{title}</div>
      )}
      {!collapsed && (
        <>
        <div className="definition-section-header">
          <div>
            <div className="muted">{description}</div>
          </div>
          <div className="definition-header-actions">
            {!sessionTerminated ? (
              <button
                type="button"
                className="definition-icon-btn definition-add-btn"
                aria-label={`Add ${title}`}
                onClick={() => {
                  onEnsureDefinitionEditing();
                  onAddItem();
                }}
              >
                +
              </button>
            ) : null}
          </div>
        </div>
        <div className="definition-list">
        {items.map((item, index) => (
          <Fragment key={item.id}>
            {deletedMarkerIndex === index ? <div className="definition-delete-marker" aria-hidden="true" /> : null}
            <div
              id={`definition-item-${item.id}`}
              className={`definition-item kind-${item.kind} source-${item.source} ${isPlaceholderItem(item) ? "definition-item-placeholder-glow" : ""} ${rowExtraClassName?.(item) ?? ""}`.trim()}
            >
                <div className="definition-item-content">
                  <div
                    className="definition-item-overlay-controls"
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      gap: "0.12rem",
                    }}
                  >
                    {!sessionTerminated ? (
                      <>
                        <button
                          type="button"
                          className="definition-icon-btn definition-remove-btn"
                          aria-label="Remove row"
                          onClick={() => {
                            onEnsureDefinitionEditing();
                            onRemoveItem(item.id, index);
                          }}
                        >
                          X
                        </button>
                        {onPromoteItem ? (
                          <button
                            type="button"
                            className="definition-icon-btn definition-promote-btn"
                            aria-label="Promote to gathered info"
                            title="Promote to gathered info"
                            onClick={() => {
                              onEnsureDefinitionEditing();
                              onPromoteItem(item.id);
                            }}
                          >
                            ✓
                          </button>
                        ) : null}
                        {onToggleItemLock && typeof item.goal_key === "string" && item.goal_key
                          ? (() => {
                              const goalKey = item.goal_key as string;
                              const isLocked = lockedGoalKeys?.has(goalKey) ?? false;
                              return (
                                <button
                                  type="button"
                                  className={`definition-icon-btn ${isLocked ? "definition-icon-btn--locked" : "definition-icon-btn--unlocked"}`}
                                  aria-label={isLocked ? "Unlock this setting" : "Lock this setting"}
                                  aria-pressed={isLocked}
                                  title={
                                    isLocked
                                      ? "Locked — the agent must ask before changing this. Click to unlock."
                                      : "Lock this setting so the agent can't change it without asking."
                                  }
                                  onClick={() => {
                                    onEnsureDefinitionEditing();
                                    onToggleItemLock(goalKey, !isLocked);
                                  }}
                                >
                                  {isLocked ? "🔒" : "🔓"}
                                </button>
                              );
                            })()
                          : null}
                      </>
                    ) : null}
                  </div>
                  {editable ? (
                    <textarea
                      id={`definition-inline-text-${item.id}`}
                      className="definition-inline-textarea definition-inline-textarea-bare"
                      value={item.text}
                      disabled={locked}
                      rows={2}
                      style={{ minHeight: rowMinHeight }}
                      onFocus={() => onEnsureDefinitionEditing()}
                      onChange={(e) => onUpdateItemText(item.id, e.target.value)}
                      onInput={onTextareaInput}
                    />
                  ) : (
                    <button
                      type="button"
                      className="definition-inline-display definition-inline-display-bare"
                      style={{ minHeight: rowMinHeight, display: "flex", alignItems: "flex-start" }}
                      title="Edit..."
                      disabled={sessionTerminated}
                      onClick={(e) => {
                        onEnsureDefinitionEditing(
                          `#definition-inline-text-${item.id}`,
                          estimatedCaretIndexFromClick(item.text || "", e),
                        );
                      }}
                    >
                      {item.text || "Click to add details..."}
                    </button>
                  )}
                </div>
              </div>
            </Fragment>
          ))}
        {deletedMarkerIndex !== null && deletedMarkerIndex === items.length ? (
          <div className="definition-delete-marker" aria-hidden="true" />
        ) : null}
        {items.length === 0 ? <div className="muted definition-empty">Nothing here yet.</div> : null}
        {!suppressTransientMarkers &&
          removedItems.map((removed) => (
          <div
            key={`removed-${removed.id}`}
            className="definition-item definition-item-removed"
            role="button"
            tabIndex={0}
            onClick={() => {
              onEnsureDefinitionEditing();
              onRestoreItem?.(removed.id);
            }}
            onKeyDown={(e) => {
              if (e.key !== "Enter" && e.key !== " ") return;
              e.preventDefault();
              onEnsureDefinitionEditing();
              onRestoreItem?.(removed.id);
            }}
          >
            <div className="definition-item-meta">
              <span className="entry-diff-marker entry-diff-marker--removed">-</span>
              <span className="muted">Removed entry</span>
              {!sessionTerminated ? (
                <button
                  type="button"
                  className="definition-icon-btn definition-restore-btn"
                  aria-label="Restore row"
                  onClick={(e) => {
                    e.stopPropagation();
                    onEnsureDefinitionEditing();
                    onRestoreItem?.(removed.id);
                  }}
                >
                  R
                </button>
              ) : null}
            </div>
            <div className="muted" style={{ fontSize: "0.78rem" }}>
              {removed.text || "(empty)"}
            </div>
          </div>
          ))}
        </div>
        </>
      )}
    </section>
  );
}

const EMPTY_OQ_PROCESSING_SET: ReadonlySet<string> = new Set<string>();

export function DefinitionPanel({
  problemBrief,
  editable,
  sessionTerminated,
  openQuestionsBusy = false,
  processingOqIds = EMPTY_OQ_PROCESSING_SET,
  workflowMode,
  onChange,
  onEnsureDefinitionEditing,
  suppressTransientMarkers = false,
}: DefinitionPanelProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const pendingScrollToItemIdRef = useRef<string | null>(null);
  const deletedMarkerTimeoutRef = useRef<number | null>(null);
  const [deletedMarker, setDeletedMarker] = useState<{
    section: "gathered" | "assumption" | "open";
    index: number;
  } | null>(null);
  const [removedItems, setRemovedItems] = useState<
    Record<"gathered" | "assumption", Array<{ id: string; item: ProblemBriefItem; index: number }>>
  >({
    gathered: [],
    assumption: [],
  });
  useEffect(() => {
    if (editable && !suppressTransientMarkers) return;
    setRemovedItems({ gathered: [], assumption: [] });
    setDeletedMarker(null);
  }, [editable, suppressTransientMarkers]);
  const { markLockedInteraction } = useLockedEditFocus({
    rootRef,
    editable,
    focusSelector: ".definition-inline-textarea",
  });
  const gatheredItems = problemBrief.items.filter((item) => item.kind === "gathered");
  const assumptionItems = problemBrief.items.filter((item) => item.kind === "assumption");
  const openQuestions = problemBrief.open_questions;
  const openLocked = sessionTerminated || !editable || openQuestionsBusy;
  const showAssumptions = (workflowMode ?? "").toLowerCase() !== "waterfall";

  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({
    runSummary: true,
  });
  const toggleSection = useCallback((key: string) => {
    setCollapsedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const showDeletedMarker = useCallback((section: "gathered" | "assumption" | "open", index: number) => {
    if (deletedMarkerTimeoutRef.current != null) {
      window.clearTimeout(deletedMarkerTimeoutRef.current);
    }
    setDeletedMarker({ section, index });
    deletedMarkerTimeoutRef.current = window.setTimeout(() => {
      setDeletedMarker(null);
      deletedMarkerTimeoutRef.current = null;
    }, 1650);
  }, []);

  const { flashClassForItem, flashClassForQuestion } = useDefinitionExternalFlash(problemBrief, editable, showDeletedMarker);

  useLayoutEffect(() => {
    const id = pendingScrollToItemIdRef.current;
    if (!id) return;
    pendingScrollToItemIdRef.current = null;
    requestAnimationFrame(() => {
      document.getElementById(`definition-item-${id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }, [problemBrief.items]);

  function persist(next: ProblemBrief) {
    onChange(next);
  }

  function removeItem(id: string, index: number) {
    const item = problemBrief.items.find((row) => row.id === id);
    if (item && index >= 0) {
      showDeletedMarker(item.kind === "assumption" ? "assumption" : "gathered", index);
      if (item.kind === "gathered" || item.kind === "assumption") {
        const bucket: "gathered" | "assumption" = item.kind;
        setRemovedItems((current) => {
          if (current[bucket].some((entry) => entry.id === item.id)) return current;
          return {
            ...current,
            [bucket]: [...current[bucket], { id: item.id, item: { ...item }, index }],
          };
        });
      }
    }
    persist(updateItems(problemBrief, (items) => items.filter((item) => item.id !== id)));
  }

  function restoreRemovedItem(kind: "gathered" | "assumption", id: string) {
    const removed = removedItems[kind].find((entry) => entry.id === id);
    if (!removed) return;
    persist(
      updateItems(problemBrief, (items) => {
        const sameKindCount = items.filter((item) => item.kind === kind).length;
        const targetSameKindIndex = Math.max(0, Math.min(sameKindCount, removed.index));
        let seen = 0;
        let insertAt = items.length;
        for (let i = 0; i < items.length; i += 1) {
          const row = items[i];
          if (row?.kind !== kind) continue;
          if (seen === targetSameKindIndex) {
            insertAt = i;
            break;
          }
          seen += 1;
        }
        const next = [...items];
        next.splice(insertAt, 0, { ...removed.item });
        return next;
      }),
    );
    setRemovedItems((current) => ({
      ...current,
      [kind]: current[kind].filter((entry) => entry.id !== id),
    }));
  }

  function addItem(kind: "gathered" | "assumption") {
    const id = makeId(`item-${kind}`);
    pendingScrollToItemIdRef.current = id;
    persist(
      updateItems(problemBrief, (items) => [
        ...items,
        {
          id,
          text: DEFINITION_NEW_ROW_PLACEHOLDER,
          kind,
          source: "user",
        },
      ]),
    );
  }

  function promoteAssumptionToGathered(id: string) {
    persist(
      updateItems(problemBrief, (items) =>
        items.map((item) =>
          item.id === id && item.kind === "assumption"
            ? { ...item, kind: "gathered", source: "user" }
            : item,
        ),
      ),
    );
  }

  // Lock state lives on the concept (`goal_terms[key].locked`) — the same lock
  // the Problem Config goal-term button sets, so there's one lock per concept
  // shown in two places. The backend honors this brief-side flag (and mirrors
  // it to the panel's `locked_goal_terms`), and `gate_locked_goal_term_changes`
  // makes the agent ask before changing a locked term.
  const lockedGoalKeys = new Set<string>(
    Object.entries((problemBrief.goal_terms as Record<string, unknown>) ?? {})
      .filter(([, entry]) => (entry as { locked?: unknown })?.locked === true)
      .map(([key]) => key),
  );

  function toggleItemLock(goalKey: string, nextLocked: boolean) {
    const currentTerms = (problemBrief.goal_terms as Record<string, unknown>) ?? {};
    const currentEntry = (currentTerms[goalKey] as Record<string, unknown>) ?? {};
    persist({
      ...problemBrief,
      goal_terms: {
        ...currentTerms,
        [goalKey]: { ...currentEntry, locked: nextLocked },
      },
    });
  }

  function updateItemText(id: string, text: string) {
    persist(
      updateItems(problemBrief, (items) => items.map((item) => (item.id === id ? { ...item, text } : item))),
    );
  }

  function removeOpenQuestion(questionId: string) {
    onEnsureDefinitionEditing();
    const index = openQuestions.findIndex((question) => question.id === questionId);
    if (index >= 0) showDeletedMarker("open", index);
    persist({
      ...problemBrief,
      open_questions: openQuestions.filter((question) => question.id !== questionId),
    });
  }

  function autoGrowTextarea(e: FormEvent<HTMLTextAreaElement>) {
    const el = e.currentTarget;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  function addOpenQuestion() {
    if (sessionTerminated) return;
    const raw = window.prompt("Enter the open question");
    const text = raw == null ? "" : raw.trim();
    if (!text) return;
    onEnsureDefinitionEditing();
    persist({
      ...problemBrief,
      open_questions: [
        ...openQuestions,
        {
          id: makeId("question-open"),
          text,
          status: "open" as ProblemBriefQuestion["status"],
          answer_text: null,
          // Researcher-side editor creates only free-form clarifications;
          // foundational topics are server-owned.
          topic: "other",
        },
      ],
    });
  }

  function updateGoalSummary(value: string) {
    persist({ ...problemBrief, goal_summary: value });
  }
  // Run history is server-managed via ``brief.runs``; no participant editor.

  function updateOpenQuestionAnswer(questionId: string, answer: string) {
    const nextQuestions = openQuestions.map((row) =>
      row.id !== questionId
        ? row
        : {
            ...row,
            /* Keep spaces while typing; trim only decides answered vs open (whitespace-only stays "open"). */
            answer_text: answer === "" ? null : answer,
            status: (answer.trim() ? "answered" : "open") as ProblemBriefQuestion["status"],
          },
    );
    persist({ ...problemBrief, open_questions: nextQuestions });
  }

  function ensureDefinitionEditingFromLocked(preferredFocusSelector?: string, preferredCaretIndex?: number) {
    if (!editable && !sessionTerminated) {
      markLockedInteraction(preferredFocusSelector, preferredCaretIndex);
    }
    onEnsureDefinitionEditing();
  }

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const textareas = root.querySelectorAll<HTMLTextAreaElement>(".definition-inline-textarea");
    for (const textarea of textareas) {
      textarea.style.height = "auto";
      textarea.style.height = `${textarea.scrollHeight}px`;
    }
  }, [editable, problemBrief.goal_summary, problemBrief.runs, problemBrief.items, problemBrief.open_questions]);

  return (
    <div className="definition-panel" ref={rootRef}>
      {/* <p className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.85rem", lineHeight: 1.45 }}>
        Clarify <strong>goals</strong> (what to improve), <strong>soft penalties</strong> (undesirable outcomes with a cost),
        and <strong>hard constraints</strong> (fixed assignments or non‑negotiable limits). Use the Problem Config tab to
        translate into solver weights.
      </p> */}
      <section className="definition-section">
        <button
          type="button"
          className={`definition-section-toggle ${collapsedSections.goalSummary ? "is-collapsed" : ""}`.trim()}
          onClick={() => toggleSection("goalSummary")}
          aria-expanded={!collapsedSections.goalSummary}
        >
          <span>Goal Summary</span>
          <span className="definition-section-chevron" aria-hidden="true">{collapsedSections.goalSummary ? "▶" : "▼"}</span>
        </button>
        {!collapsedSections.goalSummary && (
          <div className="definition-item">
            <div className="definition-item-content definition-item-content-goal">
              <textarea
                id="definition-goal-summary"
                className="definition-inline-textarea definition-inline-textarea-bare definition-inline-textarea-goal"
                value={problemBrief.goal_summary}
                disabled={sessionTerminated}
                rows={2}
                onFocus={() => ensureDefinitionEditingFromLocked("#definition-goal-summary")}
                onChange={(e) => {
                  ensureDefinitionEditingFromLocked("#definition-goal-summary");
                  updateGoalSummary(e.target.value);
                }}
                onInput={autoGrowTextarea}
                placeholder="Summarize what a good plan should prioritize."
              />
              {/* Server-rendered priority-order line — derived from
                  goal_terms[K].rank on every brief save. Read-only by design;
                  changing rank order happens in the Config tab. */}
              {problemBrief.priority_line ? (
                <p
                  className="muted definition-goal-priority"
                  style={{
                    fontSize: "0.78rem",
                    marginTop: "0.35rem",
                    lineHeight: 1.4,
                  }}
                >
                  {problemBrief.priority_line}
                </p>
              ) : null}
            </div>
          </div>
        )}
      </section>

      <section className="definition-section">
        <button
          type="button"
          className={`definition-section-toggle ${collapsedSections.runSummary ? "is-collapsed" : ""}`.trim()}
          onClick={() => toggleSection("runSummary")}
          aria-expanded={!collapsedSections.runSummary}
        >
          <span>Run Summary</span>
          <span className="definition-section-chevron" aria-hidden="true">{collapsedSections.runSummary ? "▶" : "▼"}</span>
        </button>
        {!collapsedSections.runSummary && (
          <RunSummaryAccordion runs={problemBrief.runs ?? []} />
        )}
      </section>

      <section className="definition-section" id="definition-open-questions">
        <button
          type="button"
          className={`definition-section-toggle ${collapsedSections.openQuestions ? "is-collapsed" : ""}`.trim()}
          onClick={() => toggleSection("openQuestions")}
          aria-expanded={!collapsedSections.openQuestions}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
            <span>Open Questions</span>
            {openQuestionsBusy ? <span className="inline-spinner" aria-label="Cleaning open questions" /> : null}
          </span>
          <span className="definition-section-toggle-meta">
            <span className="definition-count">{openQuestions.length}</span>
            <span className="definition-section-chevron" aria-hidden="true">{collapsedSections.openQuestions ? "▶" : "▼"}</span>
          </span>
        </button>
        {!collapsedSections.openQuestions && (
          <>
          <div className="definition-section-header">
            <div>
              <div className="muted">Questions we still need to answer to improve the plan.</div>
            </div>
            <div className="definition-header-actions">
              {!sessionTerminated ? (
                <button
                  type="button"
                  className="definition-icon-btn definition-add-btn"
                  aria-label="Add open question"
                  onClick={addOpenQuestion}
                  disabled={openQuestionsBusy}
                >
                  +
                </button>
              ) : null}
            </div>
          </div>
          <div className="definition-list">
          {openQuestions.map((question, index) => {
            const isProcessing = processingOqIds.has(question.id);
            const cardLocked = openLocked || isProcessing;
            return (
              <Fragment key={question.id}>
                {deletedMarker?.section === "open" && deletedMarker.index === index ? (
                  <div className="definition-delete-marker" aria-hidden="true" />
                ) : null}
                <div
                  className={`definition-item definition-item-open ${isProcessing ? "definition-item-processing" : ""} ${flashClassForQuestion(question.id)}`.trim()}
                >
                    <div className="definition-item-content definition-item-content-open">
                      <div className="definition-item-overlay-controls">
                        {isProcessing ? (
                          <span
                            className="inline-spinner"
                            aria-label="Rephrasing your answer"
                            title="Rephrasing your answer"
                          />
                        ) : !sessionTerminated ? (
                          <button
                            type="button"
                            className="definition-icon-btn definition-remove-btn"
                            aria-label="Remove open question"
                            disabled={openQuestionsBusy}
                            onClick={() => removeOpenQuestion(question.id)}
                          >
                            X
                          </button>
                        ) : null}
                      </div>
                      <div className="definition-question-text">{question.text}</div>
                      {editable ? (
                        <textarea
                          id={`definition-open-question-answer-${question.id}`}
                          className="definition-inline-textarea definition-answer-textarea"
                          value={question.answer_text ?? ""}
                          placeholder="Type answer..."
                          disabled={cardLocked}
                          rows={1}
                          onFocus={() => onEnsureDefinitionEditing()}
                          onChange={(e) => updateOpenQuestionAnswer(question.id, e.target.value)}
                          onInput={autoGrowTextarea}
                        />
                      ) : (
                        <button
                          type="button"
                          className="definition-inline-display"
                          style={{ textAlign: "left" }}
                          title="Edit..."
                          disabled={sessionTerminated}
                          onClick={(e) =>
                            ensureDefinitionEditingFromLocked(
                              `#definition-open-question-answer-${question.id}`,
                              estimatedCaretIndexFromClick(question.answer_text ?? "", e),
                            )
                          }
                        >
                          {(question.answer_text ?? "").length > 0 ? question.answer_text : "Type answer…"}
                        </button>
                      )}
                    </div>
                  </div>
                </Fragment>
              );
            })}
          {deletedMarker?.section === "open" && deletedMarker.index === openQuestions.length ? (
            <div className="definition-delete-marker" aria-hidden="true" />
          ) : null}
          {openQuestions.length === 0 ? <div className="muted definition-empty">Nothing here yet.</div> : null}
          </div>
          </>
        )}
      </section>

      {showAssumptions ? (
        <DefinitionSection
          title="Assumptions"
          description="Temporary assumptions used until confirmed information is available."
          items={assumptionItems}
          editable={editable}
          sessionTerminated={sessionTerminated}
          onEnsureDefinitionEditing={ensureDefinitionEditingFromLocked}
          onAddItem={() => addItem("assumption")}
          onUpdateItemText={updateItemText}
          onRemoveItem={removeItem}
          deletedMarkerIndex={deletedMarker?.section === "assumption" ? deletedMarker.index : null}
          onTextareaInput={autoGrowTextarea}
          rowExtraClassName={(item) => flashClassForItem(item.id)}
          suppressTransientMarkers={suppressTransientMarkers}
          removedItems={removedItems.assumption.map((entry) => ({
            id: entry.id,
            text: entry.item.text,
            index: entry.index,
          }))}
          onRestoreItem={(id) => restoreRemovedItem("assumption", id)}
          onPromoteItem={promoteAssumptionToGathered}
          collapsed={collapsedSections.assumptions}
          onToggle={() => toggleSection("assumptions")}
        />
      ) : null}

      <DefinitionSection
        title="Gathered Info"
        description="Confirmed facts from chat messages or uploaded materials."
        items={gatheredItems}
        editable={editable}
        sessionTerminated={sessionTerminated}
        onEnsureDefinitionEditing={ensureDefinitionEditingFromLocked}
        onAddItem={() => addItem("gathered")}
        onUpdateItemText={updateItemText}
        onRemoveItem={removeItem}
        deletedMarkerIndex={deletedMarker?.section === "gathered" ? deletedMarker.index : null}
        onTextareaInput={autoGrowTextarea}
        rowExtraClassName={(item) => flashClassForItem(item.id)}
        suppressTransientMarkers={suppressTransientMarkers}
        removedItems={removedItems.gathered.map((entry) => ({
          id: entry.id,
          text: entry.item.text,
          index: entry.index,
        }))}
        onRestoreItem={(id) => restoreRemovedItem("gathered", id)}
        onToggleItemLock={toggleItemLock}
        lockedGoalKeys={lockedGoalKeys}
        collapsed={collapsedSections.gatheredInfo}
        onToggle={() => toggleSection("gatheredInfo")}
      />

    </div>
  );
}


/**
 * Per-run accordion for the Run Summary section. One collapsed row per
 * entry in `brief.runs`. Newest run at the top. Header shows the
 * deterministic at-a-glance facts (Run #N · cost · ok/violations);
 * expanded body shows algorithm + delta-from-previous.
 *
 * Server-managed read-only display — there is no editor surface here.
 * The entries are filled by `derivation.consolidate_runs` on every
 * run-acknowledgement turn; the LLM never writes to them.
 */
function RunSummaryAccordion({ runs }: { runs: RunSummaryEntry[] }) {
  // Newest first so the most recent run is the first thing the participant sees.
  const ordered = [...runs].sort((a, b) => b.run_number - a.run_number);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(() => {
    // Default-expand the latest run; collapse the rest.
    return ordered.length > 0 ? new Set([ordered[0].run_number]) : new Set();
  });

  if (ordered.length === 0) {
    return (
      <div className="definition-item">
        <div className="definition-item-content definition-item-content-goal">
          <p className="muted" style={{ fontSize: "0.82rem", padding: "0.35rem 0" }}>
            No runs yet. Each completed run gets a structured entry here with
            cost, violations, and the delta versus the previous run.
          </p>
        </div>
      </div>
    );
  }

  function toggle(runNumber: number) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(runNumber)) next.delete(runNumber);
      else next.add(runNumber);
      return next;
    });
  }

  return (
    <div className="definition-item">
      <div className="definition-item-content definition-item-content-goal">
        {ordered.map((run) => {
          const expanded = expandedIds.has(run.run_number);
          const costText = run.cost == null ? "—" : run.cost.toFixed(2);
          // At-a-glance row (always visible): Run #N · cost · search method.
          // Outcome / violation detail / delta moves into the expanded body so
          // the collapsed view scans cleanly at a list of many runs.
          const algoText = run.algorithm || "—";
          const outcomeText = run.ok
            ? (run.violations_summary
                ? `Completed with violations: ${run.violations_summary}.`
                : "Completed with no violations.")
            : "Run failed.";
          return (
            <div
              key={run.run_number}
              className="definition-run-row"
              style={{ borderTop: "1px solid var(--border-muted, #2a2a2a)", padding: "0.4rem 0" }}
            >
              <button
                type="button"
                onClick={() => toggle(run.run_number)}
                aria-expanded={expanded}
                style={{
                  display: "flex",
                  width: "100%",
                  alignItems: "baseline",
                  gap: "0.5rem",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  textAlign: "left",
                  fontSize: "0.85rem",
                  padding: 0,
                  color: "inherit",
                }}
              >
                <span aria-hidden="true" style={{ width: "0.75rem", display: "inline-block" }}>
                  {expanded ? "▼" : "▶"}
                </span>
                <strong>Run #{run.run_number}</strong>
                <span className="muted">·</span>
                <span>cost {costText}</span>
                <span className="muted">·</span>
                <span className="muted">{algoText}</span>
              </button>
              {expanded && (
                <div
                  style={{
                    paddingLeft: "1.25rem",
                    paddingTop: "0.3rem",
                    fontSize: "0.78rem",
                    lineHeight: 1.45,
                  }}
                >
                  <p className="muted" style={{ margin: "0.1rem 0" }}>
                    {outcomeText}
                  </p>
                  {run.delta_from_prev && (
                    <p className="muted" style={{ margin: "0.1rem 0" }}>
                      {run.delta_from_prev}.
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
