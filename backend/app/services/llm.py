"""Server-side Gemini via google-genai: use Chat API (chats.create + send_message), not raw generate_content."""

from __future__ import annotations

import json
import logging
from typing import Any

from google import genai
from google.genai import types

from app.prompts.study_chat import STUDY_CHAT_STRUCTURED_JSON_RULES, STUDY_CHAT_SYSTEM_PROMPT
from app.schemas import ChatModelTurn

log = logging.getLogger(__name__)

# Gemini rejects nested OpenAPI "additional_properties" when passing a Pydantic model as
# response_schema (dict[str, Any] becomes additionalProperties: true). Use response_json_schema
# with a plain object branch (no additionalProperties) instead. Parsing still goes through
# ChatModelTurn.model_validate below.
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
                {"type": "object"},
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


def _build_structured_system_instruction(current_panel: dict[str, Any] | None) -> str:
    panel_blob = (
        json.dumps(current_panel, indent=2, ensure_ascii=False)
        if current_panel
        else "{}"
    )
    return "\n\n".join(
        [
            STUDY_CHAT_SYSTEM_PROMPT,
            STUDY_CHAT_STRUCTURED_JSON_RULES,
            "Current panel JSON (authoritative for this turn):",
            panel_blob,
        ]
    )


def _plain_fallback_reply(
    user_text: str,
    history_lines: list[tuple[str, str]],
    api_key: str,
    model_name: str,
) -> str:
    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(system_instruction=STUDY_CHAT_SYSTEM_PROMPT),
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
) -> ChatModelTurn:
    """
    Structured turn: Chat session with system instruction + history, then send_message.
    Falls back to plain chat (no panel_patch) if JSON structured output fails.
    """
    client = genai.Client(api_key=api_key)
    system_instruction = _build_structured_system_instruction(current_panel)
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
        if resp.parsed is not None:
            if isinstance(resp.parsed, ChatModelTurn):
                return resp.parsed
            if isinstance(resp.parsed, dict):
                return ChatModelTurn.model_validate(resp.parsed)
        raw = resp.text
        if not raw:
            raise RuntimeError("Empty model response")
        return ChatModelTurn.model_validate_json(raw)
    except Exception as e:
        log.warning("Structured chat failed (%s); using plain fallback", e)
        text = _plain_fallback_reply(user_text, history_lines, api_key, model_name)
        return ChatModelTurn(assistant_message=text, panel_patch=None)
