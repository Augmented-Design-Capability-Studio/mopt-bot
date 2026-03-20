"""Deep-merge panel JSON fragments from the model into the stored panel."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge patch into base (patch wins for scalars and replaces list values)."""
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
    return out
