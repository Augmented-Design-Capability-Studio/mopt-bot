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
