"""Default neutral panel configuration for new sessions.

VRPTW weight keys use human-readable aliases (see ``vrptw_study_bridge`` / ``app.adapter``).
"""

from copy import deepcopy

# Canonical default weights using participant-visible alias names.
_PROBLEM_WEIGHTS: dict = {
    "travel_time":       1.0,
    "shift_limit":       5.0,
    "deadline_penalty":  50.0,
    "capacity_penalty":  1000.0,
    "workload_balance":  10.0,
    "worker_preference": 1.0,
    "priority_penalty":  100.0,
}

DEFAULT_PANEL_CONFIG: dict = {
    "problem": {
        "weights": dict(_PROBLEM_WEIGHTS),
        "only_active_terms": True,
        "algorithm": "GA",
        "epochs": 80,
        "pop_size": 40,
        "random_seed": 42,
    }
}

# Deliberately sparse, mediocre starter that should still leave obvious room for improvement.
MEDIOCRE_PARTICIPANT_STARTER_CONFIG: dict = {
    "problem": {
        "weights": {
            "travel_time": 1.0,
            "workload_balance": 4.0,
        },
        "only_active_terms": True,
        "algorithm": "SA",
        "algorithm_params": {"temp_init": 40, "cooling_rate": 0.92},
        "epochs": 18,
        "pop_size": 12,
        "random_seed": 42,
    }
}

MEDIOCRE_KNAPSACK_PARTICIPANT_STARTER_CONFIG: dict = {
    "problem": {
        "weights": {
            "value_emphasis": 1.0,
            "capacity_overflow": 40.0,
        },
        "only_active_terms": True,
        "algorithm": "GA",
        "epochs": 24,
        "pop_size": 16,
        "random_seed": 42,
    }
}


def mediocre_participant_starter_config(test_problem_id: str | None = None) -> dict:
    pid = (test_problem_id or "vrptw").strip().lower()
    if pid == "knapsack":
        return deepcopy(MEDIOCRE_KNAPSACK_PARTICIPANT_STARTER_CONFIG)
    return deepcopy(MEDIOCRE_PARTICIPANT_STARTER_CONFIG)
