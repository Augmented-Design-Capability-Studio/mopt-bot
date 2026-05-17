"""Chat pipeline runner — orchestrates S1→S2→S3→S4→S5 for one chat turn.

This module is the wiring layer between the main-turn LLM
(``llm.generate_main_turn``), the verification module
(``pipeline_verification``), the per-message status writer
(``pipeline_status``), and the existing brief/panel persistence helpers.

Entry points:

- ``run_chat_pipeline`` — start a fresh run for an assistant message that
  was just persisted (called from the chat router after the message
  row is committed).
- ``resume_pipeline_from_pause`` — participant-triggered Retry: re-runs
  the paused stage with ``retried=true`` so a third failure surfaces
  as a permanent failure (no further retry).
- ``revert_paused_pipeline`` — participant-triggered Revert: settles
  the paused pipeline without applying any of the staged changes.

Threading model: ``run_chat_pipeline`` launches a daemon thread so the
HTTP request can return immediately with the visible reply. Stage
transitions write to the message's ``meta.pipeline`` blob; the
frontend polls via the existing ``meta.verifying`` flag.
"""

from __future__ import annotations

import json
import logging
from threading import Thread
from typing import Any

from app.database import SessionLocal
from app.models import ChatMessage, StudySession
from app.routers.sessions import derivation, helpers, sync
from app.schemas import ChatTurnResponse, PipelineIssue
from app.services import pipeline_status, pipeline_verification

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Snapshot / state helpers
# ---------------------------------------------------------------------------


