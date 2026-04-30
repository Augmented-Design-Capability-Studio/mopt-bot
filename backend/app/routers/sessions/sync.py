"""Panel and problem brief sync logic."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import StudySession
from app.problem_brief import sync_problem_brief_from_panel as merge_brief_from_panel
from app.problems.registry import DEFAULT_PROBLEM_ID

from . import helpers

log = logging.getLogger(__name__)


def _run_with_timeout(callable_obj, timeout_sec: float):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(callable_obj)
    try:
        return future.result(timeout=timeout_sec)
    finally:
        # Don't block on shutdown — if the LLM thread is still running after a
        # timeout, wait=True would hold the request handler open indefinitely.
        executor.shutdown(wait=False)


def _canonicalize_locked_goal_terms(
    current_problem: dict,
    derived_problem: dict,
    companion_fields: dict[str, str],
) -> dict:
    locked_raw = current_problem.get("locked_goal_terms")
    if not isinstance(locked_raw, list):
        locked_raw = []
    locked_goal_terms = [key for key in locked_raw if isinstance(key, str)]

    current_weights = current_problem.get("weights")
    current_weight_keys: set[str] = set()
    if isinstance(current_weights, dict):
        current_weight_keys = {
            key for key, value in current_weights.items() if isinstance(key, str) and isinstance(value, (int, float))
        }

    lockable_keys = set(current_weight_keys)
    canonical_locked = [key for key in locked_goal_terms if key in lockable_keys]

    if isinstance(derived_problem.get("weights"), dict) and isinstance(current_weights, dict):
        merged_weights = deepcopy(derived_problem["weights"])
        for key in canonical_locked:
            if key in current_weight_keys:
                merged_weights[key] = float(current_weights[key])
        derived_problem["weights"] = merged_weights

    for locked_key, companion_field in companion_fields.items():
        if locked_key in canonical_locked:
            companion = current_problem.get(companion_field)
            if isinstance(companion, list):
                derived_problem[companion_field] = deepcopy(companion)
            else:
                derived_problem[companion_field] = []

    if canonical_locked:
        derived_problem["locked_goal_terms"] = canonical_locked
    else:
        derived_problem.pop("locked_goal_terms", None)
    return derived_problem


def _merge_non_destructive_managed_fields(current_problem: dict, derived_problem: dict) -> dict:
    managed_keys = (
        "weights",
        "only_active_terms",
        "algorithm",
        "algorithm_params",
        "epochs",
        "pop_size",
    )
    merged = deepcopy(derived_problem)
    current_weights = current_problem.get("weights")
    derived_weights = merged.get("weights")
    if isinstance(current_weights, dict):
        if isinstance(derived_weights, dict):
            combined = deepcopy(current_weights)
            combined.update(derived_weights)
            merged["weights"] = combined
        else:
            merged["weights"] = deepcopy(current_weights)
    for key in managed_keys:
        if key == "weights":
            continue
        if key not in merged and key in current_problem:
            merged[key] = deepcopy(current_problem[key])
    return merged


def _managed_problem_fields() -> tuple[str, ...]:
    """Managed keys are re-derived from brief each turn unless preserve mode is requested."""
    return (
        "weights",
        "only_active_terms",
        "algorithm",
        "algorithm_params",
        "epochs",
        "pop_size",
        "max_shift_hours",
        "driver_preferences",
        "locked_assignments",
        "early_stop",
        "early_stop_patience",
        "early_stop_epsilon",
        "use_greedy_init",
    )


def sync_panel_from_problem_brief(
    row: StudySession,
    db: Session,
    problem_brief: dict,
    api_key: str | None = None,
    model_name: str | None = None,
    workflow_mode: str | None = None,
    recent_runs_summary: list | None = None,
    preserve_missing_managed_fields: bool = False,
) -> tuple[dict | None, list[str]]:
    from app.problems.registry import get_study_port
    from app.services.llm import generate_config_from_brief

    test_problem_id = getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID

    current_panel = helpers.panel_dict(row)
    derived_panel = None
    if api_key and model_name:
        timeout_sec = get_settings().derivation_timeout_sec
        try:
            derived_panel = _run_with_timeout(
                lambda: generate_config_from_brief(
                    brief=problem_brief,
                    current_panel=None,
                    api_key=api_key,
                    model_name=model_name,
                    workflow_mode=workflow_mode or row.workflow_mode,
                    recent_runs_summary=recent_runs_summary,
                    test_problem_id=test_problem_id,
                ),
                timeout_sec,
            )
        except FuturesTimeoutError:
            log.warning("Config derivation timed out for session %s; falling back to deterministic seed", row.id)
        except TypeError:
            try:
                derived_panel = _run_with_timeout(
                    lambda: generate_config_from_brief(
                        brief=problem_brief,
                        current_panel=None,
                        api_key=api_key,
                        model_name=model_name,
                        test_problem_id=test_problem_id,
                    ),
                    timeout_sec,
                )
            except FuturesTimeoutError:
                log.warning("Config derivation (retry) timed out for session %s; falling back to deterministic seed", row.id)
    if derived_panel is None:
        derived_panel = get_study_port(test_problem_id).derive_problem_panel_from_brief(problem_brief)
    if derived_panel is None:
        return None, []

    next_panel = deepcopy(current_panel) if isinstance(current_panel, dict) else {}
    current_problem = deepcopy(next_panel.get("problem")) if isinstance(next_panel.get("problem"), dict) else {}
    next_problem = deepcopy(current_problem)
    for key in _managed_problem_fields():
        next_problem.pop(key, None)
    derived_problem = deepcopy(derived_panel["problem"])
    companion_fields = get_study_port(test_problem_id).locked_companion_fields()
    derived_problem = _canonicalize_locked_goal_terms(current_problem, derived_problem, companion_fields)
    if preserve_missing_managed_fields:
        derived_problem = _merge_non_destructive_managed_fields(current_problem, derived_problem)
    next_problem.update(derived_problem)
    next_panel["problem"] = next_problem
    merged, weight_warnings = get_study_port(test_problem_id).sanitize_panel_config(next_panel)
    if merged == current_panel:
        return merged, weight_warnings

    log.info("Participant synced panel_config from brief: %s", merged)
    row.panel_config_json = json.dumps(merged)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return merged, weight_warnings


def sync_problem_brief_from_panel(
    row: StudySession,
    db: Session,
    panel_config: dict,
) -> dict:
    current_problem_brief = helpers.problem_brief_dict(row)
    tpid = getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID
    next_problem_brief = merge_brief_from_panel(
        current_problem_brief, panel_config, test_problem_id=tpid
    )
    if next_problem_brief == current_problem_brief:
        return current_problem_brief
    row.problem_brief_json = json.dumps(next_problem_brief)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return next_problem_brief
