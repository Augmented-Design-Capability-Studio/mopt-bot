"""Golden snapshots of the assembled main-turn system instruction.

Phase 0 of the prompt-reduction work (see
``docs/.implementation/USER_FLOW_AUDIT.md``). The main turn is a
single ~7k-word instruction; these tests pin (a) which named blocks are
present per turn type and (b) the exact word budget per turn type, so any
prompt refactor surfaces as an explicit, reviewed diff instead of silent
drift. When a change is intentional, update the manifest in the same PR —
the word-count delta is the per-step reduction measurement the plan asks
for.

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
}

# Exact per-scenario word budget at Phase 0. This is BOTH a drift tripwire
# and the reduction measurement: every prompt PR updates these numbers and
# the diff IS the savings. Update deliberately, never blindly.
WORD_BUDGET: dict[str, int] = {
    # Phase-0 baseline (warm_waterfall 7330) lives in git history. Reductions:
    #  • SYSTEM_PROMPT L5 compress 1564→1053 (−511 every turn, rules preserved)
    #  • HARD_CONSTRAINT 478→302, OUT_OF_SCOPE 363→241 (−298 every turn)
    #  • BRIEF_UPDATE 623→299 (dedup vs items), GROUNDING 300→216,
    #    ITEMS 336→242 (−502 every turn)
    #  • SYSTEM_PROMPT split: warm-only block (run/run-button/Q&A, 384 w)
    #    extracted → cold turns shed it; warm turns unchanged (content moved)
    "cold_waterfall": 4133,
    "warm_waterfall": 6019,
    "warm_agile": 6259,
    "warm_demo": 6343,
    "config_save": 6331,
    "upload_context": 6066,
    "retry": 6051,
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
def test_main_turn_word_budget(scenario):
    """Exact word-count snapshot per turn type. A failure here means the
    prompt size changed — review the diff and update WORD_BUDGET in the
    same PR, recording the reduction (or flagging accidental growth)."""
    words = len(_build(scenario).split())
    assert words == WORD_BUDGET[scenario], (
        f"[{scenario}] word count = {words}, snapshot = {WORD_BUDGET[scenario]} "
        f"(delta {words - WORD_BUDGET[scenario]:+d}). Update WORD_BUDGET if intended."
    )
