"""Unit tests for problem brief normalization and merge helpers."""

from app.problem_brief import (
    _brief_items_from_panel,
    locked_goal_terms_prompt_section,
    merge_problem_brief_patch,
    normalize_problem_brief,
    sync_problem_brief_from_panel,
)


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


def test_gathered_oq_row_not_atomized_on_commas_and_and():
    """Promoted Q&A lines must stay one row; compound splitting would break on commas / and in the answer."""
    raw = _minimal_brief_payload(
        items=[
            {
                "id": "gathered-oq-x",
                "text": (
                    "Preferred zones? — We use A, B, and C with weight 5 for travel time and balance."
                ),
                "kind": "gathered",
                "source": "user",
                "status": "confirmed",
                "editable": True,
            }
        ],
    )
    out = normalize_problem_brief(raw)
    oq_rows = [i for i in out["items"] if str(i.get("id", "")).startswith("gathered-oq-")]
    assert len(oq_rows) == 1
    assert oq_rows[0]["text"].startswith("Preferred zones?")


def test_merge_replace_open_questions_true_without_open_questions_key_preserves():
    base = normalize_problem_brief(
        _minimal_brief_payload(
            open_questions=[{"id": "q-keep", "text": "Still open?", "status": "open", "answer_text": None}],
        )
    )
    merged = merge_problem_brief_patch(
        base,
        {"replace_editable_items": True, "replace_open_questions": True, "items": []},
    )
    assert [q["id"] for q in merged["open_questions"]] == ["q-keep"]


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
    assert any("8h cap" in t for t in gathered_texts)


def test_brief_items_from_panel_omit_default_ga_algorithm_params():
    panel = {"problem": {"algorithm": "GA", "algorithm_params": {"pc": 0.9, "pm": 0.05}}}
    items = _brief_items_from_panel(panel)
    texts = [i["text"] for i in items]
    assert not any("search strategy:" in t.lower() for t in texts)
    assert not any("parameter pc" in t.lower() for t in texts)
    assert not any("parameter pm" in t.lower() for t in texts)


def test_brief_items_from_panel_include_non_default_ga_param_only():
    panel = {"problem": {"algorithm": "GA", "algorithm_params": {"pc": 0.8, "pm": 0.05}}}
    items = _brief_items_from_panel(panel)
    texts = [i["text"] for i in items]
    assert len(texts) == 1
    assert "Search strategy: GA" in texts[0]
    assert "pc=0.8" in texts[0]
    assert "pm=0.05" not in texts[0]


def test_brief_items_from_panel_skip_keys_not_allowed_for_algorithm():
    panel = {"problem": {"algorithm": "GA", "algorithm_params": {"pc": 0.85, "w": 0.4}}}
    items = _brief_items_from_panel(panel)
    texts = [i["text"] for i in items]
    assert len(texts) == 1
    assert "pc=0.85" in texts[0]
    assert "w=0.4" not in texts[0]


def test_normalize_goal_summary_strips_numeric_weight_details():
    raw = _minimal_brief_payload(
        goal_summary="Optimize travel time (weight 1) and keep deadline penalty 50 while using GA for 120 epochs."
    )
    out = normalize_problem_brief(raw)
    assert out["goal_summary"] == ""


def test_normalize_atomizes_compound_gathered_item():
    raw = _minimal_brief_payload(
        items=[
            {
                "id": "fact-1",
                "text": "Active objectives: Total travel time (weight 1) and workload balance (weight 5).",
                "kind": "gathered",
                "source": "user",
                "status": "confirmed",
                "editable": True,
            }
        ]
    )
    out = normalize_problem_brief(raw)
    gathered = [item for item in out["items"] if item["kind"] == "gathered" and item["id"].startswith("fact-1")]
    assert len(gathered) >= 2


def test_locked_goal_terms_prompt_section_lists_keys():
    text = locked_goal_terms_prompt_section(
        {"problem": {"locked_goal_terms": ["deadline_penalty", "shift_hard_penalty"]}}
    )
    assert text is not None
    assert "deadline_penalty" in text
    assert "shift_hard_penalty" in text
    assert "Locked goal terms" in text


def test_locked_goal_terms_prompt_section_empty_when_none():
    assert locked_goal_terms_prompt_section({}) is None
    assert locked_goal_terms_prompt_section({"problem": {}}) is None


def test_sync_problem_brief_from_panel_reinjects_weights_after_cleanup_style_merge():
    """After cleanup, LLM rows may omit numbers; panel overlay restores canonical weight lines."""
    merged = normalize_problem_brief(
        _minimal_brief_payload(
            items=[
                {
                    "id": "g-soft",
                    "text": "We care about travel time and deadlines.",
                    "kind": "gathered",
                    "source": "agent",
                    "status": "confirmed",
                    "editable": True,
                },
            ],
        )
    )
    panel = {
        "problem": {
            "weights": {"travel_time": 7.5, "deadline_penalty": 12.0},
            "algorithm": "GA",
        }
    }
    out = sync_problem_brief_from_panel(merged, panel)
    texts = [i.get("text", "") for i in out["items"] if i.get("kind") == "gathered"]
    joined = " ".join(texts)
    assert "7.5" in joined
    assert "12" in joined
    assert "Travel time" in joined or "travel" in joined.lower()


def test_normalize_atomizes_constraint_handling_gathered_item():
    raw = _minimal_brief_payload(
        items=[
            {
                "id": "ch-1",
                "text": (
                    "Constraint handling: Capacity violations (weight 100), "
                    "deadline/priority misses (weight 50), and 8h shift limits (hard penalty 1000)."
                ),
                "kind": "gathered",
                "source": "user",
                "status": "confirmed",
                "editable": True,
            }
        ]
    )
    out = normalize_problem_brief(raw)
    gathered = [
        item
        for item in out["items"]
        if item["kind"] == "gathered" and str(item.get("id", "")).startswith("ch-1")
    ]
    assert len(gathered) >= 3
    texts = [g["text"] for g in gathered]
    assert any(t.startswith("Constraint handling:") and "Capacity" in t for t in texts)
    assert any("deadline" in t.lower() and "miss" in t.lower() for t in texts)
    assert any("8h" in t and "shift" in t.lower() for t in texts)
