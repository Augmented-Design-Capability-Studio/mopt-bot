"""
VRPTW study bridge: neutral problem JSON ↔ vrptw_problem optimizer/evaluator.

Loaded with this package root on sys.path. Uses ``app.*`` when run inside the MOPT backend.
"""

from __future__ import annotations

import difflib
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np

from app.algorithm_catalog import filter_algorithm_params, DEFAULT_EPOCHS, DEFAULT_POP_SIZE
from app.problems.exceptions import RunCancelled

_VRPTW_ROOT = Path(__file__).resolve().parent

# Human-readable alias names shown in the participant panel and used by the agent.
# Maps alias → internal w1–w7 key expected by build_weights / evaluator.
# w2 / panel alias ``shift_limit`` scales total minutes beyond max_shift_hours (summed over vehicles).
WEIGHT_ALIASES: dict[str, str] = {
    "travel_time":       "w1",
    "shift_limit":       "w2",
    "lateness_penalty":  "w3",
    "capacity_penalty":  "w4",
    "workload_balance":  "w5",
    "worker_preference": "w6",
    "express_miss_penalty": "w7",
    "waiting_time":      "w8",
}

# Legacy keys accepted for backward compatibility (input only).
LEGACY_WEIGHT_ALIASES: dict[str, str] = {
    "deadline_penalty": "lateness_penalty",
    "priority_penalty": "express_miss_penalty",
}

# Reverse map for displaying wN keys as human-readable aliases.
WEIGHT_ALIAS_REVERSE: dict[str, str] = {v: k for k, v in WEIGHT_ALIASES.items()}

# Internal w1–w7 keys the solver accepts directly (pass-through for legacy configs).
_WEIGHT_VALID_WN: frozenset[str] = frozenset(WEIGHT_ALIASES.values())

_TERM_TYPE_VALUES = frozenset({"objective", "soft", "hard", "custom"})

# Keyword map: common alternative phrasings → canonical alias.
# Enables fuzzy recovery when a user (or the agent) types a close but non-exact key.
_WEIGHT_KEYWORD_MAP: dict[str, str] = {
    # travel_time (avoid bare "route"/"routing" — too easy to false-positive; use difflib on full keys)
    "travel":          "travel_time",
    "distance":        "travel_time",
    "transit":         "travel_time",
    "route_length":    "travel_time",
    # Fuel / mileage phrasing is modelled as route-minute pressure → travel_time (same as w1 story).
    "fuel":            "travel_time",
    "mileage":         "travel_time",
    "operating_cost":  "travel_time",
    # shift_limit (w2) — avoid bare "overtime" (ambiguous)
    "shift_limit":     "shift_limit",
    "shift_overtime":  "shift_limit",
    "shift_over":      "shift_limit",
    "hours_over_8":    "shift_limit",
    # lateness_penalty
    "deadline":        "lateness_penalty",
    "late":            "lateness_penalty",
    "time_window":     "lateness_penalty",
    "on_time":         "lateness_penalty",
    "punctuality":     "lateness_penalty",
    "lateness":        "lateness_penalty",
    "tardiness":       "lateness_penalty",
    "window":          "lateness_penalty",
    "timeliness":      "lateness_penalty",
    # capacity_penalty
    "capacity":        "capacity_penalty",
    "load":            "capacity_penalty",
    "overload":        "capacity_penalty",
    "overflow":        "capacity_penalty",
    "packing":         "capacity_penalty",
    "weight_limit":    "capacity_penalty",
    # workload_balance (omit bare "balance"/"shift" — map to wrong objective too often)
    "fairness":        "workload_balance",
    "equity":          "workload_balance",
    "workload":        "workload_balance",
    "shift_fairness":  "workload_balance",
    "shift_balance":   "workload_balance",
    "equitable":       "workload_balance",
    # worker_preference
    "preference":      "worker_preference",
    "worker":          "worker_preference",
    "driver":          "worker_preference",
    "comfort":         "worker_preference",
    "satisfaction":    "worker_preference",
    "welfare":         "worker_preference",
    # express_miss_penalty (omit bare "priority" — matches unrelated keys)
    "urgent":          "express_miss_penalty",
    "express":         "express_miss_penalty",
    "sla":             "express_miss_penalty",
    "vip":             "express_miss_penalty",
    "rush":            "express_miss_penalty",
    "critical":        "express_miss_penalty",
    # early arrival penalty (w8)
    "early_arrival":         "waiting_time",
    "early_arrival_penalty": "waiting_time",
    "arrive_early":          "waiting_time",
    "pre_window":            "waiting_time",
    "early_dwell":           "waiting_time",
}


