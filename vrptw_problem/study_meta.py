"""VRPTW study-facing weight metadata and brief-atomization hints.

Participant-visible aliases map to internal ``w1``–``w7`` via
``study_bridge.WEIGHT_ALIASES``.
"""

from __future__ import annotations

# (alias_key, label, description, direction) — one row per w1–w7 alias shown in the panel.
VRPTW_WEIGHT_DEFINITIONS: list[tuple[str, str, str, str]] = [
    ("travel_time", "Travel time", "Total route duration and driving minutes.", "minimize"),
    (
        "shift_limit",
        "Shift limit",
        "Per minute past max_shift_hours (summed over vehicles); use a large weight for a near-hard cap.",
        "minimize",
    ),
    ("deadline_penalty", "On-time delivery", "Lateness vs customer time windows (per minute late).", "minimize"),
    ("capacity_penalty", "Load capacity", "Demand exceeding vehicle capacity (per overflow unit).", "minimize"),
    ("workload_balance", "Workload balance", "Fairness of drive+service time across drivers (variance; excludes idle pre-window wait).", "minimize"),
    ("worker_preference", "Worker preferences", "Soft assignment rules (zones, priorities, shift shape).", "minimize"),
    (
        "priority_penalty",
        "Express & priority deadlines",
        "Per late express (or emphasized priority) order after its window close.",
        "minimize",
    ),
    (
        "waiting_time",
        "Idle Wait Time",
        "Penalty per idle minute a driver waits before a time window opens.",
        "minimize",
    ),
]


def weight_item_labels() -> dict[str, str]:
    return {key: label for key, label, _desc, _direction in VRPTW_WEIGHT_DEFINITIONS}


# Ordered weight keys that count toward the agile gate ("at least one goal term").
# ``waiting_time`` is intentionally omitted: it penalizes idle wait time but should
# not independently satisfy the gate without a primary routing or delivery objective.
VRPTW_WEIGHT_DISPLAY_KEYS: tuple[str, ...] = (
    "travel_time",
    "shift_limit",
    "workload_balance",
    "deadline_penalty",
    "capacity_penalty",
    "priority_penalty",
    "worker_preference",
)


def weight_display_keys() -> list[str]:
    return list(VRPTW_WEIGHT_DISPLAY_KEYS)


def worker_preference_key() -> str:
    return "worker_preference"


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
            "early arrival",
            "early arrival penalty",
            "arrive early",
            "arrives early",
            "arriving early",
            "arrived early",
            "idle wait",
            "idle time",
            "waiting time",
            "wait before window",
            "early dwell",
            "dwell before window",
            "pre-window",
            "too early",
        ),
    }
