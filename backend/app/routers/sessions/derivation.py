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
    problem_brief_item_slot,
    sync_problem_brief_from_panel,
)

from . import helpers, sync

log = logging.getLogger(__name__)
OPEN_QUESTION_CLEANUP_MESSAGE = (
    "Clean up open questions only: remove resolved or duplicate questions, keep still-ambiguous ones open."
)
_RUN_BOOKKEEPING_TEXT_SNIPPETS: tuple[str, ...] = (
    "run #",
    "just completed",
    "finished run",
    "previous run",
    "latest run",
    "this run",
    "after this run",
    "upload file",
    "uploaded file",
)


def _is_run_related_text(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if any(snippet in lowered for snippet in _RUN_BOOKKEEPING_TEXT_SNIPPETS):
        return True
    return False


def _format_run_context_line(run: dict[str, Any]) -> str:
    run_number = run.get("run_number")
    algorithm = str(run.get("algorithm") or "").strip()
    cost = run.get("cost")
    ok = bool(run.get("ok"))
    status = "succeeded" if ok else "failed"
    details: list[str] = [f"Run #{run_number}" if run_number else "Latest run", status]
    if isinstance(cost, (int, float)):
        details.append(f"cost {cost:.2f}")
    if algorithm:
        details.append(f"algorithm {algorithm}")
    violations = run.get("violations")
    if isinstance(violations, dict):
        tw = violations.get("time_window_stop_count")
        cap = violations.get("capacity_units_over")
        if isinstance(tw, (int, float)):
            details.append(f"time-window stops over {int(tw)}")
        if isinstance(cap, (int, float)):
            details.append(f"capacity units over {int(cap)}")
    return ", ".join(details) + "."


def consolidate_run_summary(
    brief: dict[str, Any],
    *,
    recent_runs_summary: list[dict[str, Any]] | None = None,
    cleanup_mode: bool = False,
    is_run_acknowledgement: bool = False,
) -> tuple[dict[str, Any], dict[str, int]]:
    """
    Maintain a single rolling run summary. On cleanup, migrate run-related noisy rows/questions
    into this summary and remove them from their sections.
    """
    normalized = normalize_problem_brief(brief)
    existing = str(normalized.get("run_summary") or "").strip()
    moved_items = 0
    moved_questions = 0
    notes: list[str] = []
    items = list(normalized.get("items") or [])
    questions = list(normalized.get("open_questions") or [])

    if cleanup_mode:
        kept_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip().lower()
            text = str(item.get("text") or "").strip()
            if kind in {"gathered", "assumption"} and _is_run_related_text(text):
                moved_items += 1
                if text:
                    notes.append(text)
                continue
            kept_items.append(item)
        items = kept_items

        kept_questions: list[dict[str, Any]] = []
        for question in questions:
            if not isinstance(question, dict):
                continue
            text = str(question.get("text") or "").strip()
            if _is_run_related_text(text):
                moved_questions += 1
                if text:
                    notes.append(text)
                continue
            kept_questions.append(question)
        questions = kept_questions

    recent_line = ""
    if recent_runs_summary:
        latest = recent_runs_summary[-1]
        if isinstance(latest, dict):
            recent_line = _format_run_context_line(latest).strip()
    parts: list[str] = []
    if existing:
        parts.append(existing)
    if recent_line and (is_run_acknowledgement or cleanup_mode):
        parts.append(recent_line)
    if notes and cleanup_mode:
        unique = list(dict.fromkeys(n for n in notes if n.strip()))
        if unique:
            parts.append(f"Cleanup consolidated run notes: {'; '.join(unique[:2])}.")

    next_summary = " ".join(parts).strip()
    if next_summary:
        next_summary = next_summary[-420:]
        if next_summary[0].islower():
            next_summary = next_summary[0].upper() + next_summary[1:]
        if next_summary[-1] not in ".!?":
            next_summary += "."

    updated = {
        **normalized,
        "items": items,
        "open_questions": questions,
        "run_summary": next_summary,
    }
    return normalize_problem_brief(updated), {"moved_items": moved_items, "moved_questions": moved_questions}


def _is_bookkeeping(raw: dict[str, Any]) -> bool:
    text = str(raw.get("text") or "").strip().lower()
    return any(snippet in text for snippet in _RUN_BOOKKEEPING_TEXT_SNIPPETS)


def _sanitize_run_ack_patch_payload(patch_payload: dict[str, Any], *, workflow_mode: str | None = None) -> dict[str, Any]:
    """
    Keep run-ack brief edits compact: allow open-question curation plus durable config-slot rows.
    Drop per-run/session bookkeeping rows to prevent Definition growth across runs.
    """
    sanitized = dict(patch_payload)
    raw_items = sanitized.get("items")
    if not isinstance(raw_items, list):
        sanitized["replace_editable_items"] = False
        return sanitized

    mode = str(workflow_mode or "").strip().lower()
    kept_items: list[dict[str, Any]] = []
    kept_agile_assumption_count = 0
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip().lower()
        # On run-ack turns we normally keep only durable config-slot rows. Agile is allowed
        # a very small provisional assumption update to support iterative refinement.
        if kind == "assumption" and mode == "agile":
            if not _is_bookkeeping(raw) and kept_agile_assumption_count < 1:
                kept_items.append(raw)
                kept_agile_assumption_count += 1
            continue
        slot = problem_brief_item_slot(raw)
        if slot and not _is_bookkeeping(raw):
            kept_items.append(raw)

    sanitized["items"] = kept_items
    sanitized["replace_editable_items"] = False
    return sanitized


def sanitize_run_ack_patch_payload(patch_payload: dict[str, Any], *, workflow_mode: str | None = None) -> dict[str, Any]:
    """Public wrapper for run-ack patch sanitization."""
    return _sanitize_run_ack_patch_payload(patch_payload, workflow_mode=workflow_mode)


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
    is_run_acknowledgement: bool = False,
    cleanup_mode: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Shared patch-merge pipeline used by definition cleanup and OQ cleanup-triggered flows.
    """
    merged = merge_problem_brief_patch(base_problem_brief, patch_payload)
    if not enable_auto_open_question_cleanup or merged == base_problem_brief:
        consolidated, run_meta = consolidate_run_summary(
            merged,
            recent_runs_summary=recent_runs_summary,
            cleanup_mode=cleanup_mode,
            is_run_acknowledgement=is_run_acknowledgement,
        )
        return consolidated, {"removed_total": 0, **run_meta}
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
    consolidated, run_meta = consolidate_run_summary(
        cleaned,
        recent_runs_summary=recent_runs_summary,
        cleanup_mode=cleanup_mode,
        is_run_acknowledgement=is_run_acknowledgement,
    )
    return consolidated, {**meta, **run_meta}


def _run_with_timeout(callable_obj, timeout_sec: float):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(callable_obj)
    try:
        return future.result(timeout=timeout_sec)
    finally:
        # Don't block on shutdown — if the LLM thread is still running after a
        # timeout, wait=True would hold the request handler open indefinitely.
        executor.shutdown(wait=False)


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
    is_config_save: bool = False,
    is_upload_context: bool = False,
    is_tutorial_active: bool = False,
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
                    is_config_save=is_config_save,
                    is_upload_context=is_upload_context,
                    is_tutorial_active=is_tutorial_active,
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
                patch_payload = _sanitize_run_ack_patch_payload(patch_payload)
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
                is_run_acknowledgement=is_run_acknowledgement,
                cleanup_mode=cleanup_requested or bool(brief_turn.cleanup_mode),
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

            # On a config-save turn the participant just authored the panel via
            # the form; re-deriving the panel from the brief here can flip
            # goal-term types or weights back (the LLM/heuristic derivation is
            # not guaranteed to reproduce the exact panel the user just saved).
            # The PATCH endpoint already synced the brief from that panel, so
            # the brief and panel are consistent — skip the panel re-derivation.
            if not is_config_save:
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
    except sync.GoalTermValidationError as exc:
        log.exception("Background derivation goal-term validation failed for session %s", session_id)
        with SessionLocal() as db:
            row = db.get(StudySession, session_id)
            if row is not None and row.processing_revision == revision:
                helpers.fail_processing_state(row, exc.processing_error_text())
                append_message(
                    db,
                    session_id,
                    "assistant",
                    "I could not sync the configuration because goal terms were inconsistent with the current definition. "
                    "Please retry sync after confirming the Definition items cover each goal term.",
                    True,
                    kind="panel",
                )
                db.commit()
        return
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
