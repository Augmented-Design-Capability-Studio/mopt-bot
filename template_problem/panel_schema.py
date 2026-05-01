"""Gemini structured-output JSON schema for panel patches.

Used by study_port.panel_patch_response_json_schema() to constrain the LLM's
structured output when deriving or patching a panel config.
"""

from __future__ import annotations

from app.problems.schema_shared import ALGORITHM_PARAMS_SCHEMA, CONSTRAINT_TYPES_SCHEMA


def panel_patch_response_json_schema() -> dict:
    """Return the Gemini response_json_schema for a { "problem": ... } patch."""
    return {
        "type": "object",
        "properties": {
            "problem": {
                "type": "object",
                "properties": {
                    "weights": {
                        "type": "object",
                        "description": "Objective weights keyed by weight alias.",
                        "properties": {
                            # TODO: add an entry per weight key with type + description.
                            "obj_a": {
                                "type": "number",
                                "description": "TODO: describe what obj_a penalizes.",
                            },
                            "obj_b": {
                                "type": "number",
                                "description": "TODO: describe what obj_b penalizes.",
                            },
                        },
                        "additionalProperties": False,
                    },
                    "algorithm": {
                        "type": "string",
                        "description": "Metaheuristic algorithm name (e.g. GA, PSO, SA).",
                    },
                    "epochs": {"type": "integer", "description": "Maximum number of iterations."},
                    "pop_size": {"type": "integer", "description": "Population / swarm size."},
                    "random_seed": {"type": "integer", "description": "RNG seed for reproducibility."},
                    "algorithm_params": ALGORITHM_PARAMS_SCHEMA,
                    "constraint_types": CONSTRAINT_TYPES_SCHEMA,
                },
                "additionalProperties": False,
            }
        },
        "required": ["problem"],
        "additionalProperties": False,
    }
