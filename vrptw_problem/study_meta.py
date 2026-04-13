"""VRPTW study-facing weight metadata and brief-atomization hints.

Participant-visible aliases map to internal ``w1``–``w7`` via
``study_bridge.WEIGHT_ALIASES``.
"""

from __future__ import annotations

# (alias_key, label, description) — one row per w1–w7 alias shown in the panel.
VRPTW_WEIGHT_DEFINITIONS: list[tuple[str, str, str]] = [
    ("travel_time", "Travel time", "Total route duration and driving minutes."),
    (
        "shift_limit",
        "Shift limit",
        "Per minute past max_shift_hours (summed over vehicles); use a large weight for a near-hard cap.",
    ),
    ("deadline_penalty", "On-time delivery", "Lateness vs customer time windows (per minute late)."),
    ("capacity_penalty", "Load capacity", "Demand exceeding vehicle capacity (per overflow unit)."),
    ("workload_balance", "Workload balance", "Fairness of shift lengths across drivers (variance)."),
    ("worker_preference", "Worker preferences", "Soft assignment rules (zones, priorities, shift shape)."),
    (
        "priority_penalty",
        "Express & priority deadlines",
        "Per late express (or emphasized priority) order after its window close — protects SLA-style orders.",
    ),
    (
        "waiting_time",
        "Driver wait time",
        "Total minutes drivers idle waiting for time windows to open (across all stops and vehicles).",
    ),
]


def weight_item_labels() -> dict[str, str]:
    return {key: label for key, label, _desc in VRPTW_WEIGHT_DEFINITIONS}


def weight_slot_markers() -> dict[str, tuple[str, ...]]:
    """Substrings for brief atomization / config seeding."""
    return {
        "travel_time": (
            "travel time",
            "route duration",
            "driving time",
            "operating time",
            "trip duration",
            "distance",
            "transit",
            "fuel",
            "mileage",
            "fuel cost",
            "operating cost",
            "fuel and operating cost",
        ),
        "shift_limit": (
            "shift limit",
            "shift overtime",
            "overtime minutes",
            "minutes over shift",
            "beyond 8 hours",
            "beyond 8h",
            "exceed max shift",
            "shift length limit",
            "hours over limit",
            "long shift penalty",
            "shift duration hard penalty",
            "shift hard penalty",
        ),
        "deadline_penalty": (
            "on-time delivery",
            "deadline penalty",
            "lateness penalty",
            "time window",
            "punctual",
            "on-time",
            "deadline",
        ),
        "capacity_penalty": (
            "load capacity limits",
            "capacity penalty",
            "capacity",
            "overload",
            "vehicle capacity",
        ),
        "workload_balance": ("workload balance", "fair", "equitable", "balanced workload"),
        "worker_preference": (
            "worker preferences",
            "worker preference",
            "driver preference",
            "driver preferences",
        ),
        "priority_penalty": (
            "express",
            "express order",
            "express orders",
            "priority order",
            "priority orders",
            "priority deadline",
            "priority-order",
            "vip",
            "sla",
            "urgent",
        ),
        "waiting_time": (
            "driver wait time",
            "waiting time",
            "idle time",
            "dwell time",
            "wait at stop",
            "early arrival",
        ),
    }