def _fuzzy_match_weight_key(key: str) -> str | None:
    """
    Try to map an unrecognized weight key to a known alias using:
    1. Direct keyword lookup (exact).
    2. Substring containment: keyword inside key (longest keyword first to avoid
       short keywords like "load" winning over "workload").
    3. Difflib close-match against canonical alias names.

    (No "key inside keyword" pass: short keys like ``cost`` would wrongly match
    ``operating_cost`` and map to ``travel_time``.)
    Returns the matched canonical alias name, or None if no confident match.
    """
    k = key.lower().strip()
    # 1. Direct keyword match
    if k in _WEIGHT_KEYWORD_MAP:
        return _WEIGHT_KEYWORD_MAP[k]
    # 2 & 3. Substring containment — sort by keyword length descending so longer,
    # more-specific keywords match before shorter ones (e.g. "workload" before "load").
    sorted_keywords = sorted(_WEIGHT_KEYWORD_MAP.items(), key=lambda x: len(x[0]), reverse=True)
    for kw, alias in sorted_keywords:
        if kw in k:
            return alias
    # 3. Difflib fuzzy match against canonical alias names (skip very short keys — e.g. "cost"
    # otherwise matches unrelated aliases.)
    if len(k) >= 5:
        close = difflib.get_close_matches(k, list(WEIGHT_ALIASES.keys()), n=1, cutoff=0.6)
        if close:
            return close[0]
    return None


