"""Tests for driver preference rules and shift duration units."""

import numpy as np
import pytest

from vrptw_problem.evaluator import simulate_routes
from vrptw_problem.orders import get_orders


def _default_routes():
    return [
        list(range(0, 6)),
        list(range(6, 12)),
        list(range(12, 18)),
        list(range(18, 24)),
        list(range(24, 30)),
    ]


def test_shift_durations_are_minutes():
    orders = get_orders(seed=None)
    rng = np.random.RandomState(42)
    weights = {f"w{i}": 0.0 for i in range(1, 8)}
    _, metrics, _ = simulate_routes(_default_routes(), orders, rng, weights, driver_preferences=[])
    sds = metrics["shift_durations"]
    assert len(sds) == 5
    for sd in sds:
        assert sd < 24 * 60
        assert sd > 0


def test_metrics_include_shift_overtime_minutes():
    orders = get_orders(seed=None)
    rng = np.random.RandomState(42)
    weights = {f"w{i}": 0.0 for i in range(1, 8)}
    _, metrics, _ = simulate_routes(_default_routes(), orders, rng, weights, driver_preferences=[])
    assert "shift_overtime_minutes" in metrics
    assert metrics["shift_overtime_minutes"] >= 0
    assert "fuel_cost" not in metrics


def test_two_avoid_zone_rules_different_vehicles():
    orders = get_orders(seed=None)
    rng = np.random.RandomState(0)
    weights = {f"w{i}": 0.0 for i in range(1, 8)}
    weights["w6"] = 1.0
    prefs = [
        {"vehicle_idx": 0, "condition": "avoid_zone", "zone": 4, "penalty": 3.0},
        {"vehicle_idx": 1, "condition": "avoid_zone", "zone": 4, "penalty": 7.0},
    ]
    _, m1, _ = simulate_routes(_default_routes(), orders, rng, weights, driver_preferences=prefs)
    _, m0, _ = simulate_routes(_default_routes(), orders, rng, weights, driver_preferences=[])
    assert m1["driver_penalty"] >= m0["driver_penalty"]


def test_shift_over_limit_minutes():
    orders = get_orders(seed=None)
    rng = np.random.RandomState(2)
    weights = {f"w{i}": 0.0 for i in range(1, 8)}
    weights["w6"] = 1.0
    prefs = [
        {"vehicle_idx": 0, "condition": "shift_over_limit", "limit_minutes": 1.0, "penalty": 100.0},
    ]
    _, m, _ = simulate_routes(_default_routes(), orders, rng, weights, driver_preferences=prefs)
    assert m["driver_penalty"] >= 100.0


def test_visit_records_preference_penalty_units_per_stop():
    """Per-visit preference units appear on stops when avoid_zone fires (any vehicle/route)."""
    orders = get_orders(seed=None)
    rng = np.random.RandomState(3)
    weights = {f"w{i}": 0.0 for i in range(1, 8)}
    weights["w6"] = 1.0
    prefs = [
        {"vehicle_idx": 0, "condition": "avoid_zone", "zone": 4, "penalty": 2.5},
        {"vehicle_idx": 1, "condition": "avoid_zone", "zone": 4, "penalty": 2.5},
    ]
    _, _, visits = simulate_routes(_default_routes(), orders, rng, weights, driver_preferences=prefs)
    hits = [v for route in visits for v in route if getattr(v, "preference_penalty_units", 0) > 0]
    assert len(hits) >= 1
