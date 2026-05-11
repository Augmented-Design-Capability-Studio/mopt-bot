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


def test_maintain_definition_state_renders_gate_status_block(
    monkeypatch: pytest.MonkeyPatch,
):
    """The maintenance prompt must surface ``gate_status`` so the LLM can
    apply the gate-driven MUST-ADD rule on missing prerequisites.

    Mock genai.Client so we can capture the system instruction the call
    received without hitting the network.
    """
    captured: dict[str, Any] = {}

    class _Resp:
        parsed = {"open_questions": [], "assumption_actions": []}
        text = '{"open_questions": [], "assumption_actions": []}'

    class _Models:
        def generate_content(self, **kwargs):
            captured["system_instruction"] = kwargs.get("config").system_instruction
            return _Resp()

    class _Client:
        def __init__(self, *_a, **_k):
            self.models = _Models()

    monkeypatch.setattr(llm_module.genai, "Client", _Client)

    from app.services.llm import maintain_definition_state

    maintain_definition_state(
        workflow_mode="waterfall",
        user_message="let's go",
        visible_reply="Which search method should we use?",
        current_open_questions=[],
        current_assumptions=None,
        recent_gathered=[],
        api_key="fake-key",
        model_name="gemini-x",
        gate_status={
            "workflow_mode": "waterfall",
            "goal_term_present": True,
            "search_strategy_present": False,
            "open_questions_pending": 0,
            "gate_engaged": True,
            "ready_to_run": False,
            "missing": ["search_strategy"],
        },
    )
    si = captured.get("system_instruction") or ""
    assert "## Run-gate status (machine-readable" in si
    assert '"search_strategy_present": false' in si


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


