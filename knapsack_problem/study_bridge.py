"""Knapsack parse/solve bridge for the study backend (use ``vrptw_*`` / ``knapsack_*`` prefixed modules to avoid sys.path clashes)."""

from __future__ import annotations

from typing import Any, Callable

from app.algorithm_catalog import DEFAULT_EPOCHS, DEFAULT_POP_SIZE
import numpy as np

_EARLY_STOP_PATIENCE = 20
_EARLY_STOP_EPSILON = 1e-4


def _apply_goal_terms_overlay(raw_problem: dict[str, Any]) -> dict[str, Any]:
    out = dict(raw_problem)
    goal_terms = out.get("goal_terms")
    if not isinstance(goal_terms, dict):
        return out
    weights: dict[str, float] = {}
    for key, entry in goal_terms.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        if "weight" not in entry:
            continue
        try:
            weights[key] = float(entry.get("weight"))
        except (TypeError, ValueError):
            continue
    if weights:
        out["weights"] = weights
    return out


def parse_problem_config(
    raw: dict[str, Any],
    *,
    filter_algorithm_params: Callable[[str, Any], tuple[dict[str, Any] | None, list[str]]],
) -> dict[str, Any]:
    from knapsack_problem.evaluator import build_knapsack_weights

    from knapsack_problem.evaluator import WEIGHT_KEYS as _KS_WEIGHT_KEYS

    raw = _apply_goal_terms_overlay(raw if isinstance(raw, dict) else {})
    weight_warnings: list[str] = []
    only_active = bool(raw.get("only_active_terms", True))
    wraw = raw.get("weights") or {}
    if not isinstance(wraw, dict):
        raise ValueError("weights must be an object")
    user_weights = {k: float(v) for k, v in wraw.items() if isinstance(v, (int, float))}
    weights = build_knapsack_weights(user_weights, only_active)
    # Aliases the participant actually submitted; used to filter the cost-breakdown
    # rows so participants never see terms they didn't configure.
    submitted_weight_aliases = sorted(k for k in user_weights if k in _KS_WEIGHT_KEYS)

    algorithm = str(raw.get("algorithm", "GA")).strip().upper()
    algo_norm = "SwarmSA" if algorithm == "SWARMSA" else algorithm
    allowed = {"GA", "PSO", "SA", "SwarmSA", "ACOR"}
    if algo_norm not in allowed:
        raise ValueError(f"Unknown algorithm: use one of {sorted(allowed)}")

    epochs = int(raw.get("epochs", DEFAULT_EPOCHS))
    pop_size = int(raw.get("pop_size", DEFAULT_POP_SIZE))
    if epochs < 1 or epochs > 50000:
        raise ValueError("epochs must be between 1 and 50000")
    if pop_size < 2 or pop_size > 500:
        raise ValueError("pop_size must be between 2 and 500")

    random_seed = int(raw.get("random_seed", 42))
    algorithm_params_raw = raw.get("algorithm_params")
    if algorithm_params_raw is not None and not isinstance(algorithm_params_raw, dict):
        raise ValueError("algorithm_params must be an object or null")

    algorithm_params_filtered, ap_warnings = filter_algorithm_params(algo_norm, algorithm_params_raw)
    weight_warnings.extend(ap_warnings)

    early_stop = raw.get("early_stop", True)
    if not isinstance(early_stop, bool):
        raise ValueError("early_stop must be a boolean")

    es_patience_raw = raw.get("early_stop_patience")
    early_stop_patience = int(es_patience_raw) if es_patience_raw is not None else _EARLY_STOP_PATIENCE
    if early_stop_patience < 1 or early_stop_patience > 5000:
        raise ValueError("early_stop_patience must be between 1 and 5000")

    es_eps_raw = raw.get("early_stop_epsilon")
    early_stop_epsilon = float(es_eps_raw) if es_eps_raw is not None else _EARLY_STOP_EPSILON
    if early_stop_epsilon <= 0:
        raise ValueError("early_stop_epsilon must be > 0")

    return {
        "weights": weights,
        "submitted_weight_aliases": submitted_weight_aliases,
        "only_active_terms": only_active,
        "algorithm": algo_norm,
        "algorithm_params": algorithm_params_filtered,
        "epochs": epochs,
        "pop_size": pop_size,
        "random_seed": random_seed,
        "early_stop": early_stop,
        "early_stop_patience": early_stop_patience,
        "early_stop_epsilon": early_stop_epsilon,
        "weight_warnings": weight_warnings,
    }


