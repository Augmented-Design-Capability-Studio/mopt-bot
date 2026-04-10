"""MEALpy metaheuristic for binary knapsack (continuous [0,1] encoded)."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

import numpy as np

try:
    from mealpy import FloatVar, GA, PSO, SA, ACOR
except ImportError:
    FloatVar = GA = PSO = SA = ACOR = None

from knapsack_problem.evaluator import build_knapsack_weights, evaluate_selection
from knapsack_problem.instance import Item

EARLY_STOP_DEFAULT_PATIENCE = 20
EARLY_STOP_DEFAULT_EPSILON = 1e-4


class OptimizationCancelled(Exception):
    pass


def _default_algorithm_params(algorithm: str) -> dict:
    if algorithm == "GA":
        return {"pc": 0.9, "pm": 0.05}
    if algorithm == "PSO":
        return {"c1": 2.05, "c2": 2.05, "w": 0.4}
    if algorithm == "SA":
        return {"temp_init": 100, "cooling_rate": 0.99}
    if algorithm == "SWARMSA":
        return {
            "max_sub_iter": 5,
            "t0": 1000,
            "t1": 1,
            "move_count": 5,
            "mutation_rate": 0.1,
            "mutation_step_size": 0.1,
            "mutation_step_size_damp": 0.99,
        }
    if algorithm == "ACOR":
        return {"sample_count": 25, "intent_factor": 0.5, "zeta": 1.0}
    return {}


def solve(
    items: list[Item],
    capacity: int,
    panel_weights: dict[str, Any],
    only_active_terms: bool,
    algorithm: str,
    algorithm_params: dict[str, Any] | None,
    epochs: int,
    pop_size: int,
    random_seed: int,
    early_stop: bool,
    early_stop_patience: int,
    early_stop_epsilon: float,
    cancel_event: Optional[threading.Event] = None,
) -> tuple[float, np.ndarray, list[float], float, str]:
    if GA is None:
        raise ImportError("mealpy is required. Install with: pip install mealpy")

    wbuilt = build_knapsack_weights(panel_weights, only_active_terms)
    n = len(items)
    algo = algorithm.upper()
    if algo == "SWARMSA":
        algo = "SwarmSA"
    par = _default_algorithm_params(algo)
    if algorithm_params:
        par.update(algorithm_params)

    def obj_func(solution: np.ndarray) -> float:
        if cancel_event is not None and cancel_event.is_set():
            raise OptimizationCancelled()
        cost, _ = evaluate_selection(np.asarray(solution), items, capacity, wbuilt)
        return float(cost)

    bounds = FloatVar(lb=[0.0] * n, ub=[1.0] * n)
    problem = {
        "obj_func": obj_func,
        "bounds": bounds,
        "minmax": "min",
        "log_to": None,
    }

    t0 = time.perf_counter()
    if algo == "GA":
        model = GA.BaseGA(epoch=epochs, pop_size=pop_size, **{k: v for k, v in par.items() if k in ("pc", "pm")})
    elif algo == "PSO":
        model = PSO.OriginalPSO(
            epoch=epochs, pop_size=pop_size, **{k: v for k, v in par.items() if k in ("c1", "c2", "w")}
        )
    elif algo == "SA":
        model = SA.OriginalSA(
            epoch=epochs, pop_size=pop_size, **{k: v for k, v in par.items() if k in ("temp_init", "cooling_rate")}
        )
    elif algo == "SwarmSA":
        keys = (
            "max_sub_iter",
            "t0",
            "t1",
            "move_count",
            "mutation_rate",
            "mutation_step_size",
            "mutation_step_size_damp",
        )
        model = SA.SwarmSA(epoch=epochs, pop_size=pop_size, **{k: v for k, v in par.items() if k in keys})
    elif algo == "ACOR":
        model = ACOR.OriginalACOR(
            epoch=epochs, pop_size=pop_size, **{k: v for k, v in par.items() if k in ("sample_count", "intent_factor", "zeta")}
        )
    else:
        raise ValueError(f"Unknown algorithm: {algorithm}")

    termination = None
    if early_stop:
        termination = {
            "max_epoch": epochs,
            "max_early_stop": int(early_stop_patience),
            "epsilon": float(early_stop_epsilon),
        }

    solve_kw: dict[str, Any] = {"seed": random_seed, "mode": "single"}
    if termination is not None:
        solve_kw["termination"] = termination
    best = model.solve(problem, **solve_kw)
    runtime = time.perf_counter() - t0
    sol = np.asarray(best.solution)
    cost, _ = evaluate_selection(sol, items, capacity, wbuilt)
    convergence: list[float] = []
    if hasattr(model, "history") and model.history is not None and hasattr(model.history, "list_global_best_fit"):
        convergence = [float(f) for f in model.history.list_global_best_fit]
    return float(cost), sol, convergence, runtime, algo
