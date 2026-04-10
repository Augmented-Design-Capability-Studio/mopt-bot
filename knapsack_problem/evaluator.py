"""Scalar objective for a toy knapsack (minimization)."""

from __future__ import annotations

from typing import Any

import numpy as np

from instance import Item

WEIGHT_KEYS = ("value_emphasis", "capacity_overflow", "selection_sparsity")

DEFAULT_WEIGHTS: dict[str, float] = {
    "value_emphasis": 1.0,
    "capacity_overflow": 50.0,
    "selection_sparsity": 0.5,
}


def build_knapsack_weights(user_weights: dict[str, Any], only_active_terms: bool) -> dict[str, float]:
    base = {k: 0.0 for k in WEIGHT_KEYS} if only_active_terms else dict(DEFAULT_WEIGHTS)
    for k in WEIGHT_KEYS:
        if k in user_weights:
            base[k] = float(user_weights[k])
    return base


def _as_binary(vec: np.ndarray) -> np.ndarray:
    x = np.asarray(vec, dtype=float).ravel()
    return (x >= 0.5).astype(np.int32)


def evaluate_selection(
    vec: np.ndarray,
    items: list[Item],
    capacity: int,
    weights: dict[str, float],
) -> tuple[float, dict[str, Any]]:
    sel = _as_binary(vec)
    w_arr = np.array([it.weight for it in items], dtype=float)
    v_arr = np.array([it.value for it in items], dtype=float)
    tw = float(np.dot(sel, w_arr))
    tv = float(np.dot(sel, v_arr))
    overflow = max(0.0, tw - float(capacity))
    n_sel = int(sel.sum())
    max_val = float(v_arr.sum()) or 1.0

    wv = weights["value_emphasis"]
    wo = weights["capacity_overflow"]
    ws = weights["selection_sparsity"]

    value_term = -(tv / max_val) * 100.0
    cost = wv * value_term + wo * overflow + ws * float(n_sel)

    metrics = {
        "total_value": tv,
        "total_weight": tw,
        "overflow": overflow,
        "selected_count": n_sel,
        "feasible": overflow <= 0,
        "value_term": value_term,
    }
    return float(cost), metrics
