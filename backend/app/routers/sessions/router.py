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
from app.optimization_gate import can_run_optimization
from app.problem_brief import default_problem_brief, merge_problem_brief_patch, normalize_problem_brief
from app.schemas import (
    MessageCreate,
    MessageOut,
    ModelSettingsBody,
    ParticipantPanelUpdate,
    ParticipantProblemBriefUpdate,
    PostMessagesResponse,
    ResearcherSimulateParticipantUploadBody,
    RunOut,
    SessionCreate,
    SessionProcessingState,
    SessionOut,
    SessionPatch,
    SnapshotOut,
    SolveRunCreate,
    SteerCreate,
    serialize_utc_datetime,
)
from app.session_snapshots import EVENT_BEFORE_RUN, EVENT_BOOKMARK, EVENT_MANUAL_SAVE, create_snapshot

from . import context, derivation, helpers, intent, sync

router = APIRouter(prefix="/sessions", tags=["sessions"])
log = logging.getLogger(__name__)


def _run_gate_blocked_message(row: StudySession, brief_obj: dict[str, Any]) -> str:
    mode = str(row.workflow_mode or "").strip().lower()
    if bool(row.optimization_runs_blocked_by_researcher):
        return "I can run optimization once the researcher re-enables runs for this session."
    if mode == "agile":
        return (
            "I can start a run once the configuration includes at least one objective weight "
            "and a selected search algorithm."
        )
    if mode == "waterfall":
        if not bool(getattr(row, "optimization_gate_engaged", False)):
            return "I can start a run after we engage the optimization gate in chat."
        open_questions = brief_obj.get("open_questions") or []
        if any(isinstance(q, dict) and str(q.get("status") or "").strip().lower() == "open" for q in open_questions):
            return "I can start a run after all open questions in the Definition tab are answered."
        return "I can start a run once run prerequisites are satisfied."
    return "I can start a run once run prerequisites are satisfied."


@router.post("", response_model=SessionOut)
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
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
        optimization_allowed=False,
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
    if helpers.sync_optimization_allowed_after_participant_mutation(row):
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


@router.post("/{session_id}/snapshots", response_model=SnapshotOut, status_code=status.HTTP_201_CREATED)
def post_session_snapshot_bookmark(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    """Bookmark current saved brief+panel as a snapshot without PATCHing session (no chat message)."""
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")
    snap = create_snapshot(db, session_id, EVENT_BOOKMARK)
    if snap is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _snapshot_to_out(snap)


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
    if body.optimization_runs_blocked_by_researcher is not None:
        row.optimization_runs_blocked_by_researcher = body.optimization_runs_blocked_by_researcher
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


def _handle_post_participant_message(session_id: str, db: Session, body: MessageCreate) -> PostMessagesResponse:
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
            is_answer_save = intent.is_answered_open_question_message(body.content)
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
            run_intent = None
            # Auto-posted run-complete messages must never be classified as "run now" intent.
            if not is_run_ack:
                try:
                    from app.services.llm import classify_run_trigger_intent

                    run_intent = classify_run_trigger_intent(
                        user_text=body.content,
                        history_lines=hist,
                        api_key=key,
                        model_name=model,
                        workflow_mode=row.workflow_mode,
                    )
                except Exception:
                    log.exception("Run-trigger intent classification failed for session %s", session_id)
            if turn and (
                turn.problem_brief_patch is not None
                or turn.replace_editable_items
                or turn.replace_open_questions
                or turn.cleanup_mode
                or clear_requested
            ):
                try:
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
                except Exception:
                    log.exception("Inline brief/config sync failed for session %s", session_id)
                    row = db.get(StudySession, session_id) or row
                    helpers.fail_processing_state(row, "Inline problem-config sync failed", cancel_revision=True)
                    db.commit()
                    db.refresh(row)
                    proc_state = helpers.processing_state(row)
            elif body.skip_hidden_brief_update:
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
                    is_answered_open_question=is_answer_save,
                )

            row = db.get(StudySession, session_id) or row
            panel_obj: dict[str, Any] | None = None
            if row.panel_config_json:
                try:
                    parsed_panel = json.loads(row.panel_config_json)
                    panel_obj = parsed_panel if isinstance(parsed_panel, dict) else None
                except json.JSONDecodeError:
                    panel_obj = None
            try:
                brief_obj = json.loads(row.problem_brief_json) if row.problem_brief_json else default_problem_brief()
            except json.JSONDecodeError:
                brief_obj = default_problem_brief()
            can_run_now = can_run_optimization(
                row.workflow_mode,
                row.optimization_allowed,
                row.optimization_runs_blocked_by_researcher,
                panel_obj,
                brief_obj,
                optimization_gate_engaged=bool(getattr(row, "optimization_gate_engaged", False)),
            )
            if (
                run_intent is not None
                and run_intent.should_trigger_run
                and run_intent.intent_type in {"affirm_invite", "direct_request"}
            ):
                if can_run_now:
                    has_recent_run_reply = (
                        db.query(ChatMessage)
                        .filter(
                            ChatMessage.session_id == session_id,
                            ChatMessage.kind == "run",
                            ChatMessage.id > am.id,
                        )
                        .first()
                        is not None
                    )
                    if not has_recent_run_reply:
                        try:
                            problem_payload = (
                                panel_obj.get("problem")
                                if isinstance(panel_obj, dict) and isinstance(panel_obj.get("problem"), dict)
                                else (panel_obj or {})
                            )
                            post_run(
                                session_id,
                                SolveRunCreate(type="optimize", problem=problem_payload),
                                db,
                                None,
                            )
                        except HTTPException:
                            log.info("Auto-run trigger skipped due to run endpoint guard for session %s", session_id)
                elif run_intent.intent_type == "direct_request":
                    blocked_msg = _run_gate_blocked_message(row, brief_obj)
                    bm = derivation.append_message(db, session_id, "assistant", blocked_msg, True)
                    out.append(MessageOut.model_validate(bm))

    row = db.get(StudySession, session_id)
    if row is not None and helpers.sync_optimization_allowed_after_participant_mutation(row):
        db.commit()
        db.refresh(row)

    if proc_state is None:
        row = db.get(StudySession, session_id) or row
        proc_state = helpers.processing_state(row)

    return PostMessagesResponse(
        messages=out,
        panel_config=updated_panel,
        problem_brief=updated_problem_brief,
        processing=proc_state,
    )


