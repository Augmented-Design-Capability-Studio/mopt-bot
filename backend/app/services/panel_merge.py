"""Deep-merge panel JSON fragments from the model into the stored panel."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


def _normalize_json_like_strings(value: Any) -> Any:
    """Recursively parse embedded JSON objects/lists when the model stringifies them."""
    if isinstance(value, dict):
        return {k: _normalize_json_like_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_json_like_strings(v) for v in value]
    if isinstance(value, str):
        stripped = value.strip()
        if (
            (stripped.startswith("{") and stripped.endswith("}"))
            or (stripped.startswith("[") and stripped.endswith("]"))
        ):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return value
            if isinstance(parsed, (dict, list)):
                return _normalize_json_like_strings(parsed)
        return value
    return value


def _drop_invalid_problem_weights(value: dict[str, Any]) -> dict[str, Any]:
    """Remove malformed `problem.weights` values so the panel never stores null/string there."""
    problem = value.get("problem")
    if isinstance(problem, dict) and "weights" in problem and not isinstance(problem["weights"], dict):
        problem.pop("weights", None)
    return value


def _preserve_invalid_problem_objects(
    base: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    """
    Guard against malformed model patches for nested problem objects.
    If the model sends `problem.weights: null` (or another non-object), preserve
    the current weights object when one exists; otherwise drop that key.
    """
    problem = patch.get("problem")
    if not isinstance(problem, dict):
        return patch

    if "weights" in problem and not isinstance(problem["weights"], dict):
        base_problem = base.get("problem")
        base_weights = (
            base_problem.get("weights")
            if isinstance(base_problem, dict)
            else None
        )
        if isinstance(base_weights, dict):
            problem["weights"] = deepcopy(base_weights)
        else:
            problem.pop("weights", None)
    return patch


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge patch into base (patch wins for scalars and replaces list values)."""
    base = _drop_invalid_problem_weights(_normalize_json_like_strings(deepcopy(base)))
    patch = _normalize_json_like_strings(patch)
    patch = _preserve_invalid_problem_objects(base, patch)
    out = deepcopy(base)
    for key, val in patch.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(val, dict)
        ):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = deepcopy(val) if isinstance(val, dict) else val
    return _drop_invalid_problem_weights(out)
