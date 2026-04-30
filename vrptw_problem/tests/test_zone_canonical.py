"""Tests for canonical zone normalization."""

from __future__ import annotations

from vrptw_problem.study_bridge import parse_problem_config
from vrptw_problem.zone_canonical import normalize_delivery_zone


def test_zone_roundtrip_letter_number_name():
    assert normalize_delivery_zone("Depot") == 0
    assert normalize_delivery_zone("A") == 1
    assert normalize_delivery_zone("B") == 2
    assert normalize_delivery_zone("C") == 3
    assert normalize_delivery_zone("D") == 4
    assert normalize_delivery_zone("E") == 5
    assert normalize_delivery_zone("Westgate") == 4
    assert normalize_delivery_zone("Northgate") == 5


def test_parse_problem_config_accepts_zone_letter_and_name():
    cfg = parse_problem_config(
        {
            "weights": {"worker_preference": 5.0},
            "driver_preferences": [
                {"vehicle_idx": 0, "condition": "avoid_zone", "penalty": 2.0, "zone": "D"},
                {"vehicle_idx": 1, "condition": "avoid_zone", "penalty": 2.0, "zone": "Westgate"},
            ],
        }
    )
    prefs = cfg["driver_preferences"]
    assert prefs[0]["zone"] == 4
    assert prefs[1]["zone"] == 4
