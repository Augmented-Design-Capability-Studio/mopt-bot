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
from app.problems.registry import DEFAULT_PROBLEM_ID, get_study_port as _get_study_port, register_study_ports
from app.models import ChatMessage, OptimizationRun, SessionSnapshot, StudySession
from app.optimization_gate import can_run_optimization
from app.problem_brief import (
    coerce_problem_brief_for_workflow,
    default_problem_brief,
    merge_problem_brief_patch,
    normalize_problem_brief,
    resolve_upload_open_questions_after_upload,
)
from app.schemas import (
    CleanupOpenQuestionsBody,
    MessageCreate,
    MessageOut,
    ModelSettingsBody,
    OpenQuestionClassifierInput,
    ParticipantPanelUpdate,
    ParticipantProblemBriefUpdate,
    ParticipantTutorialUpdate,
    PostMessagesResponse,
    ResearcherSimulateParticipantUploadBody,
    RunEvaluateEditBody,
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
from app.session_export import EXPORT_SCHEMA_VERSION, build_export_timeline
from app.session_snapshots import EVENT_BEFORE_RUN, EVENT_BOOKMARK, EVENT_MANUAL_SAVE, create_snapshot

from . import context, derivation, helpers, intent, sync

router = APIRouter(prefix="/sessions", tags=["sessions"])
log = logging.getLogger(__name__)
SIMULATED_UPLOAD_MESSAGE_PREFIX = "I'm uploading the following file(s): "


def _route_oq_answers_through_classifier(
    *,
    incoming_brief: dict[str, Any],
    persisted_open_questions: list[dict[str, Any]],
    workflow_mode: str,
    api_key: str | None,
    model_name: str,
    test_problem_id: str | None,
) -> dict[str, Any]:
    """Mutate `incoming_brief` so newly-answered OQs are rephrased + bucketed by the LLM.

    For each OQ that flipped to status="answered" with non-empty answer_text:
    - bucket="gathered": drop the OQ, append a `gathered` item with the rephrased text.
    - bucket="assumption" (agile/demo only): drop the OQ, append an `assumption` item.
    - bucket="new_open_question" (waterfall only): replace the OQ with a simpler follow-up
      carrying `choices`.
    Inputs the classifier doesn't return (or that fail mode-gating) stay as answered OQs
    so the legacy `_promote_answered_open_questions_to_gathered` step in normalization
    handles them as fallback.
    """
    if not api_key:
        return incoming_brief
    open_questions = incoming_brief.get("open_questions") or []
    if not isinstance(open_questions, list):
        return incoming_brief

    persisted_by_id = {
        str(q.get("id") or ""): q
        for q in persisted_open_questions
        if isinstance(q, dict)
    }

    inputs: list[OpenQuestionClassifierInput] = []
    for q in open_questions:
        if not isinstance(q, dict):
            continue
        if str(q.get("status") or "").strip().lower() != "answered":
            continue
        answer = str(q.get("answer_text") or "").strip()
        if not answer:
            continue
        qid = str(q.get("id") or "").strip()
        prior = persisted_by_id.get(qid)
        already_answered = (
            prior is not None
            and str(prior.get("status") or "open").strip().lower() == "answered"
        )
        if already_answered:
            continue
        text = str(q.get("text") or "").strip()
        if not text:
            continue
        inputs.append(
            OpenQuestionClassifierInput(
                question_id=qid or text,
                question_text=text,
                answer_text=answer,
            )
        )

    if not inputs:
        return incoming_brief

    from app.services.llm import classify_answered_open_questions

    classifications = classify_answered_open_questions(
        inputs=inputs,
        workflow_mode=workflow_mode,
        current_problem_brief=incoming_brief,
        api_key=api_key,
        model_name=model_name,
        test_problem_id=test_problem_id,
    )
    if not classifications:
        return incoming_brief

    classified_by_id: dict[str, Any] = {}
    for entry in classifications:
        classified_by_id[str(entry.question_id)] = entry

    mode = (workflow_mode or "").strip().lower()
    next_questions: list[dict[str, Any]] = []
    items = list(incoming_brief.get("items") or [])

    for q in open_questions:
        if not isinstance(q, dict):
            next_questions.append(q)
            continue
        qid = str(q.get("id") or "").strip()
        c = classified_by_id.get(qid) or classified_by_id.get(str(q.get("text") or "").strip())
        if c is None:
            next_questions.append(q)
            continue

        if c.bucket == "new_open_question" and mode == "waterfall":
            new_text = (c.new_question_text or "").strip()
            new_choices = [s.strip() for s in (c.choices or []) if isinstance(s, str) and s.strip()]
            if not new_text or len(new_choices) < 2:
                next_questions.append(q)
                continue
            next_questions.append(
                {
                    "id": f"{qid}-followup" if qid else f"question-followup-{len(next_questions)}",
                    "text": new_text,
                    "status": "open",
                    "answer_text": None,
                    "choices": new_choices,
                }
            )
            continue

        if c.bucket == "assumption" and mode in ("agile", "demo"):
            assumption_text = (c.assumption_text or "").strip()
            if not assumption_text:
                next_questions.append(q)
                continue
            items.append(
                {
                    "id": f"item-assumption-from-question-{qid}" if qid else f"item-assumption-{len(items)}",
                    "text": assumption_text,
                    "kind": "assumption",
                    "source": "agent",
                }
            )
            continue

        if c.bucket == "gathered":
            rephrased = (c.rephrased_text or "").strip()
            if not rephrased:
                next_questions.append(q)
                continue
            items.append(
                {
                    "id": f"item-gathered-from-question-{qid}" if qid else f"item-gathered-{len(items)}",
                    "text": rephrased,
                    "kind": "gathered",
                    "source": "user",
                }
            )
            continue

        # Mode mismatch (e.g. classifier emitted assumption for waterfall) — leave the OQ
        # answered so legacy normalization promotes it the old way.
        next_questions.append(q)

    incoming_brief["items"] = items
    incoming_brief["open_questions"] = next_questions
    return incoming_brief


def _session_has_uploaded_data(db: Session, session_id: str) -> bool:
    return (
        db.query(ChatMessage.id)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "user",
            ChatMessage.content.like(f"{SIMULATED_UPLOAD_MESSAGE_PREFIX}%"),
        )
        .first()
        is not None
    )


