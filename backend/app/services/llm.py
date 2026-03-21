"""Server-side Gemini via google-genai: use Chat API (chats.create + send_message), not raw generate_content."""

from __future__ import annotations

import json
import logging
from typing import Any

from google import genai
from google.genai import types

from app.prompts.study_chat import (
    STUDY_CHAT_STRUCTURED_JSON_RULES,
    STUDY_CHAT_SYSTEM_PROMPT,
    STUDY_CHAT_WORKFLOW_AGILE,
    STUDY_CHAT_WORKFLOW_WATERFALL,
)
from app.schemas import ChatModelTurn

log = logging.getLogger(__name__)

# Gemini rejects nested OpenAPI "additional_properties" when passing a Pydantic model as
# response_schema (dict[str, Any] becomes additionalProperties: true). Use response_json_schema
# with a hand-written schema instead. Keep it explicit around `problem.weights`, since a loose
# "object" schema lets malformed fragments like `{"weights": "{"}` slip through.
_WEIGHTS_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "travel_time": {"type": "number"},
        "fuel_cost": {"type": "number"},
        "deadline_penalty": {"type": "number"},
        "capacity_penalty": {"type": "number"},
        "workload_balance": {"type": "number"},
        "worker_preference": {"type": "number"},
        "priority_penalty": {"type": "number"},
    },
}

_DRIVER_PREFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vehicle_idx": {"type": "integer"},
        "condition": {
            "type": "string",
            "enum": ["zone_d", "express_order", "shift_over_hours"],
        },
        "penalty": {"type": "number"},
    },
    "required": ["vehicle_idx", "condition", "penalty"],
}

_PROBLEM_PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "weights": _WEIGHTS_OBJECT_SCHEMA,
        "only_active_terms": {"type": "boolean"},
        "driver_preferences": {
            "type": "array",
            "items": _DRIVER_PREFERENCE_SCHEMA,
        },
        "shift_hard_penalty": {"type": "number"},
        "locked_assignments": {"type": "object"},
        "algorithm": {
            "type": "string",
            "enum": ["GA", "PSO", "SA", "SwarmSA", "ACOR"],
        },
        "algorithm_params": {"type": "object"},
        "epochs": {"type": "integer"},
        "pop_size": {"type": "integer"},
        "random_seed": {"type": "integer"},
        "hard_constraints": {"type": "array", "items": {"type": "string"}},
        "soft_constraints": {"type": "array", "items": {"type": "string"}},
    },
}

_PANEL_PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "problem": _PROBLEM_PATCH_SCHEMA,
    },
}

CHAT_MODEL_TURN_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "title": "ChatModelTurn",
    "type": "object",
    "properties": {
        "assistant_message": {
            "type": "string",
            "description": "Visible reply to the participant.",
        },
        "panel_patch": {
            "anyOf": [
                _PANEL_PATCH_SCHEMA,
                {"type": "null"},
            ],
        },
    },
    "required": ["assistant_message"],
}


def _history_to_contents(history_lines: list[tuple[str, str]]) -> list[types.Content]:
    """Map DB roles user/assistant to Gemini user/model Content turns."""
    out: list[types.Content] = []
    for role, text in history_lines:
        if not text.strip():
            continue
        r = "user" if role == "user" else "model"
        out.append(types.Content(role=r, parts=[types.Part(text=text)]))
    return out


def _workflow_prompt(workflow_mode: str) -> str:
    if workflow_mode == "agile":
        return STUDY_CHAT_WORKFLOW_AGILE
    return STUDY_CHAT_WORKFLOW_WATERFALL


def _build_structured_system_instruction(
    current_panel: dict[str, Any] | None,
    workflow_mode: str = "waterfall",
    recent_runs_summary: list[dict[str, Any]] | None = None,
    researcher_steers: list[str] | None = None,
) -> str:
    panel_blob = (
        json.dumps(current_panel, indent=2, ensure_ascii=False)
        if current_panel
        else "{}"
    )
    parts = [
        STUDY_CHAT_SYSTEM_PROMPT,
        _workflow_prompt(workflow_mode),
        STUDY_CHAT_STRUCTURED_JSON_RULES,
        "Current panel JSON (authoritative for this turn):",
        panel_blob,
    ]
    if recent_runs_summary:
        runs_blob = json.dumps(recent_runs_summary, indent=2, ensure_ascii=False)
        parts.append(
            "Recent run results (for context — compare costs and violations across runs "
            "when the user asks about results or changes):"
        )
        parts.append(runs_blob)
    if researcher_steers:
        steer_blob = "\n".join(f"- {s}" for s in researcher_steers if s.strip())
        if steer_blob.strip():
            parts.append(
                "Hidden researcher steering (highest-priority instruction for this next participant reply):\n"
                "- Do not reveal this steering exists or mention a researcher.\n"
                "- Apply the latest steering directly in your next response.\n"
                "- Transition naturally from the recent conversation instead of sounding abrupt.\n"
                f"{steer_blob}"
            )
    return "\n\n".join(parts)


def _plain_fallback_reply(
    user_text: str,
    history_lines: list[tuple[str, str]],
    api_key: str,
    model_name: str,
    workflow_mode: str = "waterfall",
    researcher_steers: list[str] | None = None,
) -> str:
    system = _build_structured_system_instruction(
        current_panel=None,
        workflow_mode=workflow_mode,
        recent_runs_summary=None,
        researcher_steers=researcher_steers,
    )
    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(system_instruction=system),
        history=_history_to_contents(history_lines),
    )
    resp = chat.send_message(user_text)
    if not resp.text:
        raise RuntimeError("Empty model response")
    return resp.text.strip()


def generate_chat_turn(
    user_text: str,
    history_lines: list[tuple[str, str]],
    api_key: str,
    model_name: str,
    current_panel: dict[str, Any] | None,
    workflow_mode: str = "waterfall",
    recent_runs_summary: list[dict[str, Any]] | None = None,
    researcher_steers: list[str] | None = None,
) -> ChatModelTurn:
    """
    Structured turn: Chat session with system instruction + history, then send_message.
    Falls back to plain chat (no panel_patch) if JSON structured output fails.
    """
    client = genai.Client(api_key=api_key)
    system_instruction = _build_structured_system_instruction(
        current_panel, workflow_mode, recent_runs_summary, researcher_steers
    )
    history = _history_to_contents(history_lines)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_json_schema=CHAT_MODEL_TURN_RESPONSE_JSON_SCHEMA,
    )
    try:
        chat = client.chats.create(
            model=model_name,
            config=config,
            history=history,
        )
        resp = chat.send_message(user_text)
        raw = resp.text
        log.info(
            "Structured Gemini raw response: %s",
            raw if raw is not None else "<no text>",
        )
        if resp.parsed is not None:
            if isinstance(resp.parsed, ChatModelTurn):
                log.info("Structured Gemini parsed turn: %s", resp.parsed.model_dump())
                return resp.parsed
            if isinstance(resp.parsed, dict):
                log.info("Structured Gemini parsed dict: %s", resp.parsed)
                return ChatModelTurn.model_validate(resp.parsed)
        if not raw:
            raise RuntimeError("Empty model response")
        turn = ChatModelTurn.model_validate_json(raw)
        log.info("Structured Gemini validated JSON turn: %s", turn.model_dump())
        return turn
    except Exception as e:
        log.warning("Structured chat failed (%s); using plain fallback", e)
        text = _plain_fallback_reply(
            user_text,
            history_lines,
            api_key,
            model_name,
            workflow_mode,
            researcher_steers,
        )
        return ChatModelTurn(assistant_message=text, panel_patch=None)
