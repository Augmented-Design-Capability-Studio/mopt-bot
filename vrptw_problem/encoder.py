"""
Solution encoding and decoding for QuickBite VRPTW.

Uses permutation encoding with vehicle separators:
- 34 positions: 30 orders + 4 separators
- Real-valued vector in [0, 34]; sort indices to decode
- The 4 indices with lowest values are separator positions
"""

import numpy as np
from typing import Optional


N_ORDERS = 30
N_VEHICLES = 5
N_SEPARATORS = N_VEHICLES - 1  # 4
VECTOR_LEN = N_ORDERS + N_SEPARATORS  # 34

# Order indices 0..29; separator indices 30,31,32,33
ORDER_INDICES = list(range(N_ORDERS))
SEPARATOR_INDICES = list(range(N_ORDERS, VECTOR_LEN))


def decode_solution(
    position_vector: np.ndarray,
    n_orders: int = N_ORDERS,
    n_vehicles: int = N_VEHICLES,
    locked_assignments: Optional[dict[int, int]] = None,
) -> list[list[int]]:
    """
    Decode a position vector into vehicle routes.

    The 4 smallest values in the vector correspond to separator positions,
    which divide the order permutation into 5 vehicle routes.

    Args:
        position_vector: Length-34 float array with values in [0, 34].
        n_orders: Number of orders (default 30).
        n_vehicles: Number of vehicles (default 5).
        locked_assignments: Optional dict {order_index: vehicle_index} to
            forcibly assign orders to vehicles.

    Returns:
        List of 5 lists, each containing order indices for that vehicle.
    """
    if locked_assignments is None:
        locked_assignments = {}

    n_sep = n_vehicles - 1
    vec = np.asarray(position_vector)
    if len(vec) != n_orders + n_sep:
        vec = np.resize(vec, n_orders + n_sep)

    # Argsort: index with smallest value comes first
    sorted_indices = np.argsort(vec)

    # Separators are entities 30,31,32,33 (or n_orders..n_orders+n_sep-1)
    # Walk sorted_indices, accumulate orders per vehicle until separator
    sep_entities = set(range(n_orders, n_orders + n_sep))
    routes = [[] for _ in range(n_vehicles)]
    current_vehicle = 0
    for idx in sorted_indices:
        if idx in sep_entities:
            current_vehicle += 1
        else:
            routes[current_vehicle].append(int(idx))

    # Apply locked assignments: move locked orders to their assigned vehicle
    for order_idx, vehicle_idx in locked_assignments.items():
        if order_idx < 0 or order_idx >= n_orders or vehicle_idx < 0 or vehicle_idx >= n_vehicles:
            continue
        # Remove from current route
        for r in routes:
            if order_idx in r:
                r.remove(order_idx)
                break
        # Insert at correct position in target vehicle (append for simplicity)
        routes[vehicle_idx].append(order_idx)

    return routes


def encode_random_solution(rng: np.random.RandomState) -> np.ndarray:
    """
    Generate a valid random position vector.

    Args:
        rng: Seeded RandomState for reproducibility.

    Returns:
        Length-34 float array with values in [0, 34].
    """
    return rng.uniform(0.0, 34.0, size=VECTOR_LEN)


def encode_routes_as_vector(routes: list[list[int]]) -> np.ndarray:
    """
    Encode specific vehicle routes into a position vector.

    Assigns ascending position values so that argsort decodes back to the
    exact routes in the given order.

    Args:
        routes: List of N_VEHICLES lists of order indices.

    Returns:
        Length-34 float array.
    """
    vec = np.full(VECTOR_LEN, float(VECTOR_LEN), dtype=float)
    pos = 0.0
    for v_idx, route in enumerate(routes):
        for o_idx in route:
            if 0 <= o_idx < N_ORDERS:
                vec[o_idx] = pos
                pos += 1.0
        if v_idx < N_VEHICLES - 1:
            sep_idx = N_ORDERS + v_idx
            vec[sep_idx] = pos
            pos += 1.0
    return vec


def encode_greedy_solution(
    orders: list,
    locked_assignments: Optional[dict[int, int]] = None,
    rng: Optional[np.random.RandomState] = None,
) -> np.ndarray:
    """
    Build a time-window-aware greedy solution and encode it as a position vector.

    Sorts unassigned orders by (window_open, zone) to cluster temporally and
    geographically coherent stops, then distributes them across vehicles using
    a round-robin that respects estimated feasibility. Passing different ``rng``
    seeds produces diverse starting points for population-based algorithms.

    Args:
        orders: List of Order objects (length N_ORDERS).
        locked_assignments: Optional {order_idx: vehicle_idx} forced assignments.
        rng: RandomState used for tie-breaking diversity; None uses seed 0.

    Returns:
        Length-34 float array suitable for use as a starting position.
    """
    from vrptw_problem.vehicles import VEHICLES
    from vrptw_problem.traffic_api import BASE_TRAVEL_MATRIX

    if locked_assignments is None:
        locked_assignments = {}
    if rng is None:
        rng = np.random.RandomState(0)

    routes: list[list[int]] = [[] for _ in range(N_VEHICLES)]

    # Place locked orders first
    for o_idx, v_idx in locked_assignments.items():
        if 0 <= o_idx < N_ORDERS and 0 <= v_idx < N_VEHICLES:
            routes[v_idx].append(o_idx)

    locked_set = set(locked_assignments.keys())
    unassigned = [i for i in range(N_ORDERS) if i not in locked_set]

    # Sort by window_open then zone for time-coherent, geographically compact groups.
    # Small random perturbation creates diversity across seeds.
    noise = rng.uniform(0.0, 5.0, len(unassigned))  # up to 5-min jitter on window
    order_noise = {order_idx: noise[pos] for pos, order_idx in enumerate(unassigned)}
    unassigned.sort(key=lambda i: (orders[i].time_window_open + order_noise[i], orders[i].zone))

    # Track each vehicle's current zone and earliest available time
    v_zone = [v.start_zone for v in VEHICLES]
    v_time = [float(v.shift_start_min) for v in VEHICLES]

    for o_idx in unassigned:
        order = orders[o_idx]
        # Pick the vehicle that can serve this order with the least wait+lateness penalty
        best_v = 0
        best_score = float("inf")
        for v_idx in range(N_VEHICLES):
            base_tt = float(BASE_TRAVEL_MATRIX[v_zone[v_idx]][order.zone])
            arrival = v_time[v_idx] + base_tt
            wait = max(0.0, float(order.time_window_open) - arrival)
            lateness = max(0.0, arrival - float(order.time_window_close))
            score = arrival + wait * 0.1 + lateness * 200.0
            if score < best_score:
                best_score = score
                best_v = v_idx

        order_obj = orders[o_idx]
        base_tt = float(BASE_TRAVEL_MATRIX[v_zone[best_v]][order_obj.zone])
        arrival = v_time[best_v] + base_tt
        service_start = max(arrival, float(order_obj.time_window_open))
        v_time[best_v] = service_start + order_obj.service_time
        v_zone[best_v] = order_obj.zone
        routes[best_v].append(o_idx)

    return encode_routes_as_vector(routes)
