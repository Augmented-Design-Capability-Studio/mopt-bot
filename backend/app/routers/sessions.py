from __future__ import annotations

import json
import logging
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import Principal, require_any_study_user, require_client, require_researcher
from app.config import get_settings
from app.crypto_util import decrypt_secret, encrypt_secret
from app.database import get_db
from app.default_config import MEDIOCRE_PARTICIPANT_STARTER_CONFIG
from app.models import ChatMessage, OptimizationRun, StudySession
from app.problem_config_seed import derive_problem_panel_from_brief
from app.problem_brief import (
    default_problem_brief,
    merge_problem_brief_patch,
    normalize_problem_brief,
    sync_problem_brief_from_panel,
)
from app.schemas import (
    MessageCreate,
    MessageOut,
    ModelSettingsBody,
    ParticipantPanelUpdate,
    ParticipantProblemBriefUpdate,
    PostMessagesResponse,
    RunOut,
    SessionCreate,
    SessionOut,
    SessionPatch,
    SolveRunCreate,
    SteerCreate,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])
log = logging.getLogger(__name__)
_CLEANUP_INTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bclean\s*up\b", re.IGNORECASE),
    re.compile(r"\bconsolidat(?:e|ion)\b", re.IGNORECASE),
    re.compile(r"\bdeduplicat(?:e|ion)\b", re.IGNORECASE),
    re.compile(r"\breorgan(?:ize|ise|ization|isation)\b", re.IGNORECASE),
    re.compile(r"\b(remove|delete|drop)\b.{0,80}\b(assumption|gathered|definition|item|fact)\b", re.IGNORECASE),
    re.compile(r"\bmerge\b.{0,60}\b(gathered|assumption)\b", re.IGNORECASE),
)
_CLEAR_INTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bclear\b.{0,40}\b(definition|brief|gathered|assumption|open question|everything|all)\b", re.IGNORECASE),
    re.compile(r"\breset\b.{0,40}\b(definition|brief|everything|all)\b", re.IGNORECASE),
    re.compile(r"\brestart\b", re.IGNORECASE),
    re.compile(r"\bfresh slate\b", re.IGNORECASE),
)


def _clean_participant_number(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _is_definition_cleanup_request(content: str) -> bool:
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _CLEANUP_INTENT_PATTERNS)


def _is_definition_clear_request(content: str) -> bool:
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _CLEAR_INTENT_PATTERNS)


def _panel_dict(row: StudySession | None) -> dict | None:
    if row is None or not row.panel_config_json:
        return None
    try:
        return json.loads(row.panel_config_json)
    except json.JSONDecodeError:
        return None


def _problem_brief_dict(row: StudySession | None) -> dict:
    if row is None or not row.problem_brief_json:
        return default_problem_brief()
    try:
        return normalize_problem_brief(json.loads(row.problem_brief_json))
    except json.JSONDecodeError:
        return default_problem_brief()


def _sync_panel_from_problem_brief(
    row: StudySession,
    db: Session,
    problem_brief: dict,
    api_key: str | None = None,
    model_name: str | None = None,
) -> tuple[dict | None, list[str]]:
    from app.adapter import sanitize_panel_weights
    from app.services.llm import generate_config_from_brief

    current_panel = _panel_dict(row)
    derived_panel = None
    if api_key and model_name:
        derived_panel = generate_config_from_brief(
            brief=problem_brief,
            # Definition-driven sync should not carry forward stale managed fields.
            current_panel=None,
            api_key=api_key,
            model_name=model_name,
        )
    if derived_panel is None:
        derived_panel = derive_problem_panel_from_brief(problem_brief)
    if derived_panel is None:
        return None, []

    next_panel = deepcopy(current_panel) if isinstance(current_panel, dict) else {}
    next_problem = deepcopy(next_panel.get("problem")) if isinstance(next_panel.get("problem"), dict) else {}
    for key in ("weights", "only_active_terms", "algorithm", "algorithm_params", "epochs", "pop_size", "shift_hard_penalty"):
        next_problem.pop(key, None)
    next_problem.update(deepcopy(derived_panel["problem"]))
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


def _sync_problem_brief_from_panel(
    row: StudySession,
    db: Session,
    panel_config: dict,
) -> dict:
    current_problem_brief = _problem_brief_dict(row)
    next_problem_brief = sync_problem_brief_from_panel(current_problem_brief, panel_config)
    if next_problem_brief == current_problem_brief:
        return current_problem_brief
    row.problem_brief_json = json.dumps(next_problem_brief)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return next_problem_brief