def _parse_simulated_upload_file_names(content: str) -> list[str]:
    if not content.startswith(SIMULATED_UPLOAD_MESSAGE_PREFIX):
        return []
    return [name.strip() for name in content[len(SIMULATED_UPLOAD_MESSAGE_PREFIX) :].split(",") if name.strip()]


def _run_gate_blocked_message(row: StudySession, brief_obj: dict[str, Any], has_uploaded_data: bool) -> str:
    mode = str(row.workflow_mode or "").strip().lower()
    if bool(row.optimization_runs_blocked_by_researcher):
        return "I can run optimization once the researcher re-enables runs for this session."
    if mode in ("agile", "demo"):
        if not has_uploaded_data:
            return (
                "I can start a run after you add a simulated upload using the **Upload file(s)...** "
                "button in the chat footer (exact label)."
            )
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


def _resolve_new_session_test_problem_id(raw: str | None) -> str:
    if raw is None or not str(raw).strip():
        return DEFAULT_PROBLEM_ID
    pid = str(raw).strip().lower()
    if pid not in register_study_ports():
        raise HTTPException(status_code=400, detail=f"Unknown test_problem_id: {pid}")
    return pid


@router.post("", response_model=SessionOut)
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_any_study_user),
):
    tpid = _resolve_new_session_test_problem_id(body.test_problem_id)
    row = StudySession(
        id=str(uuid.uuid4()),
        workflow_mode=body.workflow_mode,
        participant_number=helpers.clean_participant_number(body.participant_number),
        test_problem_id=tpid,
        status="active",
        panel_config_json=None,
        problem_brief_json=json.dumps(default_problem_brief(tpid)),
        processing_revision=0,
        brief_status="ready",
        config_status="idle",
        processing_error=None,
        optimization_allowed=False,
        participant_tutorial_enabled=False,
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
    row.panel_config_json = json.dumps(_get_study_port(row.test_problem_id).mediocre_participant_starter_config())
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
    if body.test_problem_id is not None:
        row.test_problem_id = str(body.test_problem_id).strip().lower()[:64] or DEFAULT_PROBLEM_ID
    if "participant_number" in body.model_fields_set:
        row.participant_number = helpers.clean_participant_number(body.participant_number)
    if body.panel_config is not None:
        row.panel_config_json = json.dumps(body.panel_config)
    if body.problem_brief is not None:
        row.problem_brief_json = json.dumps(
            coerce_problem_brief_for_workflow(body.problem_brief, row.workflow_mode)
        )
    if body.optimization_allowed is not None:
        row.optimization_allowed = body.optimization_allowed
    if body.optimization_runs_blocked_by_researcher is not None:
        row.optimization_runs_blocked_by_researcher = body.optimization_runs_blocked_by_researcher
    if body.participant_tutorial_enabled is not None:
        row.participant_tutorial_enabled = body.participant_tutorial_enabled
    if "tutorial_step_override" in body.model_fields_set:
        row.tutorial_step_override = body.tutorial_step_override
        helpers.rewind_tutorial_tracking_from_step(row, row.tutorial_step_override)
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


@router.post("/{session_id}/reset", response_model=SessionOut)
def reset_session(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    """Clear session activity while preserving participant id and model/key settings."""
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.query(OptimizationRun).filter(OptimizationRun.session_id == session_id).delete()
    db.query(SessionSnapshot).filter(SessionSnapshot.session_id == session_id).delete()
    row.status = "active"
    row.panel_config_json = None
    pid = str(getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID)
    row.problem_brief_json = json.dumps(default_problem_brief(pid))
    row.content_reset_revision = int(getattr(row, "content_reset_revision", 0) or 0) + 1
    row.optimization_allowed = False
    row.optimization_runs_blocked_by_researcher = False
    row.optimization_gate_engaged = False
    row.tutorial_step_override = None
    row.tutorial_chat_started = False
    row.tutorial_uploaded_files = False
    row.tutorial_definition_tab_visited = False
    row.tutorial_definition_saved = False
    row.tutorial_config_tab_visited = False
    row.tutorial_config_first_saved = False
    row.tutorial_config_saved = False
    row.tutorial_first_run_done = False
    row.tutorial_second_run_done = False
    row.tutorial_run_summary_read = False
    row.tutorial_results_inspected = False
    row.tutorial_explain_used = False
    row.tutorial_candidate_marked = False
    row.tutorial_third_run_done = False
    row.tutorial_completed = False
    helpers.settle_processing_state(row, cancel_revision=True)
    row.config_status = "idle"
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
    is_run_ack = intent.is_run_acknowledgement_message(body.content)
    user_visible = not is_run_ack
    um = derivation.append_message(db, session_id, "user", body.content, user_visible)
    if user_visible:
        out.append(MessageOut.model_validate(um))
    updated_panel: dict | None = None
    updated_problem_brief: dict | None = None
    proc_state: SessionProcessingState | None = None
    uploaded_file_names = _parse_simulated_upload_file_names(body.content)
    if uploaded_file_names:
        row.tutorial_uploaded_files = True
        current_problem_brief = helpers.problem_brief_dict(row)
        next_problem_brief = resolve_upload_open_questions_after_upload(current_problem_brief, uploaded_file_names)
        if next_problem_brief != current_problem_brief:
            row.problem_brief_json = json.dumps(next_problem_brief)
            updated_problem_brief = next_problem_brief
        helpers.touch_session(row)
        db.commit()
        db.refresh(row)

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
            # Mark processing pending BEFORE the (potentially multi-second) model call so any
            # client polling during the call window sees the in-flight state and shows a
            # response-spinner bubble. Without this, researcher-driven posts (e.g. simulated
            # uploads via /researcher/simulate-participant-upload) and any other path where
            # the participant frontend has no local aiPending hook would have no indication
            # that an AI reply is being prepared until the assistant message itself arrives.
            # The patch / else / interpret-only branches below still set the final state
            # (settle to "ready" or keep "pending" if background derivation was launched).
            helpers.mark_processing_pending(row)
            db.commit()
            db.refresh(row)
            hist, researcher_steers, recent_runs_summary = context.load_turn_context(db, session_id, um.id)
            text = "The model request failed. Try again or continue without AI."
            current = helpers.panel_dict(row)
            current_problem_brief = helpers.problem_brief_dict(row)
            updated_panel = current
            is_answer_save = intent.is_answered_open_question_message(body.content)
            is_config_save = intent.is_config_save_context_message(body.content)
            # Set when the participant message is the synthetic "I'm uploading the
            # following file(s): …" line. The brief already grew a canonical
            # `item-gathered-upload` row in the upload-OQ block above; signaling
            # this to the LLM keeps it from emitting a parallel upload-tracking
            # gathered row that would visually duplicate the marker.
            is_upload_context = bool(uploaded_file_names)
            # Demo mode reuses tutorial guardrails to keep agent output narrow
            # for screen recordings, even though no bubbles are shown to the
            # participant. See plans note: "demo mode = guardrails on, bubbles
            # off".
            is_demo_mode = str(row.workflow_mode or "").strip().lower() == "demo"
            is_tutorial_active = bool(
                is_demo_mode
                or (
                    getattr(row, "participant_tutorial_enabled", False)
                    and not getattr(row, "tutorial_completed", False)
                )
            )
            turn = None
            try:
                from app.services.llm import classify_definition_intents, generate_chat_turn

                cleanup_requested, clear_requested = classify_definition_intents(body.content, key, model)

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
                    is_tutorial_active=is_tutorial_active,
                    test_problem_id=row.test_problem_id,
                )
                text = turn.assistant_message
            except Exception:
                log.exception("Participant model turn failed for session %s", session_id)
            text = intent.sanitize_visible_assistant_reply(text)
            am = derivation.append_message(db, session_id, "assistant", text, True)
            out.append(MessageOut.model_validate(am))
            run_intent = None
            assistant_invites_run_now = False
            # Auto-posted run-complete messages must never be classified as "run now" intent.
            if not is_run_ack:
                try:
                    from app.services.llm import (
                        classify_assistant_run_invitation,
                        classify_run_trigger_intent,
                    )

                    run_intent = classify_run_trigger_intent(
                        user_text=body.content,
                        history_lines=hist,
                        api_key=key,
                        model_name=model,
                        workflow_mode=row.workflow_mode,
                    )
                    if run_intent.intent_type == "affirm_invite":
                        assistant_invites_run_now = classify_assistant_run_invitation(
                            assistant_text=text,
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
                        if is_run_ack:
                            patch_payload = derivation.sanitize_run_ack_patch_payload(
                                patch_payload, workflow_mode=row.workflow_mode
                            )
                        if cleanup_requested or turn.cleanup_mode or turn.replace_editable_items:
                            patch_payload["replace_editable_items"] = True
                        if clear_requested:
                            patch_payload["replace_open_questions"] = True
                        elif turn.replace_open_questions:
                            patch_payload["replace_open_questions"] = True
                        merged_brief, cleanup_meta = derivation.apply_brief_patch_with_cleanup(
                            base_problem_brief=current_problem_brief,
                            patch_payload=patch_payload,
                            history_lines=hist,
                            api_key=key,
                            model_name=model,
                            workflow_mode=row.workflow_mode,
                            current_panel=current,
                            recent_runs_summary=recent_runs_summary,
                            researcher_steers=researcher_steers,
                            test_problem_id=row.test_problem_id,
                            enable_auto_open_question_cleanup=True,
                            is_run_acknowledgement=is_run_ack,
                            cleanup_mode=cleanup_requested or bool(turn.cleanup_mode),
                        )
                        merged_brief = coerce_problem_brief_for_workflow(merged_brief, row.workflow_mode)
                        if int(cleanup_meta.get("removed_total", 0)) > 0:
                            log.info(
                                "Auto open-question cleanup removed %s question(s) for session %s",
                                cleanup_meta.get("removed_total"),
                                session_id,
                            )
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
                except sync.GoalTermValidationError as exc:
                    log.exception("Inline brief/config sync goal-term validation failed for session %s", session_id)
                    row = db.get(StudySession, session_id) or row
                    helpers.fail_processing_state(row, exc.processing_error_text(), cancel_revision=True)
                    db.commit()
                    db.refresh(row)
                    proc_state = helpers.processing_state(row)
                    msg = derivation.append_message(
                        db,
                        session_id,
                        "assistant",
                        "I could not sync configuration because goal terms are inconsistent with the definition. "
                        "Please review Definition items and retry sync.",
                        True,
                        kind="panel",
                    )
                    out.append(MessageOut.model_validate(msg))
                except Exception:
                    log.exception("Inline brief/config sync failed for session %s", session_id)
                    row = db.get(StudySession, session_id) or row
                    helpers.fail_processing_state(row, "Inline problem-config sync failed", cancel_revision=True)
                    db.commit()
                    db.refresh(row)
                    proc_state = helpers.processing_state(row)
            elif body.skip_hidden_brief_update or intent.is_interpret_only_context_message(body.content):
                row = db.get(StudySession, session_id) or row
                helpers.settle_processing_state(row, cancel_revision=True)
                helpers.touch_session(row)
                db.commit()
                db.refresh(row)
                proc_state = helpers.processing_state(row)
            else:
                # Processing was already marked pending before the model call (see early
                # mark above); reuse that same revision for the background derivation so we
                # don't double-increment processing_revision per turn.
                row = db.get(StudySession, session_id) or row
                revision = int(row.processing_revision or 0)
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
                    is_config_save=is_config_save,
                    is_upload_context=is_upload_context,
                    is_tutorial_active=is_tutorial_active,
                    test_problem_id=row.test_problem_id,
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
                has_uploaded_data=_session_has_uploaded_data(db, session_id),
                optimization_gate_engaged=bool(getattr(row, "optimization_gate_engaged", False)),
                problem_id=str(getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID),
            )
            if (
                run_intent is not None
                and run_intent.should_trigger_run
                and run_intent.intent_type in {"affirm_invite", "direct_request"}
                and not assistant_invites_run_now
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
                            pending = derivation.append_message(
                                db,
                                session_id,
                                "assistant",
                                "Optimization run requested. Starting now...",
                                True,
                                kind="run_pending",
                            )
                            out.append(MessageOut.model_validate(pending))
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
                    blocked_msg = _run_gate_blocked_message(
                        row,
                        brief_obj,
                        _session_has_uploaded_data(db, session_id),
                    )
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
    from app.problems.exceptions import RunCancelled
    from app.problems.registry import get_study_port
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

    run_type = str(body.type).lower()
    if run_type == "optimize":
        if not can_run_optimization(
            row.workflow_mode,
            row.optimization_allowed,
            row.optimization_runs_blocked_by_researcher,
            panel_obj,
            brief_obj,
            has_uploaded_data=_session_has_uploaded_data(db, session_id),
            optimization_gate_engaged=bool(getattr(row, "optimization_gate_engaged", False)),
            problem_id=str(getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID),
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Optimization is not allowed (researcher block, or intrinsic readiness not met and no permit)",
            )

    payload = {
        "type": body.type,
        "problem": body.problem,
        "routes": body.routes,
        "candidate_seed_run_ids": body.candidate_seed_run_ids,
        "candidate_seeds": body.candidate_seeds,
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

    cancel_ev = register_cancel_event(session_id) if run_type == "optimize" else None
    try:
        timeout = get_settings().solve_timeout_sec
        port = get_study_port(row.test_problem_id)
        result = port.solve_request_to_result(payload, timeout, cancel_event=cancel_ev)
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
        log.exception("Optimization import error for session %s", session_id)
        run_row.error_message = f"Solver import error: {e}"
    except Exception:
        log.exception("Optimization run failed for session %s", session_id)
        run_row.error_message = "Optimization failed"
    finally:
        if cancel_ev is not None:
            clear_cancel_event(session_id)

    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run_row)

    result_dict: dict[str, Any] | None = None
    if run_row.result_json:
        try:
            parsed = json.loads(run_row.result_json)
            result_dict = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            result_dict = None
    summary_port = get_study_port(row.test_problem_id)
    summary = summary_port.format_optimization_run_chat_summary(
        session_run_number=session_run_number,
        run_ok=bool(run_row.ok),
        cost=float(run_row.cost) if run_row.cost is not None else None,
        result=result_dict,
        error_message=run_row.error_message,
    )
    derivation.append_message(db, session_id, "assistant", summary, True, kind="run")
    return helpers.run_to_out(run_row)


def _normalize_routes_for_compare(raw: Any) -> list[list[int]] | None:
    if not isinstance(raw, list):
        return None
    if all(isinstance(row, dict) and isinstance(row.get("task_indices"), list) for row in raw):
        out_obj: list[list[int]] = []
        for row in raw:
            task_indices = row.get("task_indices")
            if not isinstance(task_indices, list):
                return None
            vals_obj: list[int] = []
            for value in task_indices:
                try:
                    vals_obj.append(int(value))
                except (TypeError, ValueError):
                    return None
            out_obj.append(vals_obj)
        return out_obj
    out: list[list[int]] = []
    for row in raw:
        if not isinstance(row, list):
            return None
        vals: list[int] = []
        for value in row:
            try:
                vals.append(int(value))
            except (TypeError, ValueError):
                return None
        out.append(vals)
    return out


def _routes_equal(a: Any, b: Any) -> bool:
    na = _normalize_routes_for_compare(a)
    nb = _normalize_routes_for_compare(b)
    return na is not None and nb is not None and na == nb


@router.post("/{session_id}/runs/{run_id}/evaluate-edit", response_model=RunOut)
def post_evaluate_edit_run(
    session_id: str,
    run_id: int,
    body: RunEvaluateEditBody,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    from app.problems.registry import get_study_port

    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    run_row = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.session_id == session_id, OptimizationRun.id == run_id)
        .first()
    )
    if run_row is None:
        raise HTTPException(status_code=404, detail="Run not found")

    payload = {"type": "evaluate", "problem": body.problem, "routes": body.routes}
    timeout = get_settings().solve_timeout_sec
    port = get_study_port(row.test_problem_id)

    try:
        result = port.solve_request_to_result(payload, timeout, cancel_event=None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        log.exception("Run edit-evaluate failed for session %s run %s", session_id, run_id)
        raise HTTPException(status_code=500, detail="Evaluate failed") from None

    req_old: dict[str, Any] | None = None
    if run_row.request_json:
        try:
            parsed = json.loads(run_row.request_json)
            req_old = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            req_old = None
    res_old: dict[str, Any] | None = None
    if run_row.result_json:
        try:
            parsed = json.loads(run_row.result_json)
            res_old = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            res_old = None

    original_snapshot = (
        res_old.get("original_snapshot")
        if isinstance(res_old, dict) and isinstance(res_old.get("original_snapshot"), dict)
        else {
            "request": req_old,
            "result": res_old,
            "cost": run_row.cost,
            "reference_cost": run_row.reference_cost,
            "ok": bool(run_row.ok),
            "error_message": run_row.error_message,
        }
    )

    original_result = original_snapshot.get("result") if isinstance(original_snapshot, dict) else None
    original_schedule = original_result.get("schedule") if isinstance(original_result, dict) else None
    original_routes = original_schedule.get("routes") if isinstance(original_schedule, dict) else None

    if _routes_equal(body.routes, original_routes):
        if not isinstance(original_result, dict):
            raise HTTPException(status_code=500, detail="Original run snapshot missing; cannot restore")
        restored_result = dict(original_result)
        restored_result.pop("edited_evaluation", None)
        restored_result.pop("original_snapshot", None)
        run_row.ok = bool(original_snapshot.get("ok", True))
        run_row.cost = (
            float(original_snapshot["cost"])
            if original_snapshot.get("cost") is not None
            else None
        )
        run_row.reference_cost = (
            float(original_snapshot["reference_cost"])
            if original_snapshot.get("reference_cost") is not None
            else None
        )
        run_row.result_json = json.dumps(restored_result)
        run_row.error_message = (
            str(original_snapshot.get("error_message"))
            if original_snapshot.get("error_message") is not None
            else None
        )
    else:
        result_out: dict[str, Any] = dict(result)
        result_out["original_snapshot"] = original_snapshot
        result_out["edited_evaluation"] = {
            "edited_at": serialize_utc_datetime(datetime.now(timezone.utc)),
            "request": payload,
            "cost": float(result["cost"]),
            "reference_cost": float(result["reference_cost"]) if result.get("reference_cost") is not None else None,
        }

        run_row.ok = True
        run_row.cost = float(result["cost"])
        run_row.reference_cost = float(result["reference_cost"]) if result.get("reference_cost") is not None else None
        run_row.result_json = json.dumps(result_out)
        run_row.error_message = None
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run_row)
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

    from app.problems.registry import get_study_port

    port = get_study_port(row.test_problem_id)

    # Only validate goal_terms when the participant actually changed them.
    # A pre-existing mismatch (e.g. a stale LLM-hallucinated key) shouldn't
    # block a save that only edits unrelated fields like algorithm or epochs;
    # the Recover banner is the path to clean that up.
    submitted_problem = (
        body.panel_config.get("problem")
        if isinstance(body.panel_config.get("problem"), dict)
        else body.panel_config
    )
    submitted_goal_terms = (
        submitted_problem.get("goal_terms") if isinstance(submitted_problem, dict) else None
    )
    current_panel = helpers.panel_dict(row)
    current_problem = (
        current_panel.get("problem")
        if isinstance(current_panel, dict) and isinstance(current_panel.get("problem"), dict)
        else current_panel
    )
    current_goal_terms = (
        current_problem.get("goal_terms") if isinstance(current_problem, dict) else None
    )
    goal_terms_changed = submitted_goal_terms != current_goal_terms

    if goal_terms_changed:
        try:
            # Reverse validation: on a participant-driven panel save the user
            # is authoritative. Skip the brief-grounding check; only enforce
            # shape / type / order. The hidden brief update on this same turn
            # refreshes brief rows to reflect the participant's edit.
            sync.validate_problem_goal_terms(
                problem=submitted_problem,
                problem_brief=helpers.problem_brief_dict(row),
                weight_slot_markers=port.weight_slot_markers(),
                check_grounding=False,
            )
        except sync.GoalTermValidationError as exc:
            # Set processing_error so the Recover banner appears on the next
            # session refresh; still 422 because the submitted goal_terms are
            # rejected and not persisted.
            helpers.fail_processing_state(row, exc.processing_error_text(), cancel_revision=True)
            db.commit()
            db.refresh(row)
            raise HTTPException(status_code=422, detail=exc.detail_text()) from exc
    sanitized_config, weight_warnings = port.sanitize_panel_config(body.panel_config)

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

    from app.crypto_util import decrypt_secret

    # Capture persisted open questions BEFORE we coerce the incoming brief so we can
    # diff and route just-answered OQs through the LLM classifier.
    persisted_brief_raw: dict[str, Any]
    try:
        persisted_brief_raw = json.loads(row.problem_brief_json) if row.problem_brief_json else {}
    except json.JSONDecodeError:
        persisted_brief_raw = {}
    persisted_open_questions = persisted_brief_raw.get("open_questions") or []
    if not isinstance(persisted_open_questions, list):
        persisted_open_questions = []

    incoming_brief = body.problem_brief.model_dump()
    incoming_brief = _route_oq_answers_through_classifier(
        incoming_brief=incoming_brief,
        persisted_open_questions=[q for q in persisted_open_questions if isinstance(q, dict)],
        workflow_mode=row.workflow_mode or "waterfall",
        api_key=decrypt_secret(row.gemini_key_encrypted),
        model_name=row.gemini_model or get_settings().default_gemini_model,
        test_problem_id=row.test_problem_id,
    )

    next_problem_brief = coerce_problem_brief_for_workflow(
        incoming_brief,
        row.workflow_mode,
    )
    row.problem_brief_json = json.dumps(next_problem_brief)
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    panel_sync_failed = False
    try:
        sync.sync_panel_from_problem_brief(
            row,
            db,
            next_problem_brief,
            api_key=decrypt_secret(row.gemini_key_encrypted),
            model_name=row.gemini_model or get_settings().default_gemini_model,
            workflow_mode=row.workflow_mode,
            preserve_missing_managed_fields=True,
        )
    except sync.GoalTermValidationError as exc:
        # The brief itself was already committed above. Don't fail the request
        # just because the panel re-derivation can't validate — that turns a
        # successful save into a confusing 422. Instead, surface the issue via
        # `processing_error` so the Recover banner appears and the participant
        # can clear the conflicting state in one click.
        panel_sync_failed = True
        helpers.fail_processing_state(row, exc.processing_error_text(), cancel_revision=True)
        db.commit()
        db.refresh(row)
        derivation.append_message(
            db,
            session_id,
            "assistant",
            "Saved your Definition, but I couldn't re-derive Problem Config — the goal-term keys are "
            "out of sync. Use the **Recover** button in the banner above the tabs to clear the "
            "conflicting goal terms and re-derive a clean Problem Config.",
            True,
            kind="panel",
        )
    if not panel_sync_failed:
        helpers.settle_processing_state(row)
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)

    if helpers.sync_optimization_allowed_after_participant_mutation(row):
        db.commit()
        db.refresh(row)

    create_snapshot(db, session_id, EVENT_MANUAL_SAVE)

    if body.acknowledgement and not panel_sync_failed:
        derivation.append_message(db, session_id, "assistant", body.acknowledgement, True, kind="panel")
    return helpers.session_to_out(row)


