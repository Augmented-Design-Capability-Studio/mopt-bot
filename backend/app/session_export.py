"""Versioned session archive helpers (researcher export)."""

from __future__ import annotations

from typing import Any, Callable

from app.models import ChatMessage, OptimizationRun, SessionSnapshot
from app.schemas import serialize_utc_datetime

# Bump when the archive envelope gains breaking changes; analyzers should tolerate unknown keys.
EXPORT_SCHEMA_VERSION = 2

_KIND_ORDER = {"message": 0, "snapshot": 1, "run": 2}


def _trunc(text: str, max_len: int = 160) -> str:
    s = text.replace("\n", " ").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def build_export_timeline(
    messages: list[ChatMessage],
    runs: list[OptimizationRun],
    snapshots: list[SessionSnapshot],
    *,
    run_number: Callable[[OptimizationRun], int],
) -> list[dict[str, Any]]:
    """Single sorted stream of session events for spreadsheet-style review tools."""
    keyed: list[tuple[tuple, dict[str, Any]]] = []

    for m in messages:
        at = m.created_at
        row = {
            "kind": "message",
            "at": serialize_utc_datetime(at),
            "ref": {"message_id": m.id},
            "label": f"{m.role}/{m.kind}",
            "payload_summary": _trunc(m.content or ""),
        }
        keyed.append(((at, _KIND_ORDER["message"], m.id), row))

    for snap in snapshots:
        at = snap.created_at
        has_brief = bool(snap.problem_brief_json and snap.problem_brief_json.strip())
        has_panel = bool(snap.panel_config_json and snap.panel_config_json.strip())
        row = {
            "kind": "snapshot",
            "at": serialize_utc_datetime(at),
            "ref": {"snapshot_id": snap.id},
            "label": snap.event_type,
            "payload_summary": f"brief={'yes' if has_brief else 'no'} panel={'yes' if has_panel else 'no'}",
        }
        keyed.append(((at, _KIND_ORDER["snapshot"], snap.id), row))

    for r in runs:
        at = r.created_at
        rn = run_number(r)
        row = {
            "kind": "run",
            "at": serialize_utc_datetime(at),
            "ref": {"run_id": r.id, "run_number": rn},
            "label": r.run_type,
            "payload_summary": f"ok={r.ok} cost={r.cost}",
        }
        keyed.append(((at, _KIND_ORDER["run"], r.id), row))

    keyed.sort(key=lambda item: item[0])
    return [row for _, row in keyed]
