"""Intrinsic rules for when optimization may run (agile vs waterfall), independent of researcher override."""

from __future__ import annotations

from typing import Any

from app.problem_brief import _normalize_question_status, normalize_problem_brief

# Mirrors frontend `WEIGHT_DISPLAY_ORDER` / ProblemConfigBlocks display keys.
_WEIGHT_ORDER = (
    "travel_time",
    "fuel_cost",
    "workload_balance",
    "deadline_penalty",
    "capacity_penalty",
    "priority_penalty",
    "worker_preference",
)


def _inner_problem_from_panel(panel_config: dict[str, Any] | None) -> dict[str, Any]:
    if not panel_config or not isinstance(panel_config, dict):
        return {}
    if isinstance(panel_config.get("problem"), dict):
        return panel_config["problem"]
    return panel_config


def intrinsic_optimization_ready_agile(panel_config: dict[str, Any] | None) -> bool:
    """At least one goal-term weight (display sense) and a non-empty algorithm on saved config."""
    inner = _inner_problem_from_panel(panel_config)
    if not inner:
        return False

    weights = inner.get("weights")
    if not isinstance(weights, dict):
        weights = {}
    has_worker_weight = "worker_preference" in weights
    driver_prefs = inner.get("driver_preferences")
    prefs_list = driver_prefs if isinstance(driver_prefs, list) else []
    show_worker_block = has_worker_weight or len(prefs_list) > 0

    display_weight_keys: list[str] = []
    for key in _WEIGHT_ORDER:
        if key not in weights:
            continue
        if key == "worker_preference" and not show_worker_block:
            continue
        display_weight_keys.append(key)

    algo = str(inner.get("algorithm") or "").strip()
    return bool(display_weight_keys) and bool(algo)


def intrinsic_optimization_ready_waterfall(
    normalized_brief: dict[str, Any],
    optimization_gate_engaged: bool,
) -> bool:
    """Waterfall: session must be past cold start; no open questions (list may be empty or all answered)."""
    if not optimization_gate_engaged:
        return False
    questions_raw = normalized_brief.get("open_questions") or []
    questions: list[dict[str, Any]] = [q for q in questions_raw if isinstance(q, dict)]
    for q in questions:
        if _normalize_question_status(q.get("status")) == "open":
            return False
    return True


def intrinsic_optimization_ready(
    workflow_mode: str,
    panel_config: dict[str, Any] | None,
    problem_brief: Any,
    optimization_gate_engaged: bool = False,
) -> bool:
    brief = normalize_problem_brief(problem_brief)
    mode = str(workflow_mode or "").strip().lower()
    if mode == "agile":
        return intrinsic_optimization_ready_agile(panel_config)
    if mode == "waterfall":
        return intrinsic_optimization_ready_waterfall(brief, optimization_gate_engaged)
    return False


def can_run_optimization(
    workflow_mode: str,
    optimization_allowed: bool,
    optimization_runs_blocked_by_researcher: bool,
    panel_config: dict[str, Any] | None,
    problem_brief: Any,
    optimization_gate_engaged: bool = False,
) -> bool:
    if optimization_runs_blocked_by_researcher:
        return False
    if optimization_allowed:
        return True
    return intrinsic_optimization_ready(
        workflow_mode,
        panel_config,
        problem_brief,
        optimization_gate_engaged=optimization_gate_engaged,
    )