def translate_weights(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Translate human-readable alias keys (travel_time, lateness_penalty, …) to the
    internal w1–w7 keys expected by build_weights. Also tries fuzzy/keyword matching
    for close-but-not-exact keys. Unknown keys that cannot be matched are dropped.
    Configs already using w1–w7 keys pass through unchanged.
    """
    translated, _ = translate_weights_strict(raw)
    return translated


def translate_weights_strict(
    raw: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """
    Like translate_weights but also returns a human-readable list of messages for
    each key that was auto-corrected (fuzzy-matched) or dropped (unrecognised).

    Returns:
        (translated_weights_dict, warning_messages)
    """
    out: dict[str, Any] = {}
    warnings: list[str] = []
    for k, v in raw.items():
        normalized_key = LEGACY_WEIGHT_ALIASES.get(k, k)
        if normalized_key in WEIGHT_ALIASES:
            out[WEIGHT_ALIASES[normalized_key]] = v
            if normalized_key != k:
                warnings.append(
                    f"Weight key '{k}' is deprecated and was normalized to '{normalized_key}'."
                )
        elif k in _WEIGHT_VALID_WN:
            out[k] = v
        else:
            matched = _fuzzy_match_weight_key(k)
            if matched:
                out[WEIGHT_ALIASES[matched]] = v
                warnings.append(
                    f"Weight key '{k}' was interpreted as '{matched}' "
                    f"(closest supported objective)."
                )
            else:
                warnings.append(
                    f"Weight key '{k}' is not a recognised objective and was ignored. "
                    f"Supported objectives: {', '.join(WEIGHT_ALIASES)}."
                )
    return out, warnings


def _sanitize_algorithm_params_on_problem(problem: dict[str, Any]) -> list[str]:
    from app.algorithm_catalog import canonical_algorithm_stored, filter_algorithm_params

    ap_raw = problem.get("algorithm_params")
    if ap_raw is None:
        return []
    if not isinstance(ap_raw, dict):
        problem.pop("algorithm_params", None)
        return ["Removed malformed `problem.algorithm_params`; expected an object."]
    algo = canonical_algorithm_stored(problem.get("algorithm"))
    if algo is None:
        problem.pop("algorithm_params", None)
        return ["Removed algorithm_params: `problem.algorithm` must be GA, PSO, SA, SwarmSA, or ACOR."]
    filtered, w = filter_algorithm_params(algo, ap_raw)
    if filtered:
        problem["algorithm_params"] = filtered
    else:
        problem.pop("algorithm_params", None)
    return w


def sanitize_panel_weights(panel_config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Translate/sanitize weight keys inside panel_config['problem']['weights'] in-place
    (on a deep copy). Returns (sanitized_panel_config, warnings).
    Also drops unknown `algorithm_params` keys for the selected algorithm.
    Harmless when no 'problem' key exists.
    """
    cfg = deepcopy(panel_config)
    problem = cfg.get("problem")
    if not isinstance(problem, dict):
        return cfg, []
    warnings: list[str] = []

    # Legacy / redundant lists are deprecated; goal-term typing lives in constraint_types (and goal_terms metadata).
    problem.pop("hard_constraints", None)
    problem.pop("soft_constraints", None)
    # Normalize goal_terms input first (if present) so downstream sanitization is consistent.
    projected = _apply_goal_terms_overlay(problem)
    problem.clear()
    problem.update(projected)

    weights_raw = problem.get("weights")
    if weights_raw is None:
        problem.pop("weights", None)
    elif not isinstance(weights_raw, dict):
        problem.pop("weights", None)
        warnings.append("Ignored malformed `problem.weights`; expected an object.")
    else:
        wr = dict(weights_raw)
        if "fuel_cost" in wr:
            fc = wr.pop("fuel_cost")
            if "shift_limit" not in wr:
                wr["shift_limit"] = fc
                warnings.append(
                    "Migrated deprecated `fuel_cost` weight to `shift_limit` (w2 — max shift penalty)."
                )
            else:
                warnings.append(
                    "Removed deprecated `fuel_cost` weight; `shift_limit` was already set."
                )
        if "shift_overtime" in wr:
            so = wr.pop("shift_overtime")
            if "shift_limit" not in wr:
                wr["shift_limit"] = so
                # No warning needed for this rename as it's the standard evolution.
            else:
                warnings.append(
                    "Removed redundant `shift_overtime` weight; `shift_limit` was already set."
                )
        translated, w = translate_weights_strict(wr)
        problem["weights"] = {WEIGHT_ALIAS_REVERSE.get(k, k): v for k, v in translated.items()}
        warnings.extend(w)

    locked_raw = problem.get("locked_goal_terms")
    if isinstance(locked_raw, list):
        seen: set[str] = set()
        out: list[str] = []
        migrated_lock = False
        for x in locked_raw:
            if not isinstance(x, str):
                continue
            raw_k = x.strip()
            nk = "shift_limit" if raw_k in ("fuel_cost", "shift_overtime") else raw_k
            nk = LEGACY_WEIGHT_ALIASES.get(nk, nk)
            if raw_k in ("fuel_cost", "shift_overtime") or raw_k in LEGACY_WEIGHT_ALIASES:
                migrated_lock = True
            if nk not in seen:
                out.append(nk)
                seen.add(nk)
        if migrated_lock:
            warnings.append("Renamed deprecated locked goal term(s) to canonical names.")
        problem["locked_goal_terms"] = out

    warnings.extend(_sanitize_algorithm_params_on_problem(problem))

    # Canonical projection for downstream clients: one place to inspect goal-term semantics.
    _rebuild_goal_terms_metadata(problem)
    # goal_terms is canonical storage; keep legacy fields out of persisted panel config.
    problem.pop("weights", None)
    problem.pop("constraint_types", None)
    return cfg, warnings


def _canonical_weight_aliases_from_payload(raw_weights: Any) -> dict[str, float]:
    if not isinstance(raw_weights, dict):
        return {}
    translated, _ = translate_weights_strict(raw_weights)
    out: dict[str, float] = {}
    for internal_key, value in translated.items():
        alias = WEIGHT_ALIAS_REVERSE.get(internal_key)
        if alias is None:
            continue
        try:
            out[alias] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _apply_goal_terms_overlay(raw_problem: dict[str, Any]) -> dict[str, Any]:
    """
    Accept canonical `goal_terms` map and project it onto `weights` + `constraint_types`
    (+ selected term properties) for solver-facing parsing.
    """
    out = dict(raw_problem)
    goal_terms = out.get("goal_terms")
    if not isinstance(goal_terms, dict):
        return out

    overlay_weights: dict[str, float] = {}
    overlay_constraint_types: dict[str, str] = {}
    overlay_locked: list[str] = []
    overlay_driver_preferences: list[Any] | None = None
    overlay_max_shift_hours: float | None = None

    ranked: list[tuple[int, str]] = []
    for key, entry in goal_terms.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        if "weight" not in entry:
            continue
        try:
            overlay_weights[key] = float(entry.get("weight"))
        except (TypeError, ValueError):
            continue

        term_type = str(entry.get("type") or "").strip().lower()
        if term_type in {"soft", "hard", "custom"}:
            overlay_constraint_types[key] = term_type
        if bool(entry.get("locked")):
            overlay_locked.append(key)
        rank_raw = entry.get("rank")
        try:
            rank = int(rank_raw)
            if rank > 0:
                ranked.append((rank, key))
        except (TypeError, ValueError):
            pass

        props = entry.get("properties")
        if not isinstance(props, dict):
            continue
        if key == "worker_preference" and isinstance(props.get("driver_preferences"), list):
            overlay_driver_preferences = list(props.get("driver_preferences") or [])
        if key == "shift_limit" and "max_shift_hours" in props:
            try:
                overlay_max_shift_hours = float(props.get("max_shift_hours"))
            except (TypeError, ValueError):
                pass

    if overlay_weights:
        out["weights"] = overlay_weights
    if overlay_constraint_types:
        base_ct = (
            dict(out.get("constraint_types"))
            if isinstance(out.get("constraint_types"), dict)
            else {}
        )
        base_ct.update(overlay_constraint_types)
        out["constraint_types"] = base_ct
    if overlay_locked:
        base_locked = (
            [x for x in out.get("locked_goal_terms", []) if isinstance(x, str)]
            if isinstance(out.get("locked_goal_terms"), list)
            else []
        )
        seen = set(base_locked)
        for key in overlay_locked:
            if key in seen:
                continue
            base_locked.append(key)
            seen.add(key)
        out["locked_goal_terms"] = base_locked
    if overlay_driver_preferences is not None:
        out["driver_preferences"] = overlay_driver_preferences
    if overlay_max_shift_hours is not None:
        out["max_shift_hours"] = overlay_max_shift_hours
    if ranked:
        ranked_sorted = [key for _rank, key in sorted(ranked, key=lambda x: x[0])]
        out["goal_term_order"] = ranked_sorted
    return out


def _rebuild_goal_terms_metadata(problem: dict[str, Any]) -> None:
    """Build canonical `goal_terms` map from current solver-facing fields."""
    if not isinstance(problem, dict):
        return
    weights = problem.get("weights")
    if not isinstance(weights, dict):
        problem.pop("goal_terms", None)
        return
    constraint_types = (
        problem.get("constraint_types")
        if isinstance(problem.get("constraint_types"), dict)
        else {}
    )
    locked_goal_terms = (
        [x for x in problem.get("locked_goal_terms", []) if isinstance(x, str)]
        if isinstance(problem.get("locked_goal_terms"), list)
        else []
    )
    locked_set = set(locked_goal_terms)
    goal_terms: dict[str, Any] = {}
    order = (
        [k for k in problem.get("goal_term_order", []) if isinstance(k, str)]
        if isinstance(problem.get("goal_term_order"), list)
        else []
    )
    order_idx = {k: i + 1 for i, k in enumerate(order)}
    max_rank = len(order_idx)
    for key, value in weights.items():
        if not isinstance(key, str):
            continue
        try:
            weight_val = float(value)
        except (TypeError, ValueError):
            continue
        entry: dict[str, Any] = {"weight": weight_val}
        raw_type = str(constraint_types.get(key) or "").strip().lower()
        entry["type"] = raw_type if raw_type in _TERM_TYPE_VALUES else "objective"
        if key in locked_set:
            entry["locked"] = True
        rank = order_idx.get(key)
        if rank is None:
            max_rank += 1
            rank = max_rank
        entry["rank"] = rank
        props: dict[str, Any] = {}
        if key == "worker_preference" and isinstance(problem.get("driver_preferences"), list):
            props["driver_preferences"] = deepcopy(problem.get("driver_preferences"))
        if key == "shift_limit" and isinstance(problem.get("max_shift_hours"), (int, float)):
            props["max_shift_hours"] = float(problem.get("max_shift_hours"))
        if props:
            entry["properties"] = props
        goal_terms[key] = entry
    if goal_terms:
        problem["goal_terms"] = goal_terms
    else:
        problem.pop("goal_terms", None)


def ensure_vrptw_on_path() -> Path:
    root = _VRPTW_ROOT.resolve()
    if not root.is_dir():
        raise RuntimeError(f"vrptw_problem root not found at {root}")
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)
    return root


