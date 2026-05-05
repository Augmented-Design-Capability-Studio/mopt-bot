"""Smoke test: knapsack SPECS table feeds the shared builder correctly.

Generic filter / coercion / arithmetic behaviour is covered by
``backend/tests/test_cost_breakdown.py``.  This file just pins each knapsack
alias to the right (weight key, metric key) pair so the cost line in
``knapsack_problem/evaluator.py:evaluate_selection`` stays in sync.
"""

from __future__ import annotations

from app.problems.cost_breakdown import build_goal_term_contributions
from knapsack_problem.cost_breakdown import SPECS


def _metrics() -> dict[str, float]:
    return {"value_term": -42.5, "overflow": 3.0, "selected_count": 7}


def _weights() -> dict[str, float]:
    return {"value_emphasis": 1.0, "capacity_overflow": 50.0, "selection_sparsity": 0.5}


def test_spec_keys_cover_all_three_knapsack_terms():
    assert {s.key for s in SPECS} == {
        "value_emphasis", "capacity_overflow", "selection_sparsity",
    }


def test_each_spec_resolves_to_a_real_weight_and_metric():
    weights = _weights()
    metrics = _metrics()
    rows = build_goal_term_contributions(SPECS, [s.key for s in SPECS], weights, metrics)
    for row in rows:
        spec = next(s for s in SPECS if s.key == row["key"])
        assert row["weight"] == weights[spec.weight_key], f"{spec.key}: weight didn't bind"
        assert row["metric_value"] == metrics[spec.metric_key], f"{spec.key}: metric didn't bind"
        assert row["weighted_cost"] == row["weight"] * row["metric_value"]


def test_negative_weighted_cost_supported():
    """value_emphasis × negative value_term yields a cost-reducing contribution."""
    rows = build_goal_term_contributions(SPECS, ["value_emphasis"], _weights(), _metrics())
    assert rows[0]["weighted_cost"] == 1.0 * -42.5
