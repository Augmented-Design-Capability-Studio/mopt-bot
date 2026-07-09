"""Researcher-steer freshness in `load_turn_context`.

A steer is a one-shot directive for the very next agent reply. Once the agent
has replied after a steer, it must drop out so the agent doesn't keep
re-applying / re-mentioning it every subsequent turn.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import ChatMessage, StudySession
from app.routers.sessions import context


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(StudySession(id="s1", workflow_mode="agile"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _add(db, role, content, *, visible=True, kind="chat"):
    m = ChatMessage(
        session_id="s1", role=role, content=content, visible_to_participant=visible, kind=kind
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _steers(db, before_id):
    _hist, steers, _runs = context.load_turn_context(db, "s1", before_id)
    return steers


def test_fresh_steer_is_surfaced_on_the_next_turn(db):
    _add(db, "user", "hi")
    _add(db, "assistant", "hello")
    _add(db, "researcher", "Stop mentioning driver preferences.", visible=False)
    next_user = _add(db, "user", "what next?")
    assert _steers(db, next_user.id) == ["Stop mentioning driver preferences."]


def test_applied_steer_drops_out_after_the_agent_replies(db):
    _add(db, "user", "hi")
    _add(db, "assistant", "hello")
    _add(db, "researcher", "Stop mentioning driver preferences.", visible=False)
    _add(db, "user", "what next?")
    # The agent replied to the steer on that turn...
    _add(db, "assistant", "Sure — here's the next step.")
    # ...so on the following turn the steer is considered acknowledged and gone.
    later_user = _add(db, "user", "and after that?")
    assert _steers(db, later_user.id) == []


def test_multiple_steers_since_last_reply_are_all_surfaced_once(db):
    _add(db, "user", "hi")
    _add(db, "assistant", "hello")
    _add(db, "researcher", "Steer A.", visible=False)
    _add(db, "researcher", "Steer B.", visible=False)
    next_user = _add(db, "user", "go")
    assert _steers(db, next_user.id) == ["Steer A.", "Steer B."]
    # After a reply, both drop.
    _add(db, "assistant", "done")
    after = _add(db, "user", "again")
    assert _steers(db, after.id) == []


def test_steer_before_any_reply_is_surfaced(db):
    # No prior assistant message — a steer at the very start still applies.
    _add(db, "researcher", "Keep replies short.", visible=False)
    first_user = _add(db, "user", "hello")
    assert _steers(db, first_user.id) == ["Keep replies short."]


def test_canned_run_ack_does_not_consume_a_steer(db):
    """A steer sent mid-run must still reach the LLM interpretation turn — the
    canned "Run #N finished" ack (kind="run") is an assistant row but not a
    model turn, so it must not count as the steer having been applied."""
    _add(db, "user", "hi")
    _add(db, "assistant", "hello", kind="chat")
    _add(db, "user", "I started Run #1.")
    _add(db, "researcher", "Suggest enabling all-iterations after a plateau.", visible=False)
    _add(db, "assistant", "Run #1 finished. Timeline updated.", kind="run")  # canned ack
    run_ack = _add(db, "user", "Run #1 just completed - cost 100.", visible=False)
    # The interpretation turn (this user msg) still sees the steer.
    assert _steers(db, run_ack.id) == ["Suggest enabling all-iterations after a plateau."]


def test_canned_panel_ack_does_not_consume_a_steer(db):
    """Same guarantee for the canned definition/panel save ack (kind="panel")."""
    _add(db, "user", "hi")
    _add(db, "assistant", "hello", kind="chat")
    _add(db, "researcher", "Stop mentioning driver preferences.", visible=False)
    _add(db, "assistant", "Problem definition saved.", kind="panel")  # canned ack
    def_edit = _add(db, "user", "Definition edited: 1 fact added.")
    assert _steers(db, def_edit.id) == ["Stop mentioning driver preferences."]
    # And after the real chat reply, it drops.
    _add(db, "assistant", "Got it.", kind="chat")
    later = _add(db, "user", "next?")
    assert _steers(db, later.id) == []


def test_resume_reconstruction_preserves_fresh_steer(db):
    """The Retry/resume path rebuilds the turn's steers from the DB via
    `load_fresh_researcher_steers` anchored on the triggering user message.
    The paused turn's own placeholder chat reply (id AFTER the user message)
    must not count as having applied the steer."""
    _add(db, "user", "hi")
    _add(db, "assistant", "hello", kind="chat")
    _add(db, "researcher", "Keep it concise.", visible=False)
    trigger = _add(db, "user", "please tune")  # the turn that later pauses
    # Pipeline started and wrote a placeholder reply, then paused (no final reply).
    _add(db, "assistant", "…thinking…", kind="chat")
    # Resume rebuilds context anchored on the triggering user message.
    assert context.load_fresh_researcher_steers(db, "s1", trigger.id) == ["Keep it concise."]