def solve_request_to_result(
    body: dict[str, Any],
    timeout_sec: float,
    cancel_event: Any | None,
    *,
    filter_algorithm_params: Callable[[str, Any], tuple[dict[str, Any] | None, list[str]]],
) -> dict[str, Any]:
    from app.problems.cost_breakdown import build_goal_term_contributions
    from knapsack_problem.cost_breakdown import SPECS as COST_TERM_SPECS
    from knapsack_problem.evaluator import evaluate_selection
    from knapsack_problem.instance import get_items
    from knapsack_problem.mealpy_solve import OptimizationCancelled, solve

    run_type = (body.get("type") or "optimize").lower()
    if run_type == "evaluate":
        raise ValueError("Knapsack benchmark does not support evaluate-from-routes yet")

    cfg = parse_problem_config(body.get("problem") or body, filter_algorithm_params=filter_algorithm_params)
    weight_warnings: list[str] = cfg.pop("weight_warnings", [])
    items, capacity = get_items(seed=0)
    try:
        cost, sol, convergence, runtime, algo = solve(
            items,
            capacity,
            cfg["weights"],
            cfg["only_active_terms"],
            cfg["algorithm"],
            cfg["algorithm_params"],
            cfg["epochs"],
            cfg["pop_size"],
            cfg["random_seed"],
            cfg["early_stop"],
            cfg["early_stop_patience"],
            cfg["early_stop_epsilon"],
            cancel_event=cancel_event,
        )
    except OptimizationCancelled:
        raise

    _, metrics = evaluate_selection(sol, items, capacity, cfg["weights"])
    sel = (np.asarray(sol, dtype=float).ravel() >= 0.5).astype(int)
    payload_items = [
        {
            "id": it.index,
            "weight": it.weight,
            "value": it.value,
            "selected": bool(sel[it.index]),
        }
        for it in items
    ]
    result = {
        "cost": float(cost),
        "reference_cost": None,
        "schedule": {
            "routes": [],
            "stops": [],
            "vehicle_summaries": [],
            "time_bounds": {"start_minutes": 0, "end_minutes": 0},
        },
        "violations": {
            "time_window_minutes_over": 0,
            "time_window_stop_count": 0,
            "capacity_units_over": int(metrics["overflow"] > 0),
            "priority_deadline_misses": 0,
        },
        "metrics": {
            "total_travel_minutes": 0.0,
            "shift_overtime_minutes": 0.0,
            "workload_variance": float(metrics["total_weight"]),
            "driver_preference_units": float(metrics["selected_count"]),
            "driver_preference_penalty": 0.0,
            "knapsack_overflow": float(metrics["overflow"]),
            "knapsack_feasible": bool(metrics["feasible"]),
        },
        "goal_term_contributions": build_goal_term_contributions(
            COST_TERM_SPECS,
            cfg.get("submitted_weight_aliases") or [],
            cfg["weights"],
            metrics,
        ),
        "runtime_seconds": float(runtime),
        "algorithm": algo,
        "convergence": convergence[:200] if convergence else [],
        "visualization": {
            "preset": "knapsack_selection",
            "version": 1,
            "payload": {
                "items": payload_items,
                "capacity": capacity,
                "total_weight": metrics["total_weight"],
                "total_value": metrics["total_value"],
                "feasible": metrics["feasible"],
            },
        },
    }
    if weight_warnings:
        result["weight_warnings"] = weight_warnings
    return result
