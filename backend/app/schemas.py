import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.problems.registry import DEFAULT_PROBLEM_ID


def serialize_utc_datetime(value: datetime) -> str:
    """Emit API datetimes as explicit UTC (Z) for stable client parsing."""
    normalized = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")


# Tutorial step IDs that the researcher can target via tutorial_step_override.
# `inspect-definition` is retained for backward compatibility with sessions
# created before the step list was restructured (the new default flow drops it).
TutorialStepIdLiteral = Literal[
    "chat-info",
    "upload-files",
    "inspect-definition",
    "update-definition",
    "inspect-config",
    "first-run",
    "read-run-summary",
    "inspect-results",
    "explain-run",
    "update-config",
    "second-run",
    "mark-candidate",
    "third-run",
    "tutorial-complete",
]


class SessionCreate(BaseModel):
    # Participant apps omit this; researcher sets workflow via PATCH. Default is conservative (gated runs).
    workflow_mode: Literal["agile", "waterfall", "demo"] = "waterfall"
    participant_number: str | None = Field(default=None, max_length=64)
    test_problem_id: str | None = Field(default=None, max_length=64)


class SessionPatch(BaseModel):
    workflow_mode: Literal["agile", "waterfall", "demo"] | None = None
    participant_number: str | None = Field(default=None, max_length=64)
    test_problem_id: str | None = Field(default=None, max_length=64)
    panel_config: dict[str, Any] | None = None
    problem_brief: dict[str, Any] | None = None
    optimization_allowed: bool | None = None
    optimization_runs_blocked_by_researcher: bool | None = None
    allow_agent_autorun: bool | None = None
    participant_tutorial_enabled: bool | None = None
    tutorial_step_override: TutorialStepIdLiteral | None = None
    gemini_model: str | None = None
    embedding_model: str | None = None
    gemini_api_key: str | None = None


class ProblemBriefItem(BaseModel):
    id: str
    text: str
    kind: Literal["gathered", "assumption"]
    source: Literal["user", "upload", "agent"]
    # Canonical anchor to a `goal_terms[K]` entry. Two server-side consumers
    # act on this:
    #   1. Lifecycle (on `kind: "assumption"` rows): the resolver at
    #      `derivation._resolve_anchored_provisional_rows` drops the row once
    #      `K` has user-gathered evidence.
    #   2. Display (on rows whose text follows the canonical
    #      `<Label> (<role>, weight N) — <rationale>` shape): the normalizer at
    #      `problem_brief._refresh_referenced_goal_term_text` keeps the
    #      parenthesized middle in sync with live `goal_terms[K].{type, weight}`
    #      so hallucinated or stale weight values can't survive.
    # Both behaviors compose; set the field whenever either applies. Omit on
    # qualitative rows that don't reference a specific goal term. Same
    # Pydantic-strip caveat as `ProblemBriefQuestion.topic` — listing the
    # field here keeps it from being dropped on PATCH round-trips.
    goal_key: str | None = None


class ProblemBriefQuestion(BaseModel):
    id: str
    text: str
    status: Literal["open", "answered"] = "open"
    answer_text: str | None = None
    # Required by the main-turn schema (`_PROBLEM_BRIEF_QUESTION_SCHEMA`) so
    # the server can distinguish foundational-topic OQs (server-owned) from
    # free-form clarifications. Optional here because legacy briefs in
    # snapshots and external PATCH bodies may omit it; `normalize_problem_brief`
    # defaults missing values to `"other"`. Listing the field on the Pydantic
    # model is what stops it from being silently stripped during
    # `body.problem_brief.model_dump()` on the brief PATCH endpoint — the
    # missing line was the reason router-generated `*-followup` OQs lost
    # their inherited topic and slipped past the foundational-topic strip.
    topic: Literal["upload", "primary_goal", "search_strategy", "other"] = "other"
    # Canonical anchor to a `goal_terms[K]` entry (e.g. "capacity_penalty" for
    # *"Should I add a capacity penalty?"*). The resolver at
    # `derivation._resolve_anchored_provisional_rows` drops the OQ once the
    # key lands in `brief.goal_terms`, so the LLM doesn't have to remember to
    # drop the row via `replace_open_questions=true`. The same resolver path
    # also runs from `sync_problem_brief_from_panel` when the user edits the
    # matching weight/type/rank via the panel. Foundational-topic OQs
    # (topic != "other") use the monitor state machine instead — leave this
    # empty on those. Same Pydantic-strip caveat as `topic`. Field name
    # matches `ProblemBriefItem.goal_key` so both anchor types share one
    # vocabulary.
    goal_key: str | None = None


