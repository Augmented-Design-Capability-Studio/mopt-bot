from app.problems.registry import get_study_port


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
