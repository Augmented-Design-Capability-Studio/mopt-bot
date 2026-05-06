"""Tests for run-button-awareness injection into the chat system prompt.

The chat-turn handler in `router.py` computes whether the **Run optimization**
button is currently available and threads that state through
`generate_chat_turn → generate_visible_chat_reply → _build_visible_chat_system_instruction`.
The system prompt then contains either:

    Run optimization button: ENABLED

or:

    Run optimization button: DISABLED — reason: <hint>

The agent uses this to keep its replies honest about what the participant can do
right now (no false promises to start a run, no offers to click a button that's
greyed out). These tests lock in the injection contract — they don't probe
agent behavior, just the prompt-construction surface.
"""
from __future__ import annotations

import pytest

from app.problem_brief import default_problem_brief
from app.services import llm


def _warm_brief() -> dict:
    """Brief shaped to put resolve_context_profile in the 'warm' bucket so the
    rest of the prompt assembly runs through normally."""
    brief = default_problem_brief("vrptw")
    brief["items"] = [
        {
            "id": "g-1",
            "text": "Fleet has 5 vehicles serving downtown deliveries.",
            "kind": "gathered",
            "source": "user",
            "status": "active",
            "editable": True,
        }
    ]
    return brief


def test_run_button_enabled_state_is_announced(monkeypatch: pytest.MonkeyPatch):
    """When run_button_enabled=True, the system prompt carries the ENABLED line
    as a standalone paragraph (distinct from the awareness-section description
    which mentions both states inside backticked examples)."""
    monkeypatch.setattr(llm, "classify_chat_temperature", lambda **_: "warm")
    system = llm._build_visible_chat_system_instruction(
        user_text="how do you optimize?",
        current_problem_brief=_warm_brief(),
        workflow_mode="agile",
        test_problem_id="vrptw",
        api_key="fake-key",
        model_name="fake-model",
        run_button_enabled=True,
    )
    # Standalone line — paragraph boundaries are \n\n in the joined output.
    assert "\n\nRun optimization button: ENABLED\n\n" in system or system.endswith(
        "\n\nRun optimization button: ENABLED"
    ) or "\n\nRun optimization button: ENABLED" in system
    # No DISABLED standalone line — the awareness-section description mentions
    # the DISABLED string only inside `**"..."**` quoting.
    assert "\n\nRun optimization button: DISABLED" not in system


def test_run_button_disabled_state_includes_reason(monkeypatch: pytest.MonkeyPatch):
    """When run_button_enabled=False, the DISABLED line includes the reason verbatim,
    as a standalone per-turn paragraph (distinct from the awareness-section examples)."""
    monkeypatch.setattr(llm, "classify_chat_temperature", lambda **_: "warm")
    reason = "I can start a run after you add a simulated upload using the **Upload file(s)...** button in the chat footer (exact label)."
    system = llm._build_visible_chat_system_instruction(
        user_text="run it",
        current_problem_brief=_warm_brief(),
        workflow_mode="agile",
        test_problem_id="vrptw",
        api_key="fake-key",
        model_name="fake-model",
        run_button_enabled=False,
        run_disabled_reason=reason,
    )
    assert "\n\nRun optimization button: DISABLED — reason: " in system
    assert reason in system
    # No ENABLED standalone line.
    assert "\n\nRun optimization button: ENABLED" not in system


def test_run_button_disabled_uses_default_reason_when_missing(monkeypatch: pytest.MonkeyPatch):
    """If the caller forgets to pass a reason but the button is disabled, the
    builder falls back to a generic 'prerequisites not met' message rather than
    leaving the reason text empty."""
    monkeypatch.setattr(llm, "classify_chat_temperature", lambda **_: "warm")
    system = llm._build_visible_chat_system_instruction(
        user_text="run it",
        current_problem_brief=_warm_brief(),
        workflow_mode="agile",
        test_problem_id="vrptw",
        api_key="fake-key",
        model_name="fake-model",
        run_button_enabled=False,
        run_disabled_reason=None,
    )
    assert "\n\nRun optimization button: DISABLED — reason: " in system
    # Generic default fallback wording.
    assert "prerequisites" in system.lower()


def test_run_button_state_omitted_when_unknown(monkeypatch: pytest.MonkeyPatch):
    """When run_button_enabled is None (probe failed / not computed), the
    builder omits the per-turn line entirely. The awareness section in the
    base prompt still mentions the strings inside its description (so the
    agent knows what to look for), but no standalone state line is injected.
    Pairs with the prompt rule: 'Never speculate about the button state when
    the system line is missing.'"""
    monkeypatch.setattr(llm, "classify_chat_temperature", lambda **_: "warm")
    system = llm._build_visible_chat_system_instruction(
        user_text="hi",
        current_problem_brief=_warm_brief(),
        workflow_mode="agile",
        test_problem_id="vrptw",
        api_key="fake-key",
        model_name="fake-model",
        run_button_enabled=None,
    )
    # No standalone per-turn line for either state.
    assert "\n\nRun optimization button: ENABLED" not in system
    assert "\n\nRun optimization button: DISABLED" not in system


def test_run_button_awareness_section_present_in_base_prompt():
    """The base system prompt must always carry the awareness rule, regardless
    of whether the per-turn state line is present, so the agent knows how to
    interpret the line when it does appear."""
    from app.prompts.study_chat import STUDY_CHAT_SYSTEM_PROMPT

    assert "Run-button awareness" in STUDY_CHAT_SYSTEM_PROMPT
    assert "DISABLED" in STUDY_CHAT_SYSTEM_PROMPT
    assert "ENABLED" in STUDY_CHAT_SYSTEM_PROMPT