class RunSummaryEntry(BaseModel):
    """One structured entry per completed run.

    Server-managed: every field is filled deterministically by
    ``derivation.consolidate_runs`` on each run-ack from the freshly-loaded
    ``OptimizationRun`` row plus the previous entry for ``delta_from_prev``.
    The LLM never writes here — the rolling-prose ``run_summary`` field this
    replaces was an LLM-maintained string and drifted (stale numbers, hand-
    written deltas that disagreed with the actual cost diff).

    The frontend Run Summary section renders one collapsed accordion item
    per entry. The LLM receives the full array in its prompt context, so
    cross-run reasoning ("how did Run #3 compare to Run #5?") works without
    re-fetching from the runs table.
    """

    run_number: int
    cost: float | None = None
    ok: bool = True
    algorithm: str = ""
    # Plain-English summary of any violations, rendered by the active port via
    # ``format_run_context_violation_details``. Empty when the run had none.
    violations_summary: str = ""
    # Comparison vs. the previous entry's cost / violations. Empty on the
    # first run (nothing to compare to). Single short line.
    delta_from_prev: str = ""


class ProblemBrief(BaseModel):
    goal_summary: str = ""
    # ``runs`` is the structured per-run history. Replaces the legacy
    # ``run_summary`` rolling-string field (which the LLM had to maintain
    # turn-by-turn and routinely drifted from actual cost/violation numbers).
    # Server-managed end-to-end: ``derivation.consolidate_runs`` appends
    # an entry on every run-ack from the matching ``OptimizationRun`` row.
    # The legacy ``run_summary`` field on PATCHed briefs is silently dropped
    # by ``normalize_problem_brief`` — no migration needed because the
    # canonical data lives in the ``OptimizationRun`` table.
    runs: list[RunSummaryEntry] = Field(default_factory=list)
    items: list[ProblemBriefItem] = Field(default_factory=list)
    # Accept legacy string questions; normalize_problem_brief coerces to {id, text}.
    open_questions: list[ProblemBriefQuestion | str] = Field(default_factory=list)
    # `goal_terms` is the structured carrier for every per-key
    # weight/type/properties/evidence record. **Must be listed here** —
    # Pydantic silently drops unlisted fields during
    # `body.problem_brief.model_dump()` on the brief PATCH endpoint, so
    # before this line existed every OQ-answer save wiped the committed
    # goal terms (observed pattern: user answers an OQ → backend saves
    # the validated brief → `goal_terms.travel_time` gone → S5 verify
    # immediately flags "travel_time on panel but not in brief"). Same
    # Pydantic-strip class of bug as `ProblemBriefQuestion.topic`.
    goal_terms: dict[str, Any] = Field(default_factory=dict)
    # `unmodeled_requests` is the append-only audit log of participant
    # asks that don't map to any modelled goal-term. Same Pydantic-strip
    # concern — listing it here keeps it stable across PATCH round-trips.
    unmodeled_requests: list[dict[str, Any]] = Field(default_factory=list)
    # One-way sticky warmth flag (see `topic_engaged_next` in the
    # main-turn patch). Stripped here would cause the brief to
    # silently regress to cold-start framing on every PATCH save.
    topic_engaged: bool = False
    # ``priority_line`` is SERVER-managed — recomputed from
    # ``goal_terms[K].rank`` on every normalize pass. The LLM never writes
    # it (anything emitted is overwritten). Pydantic field exists so the
    # value survives PATCH round-trips for the frontend to render.
    # Stored as ``"Priority order: 1) K1, 2) K2, ..."`` using raw goal-term
    # keys; the frontend prettifies via its weight-label catalog.
    priority_line: str = ""
    solver_scope: str = ""
    backend_template: str = ""


