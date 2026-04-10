"""
Official Evaluator — canonical scoring for QuickBite VRPTW solutions.

Evaluates both:
1. **Problem formulation** — What the user specified (objectives, constraints)
2. **Results** — Quality of the solution (official cost, user cost, constraint satisfaction)

Used for research: compare how well different users did under the same problem.
"""

import numpy as np
from typing import Any, Optional

from evaluator import simulate_routes
from orders import Order, get_orders
from user_input import (
    DEFAULT_WEIGHTS,
    DEFAULT_DRIVER_PREFERENCES,
    SHIFT_HARD_PENALTY,
)
from vehicles import VEHICLES

MAX_SHIFT_MIN = 8.0 * 60  # 8 hours
N_ORDERS = 30
WEIGHT_KEYS = ["w1", "w2", "w3", "w4", "w5", "w6", "w7"]


def evaluate_formulation(user_config: dict) -> dict[str, Any]:
    """
    Evaluate the user's problem formulation (what they specified).

    Returns:
        formulation_metrics: hard_constraints_defined, soft_constraints_defined,
            soft_terms_count (1–7), has_driver_prefs, has_locked_assignments
    """
    weights = user_config.get("weights", {})
    soft_count = sum(1 for k in WEIGHT_KEYS if weights.get(k, 0) and weights.get(k, 0) != 0)
    return {
        "hard_constraints_defined": user_config.get("hard_constraints", []),
        "soft_constraints_defined": user_config.get("soft_constraints", []),
        "soft_terms_count": soft_count,
        "has_driver_prefs": bool(user_config.get("driver_preferences")),
        "has_locked_assignments": bool(user_config.get("locked_assignments")),
    }


def evaluate_official(
    routes: list[list[int]],
    orders: list[Order],
    rng: np.random.RandomState,
) -> tuple[float, dict]:
    """
    Official score: canonical objective (full 7 terms + defaults).

    Returns:
        (official_cost, metrics)
    """
    cost, metrics, _ = simulate_routes(
        routes,
        orders,
        rng,
        weights=DEFAULT_WEIGHTS,
        driver_preferences=DEFAULT_DRIVER_PREFERENCES,
        shift_hard_penalty=SHIFT_HARD_PENALTY,
    )
    return float(cost), metrics


def evaluate_user(
    routes: list[list[int]],
    orders: list[Order],
    rng: np.random.RandomState,
    user_config: dict,
) -> tuple[float, dict]:
    """
    User score: user's stated objective and constraints.

    user_config must have: weights, driver_preferences, shift_hard_penalty.

    Returns:
        (user_cost, metrics)
    """
    cost, metrics, _ = simulate_routes(
        routes,
        orders,
        rng,
        weights=user_config["weights"],
        driver_preferences=user_config.get("driver_preferences", []),
        shift_hard_penalty=user_config.get("shift_hard_penalty", SHIFT_HARD_PENALTY),
    )
    return float(cost), metrics