@router.post("/{session_id}/cleanup-open-questions", response_model=SessionOut)
def cleanup_participant_open_questions(
    session_id: str,
    body: CleanupOpenQuestionsBody,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    current_problem_brief = helpers.problem_brief_dict(row)
    current_panel = helpers.panel_dict(row)
    history = [
        (str(m.role or "user"), str(m.content or ""))
        for m in db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id, ChatMessage.visible_to_participant.is_(True))
        .order_by(ChatMessage.id.asc())
        .all()
    ]
    researcher_steers = [
        str(m.content or "")
        for m in db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "researcher",
            ChatMessage.visible_to_participant.is_(False),
            ChatMessage.kind == "steer",
        )
        .order_by(ChatMessage.id.asc())
        .all()
        if str(m.content or "").strip()
    ]
    recent_runs_summary: list[dict[str, Any]] = []
    from app.crypto_util import decrypt_secret

    api_key = decrypt_secret(row.gemini_key_encrypted)
    model = row.gemini_model or get_settings().default_gemini_model
    cleaned_brief, meta = derivation.apply_open_question_cleanup_pass(
        problem_brief=current_problem_brief,
        history_lines=history,
        user_text=derivation.OPEN_QUESTION_CLEANUP_MESSAGE,
        api_key=api_key,
        model_name=model,
        workflow_mode=row.workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
        researcher_steers=researcher_steers,
        test_problem_id=row.test_problem_id,
        infer_resolved=bool(body.infer_resolved),
    )
    cleaned_brief, run_meta = derivation.consolidate_run_summary(
        cleaned_brief,
        recent_runs_summary=recent_runs_summary,
        cleanup_mode=True,
        is_run_acknowledgement=False,
    )
    cleaned_brief = coerce_problem_brief_for_workflow(cleaned_brief, row.workflow_mode)
    if cleaned_brief != current_problem_brief:
        row.problem_brief_json = json.dumps(cleaned_brief)
        helpers.touch_session(row)
        db.commit()
        db.refresh(row)
    log.info("Manual open-question cleanup metadata for session %s: %s", session_id, {**meta, **run_meta})
    return helpers.session_to_out(row)