ProcessingStatus = Literal["idle", "pending", "ready", "failed"]


class SessionProcessingState(BaseModel):
    processing_revision: int = 0
    brief_status: ProcessingStatus = "idle"
    config_status: ProcessingStatus = "idle"
    processing_error: str | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
    workflow_mode: str
    participant_number: str | None
    test_problem_id: str = DEFAULT_PROBLEM_ID
    status: str
    panel_config: dict[str, Any] | None
    problem_brief: ProblemBrief
    processing: SessionProcessingState = Field(default_factory=SessionProcessingState)
    optimization_allowed: bool
    optimization_runs_blocked_by_researcher: bool
    allow_agent_autorun: bool = False
    participant_tutorial_enabled: bool = False
    tutorial_step_override: TutorialStepIdLiteral | None = None
    tutorial_chat_started: bool = False
    tutorial_uploaded_files: bool = False
    tutorial_definition_tab_visited: bool = False
    tutorial_definition_saved: bool = False
    tutorial_config_tab_visited: bool = False
    tutorial_config_first_saved: bool = False
    tutorial_config_saved: bool = False
    tutorial_first_run_done: bool = False
    tutorial_second_run_done: bool = False
    tutorial_run_summary_read: bool = False
    tutorial_results_inspected: bool = False
    tutorial_explain_used: bool = False
    tutorial_candidate_marked: bool = False
    tutorial_third_run_done: bool = False
    tutorial_completed: bool = False
    optimization_gate_engaged: bool = False
    gemini_model: str | None
    embedding_model: str | None
    gemini_key_configured: bool = False
    content_reset_revision: int = 0
    brief_panel_drift: list[dict[str, Any]] = Field(default_factory=list)

    @field_serializer("created_at", "updated_at")
    def _serialize_datetimes(self, value: datetime) -> str:
        return serialize_utc_datetime(value)


ChatContextKind = Literal[
    "run_started",
    "run_ack",
    "config_save",
    "definition_save",
    "config_restore",
    "definition_restore",
    "definition_cleanup",
    "open_question_answered",
    "explain_run",
    "simulated_upload",
]


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=32000)
    invoke_model: bool = False
    # When true with invoke_model: visible reply only; skip hidden brief derivation / panel resync.
    skip_hidden_brief_update: bool = False
    # When true: also skip the panel-derivation LLM call (used by the server-side
    # intent classifier when the message is a concept question / clarification
    # that doesn't intend any panel change).
    skip_panel_derivation: bool = False
    # Typed discriminator for synthetic context messages the frontend posts
    # (run-ack, config-save, definition-restore, …). When set, takes precedence
    # over the legacy content-regex classifiers in
    # ``app.routers.sessions.intent`` so we no longer have to match strings
    # like "Run #N just completed". ``None`` (the default) preserves the
    # regex-fallback behaviour for ad-hoc / programmatic posts.
    context_kind: ChatContextKind | None = None


class ResearcherSimulateParticipantUploadBody(BaseModel):
    """Researcher-only: inject the same user message as a simulated file upload."""

    file_names: list[str] | None = None
    invoke_model: bool = False


class SteerCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=32000)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    role: str
    content: str
    visible_to_participant: bool
    kind: str
    meta: dict[str, Any] | None = None

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        return serialize_utc_datetime(value)

    @model_validator(mode="before")
    @classmethod
    def _decode_meta_json(cls, obj: Any) -> Any:
        # Decode meta_json (stored as a Text column on ChatMessage) into the
        # `meta` dict the API exposes. Runs in `mode="before"` so FastAPI's
        # response_model serialization picks it up — overriding the
        # `model_validate` classmethod alone is NOT enough because FastAPI
        # goes through pydantic-core's schema validators directly, bypassing
        # classmethod overrides. Kept tolerant: a malformed string just
        # becomes None so a single bad row never breaks the chat list.
        if hasattr(obj, "meta_json") and not isinstance(obj, dict):
            raw = getattr(obj, "meta_json", None)
            parsed: dict[str, Any] | None = None
            if isinstance(raw, str) and raw.strip():
                try:
                    decoded = json.loads(raw)
                    parsed = decoded if isinstance(decoded, dict) else None
                except json.JSONDecodeError:
                    parsed = None
            return {
                "id": obj.id,
                "created_at": obj.created_at,
                "role": obj.role,
                "content": obj.content,
                "visible_to_participant": obj.visible_to_participant,
                "kind": obj.kind,
                "meta": parsed,
            }
        return obj


