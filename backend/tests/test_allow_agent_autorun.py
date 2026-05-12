"""Tests for the ``allow_agent_autorun`` session field and the persisted
``is_run_invitation`` flag on chat messages.

Context: the agile auto-first-run is now OFF by default. The researcher
can re-enable autonomous runs per-session via the ``allow_agent_autorun``
flag. Independently, the agent's run-invitation reply is mirrored to the
chat bubble as an inline Run button — that hinges on persisting the
``is_run_invitation`` intent in the message's ``meta_json``.
"""

from __future__ import annotations

import json

import pytest

from app.routers.sessions import derivation


def test_session_out_defaults_to_no_autorun(test_session_id):
    """A freshly created session has ``allow_agent_autorun=False`` so the
    participant is in control of when runs fire."""
    from app.database import SessionLocal
    from app.models import StudySession
    from app.routers.sessions import helpers

    with SessionLocal() as db:
        row = db.get(StudySession, test_session_id)
        assert row is not None
        out = helpers.session_to_out(row)
    assert out.allow_agent_autorun is False


def test_session_patch_toggles_allow_agent_autorun(test_session_id):
    from app.database import SessionLocal
    from app.models import StudySession

    with SessionLocal() as db:
        row = db.get(StudySession, test_session_id)
        assert row is not None
        row.allow_agent_autorun = True
        db.commit()
        db.refresh(row)
        assert row.allow_agent_autorun is True


def test_append_message_persists_meta_json_when_run_invitation(test_session_id):
    """When the assistant message invites a run, ``meta_json`` carries the
    flag so the participant client can render an inline Run button."""
    from app.database import SessionLocal

    with SessionLocal() as db:
        msg = derivation.append_message(
            db,
            test_session_id,
            "assistant",
            "Click Run optimization for a baseline.",
            visible=True,
            meta={"is_run_invitation": True},
        )
    assert msg.meta_json is not None
    parsed = json.loads(msg.meta_json)
    assert parsed == {"is_run_invitation": True}


def test_append_message_leaves_meta_json_null_for_normal_chat(test_session_id):
    from app.database import SessionLocal

    with SessionLocal() as db:
        msg = derivation.append_message(
            db,
            test_session_id,
            "assistant",
            "Just thinking out loud.",
            visible=True,
        )
    assert msg.meta_json is None


def test_message_out_exposes_parsed_meta(test_session_id):
    """``MessageOut`` round-trips ``meta_json`` text into a structured
    ``meta`` dict so the frontend doesn't have to parse strings."""
    from app.database import SessionLocal
    from app.schemas import MessageOut

    with SessionLocal() as db:
        msg = derivation.append_message(
            db,
            test_session_id,
            "assistant",
            "Ready when you are.",
            visible=True,
            meta={"is_run_invitation": True},
        )
        out = MessageOut.model_validate(msg)
    assert out.meta == {"is_run_invitation": True}


def test_message_out_meta_is_none_for_missing_meta_json(test_session_id):
    from app.database import SessionLocal
    from app.schemas import MessageOut

    with SessionLocal() as db:
        msg = derivation.append_message(db, test_session_id, "assistant", "hi", visible=True)
        out = MessageOut.model_validate(msg)
    assert out.meta is None


def test_message_out_meta_is_none_for_malformed_meta_json(test_session_id):
    """Defensive: a bad row never breaks the chat list."""
    from app.database import SessionLocal
    from app.models import ChatMessage
    from app.schemas import MessageOut

    with SessionLocal() as db:
        msg = ChatMessage(
            session_id=test_session_id,
            role="assistant",
            content="hi",
            visible_to_participant=True,
            kind="chat",
            meta_json="not valid json {",
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        out = MessageOut.model_validate(msg)
    assert out.meta is None


@pytest.fixture
def test_session_id():
    """A throwaway session row scoped to the test, removed at teardown."""
    import uuid

    from app.database import SessionLocal
    from app.models import StudySession

    sid = f"sess-autorun-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        db.add(
            StudySession(
                id=sid,
                workflow_mode="agile",
                status="active",
                problem_brief_json='{"items": [], "open_questions": []}',
            )
        )
        db.commit()
    try:
        yield sid
    finally:
        with SessionLocal() as db:
            row = db.get(StudySession, sid)
            if row is not None:
                db.delete(row)
                db.commit()
