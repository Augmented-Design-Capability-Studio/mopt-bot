"""Unit tests for problem brief normalization and merge helpers."""

from app.problem_brief import merge_problem_brief_patch, normalize_problem_brief


def _minimal_brief_payload(**kwargs):
    base = {
        "goal_summary": "g",
        "items": [],
        "open_questions": [],
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }
    base.update(kwargs)
    return base


def test_normalize_promotes_answered_open_question_to_gathered():
    raw = _minimal_brief_payload(
        open_questions=[
            {"id": "q1", "text": "How many?", "status": "answered", "answer_text": "Ten."},
            {"id": "q2", "text": "Why?", "status": "open", "answer_text": None},
        ],
    )
    out = normalize_problem_brief(raw)
    texts = [q["text"] for q in out["open_questions"]]
    assert texts == ["Why?"]
    gathered_non_system = [
        i for i in out["items"] if str(i.get("kind")) == "gathered" and not str(i.get("id", "")).startswith("system")
    ]
    assert any(i.get("text") == "How many? — Ten." for i in gathered_non_system)
    assert any(i.get("id") == "gathered-oq-q1" for i in gathered_non_system)


def test_merge_moves_answered_suffix_open_question_to_gathered():
    base = normalize_problem_brief(
        _minimal_brief_payload(
            open_questions=[
                {"id": "keep", "text": "Still open?", "status": "open", "answer_text": None},
            ],
        )
    )
    merged = merge_problem_brief_patch(
        base,
        {
            "open_questions": [
                "Shift limits? (Answered: 8h cap, balanced workload).",
            ],
        },
    )
    q_texts = [q["text"] for q in merged["open_questions"]]
    assert "Still open?" in q_texts
    assert not any("(answered" in q["text"].lower() for q in merged["open_questions"])
    gathered_texts = [i["text"] for i in merged["items"] if i.get("kind") == "gathered"]
    assert any("Shift limits?" in t and "8h cap" in t for t in gathered_texts)
