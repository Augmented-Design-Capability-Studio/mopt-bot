"""Background derivation and message append logic."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from threading import Thread
from typing import Any

from app.config import get_settings
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ChatMessage, StudySession
from app.problem_brief import (
    cleanup_open_questions,
    merge_problem_brief_patch,
    normalize_problem_brief,
    sync_problem_brief_from_panel,
)

from . import helpers, sync

log = logging.getLogger(__name__)
OPEN_QUESTION_CLEANUP_MESSAGE = (
    "Clean up open questions only: remove resolved or duplicate questions, keep still-ambiguous ones open."
)


def apply_open_question_cleanup_pass(
    *,
    problem_brief: dict[str, Any],
    history_lines: list[tuple[str, str]],
    user_text: str,
    api_key: str,
    model_name: str,
    workflow_mode: str,
    current_panel: dict[str, Any] | None,
    recent_runs_summary: list[dict[str, Any]],
    researcher_steers: list[str],
    test_problem_id: str | None,
    infer_resolved: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    LLM-first open-question cleanup with conservative deterministic fallback.
    """
    base = normalize_problem_brief(problem_brief)
    llm_used = False
    llm_pruned = False
    if infer_resolved and api_key.strip():
        try:
            from app.services.llm import generate_problem_brief_update

            turn = generate_problem_brief_update(
                user_text=user_text,
                history_lines=history_lines,
                api_key=api_key,
                model_name=model_name,
                current_problem_brief=base,
                workflow_mode=workflow_mode,
                current_panel=current_panel,
                recent_runs_summary=recent_runs_summary or None,
                researcher_steers=researcher_steers or None,
                cleanup_mode=True,
                test_problem_id=test_problem_id,
            )
            llm_used = True
            patch = turn.problem_brief_patch if isinstance(turn.problem_brief_patch, dict) else None
            if patch is not None and "open_questions" in patch:
                candidate = merge_problem_brief_patch(
                    base,
                    {"open_questions": patch.get("open_questions"), "replace_open_questions": True},
                )
                if len(candidate.get("open_questions") or []) <= len(base.get("open_questions") or []):
                    base = candidate
                    llm_pruned = True
        except Exception:
            log.exception("Open-question cleanup model pass failed")
    cleaned, cleanup_meta = cleanup_open_questions(
        base, infer_resolved=(infer_resolved and not llm_pruned)
    )
    return cleaned, {
        "llm_used": llm_used,
        "llm_pruned": llm_pruned,
        **cleanup_meta,
    }


def apply_brief_patch_with_cleanup(
    *,
    base_problem_brief: dict[str, Any],
    patch_payload: dict[str, Any],
    history_lines: list[tuple[str, str]],
    api_key: str,
    model_name: str,
    workflow_mode: str,
    current_panel: dict[str, Any] | None,
    recent_runs_summary: list[dict[str, Any]],
    researcher_steers: list[str],
    test_problem_id: str | None,
    enable_auto_open_question_cleanup: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Shared patch-merge pipeline used by definition cleanup and OQ cleanup-triggered flows.
    """
    merged = merge_problem_brief_patch(base_problem_brief, patch_payload)
    if not enable_auto_open_question_cleanup or merged == base_problem_brief:
        return merged, {"removed_total": 0}
    cleaned, meta = apply_open_question_cleanup_pass(
        problem_brief=merged,
        history_lines=history_lines,
        user_text=OPEN_QUESTION_CLEANUP_MESSAGE,
        api_key=api_key,
        model_name=model_name,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
        researcher_steers=researcher_steers,
        test_problem_id=test_problem_id,
        infer_resolved=True,
    )
    return cleaned, meta


def _run_with_timeout(callable_obj, timeout_sec: float):
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(callable_obj)
        return future.result(timeout=timeout_sec)


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
        if role == "user" and visible:
            s.optimization_gate_engaged = True
    db.commit()
    db.refresh(m)
    return m


def persist_processing_failure(session_id: str, revision: int, detail: str) -> None:
    with SessionLocal() as db:
        row = db.get(StudySession, session_id)
        if row is None or row.processing_revision != revision:
            return
        helpers.fail_processing_state(row, detail)
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
    test_problem_id: str | None = None,
) -> None:
    try:
        from app.services.llm import generate_problem_brief_update
        timeout_sec = get_settings().derivation_timeout_sec
        try:
            brief_turn = _run_with_timeout(
                lambda: generate_problem_brief_update(
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
                    test_problem_id=test_problem_id,
                ),
                timeout_sec,
            )
        except FuturesTimeoutError as exc:
            raise TimeoutError("Brief derivation timed out") from exc
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
            effective_problem_brief, meta = apply_brief_patch_with_cleanup(
                base_problem_brief=base_problem_brief,
                patch_payload=patch_payload,
                history_lines=history_lines,
                api_key=api_key,
                model_name=model_name,
                workflow_mode=workflow_mode,
                current_panel=base_panel,
                recent_runs_summary=recent_runs_summary,
                researcher_steers=researcher_steers,
                test_problem_id=test_problem_id,
                enable_auto_open_question_cleanup=True,
            )
            if int(meta.get("removed_total", 0)) > 0:
                log.info("Auto open-question cleanup removed %s question(s)", meta.get("removed_total"))
            if (cleanup_requested or brief_turn.cleanup_mode) and base_panel:
                effective_problem_brief = sync_problem_brief_from_panel(
                    effective_problem_brief, base_panel, test_problem_id=test_problem_id
                )

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
            helpers.sync_optimization_allowed_after_participant_mutation(row)
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
