"""Golden snapshots of the assembled main-turn system instruction.

Phase 0 of the prompt-reduction work (see
``docs/.implementation/USER_FLOW_AUDIT.md``). Two guards on the assembled
main-turn instruction:

(a) **block presence** — which named blocks load per turn type. This is the
    behavioural contract (e.g. cold turns shed the warm-only guidance); the
    expected sets encode intent, so a block loading in the wrong state fails.
(b) **word ceiling** — the prompt must not silently grow past budget. A
    ceiling (not an exact `==` snapshot) so reductions pass freely while
    growth trips the test for review — avoids self-fulfilling churn.

Assembly is exercised API-free (``api_key=None`` skips the optional
temperature-classify / doc-retrieval sub-calls), so these run in CI with
no key and no network.
"""

from __future__ import annotations

import pytest

from app.prompts import study_chat as P
from app.services.llm import build_main_turn_system_instruction


# Map a short key → a stable marker substring taken from the head of each
# block constant (post-strip, so join-whitespace differences don't matter).
# Membership of the marker in the assembled instruction == block present.
def _marker(block_text: str) -> str:
    return block_text.strip()[:60]


BLOCK_MARKERS: dict[str, str] = {
    "system": _marker(P.STUDY_CHAT_SYSTEM_PROMPT),
    "system_warm": _marker(P.STUDY_CHAT_SYSTEM_PROMPT_WARM),
    "visible_reply": _marker(P.STUDY_CHAT_VISIBLE_REPLY_TASK),
    "brief_update": _marker(P.STUDY_CHAT_BRIEF_UPDATE_TASK),
    "items": _marker(P.STUDY_CHAT_ITEMS_DISCIPLINE),
    "hidden_items": _marker(P.STUDY_CHAT_HIDDEN_BRIEF_ITEMS_RULES),
    "grounding": _marker(P.STUDY_CHAT_GROUNDING_DISCIPLINE),
    "hard_constraint": _marker(P.STUDY_CHAT_HARD_CONSTRAINT_DISCIPLINE),
    "ambiguity": _marker(P.STUDY_CHAT_AMBIGUITY_DISCIPLINE),
    "out_of_scope": _marker(P.STUDY_CHAT_OUT_OF_SCOPE_DISCIPLINE),
    "workflow_waterfall": _marker(P.STUDY_CHAT_WORKFLOW_WATERFALL),
    "workflow_agile": _marker(P.STUDY_CHAT_WORKFLOW_AGILE),
    "workflow_demo": _marker(P.STUDY_CHAT_WORKFLOW_DEMO),
    "sandbox": _marker(P.STUDY_CHAT_SANDBOX_RULES),
    "visualization": _marker(P.STUDY_CHAT_VISUALIZATION_GUIDANCE),
    "config_save": _marker(P.STUDY_CHAT_CONFIG_SAVE_RATIONALE),
    "upload_context": _marker(P.STUDY_CHAT_UPLOAD_CONTEXT_GUIDANCE),
    "answered_oq": _marker(P.STUDY_CHAT_ANSWERED_OQ_CONTEXT),
    "run_ack": _marker(P.STUDY_CHAT_RUN_ACK_BASE),
    "tutorial": _marker(P.STUDY_CHAT_TUTORIAL_GUARDRAILS),
    # Brief-edit ack is an inline block in build_main_turn_system_instruction,
    # not a study_chat constant — match its literal heading.
    "brief_edit": "## Brief-edit acknowledgement",
}


def _present_blocks(instruction: str) -> set[str]:
    return {key for key, marker in BLOCK_MARKERS.items() if marker in instruction}


def _warm_brief() -> dict:
    return {
        "goal_summary": "Minimize total travel time.",
        "items": [
            {"id": "x", "text": "Minimize travel time", "kind": "gathered", "source": "user"}
        ],
        "open_questions": [],
        "goal_terms": {"travel_time": {"weight": 1.0, "type": "objective", "rank": 1}},
        "topic_engaged": True,
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }


def _cold_brief() -> dict:
    return {
        "goal_summary": "",
        "items": [],
        "open_questions": [],
        "goal_terms": {},
        "topic_engaged": False,
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }


# scenario key → kwargs for build_main_turn_system_instruction
SCENARIOS: dict[str, dict] = {
    "cold_waterfall": dict(
        user_text="hi", current_problem_brief=_cold_brief(), workflow_mode="waterfall"
    ),
    "warm_waterfall": dict(
        user_text="minimize travel time",
        current_problem_brief=_warm_brief(),
        workflow_mode="waterfall",
    ),
    "warm_agile": dict(
        user_text="minimize travel time",
        current_problem_brief=_warm_brief(),
        workflow_mode="agile",
    ),
    "warm_demo": dict(
        user_text="minimize travel time",
        current_problem_brief=_warm_brief(),
        workflow_mode="demo",
    ),
    "config_save": dict(
        user_text="(saved panel)",
        current_problem_brief=_warm_brief(),
        workflow_mode="waterfall",
        is_config_save=True,
    ),
    "upload_context": dict(
        user_text="uploading ORDERS.csv",
        current_problem_brief=_warm_brief(),
        workflow_mode="waterfall",
        is_upload_context=True,
    ),
    "retry": dict(
        user_text="minimize travel time",
        current_problem_brief=_warm_brief(),
        workflow_mode="waterfall",
        verification_issues=[
            {"category": "unanchored_goal_term", "severity": "error", "message": "x"}
        ],
    ),
    # Run-ack carries completed runs, so the (pre-first-run) visualization
    # block is correctly OFF while the run-ack guidance block is ON.
    "run_ack": dict(
        user_text="Run #1 just completed",
        current_problem_brief=_warm_brief(),
        workflow_mode="waterfall",
        is_run_acknowledgement=True,
        recent_runs_summary=[{"run": 1, "cost": 5}],
    ),
    "tutorial": dict(
        user_text="minimize travel time",
        current_problem_brief=_warm_brief(),
        workflow_mode="waterfall",
        is_tutorial_active=True,
    ),
    "answered_oq": dict(
        user_text='- "Q" -> "A"',
        current_problem_brief=_warm_brief(),
        workflow_mode="waterfall",
        is_answered_open_question=True,
    ),
    "brief_edit": dict(
        user_text="(saved definition)",
        current_problem_brief=_warm_brief(),
        workflow_mode="waterfall",
        is_brief_edit_ack=True,
    ),
}


