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

from app.services.goal_term_anchoring import extract_algorithm_from_brief


def _item(text: str, kind: str = "gathered") -> dict:
    return {"id": "x", "text": text, "kind": kind, "source": "user"}


def test_extract_genetic_search_returns_ga():
    items = [_item("Genetic search is being used as the search method.")]
    assert extract_algorithm_from_brief(items) == "GA"


def test_extract_swarmsa_wins_over_sa():
    """Longer alias must win: "swarm-based simulated annealing" → SwarmSA,
    not SA (which is a substring of "simulated annealing")."""
    items = [_item("Swarm-based simulated annealing chosen.")]
    assert extract_algorithm_from_brief(items) == "SwarmSA"


def test_extract_returns_none_when_no_algorithm_mentioned():
    items = [_item("Minimize travel time and balance workload.")]
    assert extract_algorithm_from_brief(items) is None
