"""Default neutral panel configuration for new sessions."""

_PROBLEM_WEIGHTS: dict = {
    "w1": 1.0,
    "w2": 0.15,
    "w3": 50.0,
    "w4": 1000.0,
    "w5": 10.0,
    "w6": 1.0,
    "w7": 100.0,
}

DEFAULT_PANEL_CONFIG: dict = {
    "problem": {
        "weights": dict(_PROBLEM_WEIGHTS),
        "only_active_terms": False,
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
        "only_active_terms": False,
        "algorithm": "GA",
        "epochs": 35,
        "pop_size": 20,
        "random_seed": 42,
    }
}