def _build(scenario_key: str) -> str:
    return build_main_turn_system_instruction(
        test_problem_id="vrptw", api_key=None, model_name=None, **SCENARIOS[scenario_key]
    )


# Golden manifest: scenario → (frozenset of present block keys, exact word count).
# UPDATE DELIBERATELY when a prompt change is intended; the word-count delta
# is the reduction measurement for that PR.
_ALWAYS = {
    "system", "visible_reply", "brief_update", "items", "hidden_items",
    "grounding", "hard_constraint", "ambiguity", "out_of_scope",
}
EXPECTED_BLOCKS: dict[str, set[str]] = {
    # Cold start: warm system block + visualization gated off; sandbox on
    # (cold probe window). Cold is pure goal-elicitation.
    "cold_waterfall": _ALWAYS | {"workflow_waterfall", "sandbox"},
    # Warm turns load the warm system block (run results / run-button /
    # algorithm-weight Q&A) + visualization guidance (pre-first-run).
    "warm_waterfall": _ALWAYS | {"system_warm", "workflow_waterfall", "visualization"},
    "warm_agile": _ALWAYS | {"system_warm", "workflow_agile", "visualization"},
    "warm_demo": _ALWAYS | {"system_warm", "workflow_demo", "visualization"},
    "config_save": _ALWAYS | {"system_warm", "workflow_waterfall", "visualization", "config_save"},
    "upload_context": _ALWAYS | {"system_warm", "workflow_waterfall", "visualization", "upload_context"},
    "retry": _ALWAYS | {"system_warm", "workflow_waterfall", "visualization"},
    # Run-ack: run-ack guidance ON; visualization OFF (runs already completed).
    "run_ack": _ALWAYS | {"system_warm", "workflow_waterfall", "run_ack"},
    "tutorial": _ALWAYS | {"system_warm", "workflow_waterfall", "visualization", "tutorial"},
    "answered_oq": _ALWAYS | {"system_warm", "workflow_waterfall", "visualization", "answered_oq"},
    "brief_edit": _ALWAYS | {"system_warm", "workflow_waterfall", "visualization", "brief_edit"},
}

# Per-scenario word CEILINGS, not exact snapshots. The intent this encodes is
# "the main-turn prompt must not silently grow past budget" — the actual goal of
# keeping prompts short for accuracy. Asymmetric on purpose: a reduction passes
# freely (stays under the cap), but GROWTH trips the test and must be reviewed +
# the cap bumped deliberately. Set at the current word counts (no headroom) so
# any regrowth is caught immediately. A ceiling avoids the self-fulfilling churn
# of an exact `==` snapshot, which would have to be re-pasted on every edit.
# Deliberate bump (~+32 across the board): the items-discipline block was
# reworked to match the structured-items whitelist — items[] is now a
# server-built projection (goal terms + search strategy + upload marker), the
# agent no longer authors standalone fact rows, and is told to FOLD any
# free-text it's handed (a Definition row the participant typed, an answered
# question's note) into a goal term / goal_summary / open question. Net new
# behavior, so a small uniform growth; replaced the looser "other rows are
# natural language" rule.
# Deliberate +45 on every WATERFALL scenario only (agile/demo unchanged): the
# waterfall assumption-policy block now tells the agent that a USER-stated
# primary objective is already `gathered` and must be committed the same turn
# (like agile), rather than deferred into an open_question — which left the
# brief with no objective and kept the server goal-monitor OQ up (P_0602).
WORD_BUDGET_CEILING: dict[str, int] = {
    "cold_waterfall": 4215,
    "warm_waterfall": 6096,
    "warm_agile": 6268,
    "warm_demo": 6391,
    "config_save": 6408,
    "upload_context": 6141,
    "retry": 6187,
    "run_ack": 5954,
    "tutorial": 6353,
    "answered_oq": 6141,
    "brief_edit": 6167,
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_main_turn_block_presence(scenario):
    """Pins which named blocks are loaded per turn type. Catches accidental
    (or intentional-but-unreviewed) changes to conditional loading."""
    present = _present_blocks(_build(scenario))
    assert present == EXPECTED_BLOCKS[scenario], (
        f"[{scenario}] block set drifted.\n"
        f"  added:   {sorted(present - EXPECTED_BLOCKS[scenario])}\n"
        f"  removed: {sorted(EXPECTED_BLOCKS[scenario] - present)}"
    )


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_main_turn_stays_under_word_ceiling(scenario):
    """The main-turn prompt must not silently grow past its budget. Reductions
    pass freely; growth fails — review the new content, then bump the ceiling in
    WORD_BUDGET_CEILING deliberately (and ideally tighten it back down)."""
    words = len(_build(scenario).split())
    ceiling = WORD_BUDGET_CEILING[scenario]
    assert words <= ceiling, (
        f"[{scenario}] main-turn prompt grew to {words} words, over the "
        f"{ceiling} ceiling (+{words - ceiling}). Review the added content; if "
        f"intended, raise the ceiling in WORD_BUDGET_CEILING."
    )
