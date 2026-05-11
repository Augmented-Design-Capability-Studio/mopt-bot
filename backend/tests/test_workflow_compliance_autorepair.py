"""Tests for the waterfall auto-repair OQ synthesis safety net."""

from app.problem_brief import default_problem_brief, normalize_problem_brief
from app.services.workflow_compliance import synthesize_missing_oq_for_waterfall


def _empty_brief() -> dict:
    return normalize_problem_brief(default_problem_brief())


def _gate(missing: list[str]) -> dict:
    return {
        "workflow_mode": "waterfall",
        "goal_term_present": "goal_term" not in missing,
        "search_strategy_present": "search_strategy" not in missing,
        "open_questions_pending": 0,
        "gate_engaged": True,
        "ready_to_run": False,
        "missing": missing,
    }


def test_waterfall_synthesises_search_strategy_oq_when_missing():
    base = _empty_brief()
    new = _empty_brief()  # no OQ delta
    synth = synthesize_missing_oq_for_waterfall(
        workflow_mode="waterfall",
        base_brief=base,
        new_brief=new,
        visible_reply_asks_user_question=True,
        gate_status=_gate(["search_strategy"]),
    )
    assert synth is not None
    assert "search method" in synth["text"].lower()
    assert synth["status"] == "open"


def test_no_synthesis_when_oq_already_added():
    base = _empty_brief()
    new = _empty_brief()
    new["open_questions"] = [
        {"id": "q-new", "text": "Which algorithm?", "status": "open"}
    ]
    synth = synthesize_missing_oq_for_waterfall(
        workflow_mode="waterfall",
        base_brief=base,
        new_brief=new,
        visible_reply_asks_user_question=True,
        gate_status=_gate(["search_strategy"]),
    )
    assert synth is None


def test_no_synthesis_when_open_oq_already_present_in_base():
    base = _empty_brief()
    base["open_questions"] = [
        {"id": "q-existing", "text": "Existing question", "status": "open"}
    ]
    new = _empty_brief()
    new["open_questions"] = list(base["open_questions"])  # unchanged
    synth = synthesize_missing_oq_for_waterfall(
        workflow_mode="waterfall",
        base_brief=base,
        new_brief=new,
        visible_reply_asks_user_question=True,
        gate_status=_gate(["search_strategy"]),
    )
    # An existing open OQ already represents the unanswered question — no
    # need to synthesise another row.
    assert synth is None


def test_no_synthesis_when_question_was_not_asked():
    synth = synthesize_missing_oq_for_waterfall(
        workflow_mode="waterfall",
        base_brief=_empty_brief(),
        new_brief=_empty_brief(),
        visible_reply_asks_user_question=False,
        gate_status=_gate(["search_strategy"]),
    )
    assert synth is None


def test_no_synthesis_for_agile():
    synth = synthesize_missing_oq_for_waterfall(
        workflow_mode="agile",
        base_brief=_empty_brief(),
        new_brief=_empty_brief(),
        visible_reply_asks_user_question=True,
        gate_status=_gate(["search_strategy"]),
    )
    assert synth is None


def test_no_synthesis_when_gate_status_missing():
    synth = synthesize_missing_oq_for_waterfall(
        workflow_mode="waterfall",
        base_brief=_empty_brief(),
        new_brief=_empty_brief(),
        visible_reply_asks_user_question=True,
        gate_status=None,
    )
    assert synth is None


def test_no_synthesis_for_unknown_missing_key():
    synth = synthesize_missing_oq_for_waterfall(
        workflow_mode="waterfall",
        base_brief=_empty_brief(),
        new_brief=_empty_brief(),
        visible_reply_asks_user_question=True,
        gate_status=_gate(["something_unknown"]),
    )
    # Templates only cover known prerequisites — anything else falls through
    # to the regular compliance warning rather than synthesising a guess.
    assert synth is None
