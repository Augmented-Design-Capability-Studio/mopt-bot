"""Smoke test: VRPTW SPECS table feeds the shared builder correctly.

Generic filter / coercion / arithmetic behaviour is covered by
``backend/tests/test_cost_breakdown.py``.  This file just pins each VRPTW
alias to the right (weight key, metric key) pair so the cost line in
``vrptw_problem/evaluator.py:simulate_routes`` stays in sync with the breakdown.
"""

from __future__ import annotations

from app.problems.cost_breakdown import build_goal_term_contributions
from vrptw_problem.cost_breakdown import SPECS


def _full_metrics() -> dict[str, float]:
    return {
        "travel_time": 120.5,
        "shift_overtime_minutes": 30.0,
        "tw_violation_min": 12.0,
        "capacity_overflow": 4,
        "workload_variance": 2.1,
        "driver_penalty": 8.0,
        "express_late_count": 2,
        "wait_time": 5.0,
    }


def _full_weights() -> dict[str, float]:
    return {f"w{i}": float(i) for i in range(1, 9)}


def test_spec_keys_cover_all_eight_vrptw_terms():
    assert {s.key for s in SPECS} == {
        "travel_time", "shift_limit", "lateness_penalty", "capacity_penalty",
        "workload_balance", "worker_preference", "express_miss_penalty", "waiting_time",
    }


def test_each_spec_resolves_to_a_real_weight_and_metric():
    """Catches typos in SPECS (a wrong wN or metric key would silently emit zeros)."""
    weights = _full_weights()
    metrics = _full_metrics()
    rows = build_goal_term_contributions(SPECS, [s.key for s in SPECS], weights, metrics)
    for row in rows:
        spec = next(s for s in SPECS if s.key == row["key"])
        assert row["weight"] == weights[spec.weight_key], f"{spec.key}: weight didn't bind"
        assert row["metric_value"] == metrics[spec.metric_key], f"{spec.key}: metric didn't bind"
        assert row["weighted_cost"] == row["weight"] * row["metric_value"]
