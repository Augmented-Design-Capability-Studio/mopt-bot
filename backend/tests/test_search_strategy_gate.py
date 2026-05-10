"""Workflow-legitimacy gate: search-strategy panel fields require a brief row.

The brief→panel sync should NOT silently surface algorithm/epochs/pop_size
when the brief lacks any gathered/assumption row that names search strategy.
The gate is problem-agnostic; the underlying detector consults the active
port for slot-key recognition and the closed algorithm-name vocabulary.
"""

from __future__ import annotations

from app.services.goal_term_anchoring import (
    SEARCH_STRATEGY_PANEL_FIELDS,
    brief_mentions_search_strategy,
)


def _gathered(text: str, item_id: str = "g1") -> dict:
    return {"id": item_id, "text": text, "kind": "gathered", "source": "user"}


def _assumption(text: str, item_id: str = "a1") -> dict:
    return {"id": item_id, "text": text, "kind": "assumption", "source": "agent"}


def test_empty_brief_does_not_mention_search_strategy():
    assert brief_mentions_search_strategy({"items": []}) is False
    assert brief_mentions_search_strategy(None) is False


def test_brief_with_only_objective_facts_does_not_mention_search_strategy():
    brief = {
        "items": [
            _gathered("User wants to minimize total travel time."),
            _gathered("Capacity is treated as a hard constraint.", "g2"),
        ]
    }
    assert brief_mentions_search_strategy(brief) is False


def test_algorithm_name_in_text_counts_as_mention():
    brief = {"items": [_gathered("Let's start with GA for now.")]}
    assert brief_mentions_search_strategy(brief) is True


def test_synthesized_search_strategy_slot_counts_as_mention():
    """Items synthesised from the panel use stable ids like
    ``config-search-strategy`` / ``config-algorithm`` / ``config-pop-size``;
    the slot detector picks those up regardless of text content."""
    brief = {
        "items": [
            {
                "id": "config-search-strategy",
                "text": "Search strategy: SA (max iterations 25, population size 12).",
                "kind": "gathered",
                "source": "agent",
            }
        ]
    }
    assert brief_mentions_search_strategy(brief) is True


def test_unmentioned_algorithm_param_in_isolation_still_counts():
    brief = {
        "items": [
            {
                "id": "config-algorithm-param-pc",
                "text": "Crossover rate is set to 0.8.",
                "kind": "gathered",
                "source": "agent",
            }
        ]
    }
    assert brief_mentions_search_strategy(brief) is True


def test_open_question_alone_is_not_a_mention():
    """An *unanswered* OQ asking about algorithm choice is not a justification.
    Only a gathered/assumption row (which is what the answered-OQ path produces) is."""
    brief = {
        "items": [],
        "open_questions": [
            {"id": "q1", "text": "Which algorithm should we use?", "status": "open"}
        ],
    }
    assert brief_mentions_search_strategy(brief) is False


def test_search_strategy_panel_fields_include_algorithm_and_budget():
    """Sanity check on the constant the gate strips. The exact membership is
    load-bearing for `sync_panel_from_problem_brief`'s strip step."""
    assert "algorithm" in SEARCH_STRATEGY_PANEL_FIELDS
    assert "epochs" in SEARCH_STRATEGY_PANEL_FIELDS
    assert "pop_size" in SEARCH_STRATEGY_PANEL_FIELDS
    assert "algorithm_params" in SEARCH_STRATEGY_PANEL_FIELDS
