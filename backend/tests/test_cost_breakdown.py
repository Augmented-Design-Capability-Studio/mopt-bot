"""Tests for the shared cost-breakdown helper.

Per-problem spec tables are exercised separately in
``vrptw_problem/tests/test_cost_breakdown.py`` and
``knapsack_problem/tests/test_knapsack_cost_breakdown.py``; this file pins the
generic filtering / coercion / arithmetic behaviour so problems can rely on it.
"""

from __future__ import annotations

from app.problems.cost_breakdown import CostTermSpec, build_goal_term_contributions


_SPECS = (
    CostTermSpec("alpha", "Alpha", "wA", "metric_a", "min"),
    CostTermSpec("beta",  "Beta",  "wB", "metric_b", "units"),
    CostTermSpec("gamma", "Gamma", "wC", "metric_c", ""),
)


def test_filters_to_submitted_aliases_only():
    rows = build_goal_term_contributions(
        _SPECS,
        ["alpha", "gamma"],
        {"wA": 2.0, "wB": 3.0, "wC": 4.0},
        {"metric_a": 10.0, "metric_b": 20.0, "metric_c": 30.0},
    )
    assert {r["key"] for r in rows} == {"alpha", "gamma"}


def test_empty_submitted_aliases_yields_empty_list():
    assert build_goal_term_contributions(_SPECS, [], {}, {}) == []


def test_weighted_cost_equals_weight_times_metric():
    rows = build_goal_term_contributions(
        _SPECS, ["beta"], {"wB": 3.0}, {"metric_b": 20.0}
    )
    assert rows == [{
        "key": "beta",
        "label": "Beta",
        "weight": 3.0,
        "metric_value": 20.0,
        "metric_unit": "units",
        "weighted_cost": 60.0,
    }]


def test_zero_weight_row_still_emitted():
    rows = build_goal_term_contributions(
        _SPECS, ["alpha"], {"wA": 0.0}, {"metric_a": 10.0}
    )
    assert len(rows) == 1
    assert rows[0]["weight"] == 0.0
    assert rows[0]["weighted_cost"] == 0.0


def test_unknown_alias_silently_ignored():
    rows = build_goal_term_contributions(
        _SPECS, ["alpha", "not_a_term"], {"wA": 1.0}, {"metric_a": 5.0}
    )
    assert {r["key"] for r in rows} == {"alpha"}


def test_missing_weight_or_metric_coerces_to_zero():
    rows = build_goal_term_contributions(
        _SPECS, ["alpha", "beta"], {"wA": 1.0}, {"metric_b": 7.0}
    )
    by_key = {r["key"]: r for r in rows}
    assert by_key["alpha"]["weighted_cost"] == 0.0  # missing metric → 0
    assert by_key["beta"]["weighted_cost"] == 0.0   # missing weight → 0


def test_non_numeric_input_coerces_to_zero():
    rows = build_goal_term_contributions(
        _SPECS, ["alpha"], {"wA": "garbage"}, {"metric_a": None}
    )
    assert rows[0]["weight"] == 0.0
    assert rows[0]["metric_value"] == 0.0
