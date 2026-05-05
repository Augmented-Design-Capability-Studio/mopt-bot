"""Tests for the chat-temperature pipeline in `llm._build_visible_chat_system_instruction`.

Two distinct things are tested here:

1. **Refinement path** — when the heuristic returns "warm", the LLM classifier is
   invoked to refine the call (or fall back to the heuristic if it raises).
2. **Fast-path skip** — when the heuristic returns "cold" or "hot", the classifier
   is *not* invoked. This is a deliberate optimization in `llm.py:532` so that
   cold-start and post-run turns don't pay the extra LLM round-trip. The tests
   here lock that fast-path in so future changes can't accidentally re-introduce
   the classifier call on cold/hot fallbacks.
"""
from __future__ import annotations

import pytest

from app.problem_brief import default_problem_brief
from app.services import llm


def _warm_fallback_brief() -> dict:
    """Brief shaped to put `resolve_context_profile` in the 'warm' bucket
    (at least one structural signal: a gathered item)."""
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


def test_visible_instruction_uses_model_temperature_when_available(monkeypatch: pytest.MonkeyPatch):
    """When the heuristic puts the session in 'warm', the classifier is invoked
    and its verdict surfaces in the guardrails block."""
    monkeypatch.setattr(llm, "classify_chat_temperature", lambda **_: "warm")
    system = llm._build_visible_chat_system_instruction(
        user_text="how do you optimize?",
        current_problem_brief=_warm_fallback_brief(),
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        api_key="fake-key",
        model_name="fake-model",
    )
    assert "Conversation temperature: WARM" in system
    assert "Goal terms you can adjust:" in system


def test_visible_instruction_falls_back_when_model_temperature_fails(monkeypatch: pytest.MonkeyPatch):
    """If the classifier raises mid-warm, the heuristic temperature is used.
    The brief is shaped to land at 'warm' so the classifier *is* actually invoked
    (otherwise this test would pass vacuously without exercising the recovery)."""
    def _boom(**_kwargs):
        raise RuntimeError("classifier failed")

    monkeypatch.setattr(llm, "classify_chat_temperature", _boom)
    system = llm._build_visible_chat_system_instruction(
        user_text="how do you optimize?",
        current_problem_brief=_warm_fallback_brief(),
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        api_key="fake-key",
        model_name="fake-model",
    )
    # Heuristic fallback is "warm" because the brief has a gathered item.
    assert "Conversation temperature: WARM" in system


def test_visible_instruction_skips_classifier_on_cold_fallback(monkeypatch: pytest.MonkeyPatch):
    """Cold-start optimization: empty brief → heuristic 'cold' → classifier is NOT
    invoked. This locks in the fast-path so a generic cold-start turn doesn't pay
    an extra LLM round-trip."""
    call_count = {"n": 0}

    def _track(**_kwargs):
        call_count["n"] += 1
        return "warm"  # would change the result if it were called

    monkeypatch.setattr(llm, "classify_chat_temperature", _track)
    system = llm._build_visible_chat_system_instruction(
        user_text="hi there",
        current_problem_brief=default_problem_brief("vrptw"),  # empty → cold
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        api_key="fake-key",
        model_name="fake-model",
    )
    assert call_count["n"] == 0, "Classifier must not be invoked on cold fallback."
    assert "Conversation temperature: COLD" in system
    assert "Goal terms you can adjust:" not in system


def test_visible_instruction_skips_classifier_on_hot_fallback(monkeypatch: pytest.MonkeyPatch):
    """Hot fallback (runs already exist) is unambiguous; classifier is NOT invoked.
    Locks in the post-run fast-path."""
    call_count = {"n": 0}

    def _track(**_kwargs):
        call_count["n"] += 1
        return "warm"  # would demote if it were called

    monkeypatch.setattr(llm, "classify_chat_temperature", _track)
    system = llm._build_visible_chat_system_instruction(
        user_text="how was the run?",
        current_problem_brief=default_problem_brief("vrptw"),
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        api_key="fake-key",
        model_name="fake-model",
        recent_runs_summary=[{"ok": True, "cost": 100.0}],
    )
    assert call_count["n"] == 0, "Classifier must not be invoked on hot fallback."
    assert "Conversation temperature: HOT" in system


def test_visible_instruction_skips_classifier_when_no_api_key(monkeypatch: pytest.MonkeyPatch):
    """No api_key/model_name → heuristic is used, classifier is never called.
    Mirrors the offline / no-credentials path."""
    call_count = {"n": 0}

    def _track(**_kwargs):
        call_count["n"] += 1
        return "warm"

    monkeypatch.setattr(llm, "classify_chat_temperature", _track)
    system = llm._build_visible_chat_system_instruction(
        user_text="how do you optimize?",
        current_problem_brief=_warm_fallback_brief(),
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        api_key=None,
        model_name=None,
    )
    assert call_count["n"] == 0, "Classifier must not be invoked without credentials."
    assert "Conversation temperature: WARM" in system  # heuristic stands alone
