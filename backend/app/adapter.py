"""
Thin adapter: neutral problem JSON ↔ vrptw-problem optimizer/evaluator.

Does not copy solver logic; imports from vrptw-problem with sys.path bootstrap.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any

import numpy as np

_VRPTW_ROOT = Path(__file__).resolve().parents[2] / "vrptw-problem"


def ensure_vrptw_on_path() -> Path:
    root = _VRPTW_ROOT.resolve()
    if not root.is_dir():
        raise RuntimeError(f"vrptw-problem not found at {root}")
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)
    return root


def neutral_violations(metrics: dict) -> dict[str, Any]:
    return {
        "time_window_minutes_over": float(metrics.get("tw_violation_min", 0)),
        "time_window_stop_count": int(metrics.get("tw_violation_count", 0)),
        "capacity_units_over": int(metrics.get("capacity_overflow", 0)),
        "shift_limit_penalty": float(metrics.get("shift_hard_penalty", 0)),
        "priority_deadline_misses": int(metrics.get("express_late_count", 0)),
    }


def _visits_from_evaluator_records(visits_per_vehicle: list) -> list[dict[str, Any]]:
    ensure_vrptw_on_path()
    from traffic_api import ZONE_NAMES

    out: list[dict[str, Any]] = []
    for v_idx, stops in enumerate(visits_per_vehicle):
        for rec in stops:
            try:
                ri = ZONE_NAMES.index(rec.zone)
            except ValueError:
                ri = 0
            oid = str(rec.order_id)
            task_index = int(oid[1:]) if oid.startswith("O") and oid[1:].isdigit() else None
            out.append(
                {
                    "vehicle_index": v_idx,
                    "task_id": oid,
                    "task_index": task_index,
                    "region_index": ri,
                    "arrival_minutes": float(rec.arrival_time),
                    "departure_minutes": float(rec.departure_time),
                    "window_open_minutes": int(rec.window_open),
                    "window_close_minutes": int(rec.window_close),
                    "priority_urgent": bool(rec.is_express),
                    "constraint_conflict": bool(rec.is_violation),
                }
            )
    return out


def routes_to_neutral(routes: list[list[int]]) -> list[dict[str, Any]]:
    return [
        {"vehicle_index": i, "task_indices": [int(x) for x in route]}
        for i, route in enumerate(routes)
    ]


def parse_problem_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize incoming neutral problem configuration."""
    ensure_vrptw_on_path()
    from user_input import DEFAULT_DRIVER_PREFERENCES, SHIFT_HARD_PENALTY, build_weights

    weights_in = raw.get("weights") or {}
    only_active = bool(raw.get("only_active_terms", False))
    weights = build_weights(weights_in, only_active_terms=only_active)

    driver_preferences = raw.get("driver_preferences")
    if driver_preferences is None:
        driver_preferences = list(DEFAULT_DRIVER_PREFERENCES)
    if not isinstance(driver_preferences, list):
        raise ValueError("driver_preferences must be a list")

    shift_hard = float(raw.get("shift_hard_penalty", SHIFT_HARD_PENALTY))

    locked: dict[int, int] = {}
    la = raw.get("locked_assignments") or {}
    for k, v in la.items():
        locked[int(k)] = int(v)

    algorithm = str(raw.get("algorithm", "GA")).strip().upper()
    algo_norm = "SwarmSA" if algorithm == "SWARMSA" else algorithm
    allowed = {"GA", "PSO", "SA", "SwarmSA", "ACOR"}
    if algo_norm not in allowed:
        raise ValueError(f"Unknown algorithm: use one of {sorted(allowed)}")

    epochs = int(raw.get("epochs", 500))
    pop_size = int(raw.get("pop_size", 100))
    if epochs < 1 or epochs > 50000:
        raise ValueError("epochs must be between 1 and 50000")
    if pop_size < 2 or pop_size > 500:
        raise ValueError("pop_size must be between 2 and 500")

    random_seed = int(raw.get("random_seed", 42))
    algorithm_params = raw.get("algorithm_params")
    if algorithm_params is not None and not isinstance(algorithm_params, dict):
        raise ValueError("algorithm_params must be an object or null")

    ref_weights = raw.get("reference_weights")
    if ref_weights is not None:
        if not isinstance(ref_weights, dict):
            raise ValueError("reference_weights must be an object or null")
        ref_weights = build_weights(
            ref_weights,
            only_active_terms=raw.get("reference_only_active_terms", False),
        )

    return {
        "weights": weights,
        "driver_preferences": driver_preferences,
        "shift_hard_penalty": shift_hard,
        "locked_assignments": locked,
        "algorithm": algo_norm,
        "algorithm_params": algorithm_params,
        "epochs": epochs,
        "pop_size": pop_size,
        "random_seed": random_seed,
        "reference_weights": ref_weights,
    }


