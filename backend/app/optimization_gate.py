"""Intrinsic rules for when optimization may run (agile vs waterfall), independent of researcher override."""

from __future__ import annotations

from typing import Any

from app.problem_brief import _normalize_question_status, normalize_problem_brief


def _inner_problem_from_panel(panel_config: dict[str, Any] | None) -> dict[str, Any]:
    if not panel_config or not isinstance(panel_config, dict):
        return {}
    if isinstance(panel_config.get("problem"), dict):
        return panel_config["problem"]
    return panel_config


def _goal_term_keys(problem: dict[str, Any]) -> set[str]:
    goal_terms = problem.get("goal_terms")
    keys: set[str] = set()
    if isinstance(goal_terms, dict):
        for key, entry in goal_terms.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                continue
            if isinstance(entry.get("weight"), (int, float)) and not isinstance(entry.get("weight"), bool):
                keys.add(key)
    if keys:
        return keys
    weights = problem.get("weights")
    if isinstance(weights, dict):
        return {k for k, v in weights.items() if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)}
    return set()


def intrinsic_optimization_ready_agile(
    panel_config: dict[str, Any] | None,
    weight_display_keys: list[str],
    worker_preference_key: str | None,
    worker_preference_companion_field: str | None = None,
) -> bool:
    """At least one goal-term weight (display sense) and a non-empty algorithm on saved config.

    ``weight_display_keys`` is the ordered list of keys that count toward the gate — supplied by
    the active problem module so the check is problem-agnostic.

    ``worker_preference_key`` names the one weight key (if any) whose inclusion in the gate
    requires the panel's ``worker_preference_companion_field`` (a top-level list-valued field
    like VRPTW's ``driver_preferences``) to be non-empty. Both arguments are ``None`` for
    problems without this concept (e.g. knapsack); they are supplied together by the active
    port. Field names are never hardcoded here.

    When ``weight_display_keys`` is empty the function falls back to any-weight logic (same
    behaviour as ``intrinsic_optimization_ready_demo``).
    """
    inner = _inner_problem_from_panel(panel_config)
    if not inner:
        return False

    goal_term_keys = _goal_term_keys(inner)

    algo = str(inner.get("algorithm") or "").strip()

    # Fallback: if no display keys defined by the module, accept any weight (demo-style).
    if not weight_display_keys:
        return bool(goal_term_keys) and bool(algo)

    show_worker_block = False
    if worker_preference_key is not None:
        has_worker_weight = worker_preference_key in goal_term_keys
        companion_present = False
        if worker_preference_companion_field:
            companion = inner.get(worker_preference_companion_field)
            companion_list = companion if isinstance(companion, list) else []
            companion_present = len(companion_list) > 0
        show_worker_block = has_worker_weight or companion_present

    display_weight_keys: list[str] = []
    for key in weight_display_keys:
        if key not in goal_term_keys:
            continue
        if worker_preference_key is not None and key == worker_preference_key and not show_worker_block:
            continue
        display_weight_keys.append(key)

    return bool(display_weight_keys) and bool(algo)


def intrinsic_optimization_ready_waterfall(
    normalized_brief: dict[str, Any],
    optimization_gate_engaged: bool,
    panel_config: dict[str, Any] | None = None,
) -> bool:
    """Waterfall gate.

    Requires **all** of:

    - At least one goal-term weight in the saved panel.
    - A non-empty ``algorithm`` (search strategy) in the saved panel.
    - ``optimization_gate_engaged`` (first user chat turn has happened).
    - No open-status open questions remaining.

    Earlier versions used ``not goal_term AND not search_strategy`` (i.e.
    only failed when *both* were missing); that allowed runs with goal
    terms but no chosen algorithm, which violates waterfall's "specify
    before solve" contract. Now both must be present.
    """
    inner = _inner_problem_from_panel(panel_config)
    has_goal_term = len(_goal_term_keys(inner)) > 0
    has_search_strategy = bool(str(inner.get("algorithm") or "").strip())
    if not has_goal_term or not has_search_strategy:
        return False
    if not optimization_gate_engaged:
        return False
    questions_raw = normalized_brief.get("open_questions") or []
    questions: list[dict[str, Any]] = [q for q in questions_raw if isinstance(q, dict)]
    for q in questions:
        if _normalize_question_status(q.get("status")) == "open":
            return False
    return True


def intrinsic_optimization_ready_demo(panel_config: dict[str, Any] | None) -> bool:
    """Demo: any goal-term weight (any key) and a non-empty algorithm — problem-agnostic."""
    inner = _inner_problem_from_panel(panel_config)
    if not inner:
        return False
    has_any_weight = len(_goal_term_keys(inner)) > 0
    algo = str(inner.get("algorithm") or "").strip()
    return has_any_weight and bool(algo)


def intrinsic_optimization_ready(
    workflow_mode: str,
    panel_config: dict[str, Any] | None,
    problem_brief: Any,
    optimization_gate_engaged: bool = False,
    problem_id: str | None = None,
) -> bool:
    brief = normalize_problem_brief(problem_brief)
    mode = str(workflow_mode or "").strip().lower()
    if mode == "agile":
        from app.problems.registry import get_study_port

        port = get_study_port(problem_id)
        wpk = port.worker_preference_key()
        # Look up the companion field via the existing port hook so the gate
        # never hardcodes a problem-specific field name.
        companion_field: str | None = None
        if wpk is not None:
            companion_fields = port.locked_companion_fields()
            if isinstance(companion_fields, dict):
                cf = companion_fields.get(wpk)
                if isinstance(cf, str) and cf:
                    companion_field = cf
        return intrinsic_optimization_ready_agile(
            panel_config,
            port.weight_display_keys(),
            wpk,
            worker_preference_companion_field=companion_field,
        )
    if mode == "demo":
        return intrinsic_optimization_ready_demo(panel_config)
    if mode == "waterfall":
        return intrinsic_optimization_ready_waterfall(brief, optimization_gate_engaged, panel_config)
    return False


def can_run_optimization(
    workflow_mode: str,
    optimization_allowed: bool,
    optimization_runs_blocked_by_researcher: bool,
    panel_config: dict[str, Any] | None,
    problem_brief: Any,
    has_uploaded_data: bool = True,
    optimization_gate_engaged: bool = False,
    problem_id: str | None = None,
) -> bool:
    mode = str(workflow_mode or "").strip().lower()
    if mode in ("agile", "demo") and not has_uploaded_data:
        return False
    if optimization_runs_blocked_by_researcher:
        return False
    if optimization_allowed:
        return True
    return intrinsic_optimization_ready(
        workflow_mode,
        panel_config,
        problem_brief,
        optimization_gate_engaged=optimization_gate_engaged,
        problem_id=problem_id,
    )
