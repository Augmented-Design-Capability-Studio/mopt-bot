"""Tests for the OQ-answer classifier routing in PATCH /problem-brief.

The classifier itself (a Gemini call) is stubbed; we exercise the dispatch logic
that turns its output into brief items / replacement OQs / ignored fallbacks.
"""

from __future__ import annotations

from typing import Any

import pytest

import importlib

from app.schemas import (
    OpenQuestionClassification,
    OpenQuestionClassifierInput,
)

router_module = importlib.import_module("app.routers.sessions.router")


def _brief(*, items: list[dict[str, Any]] | None = None,
           open_questions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "goal_summary": "",
        "run_summary": "",
        "items": list(items or []),
        "open_questions": list(open_questions or []),
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }


def _stub_classifier(monkeypatch: pytest.MonkeyPatch, classifications: list[OpenQuestionClassification]):
    captured: dict[str, list[OpenQuestionClassifierInput]] = {"inputs": []}

    def fake_classify(*, inputs, **_kwargs):  # noqa: ANN001
        captured["inputs"] = list(inputs)
        return classifications

    monkeypatch.setattr("app.services.llm.classify_answered_open_questions", fake_classify)
    return captured


def test_concrete_answer_routes_to_gathered(monkeypatch: pytest.MonkeyPatch) -> None:
    incoming = _brief(open_questions=[
        {"id": "oq-1", "text": "How strict is the capacity limit?",
         "status": "answered", "answer_text": "30 max per route"},
    ])
    persisted = [{"id": "oq-1", "text": "How strict is the capacity limit?",
                  "status": "open", "answer_text": None}]

    _stub_classifier(monkeypatch, [
        OpenQuestionClassification(
            question_id="oq-1",
            bucket="gathered",
            rephrased_text="Capacity is capped at 30 per route.",
        ),
    ])

    result = router_module._route_oq_answers_through_classifier(
        incoming_brief=incoming,
        persisted_open_questions=persisted,
        workflow_mode="waterfall",
        api_key="test-key",
        model_name="gemini-test",
        test_problem_id=None,
    )

    assert result["open_questions"] == []
    gathered = [i for i in result["items"] if i["kind"] == "gathered"]
    assert len(gathered) == 1
    assert gathered[0]["text"] == "Capacity is capped at 30 per route."
    assert gathered[0]["source"] == "user"


def test_waterfall_hedge_replaces_with_simpler_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    incoming = _brief(open_questions=[
        {"id": "oq-1", "text": "How strict is the capacity limit?",
         "status": "answered", "answer_text": "you decide"},
    ])
    persisted = [{"id": "oq-1", "text": "How strict is the capacity limit?",
                  "status": "open", "answer_text": None}]

    _stub_classifier(monkeypatch, [
        OpenQuestionClassification(
            question_id="oq-1",
            bucket="new_open_question",
            new_question_text=(
                "Roughly how strict is the capacity limit — hard cap, "
                "soft with small overflow ok, or doesn't matter much?"
            ),
        ),
    ])

    result = router_module._route_oq_answers_through_classifier(
        incoming_brief=incoming,
        persisted_open_questions=persisted,
        workflow_mode="waterfall",
        api_key="test-key",
        model_name="gemini-test",
        test_problem_id=None,
    )

    assert [i for i in result["items"] if i["kind"] == "gathered"] == []
    assert len(result["open_questions"]) == 1
    new_q = result["open_questions"][0]
    assert new_q["status"] == "open"
    assert new_q["answer_text"] is None
    assert "Roughly how strict is the capacity limit" in new_q["text"]
    assert "choices" not in new_q


def test_agile_hedge_routes_to_assumption(monkeypatch: pytest.MonkeyPatch) -> None:
    incoming = _brief(open_questions=[
        {"id": "oq-1", "text": "How strict is the capacity limit?",
         "status": "answered", "answer_text": "i don't know"},
    ])
    persisted = [{"id": "oq-1", "text": "How strict is the capacity limit?",
                  "status": "open", "answer_text": None}]

    _stub_classifier(monkeypatch, [
        OpenQuestionClassification(
            question_id="oq-1",
            bucket="assumption",
            assumption_text=(
                "Assume capacity is a soft constraint with moderate penalty."
            ),
        ),
    ])

    result = router_module._route_oq_answers_through_classifier(
        incoming_brief=incoming,
        persisted_open_questions=persisted,
        workflow_mode="agile",
        api_key="test-key",
        model_name="gemini-test",
        test_problem_id=None,
    )

    assert result["open_questions"] == []
    assumptions = [i for i in result["items"] if i["kind"] == "assumption"]
    assert len(assumptions) == 1
    assert assumptions[0]["source"] == "agent"
    assert "soft constraint" in assumptions[0]["text"]


