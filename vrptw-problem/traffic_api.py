"""
Simulated Traffic API - Travel times between zones.

Provides travel time estimates based on a base matrix, time-of-day multipliers,
roadworks, and stochastic noise. Designed to be replaceable by a real traffic
API in future (e.g., for user study "API reveal" phase).

All times internally in minutes since midnight (e.g., 480 = 08:00).
"""

import numpy as np

# Zone indices
ZONE_DEPOT = 0
ZONE_A = 1  # Riverside
ZONE_B = 2  # Harbor
ZONE_C = 3  # Uptown
ZONE_D = 4  # Westgate
ZONE_E = 5  # Northgate

ZONE_NAMES = ["Depot", "A", "B", "C", "D", "E"]

# Base travel time matrix (minutes, symmetric)
#         Depot   A     B     C     D     E
BASE_TRAVEL_MATRIX = np.array([
    [0, 12, 18, 25, 30, 22],   # Depot
    [12, 0, 8, 15, 20, 14],    # A
    [18, 8, 0, 10, 18, 12],    # B
    [25, 15, 10, 0, 9, 11],    # C
    [30, 20, 18, 9, 0, 7],     # D
    [22, 14, 12, 11, 7, 0],    # E
], dtype=float)

# Traffic periods: (start_min, end_min, multiplier)
# Period 1: 07:00-09:30 = 420-570
# Period 2: 09:30-11:30 = 570-690
# Period 3: 11:30-13:00 = 690-780
# Period 4: 13:00-16:00 = 780-960
# Period 5: 16:00-18:00 = 960-1080
TRAFFIC_PERIODS = [
    (420, 570, 1.4),   # morning peak
    (570, 690, 1.0),   # normal
    (690, 780, 1.3),   # lunch surge
    (780, 960, 1.0),   # normal
    (960, 1080, 1.5),  # evening peak
]

# Zone D roadworks: 08:00-12:00 = 480-720
ROADWORKS_START = 480
ROADWORKS_END = 720


def get_traffic_multiplier(current_time_minutes: float) -> float:
    """Return traffic multiplier for given time of day."""
    for start, end, mult in TRAFFIC_PERIODS:
        if start <= current_time_minutes < end:
            return mult
    return 1.0


def get_zone_d_roadworks_penalty(current_time_minutes: float) -> float:
    """Return 5 min penalty if in Zone D roadworks window, else 0."""
    if ROADWORKS_START <= current_time_minutes < ROADWORKS_END:
        return 5.0
    return 0.0


def get_travel_time(
    from_zone: int,
    to_zone: int,
    current_time_minutes: float,
    rng: np.random.RandomState,
) -> float:
    """
    Compute travel time in minutes between two zones.

    Uses base matrix, traffic multipliers, roadworks, and stochastic noise.

    Args:
        from_zone: Origin zone index (0-5).
        to_zone: Destination zone index (0-5).
        current_time_minutes: Minutes since midnight.
        rng: Seeded RandomState for reproducibility.

    Returns:
        Travel time in minutes (float).
    """
    base = BASE_TRAVEL_MATRIX[from_zone, to_zone]
    mult = get_traffic_multiplier(current_time_minutes)
    time_with_traffic = base * mult

    # Zone D roadworks: add 5 min if trip involves Zone D (4) between 08:00-12:00
    if ZONE_D in (from_zone, to_zone):
        time_with_traffic += get_zone_d_roadworks_penalty(current_time_minutes)

    # Stochastic noise: Uniform(0.9, 1.1)
    noise = rng.uniform(0.9, 1.1)
    return time_with_traffic * noise
