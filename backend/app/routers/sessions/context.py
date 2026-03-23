"""Turn context loading for chat."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import ChatMessage, OptimizationRun

from . import helpers


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

    steer_rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "researcher",
            ChatMessage.visible_to_participant.is_(False),
            ChatMessage.id < before_message_id,
        )
        .order_by(ChatMessage.id.desc())
        .limit(4)
        .all()
    )
    researcher_steers = [message.content for message in reversed(steer_rows)]

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
