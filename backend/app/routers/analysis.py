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
from app.analysis.metrics import initial_prompt_word_count
from app.analysis.rows import CSV_COLUMNS, build_coding_rows
from app.analysis.survey import extract_named_metrics, normalize_pid, parse_survey_csv
from app.analysis.timeutil import iso_and_epoch, to_epoch
from app.analysis_db import get_analysis_db
from app.auth import Principal, require_researcher
from app.database import get_db
from app.models import ChatMessage, OptimizationRun, SessionSnapshot, StudySession
from app.problems import get_study_port

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


def _populate_children(
    adb: Session,
    loaded: m.LoadedSession,
    messages: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> None:
    """Insert the study-data copies (messages/runs/snapshots) for a loaded
    session. On re-import the caller clears these first; manual coding rows
    (annotations/pauses) and the video↔clock metadata are keyed on the stable
    source ids, so they are never touched here."""
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


def _upsert_one(
    adb: Session,
    *,
    source_kind: str,
    source_filename: str | None,
    session_fields: dict[str, Any],
    messages: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> tuple[m.LoadedSession, bool]:
    """Load one session, replacing an existing copy of the same source session
    in place (add-or-refresh). Returns ``(loaded, created)``.

    Re-importing refreshes only the study-data copy (the participant/workflow
    fields + messages/runs/snapshots). Manual coding — annotations, notes,
    pauses, and the video↔clock alignment — is preserved: those rows either
    live on the ``LoadedSession`` row itself (kept) or reference events by the
    stable study ``source_id`` (so replacing the message/run/snapshot copies
    keeps every annotation anchored)."""
    sid = session_fields.get("id")
    loaded: m.LoadedSession | None = None
    if sid is not None:
        loaded = (
            adb.query(m.LoadedSession)
            .filter(m.LoadedSession.source_session_id == sid)
            .first()
        )
    created = loaded is None
    if loaded is None:
        loaded = m.LoadedSession(source_session_id=sid)
        adb.add(loaded)
    else:
        # Drop the stale study-data copies; coding rows survive (see docstring).
        for child in (m.LoadedMessage, m.LoadedRun, m.LoadedSnapshot):
            adb.query(child).filter(child.loaded_session_id == loaded.id).delete(
                synchronize_session=False
            )
    loaded.participant_number = session_fields.get("participant_number")
    loaded.workflow_mode = session_fields.get("workflow_mode")
    loaded.test_problem_id = session_fields.get("test_problem_id")
    loaded.source_kind = source_kind
    loaded.source_filename = source_filename
    adb.flush()  # assign loaded.id for new rows / expose it after the delete
    _populate_children(adb, loaded, messages, runs, snapshots)
    return loaded, created


def _import_from_sqlite(
    adb: Session, data: bytes, filename: str | None
) -> list[tuple[m.LoadedSession, bool]]:
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

        out: list[tuple[m.LoadedSession, bool]] = []
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
                _upsert_one(
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


def _import_from_json(
    adb: Session, data: bytes, filename: str | None
) -> list[tuple[m.LoadedSession, bool]]:
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
        _upsert_one(
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
        results = _import_from_json(adb, data, filename)
    else:
        results = _import_from_sqlite(adb, data, filename)
    adb.commit()
    added = sum(1 for _, created in results if created)
    return {
        "loaded": [_loaded_summary(x) for x, _ in results],
        "added": added,
        "updated": len(results) - added,
    }


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
    loaded, created = _upsert_one(
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
    return {
        "loaded": [_loaded_summary(loaded)],
        "added": int(created),
        "updated": int(not created),
    }


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


@router.post("/delete-loaded")
def delete_loaded_bulk(
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    """Remove several loaded sessions at once (child rows cascade at the DB
    level via the FK ON DELETE CASCADE + PRAGMA foreign_keys=ON)."""
    ids = body.get("ids") or []
    if not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="ids must be a list")
    if not ids:
        return {"deleted": 0}
    deleted = (
        adb.query(m.LoadedSession)
        .filter(m.LoadedSession.id.in_(ids))
        .delete(synchronize_session=False)
    )
    adb.commit()
    return {"deleted": deleted}


# --------------------------------------------------------------------------- #
# Surveys + cross-session aggregate (notebook tab)
# --------------------------------------------------------------------------- #

@router.post("/surveys/upload")
async def upload_survey(
    request: Request,
    phase: str = "pre",
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    """Ingest a pre/post-task survey CSV (raw body). Replaces any prior rows for
    the same phase. Email/PII columns are dropped before storage."""
    if phase not in ("pre", "post"):
        raise HTTPException(status_code=400, detail="phase must be 'pre' or 'post'")
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    records = parse_survey_csv(data, phase)
    adb.query(m.SurveyResponse).filter(m.SurveyResponse.phase == phase).delete()
    for rec in records:
        adb.add(
            m.SurveyResponse(
                participant_id=rec["participant_id"],
                phase=phase,
                expertise_score=rec["expertise_score"],
                data_json=json.dumps(rec["data"]),
            )
        )
    adb.commit()
    return {"phase": phase, "count": len(records)}


@router.get("/surveys")
def survey_status(
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    rows = adb.query(m.SurveyResponse).all()
    by_phase: dict[str, int] = {}
    for r in rows:
        by_phase[r.phase] = by_phase.get(r.phase, 0) + 1
    return {"counts": by_phase}


@router.get("/notebook")
def get_notebook(
    name: str = "aggregate",
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    doc = adb.get(m.NotebookDoc, name)
    cells = None
    if doc and doc.cells_json:
        try:
            cells = json.loads(doc.cells_json)
        except json.JSONDecodeError:
            cells = None
    return {
        "name": name,
        "cells": cells,
        "updated_at": doc.updated_at.isoformat() if doc and doc.updated_at else None,
    }


@router.put("/notebook")
def put_notebook(
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    name = body.get("name") or "aggregate"
    cells = body.get("cells")
    if not isinstance(cells, list):
        raise HTTPException(status_code=400, detail="cells must be a list")
    doc = adb.get(m.NotebookDoc, name)
    if doc is None:
        doc = m.NotebookDoc(name=name)
        adb.add(doc)
    doc.cells_json = json.dumps(cells)
    adb.commit()
    return {"name": name, "saved": len(cells)}


@router.get("/aggregate")
def aggregate(
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    """Per-loaded-session metrics joined to survey expertise, for the plot."""
    expertise: dict[str, float] = {
        r.participant_id: r.expertise_score
        for r in adb.query(m.SurveyResponse).filter(
            m.SurveyResponse.phase == "pre", m.SurveyResponse.expertise_score.isnot(None)
        )
    }
    rows: list[dict[str, Any]] = []
    for loaded in adb.query(m.LoadedSession).all():
        pid = normalize_pid(loaded.participant_number)
        rows.append(
            {
                "loaded_id": loaded.id,
                "participant": loaded.participant_number,
                "workflow_mode": loaded.workflow_mode,
                "initial_prompt_words": initial_prompt_word_count(loaded.messages),
                "expertise_score": expertise.get(pid),
            }
        )
    return {"rows": rows, "expertise_available": bool(expertise)}


def _survey_metrics(data_json: str | None) -> dict[str, float | None]:
    """Short-named single-column metrics (confidence, est_time_minutes) for the
    notebook. Free-text (where identifying info could hide) never leaves here."""
    if not data_json:
        return {}
    try:
        row = json.loads(data_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return extract_named_metrics(row or {})


@router.get("/dataset")
def dataset(
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    """De-identified tidy tables for the in-browser (Pyodide) notebook.

    Data minimization: participant ids are the study's anonymized labels; survey
    free-text and any email/PII were already dropped at ingest, and only numeric
    survey answers are surfaced here. No researcher token is embedded.
    """
    loaded = adb.query(m.LoadedSession).all()

    _ports: dict[str, Any] = {}

    def _port(pid: str | None):
        if pid not in _ports:
            try:
                _ports[pid] = get_study_port(pid)
            except Exception:
                _ports[pid] = None
        return _ports[pid]

    def _origins(s) -> dict[str, str]:
        fn = getattr(_port(s.test_problem_id), "hard_constraint_origins", None)
        if fn is None:
            return {}
        # Reconstruct the brief per assistant TURN from message meta
        # (pre_turn_state / v2_turn_snapshot), not the sparse run/save snapshots —
        # otherwise an OQ raised and answered in chat between snapshots is missed
        # and mis-attributed to the user.
        briefs = []
        for msg in sorted(s.messages, key=lambda x: x.id):
            if not msg.meta_json:
                continue
            try:
                mj = json.loads(msg.meta_json)
            except json.JSONDecodeError:
                continue
            pre = (mj.get("pre_turn_state") or {}).get("problem_brief")
            if isinstance(pre, dict):
                briefs.append(pre)
            v2 = mj.get("v2_turn_snapshot")
            b2 = (v2 or {}).get("problem_brief") if isinstance(v2, dict) else None
            if isinstance(b2, dict):
                briefs.append(b2)
        if not briefs:  # fallback for data without per-turn meta
            for sn in sorted(s.snapshots, key=lambda x: x.id):
                if sn.problem_brief_json:
                    try:
                        briefs.append(json.loads(sn.problem_brief_json))
                    except json.JSONDecodeError:
                        pass
        try:
            return fn(briefs)
        except Exception:
            return {}

    sessions = [
        {
            "loaded_id": s.id,
            "participant": s.participant_number,
            "workflow_mode": s.workflow_mode,
            "test_problem_id": s.test_problem_id,
            "hard_origins": _origins(s),
        }
        for s in loaded
    ]
    messages = [
        {
            "loaded_id": msg.loaded_session_id,
            "source_id": msg.source_id,
            "ts_epoch": msg.ts_epoch,
            "role": msg.role,
            "kind": msg.kind,
            "content": msg.content,
        }
        for s in loaded
        for msg in s.messages
    ]
    # Canonical (official) re-scoring of each run's schedule — comparable across
    # users regardless of their chosen weights. Routed through the problem port
    # so the main backend stays problem-agnostic (port hook is optional).
    _EMPTY_CANON = {
        "canonical_cost": None, "canonical_cost_std": None, "feasible": None,
        "feasible_frac": None, "lateness_min": None, "capacity_overflow": None,
        "shift_over_8h": None, "all_orders_covered": None,
    }

    def _canon(pid: str | None, result_json: str | None) -> dict[str, Any]:
        if pid not in _ports:
            try:
                _ports[pid] = get_study_port(pid)
            except Exception:
                _ports[pid] = None
        port = _ports[pid]
        fn = getattr(port, "canonical_evaluation_for_result", None)
        if fn is None or not result_json:
            return _EMPTY_CANON
        try:
            return fn(json.loads(result_json)) or _EMPTY_CANON
        except Exception:
            return _EMPTY_CANON

    runs = [
        {
            "loaded_id": r.loaded_session_id,
            "source_id": r.source_id,
            "session_run_index": r.session_run_index,
            "ts_epoch": r.ts_epoch,
            "run_type": r.run_type,
            "cost": r.cost,
            "reference_cost": r.reference_cost,
            "ok": r.ok,
            **_canon(s.test_problem_id, r.result_json),
        }
        for s in loaded
        for r in s.runs
    ]
    annotations = [
        {
            "loaded_id": a.loaded_session_id,
            "anno_type": a.anno_type,
            "label": a.label,
            "video_pos_sec": a.video_pos_sec,
            "row_ref": a.row_ref,
        }
        for s in loaded
        for a in s.annotations
    ]
    # Snapshot event timing/type + derived formulation-quality scores (NOT the
    # raw brief/panel JSON) — lets the notebook chart formulation over time.
    def _form(pid: str | None, panel_json: str | None) -> dict[str, Any]:
        if pid not in _ports:
            try:
                _ports[pid] = get_study_port(pid)
            except Exception:
                _ports[pid] = None
        fn = getattr(_ports.get(pid), "formulation_quality_for_config", None)
        if fn is None or not panel_json:
            return {}
        try:
            r = fn(json.loads(panel_json)) or {}
        except Exception:
            return {}
        return {
            "coverage": r.get("coverage"),
            "hard_bonus": r.get("hard_bonus"),
            "objective_present": r.get("objective_present"),
            "objective_bonus": r.get("objective_bonus"),
            "soft_covered": r.get("soft_covered"),
            # descriptive, NOT scored:
            "objective_as_hard": r.get("objective_as_hard"),
            "soft_as_hard": r.get("soft_as_hard"),
            "n_custom_hard": r.get("n_custom_hard"),
            "formulation_score": r.get("formulation_score"),
        }

    # Goal-term edit counts per snapshot (weight / type / rank / add-remove),
    # by diffing each snapshot's goal_terms against the previous one. Structural
    # (no text parsing); captures the participant's tradeoff-balancing activity.
    def _goal_terms(panel_json: str | None) -> dict:
        try:
            p = json.loads(panel_json or "{}")
        except json.JSONDecodeError:
            return {}
        prob = p.get("problem") or p
        return prob.get("goal_terms") or {}

    def _rank_order(terms: dict, keys) -> list:
        return sorted(
            keys,
            key=lambda k: (
                terms[k].get("rank") if isinstance(terms[k], dict) and terms[k].get("rank") is not None else 10**9,
                k,
            ),
        )

    edit_by_snap: dict[int, dict[str, int]] = {}
    for s in loaded:
        prev = None
        for sn in sorted(s.snapshots, key=lambda x: x.id):
            g = _goal_terms(sn.panel_config_json)
            we = te = reranked = added = removed = 0
            if prev is not None:
                common = set(prev) & set(g)
                for k in common:  # weight/type edits: per-term, only on terms that persisted
                    a, b = prev[k], g[k]
                    if isinstance(a, dict) and isinstance(b, dict):
                        we += a.get("weight") != b.get("weight")
                        te += a.get("type") != b.get("type")
                # A genuine RE-RANK = the relative order of the *common* terms changed
                # (excludes the renumbering cascade caused by add/remove).
                reranked = int(_rank_order(prev, common) != _rank_order(g, common))
                added = len(set(g) - set(prev))
                removed = len(set(prev) - set(g))
            edit_by_snap[sn.id] = {
                "weight_edits": we, "type_edits": te, "reranked": reranked,
                "terms_added": added, "terms_removed": removed,
            }
            prev = g

    snapshots = [
        {
            "loaded_id": sn.loaded_session_id,
            "source_id": sn.source_id,
            "ts_epoch": sn.ts_epoch,
            "event_type": sn.event_type,
            **edit_by_snap.get(sn.id, {}),
            **_form(s.test_problem_id, sn.panel_config_json),
        }
        for s in loaded
        for sn in s.snapshots
    ]
    surveys = [
        {
            "participant_id": sv.participant_id,
            "phase": sv.phase,
            "expertise_score": sv.expertise_score,
            **_survey_metrics(sv.data_json),
        }
        for sv in adb.query(m.SurveyResponse).all()
    ]
    return {
        "sessions": sessions,
        "messages": messages,
        "runs": runs,
        "annotations": annotations,
        "snapshots": snapshots,
        "surveys": surveys,
    }


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
