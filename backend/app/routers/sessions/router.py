"""Sessions API router."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import Principal, require_any_study_user, require_client, require_researcher
from app.config import get_settings
from app.crypto_util import encrypt_secret
from app.database import get_db
from app.default_config import MEDIOCRE_PARTICIPANT_STARTER_CONFIG
from app.models import ChatMessage, OptimizationRun, SessionSnapshot, StudySession
from app.problem_brief import default_problem_brief, merge_problem_brief_patch, normalize_problem_brief
from app.schemas import (
    MessageCreate,
    MessageOut,
    ModelSettingsBody,
    ParticipantPanelUpdate,
    ParticipantProblemBriefUpdate,
    PostMessagesResponse,
    RunOut,
    SessionCreate,
    SessionProcessingState,
    SessionOut,
    SessionPatch,
    SnapshotOut,
    SolveRunCreate,
    SteerCreate,
)
from app.session_snapshots import EVENT_BEFORE_RUN, EVENT_MANUAL_SAVE, create_snapshot

from . import context, derivation, helpers, intent, sync

router = APIRouter(prefix="/sessions", tags=["sessions"])
log = logging.getLogger(__name__)


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
        participant_number=helpers.clean_participant_number(body.participant_number),
        status="active",
        panel_config_json=None,
        problem_brief_json=json.dumps(default_problem_brief()),
        processing_revision=0,
        brief_status="ready",
        config_status="idle",
        processing_error=None,
        optimization_allowed=opt_allowed,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return helpers.session_to_out(row)


@router.get("/for-participant", response_model=list[SessionOut])
def list_sessions_for_participant(
    participant_number: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    """List sessions for the given participant number (participant-facing, safe filter)."""
    cleaned = helpers.clean_participant_number(participant_number)
    if not cleaned:
        raise HTTPException(status_code=400, detail="participant_number required")
    lower_val = cleaned.lower()
    rows = (
        db.query(StudySession)
        .filter(
            StudySession.participant_number.isnot(None),
            func.lower(StudySession.participant_number) == lower_val,
        )
        .order_by(StudySession.updated_at.desc())
        .limit(30)
        .all()
    )
    return [helpers.session_to_out(r) for r in rows]


@router.get("", response_model=list[SessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    rows = db.query(StudySession).order_by(StudySession.updated_at.desc()).all()
    return [helpers.session_to_out(r) for r in rows]


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
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return helpers.session_to_out(row)


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
    return helpers.session_to_out(row)


@router.get("/{session_id}/researcher", response_model=SessionOut)
def get_session_researcher(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return helpers.session_to_out(row)


def _snapshot_to_out(snap: SessionSnapshot) -> SnapshotOut:
    """Build SnapshotOut from a SessionSnapshot row."""
    brief: dict[str, Any] | None = None
    panel: dict[str, Any] | None = None
    items_count = 0
    questions_count = 0
    has_config = False
    if snap.problem_brief_json:
        try:
            brief = json.loads(snap.problem_brief_json)
            items_count = len(brief.get("items") or [])
            questions_count = len(brief.get("open_questions") or [])
        except (json.JSONDecodeError, TypeError):
            pass
    if snap.panel_config_json:
        try:
            panel = json.loads(snap.panel_config_json)
            has_config = bool(panel and panel.get("problem"))
        except (json.JSONDecodeError, TypeError):
            pass
    return SnapshotOut(
        id=snap.id,
        created_at=snap.created_at,
        event_type=snap.event_type or "before_run",
        items_count=items_count,
        questions_count=questions_count,
        has_config=has_config,
        problem_brief=brief,
        panel_config=panel,
    )


@router.get("/{session_id}/snapshots", response_model=list[SnapshotOut])
def list_snapshots(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_client),
):
    """List snapshots for the session (brief+panel history)."""
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status == "deleted":
        raise HTTPException(status_code=410, detail="Session removed")
    snaps = (
        db.query(SessionSnapshot)
        .filter(SessionSnapshot.session_id == session_id)
        .order_by(SessionSnapshot.created_at.desc())
        .all()
    )
    return [_snapshot_to_out(s) for s in snaps]


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
        row.participant_number = helpers.clean_participant_number(body.participant_number)
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
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return helpers.session_to_out(row)


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
    return helpers.session_to_out(row)


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
    um = derivation.append_message(db, session_id, "user", body.content, True)
    out.append(MessageOut.model_validate(um))
    updated_panel: dict | None = None
    updated_problem_brief: dict | None = None
    proc_state: SessionProcessingState | None = None

    if body.invoke_model:
        from app.crypto_util import decrypt_secret

        key = decrypt_secret(row.gemini_key_encrypted)
        model = row.gemini_model or get_settings().default_gemini_model
        if not key:
            am = derivation.append_message(
                db,
                session_id,
                "assistant",
                "No model API key is configured. Open settings and add a key, or continue without AI.",
                True,
            )
            out.append(MessageOut.model_validate(am))
            proc_state = helpers.processing_state(db.get(StudySession, session_id) or row)
        else:
            hist, researcher_steers, recent_runs_summary = context.load_turn_context(db, session_id, um.id)
            text = "The model request failed. Try again or continue without AI."
            current = helpers.panel_dict(row)
            current_problem_brief = helpers.problem_brief_dict(row)
            updated_panel = current
            cleanup_requested = intent.is_definition_cleanup_request(body.content)
            clear_requested = intent.is_definition_clear_request(body.content)
            is_run_ack = intent.is_run_acknowledgement_message(body.content)
            turn = None
            try:
                from app.services.llm import generate_chat_turn

                turn = generate_chat_turn(
                    body.content,
                    hist,
                    key,
                    model,
                    current_problem_brief,
                    workflow_mode=row.workflow_mode,
                    recent_runs_summary=recent_runs_summary or None,
                    current_panel=current,
                    researcher_steers=researcher_steers or None,
                    cleanup_mode=cleanup_requested,
                    is_run_acknowledgement=is_run_ack,
                )
                text = turn.assistant_message
            except Exception:
                log.exception("Participant model turn failed for session %s", session_id)
            text = intent.sanitize_visible_assistant_reply(text)
            am = derivation.append_message(db, session_id, "assistant", text, True)
            out.append(MessageOut.model_validate(am))
            if turn and (
                turn.problem_brief_patch is not None
                or turn.replace_editable_items
                or turn.replace_open_questions
                or turn.cleanup_mode
                or clear_requested
            ):
                patch_payload: dict[str, Any] | None = None
                if turn.problem_brief_patch:
                    patch_payload = dict(turn.problem_brief_patch)
                elif clear_requested:
                    patch_payload = {"items": [], "open_questions": []}
                elif cleanup_requested:
                    log.warning("Cleanup requested but model returned no brief patch for session %s", session_id)

                if patch_payload is not None:
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
                    merged_brief = merge_problem_brief_patch(current_problem_brief, patch_payload)
                    if merged_brief != current_problem_brief:
                        row = db.get(StudySession, session_id) or row
                        row.problem_brief_json = json.dumps(merged_brief)
                        updated_problem_brief = merged_brief
                        helpers.touch_session(row)
                        db.commit()
                        db.refresh(row)
                effective_problem_brief = updated_problem_brief or current_problem_brief
                row = db.get(StudySession, session_id) or row
                updated_panel, _ = sync.sync_panel_from_problem_brief(
                    row,
                    db,
                    effective_problem_brief,
                    api_key=key,
                    model_name=model,
                    workflow_mode=row.workflow_mode,
                    recent_runs_summary=recent_runs_summary,
                    preserve_missing_managed_fields=True,
                )
                row = db.get(StudySession, session_id) or row
                helpers.settle_processing_state(row, cancel_revision=True)
                helpers.touch_session(row)
                db.commit()
                db.refresh(row)
                proc_state = helpers.processing_state(row)
            else:
                row = db.get(StudySession, session_id) or row
                revision = helpers.mark_processing_pending(row)
                db.commit()
                db.refresh(row)
                proc_state = helpers.processing_state(row)
                derivation.launch_background_derivation(
                    session_id=session_id,
                    revision=revision,
                    user_text=body.content,
                    workflow_mode=row.workflow_mode,
                    api_key=key,
                    model_name=model,
                    history_lines=hist,
                    researcher_steers=researcher_steers,
                    recent_runs_summary=recent_runs_summary,
                    base_problem_brief=current_problem_brief,
                    base_panel=current,
                    cleanup_requested=cleanup_requested,
                    clear_requested=clear_requested,
                    is_run_acknowledgement=is_run_ack,
                )

    return PostMessagesResponse(
        messages=out,
        panel_config=updated_panel,
        problem_brief=updated_problem_brief,
        processing=proc_state,
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
    m = derivation.append_message(db, session_id, "researcher", body.content, False)
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
    session_run_number = helpers.next_session_run_number(db, session_id)
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

    create_snapshot(db, session_id, EVENT_BEFORE_RUN)

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
                weight_warnings = rd.get("weight_warnings") or []
                for w in weight_warnings:
                    summary_parts.append(f"Note: {w}")
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        summary = ". ".join(summary_parts) + "."
    else:
        summary = f"Run #{session_run_number} failed: {run_row.error_message or 'error'}."
    derivation.append_message(db, session_id, "assistant", summary, True, kind="run")
    return helpers.run_to_out(run_row)


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
    return [helpers.run_to_out(r) for r in rows]


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
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return helpers.session_to_out(row)


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

    from app.adapter import sanitize_panel_weights

    sanitized_config, weight_warnings = sanitize_panel_weights(body.panel_config)

    row.panel_config_json = json.dumps(sanitized_config)
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    sync.sync_problem_brief_from_panel(row, db, sanitized_config)
    helpers.settle_processing_state(row)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    create_snapshot(db, session_id, EVENT_MANUAL_SAVE)

    ack_parts = []
    if body.acknowledgement:
        ack_parts.append(body.acknowledgement)
    for w in weight_warnings:
        ack_parts.append(f"Note: {w}")
    ack = " ".join(ack_parts).strip()
    if ack:
        derivation.append_message(db, session_id, "assistant", ack, True, kind="panel")
    return helpers.session_to_out(row)


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
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    from app.crypto_util import decrypt_secret

    sync.sync_panel_from_problem_brief(
        row,
        db,
        next_problem_brief,
        api_key=decrypt_secret(row.gemini_key_encrypted),
        model_name=row.gemini_model or get_settings().default_gemini_model,
        workflow_mode=row.workflow_mode,
    )
    helpers.settle_processing_state(row)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    create_snapshot(db, session_id, EVENT_MANUAL_SAVE)

    if body.acknowledgement:
        derivation.append_message(db, session_id, "assistant", body.acknowledgement, True, kind="panel")
    return helpers.session_to_out(row)


@router.post("/{session_id}/sync-panel", response_model=SessionOut)
def sync_panel_from_problem_brief_route(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    from app.crypto_util import decrypt_secret

    problem_brief = helpers.problem_brief_dict(row)
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    updated_panel, _ = sync.sync_panel_from_problem_brief(
        row,
        db,
        problem_brief,
        api_key=decrypt_secret(row.gemini_key_encrypted),
        model_name=row.gemini_model or get_settings().default_gemini_model,
        workflow_mode=row.workflow_mode,
    )
    if updated_panel is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Problem definition is not specific enough to sync a solver configuration yet",
        )
    helpers.settle_processing_state(row)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return helpers.session_to_out(row)


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
            "panel_config": helpers.panel_dict(row),
            "problem_brief": helpers.problem_brief_dict(row),
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
                "run_number": helpers.run_number(r),
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
