"""Panel and problem brief sync logic."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import StudySession
from app.problem_brief import sync_problem_brief_from_panel as merge_brief_from_panel

from . import helpers

log = logging.getLogger(__name__)


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
    from app.adapter import sanitize_panel_weights
    from app.problem_config_seed import derive_problem_panel_from_brief
    from app.services.llm import generate_config_from_brief

    current_panel = helpers.panel_dict(row)
    derived_panel = None
    if api_key and model_name:
        try:
            derived_panel = generate_config_from_brief(
                brief=problem_brief,
                current_panel=None,
                api_key=api_key,
                model_name=model_name,
                workflow_mode=workflow_mode or row.workflow_mode,
                recent_runs_summary=recent_runs_summary,
            )
        except TypeError:
            derived_panel = generate_config_from_brief(
                brief=problem_brief,
                current_panel=None,
                api_key=api_key,
                model_name=model_name,
            )
    if derived_panel is None:
        derived_panel = derive_problem_panel_from_brief(problem_brief)
    if derived_panel is None:
        return None, []

    next_panel = deepcopy(current_panel) if isinstance(current_panel, dict) else {}
    current_problem = deepcopy(next_panel.get("problem")) if isinstance(next_panel.get("problem"), dict) else {}
    next_problem = deepcopy(current_problem)
    for key in ("weights", "only_active_terms", "algorithm", "algorithm_params", "epochs", "pop_size", "shift_hard_penalty"):
        next_problem.pop(key, None)
    derived_problem = deepcopy(derived_panel["problem"])
    # Preserve locked goal-term weights against brief/chat-driven derivation updates.
    locked_goal_terms_raw = current_problem.get("locked_goal_terms")
    locked_goal_terms = (
        [k for k in locked_goal_terms_raw if isinstance(k, str)]
        if isinstance(locked_goal_terms_raw, list)
        else []
    )
    if isinstance(derived_problem.get("weights"), dict) and isinstance(current_problem.get("weights"), dict):
        derived_weights = deepcopy(derived_problem["weights"])
        current_weights = current_problem["weights"]
        for key in locked_goal_terms:
            if key in current_weights and isinstance(current_weights[key], (int, float)):
                derived_weights[key] = float(current_weights[key])
        derived_problem["weights"] = derived_weights
    for key in locked_goal_terms:
        if key in current_problem and key not in (derived_problem.get("weights") or {}):
            derived_problem[key] = deepcopy(current_problem[key])
    if locked_goal_terms:
        derived_problem["locked_goal_terms"] = locked_goal_terms
    if preserve_missing_managed_fields:
        for key in ("weights", "only_active_terms", "algorithm", "algorithm_params", "epochs", "pop_size", "shift_hard_penalty"):
            if key not in derived_problem and key in current_problem:
                derived_problem[key] = deepcopy(current_problem[key])
    next_problem.update(derived_problem)
    next_panel["problem"] = next_problem
    merged, weight_warnings = sanitize_panel_weights(next_panel)
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
    next_problem_brief = merge_brief_from_panel(current_problem_brief, panel_config)
    if next_problem_brief == current_problem_brief:
        return current_problem_brief
    row.problem_brief_json = json.dumps(next_problem_brief)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return next_problem_brief