class OpenQuestionClassifierInput(BaseModel):
    """One OQ answer to be rephrased + bucketed by the classifier."""

    question_id: str
    question_text: str
    answer_text: str


class OpenQuestionGoalTermProposal(BaseModel):
    """The benchmark goal-term key endorsed by an answered OQ.

    Emitted by the OQ classifier when the participant's answer concretely
    endorses introducing (or confirming) a benchmark goal-term concept that
    isn't yet in ``brief.goal_terms`` — e.g. answering "yes" to *"Should I
    add workload balance as a priority?"* must seed the ``workload_balance``
    key so the brief→panel sync can attach a weight. Without this signal,
    the answer only lands as a gathered items[] row and the panel-derive
    LLM (which is told **not** to invent goal-term keys from prose) leaves
    the panel unchanged — exactly the regression that motivated this field.
    """

    key: str
    type: Literal["objective", "soft", "hard", "custom"] = "soft"


class OpenQuestionClassification(BaseModel):
    """Classifier output for one OQ answer.

    bucket="gathered": rephrased_text holds the concise gathered-info line.
    bucket="assumption": assumption_text holds the agent-decided assumption (agile only).
    bucket="new_open_question": new_question_text + choices hold the simpler follow-up (waterfall only).
    """

    question_id: str
    bucket: Literal["gathered", "assumption", "new_open_question"]
    rephrased_text: str | None = None
    assumption_text: str | None = None
    new_question_text: str | None = None
    goal_term_proposal: OpenQuestionGoalTermProposal | None = None


class OpenQuestionClassifierTurn(BaseModel):
    """Top-level structured response from classify_answered_open_questions."""

    classifications: list[OpenQuestionClassification] = Field(default_factory=list)


class AssumptionMaintenanceItem(BaseModel):
    """One assumption-row decision returned by the maintenance pass.

    Used in agile/demo modes only — waterfall has no assumption rows. The
    server applies the action to the items[] row identified by ``id``:

    - ``keep``: no-op.
    - ``rephrase``: update only ``text`` to ``rephrased_text``; preserve
      ``kind`` and ``source`` (still a `kind: "assumption"`, `source:
      "agent"` row).
    - ``drop``: remove the row entirely.
    - ``promote_to_gathered``: lock the row in. Set ``kind`` to
      ``"gathered"`` and ``source`` to ``"user"`` (the user originated the
      lock-in — see memory ``feedback_provenance_origin_not_phrasing``).
      ``rephrased_text`` carries the locked-in natural-language sentence.
    """

    id: str
    action: Literal["keep", "rephrase", "drop", "promote_to_gathered"]
    rephrased_text: str | None = None


class OQMaintenanceItem(BaseModel):
    """One open-question lifecycle decision returned by the main-turn LLM.

    Symmetric to ``AssumptionMaintenanceItem`` — gives the model a per-row
    way to express OQ lifecycle instead of round-tripping the full
    survivor list via ``replace_open_questions=true``. The flag/list path
    remains supported for genuine cleanup-mode re-authoring; routine
    "user answered X, drop X" turns should use this carrier instead.

    - ``keep``: no-op.
    - ``rephrase``: update only ``text`` to ``rephrased_text`` (e.g. tighten
      a question after partial info). Preserves status/topic/anchor.
    - ``drop``: remove the OQ entirely. Use when the answer is already
      represented elsewhere (e.g. a `config-weight-K` row was just
      synthesized for the proposed key).
    - ``mark_answered``: write ``status="answered" + answer_text``; the
      existing ``_promote_answered_open_questions_to_gathered`` normalizer
      folds it into a gathered row on the next pass.
    """

    id: str
    action: Literal["keep", "rephrase", "drop", "mark_answered"]
    rephrased_text: str | None = None
    answer_text: str | None = None


# ============================================================================
# Chat-pipeline schemas
# ============================================================================


