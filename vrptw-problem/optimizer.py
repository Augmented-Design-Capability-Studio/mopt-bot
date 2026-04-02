"""
MEALpy-based QuickBite optimizer.

Wraps GA, PSO, SA, SwarmSA, and ACOR algorithms for VRPTW solving.
"""

import threading
import time
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

try:
    from mealpy import FloatVar, GA, PSO, SA, ACOR
except ImportError:
    FloatVar = GA = PSO = SA = ACOR = None

from orders import get_orders, print_order_table
from encoder import decode_solution, VECTOR_LEN, encode_random_solution
from evaluator import evaluate_solution
from user_input import DEFAULT_WEIGHTS, load_user_input
from vehicles import VEHICLES



class OptimizationCancelled(Exception):
    """Raised when solve is stopped early (cooperative cancel)."""


@dataclass
class SolverConfig:
    """
    Configuration for the QuickBite solver.

    JSON-serializable (no numpy types, no callables).
    """

    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    locked_assignments: dict = field(default_factory=dict)
    algorithm: str = "GA"
    algorithm_params: Optional[dict] = None
    random_seed: int = 42
    epochs: int = 500
    pop_size: int = 100

    def to_dict(self) -> dict:
        """Return JSON-serializable dict."""
        return {
            "weights": {k: float(v) for k, v in self.weights.items()},
            "locked_assignments": {int(k): int(v) for k, v in self.locked_assignments.items()},
            "algorithm": str(self.algorithm),
            "algorithm_params": dict(self.algorithm_params) if self.algorithm_params else None,
            "random_seed": int(self.random_seed),
            "epochs": int(self.epochs),
            "pop_size": int(self.pop_size),
        }


@dataclass
class SolveResult:
    """Result of a solve run."""

    best_cost: float
    routes: list[list[int]]
    metrics: dict
    visits: list[list[Any]]  # visits_per_vehicle from final evaluate_solution
    convergence: list[float]
    runtime: float
    algorithm: str = ""
    epoch_times: Optional[list[float]] = None  # per-epoch wall time for time-based plots
    # Problem definition used (for reporter / research re-evaluation)
    weights: Optional[dict] = None
    driver_preferences: Optional[list] = None
    shift_hard_penalty: Optional[float] = None
    locked_assignments: Optional[dict] = None


def _default_algorithm_params(algorithm: str) -> dict:
    """Return default hyperparameters for each algorithm."""
    if algorithm == "GA":
        return {"pc": 0.9, "pm": 0.05}
    if algorithm == "PSO":
        return {"c1": 2.05, "c2": 2.05, "w": 0.4}
    if algorithm == "SA":
        return {"temp_init": 100, "cooling_rate": 0.99}
    if algorithm == "SWARMSA":
        return {"max_sub_iter": 5, "t0": 1000, "t1": 1, "move_count": 5,
                "mutation_rate": 0.1, "mutation_step_size": 0.1, "mutation_step_size_damp": 0.99}
    if algorithm == "ACOR":
        return {"sample_count": 25, "intent_factor": 0.5, "zeta": 1.0}
    return {}


