from app.problem_brief import default_problem_brief
from app.problems.registry import get_study_port
from app.services import llm
from app.services.llm import (
    CHAT_MODEL_TURN_RESPONSE_JSON_SCHEMA,
    CONFIG_MODEL_PANEL_RESPONSE_JSON_SCHEMA,
    RUN_TRIGGER_INTENT_RESPONSE_JSON_SCHEMA,
    _build_visible_chat_system_instruction,
    _build_brief_update_system_instruction,
    _build_structured_system_instruction,
)


def test_config_schema_constrains_problem_weights_to_object():
    panel_patch = CONFIG_MODEL_PANEL_RESPONSE_JSON_SCHEMA
    problem = panel_patch["properties"]["problem"]
    weights = problem["properties"]["weights"]

    assert weights["type"] == "object"
    assert weights.get("additionalProperties") is False
    assert len(weights["properties"]) > 0
    assert problem.get("additionalProperties") is False
    assert panel_patch.get("additionalProperties") is False


def test_config_schema_algorithm_params_has_bounded_properties():
    panel_patch = CONFIG_MODEL_PANEL_RESPONSE_JSON_SCHEMA
    problem_props = panel_patch["properties"]["problem"]["properties"]
    ap = problem_props["algorithm_params"]
    assert ap.get("additionalProperties") is False
    assert "pc" in ap["properties"]
    assert "mutation_step_size_damp" in ap["properties"]
    constraint_types = problem_props["constraint_types"]
    assert constraint_types["type"] == "object"
    assert constraint_types["additionalProperties"]["enum"] == ["soft", "hard", "custom"]
    assert "goal_terms" in problem_props
    assert "hard_constraints" not in problem_props
    assert "soft_constraints" not in problem_props


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
    assert "One goal term per row" in system
    assert "Mandatory:" in system and "Constraint handling" in system


def test_visible_chat_instruction_enforces_plain_language_over_internal_keys():
    system = _build_visible_chat_system_instruction(
        current_problem_brief={"goal_summary": "Improve delivery consistency.", "items": [], "open_questions": []},
        workflow_mode="agile",
    )
    assert "Participant-facing wording guardrails" in system
    assert "**not** use raw key names" in system
    assert "avoid \"activate/enable/turn on\" phrasing" in system


def _warm_brief() -> dict:
    """Warm = appendix and full brief are injected; empty dict is cold."""
    return {"goal_summary": "User stated goals", "open_questions": [], "items": []}


def test_system_instruction_includes_vrptw_benchmark_appendix():
    system = _build_structured_system_instruction(
        current_problem_brief=_warm_brief(),
        workflow_mode="waterfall",
        test_problem_id="vrptw",
    )
    assert "Active benchmark — fleet scheduling (VRPTW)" in system
    assert "Active benchmark" in system


def test_system_instruction_includes_knapsack_benchmark_appendix():
    system = _build_structured_system_instruction(
        current_problem_brief=_warm_brief(),
        workflow_mode="waterfall",
        test_problem_id="knapsack",
    )
    assert "Active benchmark — 0/1 knapsack" in system
    assert "Active benchmark" in system


def test_system_prompt_openers_skip_appendix_when_cold_knapsack():
    apx = get_study_port("knapsack").study_prompt_appendix() or ""
    assert "0/1 knapsack" in apx
    parts = llm._system_prompt_openers("knapsack", default_problem_brief("knapsack"))
    assert len(parts) == 1
    assert "0/1 knapsack" not in "\n\n".join(parts)


def test_system_prompt_openers_includes_appendix_when_warm_knapsack():
    b = {**default_problem_brief("knapsack"), "goal_summary": "Pack high value under capacity."}
    parts = llm._system_prompt_openers("knapsack", b)
    assert len(parts) == 2
    assert "0/1 knapsack" in parts[1]
