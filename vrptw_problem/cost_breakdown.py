"""VRPTW cost-term spec table consumed by the shared contribution builder.

The actual list-construction lives in
``backend/app/problems/cost_breakdown.py``; this module just declares the
``alias → (weight key, metric key, label, unit)`` mapping for VRPTW's eight
soft goal terms.  See ``vrptw_problem/evaluator.py:simulate_routes`` for the
cost formula these specs mirror.
"""

from __future__ import annotations

from app.problems.cost_breakdown import CostTermSpec

# Order here drives display order in the breakdown card grid.
SPECS: tuple[CostTermSpec, ...] = (
    CostTermSpec("travel_time",          "Travel time",         "w1", "travel_time",            "min"),
    CostTermSpec("shift_limit",          "Shift overtime",      "w2", "shift_overtime_minutes", "min"),
    CostTermSpec("lateness_penalty",     "Punctuality (late)",  "w3", "tw_violation_min",       "min"),
    CostTermSpec("capacity_penalty",     "Capacity overflow",   "w4", "capacity_overflow",      "units"),
    CostTermSpec("workload_balance",     "Workload variance",   "w5", "workload_variance",      ""),
    CostTermSpec("worker_preference",    "Driver preferences",  "w6", "driver_penalty",         "units"),
    CostTermSpec("express_miss_penalty", "Express misses",      "w7", "express_late_count",     "late"),
    CostTermSpec("waiting_time",         "Idle wait",           "w8", "wait_time",              "min"),
)
