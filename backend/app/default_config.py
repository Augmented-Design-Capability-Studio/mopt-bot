"""Default neutral panel configuration for new sessions."""

DEFAULT_PANEL_CONFIG: dict = {
    "problem": {
        "weights": {
            "w1": 1.0,
            "w2": 0.15,
            "w3": 50.0,
            "w4": 1000.0,
            "w5": 10.0,
            "w6": 1.0,
            "w7": 100.0,
        },
        "only_active_terms": False,
        "algorithm": "GA",
        "epochs": 80,
        "pop_size": 40,
        "random_seed": 42,
    }
}
