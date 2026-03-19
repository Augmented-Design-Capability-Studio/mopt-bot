"""
Objective function and route simulator for QuickBite VRPTW.

Evaluates solutions against a given problem definition (weights, driver
preferences, penalties). Used by the optimizer at solve time and by
researchers for retroactive evaluation of user problem definitions.

This module does NOT load user_input; the caller supplies the problem
definition (weights, driver_preferences, shift_hard_penalty).
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from traffic_api import get_travel_time, ZONE_DEPOT, ZONE_D, ZONE_NAMES
from encoder import decode_solution
from orders import Order
from vehicles import VEHICLES


@dataclass
class VisitRecord:
    """Record of a single order visit for Gantt/reporting."""
    vehicle_id: int
    vehicle_name: str
    order_id: str
    zone: str
    arrival_time: float
    departure_time: float
    window_open: int
    window_close: int
    is_express: bool
    is_violation: bool


@dataclass
class RouteMetrics:
    """Metrics for a single vehicle route."""
    total_travel_time: float = 0.0
    total_service_time: float = 0.0
    load: int = 0
    capacity_overflow: int = 0
    shift_duration_min: float = 0.0
    tw_violation_min: float = 0.0
    tw_violation_count: int = 0
    express_late_count: int = 0
    driver_penalty: float = 0.0
    visits: list[VisitRecord] = field(default_factory=list)


def _apply_driver_penalties_per_visit(
    v_idx: int,
    order: Order,
    is_express: bool,
    driver_preferences: list[dict],
) -> float:
    """Compute driver penalty for a single visit from user-specified rules."""
    penalty = 0.0
    for rule in driver_preferences:
        if rule.get("vehicle_idx") != v_idx:
            continue
        cond = rule.get("condition", "")
        if cond == "zone_d" and order.zone == ZONE_D:
            penalty += rule.get("penalty", 0)
        elif cond == "express_order" and is_express:
            penalty += rule.get("penalty", 0)
    return penalty


def _apply_driver_penalties_per_route(
    v_idx: int,
    shift_duration_hours: float,
    driver_preferences: list[dict],
) -> float:
    """Compute driver penalty for a route (e.g., shift_over_hours)."""
    penalty = 0.0
    for rule in driver_preferences:
        if rule.get("vehicle_idx") != v_idx:
            continue
        if rule.get("condition") == "shift_over_hours":
            limit_hours = rule.get("hours", 6.5)
            if shift_duration_hours > limit_hours:
                penalty += rule.get("penalty", 0)
    return penalty


def simulate_routes(
    routes: list[list[int]],
    orders: list[Order],
    rng: np.random.RandomState,
    weights: dict,
    driver_preferences: Optional[list[dict]] = None,
    shift_hard_penalty: float = 5000.0,
) -> tuple[float, dict, list[list[VisitRecord]]]:
    """
    Simulate route execution and compute cost components.

    Args:
        routes: List of 5 lists of order indices.
        orders: List of Order objects.
        rng: Seeded RandomState for get_travel_time.
        weights: Weight dict (w1..w7). Partial dicts supported; missing keys use 0.
        driver_preferences: List of rule dicts. Default [] (no driver penalties).
        shift_hard_penalty: Penalty per vehicle exceeding 8h.

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

    total_travel_time = 0.0
    total_tw_violation_min = 0.0
    total_tw_violation_count = 0
    total_capacity_overflow = 0
    total_driver_penalty = 0.0
    total_express_late = 0
    shift_durations: list[float] = []
    visits_per_vehicle: list[list[VisitRecord]] = []

    max_shift_min = 8.0 * 60  # 8 hours

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
            departure = current_time
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

            rm.driver_penalty += _apply_driver_penalties_per_visit(
                v_idx, order, is_express, driver_preferences
            )

            rm.visits.append(VisitRecord(
                vehicle_id=vehicle.vehicle_id,
                vehicle_name=vehicle.name,
                order_id=order.order_id,
                zone=ZONE_NAMES[order.zone],
                arrival_time=arrival,
                departure_time=departure,
                window_open=order.time_window_open,
                window_close=order.time_window_close,
                is_express=is_express,
                is_violation=is_violation,
            ))
            current_zone = order.zone

        # Return to depot
        tt = get_travel_time(current_zone, ZONE_DEPOT, current_time, rng)
        current_time += tt
        rm.total_travel_time += tt

        rm.shift_duration_min = (current_time - vehicle.shift_start_min) / 60.0  # hours
        shift_durations.append(rm.shift_duration_min * 60)  # store in minutes for variance

        rm.driver_penalty += _apply_driver_penalties_per_route(
            v_idx, rm.shift_duration_min, driver_preferences
        )

        total_travel_time += rm.total_travel_time
        total_tw_violation_min += rm.tw_violation_min
        total_tw_violation_count += rm.tw_violation_count
        total_capacity_overflow += rm.capacity_overflow
        total_driver_penalty += rm.driver_penalty
        total_express_late += rm.express_late_count

        visits_per_vehicle.append(rm.visits)

    # Workload variance (variance of shift durations in minutes)
    shift_arr = np.array(shift_durations)
    workload_variance = float(np.var(shift_arr)) if len(shift_arr) > 1 else 0.0

    # Hard shift penalty
    hard_penalty_total = 0
    for sd in shift_durations:
        if sd > max_shift_min:
            hard_penalty_total += shift_hard_penalty

    # Cost
    fuel_cost = total_travel_time  # fuel proxy = travel time
    cost = (
        w1 * total_travel_time
        + w2 * fuel_cost
        + w3 * total_tw_violation_min
        + w4 * total_capacity_overflow
        + w5 * workload_variance
        + w6 * total_driver_penalty
        + w7 * total_express_late
        + hard_penalty_total
    )

    metrics = {
        "travel_time": total_travel_time,
        "fuel_cost": fuel_cost,
        "tw_violation_min": total_tw_violation_min,
        "tw_violation_count": total_tw_violation_count,
        "capacity_overflow": total_capacity_overflow,
        "workload_variance": workload_variance,
        "driver_penalty": total_driver_penalty,
        "express_late_count": total_express_late,
        "shift_hard_penalty": hard_penalty_total,
        "shift_durations": shift_durations,
    }
    return cost, metrics, visits_per_vehicle


def evaluate_solution(
    position_vector: np.ndarray,
    orders: list[Order],
    rng: np.random.RandomState,
    weights: dict,
    locked_assignments: Optional[dict[int, int]] = None,
    driver_preferences: Optional[list[dict]] = None,
    shift_hard_penalty: float = 5000.0,
) -> tuple[float, dict, list[list[VisitRecord]]]:
    """
    Decode position vector, simulate routes, and return cost + metrics.

    Args:
        position_vector: Length-34 float array.
        orders: List of Order objects.
        rng: Seeded RandomState.
        weights: Weight dict (w1..w7). Partial dicts supported.
        locked_assignments: Optional {order_idx: vehicle_idx}.
        driver_preferences: Optional list of rule dicts.
        shift_hard_penalty: Penalty per vehicle exceeding 8h.

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
        shift_hard_penalty=shift_hard_penalty,
    )
