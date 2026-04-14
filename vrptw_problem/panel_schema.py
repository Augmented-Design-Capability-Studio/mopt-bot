"""Gemini ``response_json_schema`` for structured VRPTW panel / problem patches."""

from __future__ import annotations

from typing import Any

from app.problems.schema_shared import ALGORITHM_PARAMS_SCHEMA, wrap_panel_patch_schema

_VRPTW_WEIGHTS_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Only these participant-facing objective keys exist — omit keys the user did not discuss. "
        "Never invent names. Time, distance, fuel, or operating-time language maps to travel_time only. "
        "Shift hours beyond the max_shift_hours limit → shift_limit."
    ),
    "properties": {
        "travel_time": {"type": "number"},
        "shift_limit": {"type": "number"},
        "deadline_penalty": {"type": "number"},
        "capacity_penalty": {"type": "number"},
        "workload_balance": {"type": "number"},
        "worker_preference": {"type": "number"},
        "priority_penalty": {"type": "number"},
        "waiting_time": {
            "type": "number",
            "description": (
                "Penalty per minute a driver arrives more than early_arrival_threshold_min "
                "minutes before a time window opens. Arrivals within the grace period are free."
            ),
        },
    },
    "additionalProperties": False,
}

_DRIVER_PREFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vehicle_idx": {"type": "integer"},
        "condition": {
            "type": "string",
            "description": (
                "avoid_zone, order_priority, shift_over_limit; legacy: zone_d, express_order, shift_over_hours"
            ),
        },
        "penalty": {"type": "number"},
        "zone": {"type": "integer"},
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
        "early_arrival_threshold_min": {
            "type": "number",
            "description": (
                "Grace period in minutes before the waiting_time penalty applies. "
                "Arrivals within this window are not penalised. Default 30."
            ),
        },
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
    return wrap_panel_patch_schema(VRPTW_PROBLEM_PATCH_SCHEMA)