def evaluate_constraint_satisfaction(
    routes: list[list[int]],
    orders: list[Order],
    rng: np.random.RandomState,
    locked_assignments: Optional[dict] = None,
) -> dict[str, Any]:
    """
    Check hard and soft constraint satisfaction.

    Returns dict with:
        all_orders_covered, no_duplicates, all_shifts_under_8h,
        locked_assignments_obeyed, tw_violation_count, capacity_overflow,
        express_late_count, shift_durations
    """
    if locked_assignments is None:
        locked_assignments = {}

    _, metrics, _ = simulate_routes(
        routes,
        orders,
        rng,
        weights={k: 0.0 for k in ["w1", "w2", "w3", "w4", "w5", "w6", "w7"]},
        driver_preferences=[],
        shift_hard_penalty=0,  # we check manually
    )

    # All orders covered
    covered = set()
    for route in routes:
        for o in route:
            covered.add(o)
    all_covered = covered == set(range(N_ORDERS)) and len(covered) == N_ORDERS

    # No duplicates
    flat = [o for r in routes for o in r]
    no_duplicates = len(flat) == len(set(flat))

    # Shifts under 8h
    shift_durations = metrics.get("shift_durations", [])
    all_under_8h = all(sd <= MAX_SHIFT_MIN for sd in shift_durations)

    # Locked assignments obeyed
    locked_ok = True
    for order_idx, vehicle_idx in locked_assignments.items():
        if order_idx < 0 or order_idx >= N_ORDERS or vehicle_idx < 0 or vehicle_idx >= len(routes):
            continue
        if order_idx not in routes[vehicle_idx]:
            locked_ok = False
            break

    return {
        "all_orders_covered": all_covered,
        "no_duplicates": no_duplicates,
        "all_shifts_under_8h": all_under_8h,
        "locked_assignments_obeyed": locked_ok,
        "tw_violation_count": metrics.get("tw_violation_count", 0),
        "tw_violation_min": metrics.get("tw_violation_min", 0),
        "capacity_overflow": metrics.get("capacity_overflow", 0),
        "express_late_count": metrics.get("express_late_count", 0),
        "shift_durations": shift_durations,
    }


def full_official_evaluation(
    routes: list[list[int]],
    user_config: dict,
    orders: Optional[list[Order]] = None,
    random_seed: int = 42,
) -> dict[str, Any]:
    """
    One-stop official evaluation: official cost, user cost, constraint satisfaction.

    Args:
        routes: Solution routes (list of 5 lists of order indices).
        user_config: User's problem definition (from load_user_input).
        orders: Optional. Defaults to get_orders(seed=None).
        random_seed: For reproducibility.

    Returns:
        Dict with official_cost, user_cost, constraints, metrics, etc.
    """
    if orders is None:
        orders = get_orders(seed=None)
    rng = np.random.RandomState(random_seed)

    formulation = evaluate_formulation(user_config)
    official_cost, official_metrics = evaluate_official(routes, orders, rng)
    user_cost, user_metrics = evaluate_user(routes, orders, rng, user_config)
    constraints = evaluate_constraint_satisfaction(
        routes,
        orders,
        rng,
        locked_assignments=user_config.get("locked_assignments"),
    )

    return {
        "formulation": formulation,
        "official_cost": official_cost,
        "user_cost": user_cost,
        "official_metrics": official_metrics,
        "user_metrics": user_metrics,
        "constraints": constraints,
        "hard_constraints_defined": formulation["hard_constraints_defined"],
        "soft_constraints_defined": formulation["soft_constraints_defined"],
    }


def _cost_contribution(metrics: dict, weights: dict) -> dict[str, float]:
    """Break down cost by term (for comparison)."""
    w = weights
    return {
        "travel": w.get("w1", 0) * metrics.get("travel_time", 0),
        "shift_overtime": w.get("w2", 0) * metrics.get("shift_overtime_minutes", 0),
        "tw_violation": w.get("w3", 0) * metrics.get("tw_violation_min", 0),
        "capacity": w.get("w4", 0) * metrics.get("capacity_overflow", 0),
        "workload": w.get("w5", 0) * metrics.get("workload_variance", 0),
        "driver_penalty": w.get("w6", 0) * metrics.get("driver_penalty", 0),
        "express_late": w.get("w7", 0) * metrics.get("express_late_count", 0),
    }


