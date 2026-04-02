"""
Smoke tests for QuickBiteOptimizer + mealpy.

These tests cap function evaluations and keep population size moderate so runs stay
fast on low-end machines. They assert correctness and shape, not wall-clock speed.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("mealpy")

from optimizer import QuickBiteOptimizer

# Tight caps: fast everywhere; population must stay large enough for mealpy GA tournament logic.
FAST_SOLVE_KW = {
    "epochs": 3,
    "pop_size": 40,
    "termination": {"max_fe": 120},
}

# Expected vehicle count in this problem fixture.
N_VEHICLES = 5


@pytest.mark.parametrize(
    "algorithm",
    ["GA", "PSO", "SA", "SwarmSA", "ACOR"],
)
def test_algorithm_smoke(algorithm: str) -> None:
    """Each supported algorithm completes and returns a structurally valid result."""
    opt = QuickBiteOptimizer(seed=42)
    result = opt.solve(algorithm, **FAST_SOLVE_KW)

    assert result.algorithm == algorithm.upper()
    assert math.isfinite(result.best_cost)
    assert len(result.routes) == N_VEHICLES
    assert result.runtime >= 0.0


def test_ga_single_mode_is_deterministic() -> None:
    """Same seed and single-threaded mode → same best cost (not machine-specific)."""
    costs = []
    for _ in range(2):
        opt = QuickBiteOptimizer(seed=42)
        r = opt.solve("GA", mode="single", **FAST_SOLVE_KW)
        costs.append(r.best_cost)
    assert costs[0] == costs[1]


def test_ga_thread_mode_completes() -> None:
    """
    Parallel fitness (thread) runs without error; do not assert exact cost (ordering can differ).

    Note: omit n_workers so mealpy uses its default; some mealpy versions mis-handle explicit
    n_workers (logging typo in check_mode_and_workers).
    """
    opt = QuickBiteOptimizer(seed=42)
    result = opt.solve("GA", mode="thread", **FAST_SOLVE_KW)
    assert math.isfinite(result.best_cost)
    assert len(result.routes) == N_VEHICLES
