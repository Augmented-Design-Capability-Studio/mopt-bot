"""Knapsack cost-term spec table consumed by the shared contribution builder.

The actual list-construction lives in
``backend/app/problems/cost_breakdown.py``; this module just declares the
``alias → (weight key, metric key, label, unit)`` mapping for knapsack's
three soft goal terms.  See ``knapsack_problem/evaluator.py:evaluate_selection``
for the cost formula these specs mirror.
"""

from __future__ import annotations

from app.problems.cost_breakdown import CostTermSpec

SPECS: tuple[CostTermSpec, ...] = (
    CostTermSpec("value_emphasis",     "Value emphasis",     "value_emphasis",     "value_term",     ""),
    CostTermSpec("capacity_overflow",  "Capacity overflow",  "capacity_overflow",  "overflow",       "units"),
    CostTermSpec("selection_sparsity", "Selection sparsity", "selection_sparsity", "selected_count", "items"),
)
