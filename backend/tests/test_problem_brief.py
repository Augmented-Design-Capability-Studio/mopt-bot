"""Unit tests for problem brief normalization and merge helpers."""

from app.problem_brief import _brief_items_from_panel, merge_problem_brief_patch, normalize_problem_brief


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


def test_brief_items_from_panel_omit_default_ga_algorithm_params():
    panel = {"problem": {"algorithm": "GA", "algorithm_params": {"pc": 0.9, "pm": 0.05}}}
    items = _brief_items_from_panel(panel)
    texts = [i["text"] for i in items]
    assert any("Solver algorithm is GA" in t for t in texts)
    assert not any("parameter pc" in t.lower() for t in texts)
    assert not any("parameter pm" in t.lower() for t in texts)


def test_brief_items_from_panel_include_non_default_ga_param_only():
    panel = {"problem": {"algorithm": "GA", "algorithm_params": {"pc": 0.8, "pm": 0.05}}}
    items = _brief_items_from_panel(panel)
    texts = [i["text"] for i in items]
    assert any("pc" in t and "0.8" in t for t in texts)
    assert not any("parameter pm" in t.lower() or "pm is set" in t.lower() for t in texts)


def test_brief_items_from_panel_skip_keys_not_allowed_for_algorithm():
    panel = {"problem": {"algorithm": "GA", "algorithm_params": {"pc": 0.85, "w": 0.4}}}
    items = _brief_items_from_panel(panel)
    texts = [i["text"] for i in items]
    assert any("pc" in t for t in texts)
    assert not any("parameter w" in t.lower() for t in texts)
