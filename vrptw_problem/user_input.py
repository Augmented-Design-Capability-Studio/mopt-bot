"""
User-specified objective weights, driver preferences, and constraints.

Designed to be loaded from JSON for the chatbot interface. Supports partial
specifications, hard vs soft constraints, and locked_assignments.
"""

import json
from pathlib import Path
from typing import Any, Optional

# All supported weight keys (w1..w7) — soft constraint terms
WEIGHT_KEYS = ["w1", "w2", "w3", "w4", "w5", "w6", "w7"]

# Default objective weights (all 7 terms)
DEFAULT_WEIGHTS = {
    "w1": 1.0,      # total travel time
    "w2": 500.0,      # per minute over configurable max shift, summed across vehicles — panel alias `shift_limit`
    "w3": 50.0,     # per minute TW violation
    "w4": 1000.0,   # per unit capacity overflow
    "w5": 10.0,     # workload variance
    "w6": 1.0,      # driver preference penalties
    "w7": 100.0,    # per express order late
}

# Driver preference rules (preference cost units before w6; not travel-time minutes):
# Legacy: zone_d, express_order, shift_over_hours
# General: avoid_zone + zone (1–5), order_priority, shift_over_limit + limit_minutes
DEFAULT_DRIVER_PREFERENCES = [
    {"vehicle_idx": 0, "condition": "zone_d", "penalty": 8},
    {"vehicle_idx": 2, "condition": "express_order", "penalty": 5},
    {"vehicle_idx": 3, "condition": "shift_over_hours", "hours": 6.5, "penalty": 15},
]

# Base platform constraints (unless overridden by problem configuration)
DEFAULT_MAX_SHIFT_HOURS = 8.0  # hours

DEFAULT_USER_CONFIG_PATH = Path(__file__).parent / "data" / "user_config.json"


def build_weights(
    user_weights: dict,
    only_active_terms: bool = False,
) -> dict[str, float]:
    """
    Build a complete weight dict for the evaluator.

    Args:
        user_weights: User-provided weights (may be partial, e.g. 3 terms).
        only_active_terms: If True, keys not in user_weights get 0.
            If False, keys not in user_weights get DEFAULT_WEIGHTS value.

    Returns:
        Dict with all WEIGHT_KEYS, values as float.
    """
    base = {k: 0.0 for k in WEIGHT_KEYS} if only_active_terms else dict(DEFAULT_WEIGHTS)
    for k in WEIGHT_KEYS:
        if k in user_weights:
            base[k] = float(user_weights[k])
    return base


def _parse_locked_assignments(obj: Any) -> dict[int, int]:
    """Convert JSON dict (str keys) to {int: int}."""
    if not obj:
        return {}
    return {int(k): int(v) for k, v in obj.items()}


def _infer_constraint_definitions(
    weights: dict,
    locked_assignments: dict,
    driver_preferences: list,
) -> tuple[list[str], list[str]]:
    """
    Infer which constraints the user defined based on what they specified.

    Returns (hard_constraints, soft_constraints) as lists of constraint names.
    """
    hard = []
    soft = []
    if locked_assignments:
        hard.append("locked_assignments")
    w_to_name = {
        "w1": "travel_time",
        "w2": "shift_limit",
        "w3": "tw_violation",
        "w4": "capacity",
        "w5": "workload",
        "w6": "driver_prefs",
        "w7": "express_lateness",
    }
    for k, v in weights.items():
        if v and v != 0 and k in w_to_name:
            soft.append(w_to_name[k])
    if driver_preferences and "driver_prefs" not in soft and any(w for w in [weights.get("w6", 0)] if w):
        soft.append("driver_prefs")
    return hard, soft


def load_user_input(path: Optional[Path] = None) -> dict[str, Any]:
    """
    Load user config from JSON file. Returns defaults if file not found.

    Expected JSON structure:
    {
        "weights": {"w1": 1.0, "w3": 80.0, "w5": 10.0},
        "only_active_terms": true,
        "max_shift_hours": 8.0,
        "driver_preferences": [...],
        "locked_assignments": {"5": 0},
        "algorithm": "GA",
        "algorithm_params": {"pc": 0.9, "pm": 0.05},
        "epochs": 500,
        "pop_size": 100,
        "hard_constraints": ["locked_assignments"],
        "soft_constraints": ["tw_violation", "capacity", "shift_limit"]
    }

    Supported algorithms: GA, PSO, SA, SwarmSA, ACOR. algorithm, algorithm_params, epochs, pop_size optional.

    Returns:
        Dict with: weights, driver_preferences, shift_hard_penalty,
        locked_assignments, algorithm, epochs, pop_size,
        hard_constraints, soft_constraints
    """
    p = path if path is not None else DEFAULT_USER_CONFIG_PATH
    if p.exists():
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        only_active = data.get("only_active_terms", False)
        user_weights = data.get("weights", {})
        driver_prefs = data.get("driver_preferences", [])
        locked = _parse_locked_assignments(data.get("locked_assignments", {}))
        weights = build_weights(user_weights, only_active_terms=only_active)

        hard = data.get("hard_constraints")
        soft = data.get("soft_constraints")
        if hard is None or soft is None:
            hard, soft = _infer_constraint_definitions(
                weights, locked, driver_prefs
            )

        return {
            "weights": weights,
            "max_shift_hours": data.get("max_shift_hours", DEFAULT_MAX_SHIFT_HOURS),
            "driver_preferences": driver_prefs,
            "locked_assignments": locked,
            "algorithm": data.get("algorithm", "GA"),
            "algorithm_params": data.get("algorithm_params"),
            "epochs": data.get("epochs", 500),
            "pop_size": data.get("pop_size", 100),
            "hard_constraints": hard or [],
            "soft_constraints": soft or [],
        }
    return {
        "weights": dict(DEFAULT_WEIGHTS),
        "max_shift_hours": DEFAULT_MAX_SHIFT_HOURS,
        "driver_preferences": [],
        "locked_assignments": {},
        "algorithm": "GA",
        "algorithm_params": None,
        "epochs": 500,
        "pop_size": 100,
        "hard_constraints": [],
        "soft_constraints": [
            "travel_time",
            "shift_limit",
            "tw_violation",
            "capacity",
            "workload",
            "driver_prefs",
            "express_lateness",
        ],
    }


def get_weights(path: Optional[Path] = None) -> dict:
    """Return objective weights (from file or defaults)."""
    return load_user_input(path)["weights"]


def get_driver_preferences(path: Optional[Path] = None) -> list[dict]:
    """Return driver preference rules (from file or defaults)."""
    return load_user_input(path)["driver_preferences"]