def test_mode_mismatch_falls_through_to_legacy_promotion(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the classifier emits assumption for waterfall (or new_oq for agile), the
    routing helper leaves the OQ answered so the legacy promote step can handle it."""
    incoming = _brief(open_questions=[
        {"id": "oq-1", "text": "How strict is the capacity limit?",
         "status": "answered", "answer_text": "you decide"},
    ])
    persisted = [{"id": "oq-1", "text": "How strict is the capacity limit?",
                  "status": "open", "answer_text": None}]

    # Classifier mistakenly emits assumption in waterfall — should be ignored.
    _stub_classifier(monkeypatch, [
        OpenQuestionClassification(
            question_id="oq-1",
            bucket="assumption",
            assumption_text="some assumption",
        ),
    ])

    result = router_module._route_oq_answers_through_classifier(
        incoming_brief=incoming,
        persisted_open_questions=persisted,
        workflow_mode="waterfall",
        api_key="test-key",
        model_name="gemini-test",
        test_problem_id=None,
    )

    # OQ stays answered — legacy promotion in normalize_problem_brief handles it.
    assert len(result["open_questions"]) == 1
    assert result["open_questions"][0]["status"] == "answered"
    assert [i for i in result["items"] if i["kind"] == "assumption"] == []


def test_no_newly_answered_means_no_classifier_call(monkeypatch: pytest.MonkeyPatch) -> None:
    incoming = _brief(open_questions=[
        {"id": "oq-1", "text": "Still open?",
         "status": "open", "answer_text": None},
    ])
    persisted = [{"id": "oq-1", "text": "Still open?",
                  "status": "open", "answer_text": None}]

    called = {"hit": False}

    def boom(*_a, **_k):  # noqa: ANN001
        called["hit"] = True
        return []

    monkeypatch.setattr("app.services.llm.classify_answered_open_questions", boom)

    result = router_module._route_oq_answers_through_classifier(
        incoming_brief=incoming,
        persisted_open_questions=persisted,
        workflow_mode="waterfall",
        api_key="test-key",
        model_name="gemini-test",
        test_problem_id=None,
    )

    assert called["hit"] is False
    # Brief unchanged.
    assert result["open_questions"] == incoming["open_questions"]


def test_already_answered_in_persisted_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the OQ was already answered in the persisted brief (re-edit of same value),
    we don't re-classify — only fresh open→answered transitions."""
    incoming = _brief(open_questions=[
        {"id": "oq-1", "text": "Q",
         "status": "answered", "answer_text": "yes"},
    ])
    persisted = [{"id": "oq-1", "text": "Q",
                  "status": "answered", "answer_text": "yes"}]

    called = {"hit": False}

    def boom(*_a, **_k):  # noqa: ANN001
        called["hit"] = True
        return []

    monkeypatch.setattr("app.services.llm.classify_answered_open_questions", boom)

    result = router_module._route_oq_answers_through_classifier(
        incoming_brief=incoming,
        persisted_open_questions=persisted,
        workflow_mode="waterfall",
        api_key="test-key",
        model_name="gemini-test",
        test_problem_id=None,
    )

    assert called["hit"] is False
    assert result == incoming


def test_no_api_key_skips_classifier(monkeypatch: pytest.MonkeyPatch) -> None:
    incoming = _brief(open_questions=[
        {"id": "oq-1", "text": "Q",
         "status": "answered", "answer_text": "yes"},
    ])
    persisted = [{"id": "oq-1", "text": "Q",
                  "status": "open", "answer_text": None}]

    called = {"hit": False}

    def boom(*_a, **_k):  # noqa: ANN001
        called["hit"] = True
        return []

    monkeypatch.setattr("app.services.llm.classify_answered_open_questions", boom)

    result = router_module._route_oq_answers_through_classifier(
        incoming_brief=incoming,
        persisted_open_questions=persisted,
        workflow_mode="waterfall",
        api_key=None,
        model_name="gemini-test",
        test_problem_id=None,
    )

    assert called["hit"] is False
    assert result == incoming


def test_empty_classifier_response_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the classifier returns an empty list (e.g. parse failure), brief is unchanged
    so legacy promotion handles the answered OQ."""
    incoming = _brief(open_questions=[
        {"id": "oq-1", "text": "Q",
         "status": "answered", "answer_text": "yes"},
    ])
    persisted = [{"id": "oq-1", "text": "Q",
                  "status": "open", "answer_text": None}]

    _stub_classifier(monkeypatch, [])

    result = router_module._route_oq_answers_through_classifier(
        incoming_brief=incoming,
        persisted_open_questions=persisted,
        workflow_mode="waterfall",
        api_key="test-key",
        model_name="gemini-test",
        test_problem_id=None,
    )

    assert result == incoming
