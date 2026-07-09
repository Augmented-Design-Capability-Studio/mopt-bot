"""Turn context loading for chat."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import ChatMessage, OptimizationRun

from . import helpers


def load_fresh_researcher_steers(
    db: Session, session_id: str, before_message_id: int
) -> list[str]:
    """Researcher steers that are still awaiting acknowledgement for this turn.

    A researcher steer is a one-shot directive for the very NEXT agent reply,
    not a standing instruction. It's injected into the system prompt as
    "apply the latest steering directly in your next response" (see
    `_build_visible_chat_system_instruction`), so re-feeding a steer that was
    already applied on an earlier turn made the agent keep re-raising the same
    point every turn — e.g. repeatedly pushing an option the researcher asked
    it to mention "just once". Surface only steers that arrived SINCE the
    agent's last real reply: once the agent has responded after a steer, that
    steer is considered acknowledged and drops out. A researcher who wants to
    re-assert a point simply sends the steer again.

    The anchor is the last **chat** reply (`kind == "chat"`), i.e. an actual
    model turn. Canned acknowledgements are assistant rows too but do NOT
    invoke the model — the run summary ("Run #N finished", `kind="run"`) and
    the panel/definition save acks (`kind="panel"`). Anchoring on *any*
    assistant row would let one of those canned acks consume a steer sent
    mid-run/mid-save, so the steer would be dropped before the reply that
    actually goes through the LLM (run interpretation, config/def chat ack).
    Every model-invoking reply — plain chat, run acknowledgement, config-save,
    and definition-save — is written with the default `kind="chat"`, so this
    anchor makes the steer reach all of them exactly once. Shared with the
    Retry/resume path (`_rebuild_runner_context`) so a paused-then-resumed turn
    reconstructs the same fresh steers instead of losing them.
    """
    last_reply_id = (
        db.query(ChatMessage.id)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "assistant",
            ChatMessage.kind == "chat",
            ChatMessage.id < before_message_id,
        )
        .order_by(ChatMessage.id.desc())
        .limit(1)
        .scalar()
    )
    steer_query = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.role == "researcher",
        ChatMessage.visible_to_participant.is_(False),
        ChatMessage.id < before_message_id,
    )
    if last_reply_id is not None:
        # Only steers newer than the last real reply are still awaiting acknowledgement.
        steer_query = steer_query.filter(ChatMessage.id > last_reply_id)
    steer_rows = steer_query.order_by(ChatMessage.id.desc()).limit(4).all()
    return [message.content for message in reversed(steer_rows)]


def load_turn_context(
    db: Session, session_id: str, before_message_id: int
) -> tuple[list[tuple[str, str]], list[str], list[dict[str, Any]]]:
    hist: list[tuple[str, str]] = []
    prev = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.visible_to_participant.is_(True),
            ChatMessage.id < before_message_id,
        )
        .order_by(ChatMessage.id.desc())
        .limit(12)
        .all()
    )
    for entry in reversed(prev):
        if entry.role in ("user", "assistant"):
            hist.append((entry.role, entry.content))

    researcher_steers = load_fresh_researcher_steers(db, session_id, before_message_id)

    recent_run_rows = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.session_id == session_id)
        .order_by(OptimizationRun.id.desc())
        .limit(4)
        .all()
    )
    recent_runs_summary: list[dict[str, Any]] = []
    for run_row in reversed(recent_run_rows):
        entry: dict[str, Any] = {
            "run_id": run_row.id,
            "run_number": helpers.run_number(run_row),
            "ok": run_row.ok,
            "cost": run_row.cost,
        }
        if run_row.result_json:
            try:
                result_data = json.loads(run_row.result_json)
                entry["violations"] = result_data.get("violations")
                entry["metrics"] = result_data.get("metrics")
                entry["algorithm"] = result_data.get("algorithm")
            except json.JSONDecodeError:
                pass
        recent_runs_summary.append(entry)
    return hist, researcher_steers, recent_runs_summary
