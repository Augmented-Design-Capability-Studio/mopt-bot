"""Durable, external backups of the researcher's coding labour.

The coding (change-tags, notes, pauses, video-alignment, origin classifications)
is the irreplaceable output — the loaded session copies can always be rebuilt
from the study export. So a backup captures only the coding, as a portable JSON
file written OUTSIDE the analysis DB (a sibling ``coding_backups/`` dir), so it
survives DB corruption/loss and can be version-controlled or moved off-machine.

Auto-backups fire right before destructive actions (reset-tags, delete); the
same dump powers the manual download / restore.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.analysis import models as m
from app.analysis_db import analysis_engine

log = logging.getLogger(__name__)

BACKUP_KIND = "mopt-coding-backup"
_META_FIELDS = (
    "video_filename", "video_duration_sec", "clock_offset_sec",
    "t0_video_pos", "t0_iso", "t0_epoch",
)


def backup_dir() -> str:
    """``coding_backups/`` next to the analysis DB file (created on demand)."""
    db_path = analysis_engine.url.database
    if db_path and db_path != ":memory:":
        base = os.path.dirname(os.path.abspath(db_path))
    else:
        base = os.path.abspath(".")
    path = os.path.join(base, "coding_backups")
    os.makedirs(path, exist_ok=True)
    return path


def dump_coding(adb: Session, loaded_ids: list[str] | None = None) -> dict[str, Any]:
    """Serialize the coding for the given sessions (or all) to a plain dict."""
    query = adb.query(m.LoadedSession)
    if loaded_ids is not None:
        query = query.filter(m.LoadedSession.id.in_(loaded_ids))
    sessions: list[dict[str, Any]] = []
    for loaded in query.all():
        oc = adb.get(m.OriginClassification, loaded.id)
        sessions.append({
            "loaded_id": loaded.id,
            "source_session_id": loaded.source_session_id,
            "participant_number": loaded.participant_number,
            "coding_meta": {f: getattr(loaded, f) for f in _META_FIELDS},
            "annotations": [
                {
                    "anno_type": a.anno_type, "label": a.label, "color": a.color,
                    "text": a.text, "video_pos_sec": a.video_pos_sec, "row_ref": a.row_ref,
                }
                for a in loaded.annotations
            ],
            "pauses": [
                {"start_video_pos": p.start_video_pos, "end_video_pos": p.end_video_pos, "note": p.note}
                for p in loaded.pauses
            ],
            "origin_classification": (
                {"data_json": oc.data_json, "model": oc.model} if oc is not None else None
            ),
        })
    return {
        "kind": BACKUP_KIND,
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sessions": sessions,
    }


def _has_content(data: dict[str, Any]) -> bool:
    return any(s["annotations"] or s["pauses"] for s in data["sessions"])


def auto_backup(adb: Session, loaded_ids: list[str], reason: str) -> str | None:
    """Write a pre-action backup of the given sessions' coding. Never raises —
    a backup failure must not block the researcher's action."""
    try:
        data = dump_coding(adb, loaded_ids)
        if not _has_content(data):
            return None  # nothing worth saving
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = os.path.join(backup_dir(), f"coding-{reason}-{stamp}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        log.info("Coding auto-backup (%s) → %s", reason, path)
        return path
    except Exception as exc:  # pragma: no cover — best-effort safety net
        log.warning("Coding auto-backup (%s) failed: %s", reason, exc)
        return None


def restore_coding(adb: Session, data: dict[str, Any]) -> dict[str, int]:
    """Re-create coding from a backup onto the matching loaded sessions
    (matched by ``source_session_id``, else ``loaded_id``). Non-destructive: an
    annotation identical to an existing one (same type/row_ref/label/text/pos) is
    skipped, so restoring twice — or over partial coding — never duplicates."""
    if not isinstance(data, dict) or data.get("kind") != BACKUP_KIND:
        raise ValueError("Not a mopt coding backup file")

    restored_anns = restored_sessions = 0
    for s in data.get("sessions", []):
        loaded = None
        if s.get("source_session_id"):
            loaded = (
                adb.query(m.LoadedSession)
                .filter(m.LoadedSession.source_session_id == s["source_session_id"])
                .first()
            )
        if loaded is None and s.get("loaded_id"):
            loaded = adb.get(m.LoadedSession, s["loaded_id"])
        if loaded is None:
            continue  # session not loaded here — skip (re-import it first)
        restored_sessions += 1

        existing = {
            (a.anno_type, a.row_ref, a.label, a.text, a.video_pos_sec)
            for a in loaded.annotations
        }
        for a in s.get("annotations", []):
            key = (a.get("anno_type"), a.get("row_ref"), a.get("label"),
                   a.get("text"), a.get("video_pos_sec"))
            if key in existing:
                continue
            adb.add(m.Annotation(
                loaded_session_id=loaded.id,
                anno_type=a.get("anno_type", "code"),
                label=a.get("label"), color=a.get("color"), text=a.get("text"),
                video_pos_sec=a.get("video_pos_sec"), row_ref=a.get("row_ref"),
            ))
            existing.add(key)
            restored_anns += 1

        # Video-alignment meta: fill only where the current session lacks it.
        for f, v in (s.get("coding_meta") or {}).items():
            if v is not None and getattr(loaded, f, None) is None:
                setattr(loaded, f, v)
    adb.commit()
    return {"sessions": restored_sessions, "annotations": restored_anns}