def _stub_pipeline_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    maintain_return,
    assumption_actions=None,
):
    """Common stubs for unified-pipeline tests.

    ``maintain_return`` is the OQ list (or None for failure). When the
    derivation code path went to ``maintain_definition_state``, we wrap
    ``maintain_return`` into the richer return shape and also stub the
    legacy ``maintain_open_questions`` for any older code path that still
    calls it directly.
    """
    if maintain_return is None:
        legacy_return = None
        unified_return = None
    else:
        legacy_return = maintain_return
        unified_return = {
            "open_questions": maintain_return,
            "assumption_actions": list(assumption_actions or []),
        }

    monkeypatch.setattr(
        "app.services.llm.maintain_open_questions",
        lambda **_kwargs: legacy_return,
    )
    monkeypatch.setattr(
        "app.services.llm.maintain_definition_state",
        lambda **_kwargs: unified_return,
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
        return None

    monkeypatch.setattr("app.services.llm.maintain_open_questions", _spy)
    monkeypatch.setattr("app.services.llm.maintain_definition_state", _spy)
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


# ---------------------------------------------------------------------------
# Assumption-lifecycle pass (Part A — folded into definition maintenance).
#
# Agile/demo only: each existing `kind: "assumption"` row is paired with one
# of {keep, rephrase, drop, promote_to_gathered}. promote_to_gathered always
# lands as `source: "user"` because the user originated the lock-in
# (memory: feedback_provenance_origin_not_phrasing).
# ---------------------------------------------------------------------------


def _assumption_brief(item_id: str = "a-late", text: str = "Lateness penalty around 10 (soft)."):
    import json as _json

    return _json.dumps(
        {
            "items": [
                {
                    "id": item_id,
                    "text": text,
                    "kind": "assumption",
                    "source": "agent",
                }
            ],
            "open_questions": [],
        }
    )


def test_maintain_definition_promotes_modified_assumption_to_gathered(
    monkeypatch: pytest.MonkeyPatch,
):
    """User says 'lock that in at 12' → assumption row becomes a gathered row
    with source='user' and the new text. Agile mode."""
    from app.routers.sessions import derivation

    _stub_pipeline_dependencies(
        monkeypatch,
        maintain_return=[],  # no OQs in play
        assumption_actions=[
            {
                "id": "a-late",
                "action": "promote_to_gathered",
                "rephrased_text": "Lateness penalty is set to 12 (soft).",
            }
        ],
    )
    sid = "sess-promote-assumption"
    _make_session(
        sid,
        _assumption_brief(),
        workflow_mode="agile",
    )
    try:
        derivation._run_background_derivation(
            session_id=sid,
            revision=0,
            user_text="Lock that in at 12",
            workflow_mode="agile",
            api_key="fake-key",
            model_name="gemini-x",
            history_lines=[],
            researcher_steers=[],
            recent_runs_summary=[],
            base_problem_brief={
                "items": [
                    {
                        "id": "a-late",
                        "text": "Lateness penalty around 10 (soft).",
                        "kind": "assumption",
                        "source": "agent",
                    }
                ],
                "open_questions": [],
            },
            base_panel=None,
            cleanup_requested=False,
            clear_requested=False,
            visible_assistant_message="Locked it in at 12.",
            skip_brief_update_llm=True,
        )
        stored = _read_session_brief(sid)
        items = stored.get("items") or []
        # The row stays at id a-late but has been promoted.
        a_late = next((it for it in items if it.get("id") == "a-late"), None)
        assert a_late is not None
        assert a_late["kind"] == "gathered"
        assert a_late["source"] == "user"
        assert a_late["text"] == "Lateness penalty is set to 12 (soft)."
    finally:
        _delete_session(sid)


def test_maintain_definition_drops_dismissed_assumption(
    monkeypatch: pytest.MonkeyPatch,
):
    """User says 'scrap that lateness penalty' → assumption row is removed."""
    from app.routers.sessions import derivation

    _stub_pipeline_dependencies(
        monkeypatch,
        maintain_return=[],
        assumption_actions=[{"id": "a-late", "action": "drop"}],
    )
    sid = "sess-drop-assumption"
    _make_session(sid, _assumption_brief(), workflow_mode="agile")
    try:
        derivation._run_background_derivation(
            session_id=sid,
            revision=0,
            user_text="actually scrap that lateness penalty",
            workflow_mode="agile",
            api_key="fake-key",
            model_name="gemini-x",
            history_lines=[],
            researcher_steers=[],
            recent_runs_summary=[],
            base_problem_brief={
                "items": [
                    {
                        "id": "a-late",
                        "text": "Lateness penalty around 10 (soft).",
                        "kind": "assumption",
                        "source": "agent",
                    }
                ],
                "open_questions": [],
            },
            base_panel=None,
            cleanup_requested=False,
            clear_requested=False,
            visible_assistant_message="Removed the lateness penalty.",
            skip_brief_update_llm=True,
        )
        stored = _read_session_brief(sid)
        items = stored.get("items") or []
        assert all(it.get("id") != "a-late" for it in items)
    finally:
        _delete_session(sid)


def test_maintain_definition_rephrases_assumption_preserves_kind(
    monkeypatch: pytest.MonkeyPatch,
):
    """Small edit without a lock-in → text changes, kind/source stay
    assumption/agent."""
    from app.routers.sessions import derivation

    _stub_pipeline_dependencies(
        monkeypatch,
        maintain_return=[],
        assumption_actions=[
            {
                "id": "a-late",
                "action": "rephrase",
                "rephrased_text": "Lateness penalty around 8 (soft).",
            }
        ],
    )
    sid = "sess-rephrase-assumption"
    _make_session(sid, _assumption_brief(), workflow_mode="agile")
    try:
        derivation._run_background_derivation(
            session_id=sid,
            revision=0,
            user_text="bring it down to 8 ish",
            workflow_mode="agile",
            api_key="fake-key",
            model_name="gemini-x",
            history_lines=[],
            researcher_steers=[],
            recent_runs_summary=[],
            base_problem_brief={
                "items": [
                    {
                        "id": "a-late",
                        "text": "Lateness penalty around 10 (soft).",
                        "kind": "assumption",
                        "source": "agent",
                    }
                ],
                "open_questions": [],
            },
            base_panel=None,
            cleanup_requested=False,
            clear_requested=False,
            visible_assistant_message="Trimmed the assumption to ~8.",
            skip_brief_update_llm=True,
        )
        stored = _read_session_brief(sid)
        items = stored.get("items") or []
        a_late = next((it for it in items if it.get("id") == "a-late"), None)
        assert a_late is not None
        assert a_late["kind"] == "assumption"
        assert a_late["source"] == "agent"
        assert a_late["text"] == "Lateness penalty around 8 (soft)."
    finally:
        _delete_session(sid)


def test_maintain_definition_waterfall_ignores_assumption_actions(
    monkeypatch: pytest.MonkeyPatch,
):
    """Even if the LLM emits assumption_actions on a waterfall turn, the
    server-side wiring only acts on agile/demo. Waterfall briefs have no
    assumption rows for the actions to target anyway, but this protects
    against a malformed LLM emission."""
    from app.routers.sessions import derivation

    # Waterfall brief has only OQs and a gathered row — no assumption rows.
    _stub_pipeline_dependencies(
        monkeypatch,
        maintain_return=[{"id": "q1", "text": "Time windows hard or soft?"}],
        assumption_actions=[
            # Stale id — even if the LLM tried to drop something, no row exists.
            {"id": "a-late", "action": "drop"}
        ],
    )
    sid = "sess-waterfall-ignores-actions"
    import json as _json

    brief_json = _json.dumps(
        {
            "items": [
                {
                    "id": "g1",
                    "text": "User wants to minimize travel time.",
                    "kind": "gathered",
                    "source": "user",
                }
            ],
            "open_questions": [
                {"id": "q1", "text": "Time windows hard or soft?", "status": "open"}
            ],
        }
    )
    _make_session(sid, brief_json, workflow_mode="waterfall")
    try:
        derivation._run_background_derivation(
            session_id=sid,
            revision=0,
            user_text="anything else?",
            workflow_mode="waterfall",
            api_key="fake-key",
            model_name="gemini-x",
            history_lines=[],
            researcher_steers=[],
            recent_runs_summary=[],
            base_problem_brief={
                "items": [
                    {
                        "id": "g1",
                        "text": "User wants to minimize travel time.",
                        "kind": "gathered",
                        "source": "user",
                    }
                ],
                "open_questions": [
                    {"id": "q1", "text": "Time windows hard or soft?", "status": "open"}
                ],
            },
            base_panel=None,
            cleanup_requested=False,
            clear_requested=False,
            visible_assistant_message="What level of strictness for time windows?",
            skip_brief_update_llm=True,
        )
        stored = _read_session_brief(sid)
        items = stored.get("items") or []
        # The gathered row is untouched.
        assert any(it.get("id") == "g1" and it.get("kind") == "gathered" for it in items)
    finally:
        _delete_session(sid)
