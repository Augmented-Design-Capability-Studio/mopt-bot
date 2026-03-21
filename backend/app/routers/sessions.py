from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import Principal, require_any_study_user, require_client, require_researcher
from app.config import get_settings
from app.crypto_util import decrypt_secret, encrypt_secret
from app.database import get_db
from app.default_config import MEDIOCRE_PARTICIPANT_STARTER_CONFIG
from app.models import ChatMessage, OptimizationRun, StudySession
from app.schemas import (
    MessageCreate,
    MessageOut,
    ModelSettingsBody,
    ParticipantPanelUpdate,
    PostMessagesResponse,
    RunOut,
    SessionCreate,
    SessionOut,
    SessionPatch,
    SolveRunCreate,
    SteerCreate,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _panel_dict(row: StudySession | None) -> dict | None:
    if row is None or not row.panel_config_json:
        return None
    try:
        return json.loads(row.panel_config_json)
    except json.JSONDecodeError:
        return None


def _session_to_out(row: StudySession) -> SessionOut:
    return SessionOut(
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        workflow_mode=row.workflow_mode,
        status=row.status,
        panel_config=_panel_dict(row),
        optimization_allowed=row.optimization_allowed,
        gemini_model=row.gemini_model,
        gemini_key_configured=bool(row.gemini_key_encrypted),
    )


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
        status="active",
        panel_config_json=None,
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
    if body.panel_config is not None:
        row.panel_config_json = json.dumps(body.panel_config)
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
                .order_by(ChatMessage.id.asc())
                .all()
            )
            for p in prev:
                if p.role in ("user", "assistant"):
                    hist.append((p.role, p.content))
            text = "The model request failed. Try again or continue without AI."
            try:
                from app.services.llm import generate_chat_turn
                from app.services.panel_merge import deep_merge

                current = _panel_dict(row)
                turn = generate_chat_turn(body.content, hist, key, model, current)
                text = turn.assistant_message
                if turn.panel_patch:
                    # Merge into an empty base until the participant has real panel data; do not seed
                    # DEFAULT_PANEL_CONFIG (that would contradict "empty until researcher pushes").
                    base = deepcopy(current) if current is not None else {}
                    merged = deep_merge(base, turn.panel_patch)
                    row.panel_config_json = json.dumps(merged)
                    row.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    db.refresh(row)
                    updated_panel = merged
            except Exception:
                pass
            am = _append_message(db, session_id, "assistant", text, True)
            out.append(MessageOut.model_validate(am))

    return PostMessagesResponse(messages=out, panel_config=updated_panel)


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
    run_row = OptimizationRun(
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

    summary = (
        f"Run #{run_row.id} finished: cost {run_row.cost:.4f}"
        if run_row.ok and run_row.cost is not None
        else f"Run #{run_row.id} failed: {run_row.error_message or 'error'}"
    )
    _append_message(db, session_id, "assistant", summary, True, kind="run")

    res = None
    if run_row.result_json:
        try:
            res = json.loads(run_row.result_json)
        except json.JSONDecodeError:
            res = None

    return RunOut(
        id=run_row.id,
        created_at=run_row.created_at,
        run_type=run_row.run_type,
        ok=run_row.ok,
        cost=run_row.cost,
        reference_cost=run_row.reference_cost,
        error_message=run_row.error_message,
        result=res,
    )


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
    out = []
    for r in rows:
        res = None
        if r.result_json:
            try:
                res = json.loads(r.result_json)
            except json.JSONDecodeError:
                res = None
        out.append(
            RunOut(
                id=r.id,
                created_at=r.created_at,
                run_type=r.run_type,
                ok=r.ok,
                cost=r.cost,
                reference_cost=r.reference_cost,
                error_message=r.error_message,
                result=res,
            )
        )
    return out


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
    row.panel_config_json = json.dumps(body.panel_config)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    if body.acknowledgement:
        _append_message(db, session_id, "assistant", body.acknowledgement, True, kind="panel")
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
            "status": row.status,
            "panel_config": _panel_dict(row),
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
