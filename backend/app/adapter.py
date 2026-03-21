"""
Thin adapter: neutral problem JSON ↔ vrptw-problem optimizer/evaluator.

Does not copy solver logic; imports from vrptw-problem with sys.path bootstrap.
"""

from __future__ import annotations

import difflib
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np

_VRPTW_ROOT = Path(__file__).resolve().parents[2] / "vrptw-problem"

# Human-readable alias names shown in the participant panel and used by the agent.
# Maps alias → internal w1–w7 key expected by build_weights / evaluator.
WEIGHT_ALIASES: dict[str, str] = {
    "travel_time":       "w1",
    "fuel_cost":         "w2",
    "deadline_penalty":  "w3",
    "capacity_penalty":  "w4",
    "workload_balance":  "w5",
    "worker_preference": "w6",
    "priority_penalty":  "w7",
}

# Reverse map for displaying wN keys as human-readable aliases.
WEIGHT_ALIAS_REVERSE: dict[str, str] = {v: k for k, v in WEIGHT_ALIASES.items()}

# Internal w1–w7 keys the solver accepts directly (pass-through for legacy configs).
_WEIGHT_VALID_WN: frozenset[str] = frozenset(WEIGHT_ALIASES.values())

# Keyword map: common alternative phrasings → canonical alias.
# Enables fuzzy recovery when a user (or the agent) types a close but non-exact key.
_WEIGHT_KEYWORD_MAP: dict[str, str] = {
    # travel_time
    "travel":          "travel_time",
    "distance":        "travel_time",
    "transit":         "travel_time",
    "route_length":    "travel_time",
    "routing":         "travel_time",
    "route":           "travel_time",
    # fuel_cost
    "fuel":            "fuel_cost",
    "mileage":         "fuel_cost",
    "operating_cost":  "fuel_cost",
    "emission":        "fuel_cost",
    "cost":            "fuel_cost",
    # deadline_penalty
    "deadline":        "deadline_penalty",
    "late":            "deadline_penalty",
    "time_window":     "deadline_penalty",
    "on_time":         "deadline_penalty",
    "punctuality":     "deadline_penalty",
    "lateness":        "deadline_penalty",
    "tardiness":       "deadline_penalty",
    "window":          "deadline_penalty",
    "timeliness":      "deadline_penalty",
    # capacity_penalty
    "capacity":        "capacity_penalty",
    "load":            "capacity_penalty",
    "overload":        "capacity_penalty",
    "overflow":        "capacity_penalty",
    "packing":         "capacity_penalty",
    "weight_limit":    "capacity_penalty",
    # workload_balance
    "fairness":        "workload_balance",
    "balance":         "workload_balance",
    "equity":          "workload_balance",
    "workload":        "workload_balance",
    "shift_fairness":  "workload_balance",
    "shift_balance":   "workload_balance",
    "shift":           "workload_balance",
    "equitable":       "workload_balance",
    # worker_preference
    "preference":      "worker_preference",
    "worker":          "worker_preference",
    "driver":          "worker_preference",
    "comfort":         "worker_preference",
    "satisfaction":    "worker_preference",
    "welfare":         "worker_preference",
    # priority_penalty
    "priority":        "priority_penalty",
    "urgent":          "priority_penalty",
    "express":         "priority_penalty",
    "sla":             "priority_penalty",
    "vip":             "priority_penalty",
    "rush":            "priority_penalty",
    "critical":        "priority_penalty",
}


def _fuzzy_match_weight_key(key: str) -> str | None:
    """
    Try to map an unrecognized weight key to a known alias using:
    1. Direct keyword lookup (exact).
    2. Substring containment: keyword inside key (longest keyword first to avoid
       short keywords like "load" winning over "workload").
    3. Substring containment: key inside keyword.
    4. Difflib close-match against canonical alias names.
    Returns the matched canonical alias name, or None if no confident match.
    """
    k = key.lower().strip()
    # 1. Direct keyword match
    if k in _WEIGHT_KEYWORD_MAP:
        return _WEIGHT_KEYWORD_MAP[k]
    # 2 & 3. Substring containment — sort by keyword length descending so longer,
    # more-specific keywords match before shorter ones (e.g. "workload" before "load").
    sorted_keywords = sorted(_WEIGHT_KEYWORD_MAP.items(), key=lambda x: len(x[0]), reverse=True)
    for kw, alias in sorted_keywords:
        if kw in k:
            return alias
    for kw, alias in sorted_keywords:
        if k in kw:
            return alias
    # 4. Difflib fuzzy match against canonical alias names
    close = difflib.get_close_matches(k, list(WEIGHT_ALIASES.keys()), n=1, cutoff=0.6)
    if close:
        return close[0]
    return None


