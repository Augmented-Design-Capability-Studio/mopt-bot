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
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.analysis import models as m
from app.analysis.backup import auto_backup, dump_coding, restore_coding
from app.analysis.coding_llm import tag_session_changes
from app.analysis.coding_suggestions import build_turn_derivations, goal_term_keys
from app.analysis.reason_llm import reasons_from_diffs, render_run_evidence, verify_reasons
from app.analysis.metrics import initial_prompt_word_count
from app.analysis.rows import CHANGE_FIELDS, CSV_COLUMNS, _parse_change, build_coding_rows
from app.analysis.survey import (
    experience_word_count,
    extract_named_metrics,
    normalize_pid,
    parse_survey_csv,
    quiz_score,
)
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
                error_detail=run.get("error_detail"),
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
        "locked": bool(loaded.locked),
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


def _require_unlocked(loaded: m.LoadedSession) -> m.LoadedSession:
    """Backstop for the front-end lock: reject coding mutations on a locked
    session (423) so a stale tab can't edit finished coding. The lock toggle
    itself (POST .../lock) is intentionally NOT guarded."""
    if loaded.locked:
        raise HTTPException(
            status_code=423,
            detail="Session coding is locked. Unlock it before editing.",
        )
    return loaded


# --------------------------------------------------------------------------- #
# Outcome / formulation scoring for the timeline highlight.
#
# A run's ``result_json`` and an exchange's config JSON are immutable, so the
# same string always scores the same — and the timeline is re-fetched after
# every coding edit. We therefore memoize on the raw JSON string so only the
# first load of a session pays the (seed-averaged) canonical re-scoring cost.
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=8192)
def _canonical_eval_cached(pid: str | None, result_json: str | None) -> dict[str, Any] | None:
    """``{cost, feasible, contributions}`` for a run's result JSON via the
    problem port (official re-scoring, seed-averaged — lower cost is better), or
    None if the run has no scorable schedule or the port lacks the hook.
    ``contributions`` = mean weighted cost per canonical goal term (may be {})."""
    if not pid or not result_json:
        return None
    try:
        port = get_study_port(pid)
    except Exception:
        return None
    fn = getattr(port, "canonical_evaluation_for_result", None)
    if fn is None:
        return None
    try:
        ev = fn(json.loads(result_json))
    except Exception:
        return None
    if not ev or ev.get("canonical_cost") is None:
        return None
    return {
        "cost": float(ev["canonical_cost"]),
        "feasible": bool(ev.get("feasible")),
        "contributions": ev.get("term_contributions") or {},
    }


@lru_cache(maxsize=8192)
def _formulation_score_cached(pid: str | None, panel_json: str | None) -> int | None:
    """0–11 formulation score for a panel-config JSON via the problem port
    (higher is better), or None if not scorable."""
    if not pid or not panel_json:
        return None
    try:
        port = get_study_port(pid)
    except Exception:
        return None
    fn = getattr(port, "formulation_quality_for_config", None)
    if fn is None:
        return None
    try:
        res = fn(json.loads(panel_json))
    except Exception:
        return None
    if not res or res.get("formulation_score") is None:
        return None
    return int(res["formulation_score"])