def _read_pipeline_meta(message_id: int) -> dict[str, Any] | None:
    """Best-effort read of ``meta.pipeline`` for a message."""
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None or not msg.meta_json:
            return None
        try:
            parsed = json.loads(msg.meta_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        pipeline = parsed.get("pipeline")
        if isinstance(pipeline, dict):
            return pipeline
    return None


def _read_session_pre_turn_snapshot(session_id: str) -> dict[str, Any] | None:
    """Read ``meta.pre_turn_state`` from the run-pipeline ChatMessage — set
    when the runner first launches so Revert has something to roll back to.
    """
    # Pre-turn state is intentionally stored on the message itself for
    # locality; we already write to meta on every transition.
    return None  # placeholder — Phase 4 wires this in via the runner.


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run_chat_pipeline(
    *,
    session_id: str,
    revision: int,
    message_id: int,
    flavor: pipeline_status.PipelineFlavor,
    user_text: str,
    workflow_mode: str,
    api_key: str,
    model_name: str,
    history_lines: list[tuple[str, str]],
    researcher_steers: list[str] | None,
    recent_runs_summary: list[dict[str, Any]] | None,
    base_problem_brief: dict[str, Any],
    base_panel: dict[str, Any] | None,
    is_run_acknowledgement: bool = False,
    is_brief_edit_ack: bool = False,
    is_config_save: bool = False,
    is_upload_context: bool = False,
    is_answered_open_question: bool = False,
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    gate_status: dict[str, Any] | None = None,
    skip_derive_config: bool = False,
) -> None:
    """Launch the chat pipeline in a daemon thread.

    The visible assistant reply has already been persisted by the caller
    (with ``meta.verifying=true`` + an initial ``meta.pipeline`` payload).
    This function takes over, runs each stage, and updates the
    per-stage state as work progresses.
    """
    # Persist the pre-turn snapshot inline on the message so Revert can
    # restore without needing a separate row. Snapshot table also exists
    # but writing here is cheaper and scoped to one turn.
    _persist_pre_turn_snapshot(
        message_id=message_id,
        base_problem_brief=base_problem_brief,
        base_panel=base_panel,
    )

    kwargs = dict(
        session_id=session_id,
        revision=revision,
        message_id=message_id,
        flavor=flavor,
        user_text=user_text,
        workflow_mode=workflow_mode,
        api_key=api_key,
        model_name=model_name,
        history_lines=history_lines,
        researcher_steers=researcher_steers,
        recent_runs_summary=recent_runs_summary,
        base_problem_brief=base_problem_brief,
        base_panel=base_panel,
        is_run_acknowledgement=is_run_acknowledgement,
        is_brief_edit_ack=is_brief_edit_ack,
        is_config_save=is_config_save,
        is_upload_context=is_upload_context,
        is_answered_open_question=is_answered_open_question,
        is_tutorial_active=is_tutorial_active,
        test_problem_id=test_problem_id,
        gate_status=gate_status,
        skip_derive_config=skip_derive_config,
    )
    thread = Thread(
        target=_run_chat_pipeline_thread,
        kwargs=kwargs,
        daemon=True,
        name=f"pipeline-v2-{session_id}-{message_id}",
    )
    thread.start()


def resume_pipeline_from_pause(
    *,
    session_id: str,
    message_id: int,
) -> dict[str, Any]:
    """Participant-triggered Retry — relaunch the pipeline from the paused stage.

    Reads the stored pause context (``meta.pipeline.paused_stage`` +
    ``meta.pre_turn_state``) and kicks off a fresh thread that resumes
    from that stage. The stage's ``retried`` flag was already set on the
    first failure, so a second failure here surfaces as a permanent
    failure (the action row stays visible; further Retry is allowed but
    the LLM will keep getting the same feedback).
    """
    pipeline = _read_pipeline_meta(message_id)
    if not pipeline:
        raise KeyError("no_pipeline")
    paused = pipeline.get("paused_stage")
    if not paused:
        raise KeyError("not_paused")

    # Rebuild the runner context BEFORE flipping the stage. Earlier this
    # function flipped paused → in_progress first, so any exception during
    # rebuild (e.g. a bad column reference, missing api key) left the stage
    # stuck in in_progress with no thread running — the UI hung forever.
    # Build first, commit second: atomic resume.
    context = _rebuild_runner_context(session_id=session_id, message_id=message_id)
    if context is None:
        raise KeyError("missing_context")
    context["resume_from"] = paused

    pipeline_status.update_stage(
        message_id=message_id,
        stage_name=paused,  # type: ignore[arg-type]
        state="in_progress",
    )
    thread = Thread(
        target=_run_chat_pipeline_thread,
        kwargs=context,
        daemon=True,
        name=f"pipeline-v2-resume-{session_id}-{message_id}",
    )
    thread.start()
    return {"resumed_from": paused}


def revert_paused_pipeline(
    *,
    session_id: str,
    message_id: int,
) -> None:
    """Participant-triggered Revert — discard the in-flight pipeline and
    restore the pre-turn brief/panel state from the snapshot we stored
    inline on the assistant message.
    """
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None or not msg.meta_json:
            raise KeyError("no_message")
        meta = json.loads(msg.meta_json) if msg.meta_json else {}
        if not isinstance(meta, dict):
            meta = {}
        pipeline = meta.get("pipeline")
        if not isinstance(pipeline, dict) or not pipeline.get("paused_stage"):
            raise KeyError("not_paused")
        pre_turn = meta.get("pre_turn_state")
        if isinstance(pre_turn, dict):
            row = db.get(StudySession, session_id)
            if row is not None:
                if "problem_brief" in pre_turn:
                    row.problem_brief_json = json.dumps(
                        pre_turn["problem_brief"], ensure_ascii=False
                    )
                if "panel_config" in pre_turn and pre_turn["panel_config"] is not None:
                    row.panel_config_json = json.dumps(
                        pre_turn["panel_config"], ensure_ascii=False
                    )
                # Bump revision so any in-flight background job aborts.
                row.processing_revision = int(row.processing_revision or 0) + 1
                helpers.settle_processing_state(row)
                db.commit()
        # Settle the pipeline meta to "reverted" — paused stages stay
        # failed but no longer block polling.
        meta["verifying"] = False
        if isinstance(pipeline, dict):
            pipeline["paused_stage"] = None
            pipeline["reverted"] = True
        msg.meta_json = json.dumps(meta, ensure_ascii=False)
        db.commit()


# ---------------------------------------------------------------------------
# Internal — thread body (Phase 4 fills in the actual orchestration)
# ---------------------------------------------------------------------------


def _run_chat_pipeline_thread(
    *,
    session_id: str,
    revision: int,
    message_id: int,
    flavor: pipeline_status.PipelineFlavor,
    user_text: str,
    workflow_mode: str,
    api_key: str,
    model_name: str,
    history_lines: list[tuple[str, str]],
    researcher_steers: list[str] | None,
    recent_runs_summary: list[dict[str, Any]] | None,
    base_problem_brief: dict[str, Any],
    base_panel: dict[str, Any] | None,
    is_run_acknowledgement: bool,
    is_brief_edit_ack: bool,
    is_config_save: bool,
    is_upload_context: bool,
    is_answered_open_question: bool,
    is_tutorial_active: bool,
    test_problem_id: str | None,
    gate_status: dict[str, Any] | None,
    skip_derive_config: bool,
    resume_from: str | None = None,
) -> None:
    """Run S1→S2→S3→S4→S5 in sequence, updating per-stage status.

    On any second-attempt failure, set the stage to ``paused`` and exit.
    The participant clicks Retry / Revert to resume / abort.
    """
    from app.services import llm  # local import to avoid cycles

    try:
        # ------------------ Stage 1: Drafting (S1 LLM call) ------------------
        if resume_from is None or resume_from == "drafting":
            pipeline_status.update_stage(
                message_id=message_id, stage_name="drafting", state="in_progress"
            )
            turn = llm.generate_main_turn(
                user_text=user_text,
                history_lines=history_lines,
                api_key=api_key,
                model_name=model_name,
                current_problem_brief=base_problem_brief,
                workflow_mode=workflow_mode,
                current_panel=base_panel,
                recent_runs_summary=recent_runs_summary,
                researcher_steers=researcher_steers,
                is_run_acknowledgement=is_run_acknowledgement,
                is_brief_edit_ack=is_brief_edit_ack,
                is_config_save=is_config_save,
                is_upload_context=is_upload_context,
                is_answered_open_question=is_answered_open_question,
                is_tutorial_active=is_tutorial_active,
                test_problem_id=test_problem_id,
                gate_status=gate_status,
            )
            if turn is None:
                # Replace the placeholder with a visible failure message so
                # the participant doesn't see a bare "..." while the
                # checklist surfaces the structured issue alongside.
                _persist_assistant_message(
                    message_id=message_id,
                    visible_reply=(
                        "I couldn't generate a response — the model returned "
                        "an empty or malformed result. Click Retry below to try "
                        "again, or send a fresh message."
                    ),
                    inline_followup=None,
                    is_run_invitation=False,
                )
                pipeline_status.update_stage(
                    message_id=message_id,
                    stage_name="drafting",
                    state="paused",
                    issues=[
                        {
                            "category": "schema_invalid",
                            "severity": "error",
                            "subject": "main_turn",
                            "message": (
                                "The model returned an empty or malformed response. "
                                "Click Retry to try again."
                            ),
                        }
                    ],
                    bump_retried=True,
                )
                pipeline_status.fail_pipeline(
                    message_id=message_id, paused_stage="drafting"
                )
                return
            # Persist the LLM-emitted visible reply onto the message (the row
            # already exists from the router's pre-launch persistence).
            _persist_assistant_message(
                message_id=message_id,
                visible_reply=turn.assistant_message,
                inline_followup=turn.inline_followup,
                is_run_invitation=bool(turn.is_run_invitation),
            )
            pipeline_status.update_stage(
                message_id=message_id, stage_name="drafting", state="success"
            )
        else:
            # If resuming from a later stage, fetch the previous turn's
            # patch from the meta blob (we persist it for resume).
            turn = _read_persisted_turn(message_id)
            if turn is None:
                pipeline_status.update_stage(
                    message_id=message_id,
                    stage_name="drafting",
                    state="paused",
                    issues=[
                        {
                            "category": "schema_invalid",
                            "severity": "error",
                            "subject": "main_turn",
                            "message": "Could not resume — previous draft missing.",
                        }
                    ],
                )
                pipeline_status.fail_pipeline(
                    message_id=message_id, paused_stage="drafting"
                )
                return

        # Concept-question fast path: empty patch + is_change_intent=false
        # → mark verifying/applying/derive/verify_config as skipped and settle.
        patch_empty = pipeline_verification._patch_is_empty(turn.problem_brief_patch)
        if (
            not turn.is_change_intent
            and patch_empty
            and not _reply_commits(turn.assistant_message)
        ):
            for sname in ("verifying_brief", "applying", "deriving_config", "verifying_config"):
                pipeline_status.update_stage(
                    message_id=message_id, stage_name=sname, state="skipped"  # type: ignore[arg-type]
                )
            pipeline_status.settle_pipeline(message_id=message_id)
            _settle_session_state(session_id, revision)
            return

        # ------------------ Stage 2: Verify brief ------------------
        if resume_from is None or resume_from in ("drafting", "verifying_brief"):
            _run_verify_brief_stage(
                message_id=message_id,
                turn=turn,
                user_text=user_text,
                history_lines=history_lines,
                api_key=api_key,
                model_name=model_name,
                base_problem_brief=base_problem_brief,
                base_panel=base_panel,
                workflow_mode=workflow_mode,
                researcher_steers=researcher_steers,
                recent_runs_summary=recent_runs_summary,
                is_run_acknowledgement=is_run_acknowledgement,
                is_brief_edit_ack=is_brief_edit_ack,
                is_config_save=is_config_save,
                is_upload_context=is_upload_context,
                is_answered_open_question=is_answered_open_question,
                is_tutorial_active=is_tutorial_active,
                test_problem_id=test_problem_id,
                gate_status=gate_status,
            )

        # ------------------ Stage 3: Apply patch ------------------
        applied_brief = _apply_stage(
            message_id=message_id,
            turn=turn,
            session_id=session_id,
            revision=revision,
            base_problem_brief=base_problem_brief,
            base_panel=base_panel,
            workflow_mode=workflow_mode,
            history_lines=history_lines,
            api_key=api_key,
            model_name=model_name,
            researcher_steers=researcher_steers,
            recent_runs_summary=recent_runs_summary,
            is_run_acknowledgement=is_run_acknowledgement,
            user_text=user_text,
            test_problem_id=test_problem_id,
        )
        if applied_brief is None:
            return  # already marked paused / failed by _apply_stage

        # ------------------ Stage 4 + 5: Derive + verify config ------------------
        # The S5 retry leg for the config-save flavor needs the original turn
        # context so it can re-call generate_main_turn with verification
        # feedback. Bundle it once and pass through.
        retry_context: dict[str, Any] = {
            "user_text": user_text,
            "history_lines": history_lines,
            "researcher_steers": researcher_steers,
            "recent_runs_summary": recent_runs_summary,
            "base_problem_brief": base_problem_brief,
            "base_panel": base_panel,
            "is_run_acknowledgement": is_run_acknowledgement,
            "is_brief_edit_ack": is_brief_edit_ack,
            "is_config_save": is_config_save,
            "is_upload_context": is_upload_context,
            "is_answered_open_question": is_answered_open_question,
            "is_tutorial_active": is_tutorial_active,
            "gate_status": gate_status,
        }
        if skip_derive_config or is_config_save:
            pipeline_status.update_stage(
                message_id=message_id, stage_name="deriving_config", state="skipped"
            )
            _run_verify_config_stage(
                message_id=message_id,
                session_id=session_id,
                revision=revision,
                brief=applied_brief,
                workflow_mode=workflow_mode,
                test_problem_id=test_problem_id,
                api_key=api_key,
                model_name=model_name,
                recent_runs_summary=recent_runs_summary,
                derive_config=False,
                retry_context=retry_context,
            )
        else:
            _run_derive_and_verify_stages(
                message_id=message_id,
                session_id=session_id,
                revision=revision,
                brief=applied_brief,
                workflow_mode=workflow_mode,
                test_problem_id=test_problem_id,
                api_key=api_key,
                model_name=model_name,
                recent_runs_summary=recent_runs_summary,
                retry_context=retry_context,
            )

        pipeline_status.settle_pipeline(message_id=message_id)
        _settle_session_state(session_id, revision)
    except _PipelinePaused as paused_exc:
        # Internal control-flow sentinel raised by a stage helper after it
        # has ALREADY written its own structured `paused` state + issues to
        # the pipeline meta (see ``_run_verify_brief_stage`` etc.). The
        # orchestrator must not overwrite that with the generic
        # "drafting=paused / internal error" branch below — the
        # already-persisted paused state IS the correct UI state. Just exit
        # cleanly; the action row will render off the existing meta.
        log.info(
            "Chat pipeline paused at stage %s for session %s message %s",
            getattr(paused_exc, "args", ("unknown",))[0] if paused_exc.args else "unknown",
            session_id,
            message_id,
        )
    except Exception:
        log.exception("Chat pipeline thread crashed for session %s message %s", session_id, message_id)
        # If the placeholder is still on the message (S1 didn't even start),
        # replace it so the participant sees a visible failure message
        # alongside the checklist's structured issue.
        _replace_placeholder_with_error(
            message_id,
            (
                "Something went wrong on the server while preparing this reply. "
                "Click Retry below to try again."
            ),
        )
        pipeline_status.update_stage(
            message_id=message_id,
            stage_name="drafting",  # generic catch-all if we don't know where we crashed
            state="paused",
            issues=[
                {
                    "category": "schema_invalid",
                    "severity": "error",
                    "subject": "pipeline",
                    "message": "An internal error stopped the pipeline. Click Retry to try again.",
                }
            ],
        )
        pipeline_status.fail_pipeline(message_id=message_id, paused_stage="drafting")


# ---------------------------------------------------------------------------
# Internal — per-stage helpers
# ---------------------------------------------------------------------------


def _persist_pre_turn_snapshot(
    *,
    message_id: int,
    base_problem_brief: dict[str, Any],
    base_panel: dict[str, Any] | None,
) -> None:
    """Store the pre-turn brief + panel on the message's meta so Revert
    can restore them without needing a session_snapshots row."""
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None:
            return
        meta = {}
        if msg.meta_json:
            try:
                meta = json.loads(msg.meta_json) or {}
            except json.JSONDecodeError:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        meta["pre_turn_state"] = {
            "problem_brief": base_problem_brief,
            "panel_config": base_panel,
        }
        msg.meta_json = json.dumps(meta, ensure_ascii=False)
        db.commit()


# Must mirror the placeholder text the router writes when launching the pipeline.
# See ``router._handle_post_participant_message`` (the placeholder=derivation.append_message
# call) — the runner uses this to detect "S1 didn't finish" so a thread-level crash
# can swap the placeholder for a clear error message without clobbering a successful
# S1 reply.
_PLACEHOLDER_REPLIES: frozenset[str] = frozenset(
    {"...", "Drafting a reply…", "Drafting a reply..."}
)


def _replace_placeholder_with_error(message_id: int, fallback: str) -> None:
    """If the message still carries a pre-launch placeholder, swap it for
    ``fallback``. No-op when the runner already wrote a real reply (we don't
    want to clobber a successful S1 result with an error string just because
    a later stage threw).
    """
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None:
            return
        if (msg.content or "").strip() not in _PLACEHOLDER_REPLIES:
            return
        msg.content = fallback
        db.commit()


def _persist_assistant_message(
    *,
    message_id: int,
    visible_reply: str,
    inline_followup: str | None,
    is_run_invitation: bool,
) -> None:
    """Overwrite the message content with the LLM's visible_reply and set
    auxiliary meta fields. The row was created by the router with a
    placeholder reply (since S1 hasn't run yet); this finalizes it."""
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None:
            return
        msg.content = visible_reply
        meta = {}
        if msg.meta_json:
            try:
                meta = json.loads(msg.meta_json) or {}
            except json.JSONDecodeError:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        if is_run_invitation:
            meta["is_run_invitation"] = True
        else:
            meta.pop("is_run_invitation", None)
        if inline_followup:
            pipeline = meta.get("pipeline")
            if isinstance(pipeline, dict):
                pipeline["inline_followup"] = inline_followup
        msg.meta_json = json.dumps(meta, ensure_ascii=False)
        db.commit()


def _persist_turn_for_resume(message_id: int, turn: ChatTurnResponse) -> None:
    """Stash the LLM turn body on the message meta so Retry/Resume can
    pick up where the previous attempt left off."""
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None:
            return
        meta = {}
        if msg.meta_json:
            try:
                meta = json.loads(msg.meta_json) or {}
            except json.JSONDecodeError:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        meta["v2_turn_snapshot"] = turn.model_dump()
        msg.meta_json = json.dumps(meta, ensure_ascii=False)
        db.commit()


def _read_persisted_turn(message_id: int) -> ChatTurnResponse | None:
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None or not msg.meta_json:
            return None
        try:
            meta = json.loads(msg.meta_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(meta, dict):
            return None
        raw = meta.get("v2_turn_snapshot")
        if not isinstance(raw, dict):
            return None
        try:
            return ChatTurnResponse.model_validate(raw)
        except Exception:
            return None


def _rebuild_runner_context(*, session_id: str, message_id: int) -> dict[str, Any] | None:
    """Reconstruct enough state to relaunch the runner on Retry."""
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        row = db.get(StudySession, session_id)
        if msg is None or row is None:
            return None
        meta = {}
        if msg.meta_json:
            try:
                meta = json.loads(msg.meta_json) or {}
            except json.JSONDecodeError:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        pre = meta.get("pre_turn_state") or {}
        base_brief = pre.get("problem_brief") or helpers.problem_brief_dict(row)
        base_panel = pre.get("panel_config") or helpers.panel_dict(row)
        # We don't have the original user_text — fall back to the
        # latest user message in the transcript.
        from app.models import ChatMessage as _Msg

        last_user = (
            db.query(_Msg)
            .filter(_Msg.session_id == session_id, _Msg.role == "user")
            .order_by(_Msg.id.desc())
            .first()
        )
        user_text = last_user.content if last_user else ""
    pipeline = meta.get("pipeline") if isinstance(meta, dict) else {}
    flavor = (
        pipeline.get("flavor") if isinstance(pipeline, dict) else None
    ) or "chat"
    # Decrypt the Gemini key here (the original chat-turn path decrypts in
    # router._handle_post_participant_message before launching the runner;
    # the resume path bypasses that, so do it explicitly).
    # Earlier this referenced ``row.gemini_api_key_encrypted`` which doesn't
    # exist on the model — every Retry click 500'd on AttributeError.
    from app.crypto_util import decrypt_secret

    try:
        api_key = decrypt_secret(row.gemini_key_encrypted) or ""
    except Exception:
        log.exception("Failed to decrypt gemini key during pipeline resume")
        api_key = ""
    return dict(
        session_id=session_id,
        revision=int(row.processing_revision or 0),
        message_id=message_id,
        flavor=flavor,
        user_text=user_text,
        workflow_mode=str(row.workflow_mode or "waterfall"),
        api_key=api_key,
        model_name=str(row.gemini_model or ""),
        history_lines=[],
        researcher_steers=None,
        recent_runs_summary=None,
        base_problem_brief=base_brief,
        base_panel=base_panel,
        is_run_acknowledgement=False,
        is_brief_edit_ack=False,
        is_config_save=False,
        is_upload_context=False,
        is_answered_open_question=False,
        is_tutorial_active=False,
        test_problem_id=row.test_problem_id,
        gate_status=None,
        skip_derive_config=False,
    )


def _settle_session_state(session_id: str, revision: int) -> None:
    """Mark the session ready and clear any pending status, mirroring
    derivation._run_background_derivation's settle path."""
    with SessionLocal() as db:
        row = db.get(StudySession, session_id)
        if row is None or row.processing_revision != revision:
            return
        row.brief_status = "ready"
        row.config_status = helpers.desired_config_status(row)
        row.processing_error = None
        helpers.touch_session(row)
        helpers.sync_optimization_allowed_after_participant_mutation(row)
        db.commit()


def _reply_commits(text: str | None) -> bool:
    return pipeline_verification._reply_claims_change(text)


def _run_verify_brief_stage(
    *,
    message_id: int,
    turn: ChatTurnResponse,
    user_text: str,
    history_lines: list[tuple[str, str]],
    api_key: str,
    model_name: str,
    base_problem_brief: dict[str, Any],
    base_panel: dict[str, Any] | None,
    workflow_mode: str,
    researcher_steers: list[str] | None,
    recent_runs_summary: list[dict[str, Any]] | None,
    is_run_acknowledgement: bool,
    is_brief_edit_ack: bool,
    is_config_save: bool,
    is_upload_context: bool,
    is_answered_open_question: bool,
    is_tutorial_active: bool,
    test_problem_id: str | None,
    gate_status: dict[str, Any] | None,
) -> None:
    """S2 — verify; on first failure retry S1 once with feedback; on
    second failure pause. Updates the brief on the persisted turn
    snapshot so Stage 3 (apply) sees the corrected patch."""
    from app.problem_brief import merge_problem_brief_patch
    from app.services import llm

    pipeline_status.update_stage(
        message_id=message_id, stage_name="verifying_brief", state="in_progress"
    )

    def _merged(t: ChatTurnResponse) -> dict[str, Any]:
        if t.problem_brief_patch:
            return merge_problem_brief_patch(base_problem_brief, t.problem_brief_patch)
        return dict(base_problem_brief)

    issues = pipeline_verification.verify_brief_consistency(
        merged_brief=_merged(turn),
        base_brief=base_problem_brief,
        patch=turn.problem_brief_patch,
        visible_reply=turn.assistant_message,
        workflow_mode=workflow_mode,
        test_problem_id=test_problem_id,
        is_change_intent=bool(turn.is_change_intent),
        is_run_acknowledgement=is_run_acknowledgement,
    )
    if not issues:
        _persist_turn_for_resume(message_id, turn)
        pipeline_status.update_stage(
            message_id=message_id, stage_name="verifying_brief", state="success"
        )
        return

    # First failure → retry S1 with feedback.
    pipeline_status.update_stage(
        message_id=message_id,
        stage_name="verifying_brief",
        state="failed",
        issues=pipeline_verification.issues_to_audit_payload(issues),
        bump_retried=True,
    )
    pipeline_status.update_stage(
        message_id=message_id, stage_name="drafting", state="in_progress"
    )
    retry = llm.generate_main_turn(
        user_text=user_text,
        history_lines=history_lines,
        api_key=api_key,
        model_name=model_name,
        current_problem_brief=base_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=base_panel,
        recent_runs_summary=recent_runs_summary,
        researcher_steers=researcher_steers,
        is_run_acknowledgement=is_run_acknowledgement,
        is_brief_edit_ack=is_brief_edit_ack,
        is_config_save=is_config_save,
        is_upload_context=is_upload_context,
        is_answered_open_question=is_answered_open_question,
        is_tutorial_active=is_tutorial_active,
        test_problem_id=test_problem_id,
        gate_status=gate_status,
        verification_issues=pipeline_verification.issues_to_audit_payload(issues),
    )
    if retry is None:
        pipeline_status.update_stage(
            message_id=message_id,
            stage_name="verifying_brief",
            state="paused",
            issues=pipeline_verification.issues_to_audit_payload(issues),
        )
        pipeline_status.fail_pipeline(message_id=message_id, paused_stage="verifying_brief")
        raise _PipelinePaused("verifying_brief")
    _persist_assistant_message(
        message_id=message_id,
        visible_reply=retry.assistant_message,
        inline_followup=retry.inline_followup,
        is_run_invitation=bool(retry.is_run_invitation),
    )
    pipeline_status.update_stage(
        message_id=message_id, stage_name="drafting", state="success"
    )
    # Verify again.
    retry_issues = pipeline_verification.verify_brief_consistency(
        merged_brief=_merged(retry),
        base_brief=base_problem_brief,
        patch=retry.problem_brief_patch,
        visible_reply=retry.assistant_message,
        workflow_mode=workflow_mode,
        test_problem_id=test_problem_id,
        is_change_intent=bool(retry.is_change_intent),
        is_run_acknowledgement=is_run_acknowledgement,
    )
    if retry_issues:
        pipeline_status.update_stage(
            message_id=message_id,
            stage_name="verifying_brief",
            state="paused",
            issues=pipeline_verification.issues_to_audit_payload(retry_issues),
        )
        pipeline_status.fail_pipeline(message_id=message_id, paused_stage="verifying_brief")
        # Stash the latest turn for resume
        _persist_turn_for_resume(message_id, retry)
        raise _PipelinePaused("verifying_brief")
    _persist_turn_for_resume(message_id, retry)
    pipeline_status.update_stage(
        message_id=message_id, stage_name="verifying_brief", state="success"
    )
    # Replace the bound `turn` reference for caller via persisted snapshot.
    # The caller re-reads from _read_persisted_turn in subsequent stages.
    # We mutate by writing to the message's meta only — no need to
    # propagate through the function signature.
    turn.__dict__.update(retry.__dict__)


def _apply_stage(
    *,
    message_id: int,
    turn: ChatTurnResponse,
    session_id: str,
    revision: int,
    base_problem_brief: dict[str, Any],
    base_panel: dict[str, Any] | None,
    workflow_mode: str,
    history_lines: list[tuple[str, str]],
    api_key: str,
    model_name: str,
    researcher_steers: list[str] | None,
    recent_runs_summary: list[dict[str, Any]] | None,
    is_run_acknowledgement: bool,
    user_text: str,
    test_problem_id: str | None,
) -> dict[str, Any] | None:
    """S3 — deterministic patch apply + workflow coercion + monitors +
    assumption_actions. Returns the merged-and-coerced brief, or None
    if the pipeline paused (caller bails).
    """
    pipeline_status.update_stage(
        message_id=message_id, stage_name="applying", state="in_progress"
    )
    try:
        patch_payload: dict[str, Any] | None = None
        if turn.problem_brief_patch:
            patch_payload = dict(turn.problem_brief_patch)
        if patch_payload is not None:
            if turn.replace_editable_items:
                patch_payload["replace_editable_items"] = True
            if turn.replace_open_questions:
                patch_payload["replace_open_questions"] = True
            effective_brief, _meta = derivation.apply_brief_patch_with_cleanup(
                base_problem_brief=base_problem_brief,
                patch_payload=patch_payload,
                workflow_mode=workflow_mode,
                recent_runs_summary=recent_runs_summary or [],
                test_problem_id=test_problem_id,
                is_run_acknowledgement=is_run_acknowledgement,
                cleanup_mode=turn.cleanup_mode,
                user_text=user_text,
                api_key=api_key,
            )
        else:
            effective_brief = dict(base_problem_brief)
        from app.problem_brief import coerce_problem_brief_for_workflow

        effective_brief = coerce_problem_brief_for_workflow(effective_brief, workflow_mode)
        # Apply assumption_actions if any.
        if turn.assumption_actions and str(workflow_mode or "").strip().lower() in (
            "agile",
            "demo",
        ):
            effective_brief = derivation._apply_assumption_actions(
                effective_brief,
                [a.model_dump() for a in turn.assumption_actions],
            )
            effective_brief = coerce_problem_brief_for_workflow(effective_brief, workflow_mode)
        effective_brief = derivation._enforce_session_monitors(effective_brief, workflow_mode)

        # Persist the merged brief on the session row.
        with SessionLocal() as db:
            row = db.get(StudySession, session_id)
            if row is None or row.processing_revision != revision:
                pipeline_status.update_stage(
                    message_id=message_id, stage_name="applying", state="skipped"
                )
                return None
            row.problem_brief_json = json.dumps(effective_brief, ensure_ascii=False)
            row.brief_status = "ready"
            row.config_status = "pending"
            row.processing_error = None
            helpers.touch_session(row)
            db.commit()
        pipeline_status.update_stage(
            message_id=message_id, stage_name="applying", state="success"
        )
        return effective_brief
    except Exception as exc:
        log.exception("Apply stage failed for message %s", message_id)
        pipeline_status.update_stage(
            message_id=message_id,
            stage_name="applying",
            state="paused",
            issues=[
                {
                    "category": "schema_invalid",
                    "severity": "error",
                    "subject": "apply",
                    "message": f"Couldn't apply the patch: {exc}. Click Retry to try again.",
                }
            ],
        )
        pipeline_status.fail_pipeline(message_id=message_id, paused_stage="applying")
        return None


def _run_derive_and_verify_stages(
    *,
    message_id: int,
    session_id: str,
    revision: int,
    brief: dict[str, Any],
    workflow_mode: str,
    test_problem_id: str | None,
    api_key: str,
    model_name: str,
    recent_runs_summary: list[dict[str, Any]] | None,
    retry_context: dict[str, Any] | None = None,
) -> None:
    """S4 — derive config + S5 — verify mapping. One retry on S4 failure
    with verification feedback."""
    pipeline_status.update_stage(
        message_id=message_id, stage_name="deriving_config", state="in_progress"
    )
    derived_panel = _derive_panel_once(
        session_id=session_id,
        revision=revision,
        brief=brief,
        workflow_mode=workflow_mode,
        test_problem_id=test_problem_id,
        api_key=api_key,
        model_name=model_name,
        recent_runs_summary=recent_runs_summary,
    )
    if derived_panel is None:
        pipeline_status.update_stage(
            message_id=message_id,
            stage_name="deriving_config",
            state="paused",
            issues=[
                {
                    "category": "schema_invalid",
                    "severity": "error",
                    "subject": "panel",
                    "message": (
                        "Couldn't derive the panel from the brief. Click Retry to try again."
                    ),
                }
            ],
            bump_retried=True,
        )
        pipeline_status.fail_pipeline(
            message_id=message_id, paused_stage="deriving_config"
        )
        return
    pipeline_status.update_stage(
        message_id=message_id, stage_name="deriving_config", state="success"
    )

    _run_verify_config_stage(
        message_id=message_id,
        session_id=session_id,
        revision=revision,
        brief=brief,
        workflow_mode=workflow_mode,
        test_problem_id=test_problem_id,
        api_key=api_key,
        model_name=model_name,
        recent_runs_summary=recent_runs_summary,
        derive_config=True,
        retry_context=retry_context,
    )


def _run_verify_config_stage(
    *,
    message_id: int,
    session_id: str,
    revision: int,
    brief: dict[str, Any],
    workflow_mode: str,
    test_problem_id: str | None,
    api_key: str,
    model_name: str,
    recent_runs_summary: list[dict[str, Any]] | None,
    derive_config: bool,
    retry_context: dict[str, Any] | None = None,
) -> None:
    """S5 — verify the derived panel against the brief.

    Retry strategy is origin-aware:
    - ``derive_config=True`` (chat / brief origin): brief is authoritative; on
      drift, re-run S4 (LLM-driven panel derivation) with issues as feedback.
    - ``derive_config=False`` (config-save origin): panel is authoritative; on
      drift, re-run S1 (LLM-driven brief patch) with issues as feedback. If
      the LLM retry still doesn't reach parity, deterministically re-mirror
      brief from panel via ``merge_brief_from_panel`` and mark
      ``meta.brief_panel_fallback_applied`` so the participant sees the
      system auto-aligned the definition.
    """
    pipeline_status.update_stage(
        message_id=message_id, stage_name="verifying_config", state="in_progress"
    )
    with SessionLocal() as db:
        row = db.get(StudySession, session_id)
        if row is None or row.processing_revision != revision:
            pipeline_status.update_stage(
                message_id=message_id, stage_name="verifying_config", state="skipped"
            )
            return
        panel = helpers.panel_dict(row)
    issues = pipeline_verification.verify_panel_consistency(
        brief=brief,
        panel=panel,
        workflow_mode=workflow_mode,
        test_problem_id=test_problem_id,
    )
    if not issues:
        pipeline_status.update_stage(
            message_id=message_id, stage_name="verifying_config", state="success"
        )
        return

    if derive_config:
        # Chat / brief origin: re-derive the panel.
        pipeline_status.update_stage(
            message_id=message_id,
            stage_name="verifying_config",
            state="failed",
            issues=pipeline_verification.issues_to_audit_payload(issues),
            bump_retried=True,
        )
        pipeline_status.update_stage(
            message_id=message_id, stage_name="deriving_config", state="in_progress"
        )
        derived = _derive_panel_once(
            session_id=session_id,
            revision=revision,
            brief=brief,
            workflow_mode=workflow_mode,
            test_problem_id=test_problem_id,
            api_key=api_key,
            model_name=model_name,
            recent_runs_summary=recent_runs_summary,
        )
        if derived is None:
            # Retry-derive blew up (validator error, LLM timeout, etc.). Without
            # this terminal-state update the `deriving_config` row stayed in
            # `in_progress` forever — the bubble showed a spinner with no
            # retry affordance even though `paused_stage` was set below.
            pipeline_status.update_stage(
                message_id=message_id,
                stage_name="deriving_config",
                state="paused",
                issues=[
                    {
                        "category": "schema_invalid",
                        "severity": "error",
                        "subject": "panel",
                        "message": (
                            "Couldn't re-derive the panel from the brief. "
                            "Click Retry to try again."
                        ),
                    }
                ],
                bump_retried=True,
            )
            pipeline_status.fail_pipeline(
                message_id=message_id, paused_stage="deriving_config"
            )
            return
        pipeline_status.update_stage(
            message_id=message_id, stage_name="deriving_config", state="success"
        )
        with SessionLocal() as db:
            row = db.get(StudySession, session_id)
            panel = helpers.panel_dict(row) if row else None
        issues2 = pipeline_verification.verify_panel_consistency(
            brief=brief,
            panel=panel,
            workflow_mode=workflow_mode,
            test_problem_id=test_problem_id,
        )
        if not issues2:
            pipeline_status.update_stage(
                message_id=message_id,
                stage_name="verifying_config",
                state="success",
            )
            return
        issues = issues2
    else:
        # Config-save origin: panel is ground truth; align the brief.
        next_brief, next_issues, fallback_applied = _retry_brief_from_panel(
            message_id=message_id,
            session_id=session_id,
            revision=revision,
            brief=brief,
            panel=panel,
            workflow_mode=workflow_mode,
            test_problem_id=test_problem_id,
            api_key=api_key,
            model_name=model_name,
            retry_context=retry_context or {},
            issues=issues,
        )
        if not next_issues:
            if fallback_applied:
                _mark_brief_panel_fallback_applied(message_id)
            pipeline_status.update_stage(
                message_id=message_id,
                stage_name="verifying_config",
                state="success",
            )
            return
        issues = next_issues
        brief = next_brief or brief

    pipeline_status.update_stage(
        message_id=message_id,
        stage_name="verifying_config",
        state="paused",
        issues=pipeline_verification.issues_to_audit_payload(issues),
    )
    pipeline_status.fail_pipeline(
        message_id=message_id, paused_stage="verifying_config"
    )


def _retry_brief_from_panel(
    *,
    message_id: int,
    session_id: str,
    revision: int,
    brief: dict[str, Any],
    panel: dict[str, Any] | None,
    workflow_mode: str,
    test_problem_id: str | None,
    api_key: str,
    model_name: str,
    retry_context: dict[str, Any],
    issues: list[pipeline_verification.PipelineIssue],
) -> tuple[dict[str, Any] | None, list[pipeline_verification.PipelineIssue], bool]:
    """Hybrid retry for the config-save flavor.

    1. **LLM retry**: re-run ``generate_main_turn`` with the drift issues as
       feedback so the model can fix the brief patch. Apply the new patch via
       ``apply_brief_patch_with_cleanup`` and re-verify.
    2. **Deterministic fallback**: if the LLM retry still produces drift,
       call ``merge_brief_from_panel`` to mirror the brief from the panel
       directly, then re-verify.

    Returns ``(next_brief, remaining_issues, fallback_applied)``. Empty
    ``remaining_issues`` signals success. ``fallback_applied=True`` is set
    only when step 2 ran AND step 1 didn't already clear the drift.
    """
    from app.problem_brief import coerce_problem_brief_for_workflow
    from app.services import llm
    from app.routers.sessions import derivation
    from app.routers.sessions.sync import sync_problem_brief_from_panel as run_merge_brief_from_panel

    pipeline_status.update_stage(
        message_id=message_id,
        stage_name="verifying_config",
        state="failed",
        issues=pipeline_verification.issues_to_audit_payload(issues),
        bump_retried=True,
    )

    user_text = retry_context.get("user_text") or ""
    history_lines = retry_context.get("history_lines") or []
    base_problem_brief = retry_context.get("base_problem_brief") or brief
    base_panel = retry_context.get("base_panel")

    # ---- Step 1: LLM retry ----
    pipeline_status.update_stage(
        message_id=message_id, stage_name="drafting", state="in_progress"
    )
    next_brief = brief
    retry_issues: list[pipeline_verification.PipelineIssue] = issues
    try:
        retry_turn = llm.generate_main_turn(
            user_text=user_text,
            history_lines=history_lines,
            api_key=api_key,
            model_name=model_name,
            current_problem_brief=base_problem_brief,
            workflow_mode=workflow_mode,
            current_panel=base_panel,
            recent_runs_summary=retry_context.get("recent_runs_summary"),
            researcher_steers=retry_context.get("researcher_steers"),
            is_run_acknowledgement=bool(retry_context.get("is_run_acknowledgement")),
            is_brief_edit_ack=bool(retry_context.get("is_brief_edit_ack")),
            is_config_save=bool(retry_context.get("is_config_save", True)),
            is_upload_context=bool(retry_context.get("is_upload_context")),
            is_answered_open_question=bool(retry_context.get("is_answered_open_question")),
            is_tutorial_active=bool(retry_context.get("is_tutorial_active")),
            test_problem_id=test_problem_id,
            gate_status=retry_context.get("gate_status"),
            verification_issues=pipeline_verification.issues_to_audit_payload(issues),
        )
    except Exception:
        log.exception("Config-save LLM retry failed for message %s", message_id)
        retry_turn = None

    if retry_turn is not None and retry_turn.problem_brief_patch:
        try:
            patch_payload = dict(retry_turn.problem_brief_patch)
            if retry_turn.replace_editable_items:
                patch_payload["replace_editable_items"] = True
            if retry_turn.replace_open_questions:
                patch_payload["replace_open_questions"] = True
            applied, _meta = derivation.apply_brief_patch_with_cleanup(
                base_problem_brief=base_problem_brief,
                patch_payload=patch_payload,
                workflow_mode=workflow_mode,
                recent_runs_summary=retry_context.get("recent_runs_summary") or [],
                test_problem_id=test_problem_id,
                is_run_acknowledgement=bool(retry_context.get("is_run_acknowledgement")),
                cleanup_mode=bool(retry_turn.cleanup_mode),
                user_text=user_text,
                api_key=api_key,
            )
            applied = coerce_problem_brief_for_workflow(applied, workflow_mode)
            applied = derivation._enforce_session_monitors(applied, workflow_mode)
            with SessionLocal() as db:
                row = db.get(StudySession, session_id)
                if row is not None and row.processing_revision == revision:
                    row.problem_brief_json = json.dumps(applied, ensure_ascii=False)
                    helpers.touch_session(row)
                    db.commit()
                    next_brief = applied
        except Exception:
            log.exception(
                "Config-save retry patch apply failed for message %s", message_id
            )

    pipeline_status.update_stage(
        message_id=message_id, stage_name="drafting", state="success"
    )
    retry_issues = pipeline_verification.verify_panel_consistency(
        brief=next_brief,
        panel=panel,
        workflow_mode=workflow_mode,
        test_problem_id=test_problem_id,
    )
    if not retry_issues:
        return next_brief, [], False

    # ---- Step 2: Deterministic fallback ----
    log.info(
        "Config-save LLM retry didn't reach brief↔panel parity for message %s; "
        "applying deterministic merge_brief_from_panel fallback.",
        message_id,
    )
    try:
        with SessionLocal() as db:
            row = db.get(StudySession, session_id)
            if row is None or row.processing_revision != revision:
                return next_brief, retry_issues, False
            mirrored = run_merge_brief_from_panel(row, db, panel or {})
            next_brief = mirrored
    except Exception:
        log.exception("Deterministic fallback failed for message %s", message_id)
        return next_brief, retry_issues, False
    final_issues = pipeline_verification.verify_panel_consistency(
        brief=next_brief,
        panel=panel,
        workflow_mode=workflow_mode,
        test_problem_id=test_problem_id,
    )
    return next_brief, final_issues, True


def _mark_brief_panel_fallback_applied(message_id: int) -> None:
    """Set ``meta.brief_panel_fallback_applied=true`` on the message so the
    frontend can render a notice that the system auto-aligned the brief with
    the panel after the LLM retry didn't reach parity."""
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None:
            return
        meta: dict[str, Any] = {}
        if msg.meta_json:
            try:
                meta = json.loads(msg.meta_json) or {}
            except json.JSONDecodeError:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        meta["brief_panel_fallback_applied"] = True
        msg.meta_json = json.dumps(meta, ensure_ascii=False)
        db.commit()


def _derive_panel_once(
    *,
    session_id: str,
    revision: int,
    brief: dict[str, Any],
    workflow_mode: str,
    test_problem_id: str | None,
    api_key: str,
    model_name: str,
    recent_runs_summary: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Run one config-derivation pass via existing sync.sync_panel_from_problem_brief
    and commit the new panel. Returns the committed panel or None on failure."""
    try:
        with SessionLocal() as db:
            row = db.get(StudySession, session_id)
            if row is None or row.processing_revision != revision:
                return None
            sync.sync_panel_from_problem_brief(
                row,
                db,
                brief,
                api_key=api_key,
                model_name=model_name,
                workflow_mode=workflow_mode,
                recent_runs_summary=recent_runs_summary,
                preserve_missing_managed_fields=True,
                commit=False,
            )
            current_rev = int(row.processing_revision or 0)
            if current_rev != revision:
                db.rollback()
                return None
            db.commit()
            db.refresh(row)
            return helpers.panel_dict(row)
    except Exception:
        log.exception("Config derivation failed for session %s", session_id)
        return None


class _PipelinePaused(Exception):
    """Internal sentinel: a stage hit second-failure pause; thread should exit cleanly."""
