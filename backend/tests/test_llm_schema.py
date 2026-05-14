from app.problem_brief import default_problem_brief
from app.problems.registry import get_study_port
from app.services import llm
from app.services.llm import (
    CHAT_MODEL_TURN_RESPONSE_JSON_SCHEMA,
    CONFIG_MODEL_PANEL_RESPONSE_JSON_SCHEMA,
    RUN_TRIGGER_INTENT_RESPONSE_JSON_SCHEMA,
    _build_visible_chat_system_instruction,
    _build_brief_update_response_schema,
    _build_brief_update_system_instruction,
    _build_structured_system_instruction,
    _visible_reply_consistency_block,
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


def test_brief_update_schema_carries_visible_reply_intent_classification():
    """Compliance no longer regex-matches the visible reply text — instead the
    brief-update LLM self-reports the intent in `visible_reply_intent`. The
    response schema must expose that field and both booleans, otherwise the
    deterministic compliance check at the end of derivation has no signal to
    work with.
    """
    schema = _build_brief_update_response_schema(None)
    props = schema["properties"]
    assert "visible_reply_intent" in props
    intent_props = props["visible_reply_intent"]["properties"]
    assert intent_props["claims_brief_change"]["type"] == "boolean"
    assert intent_props["asks_user_question"]["type"] == "boolean"


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


# ---------------------------------------------------------------------------
# Gate-status block in system instructions.
# ---------------------------------------------------------------------------


_GATE_STATUS_FIXTURE = {
    "workflow_mode": "waterfall",
    "goal_term_present": True,
    "search_strategy_present": False,
    "open_questions_pending": 0,
    "gate_engaged": True,
    "ready_to_run": False,
    "missing": ["search_strategy"],
}


_GATE_BLOCK_MARKER = "## Run-gate status (machine-readable"


def test_brief_update_schema_forbids_synthesized_id_prefix_for_vrptw():
    """VRPTW's synthesizer owns `config-driver-pref-*`; the brief-update
    schema must reject LLM-emitted items with that prefix via a regex on id."""
    import re

    schema = _build_brief_update_response_schema("vrptw")
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