class PipelineIssue(BaseModel):
    """One verification issue surfaced by S2 (brief) or S5 (panel) checks.

    Same shape feeds three consumers:
    1. LLM retry feedback (the issue list is appended to the prompt as an
       audit block so the model can fix specific items rather than redo
       the whole turn).
    2. Frontend status bubble (issues are spelled out in plain English so
       participants understand what failed).
    3. Server logs (workflow-compliance telemetry).

    ``category`` is the typed bucket; ``message`` is the plain-English line
    that surfaces to both the LLM and the participant.
    """

    category: Literal[
        "schema_invalid",
        "claim_without_delta",
        "delta_without_claim",
        "unanchored_goal_term",
        "algorithm_committed_missing_carrier",
        "algorithm_carrier_without_commit",
        "workflow_invariant_violation",
        "runack_invariant_violation",
        "port_companion",
        "brief_panel_mismatch",
        "brief_panel_algorithm_mismatch",
        "oq_replace_without_list",
        "ask_without_oq",
    ]
    severity: Literal["error", "warn"] = "error"
    subject: str = ""
    message: str = ""


class PipelineStageName(BaseModel):
    """Enumerated stage identifier used by the per-message pipeline status."""

    name: Literal[
        "drafting",
        "verifying_brief",
        "applying",
        "deriving_config",
        "verifying_config",
        "complete",
        "skipped",
    ]


PipelineStageState = Literal["pending", "in_progress", "success", "failed", "skipped", "paused"]


class PipelineStage(BaseModel):
    """One row in the status checklist attached to an assistant message."""

    name: Literal[
        "drafting",
        "verifying_brief",
        "applying",
        "deriving_config",
        "verifying_config",
    ]
    state: PipelineStageState = "pending"
    # Plain-English label rendered by the frontend ("Drafting reply",
    # "Verifying intent & definition", "Deriving config", etc.). The frontend
    # owns the canonical mapping but accepts overrides on a per-stage basis
    # (e.g. config-edit flavor wants "Verifying brief ↔ config").
    label: str | None = None
    # Optional informational detail rows surfaced inside this stage as a
    # nested, collapsed-by-default sub-list — e.g. "Applying changes" lists the
    # material (solver-affecting) changes that landed this turn. Distinct from
    # ``issues``, which are failures shown prominently.
    details: list[str] | None = None
    # Issues attached to this stage when state=="failed" or "paused".
    issues: list[PipelineIssue] = Field(default_factory=list)
    # Set true once we've already burned the single allotted retry.
    retried: bool = False


class PipelineStatus(BaseModel):
    """Per-message snapshot of pipeline progress.

    Attached to the assistant message's ``meta.pipeline`` field. The
    frontend renders it as a checklist below the message bubble; it
    updates as the backend mutates stages. State machine:

    - Stage begins ``pending``, transitions to ``in_progress``, then either
      ``success`` (or ``skipped``) or ``failed``.
    - On first ``failed``: backend bumps ``retried=True`` and re-runs the
      stage; the row briefly returns to ``in_progress``.
    - On second ``failed``: stage transitions to ``paused`` and the
      pipeline halts. Frontend shows the issue list + Retry / Revert /
      Keep-chatting action row.

    ``flavor`` distinguishes the trigger so the frontend can choose the
    right canonical labels (chat / brief-edit / config-edit / run-ack).
    """

    flavor: Literal[
        "chat",
        "brief_edit_ack",
        "config_edit_ack",
        "run_ack",
    ] = "chat"
    stages: list[PipelineStage] = Field(default_factory=list)
    # When set, the pipeline is paused on this stage's name. Frontend uses
    # this to decide whether to render the action row.
    paused_stage: str | None = None