def neutral_violations(metrics: dict) -> dict[str, Any]:
    return {
        "time_window_minutes_over": float(metrics.get("tw_violation_min", 0)),
        "time_window_stop_count": int(metrics.get("tw_violation_count", 0)),
        "capacity_units_over": int(metrics.get("capacity_overflow", 0)),
        "shift_limit_minutes": float(metrics.get("shift_overtime_minutes", 0)),
        "priority_deadline_misses": int(metrics.get("express_late_count", 0)),
    }


def _visits_from_evaluator_records(visits_per_vehicle: list) -> list[dict[str, Any]]:
    ensure_vrptw_on_path()
    from vrptw_problem.traffic_api import ZONE_NAMES

    out: list[dict[str, Any]] = []
    for v_idx, stops in enumerate(visits_per_vehicle):
        for rec in stops:
            try:
                ri = ZONE_NAMES.index(rec.zone)
            except ValueError:
                ri = 0
            oid = str(rec.order_id)
            task_index = int(oid[1:]) if oid.startswith("O") and oid[1:].isdigit() else None
            out.append(
                {
                    "vehicle_index": v_idx,
                    "vehicle_name": rec.vehicle_name,
                    "task_id": oid,
                    "task_index": task_index,
                    "region_index": ri,
                    "region_name": rec.zone,
                    "arrival_minutes": float(rec.arrival_time),
                    "departure_minutes": float(rec.departure_time),
                    "window_open_minutes": int(rec.window_open),
                    "window_close_minutes": int(rec.window_close),
                    "service_minutes": int(getattr(rec, "service_minutes", 0)),
                    "wait_minutes": float(getattr(rec, "wait_minutes", 0)),
                    "time_window_minutes_over": float(
                        getattr(rec, "time_window_minutes_over", 0)
                    ),
                    "priority_express": bool(rec.is_express),
                    # Backward-compatible alias for older frontend payloads.
                    "priority_urgent": bool(rec.is_express),
                    "priority_deadline_missed": bool(
                        getattr(rec, "priority_deadline_missed", False)
                    ),
                    "constraint_conflict": bool(rec.is_violation),
                    "time_window_conflict": bool(rec.is_violation),
                    "order_size": int(getattr(rec, "order_size", 0)),
                    "load_after_stop": int(getattr(rec, "load_after_stop", 0)),
                    "capacity_limit": int(getattr(rec, "capacity_limit", 0)),
                    "capacity_overflow_after_stop": int(
                        getattr(rec, "capacity_overflow_after_stop", 0)
                    ),
                    "capacity_conflict": bool(
                        getattr(rec, "capacity_overflow_after_stop", 0) > 0
                    ),
                    "preference_penalty_units": float(
                        getattr(rec, "preference_penalty_units", 0) or 0
                    ),
                    "preference_conflict": bool(
                        float(getattr(rec, "preference_penalty_units", 0) or 0) > 0
                    ),
                }
            )
    return out


