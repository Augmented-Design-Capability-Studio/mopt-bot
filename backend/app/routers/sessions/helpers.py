"""Session router helper functions."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import OptimizationRun, StudySession
from app.problem_brief import default_problem_brief, normalize_problem_brief
from app.schemas import RunOut, SessionOut, SessionProcessingState
from app.config import get_settings


def clean_participant_number(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def panel_dict(row: StudySession | None) -> dict | None:
    if row is None or not row.panel_config_json:
        return None
    try:
        return json.loads(row.panel_config_json)
    except json.JSONDecodeError:
        return None


def problem_brief_dict(row: StudySession | None) -> dict:
    if row is None or not row.problem_brief_json:
        return default_problem_brief()
    try:
        return normalize_problem_brief(json.loads(row.problem_brief_json))
    except json.JSONDecodeError:
        return default_problem_brief()


def touch_session(row: StudySession) -> None:
    row.updated_at = datetime.now(timezone.utc)


def processing_state(row: StudySession) -> SessionProcessingState:
    return SessionProcessingState(
        processing_revision=int(row.processing_revision or 0),
        brief_status=str(row.brief_status or "idle"),
        config_status=str(row.config_status or "idle"),
        processing_error=row.processing_error,
    )


def desired_config_status(row: StudySession) -> str:
    return "ready" if panel_dict(row) is not None else "idle"


def settle_processing_state(row: StudySession, *, cancel_revision: bool = False) -> None:
    if cancel_revision:
        row.processing_revision = int(row.processing_revision or 0) + 1
    row.brief_status = "ready"
    row.config_status = desired_config_status(row)
    row.processing_error = None


def mark_processing_pending(row: StudySession) -> int:
    row.processing_revision = int(row.processing_revision or 0) + 1
    row.brief_status = "pending"
    row.config_status = "pending"
    row.processing_error = None
    touch_session(row)
    return row.processing_revision


def fail_processing_state(row: StudySession, detail: str, *, cancel_revision: bool = False) -> None:
    if cancel_revision:
        row.processing_revision = int(row.processing_revision or 0) + 1
    row.brief_status = "failed"
    row.config_status = "failed"
    row.processing_error = detail
    touch_session(row)


def maybe_mark_optimization_gate_engaged_from_brief(row: StudySession, brief: dict) -> bool:
    """Set ``optimization_gate_engaged`` when the brief lists at least one open-question object."""
    if row.optimization_gate_engaged:
        return False
    oq = brief.get("open_questions") or []
    if any(isinstance(q, dict) for q in oq):
        row.optimization_gate_engaged = True
        return True
    return False


def sync_optimization_allowed_after_participant_mutation(row: StudySession) -> bool:
    """Set `optimization_allowed` from intrinsic readiness after participant-side changes (not researcher PATCH).

    Keeps the stored permit aligned with ``intrinsic_optimization_ready`` so the participant Run
    button, researcher checkbox, and ``GET /sessions/:id`` stay consistent after definition saves,
    panel saves, chat (including turns that only enqueue background derivation), and derivation.

    A researcher's explicit PATCH may temporarily set ``optimization_allowed`` ahead of intrinsic
    readiness (e.g. waterfall with open questions after confirm); the next participant message or
    definition/panel update recomputes this flag from the current brief and panel.
    """
    from app.optimization_gate import intrinsic_optimization_ready

    panel = panel_dict(row)
    brief = problem_brief_dict(row)
    changed = False
    if maybe_mark_optimization_gate_engaged_from_brief(row, brief):
        changed = True
    engaged = bool(getattr(row, "optimization_gate_engaged", False))
    want = intrinsic_optimization_ready(row.workflow_mode, panel, brief, optimization_gate_engaged=engaged)
    if row.optimization_allowed != want:
        row.optimization_allowed = want
        changed = True
    if changed:
        touch_session(row)
        return True
    return False


def session_to_out(row: StudySession) -> SessionOut:
    return SessionOut(
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        workflow_mode=row.workflow_mode,
        participant_number=row.participant_number,
        test_problem_id=str(getattr(row, "test_problem_id", None) or "vrptw"),
        status=row.status,
        panel_config=panel_dict(row),
        problem_brief=problem_brief_dict(row),
        processing=processing_state(row),
        optimization_allowed=row.optimization_allowed,
        optimization_runs_blocked_by_researcher=row.optimization_runs_blocked_by_researcher,
        optimization_gate_engaged=bool(getattr(row, "optimization_gate_engaged", False)),
        gemini_model=row.gemini_model or get_settings().default_gemini_model,
        gemini_key_configured=bool(row.gemini_key_encrypted),
    )


def run_number(row: OptimizationRun) -> int:
    return int(row.session_run_index or row.id)


def run_to_out(row: OptimizationRun) -> RunOut:
    req = None
    if row.request_json:
        try:
            req = json.loads(row.request_json)
        except json.JSONDecodeError:
            req = None
    res = None
    if row.result_json:
        try:
            res = json.loads(row.result_json)
        except json.JSONDecodeError:
            res = None
    return RunOut(
        id=row.id,
        run_number=run_number(row),
        created_at=row.created_at,
        run_type=row.run_type,
        ok=row.ok,
        cost=row.cost,
        reference_cost=row.reference_cost,
        error_message=row.error_message,
        request=req,
        result=res,
    )


def next_session_run_number(db: Session, session_id: str) -> int:
    current_max = (
        db.query(func.max(OptimizationRun.session_run_index))
        .filter(OptimizationRun.session_id == session_id)
        .scalar()
    )
    return 1 if current_max is None else int(current_max) + 1