@router.post("/{session_id}/messages", response_model=PostMessagesResponse)
def post_message(
    session_id: str,
    body: MessageCreate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    return _handle_post_participant_message(session_id, db, body)


@router.post("/{session_id}/researcher/simulate-participant-upload", response_model=PostMessagesResponse)
def researcher_simulate_participant_upload(
    session_id: str,
    body: ResearcherSimulateParticipantUploadBody | None = None,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    """Post the same user-visible message as a simulated upload (for demos / dry runs)."""
    b = body or ResearcherSimulateParticipantUploadBody()
    names = list(b.file_names) if b.file_names else ["DRIVER_INFO.csv", "ORDERS.csv"]
    cleaned = [n.strip() for n in names if isinstance(n, str) and n.strip()]
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file_names must not be empty")
    content = f"I'm uploading the following file(s): {', '.join(cleaned)}"
    return _handle_post_participant_message(
        session_id,
        db,
        MessageCreate(content=content, invoke_model=b.invoke_model, skip_hidden_brief_update=False),
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


def _post_optimization_cancel(session_id: str, db: Session) -> dict[str, bool]:
    """Signal an in-flight optimize (same session) to stop early; no-op if none running."""
    from app.solve_cancel import request_cancel

    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"signalled": request_cancel(session_id)}


@router.post("/{session_id}/runs/cancel")
def post_cancel_optimization_runs_cancel(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    return _post_optimization_cancel(session_id, db)


@router.post("/{session_id}/optimization/cancel")
def post_cancel_optimization_alt_path(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    """Same as POST .../runs/cancel; alternate path for proxies that mishandle `/runs/cancel`."""
    return _post_optimization_cancel(session_id, db)


@router.post("/{session_id}/runs", response_model=RunOut)
def post_run(
    session_id: str,
    body: SolveRunCreate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    from app.adapter import RunCancelled, solve_request_to_result
    from app.solve_cancel import clear_cancel_event, register_cancel_event

    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")
    panel_obj: dict[str, Any] | None = None
    if row.panel_config_json:
        try:
            parsed = json.loads(row.panel_config_json)
            panel_obj = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            panel_obj = None
    try:
        brief_obj = json.loads(row.problem_brief_json) if row.problem_brief_json else default_problem_brief()
    except json.JSONDecodeError:
        brief_obj = default_problem_brief()

    if not can_run_optimization(
        row.workflow_mode,
        row.optimization_allowed,
        row.optimization_runs_blocked_by_researcher,
        panel_obj,
        brief_obj,
        optimization_gate_engaged=bool(getattr(row, "optimization_gate_engaged", False)),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Optimization is not allowed (researcher block, or intrinsic readiness not met and no permit)",
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

    cancel_ev = register_cancel_event(session_id) if str(body.type).lower() == "optimize" else None
    try:
        timeout = get_settings().solve_timeout_sec
        result = solve_request_to_result(payload, timeout, cancel_event=cancel_ev)
        run_row.ok = True
        run_row.cost = float(result["cost"])
        run_row.reference_cost = (
            float(result["reference_cost"]) if result.get("reference_cost") is not None else None
        )
        run_row.result_json = json.dumps(result)
        run_row.error_message = None
    except RunCancelled:
        run_row.error_message = "Optimization cancelled"
    except TimeoutError:
        run_row.error_message = "Optimization timed out"
    except ValueError as e:
        run_row.error_message = str(e)
    except ImportError as e:
        run_row.error_message = "Solver dependencies missing on server"
    except Exception:
        run_row.error_message = "Optimization failed"
    finally:
        if cancel_ev is not None:
            clear_cancel_event(session_id)

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

    if helpers.sync_optimization_allowed_after_participant_mutation(row):
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
        preserve_missing_managed_fields=True,
    )
    helpers.settle_processing_state(row)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    if helpers.sync_optimization_allowed_after_participant_mutation(row):
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
        preserve_missing_managed_fields=True,
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
    if helpers.sync_optimization_allowed_after_participant_mutation(row):
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
            "created_at": serialize_utc_datetime(row.created_at),
            "updated_at": serialize_utc_datetime(row.updated_at),
            "workflow_mode": row.workflow_mode,
            "participant_number": row.participant_number,
            "status": row.status,
            "panel_config": helpers.panel_dict(row),
            "problem_brief": helpers.problem_brief_dict(row),
            "optimization_allowed": row.optimization_allowed,
            "optimization_runs_blocked_by_researcher": row.optimization_runs_blocked_by_researcher,
            "optimization_gate_engaged": bool(getattr(row, "optimization_gate_engaged", False)),
            "gemini_model": row.gemini_model,
        },
        "messages": [
            {
                "id": m.id,
                "created_at": serialize_utc_datetime(m.created_at),
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
                "created_at": serialize_utc_datetime(r.created_at),
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
