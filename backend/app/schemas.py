from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    # Participant apps omit this; researcher sets workflow via PATCH. Default is conservative (gated runs).
    workflow_mode: Literal["agile", "waterfall"] = "waterfall"
    participant_number: str | None = Field(default=None, max_length=64)


class SessionPatch(BaseModel):
    workflow_mode: Literal["agile", "waterfall"] | None = None
    participant_number: str | None = Field(default=None, max_length=64)
    panel_config: dict[str, Any] | None = None
    problem_brief: dict[str, Any] | None = None
    optimization_allowed: bool | None = None
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
    status: str
    panel_config: dict[str, Any] | None
    problem_brief: ProblemBrief
    processing: SessionProcessingState = Field(default_factory=SessionProcessingState)
    optimization_allowed: bool
    gemini_model: str | None
    gemini_key_configured: bool = False


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=32000)
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
    result: dict[str, Any] | None = None


class ModelSettingsBody(BaseModel):
    gemini_api_key: str | None = None
    gemini_model: str | None = None


class ParticipantPanelUpdate(BaseModel):
    panel_config: dict[str, Any]
    acknowledgement: str | None = Field(default=None, max_length=2000)


class ParticipantProblemBriefUpdate(BaseModel):
    problem_brief: ProblemBrief
    acknowledgement: str | None = Field(default=None, max_length=2000)
