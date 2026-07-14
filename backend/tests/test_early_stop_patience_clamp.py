"""A run must never hard-fail on plateau-tuning knobs it may not even use.

Regression for session-8745c964 (knapsack tutorial): the panel derive left
`early_stop_patience=0` in the config while `early_stop=False`. The panel schema
permits any integer, but the run validator rejected `<1` unconditionally, so
Runs #3–5 crashed with "early_stop_patience must be between 1 and 5000" even
though the solver ignores patience while early stopping is off. Both ports now
clamp instead of raising, symmetrically.
"""

import pytest

from app.problems.registry import get_study_port

_BASE = {
    "knapsack": {"weights": {"value_emphasis": 1.0, "capacity_overflow": 100.0}},
    "vrptw": {"weights": {"travel_time": 1.0}},
}


def _cfg(problem_id: str, **overrides):
    raw = {
        **_BASE[problem_id],
        "algorithm": "GA",
        "epochs": 100,
        "pop_size": 50,
        **overrides,
    }
    return get_study_port(problem_id).parse_problem_config(raw)


@pytest.mark.parametrize("problem_id", ["knapsack", "vrptw"])
def test_zero_patience_with_early_stop_off_does_not_crash(problem_id):
    # The exact shape that failed in the archive: early_stop off, patience 0.
    cfg = _cfg(problem_id, early_stop=False, early_stop_patience=0, early_stop_epsilon=0.001)
    assert cfg["early_stop"] is False
    assert cfg["early_stop_patience"] == 1  # clamped up into range, no raise


@pytest.mark.parametrize("problem_id", ["knapsack", "vrptw"])
def test_out_of_range_patience_clamps_to_bounds(problem_id):
    assert _cfg(problem_id, early_stop=True, early_stop_patience=9999)["early_stop_patience"] == 5000
    assert _cfg(problem_id, early_stop=True, early_stop_patience=0)["early_stop_patience"] == 1


@pytest.mark.parametrize("problem_id", ["knapsack", "vrptw"])
def test_nonpositive_epsilon_falls_back_to_default(problem_id):
    cfg = _cfg(problem_id, early_stop_epsilon=0.0)
    assert cfg["early_stop_epsilon"] > 0
