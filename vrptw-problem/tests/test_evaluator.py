"""Tests for driver preference rules and shift duration units."""

import numpy as np
import pytest

from evaluator import simulate_routes
from orders import get_orders


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


def test_legacy_zone_d_matches_avoid_zone_d():
    orders = get_orders(seed=None)
    rng = np.random.RandomState(1)
    weights = {f"w{i}": 0.0 for i in range(1, 8)}
    weights["w6"] = 1.0
    legacy = [{"vehicle_idx": 0, "condition": "zone_d", "penalty": 5.0}]
    modern = [{"vehicle_idx": 0, "condition": "avoid_zone", "zone": 4, "penalty": 5.0}]
    _, a, _ = simulate_routes(_default_routes(), orders, rng, weights, driver_preferences=legacy)
    _, b, _ = simulate_routes(_default_routes(), orders, rng, weights, driver_preferences=modern)
    assert a["driver_penalty"] == b["driver_penalty"]


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
