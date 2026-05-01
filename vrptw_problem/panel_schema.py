"""Gemini ``response_json_schema`` for structured VRPTW panel / problem patches."""

from __future__ import annotations

from typing import Any

from app.problems.schema_shared import (
    ALGORITHM_PARAMS_SCHEMA,
    CONSTRAINT_TYPES_SCHEMA,
    wrap_panel_patch_schema,
)

_VRPTW_WEIGHTS_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Only these participant-facing objective keys exist — omit keys the user did not discuss. "
        "Never invent names. Time, distance, fuel, or operating-time language maps to travel_time only. "
        "Shift hours beyond the max_shift_hours limit → shift_limit. "
        "Idle wait time penalty → waiting_time (penalty per minute a driver waits before a window opens)."
    ),
    "properties": {
        "travel_time": {"type": "number"},
        "shift_limit": {"type": "number"},
        "lateness_penalty": {"type": "number"},
        "capacity_penalty": {"type": "number"},
        "workload_balance": {"type": "number"},
        "worker_preference": {"type": "number"},
        "express_miss_penalty": {"type": "number"},
        "waiting_time": {
            "type": "number",
            "description": (
                "Penalty per idle minute a driver waits before a time window opens (total wait, no grace period). "
                "Use when the user wants to minimize idle time or schedule slack. Default 100."
            ),
        },
    },
    "additionalProperties": False,
}

_DRIVER_PREFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vehicle_idx": {
            "type": "integer",
            "description": "Worker index mapping: Alice=0, Bob=1, Carol=2, Dave=3, Eve=4.",
        },
        "condition": {
            "type": "string",
            "description": (
                "avoid_zone, order_priority, shift_over_limit"
            ),
        },
        "penalty": {"type": "number"},
        "zone": {
            "type": "integer",
            "description": "Delivery zone id for avoid_zone only: A=1, B=2, C=3, D=4, E=5. Depot=0 is invalid for avoid_zone.",
        },
        "order_priority": {
            "type": "string",
            "enum": ["express", "standard"],
            "description": "Must be exactly express or standard (not low/high synonyms).",
        },
        "limit_minutes": {"type": "number"},
        "hours": {"type": "number"},
        "aggregation": {"type": "string"},
    },
    "required": ["vehicle_idx", "condition", "penalty"],
    "additionalProperties": False,
}

VRPTW_PROBLEM_PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "weights": _VRPTW_WEIGHTS_OBJECT_SCHEMA,
        "only_active_terms": {"type": "boolean"},
        "driver_preferences": {
            "type": "array",
            "items": _DRIVER_PREFERENCE_SCHEMA,
        },
        "max_shift_hours": {"type": "number"},
        "locked_assignments": {
            "type": "object",
            "description": "Map task index string to vehicle index integer.",
            "additionalProperties": {"type": "integer"},
        },
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
        "use_greedy_init": {
            "type": "boolean",
            "description": (
                "When true (default), seeds a portion of the initial population with "
                "time-window-aware greedy solutions instead of purely random ones."
            ),
        },
        "hard_constraints": {"type": "array", "items": {"type": "string"}},
        "soft_constraints": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def panel_patch_response_json_schema() -> dict[str, Any]:
    return wrap_panel_patch_schema(VRPTW_PROBLEM_PATCH_SCHEMA)

