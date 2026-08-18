from app.problems.registry import get_study_port


def test_vrptw_config_schema_has_expected_weight_keys_and_driver_preferences():
    schema = get_study_port("vrptw").panel_patch_response_json_schema()
    problem_props = schema["properties"]["problem"]["properties"]
    weights = problem_props["weights"]

    assert weights.get("additionalProperties") is False
    assert set(weights["properties"]) == {
        "travel_time",
        "shift_limit",
        "lateness_penalty",
        "capacity_penalty",
        "workload_balance",
        "worker_preference",
        "express_miss_penalty",
        "waiting_time",
    }

    driver_pref = problem_props["driver_preferences"]["items"]
    assert driver_pref["required"] == ["vehicle_idx", "condition", "penalty"]
    assert driver_pref["properties"]["condition"]["type"] == "string"
    assert "Alice=0" in driver_pref["properties"]["vehicle_idx"]["description"]
    assert "A=1" in driver_pref["properties"]["zone"]["description"]
    assert "D=4" in driver_pref["properties"]["zone"]["description"]


def _fq(goal_terms):
    port = get_study_port("vrptw")
    return port.formulation_quality_for_config({"problem": {"goal_terms": goal_terms}})


def test_formulation_quality_excludes_unbriefed_terms_from_coverage():
    """Only the 7 briefed terms count toward coverage / the 0-11 formulation_score.
    An un-briefed term a user surfaces (e.g. idle-wait `waiting_time`) must NOT move
    the score — otherwise it would silently inflate coverage and break cross-session
    comparability — but it DOES show up in `captured_terms` for the timing charts."""
    canonical = {
        "travel_time": {"weight": 1, "type": "objective"},
        "lateness_penalty": {"weight": 10, "type": "hard"},
        "capacity_penalty": {"weight": 5, "type": "hard"},
        "worker_preference": {"weight": 2},
    }
    base = _fq(canonical)
    withw = _fq({**canonical, "waiting_time": {"weight": 100}})

    # Adding the un-briefed term leaves canonical coverage and the score untouched.
    assert withw["coverage"] == base["coverage"]
    assert withw["formulation_score"] == base["formulation_score"]
    # captured_terms is the identification superset and DOES list the extra term
    # (drives the per-term timing chart), even though it's excluded from the score.
    assert "waiting_time" in withw["captured_terms"]
    assert "waiting_time" not in base["captured_terms"]
