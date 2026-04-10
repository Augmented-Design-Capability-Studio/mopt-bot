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
