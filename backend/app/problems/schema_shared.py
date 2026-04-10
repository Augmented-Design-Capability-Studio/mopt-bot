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