def _attach_scores_and_bests(rows: list[dict[str, Any]], pid: str | None) -> None:
    """Score each run/exchange and flag the session-best rows so the UI can
    highlight them:

    - **run** rows get ``canonical_cost`` + ``canonical_feasible``. The lowest
      cost wins the ``best_canonical`` star, but a feasible run always beats an
      infeasible one — a cheap cost bought by breaking a hard rule doesn't count,
      so the star only falls on an infeasible run if the session has no feasible
      run at all.
    - **codeable message** rows (agent exchanges) get ``formulation_score``
      (0–11). ``best_formulation`` marks EVERY exchange that reached the session's
      peak score (a plateau, so "each exchange that achieved it" is visible)."""
    best_cost: float | None = None
    best_feasible = False
    for r in rows:
        if r.get("kind") == "run":
            ev = _canonical_eval_cached(pid, r.get("latest_run"))
            if ev is None:
                continue
            cost, feasible = ev["cost"], ev["feasible"]
            r["canonical_cost"] = cost
            r["canonical_feasible"] = feasible
            r["canonical_contributions"] = ev["contributions"]
            # A feasible run outranks any infeasible one; within a tier, lower cost wins.
            if best_cost is None or (feasible, -cost) > (best_feasible, -best_cost):
                best_cost, best_feasible = cost, feasible
        elif r.get("kind") == "message" and r.get("codeable"):
            score = _formulation_score_cached(pid, r.get("problem_config"))
            if score is not None:
                r["formulation_score"] = score

    if best_cost is not None:
        for r in rows:
            if (
                r.get("kind") == "run"
                and r.get("canonical_cost") is not None
                and bool(r.get("canonical_feasible")) == best_feasible
                and abs(r["canonical_cost"] - best_cost) < 1e-9
            ):
                r["best_canonical"] = True

    scores = [r["formulation_score"] for r in rows if r.get("formulation_score") is not None]
    if scores:
        top = max(scores)
        for r in rows:
            if r.get("formulation_score") == top:
                r["best_formulation"] = True


def _attach_reason_suggestions(
    rows: list[dict[str, Any]], llm_reasons: dict[str, list[dict[str, Any]]]
) -> None:
    """Attribution evidence + reason suggestions — RUN rows only (a reason
    attributes the outcome change between two consecutive runs).

    Each run row gets ``outcome_delta`` (canonical cost Δ vs the previous run,
    feasibility flip, top component movers from the per-term contributions) and
    ``reason_suggestions`` derived from the structured config diffs of the
    exchanges BETWEEN the previous run and this one (``reasons_from_diffs``).
    Cached LLM verdicts (``llm_reasons``, keyed by row ref) REPLACE the
    mechanical candidates for runs the LLM checked (mirroring the tag layer);
    a verdict that matches a mechanical candidate is marked ``auto+llm``. Runs
    the LLM did not cover fall back to the mechanical candidates."""
    window: list[dict[str, Any]] = []
    prev_run: dict[str, Any] | None = None
    for r in rows:
        ref = r.get("row_ref")
        if r.get("kind") == "message":
            if isinstance(r.get("config_change"), dict):
                window.append(r["config_change"])
        elif r.get("kind") == "run" and r.get("canonical_cost") is not None:
            delta: dict[str, Any] = {
                "cost_delta": (r["canonical_cost"] - prev_run["cost"]) if prev_run else None,
                "feasible_from": prev_run["feasible"] if prev_run else None,
                "feasible_to": r.get("canonical_feasible"),
            }
            movers = []
            if prev_run:
                cur = r.get("canonical_contributions") or {}
                for term in set(cur) | set(prev_run["contributions"]):
                    d = (cur.get(term) or 0) - (prev_run["contributions"].get(term) or 0)
                    if abs(d) >= 1.0:
                        movers.append({"term": term, "delta": round(d, 1)})
                movers.sort(key=lambda x: -abs(x["delta"]))
            delta["movers"] = movers[:4]
            r["outcome_delta"] = delta
            auto = reasons_from_diffs(window)
            if (prev_run and not prev_run["feasible"] and r.get("canonical_feasible")
                    and "stochastic-rerun" not in auto):
                auto.append("feasibility-fix")
            r["reason_suggestions"] = _filter_dismissed_reasons(
                _reason_suggestions_for(auto, llm_reasons.get(ref)), r)
            window = []
            prev_run = {"cost": r["canonical_cost"], "feasible": bool(r.get("canonical_feasible")),
                        "contributions": r.get("canonical_contributions") or {}}