class ChatTurnResponse(BaseModel):
    """Main-turn LLM response (single structured Gemini call per turn).

    Produces the visible reply, intent flags, brief patch, and per-row
    assumption decisions (agile/demo only — waterfall LLMs leave
    ``assumption_actions`` empty and the merge ignores it on waterfall
    turns). The pipeline runner verifies the response and may retry
    with an issues-feedback block once before pausing.
    """

    # --- Visible reply -------------------------------------------------------
    assistant_message: str = Field(..., max_length=32000)
    # Plain-English follow-up shown on pipeline pause (frontend appends it as
    # an inline note next to the action row). LLM emits when the user's
    # message would land an irreversibly mismatched commitment. Optional.
    inline_followup: str | None = Field(default=None, max_length=2000)

    # --- Intent flags --------------------------------------------------------
    is_change_intent: bool = True
    cleanup_intent: bool = False
    clear_intent: bool = False
    should_trigger_run: bool = False
    intent_type: Literal["none", "affirm_invite", "direct_request"] = "none"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    is_run_invitation: bool = False
    change_clause: str | None = None
    question_clause: str | None = None

    # --- Brief patch ---------------------------------------------------------
    problem_brief_patch: dict[str, Any] | None = None
    replace_editable_items: bool = False
    replace_open_questions: bool = False
    cleanup_mode: bool = False

    # --- Maintenance --------------------------------------------------------
    # The maintenance fields are optional inputs to the merge. ``oq_actions``
    # is the per-row OQ lifecycle carrier (all modes) — symmetric to
    # ``assumption_actions``. Prefer it for routine turns; only set
    # ``replace_open_questions=true`` when re-authoring the full list as part
    # of a cleanup. ``assumption_actions`` covers per-row assumption-item
    # decisions in agile/demo (waterfall has no assumption rows).
    oq_actions: list[OQMaintenanceItem] = Field(default_factory=list)
    assumption_actions: list[AssumptionMaintenanceItem] = Field(default_factory=list)


class PostMessagesResponse(BaseModel):
    messages: list[MessageOut]
    panel_config: dict[str, Any] | None = None
    problem_brief: ProblemBrief | None = None
    processing: SessionProcessingState | None = None


class SolveRunCreate(BaseModel):
    type: Literal["optimize", "evaluate"] = "optimize"
    problem: dict[str, Any]
    routes: list[list[int]] | None = None
    candidate_seed_run_ids: list[int] | None = None
    candidate_seeds: list[dict[str, Any]] | None = None


class RunEvaluateEditBody(BaseModel):
    problem: dict[str, Any]
    routes: list[list[int]]


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_number: int
    created_at: datetime
    run_type: str
    ok: bool
    cost: float | None
    reference_cost: float | None
    error_message: str | None
    request: dict[str, Any] | None = None
    result: dict[str, Any] | None = None

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        return serialize_utc_datetime(value)


class ModelSettingsBody(BaseModel):
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    embedding_model: str | None = None


class ParticipantPanelUpdate(BaseModel):
    panel_config: dict[str, Any]
    acknowledgement: str | None = Field(default=None, max_length=2000)


class ParticipantProblemBriefUpdate(BaseModel):
    problem_brief: ProblemBrief
    acknowledgement: str | None = Field(default=None, max_length=2000)


class CleanupOpenQuestionsBody(BaseModel):
    infer_resolved: bool = True


class ParticipantTutorialUpdate(BaseModel):
    participant_tutorial_enabled: bool | None = None
    tutorial_step_override: TutorialStepIdLiteral | None = None
    tutorial_chat_started: bool | None = None
    tutorial_uploaded_files: bool | None = None
    tutorial_definition_tab_visited: bool | None = None
    tutorial_definition_saved: bool | None = None
    tutorial_config_tab_visited: bool | None = None
    tutorial_config_first_saved: bool | None = None
    tutorial_config_saved: bool | None = None
    tutorial_first_run_done: bool | None = None
    tutorial_second_run_done: bool | None = None
    tutorial_run_summary_read: bool | None = None
    tutorial_results_inspected: bool | None = None
    tutorial_explain_used: bool | None = None
    tutorial_candidate_marked: bool | None = None
    tutorial_third_run_done: bool | None = None
    tutorial_completed: bool | None = None


class SnapshotOut(BaseModel):
    """Snapshot summary with full brief+panel for restore."""

    id: int
    created_at: datetime
    event_type: str
    items_count: int
    questions_count: int
    has_config: bool
    problem_brief: dict[str, Any] | None = None
    panel_config: dict[str, Any] | None = None

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        return serialize_utc_datetime(value)