def translate_weights(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Translate human-readable alias keys (travel_time, deadline_penalty, …) to the
    internal w1–w7 keys expected by build_weights. Also tries fuzzy/keyword matching
    for close-but-not-exact keys. Unknown keys that cannot be matched are dropped.
    Configs already using w1–w7 keys pass through unchanged.
    """
    translated, _ = translate_weights_strict(raw)
    return translated


def translate_weights_strict(
    raw: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """
    Like translate_weights but also returns a human-readable list of messages for
    each key that was auto-corrected (fuzzy-matched) or dropped (unrecognised).

    Returns:
        (translated_weights_dict, warning_messages)
    """
    out: dict[str, Any] = {}
    warnings: list[str] = []
    for k, v in raw.items():
        if k in WEIGHT_ALIASES:
            out[WEIGHT_ALIASES[k]] = v
        elif k in _WEIGHT_VALID_WN:
            out[k] = v
        else:
            matched = _fuzzy_match_weight_key(k)
            if matched:
                out[WEIGHT_ALIASES[matched]] = v
                warnings.append(
                    f"Weight key '{k}' was interpreted as '{matched}' "
                    f"(closest supported objective)."
                )
            else:
                warnings.append(
                    f"Weight key '{k}' is not a recognised objective and was ignored. "
                    f"Supported objectives: {', '.join(WEIGHT_ALIASES)}."
                )
    return out, warnings


def sanitize_panel_weights(panel_config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Translate/sanitize weight keys inside panel_config['problem']['weights'] in-place
    (on a deep copy). Returns (sanitized_panel_config, warnings).
    Harmless when no 'problem.weights' key exists.
    """
    cfg = deepcopy(panel_config)
    problem = cfg.get("problem")
    if not isinstance(problem, dict):
        return cfg, []
    weights_raw = problem.get("weights")
    if weights_raw is None:
        problem.pop("weights", None)
        return cfg, []
    if not isinstance(weights_raw, dict):
        problem.pop("weights", None)
        return cfg, ["Ignored malformed `problem.weights`; expected an object."]
    translated, warnings = translate_weights_strict(weights_raw)
    # Convert wN keys back to alias names so the panel stays human-readable.
    problem["weights"] = {WEIGHT_ALIAS_REVERSE.get(k, k): v for k, v in translated.items()}
    return cfg, warnings


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
                    "vehicle_name": rec.vehicle_name,
                    "task_id": oid,
                    "task_index": task_index,
                    "region_index": ri,
                    "region_name": rec.zone,
                    "arrival_minutes": float(rec.arrival_time),
                    "departure_minutes": float(rec.departure_time),
                    "window_open_minutes": int(rec.window_open),
                    "window_close_minutes": int(rec.window_close),
                    "service_minutes": int(getattr(rec, "service_minutes", 0)),
                    "wait_minutes": float(getattr(rec, "wait_minutes", 0)),
                    "time_window_minutes_over": float(
                        getattr(rec, "time_window_minutes_over", 0)
                    ),
                    "priority_urgent": bool(rec.is_express),
                    "priority_deadline_missed": bool(
                        getattr(rec, "priority_deadline_missed", False)
                    ),
                    "constraint_conflict": bool(rec.is_violation),
                    "time_window_conflict": bool(rec.is_violation),
                    "order_size": int(getattr(rec, "order_size", 0)),
                    "load_after_stop": int(getattr(rec, "load_after_stop", 0)),
                    "capacity_limit": int(getattr(rec, "capacity_limit", 0)),
                    "capacity_overflow_after_stop": int(
                        getattr(rec, "capacity_overflow_after_stop", 0)
                    ),
                    "capacity_conflict": bool(
                        getattr(rec, "capacity_overflow_after_stop", 0) > 0
                    ),
                }
            )
    return out


