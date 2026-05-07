"""Shared Gemini JSON-schema fragments used by multiple study benchmarks."""

from __future__ import annotations

from typing import Any

# Union of MEALpy keys the study stack allows (see algorithm_catalog).
_ALGORITHM_PARAMS_PROPERTY_NAMES: tuple[str, ...] = (
    "pc",
    "pm",
    "c1",
    "c2",
    "w",
    "temp_init",
    "cooling_rate",
    "max_sub_iter",
    "t0",
    "t1",
    "move_count",
    "mutation_rate",
    "mutation_step_size",
    "mutation_step_size_damp",
    "sample_count",
    "intent_factor",
    "zeta",
)

ALGORITHM_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Optional tuning object. Only use keys that exist for the selected algorithm — "
        "GA: pc, pm. PSO: c1, c2, w. SA: temp_init, cooling_rate. SwarmSA: max_sub_iter, t0, t1, "
        "move_count, mutation_rate, mutation_step_size, mutation_step_size_damp. "
        "ACOR: sample_count, intent_factor, zeta. "
        "Omit unless the user discussed hyperparameters; never invent other names."
    ),
    "properties": {name: {"type": "number"} for name in _ALGORITHM_PARAMS_PROPERTY_NAMES},
    "additionalProperties": False,
}

CONSTRAINT_TYPES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Per-goal-term classification in the participant panel. "
        "Keys are weight aliases. Values: soft, hard, custom. "
        "Objective is the implicit default when a key is omitted."
    ),
    "additionalProperties": {
        "type": "string",
        "enum": ["soft", "hard", "custom"],
    },
}

# Default `goal_terms[key].properties` shape — permissive. Each problem port
# overrides via `goal_term_properties_schema()` when it has typed child fields
# (e.g. VRPTW's `driver_preferences`, `max_shift_hours`). This module stays
# problem-agnostic; it only declares the slot.
_DEFAULT_GOAL_TERM_PROPERTIES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Optional term-specific metadata. Default is an open object — problem "
        "ports add typed child fields by overriding "
        "`StudyProblemPort.goal_term_properties_schema()`."
    ),
    "additionalProperties": True,
}


def goal_term_entry_schema(
    properties_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a goal-term entry schema with a problem-specific `properties` shape.

    `properties_schema` is the JSON schema for `goal_terms[key].properties` —
    each port supplies its own (see `StudyProblemPort.goal_term_properties_schema`).
    Pass `None` to get the permissive default.
    """
    return {
        "type": "object",
        "description": (
            "Canonical per-goal-term representation. `weight` is numeric emphasis, "
            "`type` is objective/soft/hard/custom, `locked` mirrors lock state, "
            "`properties` carries optional term-specific metadata, and "
            "`evidence_item_ids` cites the brief items[] ids that justify this term "
            "(at least one for newly-introduced terms)."
        ),
        "properties": {
            "weight": {"type": "number"},
            "type": {"type": "string", "enum": ["objective", "soft", "hard", "custom"]},
            "locked": {"type": "boolean"},
            "rank": {"type": "integer", "minimum": 1},
            "properties": properties_schema or _DEFAULT_GOAL_TERM_PROPERTIES_SCHEMA,
            "evidence_item_ids": {
                "type": "array",
                "description": (
                    "Ids of brief items[] (gathered in waterfall; gathered or assumption "
                    "in agile/demo) whose text justifies this goal term. Required for "
                    "newly-introduced terms; existing terms are tolerated without it."
                ),
                "items": {"type": "string"},
            },
        },
        "required": ["weight"],
        "additionalProperties": False,
    }


def goal_terms_schema(
    properties_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a `goal_terms` map schema with a problem-specific entry shape."""
    return {
        "type": "object",
        "description": (
            "Goal-term map keyed by weight alias (e.g. travel_time, capacity_penalty). "
            "Each entry can include weight, type, lock flag, and optional term-specific properties."
        ),
        "additionalProperties": goal_term_entry_schema(properties_schema),
    }


# Back-compat constants — permissive defaults used when no port-specific
# schema is available. Problem-aware call sites should call
# `goal_term_entry_schema(...)` / `goal_terms_schema(...)` with the port's
# properties schema instead.
GOAL_TERM_ENTRY_SCHEMA: dict[str, Any] = goal_term_entry_schema()
GOAL_TERMS_SCHEMA: dict[str, Any] = goal_terms_schema()


def wrap_panel_patch_schema(problem_inner: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": "PanelPatch",
        "type": "object",
        "properties": {
            "problem": problem_inner,
        },
        "required": ["problem"],
        "additionalProperties": False,
    }
