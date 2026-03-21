"""Default neutral panel configuration for new sessions.

Weight keys use human-readable aliases (see adapter.WEIGHT_ALIASES).
The adapter translates them to w1–w7 before calling the solver.
"""

# Canonical default weights using participant-visible alias names.
_PROBLEM_WEIGHTS: dict = {
    "travel_time":       1.0,
    "fuel_cost":         0.15,
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

# Weaker GA settings for a deliberate "starter" the researcher pushes to the participant.
MEDIOCRE_PARTICIPANT_STARTER_CONFIG: dict = {
    "problem": {
        "weights": dict(_PROBLEM_WEIGHTS),
        "only_active_terms": True,
        "algorithm": "GA",
        "epochs": 35,
        "pop_size": 20,
        "random_seed": 42,
    }
}
