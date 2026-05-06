from app.problems.registry import get_study_port
from app.routers.sessions.sync import _grounded_goal_term_keys


def test_knapsack_config_schema_weights():
    schema = get_study_port("knapsack").panel_patch_response_json_schema()
    problem_props = schema["properties"]["problem"]["properties"]
    weights = problem_props["weights"]

    assert weights.get("additionalProperties") is False
    assert set(weights["properties"]) == {"value_emphasis", "capacity_overflow", "selection_sparsity"}
    assert "driver_preferences" not in problem_props
    assert problem_props["constraint_types"]["additionalProperties"]["enum"] == ["soft", "hard", "custom"]
    assert "goal_terms" in problem_props
    assert "hard_constraints" not in problem_props
    assert "soft_constraints" not in problem_props


def test_canonical_value_goal_phrasing_does_not_ground_sparsity():
    """Regression: the bare phrase 'selected items' appears in the canonical
    value-goal restatement ('Maximize total value of selected items') and was
    falsely grounding selection_sparsity on every starter brief, which let the
    panel-derive LLM speculatively include a sparsity weight even when the
    participant only asked for value + capacity. Markers must be specific to
    sparsity intent (qualifiers like 'fewer', 'number of', 'smaller')."""
    markers = get_study_port("knapsack").weight_slot_markers()

    canonical_starter_brief = {
        "items": [
            {"id": "g1", "kind": "gathered", "text": "Maximize total value of selected items.", "source": "user"},
            {"id": "g2", "kind": "gathered", "text": "Bag capacity limit set to 50.", "source": "user"},
            {
                "id": "g3",
                "kind": "gathered",
                "text": "Source data file(s) uploaded: knapsack_22.csv.",
                "source": "upload",
            },
        ],
        "open_questions": [
            {"id": "q1", "text": "Which search method would you like to use?", "status": "open"}
        ],
        "goal_summary": "Maximize total value of items packed into a bag without exceeding a weight capacity of 50.",
    }
    grounded = _grounded_goal_term_keys(canonical_starter_brief, weight_slot_markers=markers)
    assert "value_emphasis" in grounded, "value goal should ground value_emphasis"
    assert "capacity_overflow" in grounded, "capacity should ground capacity_overflow"
    assert "selection_sparsity" not in grounded, (
        "selection_sparsity must NOT be grounded by canonical 'selected items' / "
        "'items packed into a bag' phrasing — that's the value/capacity goal restatement, "
        "not a sparsity ask."
    )


def test_explicit_sparsity_ask_still_grounds_sparsity():
    """The other side of the regression: when the participant *does* ask for
    fewer items / smaller selection / sparsity, the markers must still ground
    selection_sparsity. Otherwise the tightening above would have neutralized
    the goal term entirely."""
    markers = get_study_port("knapsack").weight_slot_markers()
    cases = [
        "User wants fewer items in the bag.",
        "Penalize the number of selected items.",
        "Prefer a more compact selection.",
        "Selection size should be small.",
        "We need a sparsity penalty.",
        "Aim for a smaller bag.",
    ]
    for text in cases:
        brief = {
            "items": [{"id": "g1", "kind": "gathered", "text": text, "source": "user"}],
            "open_questions": [],
            "goal_summary": "",
        }
        grounded = _grounded_goal_term_keys(brief, weight_slot_markers=markers)
        assert "selection_sparsity" in grounded, f"sparsity ask was not grounded: {text!r}"