class QuickBiteOptimizer:
    """
    Metaheuristic solver for QuickBite Fleet Scheduling VRPTW.

    Respects current user input (weights, driver preferences, constraints).
    Loads from user_input when config not explicitly provided.
    Supports GA, PSO, SA, SwarmSA, and ACOR via mealpy.
    """

    def __init__(
        self,
        weights: Optional[dict] = None,
        locked: Optional[dict[int, int]] = None,
        driver_preferences: Optional[list] = None,
        shift_hard_penalty: Optional[float] = None,
        seed: int = 42,
        user_config_path: Optional[Any] = None,
    ):
        """
        Initialize the optimizer.

        Args:
            weights: Optional weight dict (keys w1..w7). If None, load from user_input.
            locked: Optional {order_idx: vehicle_idx} locked assignments.
            driver_preferences: Optional list of rule dicts. If None, load from user_input.
            shift_hard_penalty: Optional. If None, load from user_input.
            seed: Random seed for reproducibility.
            user_config_path: Optional path to user config JSON.
        """
        config = load_user_input(user_config_path)
        self.weights = weights if weights is not None else config["weights"]
        self.locked = (
            locked
            if locked is not None
            else config.get("locked_assignments", {})
        )
        self.driver_preferences = (
            driver_preferences
            if driver_preferences is not None
            else config["driver_preferences"]
        )
        self.shift_hard_penalty = (
            shift_hard_penalty
            if shift_hard_penalty is not None
            else config["shift_hard_penalty"]
        )
        self.seed = seed
        self.rng = np.random.RandomState(seed)
        self.orders = get_orders(seed=None)

    def solve(
        self,
        algorithm: str = "GA",
        params: Optional[dict] = None,
        epochs: int = 500,
        pop_size: int = 100,
        termination: Optional[dict] = None,
        cancel_event: Optional[threading.Event] = None,
        mode: str = "single",
        n_workers: Optional[int] = None,
    ) -> SolveResult:
        """
        Run the optimization.

        Args:
            algorithm: One of "GA", "PSO", "SA", "SwarmSA", "ACOR".
            params: Optional algorithm-specific hyperparameters.
            epochs: Number of epochs (used when termination is None).
            pop_size: Population size (ignored for SA).
            termination: Optional mealpy termination dict, e.g. {"max_time": 60}
                or {"max_fe": 100000}. Overrides epoch limit when set.
            cancel_event: When set, checked before each objective evaluation; if set, raises OptimizationCancelled.
            mode: mealpy execution mode: single, swarm, thread, or process (see mealpy Optimizer.solve).
            n_workers: Worker count for thread/process modes; omit to use mealpy default (recommended for thread).

        Returns:
            SolveResult with best_cost, routes, metrics, convergence, runtime.
        """
        if GA is None:
            raise ImportError("mealpy is required. Install with: pip install mealpy")

        algo = algorithm.upper()
        par = dict(_default_algorithm_params(algo))
        if params:
            par.update(params)

        # Closure for objective
        rng = np.random.RandomState(self.seed)
        orders = self.orders
        weights = self.weights
        locked = self.locked
        driver_prefs = self.driver_preferences
        shift_penalty = self.shift_hard_penalty

        def obj_func(solution: np.ndarray) -> float:
            if cancel_event is not None and cancel_event.is_set():
                raise OptimizationCancelled()
            cost, _, _ = evaluate_solution(
                np.asarray(solution),
                orders,
                rng,
                weights,
                locked_assignments=locked,
                driver_preferences=driver_prefs,
                shift_hard_penalty=shift_penalty,
            )
            return float(cost)

        # Mealpy problem
        bounds = FloatVar(lb=[0.0] * VECTOR_LEN, ub=[34.0] * VECTOR_LEN)
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
            model = PSO.OriginalPSO(epoch=epochs, pop_size=pop_size, **{k: v for k, v in par.items() if k in ("c1", "c2", "w")})
        elif algo == "SA":
            model = SA.OriginalSA(epoch=epochs, pop_size=pop_size, **{k: v for k, v in par.items() if k in ("temp_init", "cooling_rate")})
        elif algo == "SWARMSA":
            swarmsa_keys = ("max_sub_iter", "t0", "t1", "move_count",
                            "mutation_rate", "mutation_step_size", "mutation_step_size_damp")
            model = SA.SwarmSA(epoch=epochs, pop_size=pop_size, **{k: v for k, v in par.items() if k in swarmsa_keys})
        elif algo == "ACOR":
            model = ACOR.OriginalACOR(epoch=epochs, pop_size=pop_size, **{k: v for k, v in par.items() if k in ("sample_count", "intent_factor", "zeta")})
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}. Use GA, PSO, SA, SwarmSA, or ACOR.")

        solve_kw: dict[str, Any] = {"seed": self.seed, "mode": mode}
        if termination is not None:
            solve_kw["termination"] = termination
        if n_workers is not None:
            solve_kw["n_workers"] = n_workers
        best = model.solve(problem, **solve_kw)
        runtime = time.perf_counter() - t0

        solution = np.asarray(best.solution)
        cost, metrics, visits = evaluate_solution(
            solution,
            orders,
            rng,
            weights,
            locked_assignments=locked,
            driver_preferences=driver_prefs,
            shift_hard_penalty=shift_penalty,
        )
        routes = decode_solution(solution, locked_assignments=locked)

        # Convergence history and per-epoch times
        convergence = []
        epoch_times = None
        if hasattr(model, "history") and model.history is not None:
            if hasattr(model.history, "list_global_best_fit"):
                convergence = [float(f) for f in model.history.list_global_best_fit]
            if hasattr(model.history, "list_epoch_time") and model.history.list_epoch_time:
                epoch_times = [float(t) for t in model.history.list_epoch_time]

        return SolveResult(
            best_cost=float(cost),
            routes=routes,
            metrics=metrics,
            visits=visits,
            convergence=convergence,
            runtime=runtime,
            algorithm=algo,
            weights=weights,
            driver_preferences=driver_prefs,
            shift_hard_penalty=shift_penalty,
            locked_assignments=locked,
            epoch_times=epoch_times,
        )
