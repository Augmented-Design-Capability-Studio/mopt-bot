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


@pytest.mark.live_gemini
def test_brief_update_emits_structured_driver_preference_for_alice_zone_d(
    gemini_api_key: str,
) -> None:
    """End-to-end: when the user names a worker-specific preference rule,
    the brief-update LLM must emit it under the structured contract path —
    `goal_terms.worker_preference.properties.driver_preferences` — instead
    of writing prose. This is the regression check for the original bug
    where the parent worker_preference weight appeared but the children did not.
    """
    from app.services.llm import generate_problem_brief_update

    model = get_settings().default_gemini_model
    # Brief is warm — by the time a user names a worker-specific preference,
    # they've typically answered scope questions first. Cold-start sessions
    # skip the VRPTW appendix (which carries the contract), so this test
    # supplies a minimal warm brief.
    warm_brief = {
        "goal_summary": "Schedule fleet routes within shift limits.",
        "run_summary": "",
        "items": [
            {
                "id": "item-gathered-1",
                "text": "Fleet size: 5 drivers.",
                "kind": "gathered",
                "source": "user",
            },
            {
                "id": "item-gathered-2",
                "text": "Total orders: 30.",
                "kind": "gathered",
                "source": "user",
            },
        ],
        "open_questions": [],
        "goal_terms": {},
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }
    try:
        turn = generate_problem_brief_update(
            user_text="Alice doesn't like Zone D in this scenario.",
            history_lines=[
                ("user", "I have a fleet of 5 drivers and 30 orders to schedule."),
                ("assistant", "Got it — let's figure out priorities and constraints."),
            ],
            api_key=gemini_api_key,
            model_name=model,
            current_problem_brief=warm_brief,
            workflow_mode="agile",
            current_panel=None,
            test_problem_id="vrptw",
            visible_assistant_message=(
                "Adding a soft preference for Alice to avoid Zone D deliveries."
            ),
        )
    except genai_errors.ClientError as exc:
        if _is_auth_failure(exc):
            pytest.fail(
                "Gemini rejected the supplied key — check the key. "
                f"{_short_repr(exc)}",
                pytrace=False,
            )
        raise

    assert turn is not None, "Brief-update structured call returned None (LLM/parse failure)."
    patch = turn.problem_brief_patch
    assert isinstance(patch, dict), f"Expected a non-null patch; got: {turn!r}"
    goal_terms = patch.get("goal_terms")
    assert isinstance(goal_terms, dict) and "worker_preference" in goal_terms, (
        "Brief-update LLM must emit goal_terms.worker_preference for "
        "Alice/Zone D rules. Full patch: "
        f"{patch!r}"
    )
    wp = goal_terms["worker_preference"]
    rules = wp.get("properties", {}).get("driver_preferences", [])
    assert rules, (
        "Expected non-empty driver_preferences under worker_preference.properties. "
        f"goal_terms entry: {wp!r}"
    )
    rule = rules[0]
    assert rule.get("vehicle_idx") == 0, f"Expected Alice (vehicle_idx=0); got: {rule!r}"
    assert rule.get("condition") == "avoid_zone", f"Expected avoid_zone; got: {rule!r}"
    assert rule.get("zone") == 4, f"Expected Zone D = 4; got: {rule!r}"
