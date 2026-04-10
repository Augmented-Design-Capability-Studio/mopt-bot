"""Canonical algorithm names and algorithm_params keys (must match vrptw_problem/optimizer.py)."""

from __future__ import annotations

from typing import Any

# Allowed algorithm_params keys per algorithm — same filter sets as optimizer model construction.
ALLOWED_ALGORITHM_PARAMS: dict[str, frozenset[str]] = {
    "GA": frozenset({"pc", "pm"}),
    "PSO": frozenset({"c1", "c2", "w"}),
    "SA": frozenset({"temp_init", "cooling_rate"}),
    "SwarmSA": frozenset(
        {
            "max_sub_iter",
            "t0",
            "t1",
            "move_count",
            "mutation_rate",
            "mutation_step_size",
            "mutation_step_size_damp",
        }
    ),
    "ACOR": frozenset({"sample_count", "intent_factor", "zeta"}),
}

# Defaults duplicated from vrptw_problem/optimizer._default_algorithm_params (keep in sync).
DEFAULT_ALGORITHM_PARAMS: dict[str, dict[str, float | int]] = {
    "GA": {"pc": 0.9, "pm": 0.05},
    "PSO": {"c1": 2.05, "c2": 2.05, "w": 0.4},
    "SA": {"temp_init": 100, "cooling_rate": 0.99},
    "SwarmSA": {
        "max_sub_iter": 5,
        "t0": 1000,
        "t1": 1,
        "move_count": 5,
        "mutation_rate": 0.1,
        "mutation_step_size": 0.1,
        "mutation_step_size_damp": 0.99,
    },
    "ACOR": {"sample_count": 25, "intent_factor": 0.5, "zeta": 1.0},
}


def normalize_algorithm_name(raw: str) -> str | None:
    s = str(raw or "").strip().upper()
    if s == "SWARMSA":
        return "SwarmSA"
    if s in ("GA", "PSO", "SA", "ACOR"):
        return s
    return None


def canonical_algorithm_stored(raw: Any) -> str | None:
    """Same normalization as adapter.parse_problem_config uses for stored `algorithm` strings."""
    return normalize_algorithm_name(str(raw or "GA"))


def allowed_param_keys(algorithm: str) -> frozenset[str]:
    return ALLOWED_ALGORITHM_PARAMS.get(algorithm, frozenset())


def default_algorithm_params(algorithm: str) -> dict[str, float | int]:
    return dict(DEFAULT_ALGORITHM_PARAMS.get(algorithm, {}))


def filter_algorithm_params(
    algorithm: str,
    params: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """
    Keep only keys allowed for `algorithm`. None / missing input stays None.
    Returns (filtered_dict_or_None, warnings for dropped keys).
    """
    if params is None:
        return None, []
    if not isinstance(params, dict):
        return None, ["algorithm_params was not an object; ignored."]
    allowed = allowed_param_keys(algorithm)
    if not allowed:
        if params:
            return None, [f"algorithm_params ignored for unknown algorithm {algorithm!r}."]
        return None, []
    out: dict[str, Any] = {}
    warnings: list[str] = []
    for k, v in params.items():
        ks = str(k)
        if ks in allowed:
            out[ks] = v
        else:
            warnings.append(
                f"Algorithm parameter {ks!r} is not used by {algorithm}; it was removed from the configuration."
            )
    return out, warnings


def param_value_is_default(algorithm: str, key: str, value: Any) -> bool:
    """True if value matches catalog default for this algorithm+key (numeric tolerant)."""
    defaults = DEFAULT_ALGORITHM_PARAMS.get(algorithm) or {}
    if key not in defaults:
        return False
    d = defaults[key]
    if isinstance(value, bool) or isinstance(d, bool):
        return value == d
    try:
        fv = float(value)
        fd = float(d)
    except (TypeError, ValueError):
        return False
    return abs(fv - fd) <= 1e-9 * max(1.0, abs(fd))