def run_optimize(cfg: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    ensure_vrptw_on_path()
    from evaluator import simulate_routes
    from orders import get_orders
    from optimizer import QuickBiteOptimizer

    def _work():
        opt = QuickBiteOptimizer(
            weights=cfg["weights"],
            locked=cfg["locked_assignments"],
            driver_preferences=cfg["driver_preferences"],
            shift_hard_penalty=cfg["shift_hard_penalty"],
            seed=cfg["random_seed"],
        )
        return opt.solve(
            algorithm=cfg["algorithm"],
            params=cfg["algorithm_params"],
            epochs=cfg["epochs"],
            pop_size=cfg["pop_size"],
        )

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_work)
        try:
            result = fut.result(timeout=timeout_sec)
        except FuturesTimeout:
            raise TimeoutError("Optimization exceeded time limit") from None

    orders = get_orders(seed=None)
    rng_visits = np.random.RandomState(cfg["random_seed"])
    _, _, visits_pv = simulate_routes(
        result.routes,
        orders,
        rng_visits,
        cfg["weights"],
        driver_preferences=cfg["driver_preferences"],
        shift_hard_penalty=cfg["shift_hard_penalty"],
    )
    visits = _visits_from_evaluator_records(visits_pv)

    metrics = result.metrics
    neutral_metrics = {
        "total_travel_minutes": float(metrics.get("travel_time", 0)),
        "fuel_proxy_minutes": float(metrics.get("fuel_cost", 0)),
        "workload_variance": float(metrics.get("workload_variance", 0)),
        "driver_preference_penalty": float(metrics.get("driver_penalty", 0)),
    }

    ref_cost = None
    if cfg.get("reference_weights"):
        rng_ref = np.random.RandomState(cfg["random_seed"] + 1000)
        rc, _, _ = simulate_routes(
            result.routes,
            orders,
            rng_ref,
            cfg["reference_weights"],
            driver_preferences=cfg["driver_preferences"],
            shift_hard_penalty=cfg["shift_hard_penalty"],
        )
        ref_cost = float(rc)

    return {
        "cost": float(result.best_cost),
        "reference_cost": ref_cost,
        "schedule": {
            "routes": routes_to_neutral(result.routes),
            "stops": visits,
        },
        "violations": neutral_violations(metrics),
        "metrics": neutral_metrics,
        "runtime_seconds": float(result.runtime),
        "algorithm": result.algorithm,
        "convergence": result.convergence[:200] if result.convergence else [],
    }


def run_evaluate_routes(
    routes: list[list[int]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    ensure_vrptw_on_path()
    from evaluator import simulate_routes
    from orders import get_orders

    if len(routes) != 5:
        raise ValueError("schedule must contain exactly 5 vehicle routes")
    orders = get_orders(seed=None)
    all_idx: set[int] = set()
    for r in routes:
        for o in r:
            all_idx.add(int(o))
    expected = set(range(30))
    if all_idx != expected:
        raise ValueError("Each task index 0..29 must appear exactly once across routes")

    rng = np.random.RandomState(cfg["random_seed"])
    cost, metrics, visits_pv = simulate_routes(
        routes,
        orders,
        rng,
        cfg["weights"],
        driver_preferences=cfg["driver_preferences"],
        shift_hard_penalty=cfg["shift_hard_penalty"],
    )
    visits = _visits_from_evaluator_records(visits_pv)
    ref_cost = None
    if cfg.get("reference_weights"):
        rng2 = np.random.RandomState(cfg["random_seed"] + 1000)
        rc, _, _ = simulate_routes(
            routes,
            orders,
            rng2,
            cfg["reference_weights"],
            driver_preferences=cfg["driver_preferences"],
            shift_hard_penalty=cfg["shift_hard_penalty"],
        )
        ref_cost = float(rc)

    neutral_metrics = {
        "total_travel_minutes": float(metrics.get("travel_time", 0)),
        "fuel_proxy_minutes": float(metrics.get("fuel_cost", 0)),
        "workload_variance": float(metrics.get("workload_variance", 0)),
        "driver_preference_penalty": float(metrics.get("driver_penalty", 0)),
    }

    return {
        "cost": float(cost),
        "reference_cost": ref_cost,
        "schedule": {
            "routes": routes_to_neutral(routes),
            "stops": visits,
        },
        "violations": neutral_violations(metrics),
        "metrics": neutral_metrics,
        "runtime_seconds": 0.0,
        "algorithm": "evaluate",
        "convergence": [],
    }


def solve_request_to_result(body: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    cfg = parse_problem_config(body.get("problem") or body)
    run_type = (body.get("type") or "optimize").lower()
    if run_type == "evaluate":
        routes = body.get("routes")
        if not routes or not isinstance(routes, list):
            raise ValueError("evaluate requires routes: list of 5 lists of task indices")
        routes = [[int(x) for x in row] for row in routes]
        return run_evaluate_routes(routes, cfg)
    return run_optimize(cfg, timeout_sec)
