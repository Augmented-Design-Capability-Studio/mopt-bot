"""Session-coding analysis API.

Loads study sessions (from an uploaded export ``.db``/JSON, or the live study DB)
into the separate analysis DB as durable, self-contained copies, then serves the
merged event timeline and the manual coding CRUD (annotations, notes, pauses,
video↔DB clock metadata) plus a CSV export. The study DB is only ever read.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.analysis import models as m
from app.analysis.rows import CSV_COLUMNS, build_coding_rows
from app.analysis.timeutil import iso_and_epoch, to_epoch
from app.analysis_db import get_analysis_db
from app.auth import Principal, require_researcher
from app.database import get_db
from app.models import ChatMessage, OptimizationRun, SessionSnapshot, StudySession

router = APIRouter(prefix="/analysis", tags=["analysis"])


# --------------------------------------------------------------------------- #
# Import helpers
# --------------------------------------------------------------------------- #

def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        val = row[key]
    except (KeyError, IndexError):
        return default
    return val if val is not None else default


def _import_one(
    adb: Session,
    *,
    source_kind: str,
    source_filename: str | None,
    session_fields: dict[str, Any],
    messages: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> m.LoadedSession:
    loaded = m.LoadedSession(
        source_session_id=session_fields.get("id"),
        participant_number=session_fields.get("participant_number"),
        workflow_mode=session_fields.get("workflow_mode"),
        test_problem_id=session_fields.get("test_problem_id"),
        source_kind=source_kind,
        source_filename=source_filename,
    )
    adb.add(loaded)
    adb.flush()  # assign loaded.id

    for msg in messages:
        iso, epoch = iso_and_epoch(msg.get("created_at"))
        adb.add(
            m.LoadedMessage(
                loaded_session_id=loaded.id,
                source_id=msg.get("id"),
                ts_iso=iso,
                ts_epoch=epoch,
                role=msg.get("role"),
                content=msg.get("content"),
                kind=msg.get("kind"),
                visible_to_participant=msg.get("visible_to_participant"),
                meta_json=msg.get("meta_json"),
            )
        )
    for run in runs:
        iso, epoch = iso_and_epoch(run.get("created_at"))
        adb.add(
            m.LoadedRun(
                loaded_session_id=loaded.id,
                source_id=run.get("id"),
                session_run_index=run.get("session_run_index"),
                ts_iso=iso,
                ts_epoch=epoch,
                run_type=run.get("run_type"),
                request_json=run.get("request_json"),
                result_json=run.get("result_json"),
                cost=run.get("cost"),
                reference_cost=run.get("reference_cost"),
                ok=run.get("ok"),
                error_message=run.get("error_message"),
            )
        )
    for snap in snapshots:
        iso, epoch = iso_and_epoch(snap.get("created_at"))
        adb.add(
            m.LoadedSnapshot(
                loaded_session_id=loaded.id,
                source_id=snap.get("id"),
                ts_iso=iso,
                ts_epoch=epoch,
                event_type=snap.get("event_type"),
                problem_brief_json=snap.get("problem_brief_json"),
                panel_config_json=snap.get("panel_config_json"),
            )
        )
    return loaded


def _import_from_sqlite(adb: Session, data: bytes, filename: str | None) -> list[m.LoadedSession]:
    fd, path = tempfile.mkstemp(prefix="mopt-analysis-src-", suffix=".db")
    os.close(fd)
    try:
        with open(path, "wb") as fh:
            fh.write(data)
        src = sqlite3.connect(path)
        src.row_factory = sqlite3.Row
        try:
            session_rows = src.execute("SELECT * FROM sessions").fetchall()
        except sqlite3.Error as exc:
            raise HTTPException(status_code=400, detail=f"Not a study .db: {exc}") from exc

        out: list[m.LoadedSession] = []
        for srow in session_rows:
            sid = _row_get(srow, "id")
            msgs = [
                dict(r) for r in src.execute(
                    "SELECT * FROM messages WHERE session_id=? ORDER BY id ASC", (sid,)
                ).fetchall()
            ]
            runs = [
                dict(r) for r in src.execute(
                    "SELECT * FROM runs WHERE session_id=? ORDER BY id ASC", (sid,)
                ).fetchall()
            ]
            snaps = [
                dict(r) for r in src.execute(
                    "SELECT * FROM session_snapshots WHERE session_id=? ORDER BY id ASC", (sid,)
                ).fetchall()
            ]
            out.append(
                _import_one(
                    adb,
                    source_kind="db",
                    source_filename=filename,
                    session_fields=dict(srow),
                    messages=msgs,
                    runs=runs,
                    snapshots=snaps,
                )
            )
        return out
    finally:
        src_close = locals().get("src")
        if src_close is not None:
            src_close.close()
        try:
            os.unlink(path)
        except OSError:
            pass


def _import_from_json(adb: Session, data: bytes, filename: str | None) -> list[m.LoadedSession]:
    try:
        env = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON export: {exc}") from exc
    if not isinstance(env, dict) or "session" not in env:
        raise HTTPException(status_code=400, detail="JSON is not a session export envelope")

    sess = env.get("session") or {}
    msgs = [
        {**msg, "meta_json": json.dumps(msg["meta"]) if msg.get("meta") is not None else None}
        for msg in (env.get("messages") or [])
    ]
    runs = [
        {
            **run,
            "request_json": json.dumps(run["request"]) if run.get("request") is not None else None,
            "result_json": json.dumps(run["result"]) if run.get("result") is not None else None,
        }
        for run in (env.get("runs") or [])
    ]
    snaps = [
        {
            **snap,
            "problem_brief_json": json.dumps(snap["problem_brief"])
            if snap.get("problem_brief") is not None else None,
            "panel_config_json": json.dumps(snap["panel_config"])
            if snap.get("panel_config") is not None else None,
        }
        for snap in (env.get("snapshots") or [])
    ]
    return [
        _import_one(
            adb,
            source_kind="json",
            source_filename=filename,
            session_fields=sess,
            messages=msgs,
            runs=runs,
            snapshots=snaps,
        )
    ]


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #

def _loaded_summary(loaded: m.LoadedSession) -> dict[str, Any]:
    return {
        "id": loaded.id,
        "source_session_id": loaded.source_session_id,
        "participant_number": loaded.participant_number,
        "workflow_mode": loaded.workflow_mode,
        "test_problem_id": loaded.test_problem_id,
        "source_kind": loaded.source_kind,
        "source_filename": loaded.source_filename,
        "loaded_at": loaded.loaded_at.isoformat() if loaded.loaded_at else None,
        "video_filename": loaded.video_filename,
        "video_duration_sec": loaded.video_duration_sec,
        "clock_offset_sec": loaded.clock_offset_sec,
        "t0_video_pos": loaded.t0_video_pos,
        "t0_iso": loaded.t0_iso,
        "counts": {
            "messages": len(loaded.messages),
            "runs": len(loaded.runs),
            "snapshots": len(loaded.snapshots),
            "annotations": len(loaded.annotations),
            "pauses": len(loaded.pauses),
        },
    }


def _annotation_out(a: m.Annotation) -> dict[str, Any]:
    return {
        "id": a.id,
        "anno_type": a.anno_type,
        "label": a.label,
        "color": a.color,
        "text": a.text,
        "video_pos_sec": a.video_pos_sec,
        "row_ref": a.row_ref,
    }


def _pause_out(p: m.Pause) -> dict[str, Any]:
    return {
        "id": p.id,
        "start_video_pos": p.start_video_pos,
        "end_video_pos": p.end_video_pos,
        "note": p.note,
    }


def _get_loaded(adb: Session, loaded_id: str) -> m.LoadedSession:
    loaded = adb.get(m.LoadedSession, loaded_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="Loaded session not found")
    return loaded


def _recompute_t0(loaded: m.LoadedSession) -> None:
    """Derive t0 epoch/iso from t0_video_pos + clock offset (re-run whenever
    either changes so a re-anchor keeps t0 consistent)."""
    if loaded.t0_video_pos is not None and loaded.clock_offset_sec is not None:
        loaded.t0_epoch = loaded.t0_video_pos + loaded.clock_offset_sec
        loaded.t0_iso = datetime.fromtimestamp(loaded.t0_epoch, tz=timezone.utc).isoformat()
    else:
        loaded.t0_epoch = None
        loaded.t0_iso = None


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@router.post("/upload")
async def upload_session(
    request: Request,
    filename: str | None = None,
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    """Load one or more sessions from a raw uploaded export ``.db`` or JSON body.

    The file bytes are the request body (application/octet-stream); the original
    name is passed as the ``filename`` query param. Raw body (not multipart) so
    the backend needs no ``python-multipart`` dependency.
    """
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    name = (filename or "").lower()
    stripped = data.lstrip()
    is_json = name.endswith(".json") or stripped[:1] in (b"{", b"[")
    if is_json:
        loaded = _import_from_json(adb, data, filename)
    else:
        loaded = _import_from_sqlite(adb, data, filename)
    adb.commit()
    return {"loaded": [_loaded_summary(x) for x in loaded]}


@router.post("/load-live")
def load_live_session(
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    """Load a session directly from the live study DB by id (convenience path)."""
    sid = body.get("source_session_id")
    if not sid:
        raise HTTPException(status_code=400, detail="source_session_id is required")
    row = db.get(StudySession, sid)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found in study DB")
    msgs = [
        {
            "id": x.id, "created_at": x.created_at, "role": x.role, "content": x.content,
            "kind": x.kind, "visible_to_participant": x.visible_to_participant,
            "meta_json": x.meta_json,
        }
        for x in db.query(ChatMessage).filter(ChatMessage.session_id == sid).order_by(ChatMessage.id).all()
    ]
    runs = [
        {
            "id": x.id, "created_at": x.created_at, "session_run_index": x.session_run_index,
            "run_type": x.run_type, "request_json": x.request_json, "result_json": x.result_json,
            "cost": x.cost, "reference_cost": x.reference_cost, "ok": x.ok,
            "error_message": x.error_message,
        }
        for x in db.query(OptimizationRun).filter(OptimizationRun.session_id == sid).order_by(OptimizationRun.id).all()
    ]
    snaps = [
        {
            "id": x.id, "created_at": x.created_at, "event_type": x.event_type,
            "problem_brief_json": x.problem_brief_json, "panel_config_json": x.panel_config_json,
        }
        for x in db.query(SessionSnapshot).filter(SessionSnapshot.session_id == sid).order_by(SessionSnapshot.id).all()
    ]
    loaded = _import_one(
        adb,
        source_kind="live",
        source_filename=None,
        session_fields={
            "id": row.id, "participant_number": row.participant_number,
            "workflow_mode": row.workflow_mode, "test_problem_id": row.test_problem_id,
        },
        messages=msgs, runs=runs, snapshots=snaps,
    )
    adb.commit()
    return {"loaded": [_loaded_summary(loaded)]}


@router.get("/loaded")
def list_loaded(
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    rows = adb.query(m.LoadedSession).order_by(m.LoadedSession.loaded_at.desc()).all()
    return {"loaded": [_loaded_summary(x) for x in rows]}


@router.get("/loaded/{loaded_id}")
def get_loaded(
    loaded_id: str,
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    loaded = _get_loaded(adb, loaded_id)
    return {
        "session": _loaded_summary(loaded),
        "annotations": [_annotation_out(a) for a in loaded.annotations],
        "pauses": [_pause_out(p) for p in loaded.pauses],
        "timeline": build_coding_rows(
            loaded, loaded.messages, loaded.runs, loaded.snapshots,
            loaded.annotations, loaded.pauses,
        ),
    }


@router.get("/loaded/{loaded_id}/timeline")
def get_timeline(
    loaded_id: str,
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    loaded = _get_loaded(adb, loaded_id)
    return {
        "session": _loaded_summary(loaded),
        "annotations": [_annotation_out(a) for a in loaded.annotations],
        "pauses": [_pause_out(p) for p in loaded.pauses],
        "timeline": build_coding_rows(
            loaded, loaded.messages, loaded.runs, loaded.snapshots,
            loaded.annotations, loaded.pauses,
        ),
    }


_META_FIELDS = {"video_filename", "video_duration_sec", "clock_offset_sec", "t0_video_pos"}


@router.patch("/loaded/{loaded_id}/coding-meta")
def patch_coding_meta(
    loaded_id: str,
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    loaded = _get_loaded(adb, loaded_id)
    for field in _META_FIELDS:
        if field in body:
            setattr(loaded, field, body[field])
    # t0_iso may be provided explicitly (HH:MM cross-check); otherwise derived.
    if body.get("t0_iso"):
        loaded.t0_iso = body["t0_iso"]
        loaded.t0_epoch = to_epoch(body["t0_iso"])
    else:
        _recompute_t0(loaded)
    adb.commit()
    return {"session": _loaded_summary(loaded)}


@router.post("/loaded/{loaded_id}/annotations")
def create_annotation(
    loaded_id: str,
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    loaded = _get_loaded(adb, loaded_id)
    anno = m.Annotation(
        loaded_session_id=loaded.id,
        anno_type=body.get("anno_type", "code"),
        label=body.get("label"),
        color=body.get("color"),
        text=body.get("text"),
        video_pos_sec=body.get("video_pos_sec"),
        row_ref=body.get("row_ref"),
    )
    adb.add(anno)
    adb.commit()
    return _annotation_out(anno)


@router.patch("/loaded/{loaded_id}/annotations/{anno_id}")
def update_annotation(
    loaded_id: str,
    anno_id: int,
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    anno = adb.get(m.Annotation, anno_id)
    if anno is None or anno.loaded_session_id != loaded_id:
        raise HTTPException(status_code=404, detail="Annotation not found")
    for field in ("anno_type", "label", "color", "text", "video_pos_sec", "row_ref"):
        if field in body:
            setattr(anno, field, body[field])
    adb.commit()
    return _annotation_out(anno)


@router.delete("/loaded/{loaded_id}/annotations/{anno_id}", status_code=204)
def delete_annotation(
    loaded_id: str,
    anno_id: int,
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    anno = adb.get(m.Annotation, anno_id)
    if anno is not None and anno.loaded_session_id == loaded_id:
        adb.delete(anno)
        adb.commit()


@router.post("/loaded/{loaded_id}/pauses")
def create_pause(
    loaded_id: str,
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    loaded = _get_loaded(adb, loaded_id)
    if body.get("start_video_pos") is None:
        raise HTTPException(status_code=400, detail="start_video_pos is required")
    pause = m.Pause(
        loaded_session_id=loaded.id,
        start_video_pos=body["start_video_pos"],
        end_video_pos=body.get("end_video_pos"),
        note=body.get("note"),
    )
    adb.add(pause)
    adb.commit()
    return _pause_out(pause)


@router.delete("/loaded/{loaded_id}/pauses/{pause_id}", status_code=204)
def delete_pause(
    loaded_id: str,
    pause_id: int,
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    pause = adb.get(m.Pause, pause_id)
    if pause is not None and pause.loaded_session_id == loaded_id:
        adb.delete(pause)
        adb.commit()


@router.delete("/loaded/{loaded_id}", status_code=204)
def delete_loaded(
    loaded_id: str,
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    loaded = adb.get(m.LoadedSession, loaded_id)
    if loaded is not None:
        adb.delete(loaded)
        adb.commit()


@router.get("/loaded/{loaded_id}/export.csv")
def export_csv(
    loaded_id: str,
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    loaded = _get_loaded(adb, loaded_id)
    rows = build_coding_rows(
        loaded, loaded.messages, loaded.runs, loaded.snapshots,
        loaded.annotations, loaded.pauses,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(["" if row.get(c) is None else row.get(c) for c in CSV_COLUMNS])
    label = loaded.participant_number or loaded.source_session_id or loaded.id
    filename = f"coding-{label}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
