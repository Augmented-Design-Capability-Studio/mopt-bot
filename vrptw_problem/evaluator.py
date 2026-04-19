"""
Objective function and route simulator for QuickBite VRPTW.

Evaluates solutions against a given problem definition (weights, driver
preferences, penalties). Used by the optimizer at solve time and by
researchers for retroactive evaluation of user problem definitions.

This module does NOT load user_input; the caller supplies the problem
definition (weights, driver_preferences, max_shift_hours).
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from vrptw_problem.traffic_api import get_travel_time, ZONE_DEPOT, ZONE_D, ZONE_NAMES
from vrptw_problem.encoder import decode_solution
from vrptw_problem.orders import Order
from vrptw_problem.vehicles import VEHICLES


@dataclass
class VisitRecord:
    """Record of a single order visit for Gantt/reporting."""
    vehicle_id: int
    vehicle_name: str
    order_id: str
    order_index: int
    zone: str
    zone_index: int
    arrival_time: float
    departure_time: float
    window_open: int
    window_close: int
    is_express: bool
    is_violation: bool
    priority_deadline_missed: bool
    order_size: int
    service_minutes: int
    wait_minutes: float
    time_window_minutes_over: float
    load_after_stop: int
    capacity_limit: int
    capacity_overflow_after_stop: int
    preference_penalty_units: float = 0.0


@dataclass
class RouteMetrics:
    """Metrics for a single vehicle route."""
    total_travel_time: float = 0.0
    total_service_time: float = 0.0
    load: int = 0
    capacity_overflow: int = 0
    shift_duration_minutes: float = 0.0
    tw_violation_min: float = 0.0
    tw_violation_count: int = 0
    express_late_count: int = 0
    driver_penalty: float = 0.0
    total_wait_time: float = 0.0
    visits: list[VisitRecord] = field(default_factory=list)


def _rule_shift_limit_minutes(rule: dict) -> float:
    """Soft shift threshold in minutes (legacy: hours, limit_minutes)."""
    if "limit_minutes" in rule and rule["limit_minutes"] is not None:
        return float(rule["limit_minutes"])
    if "hours" in rule and rule["hours"] is not None:
        return float(rule["hours"]) * 60.0
    return 6.5 * 60.0


def _normalize_avoid_zone_rule(rule: dict) -> tuple[str, int]:
    """Return (condition_key, order.zone 1–5 to avoid). Legacy zone_d -> avoid zone 4."""
    c = rule.get("condition", "")
    if c == "zone_d":
        return "avoid_zone", int(rule.get("zone", ZONE_D))
    if c == "avoid_zone":
        return "avoid_zone", int(rule.get("zone", ZONE_D))
    return "", -1


def _normalize_order_priority_rule(rule: dict) -> tuple[str, str]:
    c = rule.get("condition", "")
    if c == "express_order":
        return "order_priority", str(rule.get("order_priority", "express"))
    if c == "order_priority":
        return "order_priority", str(rule.get("order_priority", "express"))
    return "", ""


def _aggregation(rule: dict) -> str:
    return str(rule.get("aggregation", "per_stop"))


def _apply_driver_penalties_per_visit(
    v_idx: int,
    order: Order,
    is_express: bool,
    driver_preferences: list[dict],
) -> float:
    """Per-stop penalties (aggregation per_stop or default)."""
    penalty = 0.0
    for rule in driver_preferences:
        if rule.get("vehicle_idx") != v_idx:
            continue
        if _aggregation(rule) == "once_per_route":
            continue
        ak, z = _normalize_avoid_zone_rule(rule)
        if ak == "avoid_zone" and order.zone == z:
            penalty += float(rule.get("penalty", 0))
            continue
        ok, pr = _normalize_order_priority_rule(rule)
        if ok == "order_priority" and order.priority == pr:
            penalty += float(rule.get("penalty", 0))
    return penalty


def _apply_driver_penalties_once_per_route(
    v_idx: int,
    order_indices: list[int],
    orders: list[Order],
    driver_preferences: list[dict],
) -> float:
    """Lump penalties when aggregation is once_per_route."""
    penalty = 0.0
    for rule in driver_preferences:
        if rule.get("vehicle_idx") != v_idx:
            continue
        if _aggregation(rule) != "once_per_route":
            continue
        p = float(rule.get("penalty", 0))
        ak, z = _normalize_avoid_zone_rule(rule)
        if ak == "avoid_zone":
            if any(orders[o].zone == z for o in order_indices):
                penalty += p
            continue
        ok, pr = _normalize_order_priority_rule(rule)
        if ok == "order_priority":
            if any(orders[o].priority == pr for o in order_indices):
                penalty += p
    return penalty


def _apply_driver_penalties_per_route(
    v_idx: int,
    shift_duration_minutes: float,
    driver_preferences: list[dict],
) -> float:
    """Route-level penalties (shift length soft limit)."""
    penalty = 0.0
    for rule in driver_preferences:
        if rule.get("vehicle_idx") != v_idx:
            continue
        cond = rule.get("condition", "")
        if cond not in ("shift_over_hours", "shift_over_limit"):
            continue
        limit_min = _rule_shift_limit_minutes(rule)
        if shift_duration_minutes > limit_min:
            penalty += float(rule.get("penalty", 0))
    return penalty


def simulate_routes(
    routes: list[list[int]],
    orders: list[Order],
    rng: np.random.RandomState,
    weights: dict,
    driver_preferences: Optional[list[dict]] = None,
    max_shift_hours: float = 8.0,
) -> tuple[float, dict, list[list[VisitRecord]]]:
    """
    Simulate route execution and compute cost components.

    Args:
        routes: List of 5 lists of order indices.
        orders: List of Order objects.
        rng: Seeded RandomState for get_travel_time.
        weights: Weight dict (w1..w8). Partial dicts supported; missing keys use 0.
        driver_preferences: List of rule dicts. Default [] (no driver penalties).
        max_shift_hours: Threshold in hours beyond which w2 penalty applies.

    Returns:
        (total_cost, metrics_dict, visits_per_vehicle)
    """
    if driver_preferences is None:
        driver_preferences = []

    w1 = weights.get("w1", 0.0)
    w2 = weights.get("w2", 0.0)
    w3 = weights.get("w3", 0.0)
    w4 = weights.get("w4", 0.0)
    w5 = weights.get("w5", 0.0)
    w6 = weights.get("w6", 0.0)
    w7 = weights.get("w7", 0.0)
    w8 = weights.get("w8", 0.0)

    total_travel_time = 0.0
    total_tw_violation_min = 0.0
    total_tw_violation_count = 0
    total_capacity_overflow = 0
    total_driver_penalty = 0.0
    total_express_late = 0
    total_wait_time = 0.0
    shift_durations: list[float] = []
    productive_durations: list[float] = []  # travel + service only; excludes idle wait
    visits_per_vehicle: list[list[VisitRecord]] = []

    max_shift_min = max_shift_hours * 60

    for v_idx, (vehicle, order_indices) in enumerate(zip(VEHICLES, routes)):
        rm = RouteMetrics()
        current_zone = vehicle.start_zone
        current_time = float(vehicle.shift_start_min)
        load = 0

        for o_idx in order_indices:
            order = orders[o_idx]
            tt = get_travel_time(current_zone, order.zone, current_time, rng)
            current_time += tt
            rm.total_travel_time += tt

            arrival = current_time
            if arrival < order.time_window_open:
                current_time = float(order.time_window_open)
            current_time += order.service_time
            rm.total_service_time += order.service_time
            load += order.size

            tw_viol = max(0, arrival - order.time_window_close)
            if tw_viol > 0:
                rm.tw_violation_min += tw_viol
                rm.tw_violation_count += 1
                is_violation = True
            else:
                is_violation = False

            is_express = order.priority == "express"
            if is_express and arrival > order.time_window_close:
                rm.express_late_count += 1

            rm.load = load
            overflow = max(0, load - vehicle.capacity)
            rm.capacity_overflow = max(rm.capacity_overflow, overflow)

            pv = _apply_driver_penalties_per_visit(
                v_idx, order, is_express, driver_preferences
            )
            rm.driver_penalty += pv

            wait_minutes = max(0.0, float(order.time_window_open) - arrival)
            rm.total_wait_time += wait_minutes

            rm.visits.append(VisitRecord(
                vehicle_id=vehicle.vehicle_id,
                vehicle_name=vehicle.name,
                order_id=order.order_id,
                order_index=o_idx,
                zone=ZONE_NAMES[order.zone],
                zone_index=order.zone,
                arrival_time=arrival,
                departure_time=current_time,
                window_open=order.time_window_open,
                window_close=order.time_window_close,
                is_express=is_express,
                is_violation=is_violation,
                priority_deadline_missed=is_express and arrival > order.time_window_close,
                order_size=order.size,
                service_minutes=order.service_time,
                wait_minutes=wait_minutes,
                time_window_minutes_over=tw_viol,
                load_after_stop=load,
                capacity_limit=vehicle.capacity,
                capacity_overflow_after_stop=overflow,
                preference_penalty_units=pv,
            ))
            current_zone = order.zone

        # Return to depot
        tt = get_travel_time(current_zone, ZONE_DEPOT, current_time, rng)
        current_time += tt
        rm.total_travel_time += tt

        rm.shift_duration_minutes = float(current_time - vehicle.shift_start_min)
        shift_durations.append(rm.shift_duration_minutes)
        productive_durations.append(rm.total_travel_time + rm.total_service_time)

        rm.driver_penalty += _apply_driver_penalties_once_per_route(
            v_idx, order_indices, orders, driver_preferences
        )
        rm.driver_penalty += _apply_driver_penalties_per_route(
            v_idx, rm.shift_duration_minutes, driver_preferences
        )

        total_travel_time += rm.total_travel_time
        total_tw_violation_min += rm.tw_violation_min
        total_tw_violation_count += rm.tw_violation_count
        total_capacity_overflow += rm.capacity_overflow
        total_driver_penalty += rm.driver_penalty
        total_express_late += rm.express_late_count
        total_wait_time += rm.total_wait_time

        visits_per_vehicle.append(rm.visits)

    # Workload variance: variance of drive+service time per vehicle (excludes idle pre-window wait).
    productive_arr = np.array(productive_durations)
    workload_variance = float(np.var(productive_arr)) if len(productive_arr) > 1 else 0.0

    # w2: total minutes beyond max_shift_hours, summed over vehicles — soft shift-hours pressure
    shift_overtime_minutes = float(
        sum(max(0.0, float(sd) - max_shift_min) for sd in shift_durations)
    )

    cost = (
        w1 * total_travel_time
        + w2 * shift_overtime_minutes
        + w3 * total_tw_violation_min
        + w4 * total_capacity_overflow
        + w5 * workload_variance
        + w6 * total_driver_penalty
        + w7 * total_express_late
        + w8 * total_wait_time
    )

    metrics = {
        "travel_time": total_travel_time,
        "shift_overtime_minutes": shift_overtime_minutes,
        "tw_violation_min": total_tw_violation_min,
        "tw_violation_count": total_tw_violation_count,
        "capacity_overflow": total_capacity_overflow,
        "workload_variance": workload_variance,
        "driver_penalty": total_driver_penalty,
        "express_late_count": total_express_late,
        "wait_time": total_wait_time,
        "shift_durations": shift_durations,
        "productive_durations": productive_durations,
    }
    return cost, metrics, visits_per_vehicle


def evaluate_solution(
    position_vector: np.ndarray,
    orders: list[Order],
    rng: np.random.RandomState,
    weights: dict,
    locked_assignments: Optional[dict[int, int]] = None,
    driver_preferences: Optional[list[dict]] = None,
    max_shift_hours: float = 8.0,
) -> tuple[float, dict, list[list[VisitRecord]]]:
    """
    Decode position vector, simulate routes, and return cost + metrics.

    Args:
        position_vector: Length-34 float array.
        orders: List of Order objects.
        rng: Seeded RandomState.
        weights: Weight dict (w1..w8). Partial dicts supported.
        locked_assignments: Optional {order_idx: vehicle_idx}.
        driver_preferences: Optional list of rule dicts.
        max_shift_hours: Threshold in hours beyond which w2 penalty applies.

    Returns:
        (cost, metrics, visits_per_vehicle)
    """
    routes = decode_solution(
        position_vector,
        locked_assignments=locked_assignments,
    )
    return simulate_routes(
        routes,
        orders,
        rng,
        weights,
        driver_preferences=driver_preferences,
        max_shift_hours=max_shift_hours,
    )
