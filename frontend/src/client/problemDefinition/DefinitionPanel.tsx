import {
  Fragment,
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
} from "react";

import type { ProblemBrief, ProblemBriefItem, ProblemBriefQuestion } from "@shared/api";

import { DEFINITION_NEW_ROW_PLACEHOLDER } from "./constants";
import { useDefinitionExternalFlash } from "./useDefinitionExternalFlash";
import { useLockedEditFocus } from "../lib/useLockedEditFocus";

export type DefinitionPanelProps = {
  problemBrief: ProblemBrief;
  /** True while global definition edit mode is active */
  editable: boolean;
  sessionTerminated: boolean;
  /** When `waterfall`, the Assumptions section is hidden (runs are gated on open questions). */
  workflowMode?: string | null;
  onChange: (value: ProblemBrief) => void;
  /** Enter definition edit mode (no-op if already editing another panel mode) */
  onEnsureDefinitionEditing: () => void;
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
};

function makeId(prefix: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.round(Math.random() * 1_000_000)}`;
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
}: DefinitionSectionProps) {
  const locked = sessionTerminated || !editable;

  return (
    <section className="definition-section">
      <div className="definition-section-header">
        <div>
          <div className="definition-section-title">{title}</div>
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
          <span className="definition-count">{items.length}</span>
        </div>
      </div>
      <div className="definition-list">
        {items.map((item, index) => (
          <Fragment key={item.id}>
            {deletedMarkerIndex === index ? <div className="definition-delete-marker" aria-hidden="true" /> : null}
            <div
              id={`definition-item-${item.id}`}
              className={`definition-item kind-${item.kind} ${isPlaceholderItem(item) ? "definition-item-placeholder-glow" : ""} ${rowExtraClassName?.(item) ?? ""}`.trim()}
            >
                <div className="definition-item-meta">
                  <span className="definition-source mono">{item.source}</span>
                  {!sessionTerminated ? (
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
                  ) : null}
                </div>
                {editable ? (
                  <textarea
                    id={`definition-inline-text-${item.id}`}
                    className="definition-inline-textarea"
                    value={item.text}
                    disabled={locked}
                  rows={1}
                    onFocus={() => onEnsureDefinitionEditing()}
                    onChange={(e) => onUpdateItemText(item.id, e.target.value)}
                    onInput={onTextareaInput}
                  />
                ) : (
                  <button
                    type="button"
                    className="definition-inline-display"
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
            </Fragment>
          ))}
        {deletedMarkerIndex !== null && deletedMarkerIndex === items.length ? (
          <div className="definition-delete-marker" aria-hidden="true" />
        ) : null}
        {items.length === 0 ? <div className="muted definition-empty">Nothing here yet.</div> : null}
      </div>
    </section>
  );
}

export function DefinitionPanel({
  problemBrief,
  editable,
  sessionTerminated,
  workflowMode,
  onChange,
  onEnsureDefinitionEditing,
}: DefinitionPanelProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const pendingScrollToItemIdRef = useRef<string | null>(null);
  const deletedMarkerTimeoutRef = useRef<number | null>(null);
  const [deletedMarker, setDeletedMarker] = useState<{
    section: "gathered" | "assumption" | "open";
    index: number;
  } | null>(null);
  const { markLockedInteraction } = useLockedEditFocus({
    rootRef,
    editable,
    focusSelector: ".definition-inline-textarea",
  });
  const gatheredItems = problemBrief.items.filter((item) => item.kind === "gathered");
  const assumptionItems = problemBrief.items.filter((item) => item.kind === "assumption");
  const openQuestions = problemBrief.open_questions;
  const openLocked = sessionTerminated || !editable;
  const showAssumptions = (workflowMode ?? "").toLowerCase() !== "waterfall";

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

  const { flashClassForItem, flashClassForQuestion } = useDefinitionExternalFlash(
    problemBrief,
    editable,
    showDeletedMarker,
  );

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
    }
    persist(updateItems(problemBrief, (items) => items.filter((item) => item.id !== id)));
  }

  function addItem(kind: "gathered" | "assumption") {
    const id = makeId(kind);
    pendingScrollToItemIdRef.current = id;
    persist(
      updateItems(problemBrief, (items) => [
        ...items,
        {
          id,
          text: DEFINITION_NEW_ROW_PLACEHOLDER,
          kind,
          source: "user",
          status: "active",
          editable: true,
        },
      ]),
    );
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
        { id: makeId("open-question"), text, status: "open" as ProblemBriefQuestion["status"], answer_text: null },
      ],
    });
  }

  function updateGoalSummary(value: string) {
    persist({ ...problemBrief, goal_summary: value });
  }

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
    if (!editable) return;
    const root = rootRef.current;
    if (!root) return;
    const textareas = root.querySelectorAll<HTMLTextAreaElement>(".definition-inline-textarea");
    for (const textarea of textareas) {
      textarea.style.height = "auto";
      textarea.style.height = `${textarea.scrollHeight}px`;
    }
  }, [editable, problemBrief.goal_summary, problemBrief.items, problemBrief.open_questions]);

  return (
    <div className="definition-panel" ref={rootRef}>
      <p className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.85rem", lineHeight: 1.45 }}>
        Clarify <strong>goals</strong> (what to improve), <strong>soft penalties</strong> (undesirable outcomes with a cost),
        and <strong>hard constraints</strong> (fixed assignments or non‑negotiable limits). Use the Problem Config tab to
        translate into solver weights.
      </p>
      <section className="definition-section">
        <div className="definition-section-title">Goal Summary</div>
        {editable ? (
          <textarea
            id="definition-goal-summary"
            className="definition-inline-textarea"
            value={problemBrief.goal_summary}
            disabled={sessionTerminated}
            rows={1}
            onFocus={() => onEnsureDefinitionEditing()}
            onChange={(e) => updateGoalSummary(e.target.value)}
            onInput={autoGrowTextarea}
            placeholder="Summarize what the solver should optimize for."
          />
        ) : (
          <button
            type="button"
            className="definition-inline-display"
            title="Edit..."
            disabled={sessionTerminated}
            onClick={(e) =>
              ensureDefinitionEditingFromLocked(
                "#definition-goal-summary",
                estimatedCaretIndexFromClick(problemBrief.goal_summary || "", e),
              )
            }
          >
            {problemBrief.goal_summary || "Summarize what the solver should optimize for."}
          </button>
        )}
      </section>

      <DefinitionSection
        title="Gathered Info"
        description="Facts grounded in user messages or simulated uploads."
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
      />

      {showAssumptions ? (
        <DefinitionSection
          title="Assumptions"
          description="Working assumptions that help the config move forward."
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
        />
      ) : null}

      <section className="definition-section" id="definition-open-questions">
        <div className="definition-section-header">
          <div>
            <div className="definition-section-title">Open Questions</div>
            <div className="muted">Outstanding clarifications that would improve the configuration.</div>
          </div>
          <div className="definition-header-actions">
            {!sessionTerminated ? (
              <button
                type="button"
                className="definition-icon-btn definition-add-btn"
                aria-label="Add open question"
                onClick={addOpenQuestion}
              >
                +
              </button>
            ) : null}
            <span className="definition-count">{openQuestions.length}</span>
          </div>
        </div>
        <div className="definition-list">
          {openQuestions.map((question, index) => {
            const questionStatus = question.status === "answered" ? "answered" : "open";
            return (
              <Fragment key={question.id}>
                {deletedMarker?.section === "open" && deletedMarker.index === index ? (
                  <div className="definition-delete-marker" aria-hidden="true" />
                ) : null}
                <div className={`definition-item ${flashClassForQuestion(question.id)}`.trim()}>
                    <div className="definition-item-meta">
                      <span className={`definition-chip status-${questionStatus}`}>{questionStatus}</span>
                      {!sessionTerminated ? (
                        <button
                          type="button"
                          className="definition-icon-btn definition-remove-btn"
                          aria-label="Remove open question"
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
                        disabled={openLocked}
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
                </Fragment>
              );
            })}
          {deletedMarker?.section === "open" && deletedMarker.index === openQuestions.length ? (
            <div className="definition-delete-marker" aria-hidden="true" />
          ) : null}
          {openQuestions.length === 0 ? <div className="muted definition-empty">Nothing here yet.</div> : null}
        </div>
      </section>
    </div>
  );
}