@router.patch("/{session_id}/participant-tutorial", response_model=SessionOut)
def patch_participant_tutorial(
    session_id: str,
    body: ParticipantTutorialUpdate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")
    if "participant_tutorial_enabled" in body.model_fields_set:
        row.participant_tutorial_enabled = bool(body.participant_tutorial_enabled)
    if "tutorial_step_override" in body.model_fields_set:
        row.tutorial_step_override = body.tutorial_step_override
    if "tutorial_chat_started" in body.model_fields_set and body.tutorial_chat_started is not None:
        row.tutorial_chat_started = bool(body.tutorial_chat_started)
    if "tutorial_uploaded_files" in body.model_fields_set and body.tutorial_uploaded_files is not None:
        row.tutorial_uploaded_files = bool(body.tutorial_uploaded_files)
    if "tutorial_definition_tab_visited" in body.model_fields_set and body.tutorial_definition_tab_visited is not None:
        row.tutorial_definition_tab_visited = bool(body.tutorial_definition_tab_visited)
    if "tutorial_definition_saved" in body.model_fields_set and body.tutorial_definition_saved is not None:
        row.tutorial_definition_saved = bool(body.tutorial_definition_saved)
    if "tutorial_config_tab_visited" in body.model_fields_set and body.tutorial_config_tab_visited is not None:
        row.tutorial_config_tab_visited = bool(body.tutorial_config_tab_visited)
    if "tutorial_config_first_saved" in body.model_fields_set and body.tutorial_config_first_saved is not None:
        row.tutorial_config_first_saved = bool(body.tutorial_config_first_saved)
    if "tutorial_config_saved" in body.model_fields_set and body.tutorial_config_saved is not None:
        row.tutorial_config_saved = bool(body.tutorial_config_saved)
    if "tutorial_first_run_done" in body.model_fields_set and body.tutorial_first_run_done is not None:
        row.tutorial_first_run_done = bool(body.tutorial_first_run_done)
    if "tutorial_second_run_done" in body.model_fields_set and body.tutorial_second_run_done is not None:
        row.tutorial_second_run_done = bool(body.tutorial_second_run_done)
    if "tutorial_run_summary_read" in body.model_fields_set and body.tutorial_run_summary_read is not None:
        row.tutorial_run_summary_read = bool(body.tutorial_run_summary_read)
    if "tutorial_results_inspected" in body.model_fields_set and body.tutorial_results_inspected is not None:
        row.tutorial_results_inspected = bool(body.tutorial_results_inspected)
    if "tutorial_explain_used" in body.model_fields_set and body.tutorial_explain_used is not None:
        row.tutorial_explain_used = bool(body.tutorial_explain_used)
    if "tutorial_candidate_marked" in body.model_fields_set and body.tutorial_candidate_marked is not None:
        row.tutorial_candidate_marked = bool(body.tutorial_candidate_marked)
    if "tutorial_third_run_done" in body.model_fields_set and body.tutorial_third_run_done is not None:
        row.tutorial_third_run_done = bool(body.tutorial_third_run_done)
    if "tutorial_completed" in body.model_fields_set and body.tutorial_completed is not None:
        row.tutorial_completed = bool(body.tutorial_completed)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
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
    sync_failed = False
    try:
        updated_panel, _ = sync.sync_panel_from_problem_brief(
            row,
            db,
            problem_brief,
            api_key=decrypt_secret(row.gemini_key_encrypted),
            model_name=row.gemini_model or get_settings().default_gemini_model,
            workflow_mode=row.workflow_mode,
            preserve_missing_managed_fields=True,
        )
    except sync.GoalTermValidationError as exc:
        # Surface via processing_error → Recover banner instead of failing the
        # request. The participant explicitly clicked Sync; a hard 422 just
        # leaves them stuck without a clear next step. The banner + Recover
        # button is the next step.
        sync_failed = True
        updated_panel = None
        helpers.fail_processing_state(row, exc.processing_error_text(), cancel_revision=True)
        db.commit()
        db.refresh(row)
        derivation.append_message(
            db,
            session_id,
            "assistant",
            "I couldn't sync Problem Config from the Definition — the goal-term keys don't match. "
            "Use the **Recover** button in the banner above the tabs to clear the conflict.",
            True,
            kind="panel",
        )
    if updated_panel is None and not sync_failed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Problem definition is not specific enough to sync a solver configuration yet",
        )
    if not sync_failed:
        helpers.settle_processing_state(row)
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
    if helpers.sync_optimization_allowed_after_participant_mutation(row):
        db.commit()
        db.refresh(row)
    return helpers.session_to_out(row)


