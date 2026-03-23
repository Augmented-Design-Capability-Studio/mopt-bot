import { useState, type FocusEvent } from "react";

import type { ProblemBrief, ProblemBriefItem, ProblemBriefQuestion } from "@shared/api";

type DefinitionPanelProps = {
  problemBrief: ProblemBrief;
  editable: boolean;
  sessionTerminated: boolean;
  onChange: (value: ProblemBrief) => void;
  onPersistInlineEdit: (
    value: ProblemBrief,
    options?: { chatNote?: string },
  ) => void | Promise<void>;
};

type DefinitionSectionProps = {
  title: string;
  description: string;
  items: ProblemBriefItem[];
  editable: boolean;
  sessionTerminated: boolean;
  onAddItem: () => void;
  onSaveItemText: (id: string, text: string) => Promise<void>;
  onUpdateItem: (id: string, patch: Partial<ProblemBriefItem>) => void;
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

function DefinitionSection({
  title,
  description,
  items,
  editable,
  sessionTerminated,
  onAddItem,
  onSaveItemText,
  onUpdateItem,
  onRemoveItem,
}: DefinitionSectionProps) {
  const [editingItemId, setEditingItemId] = useState<string | null>(null);
  const [savingItemId, setSavingItemId] = useState<string | null>(null);
  const [draftByItemId, setDraftByItemId] = useState<Record<string, string>>({});

  function startEdit(item: ProblemBriefItem) {
    setEditingItemId(item.id);
    setDraftByItemId((current) => ({ ...current, [item.id]: item.text }));
  }

  async function saveItem(item: ProblemBriefItem) {
    const draft = (draftByItemId[item.id] ?? item.text).trim();
    setSavingItemId(item.id);
    await onSaveItemText(item.id, draft);
    setSavingItemId(null);
    setEditingItemId(null);
  }

  function cancelItem(item: ProblemBriefItem) {
    setDraftByItemId((current) => ({ ...current, [item.id]: item.text }));
    setEditingItemId(null);
  }

  function handleEditorBlur(event: FocusEvent<HTMLDivElement>, item: ProblemBriefItem) {
    if (savingItemId === item.id) return;
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    cancelItem(item);
  }

  return (
    <section className="definition-section">
      <div className="definition-section-header">
        <div>
          <div className="definition-section-title">{title}</div>
          <div className="muted">{description}</div>
        </div>
        <div className="definition-header-actions">
          {editable && !sessionTerminated ? (
            <button
              type="button"
              className="definition-icon-btn definition-add-btn"
              aria-label={`Add ${title}`}
              onClick={onAddItem}
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
          {items.map((item) => {
            const locked = sessionTerminated || !editable || !item.editable;
            const editing = editingItemId === item.id;
            const saving = savingItemId === item.id;
            const draft = draftByItemId[item.id] ?? item.text;
            return (
              <div key={item.id} className={`definition-item kind-${item.kind} ${editing ? "is-editing" : ""}`}>
                <div className="definition-item-meta">
                  <span className={`definition-chip kind-${item.kind}`}>{item.kind}</span>
                  <span className={`definition-chip status-${item.status}`}>{item.status}</span>
                  <span className="definition-source mono">{item.source}</span>
                  {(editable && item.editable && !sessionTerminated) ? (
                    <button
                      type="button"
                      className="definition-icon-btn definition-remove-btn"
                      aria-label="Remove row"
                      onClick={() => onRemoveItem(item.id)}
                    >
                      X
                    </button>
                  ) : null}
                </div>
                {!editing ? (
                  <button
                    type="button"
                    className="definition-inline-display"
                    disabled={locked}
                    onClick={() => startEdit(item)}
                  >
                    {item.text || "Click to add details..."}
                  </button>
                ) : (
                  <div className="definition-inline-editor" onBlur={(event) => handleEditorBlur(event, item)}>
                    <textarea
                      value={draft}
                      onChange={(event) =>
                        setDraftByItemId((current) => ({ ...current, [item.id]: event.target.value }))}
                      disabled={locked || saving}
                      rows={2}
                      autoFocus
                    />
                    <div className="definition-inline-actions">
                      <button type="button" onClick={() => void saveItem(item)} disabled={locked || saving}>
                        {saving ? "Saving..." : "Save"}
                      </button>
                      <button type="button" onClick={() => cancelItem(item)} disabled={saving}>
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
                {(editable && item.editable && !sessionTerminated && editing) ? (
                  <div className="definition-item-actions">
                    <label className="muted">
                      Type
                      <select
                        value={item.kind}
                        onChange={(e) => onUpdateItem(item.id, { kind: e.target.value as ProblemBriefItem["kind"] })}
                      >
                        <option value="gathered">Gathered</option>
                        <option value="assumption">Assumption</option>
                      </select>
                    </label>
                    <label className="muted">
                      Status
                      <select
                        value={item.status}
                        onChange={(e) => onUpdateItem(item.id, { status: e.target.value as ProblemBriefItem["status"] })}
                      >
                        <option value="active">Active</option>
                        <option value="confirmed">Confirmed</option>
                        <option value="rejected">Rejected</option>
                      </select>
                    </label>
                  </div>
                ) : null}
              </div>
            );
          })}
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
  onPersistInlineEdit,
}: DefinitionPanelProps) {
  const gatheredItems = problemBrief.items.filter((item) => item.kind === "gathered");
  const assumptionItems = problemBrief.items.filter((item) => item.kind === "assumption");
  const openQuestions = problemBrief.open_questions;
  const openQuestionsLocked = sessionTerminated || !editable;
  const [editingGoalSummary, setEditingGoalSummary] = useState(false);
  const [savingGoalSummary, setSavingGoalSummary] = useState(false);
  const [goalSummaryDraft, setGoalSummaryDraft] = useState(problemBrief.goal_summary);
  const [editingAnswerQuestionId, setEditingAnswerQuestionId] = useState<string | null>(null);
  const [savingAnswerQuestionId, setSavingAnswerQuestionId] = useState<string | null>(null);
  const [answerDraftByQuestionId, setAnswerDraftByQuestionId] = useState<Record<string, string>>({});

  async function persistBrief(nextBrief: ProblemBrief, options?: { chatNote?: string }): Promise<void> {
    onChange(nextBrief);
    await onPersistInlineEdit(nextBrief, options);
  }

  function updateItem(id: string, patch: Partial<ProblemBriefItem>) {
    const next = updateItems(problemBrief, (items) =>
      items.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
    void persistBrief(next);
  }

  function removeItem(id: string) {
    const next = updateItems(problemBrief, (items) => items.filter((item) => item.id !== id));
    void persistBrief(next);
  }

  function addItem(kind: "gathered" | "assumption") {
    const next = updateItems(problemBrief, (items) => [
      ...items,
      {
        id: makeId(kind),
        text: "Click to edit",
        kind,
        source: "user",
        status: "active",
        editable: true,
      },
    ]);
    onChange(next);
  }

  function removeOpenQuestion(questionId: string) {
    const nextQuestions = openQuestions.filter((question) => question.id !== questionId);
    const next = {
      ...problemBrief,
      open_questions: nextQuestions,
    };
    void persistBrief(next);
  }

  function addOpenQuestion() {
    if (openQuestionsLocked) return;
    const raw = window.prompt("Enter the open question");
    const text = raw == null ? "" : raw.trim();
    if (!text) return;
    const nextQuestions = [
      ...openQuestions,
      { id: makeId("open-question"), text, status: "open" as ProblemBriefQuestion["status"], answer_text: null },
    ];
    const next = {
      ...problemBrief,
      open_questions: nextQuestions,
    };
    onChange(next);
  }

  function startGoalSummaryEdit() {
    setGoalSummaryDraft(problemBrief.goal_summary);
    setEditingGoalSummary(true);
  }

  async function saveGoalSummary() {
    setSavingGoalSummary(true);
    await persistBrief({ ...problemBrief, goal_summary: goalSummaryDraft.trim() });
    setSavingGoalSummary(false);
    setEditingGoalSummary(false);
  }

  function cancelGoalSummary() {
    setGoalSummaryDraft(problemBrief.goal_summary);
    setEditingGoalSummary(false);
  }

  function startOpenQuestionAnswerEdit(question: ProblemBriefQuestion) {
    setEditingAnswerQuestionId(question.id);
    setAnswerDraftByQuestionId((current) => ({ ...current, [question.id]: question.answer_text ?? "" }));
  }

  async function saveOpenQuestionAnswer(question: ProblemBriefQuestion) {
    const answer = (answerDraftByQuestionId[question.id] ?? "").trim();
    const nextQuestions = openQuestions.map((row) =>
      row.id !== question.id
        ? row
        : {
            ...row,
            answer_text: answer || null,
            status: (answer ? "answered" : "open") as ProblemBriefQuestion["status"],
          },
    );
    setSavingAnswerQuestionId(question.id);
    await persistBrief({
      ...problemBrief,
      open_questions: nextQuestions,
    }, {
      chatNote: `I answered an open question. Question: "${question.text}". Answer: "${answer || "(left blank)"}". Please acknowledge this specific answer and tell me whether to keep this question open or close it. Do not change unrelated definition rows.`,
    });
    setSavingAnswerQuestionId(null);
    setEditingAnswerQuestionId(null);
  }

  function cancelOpenQuestionAnswer(question: ProblemBriefQuestion) {
    setAnswerDraftByQuestionId((current) => ({ ...current, [question.id]: question.answer_text ?? "" }));
    setEditingAnswerQuestionId(null);
  }

  function handleOpenQuestionEditorBlur(event: FocusEvent<HTMLDivElement>, question: ProblemBriefQuestion) {
    if (savingAnswerQuestionId === question.id) return;
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    cancelOpenQuestionAnswer(question);
  }

  function handleGoalSummaryEditorBlur(event: FocusEvent<HTMLDivElement>) {
    if (savingGoalSummary) return;
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    cancelGoalSummary();
  }

  return (
    <div className="definition-panel">
      <section className={`definition-section ${editingGoalSummary ? "is-editing" : ""}`}>
        <div className="definition-section-title">Goal Summary</div>
        {!editingGoalSummary ? (
          <button
            type="button"
            className="definition-inline-display"
            onClick={startGoalSummaryEdit}
            disabled={!editable || sessionTerminated}
          >
            {problemBrief.goal_summary || "Summarize what the solver should optimize for."}
          </button>
        ) : (
          <div className="definition-inline-editor" onBlur={handleGoalSummaryEditorBlur}>
            <textarea
              value={goalSummaryDraft}
              onChange={(event) => setGoalSummaryDraft(event.target.value)}
              disabled={!editable || sessionTerminated}
              rows={3}
              autoFocus
              placeholder="Summarize what the solver should optimize for."
            />
            <div className="definition-inline-actions">
              <button type="button" onClick={() => void saveGoalSummary()} disabled={!editable || sessionTerminated || savingGoalSummary}>
                {savingGoalSummary ? "Saving..." : "Save"}
              </button>
              <button type="button" onClick={cancelGoalSummary} disabled={savingGoalSummary}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>

      <DefinitionSection
        title="Gathered Info"
        description="Facts grounded in user messages or simulated uploads."
        items={gatheredItems}
        editable={editable}
        sessionTerminated={sessionTerminated}
        onAddItem={() => addItem("gathered")}
        onSaveItemText={async (id, text) => {
          await persistBrief(
            updateItems(problemBrief, (items) =>
              items.map((item) => (item.id === id ? { ...item, text } : item)),
            ),
          );
        }}
        onUpdateItem={updateItem}
        onRemoveItem={removeItem}
      />

      <DefinitionSection
        title="Assumptions"
        description="Working assumptions that help the config move forward."
        items={assumptionItems}
        editable={editable}
        sessionTerminated={sessionTerminated}
        onAddItem={() => addItem("assumption")}
        onSaveItemText={async (id, text) => {
          await persistBrief(
            updateItems(problemBrief, (items) =>
              items.map((item) => (item.id === id ? { ...item, text } : item)),
            ),
          );
        }}
        onUpdateItem={updateItem}
        onRemoveItem={removeItem}
      />

      <section className="definition-section">
        <div className="definition-section-header">
          <div>
            <div className="definition-section-title">Open Questions</div>
            <div className="muted">Outstanding clarifications that would improve the configuration.</div>
          </div>
          <div className="definition-header-actions">
            {editable && !sessionTerminated ? (
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
                <div key={question.id} className={`definition-item ${editingAnswerQuestionId === question.id ? "is-editing" : ""}`}>
                  <div className="definition-item-meta">
                    <span className={`definition-chip status-${questionStatus}`}>{questionStatus}</span>
                    {editable && !sessionTerminated ? (
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
                  <div
                    className="definition-inline-editor"
                    onBlur={(event) => handleOpenQuestionEditorBlur(event, question)}
                  >
                    <input
                      type="text"
                      value={editingAnswerQuestionId === question.id ? (answerDraftByQuestionId[question.id] ?? "") : (question.answer_text ?? "")}
                      placeholder="Type answer..."
                      disabled={openQuestionsLocked}
                      onFocus={() => startOpenQuestionAnswerEdit(question)}
                      onChange={(event) =>
                        setAnswerDraftByQuestionId((current) => ({ ...current, [question.id]: event.target.value }))}
                    />
                    {editingAnswerQuestionId === question.id ? (
                      <div className="definition-inline-actions">
                        <button
                          type="button"
                          onClick={() => void saveOpenQuestionAnswer(question)}
                          disabled={openQuestionsLocked || savingAnswerQuestionId === question.id}
                        >
                          {savingAnswerQuestionId === question.id ? "Saving..." : "Save"}
                        </button>
                        <button
                          type="button"
                          onClick={() => cancelOpenQuestionAnswer(question)}
                          disabled={savingAnswerQuestionId === question.id}
                        >
                          Cancel
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
