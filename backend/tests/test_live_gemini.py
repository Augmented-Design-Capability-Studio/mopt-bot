"""Smoke tests that hit the real Gemini API.

ALL tests in this file:
  * are marked ``live_gemini`` and skip automatically when no key is configured;
  * use ``settings.default_gemini_model`` (the flash variant) to keep latency
    and quota usage low;
  * are intentionally minimal — every additional test costs API quota and
    slows local iteration.

If a test in this file fails:
  1. First check that ``backend/.secrets/gemini_api_key`` (or the
     ``GEMINI_API_KEY`` env var) holds a valid, non-revoked key.
  2. The first test failure auto-blocks subsequent live tests in this
     session (see ``backend/tests/conftest.py``) so failures don't pile up.

Coding agents (Claude Code, Cursor, Antigravity, VSCode Copilot, …): a
failure here can be a missing/invalid/expired API key — not necessarily a
product bug. See ``backend/.secrets/README.md``.
"""

from __future__ import annotations

import pytest
from google import genai
from google.genai import errors as genai_errors

from app.config import get_settings


pytestmark = pytest.mark.live_gemini


def _short_repr(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _is_auth_failure(exc: genai_errors.ClientError) -> bool:
    """Recognize the various ways Gemini reports a bad/revoked/missing key."""
    if getattr(exc, "code", None) in (401, 403):
        return True
    text = str(exc).lower()
    return (
        "api_key_invalid" in text
        or "api key not valid" in text
        or "permission_denied" in text
        or "unauthenticated" in text
    )


@pytest.mark.live_gemini
def test_default_flash_model_responds(gemini_api_key: str) -> None:
    """Raw SDK smoke: confirm the configured key + default model can be reached."""
    model = get_settings().default_gemini_model
    client = genai.Client(api_key=gemini_api_key)
    try:
        resp = client.models.generate_content(
            model=model,
            contents="Reply with exactly the word 'pong' and nothing else.",
        )
    except genai_errors.ClientError as exc:
        if _is_auth_failure(exc):
            pytest.fail(
                "Gemini rejected the supplied key — check that it isn't expired, "
                f"revoked, or restricted to a different project. Underlying error: {_short_repr(exc)}",
                pytrace=False,
            )
        raise
    text = (resp.text or "").strip()
    assert text, f"Empty response from Gemini ({model}). Full response: {resp!r}"


@pytest.mark.live_gemini
def test_generate_chat_turn_smoke(gemini_api_key: str) -> None:
    """Production code path smoke: ``generate_chat_turn`` end-to-end."""
    from app.services.llm import generate_chat_turn

    model = get_settings().default_gemini_model
    try:
        turn = generate_chat_turn(
            user_text="Hello.",
            history_lines=[],
            api_key=gemini_api_key,
            model_name=model,
            current_problem_brief=None,
            workflow_mode="agile",
            current_panel=None,
            test_problem_id="vrptw",
        )
    except genai_errors.ClientError as exc:
        if _is_auth_failure(exc):
            pytest.fail(
                "Gemini rejected the supplied key while exercising generate_chat_turn — "
                f"the key is reachable but unauthorized. {_short_repr(exc)}",
                pytrace=False,
            )
        raise
    assert turn.assistant_message and turn.assistant_message.strip(), (
        "generate_chat_turn returned an empty assistant_message; "
        f"full turn: {turn!r}"
    )
