"""Tests for the dedicated OQ maintenance LLM pass.

The pass owns the open_questions list end-to-end: a single Gemini call decides
which OQs to keep, drop, rephrase, or add given (workflow_mode, user_message,
visible_reply, current_OQs, recent_gathered). These tests mock the Gemini call
to verify:

1. The schema and prompt-build paths are wired (no live network).
2. The output is normalized correctly (id echo for kept, omitted for new).
3. Failure modes return None (caller keeps existing list — no destructive default).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services import llm as llm_module
from app.services.llm import (
    OQ_MAINTAIN_RESPONSE_JSON_SCHEMA,
    maintain_open_questions,
)


def test_maintain_oq_schema_shape_minimal_required_fields():
    """The schema requires open_questions; each item requires text. id is optional."""
    schema = OQ_MAINTAIN_RESPONSE_JSON_SCHEMA
    assert schema["required"] == ["open_questions"]
    item_schema = schema["properties"]["open_questions"]["items"]
    assert item_schema["required"] == ["text"]
    assert "id" in item_schema["properties"]
    assert "text" in item_schema["properties"]


def test_maintain_oq_returns_none_without_api_key():
    """No API key → no call attempted, return None so caller keeps current list."""
    result = maintain_open_questions(
        workflow_mode="waterfall",
        user_message="let's try first",
        visible_reply="ok, which algorithm?",
        current_open_questions=[{"id": "q1", "text": "What capacity rule?"}],
        recent_gathered=[],
        api_key="",
        model_name="gemini-x",
    )
    assert result is None


def _stub_genai(monkeypatch: pytest.MonkeyPatch, parsed_payload: dict[str, Any] | None, raw_text: str = ""):
    """Install a fake genai client whose generate_content returns parsed_payload."""
    class _Resp:
        def __init__(self):
            self.parsed = parsed_payload
            self.text = raw_text

    class _Models:
        def generate_content(self, **_kwargs):
            return _Resp()

    class _Client:
        def __init__(self, *_a, **_k):
            self.models = _Models()

    monkeypatch.setattr(llm_module.genai, "Client", _Client)


def test_maintain_oq_drops_dismissed_and_adds_new(monkeypatch: pytest.MonkeyPatch):
    """User dismissed the old OQ ('let's try first') and the visible reply
    asked a new question. The model echoes the new list — caller normalises it."""
    _stub_genai(
        monkeypatch,
        parsed_payload={
            "open_questions": [
                {"text": "Which algorithm should we use? Options include GA, PSO, SA."}
            ],
        },
    )
    result = maintain_open_questions(
        workflow_mode="waterfall",
        user_message="let's try my current problem definition first. ALright?",
        visible_reply="Would you prefer a genetic-based approach or a swarm-based search?",
        current_open_questions=[
            {"id": "q-existing", "text": "Are there any specific time windows or capacity limits?"}
        ],
        recent_gathered=[],
        api_key="fake-key",
        model_name="gemini-x",
    )
    assert result == [
        {"text": "Which algorithm should we use? Options include GA, PSO, SA."}
    ]
    # No `id` echoed for the new OQ — caller / merge layer assigns one.
    assert "id" not in result[0]


def test_maintain_oq_preserves_id_on_keep(monkeypatch: pytest.MonkeyPatch):
    _stub_genai(
        monkeypatch,
        parsed_payload={
            "open_questions": [
                {"id": "q-keep", "text": "How strict is capacity?"}
            ],
        },
    )
    result = maintain_open_questions(
        workflow_mode="waterfall",
        user_message="hmm",
        visible_reply="anything else?",
        current_open_questions=[{"id": "q-keep", "text": "How strict is capacity?"}],
        recent_gathered=[],
        api_key="fake-key",
        model_name="gemini-x",
    )
    assert result == [{"text": "How strict is capacity?", "id": "q-keep"}]


def test_maintain_oq_filters_blank_text(monkeypatch: pytest.MonkeyPatch):
    """Items with empty/whitespace text are dropped silently."""
    _stub_genai(
        monkeypatch,
        parsed_payload={
            "open_questions": [
                {"text": "  "},
                {"text": "Real question?"},
                {"text": ""},
            ],
        },
    )
    result = maintain_open_questions(
        workflow_mode="waterfall",
        user_message="x",
        visible_reply="y",
        current_open_questions=[],
        recent_gathered=[],
        api_key="fake-key",
        model_name="gemini-x",
    )
    assert result == [{"text": "Real question?"}]


def test_maintain_oq_returns_none_on_exception(monkeypatch: pytest.MonkeyPatch):
    """Any genai.Client exception → None (caller keeps current list)."""
    class _Boom:
        def __init__(self, *_a, **_k):
            raise RuntimeError("simulated transient")

    monkeypatch.setattr(llm_module.genai, "Client", _Boom)
    result = maintain_open_questions(
        workflow_mode="waterfall",
        user_message="x",
        visible_reply="y",
        current_open_questions=[{"id": "q1", "text": "Stay open?"}],
        recent_gathered=[],
        api_key="fake-key",
        model_name="gemini-x",
    )
    assert result is None


def test_maintain_oq_returns_none_when_neither_parsed_nor_raw(monkeypatch: pytest.MonkeyPatch):
    """When the model returns nothing usable, return None (no destructive replace)."""
    _stub_genai(monkeypatch, parsed_payload=None, raw_text="")
    result = maintain_open_questions(
        workflow_mode="waterfall",
        user_message="x",
        visible_reply="y",
        current_open_questions=[{"id": "q1", "text": "Still open?"}],
        recent_gathered=[],
        api_key="fake-key",
        model_name="gemini-x",
    )
    assert result is None


def test_maintain_oq_supports_empty_list_response(monkeypatch: pytest.MonkeyPatch):
    """Model returning an empty list is valid — means "drop all OQs"."""
    _stub_genai(monkeypatch, parsed_payload={"open_questions": []})
    result = maintain_open_questions(
        workflow_mode="waterfall",
        user_message="skip everything",
        visible_reply="ok, nothing else for now",
        current_open_questions=[{"id": "q1", "text": "Capacity strict?"}],
        recent_gathered=[],
        api_key="fake-key",
        model_name="gemini-x",
    )
    assert result == []


# ---------------------------------------------------------------------------
# Unified background pipeline + OQ maintenance.
#
# OQ maintenance now runs INSIDE _run_background_derivation (sequenced after
# the patch merge + workflow coercion). The chat handler launches the
# pipeline on every real turn and passes ``skip_brief_update_llm=True`` when
# the consolidated chat-turn classifier returns ``change_intent=False`` —
# so dismissals like "skip this for now" still fire the maintenance step.
#
# These tests exercise that unified path directly to confirm the dismissal
# regression is fixed.
# ---------------------------------------------------------------------------


def _stub_pipeline_dependencies(monkeypatch: pytest.MonkeyPatch, *, maintain_return):
    """Common stubs for unified-pipeline tests."""
    monkeypatch.setattr(
        "app.services.llm.maintain_open_questions",
        lambda **_kwargs: maintain_return,
    )
    # The brief-update LLM and config-derive LLM should not be called in
    # the skip_brief_update_llm=True path; stub defensively.
    from app.schemas import ProblemBriefUpdateTurn

    monkeypatch.setattr(
        "app.services.llm.generate_problem_brief_update",
        lambda **_kwargs: ProblemBriefUpdateTurn(),
    )
    monkeypatch.setattr(
        "app.services.llm.generate_config_from_brief",
        lambda **_kwargs: None,
    )


def _make_session(session_id: str, brief_json: str, *, workflow_mode: str = "waterfall"):
    from app.database import SessionLocal
    from app.models import StudySession

    with SessionLocal() as db:
        s = StudySession(
            id=session_id,
            workflow_mode=workflow_mode,
            status="active",
            problem_brief_json=brief_json,
        )
        db.add(s)
        db.commit()


def _delete_session(session_id: str):
    from app.database import SessionLocal
    from app.models import StudySession

    with SessionLocal() as db:
        row = db.get(StudySession, session_id)
        if row is not None:
            db.delete(row)
            db.commit()


def _read_session_brief(session_id: str) -> dict:
    import json as _json
    from app.database import SessionLocal
    from app.models import StudySession

    with SessionLocal() as db:
        row = db.get(StudySession, session_id)
        assert row is not None
        return _json.loads(row.problem_brief_json or "{}")


def test_unified_pipeline_drops_dismissed_oq_when_skip_brief_update_llm(
    monkeypatch: pytest.MonkeyPatch,
):
    """End-to-end mirror of the user's bug: the user says "skip this for now",
    change_intent=False so the chat handler launches with
    ``skip_brief_update_llm=True``. OQ maintenance must still drop the OQ.
    """
    from app.routers.sessions import derivation

    _stub_pipeline_dependencies(monkeypatch, maintain_return=[])
    sid = "sess-pipeline-drop-oq"
    _make_session(
        sid,
        '{"items": [], "open_questions": ['
        '{"id": "q-old", "text": "Specific constraints?", "status": "open"}'
        ']}',
    )
    try:
        derivation._run_background_derivation(
            session_id=sid,
            revision=0,
            user_text="Can you skip this for now? I'd like to do a first run",
            workflow_mode="waterfall",
            api_key="fake-key",
            model_name="gemini-x",
            history_lines=[],
            researcher_steers=[],
            recent_runs_summary=[],
            base_problem_brief={"items": [], "open_questions": [
                {"id": "q-old", "text": "Specific constraints?", "status": "open"}
            ]},
            base_panel=None,
            cleanup_requested=False,
            clear_requested=False,
            visible_assistant_message="Understood, we can proceed with a run using your current priorities.",
            skip_brief_update_llm=True,
        )
        stored = _read_session_brief(sid)
        assert stored.get("open_questions") == []
    finally:
        _delete_session(sid)


def test_unified_pipeline_skips_maintenance_on_run_ack(monkeypatch: pytest.MonkeyPatch):
    """Run-ack turns have their own waterfall OQ rules (handled by the brief-
    update LLM with the run-ack addendum). The unified pipeline should NOT
    invoke the OQ maintenance LLM on those turns.
    """
    from app.routers.sessions import derivation

    called: dict[str, int] = {"maintain": 0}

    def _spy(**_kwargs):
        called["maintain"] += 1
        return []

    monkeypatch.setattr("app.services.llm.maintain_open_questions", _spy)
    from app.schemas import ProblemBriefUpdateTurn

    monkeypatch.setattr(
        "app.services.llm.generate_problem_brief_update",
        lambda **_kwargs: ProblemBriefUpdateTurn(),
    )
    monkeypatch.setattr(
        "app.services.llm.generate_config_from_brief",
        lambda **_kwargs: None,
    )

    sid = "sess-pipeline-runack"
    _make_session(sid, '{"items": [], "open_questions": []}')
    try:
        derivation._run_background_derivation(
            session_id=sid,
            revision=0,
            user_text="Run #1 just completed - cost 100. Please interpret.",
            workflow_mode="waterfall",
            api_key="fake-key",
            model_name="gemini-x",
            history_lines=[],
            researcher_steers=[],
            recent_runs_summary=[],
            base_problem_brief={"items": [], "open_questions": []},
            base_panel=None,
            cleanup_requested=False,
            clear_requested=False,
            is_run_acknowledgement=True,
            visible_assistant_message="Run #1 finished — many time-window misses.",
            skip_brief_update_llm=False,
        )
        assert called["maintain"] == 0
    finally:
        _delete_session(sid)
