import type { ProblemBrief, ProblemBriefItem, ProblemBriefQuestion } from "@shared/api";

type DefinitionPanelProps = {
  problemBrief: ProblemBrief;
  editable: boolean;
  sessionTerminated: boolean;
  onChange: (value: ProblemBrief) => void;
};

type DefinitionSectionProps = {
  title: string;
  description: string;
  items: ProblemBriefItem[];
  editable: boolean;
  sessionTerminated: boolean;
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
  onUpdateItem,
  onRemoveItem,
}: DefinitionSectionProps) {
  return (
    <section className="definition-section">
      <div className="definition-section-header">
        <div>
          <div className="definition-section-title">{title}</div>
          <div className="muted">{description}</div>
        </div>
        <span className="definition-count">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <div className="muted definition-empty">Nothing here yet.</div>
      ) : (
        <div className="definition-list">
          {items.map((item) => {
            const locked = sessionTerminated || !editable || !item.editable;
            return (
              <div key={item.id} className={`definition-item kind-${item.kind}`}>
                <div className="definition-item-meta">
                  <span className={`definition-chip kind-${item.kind}`}>{item.kind}</span>
                  <span className={`definition-chip status-${item.status}`}>{item.status}</span>
                  <span className="definition-source mono">{item.source}</span>
                </div>
                <textarea
                  value={item.text}
                  onChange={(e) => onUpdateItem(item.id, { text: e.target.value })}
                  disabled={locked}
                  rows={2}
                />
                {editable && item.editable && !sessionTerminated && (
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
                    <button type="button" onClick={() => onRemoveItem(item.id)}>
                      Remove
                    </button>
                  </div>
                )}
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
}: DefinitionPanelProps) {
  const gatheredItems = problemBrief.items.filter((item) => item.kind === "gathered");
  const assumptionItems = problemBrief.items.filter((item) => item.kind === "assumption");
  const openQuestions = problemBrief.open_questions;
  const openQuestionsLocked = sessionTerminated || !editable;

  function updateItem(id: string, patch: Partial<ProblemBriefItem>) {
    onChange(
      updateItems(problemBrief, (items) =>
        items.map((item) => (item.id === id ? { ...item, ...patch } : item)),
      ),
    );
  }

  function removeItem(id: string) {
    onChange(updateItems(problemBrief, (items) => items.filter((item) => item.id !== id)));
  }

  function addItem(kind: "gathered" | "assumption") {
    onChange(
      updateItems(problemBrief, (items) => [
        ...items,
        {
          id: makeId(kind),
          text: "",
          kind,
          source: "user",
          status: "active",
          editable: true,
        },
      ]),
    );
  }

  function setOpenQuestions(nextQuestions: ProblemBriefQuestion[]) {
    onChange({
      ...problemBrief,
      open_questions: nextQuestions,
    });
  }

  function updateOpenQuestion(questionId: string, value: string) {
    setOpenQuestions(openQuestions.map((question) => (question.id === questionId ? { ...question, text: value } : question)));
  }

  function removeOpenQuestion(questionId: string) {
    setOpenQuestions(openQuestions.filter((question) => question.id !== questionId));
  }

  function addOpenQuestion() {
    setOpenQuestions([...openQuestions, { id: makeId("open-question"), text: "" }]);
  }

  return (
    <div className="definition-panel">
      <section className="definition-section">
        <div className="definition-section-title">Goal Summary</div>
        <textarea
          value={problemBrief.goal_summary}
          onChange={(e) => onChange({ ...problemBrief, goal_summary: e.target.value })}
          disabled={!editable || sessionTerminated}
          rows={3}
          placeholder="Summarize what the solver should optimize for."
        />
      </section>

      <DefinitionSection
        title="Gathered Info"
        description="Facts grounded in user messages or simulated uploads."
        items={gatheredItems}
        editable={editable}
        sessionTerminated={sessionTerminated}
        onUpdateItem={updateItem}
        onRemoveItem={removeItem}
      />

      <DefinitionSection
        title="Assumptions"
        description="Working assumptions that help the config move forward."
        items={assumptionItems}
        editable={editable}
        sessionTerminated={sessionTerminated}
        onUpdateItem={updateItem}
        onRemoveItem={removeItem}
      />

      <section className="definition-section">
        <div className="definition-section-header">
          <div>
            <div className="definition-section-title">Open Questions</div>
            <div className="muted">Outstanding clarifications that would improve the configuration.</div>
          </div>
          <span className="definition-count">{openQuestions.length}</span>
        </div>
        {openQuestions.length === 0 ? (
          <div className="muted definition-empty">Nothing here yet.</div>
        ) : (
          <div className="definition-list">
            {openQuestions.map((question) => (
              <div key={question.id} className="definition-item">
                <textarea
                  value={question.text}
                  onChange={(e) => updateOpenQuestion(question.id, e.target.value)}
                  disabled={openQuestionsLocked}
                  rows={2}
                  placeholder="Add an open question."
                />
                {editable && !sessionTerminated && (
                  <div className="definition-item-actions">
                    <button type="button" onClick={() => removeOpenQuestion(question.id)}>
                      Remove
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {editable && !sessionTerminated && (
        <div className="definition-add-actions">
          <button type="button" onClick={() => addItem("gathered")}>
            Add gathered info
          </button>
          <button type="button" onClick={() => addItem("assumption")}>
            Add assumption
          </button>
          <button type="button" onClick={addOpenQuestion}>
            Add open question
          </button>
        </div>
      )}
    </div>
  );
}
