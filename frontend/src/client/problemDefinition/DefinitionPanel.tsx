import { useLayoutEffect, useRef } from "react";

import type { ProblemBrief, ProblemBriefItem, ProblemBriefQuestion } from "@shared/api";

import { DEFINITION_NEW_ROW_PLACEHOLDER } from "./constants";

export type DefinitionPanelProps = {
  problemBrief: ProblemBrief;
  /** True while global definition edit mode is active */
  editable: boolean;
  sessionTerminated: boolean;
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
  onEnsureDefinitionEditing: () => void;
  onAddItem: () => void;
  onUpdateItemText: (id: string, text: string) => void;
  onRemoveItem: (id: string) => void;
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
      {items.length === 0 ? (
        <div className="muted definition-empty">Nothing here yet.</div>
      ) : (
        <div className="definition-list">
          {items.map((item) => (
            <div
              key={item.id}
              id={`definition-item-${item.id}`}
              className={`definition-item kind-${item.kind} ${isPlaceholderItem(item) ? "definition-item-placeholder-glow" : ""}`}
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
                      onRemoveItem(item.id);
                    }}
                  >
                    X
                  </button>
                ) : null}
              </div>
              {editable ? (
                <textarea
                  className="definition-inline-textarea"
                  value={item.text}
                  disabled={locked}
                  rows={2}
                  onFocus={onEnsureDefinitionEditing}
                  onChange={(e) => onUpdateItemText(item.id, e.target.value)}
                />
              ) : (
                <button
                  type="button"
                  className="definition-inline-display"
                  disabled={sessionTerminated}
                  onClick={() => {
                    onEnsureDefinitionEditing();
                  }}
                >
                  {item.text || "Click to add details..."}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function DefinitionPanel({
  problemBrief,
  editable,
  sessionTerminated,
  onChange,
  onEnsureDefinitionEditing,
}: DefinitionPanelProps) {
  const pendingScrollToItemIdRef = useRef<string | null>(null);
  const gatheredItems = problemBrief.items.filter((item) => item.kind === "gathered");
  const assumptionItems = problemBrief.items.filter((item) => item.kind === "assumption");
  const openQuestions = problemBrief.open_questions;
  const openLocked = sessionTerminated || !editable;

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

  function removeItem(id: string) {
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
    persist({
      ...problemBrief,
      open_questions: openQuestions.filter((question) => question.id !== questionId),
    });
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

  return (
    <div className="definition-panel">
      <p className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.85rem", lineHeight: 1.45 }}>
        Clarify <strong>goals</strong> (what to improve), <strong>soft penalties</strong> (undesirable outcomes with a cost),
        and <strong>hard constraints</strong> (fixed assignments or non‑negotiable limits). Use the Problem Config tab to
        translate into solver weights.
      </p>
      <section className="definition-section">
        <div className="definition-section-title">Goal Summary</div>
        {editable ? (
          <textarea
            className="definition-inline-textarea"
            value={problemBrief.goal_summary}
            disabled={sessionTerminated}
            rows={3}
            onFocus={onEnsureDefinitionEditing}
            onChange={(e) => updateGoalSummary(e.target.value)}
            placeholder="Summarize what the solver should optimize for."
          />
        ) : (
          <button
            type="button"
            className="definition-inline-display"
            disabled={sessionTerminated}
            onClick={onEnsureDefinitionEditing}
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
        onEnsureDefinitionEditing={onEnsureDefinitionEditing}
        onAddItem={() => addItem("gathered")}
        onUpdateItemText={updateItemText}
        onRemoveItem={removeItem}
      />

      <DefinitionSection
        title="Assumptions"
        description="Working assumptions that help the config move forward."
        items={assumptionItems}
        editable={editable}
        sessionTerminated={sessionTerminated}
        onEnsureDefinitionEditing={onEnsureDefinitionEditing}
        onAddItem={() => addItem("assumption")}
        onUpdateItemText={updateItemText}
        onRemoveItem={removeItem}
      />

      <section className="definition-section">
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
        {openQuestions.length === 0 ? (
          <div className="muted definition-empty">Nothing here yet.</div>
        ) : (
          <div className="definition-list">
            {openQuestions.map((question) => {
              const questionStatus = question.status === "answered" ? "answered" : "open";
              return (
                <div key={question.id} className="definition-item">
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
                      className="definition-inline-textarea definition-answer-textarea"
                      value={question.answer_text ?? ""}
                      placeholder="Type answer..."
                      disabled={openLocked}
                      rows={2}
                      onFocus={onEnsureDefinitionEditing}
                      onChange={(e) => updateOpenQuestionAnswer(question.id, e.target.value)}
                    />
                  ) : (
                    <button
                      type="button"
                      className="definition-inline-display"
                      style={{ textAlign: "left" }}
                      disabled={sessionTerminated}
                      onClick={onEnsureDefinitionEditing}
                    >
                      {(question.answer_text ?? "").length > 0 ? question.answer_text : "Type answer…"}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
