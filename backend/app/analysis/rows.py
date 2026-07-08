"""Merge DB events + manual annotations into one timestamp-ordered row stream.

Single source of truth for both the ``/timeline`` endpoint and the CSV export,
so the on-screen list and the exported file never drift. Time math (video
position, pause-aware "time since start") is derived here from the loaded
session's stored coding metadata (clock offset, t0, pauses).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.analysis.diffing import compute_definition_config_changes

# Tie-break for events sharing a timestamp (a before_run snapshot and its run
# land within microseconds): message < snapshot < run < manual annotation.
_KIND_ORDER = {"message": 0, "snapshot": 1, "run": 2, "marker": 3, "code": 3, "note": 3}

CSV_COLUMNS = [
    "timestamp_iso",
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
    "color",
    "note",
]


def _epoch_to_iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


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
    for a in annotations:
        if a.row_ref and a.anno_type == "note":
            attached_notes.setdefault(a.row_ref, []).append(a.text or "")

    diff_map = compute_definition_config_changes(snapshots)

    rows: list[dict[str, Any]] = []

    def add(kind: str, epoch: float | None, sort_id: int, **extra: Any) -> None:
        adj, raw = times(epoch)
        row: dict[str, Any] = {
            "kind": kind,
            "timestamp_iso": _epoch_to_iso(epoch) if epoch is not None else None,
            "epoch": epoch,
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
            "color": None,
            "note": None,
            "annotation_id": None,
            "row_ref": None,
        }
        row.update(extra)
        row["_sort"] = (epoch if epoch is not None else 0.0, _KIND_ORDER.get(kind, 5), sort_id)
        rows.append(row)

    for m in messages:
        ref = f"message:{m.source_id}"
        add(
            "message",
            m.ts_epoch,
            m.source_id or m.id,
            role=m.role,
            label=f"{m.role}/{m.kind}",
            summary=m.content or "",
            note=" | ".join(attached_notes.get(ref, [])) or None,
            row_ref=ref,
        )

    for r in runs:
        ref = f"run:{r.source_id}"
        add(
            "run",
            r.ts_epoch,
            r.source_id or r.id,
            label=r.run_type,
            summary=f"ok={r.ok} cost={r.cost}",
            latest_run=r.result_json,
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
            note=" | ".join(attached_notes.get(ref, [])) or None,
            row_ref=ref,
        )

    # Synthetic marker for the canonical start.
    if loaded.t0_epoch is not None:
        add("marker", loaded.t0_epoch, -1, label="first keystroke (t0)", color="#16a34a")

    # Standalone annotations (codes, markers like "ready", free notes at a time).
    for a in annotations:
        if a.row_ref and a.anno_type == "note":
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
