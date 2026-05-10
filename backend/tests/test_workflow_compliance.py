"""Tests for the deterministic workflow-compliance post-derivation check.

The natural-language judgement ("did the visible reply ask a question / claim a
brief change?") is now produced by the brief-update LLM's
``visible_reply_intent`` field, so these tests pass the booleans directly
instead of feeding free-form reply text through a regex.
"""

from __future__ import annotations

from app.services.workflow_compliance import assess_workflow_compliance


def _brief(items=None, open_questions=None, goal_terms=None, **rest):
    return {
        "items": items or [],
        "open_questions": open_questions or [],
        "goal_terms": goal_terms or {},
        "goal_summary": rest.get("goal_summary", ""),
        "run_summary": rest.get("run_summary", ""),
    }


def test_waterfall_question_without_oq_flags_violation():
    base = _brief()
    new = _brief()  # unchanged — no OQ added
    issues = assess_workflow_compliance(
        workflow_mode="waterfall",
        base_brief=base,
        new_brief=new,
        visible_reply_asks_user_question=True,
    )
    assert any("waterfall" in i and "no open questions" in i for i in issues)


def test_waterfall_question_with_existing_open_oq_is_compliant():
    base = _brief(
        open_questions=[{"id": "q1", "text": "How strict is capacity?", "status": "open"}]
    )
    new = base
    issues = assess_workflow_compliance(
        workflow_mode="waterfall",
        base_brief=base,
        new_brief=new,
        visible_reply_asks_user_question=True,
    )
    assert not any("no open questions" in i for i in issues)


def test_waterfall_question_with_new_oq_added_is_compliant():
    base = _brief()
    new = _brief(
        open_questions=[{"id": "q-new", "text": "How strict is capacity?", "status": "open"}]
    )
    issues = assess_workflow_compliance(
        workflow_mode="waterfall",
        base_brief=base,
        new_brief=new,
        visible_reply_asks_user_question=True,
    )
    assert not any("no open questions" in i for i in issues)


def test_waterfall_run_ack_with_zero_oqs_flags_violation():
    base = _brief()
    new = _brief()
    issues = assess_workflow_compliance(
        workflow_mode="waterfall",
        base_brief=base,
        new_brief=new,
        visible_reply_asks_user_question=False,
        is_run_acknowledgement=True,
    )
    assert any("run-ack" in i for i in issues)


def test_agile_change_claim_without_brief_movement_flags_violation():
    base = _brief()
    new = _brief()  # unchanged
    issues = assess_workflow_compliance(
        workflow_mode="agile",
        base_brief=base,
        new_brief=new,
        visible_reply_claims_brief_change=True,
    )
    assert any("agile" in i and "unchanged" in i for i in issues)


def test_agile_change_claim_with_brief_movement_is_compliant():
    base = _brief()
    new = _brief(
        items=[{"id": "g1", "text": "Late penalty 12", "kind": "gathered", "source": "agent"}]
    )
    issues = assess_workflow_compliance(
        workflow_mode="agile",
        base_brief=base,
        new_brief=new,
        visible_reply_claims_brief_change=True,
    )
    assert not issues


def test_agile_no_claim_no_violation_even_when_brief_unchanged():
    """When the LLM honestly reports the visible reply didn't claim a change,
    an unchanged brief is fine — this is the whole point of folding the
    classification into structured output instead of regex-matching the
    reply text."""
    base = _brief()
    new = _brief()
    issues = assess_workflow_compliance(
        workflow_mode="agile",
        base_brief=base,
        new_brief=new,
        visible_reply_claims_brief_change=False,
    )
    assert not issues


def test_demo_question_does_not_require_oq():
    """Demo behaves like a hybrid; the question→OQ rule is waterfall-specific."""
    base = _brief()
    new = _brief()
    issues = assess_workflow_compliance(
        workflow_mode="demo",
        base_brief=base,
        new_brief=new,
        visible_reply_asks_user_question=True,
    )
    assert not any("no open questions" in i for i in issues)
