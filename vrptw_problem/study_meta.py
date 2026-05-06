"""VRPTW study-facing weight metadata.

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
    ("lateness_penalty", "Overall punctuality", "Lateness vs all customer time windows (per minute late).", "minimize"),
    ("capacity_penalty", "Load capacity", "Demand exceeding vehicle capacity (per overflow unit).", "minimize"),
    ("workload_balance", "Workload balance", "Fairness of drive+service time across drivers (variance; excludes idle pre-window wait).", "minimize"),
    ("worker_preference", "Worker preferences", "Soft assignment rules (zones, priorities, shift shape).", "minimize"),
    (
        "express_miss_penalty",
        "Express order misses",
        "Per late express order after its window close (express-only misses).",
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
    "lateness_penalty",
    "capacity_penalty",
    "express_miss_penalty",
    "worker_preference",
)


def weight_display_keys() -> list[str]:
    return list(VRPTW_WEIGHT_DISPLAY_KEYS)


def worker_preference_key() -> str:
    return "worker_preference"