def _session_to_out(row: StudySession) -> SessionOut:
    return SessionOut(
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        workflow_mode=row.workflow_mode,
        participant_number=row.participant_number,
        status=row.status,
        panel_config=_panel_dict(row),
        problem_brief=_problem_brief_dict(row),
        optimization_allowed=row.optimization_allowed,
        gemini_model=row.gemini_model,
        gemini_key_configured=bool(row.gemini_key_encrypted),
    )


def _run_number(row: OptimizationRun) -> int:
    return int(row.session_run_index or row.id)


def _run_to_out(row: OptimizationRun) -> RunOut:
    res = None
    if row.result_json:
        try:
            res = json.loads(row.result_json)
        except json.JSONDecodeError:
            res = None
    return RunOut(
        id=row.id,
        run_number=_run_number(row),
        created_at=row.created_at,
        run_type=row.run_type,
        ok=row.ok,
        cost=row.cost,
        reference_cost=row.reference_cost,
        error_message=row.error_message,
        result=res,
    )


def _next_session_run_number(db: Session, session_id: str) -> int:
    current_max = (
        db.query(func.max(OptimizationRun.session_run_index))
        .filter(OptimizationRun.session_id == session_id)
        .scalar()
    )
    return int(current_max or 0) + 1


@router.post("", response_model=SessionOut)
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    opt_allowed = body.workflow_mode == "agile"
    row = StudySession(
        id=str(uuid.uuid4()),
        workflow_mode=body.workflow_mode,
        participant_number=_clean_participant_number(body.participant_number),
        status="active",
        panel_config_json=None,
        problem_brief_json=json.dumps(default_problem_brief()),
        optimization_allowed=opt_allowed,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _session_to_out(row)


@router.get("", response_model=list[SessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    rows = db.query(StudySession).order_by(StudySession.updated_at.desc()).all()
    return [_session_to_out(r) for r in rows]


@router.post("/{session_id}/participant-starter-panel", response_model=SessionOut)
def push_participant_starter_panel(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    """Apply a mediocre default problem JSON so the participant can see panel 2 / run the solver."""
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    row.panel_config_json = json.dumps(MEDIOCRE_PARTICIPANT_STARTER_CONFIG)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _session_to_out(row)


@router.get("/{session_id}", response_model=SessionOut)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status == "deleted":
        raise HTTPException(status_code=410, detail="Session removed")
    return _session_to_out(row)


@router.get("/{session_id}/researcher", response_model=SessionOut)
def get_session_researcher(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_to_out(row)


@router.patch("/{session_id}", response_model=SessionOut)
def patch_session(
    session_id: str,
    body: SessionPatch,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if body.workflow_mode is not None:
        row.workflow_mode = body.workflow_mode
    if "participant_number" in body.model_fields_set:
        row.participant_number = _clean_participant_number(body.participant_number)
    if body.panel_config is not None:
        row.panel_config_json = json.dumps(body.panel_config)
    if body.problem_brief is not None:
        row.problem_brief_json = json.dumps(normalize_problem_brief(body.problem_brief))
    if body.optimization_allowed is not None:
        row.optimization_allowed = body.optimization_allowed
    if body.gemini_model is not None:
        row.gemini_model = body.gemini_model
    if body.gemini_api_key is not None:
        row.gemini_key_encrypted = encrypt_secret(body.gemini_api_key)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _session_to_out(row)


@router.post("/{session_id}/terminate", response_model=SessionOut)
def terminate_session(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    row.status = "terminated"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _session_to_out(row)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(row)
    db.commit()
    return None


@router.get("/{session_id}/messages", response_model=list[MessageOut])
def list_messages(
    session_id: str,
    after_id: int = 0,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status == "deleted":
        raise HTTPException(status_code=410, detail="Session removed")
    q = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.visible_to_participant.is_(True),
            ChatMessage.id > after_id,
        )
        .order_by(ChatMessage.id.asc())
    )
    return list(q.all())


@router.get("/{session_id}/messages/researcher", response_model=list[MessageOut])
def list_messages_researcher(
    session_id: str,
    after_id: int = 0,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    q = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id, ChatMessage.id > after_id)
        .order_by(ChatMessage.id.asc())
    )
    return list(q.all())


def _append_message(
    db: Session,
    session_id: str,
    role: str,
    content: str,
    visible: bool,
    kind: str = "chat",
):
    m = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        visible_to_participant=visible,
        kind=kind,
    )
    db.add(m)
    s = db.get(StudySession, session_id)
    if s:
        s.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(m)
    return m


@router.post("/{session_id}/messages", response_model=PostMessagesResponse)
def post_message(
    session_id: str,
    body: MessageCreate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    out: list[MessageOut] = []
    um = _append_message(db, session_id, "user", body.content, True)
    out.append(MessageOut.model_validate(um))
    updated_panel: dict | None = None
    updated_problem_brief: dict | None = None

    if body.invoke_model:
        key = decrypt_secret(row.gemini_key_encrypted)
        model = row.gemini_model or get_settings().default_gemini_model
        if not key:
            am = _append_message(
                db,
                session_id,
                "assistant",
                "No model API key is configured. Open settings and add a key, or continue without AI.",
                True,
            )
            out.append(MessageOut.model_validate(am))
        else:
            hist: list[tuple[str, str]] = []
            prev = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.session_id == session_id,
                    ChatMessage.visible_to_participant.is_(True),
                    ChatMessage.id < um.id,
                )
                .order_by(ChatMessage.id.desc())
                .limit(12)
                .all()
            )
            for p in reversed(prev):
                if p.role in ("user", "assistant"):
                    hist.append((p.role, p.content))

            steer_rows = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == "researcher",
                    ChatMessage.visible_to_participant.is_(False),
                    ChatMessage.id < um.id,
                )
                .order_by(ChatMessage.id.desc())
                .limit(4)
                .all()
            )
            researcher_steers = [m.content for m in reversed(steer_rows)]

            # Build compact recent-runs context for the system instruction.
            recent_run_rows = (
                db.query(OptimizationRun)
                .filter(OptimizationRun.session_id == session_id)
                .order_by(OptimizationRun.id.desc())
                .limit(4)
                .all()
            )
            recent_runs_summary: list[dict] = []
            for rr in reversed(recent_run_rows):
                entry: dict = {"run_id": rr.id, "run_number": _run_number(rr), "ok": rr.ok, "cost": rr.cost}
                if rr.result_json:
                    try:
                        rd = json.loads(rr.result_json)
                        entry["violations"] = rd.get("violations")
                        entry["metrics"] = rd.get("metrics")
                        entry["algorithm"] = rd.get("algorithm")
                    except json.JSONDecodeError:
                        pass
                recent_runs_summary.append(entry)

            text = "The model request failed. Try again or continue without AI."
            try:
                from app.services.llm import generate_chat_turn

                current = _panel_dict(row)
                current_problem_brief = _problem_brief_dict(row)
                cleanup_requested = _is_definition_cleanup_request(body.content)
                clear_requested = _is_definition_clear_request(body.content)
                turn = generate_chat_turn(
                    body.content,
                    hist,
                    key,
                    model,
                    current_problem_brief,
                    workflow_mode=row.workflow_mode,
                    recent_runs_summary=recent_runs_summary or None,
                    researcher_steers=researcher_steers or None,
                    cleanup_mode=cleanup_requested,
                )
                text = turn.assistant_message
                brief_changed = False
                patch_payload: dict | None = None
                if turn.problem_brief_patch:
                    patch_payload = dict(turn.problem_brief_patch)
                elif clear_requested:
                    # Deterministic safety net: clear requests must not silently no-op.
                    patch_payload = {"items": [], "open_questions": []}
                elif cleanup_requested:
                    log.warning("Cleanup requested but model returned no brief patch for session %s", session_id)

                if patch_payload is not None:
                    base_brief = current_problem_brief
                    if cleanup_requested or turn.cleanup_mode or turn.replace_editable_items:
                        patch_payload["replace_editable_items"] = True
                    if clear_requested:
                        patch_payload["replace_open_questions"] = True
                    elif turn.replace_open_questions:
                        patch_payload["replace_open_questions"] = True
                    elif "open_questions" in patch_payload and (
                        cleanup_requested or turn.cleanup_mode
                    ):
                        patch_payload["replace_open_questions"] = True
                    merged_brief = merge_problem_brief_patch(base_brief, patch_payload)
                    if merged_brief != base_brief:
                        row.problem_brief_json = json.dumps(merged_brief)
                        updated_problem_brief = merged_brief
                        brief_changed = True
                effective_problem_brief = updated_problem_brief or current_problem_brief
                updated_panel, weight_warnings = _sync_panel_from_problem_brief(
                    row,
                    db,
                    effective_problem_brief,
                    api_key=key,
                    model_name=model,
                )
                if updated_panel is not None and weight_warnings:
                    text = f"{text}\n\nNote: {' '.join(weight_warnings)}"
                if brief_changed and updated_problem_brief is None:
                    updated_problem_brief = _problem_brief_dict(row)
                if updated_problem_brief is not None and updated_panel is None:
                    row.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    db.refresh(row)
            except Exception:
                log.exception("Participant model turn failed for session %s", session_id)
            am = _append_message(db, session_id, "assistant", text, True)
            out.append(MessageOut.model_validate(am))

    return PostMessagesResponse(
        messages=out,
        panel_config=updated_panel,
        problem_brief=updated_problem_brief,
    )


@router.post("/{session_id}/steer", response_model=MessageOut)
def post_steer(
    session_id: str,
    body: SteerCreate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    m = _append_message(db, session_id, "researcher", body.content, False)
    return MessageOut.model_validate(m)


@router.post("/{session_id}/runs", response_model=RunOut)
def post_run(
    session_id: str,
    body: SolveRunCreate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    from app.adapter import solve_request_to_result

    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")
    if not row.optimization_allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Optimization is not enabled for this session yet",
        )

    payload = {
        "type": body.type,
        "problem": body.problem,
        "routes": body.routes,
    }
    session_run_number = _next_session_run_number(db, session_id)
    run_row = OptimizationRun(
        session_run_index=session_run_number,
        session_id=session_id,
        run_type=body.type,
        request_json=json.dumps(payload),
        ok=False,
    )
    db.add(run_row)
    db.commit()
    db.refresh(run_row)

    try:
        timeout = get_settings().solve_timeout_sec
        result = solve_request_to_result(payload, timeout)
        run_row.ok = True
        run_row.cost = float(result["cost"])
        run_row.reference_cost = (
            float(result["reference_cost"]) if result.get("reference_cost") is not None else None
        )
        run_row.result_json = json.dumps(result)
        run_row.error_message = None
    except TimeoutError:
        run_row.error_message = "Optimization timed out"
    except ValueError as e:
        run_row.error_message = str(e)
    except ImportError as e:
        run_row.error_message = "Solver dependencies missing on server"
    except Exception:
        run_row.error_message = "Optimization failed"

    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run_row)

    if run_row.ok and run_row.cost is not None:
        summary_parts = [f"Run #{session_run_number} finished — cost {run_row.cost:.2f}"]
        if run_row.result_json:
            try:
                rd = json.loads(run_row.result_json)
                v = rd.get("violations") or {}
                tw_stops = int(v.get("time_window_stop_count", 0))
                tw_mins = float(v.get("time_window_minutes_over", 0))
                cap_over = int(v.get("capacity_units_over", 0))
                prio_miss = int(v.get("priority_deadline_misses", 0))
                shift_pen = float(v.get("shift_limit_penalty", 0))
                m = rd.get("metrics") or {}
                travel = float(m.get("total_travel_minutes", 0))
                wl_var = float(m.get("workload_variance", 0))
                viol_strs = []
                if tw_stops:
                    viol_strs.append(f"{tw_stops} time-window stops late ({tw_mins:.1f} min over)")
                if cap_over:
                    viol_strs.append(f"{cap_over} units over capacity")
                if prio_miss:
                    viol_strs.append(f"{prio_miss} priority-order deadline misses")
                if shift_pen:
                    viol_strs.append("shift limit exceeded")
                if viol_strs:
                    summary_parts.append("Violations: " + "; ".join(viol_strs))
                else:
                    summary_parts.append("No constraint violations")
                summary_parts.append(
                    f"Travel: {travel:.1f} min · workload variance: {wl_var:.1f}"
                )
                # Surface any weight key warnings from translation (fuzzy matches / drops).
                weight_warnings = rd.get("weight_warnings") or []
                for w in weight_warnings:
                    summary_parts.append(f"Note: {w}")
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        summary = ". ".join(summary_parts) + "."
    else:
        summary = f"Run #{session_run_number} failed: {run_row.error_message or 'error'}."
    _append_message(db, session_id, "assistant", summary, True, kind="run")
    return _run_to_out(run_row)


@router.get("/{session_id}/runs", response_model=list[RunOut])
def list_runs(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_any_study_user),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if principal == Principal.client and row.status == "deleted":
        raise HTTPException(status_code=410, detail="Session removed")
    rows = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.session_id == session_id)
        .order_by(OptimizationRun.id.asc())
        .all()
    )
    return [_run_to_out(r) for r in rows]


