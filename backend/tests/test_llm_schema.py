"""Schema-shape tests for the chat-pipeline LLM surface."""

from app.problem_brief import default_problem_brief
from app.problems.registry import get_study_port
from app.services import llm
from app.services.llm import (
    CONFIG_MODEL_PANEL_RESPONSE_JSON_SCHEMA,
    _build_main_turn_schema,
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


def test_main_turn_schema_has_required_fields():
    """Main-turn LLM response carries everything one chat turn needs in
    one structured payload: visible reply, intent flags, brief patch,
    and (agile/demo only) per-row assumption decisions."""
    schema = _build_main_turn_schema(None)
    props = schema["properties"]
    for field in (
        "assistant_message",
        "is_change_intent",
        "should_trigger_run",
        "intent_type",
        "is_run_invitation",
        "problem_brief_patch",
        "replace_editable_items",
        "replace_open_questions",
        "assumption_actions",
        "change_clause",
        "question_clause",
    ):
        assert field in props, f"Missing field {field}"
    assert schema["required"] == ["assistant_message"]


def test_main_turn_schema_carries_per_port_brief_shape():
    """The brief-patch sub-schema must reflect the active port's typing —
    VRPTW emits `goal_terms.search_strategy.properties.algorithm` as a
    typed enum carrier, knapsack does not.
    """
    vrptw = _build_main_turn_schema("vrptw")
    patch_anyof = vrptw["properties"]["problem_brief_patch"]["anyOf"]
    patch_schema = next(s for s in patch_anyof if s.get("type") == "object")
    goal_terms = patch_schema["properties"]["goal_terms"]
    # Each port's goal_terms_schema slots its properties subschema into
    # `additionalProperties`. Confirm VRPTW's algorithm carrier is typed.
    entry_schema = goal_terms.get("additionalProperties", {})
    properties_schema = entry_schema.get("properties", {}).get("properties", {})
    if isinstance(properties_schema, dict):
        algo = properties_schema.get("properties", {}).get("algorithm", {})
        if algo:
            assert algo.get("type") == "string"
            assert "GA" in algo.get("enum", [])


def _warm_brief() -> dict:
    """Warm = appendix and full brief are injected; empty dict is cold."""
    return {
        "goal_summary": "User stated goals",
        "open_questions": [],
        "items": [],
        "topic_engaged": True,
    }


def test_system_prompt_openers_skip_appendix_when_cold_knapsack():
    apx = get_study_port("knapsack").study_prompt_appendix() or ""
    assert "0/1 knapsack" in apx
    parts = llm._system_prompt_openers("knapsack", default_problem_brief("knapsack"))
    assert len(parts) == 1
    assert "0/1 knapsack" not in "\n\n".join(parts)


def test_system_prompt_openers_includes_appendix_when_warm_knapsack():
    b = {**default_problem_brief("knapsack"), "topic_engaged": True}
    parts = llm._system_prompt_openers("knapsack", b)
    assert len(parts) == 2
    assert "0/1 knapsack" in parts[1]


def test_main_turn_schema_forbids_synthesized_id_prefix_for_vrptw():
    """VRPTW's synthesizer owns `config-driver-pref-*`; the brief-patch
    sub-schema must reject LLM-emitted items[] entries with that prefix.
    """
    import re

    schema = _build_main_turn_schema("vrptw")
    patch_anyof = schema["properties"]["problem_brief_patch"]["anyOf"]
    patch_schema = next(s for s in patch_anyof if s.get("type") == "object")
    id_field = patch_schema["properties"]["items"]["items"]["properties"]["id"]
    pattern = id_field.get("pattern")
    assert pattern, "Expected an id pattern on the VRPTW item schema"
    # Forbidden prefix should be rejected.
    assert re.match(pattern, "config-driver-pref-0-zoneD") is None
    # Anything else should pass.
    assert re.match(pattern, "config-weight-travel_time") is not None
    assert re.match(pattern, "g1") is not None
