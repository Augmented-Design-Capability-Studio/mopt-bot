from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    workflow_mode: Literal["agile", "waterfall"] = "agile"


class SessionPatch(BaseModel):
    workflow_mode: Literal["agile", "waterfall"] | None = None
    panel_config: dict[str, Any] | None = None
    optimization_allowed: bool | None = None
    gemini_model: str | None = None
    gemini_api_key: str | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
    workflow_mode: str
    status: str
    panel_config: dict[str, Any] | None
    optimization_allowed: bool
    gemini_model: str | None


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


class SolveRunCreate(BaseModel):
    type: Literal["optimize", "evaluate"] = "optimize"
    problem: dict[str, Any]
    routes: list[list[int]] | None = None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
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
