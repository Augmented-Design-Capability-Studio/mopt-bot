"""
Vehicle definitions for QuickBite Fleet Scheduling.

Total demand (seed=0) = 88. Capacities set so feasible solutions exist with headroom.
"""

from dataclasses import dataclass


@dataclass
class Vehicle:
    """Vehicle definition."""
    vehicle_id: int
    name: str
    capacity: int
    start_zone: int
    shift_start_min: int  # minutes since midnight
    max_hours: float = 8.0


# Default fleet
VEHICLES = [
    Vehicle(0, "Alice", 22, 0, 480, 8.0),   # Depot, 08:00
    Vehicle(1, "Bob", 20, 0, 480, 8.0),
    Vehicle(2, "Carol", 20, 0, 540, 8.0),   # 09:00
    Vehicle(3, "Dave", 22, 0, 480, 8.0),
    Vehicle(4, "Eve", 20, 5, 570, 8.0),     # Zone E, 09:30
]
