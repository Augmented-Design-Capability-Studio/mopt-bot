"""Merge DB events + manual annotations into one timestamp-ordered row stream.

Single source of truth for both the ``/timeline`` endpoint and the CSV export,
so the on-screen list and the exported file never drift. Time math (video
position, pause-aware "time since start") is derived here from the loaded
session's stored coding metadata (clock offset, t0, pauses).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.analysis.diffing import compute_definition_config_changes

# Tie-break for events sharing a timestamp (a before_run snapshot and its run
# land within microseconds): message < snapshot < run < manual annotation.
_KIND_ORDER = {"message": 0, "snapshot": 1, "run": 2, "marker": 3, "code": 3, "note": 3}

CSV_COLUMNS = [
    "timestamp_iso",
    "t_rel",
    "time_since_start",
    "time_since_start_raw",
    "video_pos",
    "event_type",
    "role",
    "label",
    "summary",
    "definition_change",
    "config_change",
    "latest_run",
    "changes",
    "color",
    "note",
]

# The coded-change fields, in the order used to render a change in the CSV cell.
CHANGE_FIELDS = ("origin", "type", "term", "effect")


def _epoch_to_iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _message_state(meta_json: str | None) -> tuple[str | None, str | None]:
    """The full problem def (brief) + config (panel) as of a chat turn, pulled
    from the assistant message's ``meta.pre_turn_state`` — the state the model
    saw that turn. Returns pretty-printed JSON strings (or None if absent)."""
    if not meta_json:
        return None, None
    try:
        meta = json.loads(meta_json)
    except (json.JSONDecodeError, TypeError):
        return None, None
    pre = meta.get("pre_turn_state") if isinstance(meta, dict) else None
    if not isinstance(pre, dict):
        return None, None
    brief = pre.get("problem_brief")
    panel = pre.get("panel_config")
    def_json = json.dumps(brief, indent=2, ensure_ascii=False) if isinstance(brief, dict) else None
    cfg_json = json.dumps(panel, indent=2, ensure_ascii=False) if isinstance(panel, dict) else None
    return def_json, cfg_json


def _parse_change(text: str | None, label: str | None) -> dict[str, Any]:
    """A coded change is stored as a JSON object in the annotation ``text``:
    ``{origin, type, term, effect}`` (any field may be null). Falls back to a
    legacy ``"<facet>:<value>"`` label so older single-facet tags still render."""
    if text:
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            obj = None
        if isinstance(obj, dict):
            return {f: obj.get(f) for f in CHANGE_FIELDS}
    out: dict[str, Any] = {f: None for f in CHANGE_FIELDS}
    if label:
        idx = label.find(":")
        facet, value = (label[:idx], label[idx + 1 :]) if idx >= 0 else (None, label)
        if facet == "term":
            out["term"] = value
        elif facet in ("origin", "type", "effect"):
            out[facet] = value
        elif value:
            out["type"] = value
    return out


def _pause_intervals(loaded: Any, pauses: list[Any]) -> list[tuple[float, float]]:
    """Completed pauses as (start_epoch, end_epoch); needs the clock offset."""
    offset = loaded.clock_offset_sec
    if offset is None:
        return []
    out: list[tuple[float, float]] = []
    for p in pauses:
        if p.end_video_pos is None:
            continue
        start = p.start_video_pos + offset
        end = p.end_video_pos + offset
        if end > start:
            out.append((start, end))
    return out


def build_coding_rows(
    loaded: Any,
    messages: list[Any],
    runs: list[Any],
    snapshots: list[Any],
    annotations: list[Any],
    pauses: list[Any],
) -> list[dict[str, Any]]:
    offset = loaded.clock_offset_sec
    t0 = loaded.t0_epoch
    intervals = _pause_intervals(loaded, pauses)

    # Video-independent elapsed time: the first message is the zero point, so the
    # log can be coded on wall-clock alone (no video anchoring required).
    msg_epochs = [msg.ts_epoch for msg in messages if msg.ts_epoch is not None]
    t0_first = min(msg_epochs) if msg_epochs else None

    def t_rel(epoch: float | None) -> float | None:
        if epoch is None or t0_first is None:
            return None
        return round(epoch - t0_first, 2)

    def video_pos(epoch: float | None) -> float | None:
        if epoch is None or offset is None:
            return None
        return round(epoch - offset, 3)

    def times(epoch: float | None) -> tuple[float | None, float | None]:
        """(pause-adjusted, raw) seconds since t0."""
        if epoch is None or t0 is None:
            return None, None
        raw = epoch - t0
        paused = 0.0
        for start, end in intervals:
            lo = max(t0, start)
            hi = min(epoch, end)
            if hi > lo:
                paused += hi - lo
        return round(raw - paused, 2), round(raw, 2)

    # Notes attached to a DB row don't get their own row — collect by row_ref.
    attached_notes: dict[str, list[str]] = {}
    # Coded changes attached to a DB row are folded into that row's "changes"
    # list instead of becoming a standalone row, so a row can carry many changes.
    attached_changes: dict[str, list[dict[str, Any]]] = {}
    for a in annotations:
        if not a.row_ref:
            continue
        if a.anno_type == "note":
            attached_notes.setdefault(a.row_ref, []).append(a.text or "")
        elif a.anno_type == "code":
            attached_changes.setdefault(a.row_ref, []).append(
                {"id": a.id, **_parse_change(a.text, a.label)}
            )

    diff_map = compute_definition_config_changes(snapshots)

    rows: list[dict[str, Any]] = []

    def add(kind: str, epoch: float | None, sort_id: int, **extra: Any) -> None:
        adj, raw = times(epoch)
        row: dict[str, Any] = {
            "kind": kind,
            "timestamp_iso": _epoch_to_iso(epoch) if epoch is not None else None,
            "epoch": epoch,
            "t_rel": t_rel(epoch),
            "time_since_start": adj,
            "time_since_start_raw": raw,
            "video_pos": video_pos(epoch),
            "event_type": kind,
            "role": None,
            "label": None,
            "summary": None,
            "definition_change": None,
            "config_change": None,
            "latest_run": None,
            # Full problem def + config as of this row's turn (message rows only).
            "problem_def": None,
            "problem_config": None,
            # The user turn(s) that prompted this row, folded in so a row reads as
            # a full exchange (agent-response rows only).
            "user_prompt": None,
            # Whether this row is a coding target (agent chat responses + manual
            # panel saves). The chat is instant, so we code the agent's turn.
            "codeable": False,
            # Manual coded changes on this row: [{id, origin, type, term, effect}].
            "changes": [],
            # Deterministic change suggestions + captured terms, filled per row by
            # the timeline endpoint (see coding_suggestions); empty elsewhere.
            "suggested_changes": [],
            "captured_terms": [],
            "color": None,
            "note": None,
            "annotation_id": None,
            "row_ref": None,
        }
        row.update(extra)
        row["_sort"] = (epoch if epoch is not None else 0.0, _KIND_ORDER.get(kind, 5), sort_id)
        rows.append(row)

    # Fold each user chat message into the agent chat response that follows it,
    # so a row reads as one exchange (user prompt + agent reply). Coding targets
    # the agent's turn. Trailing user messages with no reply still get a row.
    def _emit_message(m: Any, *, user_prompt: str | None, codeable: bool) -> None:
        ref = f"message:{m.source_id}"
        def_json, cfg_json = _message_state(getattr(m, "meta_json", None))
        add(
            "message",
            m.ts_epoch,
            m.source_id or m.id,
            role=m.role,
            label=f"{m.role}/{m.kind}",
            summary=m.content or "",
            problem_def=def_json,
            problem_config=cfg_json,
            user_prompt=user_prompt,
            codeable=codeable,
            changes=attached_changes.get(ref, []),
            note=" | ".join(attached_notes.get(ref, [])) or None,
            row_ref=ref,
        )

    pending_user: list[Any] = []
    for m in messages:
        if m.role == "user" and (m.kind or "") == "chat":
            pending_user.append(m)
            continue
        is_assistant_chat = m.role == "assistant" and (m.kind or "") == "chat"
        prompt = None
        if is_assistant_chat and pending_user:
            prompt = "\n\n".join(um.content or "" for um in pending_user).strip() or None
            pending_user = []
        _emit_message(m, user_prompt=prompt, codeable=is_assistant_chat)
    for um in pending_user:  # user turns with no following agent reply
        _emit_message(um, user_prompt=None, codeable=False)

    for r in runs:
        ref = f"run:{r.source_id}"
        add(
            "run",
            r.ts_epoch,
            r.source_id or r.id,
            label=r.run_type,
            summary=f"ok={r.ok} cost={r.cost}",
            latest_run=r.result_json,
            changes=attached_changes.get(ref, []),
            note=" | ".join(attached_notes.get(ref, [])) or None,
            row_ref=ref,
        )

    for s in snapshots:
        entry = diff_map.get(s.id)
        if not entry:
            continue  # unchanged snapshot → no row (change-only columns)
        ref = f"snapshot:{s.source_id}"
        add(
            "snapshot",
            s.ts_epoch,
            s.source_id or s.id,
            label=s.event_type,
            definition_change=entry.get("definition_change"),
            config_change=entry.get("config_change"),
            # Snapshots are reference-only — a manual save is already reflected by
            # the "Definition edited" user message that flows into an exchange, so
            # coding here would double-count. Only agent responses are codeable.
            changes=attached_changes.get(ref, []),
            note=" | ".join(attached_notes.get(ref, [])) or None,
            row_ref=ref,
        )

    # Synthetic marker for the canonical start.
    if loaded.t0_epoch is not None:
        add("marker", loaded.t0_epoch, -1, label="first keystroke (t0)", color="#16a34a")

    # Standalone annotations (codes, markers like "ready", free notes at a time).
    for a in annotations:
        if a.row_ref and a.anno_type in ("note", "code"):
            continue  # already folded into its row
        if a.video_pos_sec is None or offset is None:
            epoch = None
        else:
            epoch = a.video_pos_sec + offset
        add(
            a.anno_type,
            epoch,
            10_000_000 + a.id,
            label=a.label,
            color=a.color,
            note=a.text,
            summary=a.label,
            annotation_id=a.id,
            # annotations carry their own video_pos even before an epoch exists
            video_pos=a.video_pos_sec if a.video_pos_sec is not None else None,
        )

    rows.sort(key=lambda x: x["_sort"])
    for row in rows:
        row.pop("_sort", None)
    return rows
