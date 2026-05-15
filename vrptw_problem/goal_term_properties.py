"""VRPTW-specific normalization for `goal_terms[key].properties` fields.

The main backend stays problem-agnostic: it iterates registered ports'
``normalize_goal_term_property`` hooks per property key. Each port owns
validation for the keys it cares about and returns a sentinel telling the
caller to keep, drop, or defer.

VRPTW owns:
- ``driver_preferences``: list of structured rule dicts (per-vehicle
  conditions with penalties).
- ``max_shift_hours``: positive numeric.
"""

from __future__ import annotations

from typing import Any

# Closed enums for driver-preference rule shapes.
_DRIVER_PREF_CONDITIONS: frozenset[str] = frozenset(
    {"avoid_zone", "order_priority", "shift_over_limit"}
)
_DRIVER_PREF_AGGREGATIONS: frozenset[str] = frozenset({"per_stop", "once_per_route"})
_DRIVER_PREF_ORDER_PRIORITIES: frozenset[str] = frozenset({"express", "standard"})

# Closed enum for the search-strategy algorithm carrier. Aliases that the LLM
# might emit (case / abbreviation variations) are folded onto canonical names
# rather than rejected so a confidently-named algorithm doesn't get dropped.
_ALGORITHM_CANONICAL: dict[str, str] = {
    "ga": "GA",
    "genetic": "GA",
    "genetic_algorithm": "GA",
    "pso": "PSO",
    "particle_swarm": "PSO",
    "sa": "SA",
    "simulated_annealing": "SA",
    "swarmsa": "SwarmSA",
    "swarm_sa": "SwarmSA",
    "acor": "ACOR",
}
_ALGORITHM_VALID: frozenset[str] = frozenset({"GA", "PSO", "SA", "SwarmSA", "ACOR"})


def _normalize_driver_preference_rule(raw: Any) -> dict[str, Any] | None:
    """Tolerant per-rule validator.

    Returns ``None`` on any structural failure so the caller can drop the
    bad rule and keep the rest of the list.
    """
    if not isinstance(raw, dict):
        return None
    vid_raw = raw.get("vehicle_idx")
    if isinstance(vid_raw, bool):
        return None
    try:
        vid = int(vid_raw)
    except (TypeError, ValueError):
        return None
    if not 0 <= vid <= 4:
        return None
    cond = str(raw.get("condition") or "").strip().lower()
    if cond not in _DRIVER_PREF_CONDITIONS:
        return None
    pen_raw = raw.get("penalty")
    if isinstance(pen_raw, bool) or not isinstance(pen_raw, (int, float)):
        return None
    if pen_raw < 0:
        return None
    out: dict[str, Any] = {
        "vehicle_idx": vid,
        "condition": cond,
        "penalty": float(pen_raw),
    }
    if cond == "avoid_zone":
        z_raw = raw.get("zone")
        if isinstance(z_raw, bool):
            return None
        try:
            z = int(z_raw)
        except (TypeError, ValueError):
            return None
        if not 1 <= z <= 5:
            return None
        out["zone"] = z
    elif cond == "order_priority":
        op = str(raw.get("order_priority") or "").strip().lower()
        if op not in _DRIVER_PREF_ORDER_PRIORITIES:
            return None
        out["order_priority"] = op
    elif cond == "shift_over_limit":
        lm_raw = raw.get("limit_minutes")
        if lm_raw is not None:
            if (
                isinstance(lm_raw, bool)
                or not isinstance(lm_raw, (int, float))
                or lm_raw <= 0
            ):
                return None
            out["limit_minutes"] = float(lm_raw)
    agg_raw = raw.get("aggregation")
    if agg_raw is not None:
        agg = str(agg_raw).strip().lower()
        if agg in _DRIVER_PREF_AGGREGATIONS:
            out["aggregation"] = agg
    return out


def normalize_goal_term_property(
    prop_key: str, prop_val: Any
) -> tuple[bool, Any] | None:
    """Port hook implementation: ``StudyProblemPort.normalize_goal_term_property``.

    Returns ``None`` for property keys VRPTW doesn't own (caller falls back
    to the next port or generic pass-through). Returns ``(True, value)`` to
    keep the property with the normalized value, or ``(False, None)`` to
    drop it on validation failure.
    """
    if prop_key == "driver_preferences":
        if not isinstance(prop_val, list):
            return (False, None)
        rules = [
            rule
            for raw_rule in prop_val
            if (rule := _normalize_driver_preference_rule(raw_rule)) is not None
        ]
        return (True, rules)
    if prop_key == "max_shift_hours":
        if (
            isinstance(prop_val, bool)
            or not isinstance(prop_val, (int, float))
            or prop_val <= 0
        ):
            return (False, None)
        return (True, float(prop_val))
    if prop_key == "algorithm":
        if not isinstance(prop_val, str):
            return (False, None)
        raw = prop_val.strip()
        if not raw:
            return (False, None)
        if raw in _ALGORITHM_VALID:
            return (True, raw)
        canonical = _ALGORITHM_CANONICAL.get(raw.lower().replace("-", "_"))
        if canonical is None:
            return (False, None)
        return (True, canonical)
    return None
