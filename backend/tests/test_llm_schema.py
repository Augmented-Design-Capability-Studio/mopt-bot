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


def test_brief_update_system_instruction_carries_visible_assistant_message_waterfall():
    """When the visible chat just told the participant 'Changes I made: …', the
    hidden brief turn must see that text as authoritative context — otherwise
    the chat and the brief diverge (chat claims a change, brief never commits).
    Workflow-aware: waterfall uses OQ language, never `kind: "assumption"`.
    """
    visible_reply = (
        "Changes I made: I've increased the lateness penalty weight to push the "
        "solver toward on-time deliveries. Want me to also rebalance workload?"
    )
    system = _build_brief_update_system_instruction(
        current_problem_brief={"goal_summary": "", "items": []},
        workflow_mode="waterfall",
        visible_assistant_message=visible_reply,
    )
    flat = " ".join(system.split())
    assert "Visible assistant reply that JUST got sent" in system
    assert visible_reply in system
    assert "emit the corresponding `problem_brief_patch`" in flat
    # Waterfall must record clarifying questions in open_questions, not as assumptions.
    assert "open_questions" in flat
    assert "Clarifying question in waterfall" in flat
    # Explicit prohibition of `kind: "assumption"` in waterfall.
    assert (
        "Never use `kind: \"assumption\"`" in flat
        or "do NOT emit a `kind: \"assumption\"` row in waterfall" in flat
    )


def test_brief_update_system_instruction_carries_visible_assistant_message_agile():
    """Agile uses `kind: "assumption"` proactively for tentative choices."""
    visible_reply = "I've added a punctuality penalty assumption (weight 5)."
    system = _build_brief_update_system_instruction(
        current_problem_brief={"goal_summary": "", "items": []},
        workflow_mode="agile",
        visible_assistant_message=visible_reply,
    )
    flat = " ".join(system.split())
    assert "Visible assistant reply that JUST got sent" in system
    assert "agile/demo" in flat
    assert "kind: \"assumption\"" in flat


def test_agile_workflow_prompt_permits_proactive_assumption_keys():
    """Agile must allow the agent to introduce new goal-term keys autonomously
    as `kind: "assumption"` (the defining behaviour of the agile arm). The
    earlier rule blocked any new key without explicit user agreement, which
    caused the LLM to claim a brief change in the visible reply but skip the
    actual patch — leaving the panel inconsistent with the chat.
    """
    system = _build_brief_update_system_instruction(
        current_problem_brief={"goal_summary": "", "items": []},
        workflow_mode="agile",
    )
    flat = " ".join(system.split())
    # Proactive-add wording for new keys must be present.
    assert "proactively add the new key" in flat or "MAY proactively add" in flat
    # The promotion bar (assumption → gathered) must remain explicit-confirmation only.
    assert "promotes an assumption row to `kind: \"gathered\"`" in flat or "promote" in flat


def test_agile_workflow_prompt_requires_decisive_search_strategy_default():
    """Agile must commit a default search strategy on the first turn that has
    objectives in play AND name the algorithm in a brief items[] row — the
    server's search-strategy gate strips the panel's algorithm field
    otherwise, which blocks the auto-first-run.
    """
    system = _build_brief_update_system_instruction(
        current_problem_brief={"goal_summary": "", "items": []},
        workflow_mode="agile",
    )
    flat = " ".join(system.split())
    # Must commit, not "may".
    assert "MUST" in flat and "default search strategy" in flat
    # Must name the algorithm in a brief row so the gate passes.
    assert "names the algorithm by name" in flat
    # Must call out the auto-first-run dependency explicitly.
    assert "auto-first-run" in flat


def test_visible_reply_context_block_requires_algorithm_named_brief_row():
    """When the visible reply commits to an algorithm, the brief MUST land
    a row that names it — otherwise the search-strategy gate strips the
    panel's algorithm and the run gate fails.
    """
    visible_reply = "I'll default our search strategy to a genetic search to get us started."
    system = _build_brief_update_system_instruction(
        current_problem_brief={"goal_summary": "", "items": []},
        workflow_mode="agile",
        visible_assistant_message=visible_reply,
    )
    flat = " ".join(system.split())
    assert "Algorithm / search-strategy commitment" in flat
    assert "names the algorithm by name" in flat
    assert "search-strategy gate" in flat or "strips the" in flat


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


def test_brief_update_instruction_asks_for_visible_reply_intent_classification():
    """The brief-update prompt must instruct the LLM to populate the new
    `visible_reply_intent` booleans whenever the visible reply is supplied,
    so the compliance check downstream gets honest signal."""
    system = _build_brief_update_system_instruction(
        current_problem_brief={"goal_summary": "", "items": []},
        workflow_mode="agile",
        visible_assistant_message="I've added a workload-balance assumption (weight 3).",
    )
    flat = " ".join(system.split())
    assert "visible_reply_intent" in flat
    assert "claims_brief_change" in flat
    assert "asks_user_question" in flat


def test_brief_update_system_instruction_omits_visible_section_when_absent():
    """When no visible reply is supplied, the section is omitted — keeps the
    legacy / non-chat call sites (e.g. the OQ-cleanup pass) unaffected."""
    system_blank = _build_brief_update_system_instruction(
        current_problem_brief={"goal_summary": "", "items": []},
        visible_assistant_message=None,
    )
    system_empty = _build_brief_update_system_instruction(
        current_problem_brief={"goal_summary": "", "items": []},
        visible_assistant_message="   ",
    )
    assert "Visible assistant reply that JUST got sent" not in system_blank
    assert "Visible assistant reply that JUST got sent" not in system_empty


def test_visible_chat_instruction_enforces_plain_language_over_internal_keys():
    system = _build_visible_chat_system_instruction(
        user_text="Help me prioritize outcomes.",
        current_problem_brief={"goal_summary": "Improve delivery consistency.", "items": [], "open_questions": []},
        workflow_mode="agile",
    )
    assert "Participant-facing wording guardrails" in system
    assert "**not** use raw key names" in system
    assert "avoid \"activate/enable/turn on\" phrasing" in system
    assert "Conversation temperature" in system
    assert "Capabilities" in system


def test_visible_chat_instruction_cold_generic_query_avoids_module_capability_rows():
    system = _build_visible_chat_system_instruction(
        user_text="how do you optimize?",
        current_problem_brief=default_problem_brief("vrptw"),
        workflow_mode="waterfall",
        test_problem_id="vrptw",
    )
    assert "Capabilities" in system
    assert "Goal terms you can adjust:" not in system
    assert "Visualizations I've set up for this task:" not in system


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


def test_system_instruction_includes_knapsack_benchmark_appendix():
    system = _build_structured_system_instruction(
        current_problem_brief=_warm_brief(),
        workflow_mode="waterfall",
        test_problem_id="knapsack",
    )
    assert "Active benchmark — 0/1 knapsack" in system


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