def _vehicle_summaries_for_schedule(
    routes: list[list[int]],
    orders: list[Any],
    stops: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ensure_vrptw_on_path()
    from vrptw_problem.vehicles import VEHICLES

    by_vehicle: dict[int, list[dict[str, Any]]] = {}
    for stop in stops:
        by_vehicle.setdefault(int(stop["vehicle_index"]), []).append(stop)

    summaries: list[dict[str, Any]] = []
    for v_idx, vehicle in enumerate(VEHICLES):
        vehicle_routes = routes[v_idx] if v_idx < len(routes) else []
        vehicle_stops = by_vehicle.get(v_idx, [])
        assigned_units = sum(int(orders[o_idx].size) for o_idx in vehicle_routes)
        max_departure = max(
            [float(s["departure_minutes"]) for s in vehicle_stops],
            default=float(vehicle.shift_start_min),
        )
        max_close = max(
            [float(s["window_close_minutes"]) for s in vehicle_stops],
            default=float(vehicle.shift_start_min),
        )
        summaries.append(
            {
                "vehicle_index": v_idx,
                "vehicle_name": vehicle.name,
                "capacity_limit": int(vehicle.capacity),
                "assigned_units": int(assigned_units),
                "capacity_overflow_units": int(
                    max(0, assigned_units - int(vehicle.capacity))
                ),
                "shift_start_minutes": int(vehicle.shift_start_min),
                "display_end_minutes": float(max(max_departure, max_close)),
                "shift_limit_minutes": float(vehicle.max_hours * 60),
                "stop_count": len(vehicle_stops),
            }
        )
    return summaries


def _time_bounds_for_schedule(
    vehicle_summaries: list[dict[str, Any]], stops: list[dict[str, Any]]
) -> dict[str, float]:
    start = min(
        [float(v["shift_start_minutes"]) for v in vehicle_summaries],
        default=0.0,
    )
    end_candidates = [
        *[float(v["display_end_minutes"]) for v in vehicle_summaries],
        *[float(s["window_close_minutes"]) for s in stops],
        *[float(s["departure_minutes"]) for s in stops],
    ]
    end = max(end_candidates, default=start)
    return {"start_minutes": start, "end_minutes": end}


def routes_to_neutral(routes: list[list[int]]) -> list[dict[str, Any]]:
    return [
        {"vehicle_index": i, "task_indices": [int(x) for x in route]}
        for i, route in enumerate(routes)
    ]


_CONDITIONS = frozenset(
    {
        "avoid_zone",
        "order_priority",
        "shift_over_limit",
    }
)

_LEGACY_CONDITION_MAP = {
    "zone_d": "avoid_zone",
    "express_order": "order_priority",
    "shift_over_hours": "shift_over_limit",
}


def _normalize_zone_value(raw_zone: Any) -> int:
    from vrptw_problem.zone_canonical import normalize_delivery_zone

    return normalize_delivery_zone(raw_zone)


def _validate_locked_assignments(raw: Any) -> dict[int, int]:
    """Task indices 0–29, vehicle indices 0–4; no duplicate tasks."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("locked_assignments must be a JSON object mapping task index to vehicle index")
    out: dict[int, int] = {}
    for k, v in raw.items():
        oi = int(k)
        vi = int(v)
        if not 0 <= oi <= 29:
            raise ValueError(f"locked_assignments: task index {oi} must be between 0 and 29")
        if not 0 <= vi <= 4:
            raise ValueError(f"locked_assignments: vehicle index {vi} must be between 0 and 4")
        if oi in out:
            raise ValueError(f"locked_assignments: duplicate task index {oi}")
        out[oi] = vi
    return out


def _normalize_order_priority_value(raw: object) -> str:
    pr = str(raw or "").strip().lower()
    if pr in ("low", "normal", "std", "default"):
        return "standard"
    if pr in ("high", "vip", "priority", "express_line", "exp"):
        return "express"
    if pr in ("express", "standard"):
        return pr
    return "standard"


def _canonicalize_driver_preference_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy driver-preference aliases into current canonical fields."""
    out = dict(rule)
    raw_cond = str(out.get("condition", "")).strip().lower()
    cond = _LEGACY_CONDITION_MAP.get(raw_cond, raw_cond)
    out["condition"] = cond

    if raw_cond == "zone_d":
        out["zone"] = 4
    elif cond == "avoid_zone" and out.get("zone_letter") is not None and out.get("zone") is None:
        out["zone"] = out.get("zone_letter")
    elif cond == "avoid_zone" and out.get("zone_name") is not None and out.get("zone") is None:
        out["zone"] = out.get("zone_name")

    if raw_cond == "express_order" and out.get("order_priority") is None:
        out["order_priority"] = "express"

    if raw_cond == "shift_over_hours" and out.get("limit_minutes") is None and out.get("hours") is not None:
        out["limit_minutes"] = float(out["hours"]) * 60.0

    return out


def _validate_driver_preferences(raw: list[Any]) -> list[dict[str, Any]]:
    """Normalize and validate driver preference rules for the VRPTW evaluator."""
    out: list[dict[str, Any]] = []
    for i, rule in enumerate(raw):
        if not isinstance(rule, dict):
            raise ValueError(f"driver_preferences[{i}] must be an object")
        vid = rule.get("vehicle_idx")
        if vid is None or not (0 <= int(vid) <= 4):
            raise ValueError(f"driver_preferences[{i}]: vehicle_idx must be an integer 0–4")
        canon_rule = _canonicalize_driver_preference_rule(rule)
        cond = str(canon_rule.get("condition", "")).strip().lower()
        if cond not in _CONDITIONS:
            raise ValueError(
                f"driver_preferences[{i}]: unknown condition {cond!r}; "
                f"expected one of: {', '.join(sorted(_CONDITIONS))}"
            )
        penalty = float(canon_rule.get("penalty", 0))
        if penalty < 0:
            raise ValueError(f"driver_preferences[{i}]: penalty must be >= 0")
        agg = str(canon_rule.get("aggregation", "per_stop"))
        if agg not in ("per_stop", "once_per_route"):
            raise ValueError(
                f"driver_preferences[{i}]: aggregation must be 'per_stop' or 'once_per_route'"
            )

        nr: dict[str, Any] = {
            "vehicle_idx": int(vid),
            "condition": cond,
            "penalty": penalty,
            "aggregation": agg,
        }

        if cond == "avoid_zone":
            z = canon_rule.get("zone")
            if z is None:
                raise ValueError(f"driver_preferences[{i}]: avoid_zone requires 'zone' (1–5)")
            try:
                zi = _normalize_zone_value(z)
            except (TypeError, ValueError):
                raise ValueError(f"driver_preferences[{i}]: zone must be 1–5 or A–E") from None
            if not 1 <= zi <= 5:
                raise ValueError(f"driver_preferences[{i}]: zone must be 1–5 (delivery zones A–E)")
            nr["zone"] = zi

        if cond == "order_priority":
            nr["order_priority"] = _normalize_order_priority_value(canon_rule.get("order_priority", "express"))

        if cond == "shift_over_limit":
            if canon_rule.get("limit_minutes") is not None:
                nr["limit_minutes"] = float(canon_rule["limit_minutes"])
            elif canon_rule.get("hours") is not None:
                nr["limit_minutes"] = float(canon_rule["hours"]) * 60.0
            else:
                nr["limit_minutes"] = 6.5 * 60.0
            if nr["limit_minutes"] <= 0:
                raise ValueError(f"driver_preferences[{i}]: limit_minutes must be > 0")

        out.append(nr)
    return out


def parse_problem_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize incoming neutral problem configuration.

    The returned dict includes a 'weight_warnings' key (list[str]) for any
    weight keys that were auto-corrected or dropped; callers should pop and
    surface this before passing the config to the solver.
    """
    ensure_vrptw_on_path()
    from vrptw_problem.optimizer import EARLY_STOP_DEFAULT_EPSILON, EARLY_STOP_DEFAULT_PATIENCE
    from vrptw_problem.user_input import DEFAULT_MAX_SHIFT_HOURS, build_weights

    raw = _apply_goal_terms_overlay(raw if isinstance(raw, dict) else {})
    weights_raw, weight_warnings = translate_weights_strict(raw.get("weights") or {})
    # Default to explicit-only objective scoring when the field is omitted.
    only_active = bool(raw.get("only_active_terms", True))
    weights = build_weights(weights_raw, only_active_terms=only_active)

    driver_preferences_raw = raw.get("driver_preferences")
    if driver_preferences_raw is None:
        driver_preferences_raw = []
    if not isinstance(driver_preferences_raw, list):
        raise ValueError("driver_preferences must be a list")
    driver_preferences = _validate_driver_preferences(driver_preferences_raw)

    shift_hard = float(raw.get("max_shift_hours", DEFAULT_MAX_SHIFT_HOURS))

    locked = _validate_locked_assignments(raw.get("locked_assignments"))

    algorithm = str(raw.get("algorithm", "GA")).strip().upper()
    algo_norm = "SwarmSA" if algorithm == "SWARMSA" else algorithm
    allowed = {"GA", "PSO", "SA", "SwarmSA", "ACOR"}
    if algo_norm not in allowed:
        raise ValueError(f"Unknown algorithm: use one of {sorted(allowed)}")

    epochs = int(raw.get("epochs", DEFAULT_EPOCHS))
    pop_size = int(raw.get("pop_size", DEFAULT_POP_SIZE))
    if epochs < 1 or epochs > 50000:
        raise ValueError("epochs must be between 1 and 50000")
    if pop_size < 2 or pop_size > 500:
        raise ValueError("pop_size must be between 2 and 500")

    random_seed = int(raw.get("random_seed", 42))
    algorithm_params_raw = raw.get("algorithm_params")
    if algorithm_params_raw is not None and not isinstance(algorithm_params_raw, dict):
        raise ValueError("algorithm_params must be an object or null")

    algorithm_params_filtered, ap_warnings = filter_algorithm_params(algo_norm, algorithm_params_raw)
    weight_warnings.extend(ap_warnings)

    ref_weights = raw.get("reference_weights")
    if ref_weights is not None:
        if not isinstance(ref_weights, dict):
            raise ValueError("reference_weights must be an object or null")
        ref_w_translated, ref_w_warnings = translate_weights_strict(ref_weights)
        weight_warnings.extend(ref_w_warnings)
        ref_weights = build_weights(
            ref_w_translated,
            only_active_terms=raw.get("reference_only_active_terms", False),
        )

    early_stop = raw.get("early_stop", True)
    if not isinstance(early_stop, bool):
        raise ValueError("early_stop must be a boolean")

    es_patience_raw = raw.get("early_stop_patience")
    if es_patience_raw is None:
        early_stop_patience = EARLY_STOP_DEFAULT_PATIENCE
    else:
        early_stop_patience = int(es_patience_raw)
        if early_stop_patience < 1 or early_stop_patience > 5000:
            raise ValueError("early_stop_patience must be between 1 and 5000")

    es_eps_raw = raw.get("early_stop_epsilon")
    if es_eps_raw is None:
        early_stop_epsilon = EARLY_STOP_DEFAULT_EPSILON
    else:
        early_stop_epsilon = float(es_eps_raw)
        if early_stop_epsilon <= 0:
            raise ValueError("early_stop_epsilon must be > 0")

    use_greedy_init = raw.get("use_greedy_init", True)
    if not isinstance(use_greedy_init, bool):
        use_greedy_init = bool(use_greedy_init)

    return {
        "weights": weights,
        "driver_preferences": driver_preferences,
        "max_shift_hours": shift_hard,
        "locked_assignments": locked,
        "algorithm": algo_norm,
        "algorithm_params": algorithm_params_filtered,
        "epochs": epochs,
        "pop_size": pop_size,
        "random_seed": random_seed,
        "early_stop": early_stop,
        "early_stop_patience": early_stop_patience,
        "early_stop_epsilon": early_stop_epsilon,
        "use_greedy_init": use_greedy_init,
        "reference_weights": ref_weights,
        "candidate_seed_vectors": [],
        # Callers must pop this before passing cfg to the solver.
        "weight_warnings": weight_warnings,
    }


def _normalize_candidate_seed_routes(candidate_seeds_raw: Any) -> tuple[list[list[list[int]]], list[str]]:
    candidate_routes_list: list[list[list[int]]] = []
    warnings: list[str] = []
    if candidate_seeds_raw is None:
        return candidate_routes_list, warnings
    if not isinstance(candidate_seeds_raw, list):
        return candidate_routes_list, ["Ignored candidate seeds: expected a list."]

    expected = set(range(30))
    for idx, raw_seed in enumerate(candidate_seeds_raw):
        if not isinstance(raw_seed, dict):
            warnings.append(f"Ignored candidate seed #{idx + 1}: expected an object.")
            continue
        routes_raw = raw_seed.get("routes")
        if not isinstance(routes_raw, list) or len(routes_raw) != 5:
            warnings.append(f"Ignored candidate seed #{idx + 1}: expected exactly 5 routes.")
            continue
        try:
            routes = [[int(x) for x in route] for route in routes_raw]
        except (TypeError, ValueError):
            warnings.append(f"Ignored candidate seed #{idx + 1}: routes must contain integer task indices.")
            continue
        flat: list[int] = [task for route in routes for task in route]
        if len(flat) != 30 or set(flat) != expected:
            warnings.append(f"Ignored candidate seed #{idx + 1}: routes must cover task indices 0..29 exactly once.")
            continue
        candidate_routes_list.append(routes)
    return candidate_routes_list, warnings


def run_optimize(cfg: dict[str, Any], timeout_sec: float, cancel_event: Any | None = None) -> dict[str, Any]:
    ensure_vrptw_on_path()
    from vrptw_problem.encoder import encode_routes_as_vector
    from vrptw_problem.evaluator import simulate_routes
    from vrptw_problem.orders import get_orders
    from vrptw_problem.optimizer import OptimizationCancelled, QuickBiteOptimizer

    def _work():
        candidate_seed_vectors = [
            encode_routes_as_vector(routes)
            for routes in cfg.get("candidate_seed_routes", [])
        ]
        opt = QuickBiteOptimizer(
            weights=cfg["weights"],
            locked=cfg["locked_assignments"],
            driver_preferences=cfg["driver_preferences"],
            max_shift_hours=cfg["max_shift_hours"],
            seed=cfg["random_seed"],
        )
        return opt.solve(
            algorithm=cfg["algorithm"],
            params=cfg["algorithm_params"],
            epochs=cfg["epochs"],
            pop_size=cfg["pop_size"],
            early_stop=cfg["early_stop"],
            early_stop_patience=cfg["early_stop_patience"],
            early_stop_epsilon=cfg["early_stop_epsilon"],
            cancel_event=cancel_event,
            use_greedy_init=cfg.get("use_greedy_init", True),
            initial_solutions=candidate_seed_vectors,
        )

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_work)
        try:
            result = fut.result(timeout=timeout_sec)
        except FuturesTimeout:
            raise TimeoutError("Optimization exceeded time limit") from None
        except OptimizationCancelled:
            raise RunCancelled() from None

    orders = get_orders(seed=None)
    visits = _visits_from_evaluator_records(result.visits)
    route_rows = routes_to_neutral(result.routes)
    vehicle_summaries = _vehicle_summaries_for_schedule(result.routes, orders, visits)
    time_bounds = _time_bounds_for_schedule(vehicle_summaries, visits)

    metrics = result.metrics
    dp_raw = float(metrics.get("driver_penalty", 0))
    neutral_metrics = {
        "total_travel_minutes": float(metrics.get("travel_time", 0)),
        "shift_overtime_minutes": float(metrics.get("shift_overtime_minutes", 0)),
        "workload_variance": float(metrics.get("workload_variance", 0)),
        "driver_preference_units": dp_raw,
        "driver_preference_penalty": dp_raw,
    }

    ref_cost = None
    if cfg.get("reference_weights"):
        rng_ref = np.random.RandomState(cfg["random_seed"] + 1000)
        rc, _, _ = simulate_routes(
            result.routes,
            orders,
            rng_ref,
            cfg["reference_weights"],
            driver_preferences=cfg["driver_preferences"],
            max_shift_hours=cfg["max_shift_hours"],
        )
        ref_cost = float(rc)

    return {
        "cost": float(result.best_cost),
        "reference_cost": ref_cost,
        "schedule": {
            "routes": route_rows,
            "stops": visits,
            "vehicle_summaries": vehicle_summaries,
            "time_bounds": time_bounds,
        },
        "violations": neutral_violations(metrics),
        "metrics": neutral_metrics,
        "runtime_seconds": float(result.runtime),
        "algorithm": result.algorithm,
        "convergence": result.convergence[:200] if result.convergence else [],
    }


def run_evaluate_routes(
    routes: list[list[int]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    ensure_vrptw_on_path()
    from vrptw_problem.evaluator import simulate_routes
    from vrptw_problem.orders import get_orders

    if len(routes) != 5:
        raise ValueError("schedule must contain exactly 5 vehicle routes")
    orders = get_orders(seed=None)
    all_idx: set[int] = set()
    for r in routes:
        for o in r:
            all_idx.add(int(o))
    expected = set(range(30))
    if all_idx != expected:
        raise ValueError("Each task index 0..29 must appear exactly once across routes")

    rng = np.random.RandomState(cfg["random_seed"])
    cost, metrics, visits_pv = simulate_routes(
        routes,
        orders,
        rng,
        cfg["weights"],
        driver_preferences=cfg["driver_preferences"],
        max_shift_hours=cfg["max_shift_hours"],
    )
    visits = _visits_from_evaluator_records(visits_pv)
    route_rows = routes_to_neutral(routes)
    vehicle_summaries = _vehicle_summaries_for_schedule(routes, orders, visits)
    time_bounds = _time_bounds_for_schedule(vehicle_summaries, visits)
    ref_cost = None
    if cfg.get("reference_weights"):
        rng2 = np.random.RandomState(cfg["random_seed"] + 1000)
        rc, _, _ = simulate_routes(
            routes,
            orders,
            rng2,
            cfg["reference_weights"],
            driver_preferences=cfg["driver_preferences"],
            max_shift_hours=cfg["max_shift_hours"],
        )
        ref_cost = float(rc)

    dp_raw = float(metrics.get("driver_penalty", 0))
    neutral_metrics = {
        "total_travel_minutes": float(metrics.get("travel_time", 0)),
        "shift_overtime_minutes": float(metrics.get("shift_overtime_minutes", 0)),
        "workload_variance": float(metrics.get("workload_variance", 0)),
        "driver_preference_units": dp_raw,
        "driver_preference_penalty": dp_raw,
    }

    return {
        "cost": float(cost),
        "reference_cost": ref_cost,
        "schedule": {
            "routes": route_rows,
            "stops": visits,
            "vehicle_summaries": vehicle_summaries,
            "time_bounds": time_bounds,
        },
        "violations": neutral_violations(metrics),
        "metrics": neutral_metrics,
        "runtime_seconds": 0.0,
        "algorithm": "evaluate",
        "convergence": [],
    }


def attach_fleet_gantt_visualization(result: dict[str, Any]) -> dict[str, Any]:
    """Add visualization preset for the participant results UI."""
    out = dict(result)
    sched = out.get("schedule")
    if isinstance(sched, dict):
        out["visualization"] = {
            "preset": "fleet_gantt",
            "version": 1,
            "payload": {
                "routes": sched.get("routes"),
                "stops": sched.get("stops"),
                "vehicle_summaries": sched.get("vehicle_summaries"),
                "time_bounds": sched.get("time_bounds"),
            },
        }
    return out


def solve_request_to_result(body: dict[str, Any], timeout_sec: float, cancel_event: Any | None = None) -> dict[str, Any]:
    cfg = parse_problem_config(body.get("problem") or body)
    candidate_routes, candidate_warnings = _normalize_candidate_seed_routes(body.get("candidate_seeds"))
    cfg["candidate_seed_routes"] = candidate_routes
    # Pop warnings before passing cfg to the solver (solver ignores unknown keys anyway,
    # but this keeps cfg clean and makes warning propagation explicit).
    weight_warnings: list[str] = cfg.pop("weight_warnings", [])
    weight_warnings.extend(candidate_warnings)
    run_type = (body.get("type") or "optimize").lower()
    if run_type == "evaluate":
        routes = body.get("routes")
        if not routes or not isinstance(routes, list):
            raise ValueError("evaluate requires routes: list of 5 lists of task indices")
        routes = [[int(x) for x in row] for row in routes]
        result = run_evaluate_routes(routes, cfg)
    else:
        result = run_optimize(cfg, timeout_sec, cancel_event=cancel_event)
    if weight_warnings:
        result["weight_warnings"] = weight_warnings
    return attach_fleet_gantt_visualization(result)
