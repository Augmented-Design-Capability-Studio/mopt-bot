"""Background derivation and message append logic."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from threading import Thread
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ChatMessage, StudySession
from app.problem_brief import merge_problem_brief_patch, normalize_problem_brief

from . import helpers, sync

log = logging.getLogger(__name__)


def append_message(
    db: Session,
    session_id: str,
    role: str,
    content: str,
    visible: bool,
    kind: str = "chat",
) -> ChatMessage:
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


def persist_processing_failure(session_id: str, revision: int, detail: str) -> None:
    with SessionLocal() as db:
        row = db.get(StudySession, session_id)
        if row is None or row.processing_revision != revision:
            return
        row.brief_status = "failed"
        row.config_status = "failed"
        row.processing_error = detail
        helpers.touch_session(row)
        db.commit()


def _run_background_derivation(
    *,
    session_id: str,
    revision: int,
    user_text: str,
    workflow_mode: str,
    api_key: str,
    model_name: str,
    history_lines: list[tuple[str, str]],
    researcher_steers: list[str],
    recent_runs_summary: list[dict[str, Any]],
    base_problem_brief: dict[str, Any],
    base_panel: dict[str, Any] | None,
    cleanup_requested: bool,
    clear_requested: bool,
    is_run_acknowledgement: bool = False,
    is_answered_open_question: bool = False,
) -> None:
    try:
        from app.services.llm import generate_problem_brief_update

        brief_turn = generate_problem_brief_update(
            user_text=user_text,
            history_lines=history_lines,
            api_key=api_key,
            model_name=model_name,
            current_problem_brief=base_problem_brief,
            workflow_mode=workflow_mode,
            current_panel=base_panel,
            recent_runs_summary=recent_runs_summary or None,
            researcher_steers=researcher_steers or None,
            cleanup_mode=cleanup_requested,
            is_run_acknowledgement=is_run_acknowledgement,
            is_answered_open_question=is_answered_open_question,
        )
        patch_payload: dict[str, Any] | None = None
        if brief_turn.problem_brief_patch:
            patch_payload = dict(brief_turn.problem_brief_patch)
        elif clear_requested:
            patch_payload = {"items": [], "open_questions": []}
        elif cleanup_requested:
            log.warning("Cleanup requested but model returned no brief patch for session %s", session_id)

        effective_problem_brief = base_problem_brief
        if patch_payload is not None:
            if is_run_acknowledgement:
                patch_payload["replace_editable_items"] = False
            elif cleanup_requested or brief_turn.cleanup_mode or brief_turn.replace_editable_items:
                patch_payload["replace_editable_items"] = True
            if clear_requested:
                patch_payload["replace_open_questions"] = True
            elif brief_turn.replace_open_questions:
                patch_payload["replace_open_questions"] = True
            elif "open_questions" in patch_payload and (cleanup_requested or brief_turn.cleanup_mode):
                patch_payload["replace_open_questions"] = True
            effective_problem_brief = merge_problem_brief_patch(base_problem_brief, patch_payload)

        with SessionLocal() as db:
            row = db.get(StudySession, session_id)
            if row is None or row.status != "active" or row.processing_revision != revision:
                return
            if effective_problem_brief != helpers.problem_brief_dict(row):
                row.problem_brief_json = json.dumps(effective_problem_brief)
            row.brief_status = "ready"
            row.config_status = "pending"
            row.processing_error = None
            helpers.touch_session(row)
            db.commit()
            db.refresh(row)

            # If the hidden brief pass made no effective change, skip the config LLM and use
            # heuristic derivation only (same stability as sync when the brief is unchanged).
            brief_unchanged = json.dumps(
                normalize_problem_brief(effective_problem_brief), sort_keys=True, default=str
            ) == json.dumps(normalize_problem_brief(base_problem_brief), sort_keys=True, default=str)
            config_api_key = None if brief_unchanged else api_key

            sync.sync_panel_from_problem_brief(
                row,
                db,
                effective_problem_brief,
                api_key=config_api_key,
                model_name=model_name,
                workflow_mode=workflow_mode,
                recent_runs_summary=recent_runs_summary,
                preserve_missing_managed_fields=True,
            )

            row = db.get(StudySession, session_id)
            if row is None or row.processing_revision != revision:
                return
            row.brief_status = "ready"
            row.config_status = helpers.desired_config_status(row)
            row.processing_error = None
            helpers.touch_session(row)
            db.commit()
    except Exception:
        log.exception("Background derivation failed for session %s", session_id)
        persist_processing_failure(session_id, revision, "Background problem derivation failed")


def launch_background_derivation(**kwargs: Any) -> None:
    thread = Thread(
        target=_run_background_derivation,
        kwargs=kwargs,
        daemon=True,
        name=f"session-derive-{kwargs['session_id']}",
    )
    thread.start()