def _filter_dismissed_reasons(
    suggestions: list[dict[str, Any]], row: dict[str, Any]
) -> list[dict[str, Any]]:
    """Drop suggestions the researcher explicitly rejected on this row
    (persisted ``dismiss-reason`` annotations)."""
    dismissed = set(row.get("dismissed_reasons") or [])
    if not dismissed:
        return suggestions
    return [s for s in suggestions if s.get("reason") not in dismissed]


def _reason_suggestions_for(
    auto: list[str], llm: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """The suggestions shown for one run. Once the LLM has checked this run its
    verdicts REPLACE the mechanical candidates (the mechanical list is a
    recall-oriented enumeration; the LLM output is the judged subset) — a
    verdict that matches a mechanical candidate is marked ``auto+llm``
    (agreement, the strongest signal). Without an LLM verdict for this run the
    mechanical candidates stand."""
    if not llm:
        return [{"reason": reason, "source": "auto"} for reason in auto]
    auto_set = set(auto)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in llm:
        reason = entry.get("reason")
        if not reason or reason in seen:
            continue
        seen.add(reason)
        out.append({"reason": reason,
                    "source": "auto+llm" if reason in auto_set else "llm",
                    "rationale": entry.get("rationale")})
    return out


def _timeline_payload(adb: Session, loaded: m.LoadedSession) -> dict[str, Any]:
    """Timeline rows + manual coding + per-row change-tag suggestions.

    Two suggestion sources merge onto each exchange row (kept out of the CSV
    export, which carries only accepted codes):

    - **deterministic** search-strategy / search-param tags + the structured
      config diff + stripped def Δ + result-state display, from
      ``build_turn_derivations`` (structural facts, recomputed every fetch);
    - **LLM** goal-term tags from the cached ✨ LLM tagging pass (see
      ``CodingLlmTags`` / ``coding_llm``), keyed by row ref.

    Snapshots are reference-only (not coded — a manual save is already captured
    by its "Definition edited" user message flowing into an exchange)."""
    rows = build_coding_rows(
        loaded, loaded.messages, loaded.runs, loaded.snapshots,
        loaded.annotations, loaded.pauses,
    )
    port = get_study_port(loaded.test_problem_id)
    turn_deriv = build_turn_derivations(loaded.messages, port)
    doc = adb.get(m.CodingLlmTags, loaded.id)
    llm_by_ref: dict[str, list[dict[str, Any]]] = {}
    if doc and doc.data_json:
        try:
            llm_by_ref = json.loads(doc.data_json)
        except json.JSONDecodeError:
            llm_by_ref = {}
    for row in rows:
        ref = row.get("row_ref")
        d = turn_deriv.get(ref)
        suggested: list[dict[str, Any]] = []
        if d is not None:
            suggested.extend(d["changes"])
            row["captured_terms"] = d["captured_terms"]
            if d["definition_change"] is not None:
                row["definition_change"] = d["definition_change"]
            if d["config_change"] is not None:
                row["config_change"] = d["config_change"]
            # Show the agent-response (post-reply) def/config, not the user-send state.
            if d.get("problem_def") is not None:
                row["problem_def"] = d["problem_def"]
            if d.get("problem_config") is not None:
                row["problem_config"] = d["problem_config"]
        if row.get("codeable") and ref in llm_by_ref:
            cached = llm_by_ref[ref]
            if isinstance(cached, list):
                suggested.extend(c for c in cached if isinstance(c, dict))
        # Drop suggestions the researcher explicitly dismissed on this row
        # (`dismiss` annotations — persisted, so they stay gone across reloads).
        if suggested and row.get("dismissed"):
            def _key(c: dict[str, Any]) -> str:
                return "|".join(str(c.get(f) or "") for f in CHANGE_FIELDS)
            dismissed_keys = {_key(d) for d in row["dismissed"]}
            suggested = [c for c in suggested if _key(c) not in dismissed_keys]
        if suggested:
            row["suggested_changes"] = suggested
    # Score runs (canonical cost) + exchanges (formulation) and star the bests.
    _attach_scores_and_bests(rows, loaded.test_problem_id)
    # Attribution evidence + reason suggestions (deterministic + cached LLM).
    rdoc = adb.get(m.CodingLlmReasons, loaded.id)
    llm_reasons: dict[str, list[dict[str, Any]]] = {}
    if rdoc and rdoc.data_json:
        try:
            llm_reasons = json.loads(rdoc.data_json)
        except json.JSONDecodeError:
            llm_reasons = {}
    _attach_reason_suggestions(rows, llm_reasons)
    return {
        "session": _loaded_summary(loaded),
        "annotations": [_annotation_out(a) for a in loaded.annotations],
        "pauses": [_pause_out(p) for p in loaded.pauses],
        "timeline": rows,
        "goal_term_keys": goal_term_keys(loaded.snapshots, port),
    }


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
    return _timeline_payload(adb, loaded)


@router.get("/loaded/{loaded_id}/timeline")
def get_timeline(
    loaded_id: str,
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    loaded = _get_loaded(adb, loaded_id)
    return _timeline_payload(adb, loaded)


@router.post("/llm-tags")
def run_llm_tags(
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    """Run (and cache) the ✨ LLM change-tagging pass: one batched call per
    session reads every exchange + the deterministic evidence and proposes
    composite change tags (goal-term origin / first-applied / mentioned /
    dropped / declined / removed). Scope to one session via ``loaded_id`` or run
    all loaded sessions.

    Without an ``api_key`` this is a PURE no-op — the existing cache is kept
    (unlike the old origin pass, which destructively wrote empty results). A
    per-session failure likewise keeps that session's old cache and is counted
    in ``failed``. Cached results feed every later timeline load, so a refresh
    never re-hits the API.

    ``purge_tags`` (re-label from scratch): per session, AFTER its LLM run
    succeeded, the existing accepted ``code`` annotations are deleted — with an
    auto-backup first — so the fresh suggestions can be re-accepted cleanly. A
    failed run purges nothing (old tags AND old cache stay); notes/markers/
    pauses are never touched; locked sessions are skipped entirely."""
    api_key = (body.get("api_key") or "").strip()
    model = (body.get("model") or "gemini-2.5-flash").strip()
    loaded_id = body.get("loaded_id")
    purge_tags = bool(body.get("purge_tags"))

    query = adb.query(m.LoadedSession)
    if loaded_id:
        query = query.filter(m.LoadedSession.id == loaded_id)
    # Locked sessions are "coding done" — never rewrite their tag cache.
    candidates = query.all()
    sessions = [s for s in candidates if not s.locked]
    skipped_locked = len(candidates) - len(sessions)

    if not api_key:
        return {"sessions": 0, "tagged_exchanges": 0, "ran_llm": False,
                "skipped_locked": skipped_locked, "failed": 0, "purged_tags": 0}

    tagged_exchanges = purged_total = 0
    ok = failed = 0
    for loaded in sessions:
        port = get_study_port(loaded.test_problem_id)
        rows = build_coding_rows(
            loaded, loaded.messages, loaded.runs, loaded.snapshots,
            loaded.annotations, loaded.pauses,
        )
        deriv = build_turn_derivations(loaded.messages, port)
        result = tag_session_changes(rows, deriv, port, api_key, model)
        if result is None:
            failed += 1  # keep this session's old cache AND old tags
            continue
        if purge_tags:
            # Re-label from scratch: back up, then drop the accepted code tags AND
            # old suggestion-dismissals (they referred to the previous suggestions)
            # — only now that this session's fresh suggestions are in hand.
            auto_backup(adb, [loaded.id], "llm-retag")
            purged_total += (
                adb.query(m.Annotation)
                .filter(m.Annotation.loaded_session_id == loaded.id,
                        m.Annotation.anno_type.in_(("code", "dismiss")))
                .delete(synchronize_session=False)
            )
        doc = adb.get(m.CodingLlmTags, loaded.id)
        if doc is None:
            doc = m.CodingLlmTags(loaded_session_id=loaded.id)
            adb.add(doc)
        doc.data_json = json.dumps(result, ensure_ascii=False)
        doc.model = model
        tagged_exchanges += len(result)
        ok += 1
    adb.commit()
    return {
        "sessions": ok,
        "tagged_exchanges": tagged_exchanges,
        "ran_llm": True,
        "skipped_locked": skipped_locked,
        "failed": failed,
        "purged_tags": purged_total,
    }


@router.post("/llm-reasons")
def run_llm_reasons(
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    """Run (and cache) the ✨ LLM reason-verification pass — fully SEPARATE from
    /llm-tags (own cache table, never touches change tags or their cache).

    For each run row it sends the verified attribution evidence (cost delta,
    component movers, config changes since the previous run) plus the
    conversation window, and caches the LLM's reason verdicts. Same safety
    semantics as /llm-tags: no api_key = pure no-op (cache kept); per-session
    failure keeps that session's old cache; locked sessions skipped."""
    api_key = (body.get("api_key") or "").strip()
    model = (body.get("model") or "gemini-2.5-flash").strip()
    loaded_id = body.get("loaded_id")

    query = adb.query(m.LoadedSession)
    if loaded_id:
        query = query.filter(m.LoadedSession.id == loaded_id)
    candidates = query.all()
    sessions = [s for s in candidates if not s.locked]
    skipped_locked = len(candidates) - len(sessions)

    if not api_key:
        return {"sessions": 0, "checked_runs": 0, "ran_llm": False,
                "skipped_locked": skipped_locked, "failed": 0}

    checked = ok = failed = 0
    for loaded in sessions:
        # Rebuild the same evidence the timeline shows (scores + windows).
        rows = build_coding_rows(
            loaded, loaded.messages, loaded.runs, loaded.snapshots,
            loaded.annotations, loaded.pauses,
        )
        port = get_study_port(loaded.test_problem_id)
        turn_deriv = build_turn_derivations(loaded.messages, port)
        for row in rows:
            d = turn_deriv.get(row.get("row_ref"))
            if d is not None:
                if d["config_change"] is not None:
                    row["config_change"] = d["config_change"]
                if d.get("problem_config") is not None:
                    row["problem_config"] = d["problem_config"]
        _attach_scores_and_bests(rows, loaded.test_problem_id)
        _attach_reason_suggestions(rows, {})

        # Targets: run rows with evidence; context = the window's user/agent text.
        targets: list[dict[str, Any]] = []
        window_text: list[str] = []
        for r in rows:
            if r.get("kind") == "message" and r.get("codeable"):
                up = (r.get("user_prompt") or "").strip()
                ag = (r.get("summary") or "").strip()
                snippet = (f"USER: {up[:400]}\n" if up else "") + (f"AGENT: {ag[:400]}" if ag else "")
                if snippet:
                    window_text.append(snippet)
            elif r.get("kind") == "run" and r.get("reason_suggestions"):
                targets.append({
                    "ref": r["row_ref"],
                    "evidence": render_run_evidence(r),
                    "context": "\n\n".join(window_text[-6:]) or "(no conversation since previous run)",
                })
                window_text = []
        if not targets:
            ok += 1
            continue
        result = verify_reasons(targets, api_key, model)
        if result is None:
            failed += 1  # keep this session's old cache
            continue
        doc = adb.get(m.CodingLlmReasons, loaded.id)
        if doc is None:
            doc = m.CodingLlmReasons(loaded_session_id=loaded.id)
            adb.add(doc)
        doc.data_json = json.dumps(result, ensure_ascii=False)
        doc.model = model
        checked += len(result)
        ok += 1
    adb.commit()
    return {
        "sessions": ok,
        "checked_runs": checked,
        "ran_llm": True,
        "skipped_locked": skipped_locked,
        "failed": failed,
    }


_META_FIELDS = {"video_filename", "video_duration_sec", "clock_offset_sec", "t0_video_pos"}


@router.patch("/loaded/{loaded_id}/coding-meta")
def patch_coding_meta(
    loaded_id: str,
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    loaded = _require_unlocked(_get_loaded(adb, loaded_id))
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


@router.post("/loaded/{loaded_id}/lock")
def set_lock(
    loaded_id: str,
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    """Toggle the "coding done" lock. Deliberately un-guarded so it's always
    reachable — it's the only way to unlock. Everything else on a locked session
    is rejected by ``_require_unlocked``."""
    loaded = _get_loaded(adb, loaded_id)
    loaded.locked = bool(body.get("locked"))
    adb.commit()
    return {"session": _loaded_summary(loaded)}


@router.post("/loaded/{loaded_id}/annotations")
def create_annotation(
    loaded_id: str,
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    loaded = _require_unlocked(_get_loaded(adb, loaded_id))
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
    _require_unlocked(_get_loaded(adb, loaded_id))
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
        _require_unlocked(_get_loaded(adb, loaded_id))
        adb.delete(anno)
        adb.commit()


@router.post("/loaded/{loaded_id}/reset-tags")
def reset_tags(
    loaded_id: str,
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    """Delete every coded change-tag (``anno_type='code'``) and every
    suggestion-dismissal (``'dismiss'``) for this session — a full reset of the
    researcher's tagging decisions. Notes, markers and pauses are untouched."""
    loaded = _require_unlocked(_get_loaded(adb, loaded_id))
    auto_backup(adb, [loaded.id], "reset-tags")
    deleted = (
        adb.query(m.Annotation)
        .filter(m.Annotation.loaded_session_id == loaded.id,
                m.Annotation.anno_type.in_(("code", "dismiss")))
        .delete(synchronize_session=False)
    )
    adb.commit()
    return {"deleted": deleted}


@router.post("/loaded/{loaded_id}/reset-reasons")
def reset_reasons(
    loaded_id: str,
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    """Delete every improvement-reason label (``anno_type='reason'``) AND every
    rejected reason suggestion (``'dismiss-reason'``) for this session — a full
    reset of the reason layer. Change tags, tag dismissals, notes, markers and
    pauses are untouched — the reason layer resets independently."""
    loaded = _require_unlocked(_get_loaded(adb, loaded_id))
    auto_backup(adb, [loaded.id], "reset-reasons")
    deleted = (
        adb.query(m.Annotation)
        .filter(m.Annotation.loaded_session_id == loaded.id,
                m.Annotation.anno_type.in_(("reason", "dismiss-reason")))
        .delete(synchronize_session=False)
    )
    adb.commit()
    return {"deleted": deleted}


@router.post("/loaded/{loaded_id}/pauses")
def create_pause(
    loaded_id: str,
    body: dict = Body(...),
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    loaded = _require_unlocked(_get_loaded(adb, loaded_id))
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
        _require_unlocked(_get_loaded(adb, loaded_id))
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
        auto_backup(adb, [loaded.id], "delete-session")
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
    auto_backup(adb, ids, "bulk-delete")
    deleted = (
        adb.query(m.LoadedSession)
        .filter(m.LoadedSession.id.in_(ids))
        .delete(synchronize_session=False)
    )
    adb.commit()
    return {"deleted": deleted}


@router.get("/coding-backup.json")
def download_coding_backup(
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    """Portable JSON of ALL coding (tags, notes, pauses, video-alignment, origin
    classifications) — the off-machine / version-control safety copy."""
    data = dump_coding(adb)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        iter([json.dumps(data, indent=2, ensure_ascii=False)]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="mopt-coding-backup-{stamp}.json"'},
    )


@router.post("/coding-restore")
async def restore_coding_backup(
    request: Request,
    adb: Session = Depends(get_analysis_db),
    _: Principal = Depends(require_researcher),
):
    """Restore coding from a backup JSON (raw body). Non-destructive: re-creates
    tags on the matching loaded sessions, skipping exact duplicates."""
    raw = await request.body()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid backup JSON: {exc}") from exc
    try:
        return restore_coding(adb, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    uploaded_at: dict[str, str] = {}
    for r in rows:
        by_phase[r.phase] = by_phase.get(r.phase, 0) + 1
        if r.created_at is not None:
            iso = r.created_at.isoformat()
            if r.phase not in uploaded_at or iso > uploaded_at[r.phase]:
                uploaded_at[r.phase] = iso
    return {"counts": by_phase, "uploaded_at": uploaded_at}


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
    metrics: dict[str, float | None] = dict(extract_named_metrics(row or {}))
    # Word count of the free-text experience answer (number only — text stays here).
    words = experience_word_count(row or {})
    if words is not None:
        metrics["experience_words"] = float(words)
    # Warm-up quiz: # correct of the 5 scenario MCQs (objective knowledge measure).
    quiz = quiz_score(row or {})
    if quiz is not None:
        metrics["quiz_score"] = float(quiz)
    return metrics


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

    def _briefs(s) -> list:
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
        return briefs

    def _origins(s) -> dict[str, str]:
        """Origin (user_volunteered / agent_asked / agent_assumed / …) of EVERY
        goal term for a session — see VrptwStudyPort.goal_term_origins."""
        fn = getattr(_port(s.test_problem_id), "goal_term_origins", None)
        if fn is None:
            return {}
        try:
            return fn(_briefs(s)) or {}
        except Exception:
            return {}

    _HARD_KEYS = ("lateness_penalty", "capacity_penalty", "shift_limit")
    sessions = []
    for s in loaded:
        origins = _origins(s)  # all goal terms; computed once per session
        sessions.append(
            {
                "loaded_id": s.id,
                "participant": s.participant_number,
                "workflow_mode": s.workflow_mode,
                "test_problem_id": s.test_problem_id,
                # origin of every goal term (objective + hard + soft + custom):
                "term_origins": origins,
                # hard-only subset kept for backward compatibility:
                "hard_origins": {k: origins.get(k, "absent") for k in _HARD_KEYS},
            }
        )
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
    def _reason_list(a: m.Annotation) -> list[str] | None:
        """Accepted improvement reasons for `reason` annotations (None elsewhere)."""
        if a.anno_type != "reason":
            return None
        try:
            obj = json.loads(a.text or "{}")
        except (json.JSONDecodeError, TypeError):
            return None
        return obj.get("reasons") if isinstance(obj.get("reasons"), list) else None

    annotations = [
        {
            "loaded_id": a.loaded_session_id,
            "anno_type": a.anno_type,
            "label": a.label,
            "video_pos_sec": a.video_pos_sec,
            "row_ref": a.row_ref,
            # Parsed coded-change facets (origin/type/term/effect) for `code` tags,
            # so the notebook can matrix the MANUAL session-coding labels. Null for
            # note/marker rows. Re-parses live from the annotation each dataset load,
            # so re-coding + Reload data refreshes them.
            **_parse_change(a.text, a.label),
            # Accepted improvement reasons for `reason` annotations (list | None) —
            # drives the breakthrough/jump/feasibility tallies in the notebook.
            "reasons": _reason_list(a),
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
            # list of present & active goal terms (objective + 3 hard + 3 soft +
            # custom) at this snapshot — drives the "goal terms captured" heatmap
            # (== coverage) + the per-term identification-timing chart in the notebook.
            "captured_terms": r.get("captured_terms"),
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

    # Per-exchange SOLVER-side change events, field-level, from the verified
    # structural diff layer (same source as the cfg Δ chips): algorithm switches
    # + every solver-knob change, with `algorithm_params` expanded per KEY
    # (cooling_rate, c1, pc, …; key-removal churn already suppressed upstream).
    # Origin = the deterministic search-tag origin (user on manual-edit ack
    # turns, else agent); the notebook can override it with accepted-tag origins
    # joined on row_ref. Drives the "which sessions changed what" grid.
    from app.analysis.coding_suggestions import _canon as _sc_canon

    search_changes: list[dict[str, Any]] = []
    # Per-exchange goal-term WEIGHT change events (term, from→to) — powers the
    # oscillation/tuning-style tallies in the notebook (origin joins there from
    # the accepted tags on the same row_ref).
    weight_changes: list[dict[str, Any]] = []
    for s in loaded:
        port = _port(s.test_problem_id)
        if port is None:
            continue
        try:
            deriv = build_turn_derivations(s.messages, port)
        except Exception:
            continue
        msg_ts = {f"message:{msg.source_id}": msg.ts_epoch for msg in s.messages}
        for ref, d in deriv.items():
            diff = d.get("config_change") or {}
            for t in diff.get("terms") or []:
                for c in t.get("changes") or []:
                    if c.get("field") == "weight":
                        weight_changes.append({
                            "loaded_id": s.id, "row_ref": ref, "ts_epoch": msg_ts.get(ref),
                            "term": t.get("term"), "from": c.get("from"), "to": c.get("to"),
                        })
            strat_origin = next((c["origin"] for c in d["changes"] if c["type"] == "search-strategy"), None)
            param_origin = next((c["origin"] for c in d["changes"] if c["type"] == "search-param"), None)

            def _add(field: str, frm: Any, to: Any, origin: str | None) -> None:
                search_changes.append({
                    "loaded_id": s.id, "row_ref": ref, "ts_epoch": msg_ts.get(ref),
                    "field": field, "from": frm, "to": to, "origin": origin or "agent",
                })

            if diff.get("algorithm"):
                alg = diff["algorithm"]
                _add("algorithm", alg.get("from"), alg.get("to"), strat_origin)
            for p in diff.get("params") or []:
                if p["field"] == "algorithm_params":
                    a = p.get("from") if isinstance(p.get("from"), dict) else {}
                    b = p.get("to") if isinstance(p.get("to"), dict) else {}
                    for k in sorted(b):
                        if k not in a or _sc_canon(a.get(k)) != _sc_canon(b.get(k)):
                            _add(k, a.get(k), b.get(k), param_origin)
                else:
                    _add(p["field"], p.get("from"), p.get("to"), param_origin)

    return {
        "sessions": sessions,
        "messages": messages,
        "runs": runs,
        "annotations": annotations,
        "snapshots": snapshots,
        "surveys": surveys,
        "search_changes": search_changes,
        "weight_changes": weight_changes,
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
    def _cell(row: dict[str, Any], col: str) -> Any:
        if col == "changes":  # composite change tags → "origin|type|term|effect"
            parts = [
                "|".join(str(c.get(f) or "") for f in CHANGE_FIELDS)
                for c in (row.get("changes") or [])
            ]
            return "; ".join(parts)
        if col == "reasons":  # accepted improvement reasons → "a; b (note)"
            rl = row.get("reasons")
            if not isinstance(rl, dict):
                return ""
            txt = "; ".join(rl.get("reasons") or [])
            return f"{txt} ({rl['note']})" if rl.get("note") else txt
        val = row.get(col)
        if isinstance(val, dict):  # structured config diff → JSON string
            return json.dumps(val, ensure_ascii=False)
        return "" if val is None else val

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow([_cell(row, c) for c in CSV_COLUMNS])
    label = loaded.participant_number or loaded.source_session_id or loaded.id
    filename = f"coding-{label}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
