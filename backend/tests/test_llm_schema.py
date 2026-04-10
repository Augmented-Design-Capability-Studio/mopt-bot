from app.services.llm import (
    CHAT_MODEL_TURN_RESPONSE_JSON_SCHEMA,
    CONFIG_MODEL_PANEL_RESPONSE_JSON_SCHEMA,
    RUN_TRIGGER_INTENT_RESPONSE_JSON_SCHEMA,
    _build_brief_update_system_instruction,
    _build_structured_system_instruction,
)


def test_config_schema_constrains_problem_weights_to_object():
    panel_patch = CONFIG_MODEL_PANEL_RESPONSE_JSON_SCHEMA
    problem = panel_patch["properties"]["problem"]
    weights = problem["properties"]["weights"]

    assert weights["type"] == "object"
    assert weights.get("additionalProperties") is False
    assert set(weights["properties"]) == {
        "travel_time",
        "fuel_cost",
        "deadline_penalty",
        "capacity_penalty",
        "workload_balance",
        "worker_preference",
        "priority_penalty",
    }
    assert problem.get("additionalProperties") is False
    assert panel_patch.get("additionalProperties") is False


def test_config_schema_algorithm_params_has_bounded_properties():
    panel_patch = CONFIG_MODEL_PANEL_RESPONSE_JSON_SCHEMA
    ap = panel_patch["properties"]["problem"]["properties"]["algorithm_params"]
    assert ap.get("additionalProperties") is False
    assert "pc" in ap["properties"]
    assert "mutation_step_size_damp" in ap["properties"]


def test_config_schema_requires_known_driver_preference_fields():
    panel_patch = CONFIG_MODEL_PANEL_RESPONSE_JSON_SCHEMA
    driver_pref = panel_patch["properties"]["problem"]["properties"]["driver_preferences"]["items"]

    assert driver_pref["required"] == ["vehicle_idx", "condition", "penalty"]
    assert driver_pref["properties"]["condition"]["type"] == "string"


def test_chat_schema_focuses_on_assistant_and_problem_brief_patch():
    assert "assistant_message" in CHAT_MODEL_TURN_RESPONSE_JSON_SCHEMA["properties"]
    assert "problem_brief_patch" in CHAT_MODEL_TURN_RESPONSE_JSON_SCHEMA["properties"]
    assert "panel_patch" not in CHAT_MODEL_TURN_RESPONSE_JSON_SCHEMA["properties"]


def test_run_trigger_intent_schema_has_expected_fields():
    assert RUN_TRIGGER_INTENT_RESPONSE_JSON_SCHEMA["properties"]["should_trigger_run"]["type"] == "boolean"
    assert RUN_TRIGGER_INTENT_RESPONSE_JSON_SCHEMA["properties"]["intent_type"]["enum"] == [
        "none",
        "affirm_invite",
        "direct_request",
    ]
    assert "should_trigger_run" in RUN_TRIGGER_INTENT_RESPONSE_JSON_SCHEMA["required"]


def test_system_instruction_includes_hidden_researcher_steering_block():
    system = _build_structured_system_instruction(
        current_problem_brief={},
        workflow_mode="waterfall",
        recent_runs_summary=None,
        researcher_steers=["Prioritize concise, run-focused guidance."],
    )

    assert "Hidden researcher steering" in system
    assert "highest-priority instruction for this next participant reply" in system
    assert "Prioritize concise, run-focused guidance." in system


def test_brief_update_system_instruction_includes_items_discipline_and_cleanup_mandate():
    """Hidden brief derivation used to omit structured-chat items rules; cleanup must not conflict."""
    system = _build_brief_update_system_instruction(
        current_problem_brief={"goal_summary": "", "items": []},
        cleanup_mode=True,
    )
    assert "Rule 5 — One goal term per row" in system
    assert "Mandatory:" in system and "Constraint handling" in system
