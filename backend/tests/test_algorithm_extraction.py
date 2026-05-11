"""Tests for extracting the canonical algorithm name from brief items.

This helper backs the deterministic ``derive_problem_panel_from_brief``
seed used by every problem port. The bug it fixes: when a participant
answered "which search method?" with *"Genetic search"* in waterfall +
knapsack, the gathered brief row landed but knapsack's panel-derive
returned None — so the panel's ``algorithm`` stayed empty, the run gate's
``search_strategy_present`` check failed, and Run optimization stayed
disabled. VRPTW already extracted algorithm from brief text; knapsack
now uses the same helper.
"""

from app.services.goal_term_anchoring import (
    algorithm_mentioned_in_brief,
    extract_algorithm_from_brief,
)


def _item(text: str, kind: str = "gathered") -> dict:
    return {"id": "x", "text": text, "kind": kind, "source": "user"}


def test_extract_genetic_search_returns_ga():
    items = [_item("Genetic search is being used as the search method.")]
    assert extract_algorithm_from_brief(items) == "GA"


def test_extract_short_acronym_word_boundary():
    items = [_item("Using GA for this run.")]
    assert extract_algorithm_from_brief(items) == "GA"


def test_extract_short_acronym_avoids_substring_false_positive():
    # "garbage" contains "ga" — must NOT match.
    items = [_item("ignore the garbage values for now.")]
    assert extract_algorithm_from_brief(items) is None


def test_extract_swarm_search_returns_pso():
    items = [_item("We'll start with swarm search (PSO).")]
    # Longer aliases ("swarm search") win over short ones; either way
    # PSO is the canonical result.
    assert extract_algorithm_from_brief(items) == "PSO"


def test_extract_swarmsa_wins_over_sa():
    """Longer alias must win: "swarm-based simulated annealing" → SwarmSA,
    not SA (which is a substring of "simulated annealing")."""
    items = [_item("Swarm-based simulated annealing chosen.")]
    assert extract_algorithm_from_brief(items) == "SwarmSA"


def test_extract_returns_none_when_no_algorithm_mentioned():
    items = [_item("Minimize travel time and balance workload.")]
    assert extract_algorithm_from_brief(items) is None


def test_extract_skips_empty_or_malformed_items():
    items = [
        None,  # type: ignore[list-item]
        {"text": ""},
        {"text": "  "},
        _item("Genetic search picked."),
    ]
    assert extract_algorithm_from_brief(items) == "GA"


def test_extract_uses_first_item_with_a_match():
    items = [
        _item("Some background context."),
        _item("Let's use PSO."),
        _item("Also mentioned: simulated annealing as backup."),
    ]
    assert extract_algorithm_from_brief(items) == "PSO"


def test_mentioned_and_extract_agree_on_negative_case():
    items = [_item("No algorithm preference yet.")]
    assert algorithm_mentioned_in_brief(items) is False
    assert extract_algorithm_from_brief(items) is None


def test_mentioned_and_extract_agree_on_positive_case():
    items = [_item("Genetic search.")]
    assert algorithm_mentioned_in_brief(items) is True
    assert extract_algorithm_from_brief(items) == "GA"
