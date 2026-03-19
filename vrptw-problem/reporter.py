"""
Formatted reporting and Gantt data for QuickBite optimization results.
"""

import numpy as np

from optimizer import SolveResult
from evaluator import VEHICLES, simulate_routes
from orders import get_orders
from traffic_api import ZONE_NAMES
from user_input import load_user_input


def _get_sim_config(result: SolveResult) -> tuple[dict, list, float]:
    """Get (weights, driver_preferences, shift_hard_penalty) from result or user_input."""
    if result.weights is not None:
        weights = result.weights
        driver_prefs = result.driver_preferences or []
        shift_penalty = result.shift_hard_penalty or 5000.0
    else:
        config = load_user_input()
        weights = config["weights"]
        driver_prefs = config["driver_preferences"]
        shift_penalty = config["shift_hard_penalty"]
    return weights, driver_prefs, shift_penalty


def get_gantt_data(
    result: SolveResult,
    random_seed: int = 42,
) -> list[dict]:
    """
    Build Gantt-compatible data from a solve result.

    Uses the problem definition stored in result (or current user_input as fallback).

    Returns a list of dicts suitable for Gantt chart rendering.
    """
    orders = get_orders(seed=None)
    rng = np.random.RandomState(random_seed)
    weights, driver_prefs, shift_penalty = _get_sim_config(result)
    _, _, visits_per_vehicle = simulate_routes(
        result.routes,
        orders,
        rng,
        weights,
        driver_preferences=driver_prefs,
        shift_hard_penalty=shift_penalty,
    )

    gantt = []
    for v_idx, visits in enumerate(visits_per_vehicle):
        route = result.routes[v_idx] if v_idx < len(result.routes) else []
        for i, v in enumerate(visits):
            order_idx = route[i] if i < len(route) else -1
            gantt.append({
                "vehicle_id": v.vehicle_id,
                "vehicle_name": v.vehicle_name,
                "order_idx": order_idx,
                "order_id": v.order_id,
                "zone": v.zone,
                "arrival_time": v.arrival_time,
                "departure_time": v.departure_time,
                "window_open": v.window_open,
                "window_close": v.window_close,
                "is_express": v.is_express,
                "is_violation": v.is_violation,
            })
    return gantt


def _minutes_to_hours_str(minutes: float) -> str:
    """Convert minutes to 'X.Xh' string."""
    h = minutes / 60
    return f"{h:.1f}h"


def print_report(result: SolveResult, random_seed: int = 42) -> None:
    """Print a formatted QuickBite optimization report."""
    orders = get_orders(seed=None)
    rng = np.random.RandomState(random_seed)
    weights, driver_prefs, shift_penalty = _get_sim_config(result)
    _, metrics, visits_per_vehicle = simulate_routes(
        result.routes,
        orders,
        rng,
        weights,
        driver_preferences=driver_prefs,
        shift_hard_penalty=shift_penalty,
    )

    m = metrics
    shift_durations = m.get("shift_durations", [0.0] * 5)
    variance = m.get("workload_variance", 0.0)

    print("\n=== QuickBite Optimization Result ===")
    print(f"  Algorithm : {result.algorithm}")
    print(f"  Runtime   : {result.runtime:.1f}s")
    print(f"  Best Cost : {result.best_cost:.1f}")
    print("\n  --- Cost Breakdown ---")
    print(f"  Travel Time       : {m.get('travel_time', 0):.1f} min")
    print(f"  Fuel Cost         : {m.get('fuel_cost', 0):.1f}")
    print(f"  TW Violations     : {m.get('tw_violation_count', 0)} orders, "
          f"{m.get('tw_violation_min', 0):.1f} min total")
    print(f"  Capacity Overflow : {m.get('capacity_overflow', 0)} units")
    print(f"  Workload Variance : {m.get('workload_variance', 0):.1f}")
    print(f"  Driver Penalties  : {m.get('driver_penalty', 0):.1f} min")
    print(f"  Express Lateness  : {m.get('express_late_count', 0)} orders")
    print("\n  --- Route Summary ---")

    for v_idx, (vehicle, route_order_ids) in enumerate(zip(VEHICLES, result.routes)):
        load = sum(orders[o].size for o in route_order_ids)
        shift_min = shift_durations[v_idx] if v_idx < len(shift_durations) else 0
        order_str = " ".join(f"O{o:02d}" for o in route_order_ids)
        zone_str = " ".join(ZONE_NAMES[orders[o].zone] for o in route_order_ids)
        print(f"  V{vehicle.vehicle_id} {vehicle.name:<6}: {order_str or '(empty)'}  "
              f"|  Load: {load}/{vehicle.capacity}")
        print(f"               Shift: {_minutes_to_hours_str(shift_min)}  |  Zones: {zone_str or '-'}")

    print("\n  --- Workload Balance ---")
    balance = "  ".join(
        f"{v.name}: {_minutes_to_hours_str(shift_durations[i])}"
        for i, v in enumerate(VEHICLES) if i < len(shift_durations)
    )
    print(f"  {balance}")
    print(f"  Variance: {variance:.2f}\n")
