"""Gemini ``response_json_schema`` for structured knapsack panel / problem patches."""

from __future__ import annotations

from typing import Any

from app.problems.schema_shared import (
    ALGORITHM_PARAMS_SCHEMA,
    CONSTRAINT_TYPES_SCHEMA,
    wrap_panel_patch_schema,
)

_KNAPSACK_WEIGHTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Knapsack benchmark weights — omit keys the user did not discuss. "
        "Never invent names outside value_emphasis, capacity_overflow, selection_sparsity."
    ),
    "properties": {
        "value_emphasis": {"type": "number"},
        "capacity_overflow": {"type": "number"},
        "selection_sparsity": {"type": "number"},
    },
    "additionalProperties": False,
}

KNAPSACK_PROBLEM_PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "weights": _KNAPSACK_WEIGHTS_SCHEMA,
        "only_active_terms": {"type": "boolean"},
        "algorithm": {
            "type": "string",
            "enum": ["GA", "PSO", "SA", "SwarmSA", "ACOR"],
        },
        "algorithm_params": ALGORITHM_PARAMS_SCHEMA,
        "constraint_types": CONSTRAINT_TYPES_SCHEMA,
        "epochs": {"type": "integer"},
        "pop_size": {"type": "integer"},
        "random_seed": {"type": "integer"},
        "early_stop": {"type": "boolean"},
        "early_stop_patience": {"type": "integer"},
        "early_stop_epsilon": {"type": "number"},
        "hard_constraints": {"type": "array", "items": {"type": "string"}},
        "soft_constraints": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def panel_patch_response_json_schema() -> dict[str, Any]:
    return wrap_panel_patch_schema(KNAPSACK_PROBLEM_PATCH_SCHEMA)

