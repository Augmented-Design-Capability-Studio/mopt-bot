from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.problems.registry import DEFAULT_PROBLEM_ID


def serialize_utc_datetime(value: datetime) -> str:
    """Emit API datetimes as explicit UTC (Z) for stable client parsing."""
    normalized = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")


class SessionCreate(BaseModel):
    # Participant apps omit this; researcher sets workflow via PATCH. Default is conservative (gated runs).
    workflow_mode: Literal["agile", "waterfall", "demo"] = "waterfall"
    participant_number: str | None = Field(default=None, max_length=64)


class SessionPatch(BaseModel):
    workflow_mode: Literal["agile", "waterfall", "demo"] | None = None
    participant_number: str | None = Field(default=None, max_length=64)
    test_problem_id: str | None = Field(default=None, max_length=64)
    panel_config: dict[str, Any] | None = None
    problem_brief: dict[str, Any] | None = None
    optimization_allowed: bool | None = None
    optimization_runs_blocked_by_researcher: bool | None = None
    gemini_model: str | None = None
    gemini_api_key: str | None = None


class ProblemBriefItem(BaseModel):
    id: str
    text: str
    kind: Literal["gathered", "assumption", "system"]
    source: Literal["user", "upload", "agent", "system"]
    status: Literal["active", "confirmed", "rejected"]
    editable: bool = True


class ProblemBriefQuestion(BaseModel):
    id: str
    text: str
    status: Literal["open", "answered"] = "open"
    answer_text: str | None = None


class ProblemBrief(BaseModel):
    goal_summary: str = ""
    items: list[ProblemBriefItem] = Field(default_factory=list)
    # Accept legacy string questions; normalize_problem_brief coerces to {id, text}.
    open_questions: list[ProblemBriefQuestion | str] = Field(default_factory=list)
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
    optimization_gate_engaged: bool = False
    gemini_model: str | None
    gemini_key_configured: bool = False
    content_reset_revision: int = 0

    @field_serializer("created_at", "updated_at")
    def _serialize_datetimes(self, value: datetime) -> str:
        return serialize_utc_datetime(value)


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=32000)
    invoke_model: bool = False
    # When true with invoke_model: visible reply only; skip hidden brief derivation / panel resync.
    skip_hidden_brief_update: bool = False


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

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        return serialize_utc_datetime(value)


class ChatModelTurn(BaseModel):
    """Structured Gemini reply for chat-to-brief updates."""

    assistant_message: str = Field(..., max_length=32000)
    # Back-compat field: kept optional for old callers/tests, but chat agent should not emit it.
    panel_patch: dict[str, Any] | None = None
    problem_brief_patch: dict[str, Any] | None = None
    # Cleanup-mode controls: when true, backend replaces existing editable content.
    replace_editable_items: bool = False
    replace_open_questions: bool = False
    cleanup_mode: bool = False


class RunTriggerIntentTurn(BaseModel):
    """Structured intent classification for chat-triggered optimization runs."""

    should_trigger_run: bool = False
    intent_type: Literal["none", "affirm_invite", "direct_request"] = "none"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


class ProblemBriefUpdateTurn(BaseModel):
    """Structured hidden Gemini reply for brief extraction/update only."""

    problem_brief_patch: dict[str, Any] | None = None
    replace_editable_items: bool = False
    replace_open_questions: bool = False
    cleanup_mode: bool = False


class PostMessagesResponse(BaseModel):
    messages: list[MessageOut]
    panel_config: dict[str, Any] | None = None
    problem_brief: ProblemBrief | None = None
    processing: SessionProcessingState | None = None


class SolveRunCreate(BaseModel):
    type: Literal["optimize", "evaluate"] = "optimize"
    problem: dict[str, Any]
    routes: list[list[int]] | None = None


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


class ParticipantPanelUpdate(BaseModel):
    panel_config: dict[str, Any]
    acknowledgement: str | None = Field(default=None, max_length=2000)


class ParticipantProblemBriefUpdate(BaseModel):
    problem_brief: ProblemBrief
    acknowledgement: str | None = Field(default=None, max_length=2000)


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
