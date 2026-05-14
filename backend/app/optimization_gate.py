"""Intrinsic rules for when optimization may run, independent of researcher override.

Single unified gate across all three workflow modes (agile / waterfall / demo).
The only mode-driven difference is the open-questions check, which applies in
waterfall. Every other prerequisite — algorithm chosen, qualifying goal term
present, the chat gate engaged, and (at the wrapper layer) uploaded data — is
shared across modes.
"""

from __future__ import annotations

from typing import Any, Callable

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


def _qualifying_goal_term_present(
    inner: dict[str, Any],
    weight_display_keys: list[str],
    gate_conditional_companions: dict[str, str],
    companion_present: "Callable[[str, Any], bool] | None" = None,
) -> bool:
    """Mode-agnostic ``has_goal_term`` test.

    A goal term key contributes to gate-opening iff it appears in
    ``weight_display_keys`` AND one of:

    - The key has **no** registered companion → its weight is set in the
      panel; OR
    - The key has a registered companion → ``companion_present(key, value)``
      returns True for the panel's companion field value. The weight on
      such a key is **not** required and does **not** open the gate on its
      own — the companion content is what carries.

    Together these implement "require a defined property if that companion-
    requiring goal term is the only one set" without any special-case for
    the alone-vs-alongside distinction (when alongside a non-companion
    weighted key, the other key opens the gate; the companion-requiring
    key just doesn't contribute).

    When ``weight_display_keys`` is empty the port has declared no opinion,
    so any weight in the panel counts (problem-agnostic fallback).
    """
    goal_term_keys = _goal_term_keys(inner)
    if not weight_display_keys:
        return bool(goal_term_keys)
    companions = gate_conditional_companions or {}
    predicate = companion_present or _default_companion_present
    for key in weight_display_keys:
        companion_field = companions.get(key)
        if companion_field:
            raw = inner.get(companion_field)
            if predicate(key, raw):
                return True
        else:
            if key in goal_term_keys:
                return True
    return False


def _default_companion_present(_goal_term_key: str, value: Any) -> bool:
    """Fallback predicate used in unit tests that don't supply a port.

    Mirrors ``StudyProblemPort.companion_present``'s default: lists are
    present iff non-empty, everything else is ``bool(value)``.
    """
    if isinstance(value, list):
        return len(value) > 0
    return bool(value)


def _has_open_status_question(brief: dict[str, Any]) -> bool:
    for q in brief.get("open_questions") or []:
        if isinstance(q, dict) and _normalize_question_status(q.get("status")) == "open":
            return True
    return False


def intrinsic_optimization_ready(
    workflow_mode: str,
    panel_config: dict[str, Any] | None,
    problem_brief: Any,
    optimization_gate_engaged: bool = False,
    problem_id: str | None = None,
) -> bool:
    """Unified intrinsic gate for agile / waterfall / demo.

    All modes require: algorithm chosen, a qualifying goal term, and
    ``optimization_gate_engaged`` (set automatically when the participant
    sends a visible chat message or the brief lists any open question).
    Waterfall additionally requires no open-status open questions.

    Returns ``False`` when ``workflow_mode`` is unrecognized.
    """
    mode = str(workflow_mode or "").strip().lower()
    if mode not in ("agile", "waterfall", "demo"):
        return False

    inner = _inner_problem_from_panel(panel_config)
    if not inner:
        return False

    if not str(inner.get("algorithm") or "").strip():
        return False

    from app.problems.registry import get_study_port

    port = get_study_port(problem_id)
    if not _qualifying_goal_term_present(
        inner,
        port.weight_display_keys(),
        port.gate_conditional_companions(),
        companion_present=port.companion_present,
    ):
        return False

    if not optimization_gate_engaged:
        return False

    if mode == "waterfall":
        brief = normalize_problem_brief(problem_brief)
        if _has_open_status_question(brief):
            return False

    return True


def gate_status(
    workflow_mode: str,
    panel_config: dict[str, Any] | None,
    problem_brief: Any,
    optimization_gate_engaged: bool = False,
    problem_id: str | None = None,
) -> dict[str, Any]:
    """Structured snapshot of run-prerequisite state for prompt injection.

    Returns deterministic flags the chat / brief-update / maintenance prompts
    can read by name. Pure state-reading: no NL parsing, no regex.

    The ``missing`` list is ordered for elicitation phases (goal_term first,
    then search_strategy, then gate_engaged, then waterfall-only
    open_questions) so the chat prompt can pop the head and ask about it.
    Agile / demo treat ``search_strategy`` missing as an assumption-to-add
    cue rather than a question.
    """
    inner = _inner_problem_from_panel(panel_config)

    from app.problems.registry import get_study_port

    port = get_study_port(problem_id)
    has_goal_term = _qualifying_goal_term_present(
        inner,
        port.weight_display_keys(),
        port.gate_conditional_companions(),
        companion_present=port.companion_present,
    )
    has_search_strategy = bool(str(inner.get("algorithm") or "").strip())

    brief = normalize_problem_brief(problem_brief)
    open_count = sum(
        1
        for q in (brief.get("open_questions") or [])
        if isinstance(q, dict) and _normalize_question_status(q.get("status")) == "open"
    )

    mode = str(workflow_mode or "").strip().lower()
    missing: list[str] = []
    if not has_goal_term:
        missing.append("goal_term")
    if not has_search_strategy:
        missing.append("search_strategy")
    if not optimization_gate_engaged:
        missing.append("gate_engaged")
    if mode == "waterfall" and open_count > 0:
        missing.append("open_questions")

    ready = intrinsic_optimization_ready(
        workflow_mode,
        panel_config,
        problem_brief,
        optimization_gate_engaged=optimization_gate_engaged,
        problem_id=problem_id,
    )

    return {
        "workflow_mode": mode,
        "goal_term_present": has_goal_term,
        "search_strategy_present": has_search_strategy,
        "open_questions_pending": open_count,
        "gate_engaged": bool(optimization_gate_engaged),
        "ready_to_run": bool(ready),
        "missing": missing,
    }


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
    if not has_uploaded_data:
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