def print_cost_breakdown_comparison(
    results: list[tuple[str, dict]],
) -> None:
    """
    Print side-by-side official cost breakdown and identify compromised terms.

    results: list of (label, eval_result) where eval_result has official_metrics.
    """
    if len(results) < 2:
        return
    print("\n" + "=" * 70)
    print("  COST BREAKDOWN (Official / Canonical Weights)")
    print("=" * 70)
    headers = ["Term", "w", "Unit"] + [r[0][:12] for r in results]
    print(f"  {'Term':<16} {'w':<6} {'Unit':<10} " + "  ".join(label.rjust(10) for label, _ in results))
    print("-" * 70)

    m0 = results[0][1].get("official_metrics", {})
    term_info = [
        ("travel_time", "w1", "1.0", "min"),
        ("shift_overtime_minutes", "w2", "5", "min"),
        ("tw_violation_min", "w3", "50", "min"),
        ("capacity_overflow", "w4", "1k", "units"),
        ("workload_variance", "w5", "10", "var"),
        ("driver_penalty", "w6", "1.0", "min"),
        ("express_late_count", "w7", "100", "count"),
    ]
    term_costs: list[tuple[str, list[float]]] = []
    for key, wk, wval, unit in term_info:
        contribs = []
        for _, ev in results:
            c = _cost_contribution(ev.get("official_metrics", {}), DEFAULT_WEIGHTS)
            name = {"travel_time": "travel", "shift_overtime_minutes": "shift_overtime", "tw_violation_min": "tw_violation",
                    "capacity_overflow": "capacity", "workload_variance": "workload",
                    "driver_penalty": "driver_penalty", "express_late_count": "express_late"}[key]
            contribs.append(c.get(name, 0))
        display = {"travel_time": "Travel time", "shift_overtime_minutes": "Shift OT min", "tw_violation_min": "TW violation",
                   "capacity_overflow": "Capacity", "workload_variance": "Workload var",
                   "driver_penalty": "Driver penalty", "express_late_count": "Express late"}[key]
        term_costs.append((display, contribs))

    for (term, contribs), (key, wk, wval, unit) in zip(term_costs, term_info):
        row = f"  {term:<16} {wval:<6} {unit:<10}"
        for c in contribs:
            row += f"  {c:>10.1f}"
        print(row)

    print("-" * 70)
    row = f"  {'TOTAL':<16} {'':<6} {'':<10}"
    for label, ev in results:
        row += f"  {ev.get('official_cost', 0):>10.1f}"
    print(row)
    col_start = 36
    for label, _ in results:
        print(" " * col_start + f"<- {label}")
        col_start += 12

    print("=" * 70 + "\n")


def print_official_report(eval_result: dict, user_label: str = "User") -> None:
    """Print a formatted official evaluation report."""
    c = eval_result["constraints"]
    f = eval_result.get("formulation", {})
    print(f"\n{'='*60}")
    print(f"  OFFICIAL EVALUATION — {user_label}")
    print("="*60)
    print("  --- A. Problem Formulation ---")
    print(f"  Soft terms specified    : {f.get('soft_terms_count', 0)}/7")
    print(f"  Hard constraints        : {f.get('hard_constraints_defined', [])}")
    print(f"  Soft constraints        : {f.get('soft_constraints_defined', [])}")
    print(f"  Driver prefs specified  : {f.get('has_driver_prefs', False)}")
    print(f"  Locked assignments      : {f.get('has_locked_assignments', False)}")
    print()
    print("  --- B. Results ---")
    print(f"  Official Cost (canonical) : {eval_result['official_cost']:.1f}")
    print(f"  User Cost (user objective): {eval_result['user_cost']:.1f}")
    print()
    print("  --- Hard Constraint Satisfaction ---")
    print(f"  All orders covered        : {c['all_orders_covered']}")
    print(f"  No duplicates             : {c['no_duplicates']}")
    print(f"  All shifts ≤ 8h           : {c['all_shifts_under_8h']}")
    print(f"  Locked assignments obeyed : {c['locked_assignments_obeyed']}")
    print()
    print("  --- Soft Constraint Violations ---")
    print(f"  TW violations     : {c['tw_violation_count']} orders, {c['tw_violation_min']:.1f} min")
    print(f"  Capacity overflow : {c['capacity_overflow']} units")
    print(f"  Express late      : {c['express_late_count']} orders")
    print("="*60)