def _vehicle_summaries_for_schedule(
    routes: list[list[int]],
    orders: list[Any],
    stops: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ensure_vrptw_on_path()
    from vehicles import VEHICLES

    by_vehicle: dict[int, list[dict[str, Any]]] = {}
    for stop in stops:
        by_vehicle.setdefault(int(stop["vehicle_index"]), []).append(stop)

    summaries: list[dict[str, Any]] = []
    for v_idx, vehicle in enumerate(VEHICLES):
        vehicle_routes = routes[v_idx] if v_idx < len(routes) else []
        vehicle_stops = by_vehicle.get(v_idx, [])
        assigned_units = sum(int(orders[o_idx].size) for o_idx in vehicle_routes)
        max_departure = max(
            [float(s["departure_minutes"]) for s in vehicle_stops],
            default=float(vehicle.shift_start_min),
        )
        max_close = max(
            [float(s["window_close_minutes"]) for s in vehicle_stops],
            default=float(vehicle.shift_start_min),
        )
        summaries.append(
            {
                "vehicle_index": v_idx,
                "vehicle_name": vehicle.name,
                "capacity_limit": int(vehicle.capacity),
                "assigned_units": int(assigned_units),
                "capacity_overflow_units": int(
                    max(0, assigned_units - int(vehicle.capacity))
                ),
                "shift_start_minutes": int(vehicle.shift_start_min),
                "display_end_minutes": float(max(max_departure, max_close)),
                "shift_limit_minutes": float(vehicle.max_hours * 60),
                "stop_count": len(vehicle_stops),
            }
        )
    return summaries


def _time_bounds_for_schedule(
    vehicle_summaries: list[dict[str, Any]], stops: list[dict[str, Any]]
) -> dict[str, float]:
    start = min(
        [float(v["shift_start_minutes"]) for v in vehicle_summaries],
        default=0.0,
    )
    end_candidates = [
        *[float(v["display_end_minutes"]) for v in vehicle_summaries],
        *[float(s["window_close_minutes"]) for s in stops],
        *[float(s["departure_minutes"]) for s in stops],
    ]
    end = max(end_candidates, default=start)
    return {"start_minutes": start, "end_minutes": end}


def routes_to_neutral(routes: list[list[int]]) -> list[dict[str, Any]]:
    return [
        {"vehicle_index": i, "task_indices": [int(x) for x in route]}
        for i, route in enumerate(routes)
    ]


def parse_problem_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize incoming neutral problem configuration.

    The returned dict includes a 'weight_warnings' key (list[str]) for any
    weight keys that were auto-corrected or dropped; callers should pop and
    surface this before passing the config to the solver.
    """
    ensure_vrptw_on_path()
    from user_input import DEFAULT_DRIVER_PREFERENCES, SHIFT_HARD_PENALTY, build_weights

    weights_raw, weight_warnings = translate_weights_strict(raw.get("weights") or {})
    only_active = bool(raw.get("only_active_terms", False))
    weights = build_weights(weights_raw, only_active_terms=only_active)

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
        ref_w_translated, ref_w_warnings = translate_weights_strict(ref_weights)
        weight_warnings.extend(ref_w_warnings)
        ref_weights = build_weights(
            ref_w_translated,
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
        # Callers must pop this before passing cfg to the solver.
        "weight_warnings": weight_warnings,
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
    route_rows = routes_to_neutral(result.routes)
    vehicle_summaries = _vehicle_summaries_for_schedule(result.routes, orders, visits)
    time_bounds = _time_bounds_for_schedule(vehicle_summaries, visits)

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
            "routes": route_rows,
            "stops": visits,
            "vehicle_summaries": vehicle_summaries,
            "time_bounds": time_bounds,
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
    route_rows = routes_to_neutral(routes)
    vehicle_summaries = _vehicle_summaries_for_schedule(routes, orders, visits)
    time_bounds = _time_bounds_for_schedule(vehicle_summaries, visits)
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
            "routes": route_rows,
            "stops": visits,
            "vehicle_summaries": vehicle_summaries,
            "time_bounds": time_bounds,
        },
        "violations": neutral_violations(metrics),
        "metrics": neutral_metrics,
        "runtime_seconds": 0.0,
        "algorithm": "evaluate",
        "convergence": [],
    }


def solve_request_to_result(body: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    cfg = parse_problem_config(body.get("problem") or body)
    # Pop warnings before passing cfg to the solver (solver ignores unknown keys anyway,
    # but this keeps cfg clean and makes warning propagation explicit).
    weight_warnings: list[str] = cfg.pop("weight_warnings", [])
    run_type = (body.get("type") or "optimize").lower()
    if run_type == "evaluate":
        routes = body.get("routes")
        if not routes or not isinstance(routes, list):
            raise ValueError("evaluate requires routes: list of 5 lists of task indices")
        routes = [[int(x) for x in row] for row in routes]
        result = run_evaluate_routes(routes, cfg)
    else:
        result = run_optimize(cfg, timeout_sec)
    if weight_warnings:
        result["weight_warnings"] = weight_warnings
    return result