@router.post("/{session_id}/recover-goal-terms", response_model=SessionOut)
def post_recover_goal_terms(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    """Break a goal-term validation deadlock.

    When `validate_problem_goal_terms` rejects an LLM-derived panel because
    its `goal_terms` keys don't match what the brief grounds, subsequent saves
    keep failing for the same reason and the participant is stuck. This route:

      1. Clears `panel.problem.{goal_terms, weights, constraint_types, locked_goal_terms}`
         so the next sync starts from an empty term set.
      2. Resets the session processing state (clears `processing_error`).
      3. Re-derives the panel from the existing brief using the deterministic
         seed only (no LLM), guaranteeing keys grounded in brief items.

    Brief content is preserved — the user's stated goals are not lost.
    """
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    panel = helpers.panel_dict(row)
    if isinstance(panel, dict) and isinstance(panel.get("problem"), dict):
        problem = panel["problem"]
        for key in ("goal_terms", "weights", "constraint_types", "locked_goal_terms"):
            problem.pop(key, None)
        row.panel_config_json = json.dumps(panel)

    helpers.settle_processing_state(row, cancel_revision=True)
    helpers.touch_session(row)
    db.commit()
    db.refresh(row)

    problem_brief = helpers.problem_brief_dict(row)
    try:
        sync.sync_panel_from_problem_brief(
            row,
            db,
            problem_brief,
            api_key=None,
            model_name=None,
            workflow_mode=row.workflow_mode,
            preserve_missing_managed_fields=False,
        )
    except sync.GoalTermValidationError:
        # Even the deterministic seed couldn't produce a clean panel for this
        # brief. Leave the panel cleared and the error reset; the participant
        # can edit Definition or chat to articulate goals again.
        row = db.get(StudySession, session_id) or row
        helpers.settle_processing_state(row, cancel_revision=True)
        helpers.touch_session(row)
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


def _parse_json_field(raw: str | None) -> dict | list | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
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
    snapshots = (
        db.query(SessionSnapshot)
        .filter(SessionSnapshot.session_id == session_id)
        .order_by(SessionSnapshot.id.asc())
        .all()
    )
    exported_at = datetime.now(timezone.utc)
    timeline = build_export_timeline(messages, runs, snapshots, run_number=helpers.run_number)
    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": serialize_utc_datetime(exported_at),
        "timeline": timeline,
        "session": {
            "id": row.id,
            "created_at": serialize_utc_datetime(row.created_at),
            "updated_at": serialize_utc_datetime(row.updated_at),
            "workflow_mode": row.workflow_mode,
            "participant_number": row.participant_number,
            "test_problem_id": str(getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID),
            "status": row.status,
            "panel_config": helpers.panel_dict(row),
            "problem_brief": helpers.problem_brief_dict(row),
            "processing_revision": int(row.processing_revision or 0),
            "brief_status": row.brief_status,
            "config_status": row.config_status,
            "processing_error": row.processing_error,
            "optimization_allowed": row.optimization_allowed,
            "optimization_runs_blocked_by_researcher": row.optimization_runs_blocked_by_researcher,
            "participant_tutorial_enabled": bool(getattr(row, "participant_tutorial_enabled", False)),
            "tutorial_step_override": getattr(row, "tutorial_step_override", None),
            "tutorial_chat_started": bool(getattr(row, "tutorial_chat_started", False)),
            "tutorial_uploaded_files": bool(getattr(row, "tutorial_uploaded_files", False)),
            "tutorial_definition_tab_visited": bool(getattr(row, "tutorial_definition_tab_visited", False)),
            "tutorial_definition_saved": bool(getattr(row, "tutorial_definition_saved", False)),
            "tutorial_config_tab_visited": bool(getattr(row, "tutorial_config_tab_visited", False)),
            "tutorial_config_first_saved": bool(getattr(row, "tutorial_config_first_saved", False)),
            "tutorial_config_saved": bool(getattr(row, "tutorial_config_saved", False)),
            "tutorial_first_run_done": bool(getattr(row, "tutorial_first_run_done", False)),
            "tutorial_second_run_done": bool(getattr(row, "tutorial_second_run_done", False)),
            "tutorial_run_summary_read": bool(getattr(row, "tutorial_run_summary_read", False)),
            "tutorial_results_inspected": bool(getattr(row, "tutorial_results_inspected", False)),
            "tutorial_explain_used": bool(getattr(row, "tutorial_explain_used", False)),
            "tutorial_candidate_marked": bool(getattr(row, "tutorial_candidate_marked", False)),
            "tutorial_third_run_done": bool(getattr(row, "tutorial_third_run_done", False)),
            "tutorial_completed": bool(getattr(row, "tutorial_completed", False)),
            "optimization_gate_engaged": bool(getattr(row, "optimization_gate_engaged", False)),
            "gemini_model": row.gemini_model,
            "gemini_key_configured": bool(row.gemini_key_encrypted),
            "content_reset_revision": int(getattr(row, "content_reset_revision", 0) or 0),
        },
        "messages": [
            {
                "id": m.id,
                "created_at": serialize_utc_datetime(m.created_at),
                "role": m.role,
                "content": m.content,
                "visible_to_participant": m.visible_to_participant,
                "kind": m.kind,
                "meta": _parse_json_field(m.meta_json),
            }
            for m in messages
        ],
        "runs": [
            {
                "id": r.id,
                "session_run_index": r.session_run_index,
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
        "snapshots": [
            {
                "id": s.id,
                "created_at": serialize_utc_datetime(s.created_at),
                "event_type": s.event_type,
                "problem_brief": _parse_json_field(s.problem_brief_json),
                "panel_config": _parse_json_field(s.panel_config_json),
            }
            for s in snapshots
        ],
    }