@router.delete("/{session_id}/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(
    session_id: str,
    run_id: int,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    run = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.session_id == session_id, OptimizationRun.id == run_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    db.delete(run)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return None


@router.patch("/{session_id}/settings", response_model=SessionOut)
def patch_participant_model_settings(
    session_id: str,
    body: ModelSettingsBody,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")
    if body.gemini_model is not None:
        row.gemini_model = body.gemini_model
    if body.gemini_api_key is not None:
        row.gemini_key_encrypted = encrypt_secret(body.gemini_api_key)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _session_to_out(row)


@router.patch("/{session_id}/panel", response_model=SessionOut)
def patch_participant_panel(
    session_id: str,
    body: ParticipantPanelUpdate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    # Sanitize weight keys in the panel before storing, so unknown/fuzzy keys are
    # translated or dropped early and the stored panel stays consistent.
    from app.adapter import sanitize_panel_weights
    sanitized_config, weight_warnings = sanitize_panel_weights(body.panel_config)

    row.panel_config_json = json.dumps(sanitized_config)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    _sync_problem_brief_from_panel(row, db, sanitized_config)

    # Build acknowledgement, appending any weight-key correction notices.
    ack_parts = []
    if body.acknowledgement:
        ack_parts.append(body.acknowledgement)
    for w in weight_warnings:
        ack_parts.append(f"Note: {w}")
    ack = " ".join(ack_parts).strip()
    if ack:
        _append_message(db, session_id, "assistant", ack, True, kind="panel")
    return _session_to_out(row)


@router.patch("/{session_id}/problem-brief", response_model=SessionOut)
def patch_participant_problem_brief(
    session_id: str,
    body: ParticipantProblemBriefUpdate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    next_problem_brief = normalize_problem_brief(body.problem_brief.model_dump())
    row.problem_brief_json = json.dumps(next_problem_brief)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    _sync_panel_from_problem_brief(
        row,
        db,
        next_problem_brief,
        api_key=decrypt_secret(row.gemini_key_encrypted),
        model_name=row.gemini_model or get_settings().default_gemini_model,
    )

    if body.acknowledgement:
        _append_message(db, session_id, "assistant", body.acknowledgement, True, kind="panel")
    return _session_to_out(row)


@router.post("/{session_id}/sync-panel", response_model=SessionOut)
def sync_panel_from_problem_brief(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    problem_brief = _problem_brief_dict(row)
    updated_panel, _ = _sync_panel_from_problem_brief(
        row,
        db,
        problem_brief,
        api_key=decrypt_secret(row.gemini_key_encrypted),
        model_name=row.gemini_model or get_settings().default_gemini_model,
    )
    if updated_panel is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Problem definition is not specific enough to sync a solver configuration yet",
        )
    return _session_to_out(row)


@router.post("/{session_id}/simulate-upload", status_code=status.HTTP_204_NO_CONTENT)
def simulate_upload(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")
    return None


@router.get("/{session_id}/export")
def export_session(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = (
        db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.id.asc()).all()
    )
    runs = (
        db.query(OptimizationRun).filter(OptimizationRun.session_id == session_id).order_by(OptimizationRun.id.asc()).all()
    )
    return {
        "session": {
            "id": row.id,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "workflow_mode": row.workflow_mode,
            "participant_number": row.participant_number,
            "status": row.status,
            "panel_config": _panel_dict(row),
            "problem_brief": _problem_brief_dict(row),
            "optimization_allowed": row.optimization_allowed,
            "gemini_model": row.gemini_model,
        },
        "messages": [
            {
                "id": m.id,
                "created_at": m.created_at.isoformat(),
                "role": m.role,
                "content": m.content,
                "visible_to_participant": m.visible_to_participant,
                "kind": m.kind,
            }
            for m in messages
        ],
        "runs": [
            {
                "id": r.id,
                "run_number": _run_number(r),
                "created_at": r.created_at.isoformat(),
                "run_type": r.run_type,
                "ok": r.ok,
                "cost": r.cost,
                "reference_cost": r.reference_cost,
                "error_message": r.error_message,
                "request": json.loads(r.request_json) if r.request_json else None,
                "result": json.loads(r.result_json) if r.result_json else None,
            }
            for r in runs
        ],
    }
