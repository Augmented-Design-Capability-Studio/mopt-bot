from app.services.llm import (
    CHAT_MODEL_TURN_RESPONSE_JSON_SCHEMA,
    _build_structured_system_instruction,
)


def test_chat_schema_constrains_problem_weights_to_object():
    panel_patch = CHAT_MODEL_TURN_RESPONSE_JSON_SCHEMA["properties"]["panel_patch"]["anyOf"][0]
    problem = panel_patch["properties"]["problem"]
    weights = problem["properties"]["weights"]

    assert weights["type"] == "object"
    assert set(weights["properties"]) == {
        "travel_time",
        "fuel_cost",
        "deadline_penalty",
        "capacity_penalty",
        "workload_balance",
        "worker_preference",
        "priority_penalty",
    }


def test_chat_schema_requires_known_driver_preference_fields():
    panel_patch = CHAT_MODEL_TURN_RESPONSE_JSON_SCHEMA["properties"]["panel_patch"]["anyOf"][0]
    driver_pref = panel_patch["properties"]["problem"]["properties"]["driver_preferences"]["items"]

    assert driver_pref["required"] == ["vehicle_idx", "condition", "penalty"]
    assert driver_pref["properties"]["condition"]["enum"] == [
        "zone_d",
        "express_order",
        "shift_over_hours",
    ]


def test_system_instruction_includes_hidden_researcher_steering_block():
    system = _build_structured_system_instruction(
        current_panel={},
        workflow_mode="waterfall",
        recent_runs_summary=None,
        researcher_steers=["Prioritize concise, run-focused guidance."],
    )

    assert "Hidden researcher steering" in system
    assert "highest-priority instruction for this next participant reply" in system
    assert "Prioritize concise, run-focused guidance." in system
