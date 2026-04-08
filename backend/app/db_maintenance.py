from __future__ import annotations

import json
import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.models import OptimizationRun, StudySession
from app.problem_brief import normalize_problem_brief

log = logging.getLogger(__name__)


def ensure_database_shape() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_sessions_problem_brief_column()
    _ensure_sessions_participant_number_column()
    _ensure_sessions_processing_columns()
    _ensure_sessions_optimization_runs_blocked_column()
    _ensure_sessions_optimization_gate_engaged_column()
    _backfill_optimization_gate_engaged()
    _ensure_runs_session_index_column()
    _backfill_runs_session_index()


def _ensure_sessions_problem_brief_column() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("sessions"):
        return
    columns = {column["name"] for column in inspector.get_columns("sessions")}
    if "problem_brief_json" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE sessions ADD COLUMN problem_brief_json TEXT"))
    log.info("Added sessions.problem_brief_json column")


def _ensure_sessions_participant_number_column() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("sessions"):
        return
    columns = {column["name"] for column in inspector.get_columns("sessions")}
    if "participant_number" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE sessions ADD COLUMN participant_number VARCHAR(64)"))
    log.info("Added sessions.participant_number column")


def _ensure_sessions_processing_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("sessions"):
        return
    columns = {column["name"] for column in inspector.get_columns("sessions")}
    statements: list[tuple[str, str]] = []
    if "processing_revision" not in columns:
        statements.append(
            ("ALTER TABLE sessions ADD COLUMN processing_revision INTEGER NOT NULL DEFAULT 0", "sessions.processing_revision")
        )
    if "brief_status" not in columns:
        statements.append(("ALTER TABLE sessions ADD COLUMN brief_status VARCHAR(16) NOT NULL DEFAULT 'idle'", "sessions.brief_status"))
    if "config_status" not in columns:
        statements.append(("ALTER TABLE sessions ADD COLUMN config_status VARCHAR(16) NOT NULL DEFAULT 'idle'", "sessions.config_status"))
    if "processing_error" not in columns:
        statements.append(("ALTER TABLE sessions ADD COLUMN processing_error TEXT", "sessions.processing_error"))
    if not statements:
        return
    with engine.begin() as conn:
        for sql, _ in statements:
            conn.execute(text(sql))
    for _, column_name in statements:
        log.info("Added %s column", column_name)


def _ensure_sessions_optimization_runs_blocked_column() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("sessions"):
        return
    columns = {column["name"] for column in inspector.get_columns("sessions")}
    if "optimization_runs_blocked_by_researcher" in columns:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE sessions ADD COLUMN optimization_runs_blocked_by_researcher BOOLEAN NOT NULL DEFAULT 0"
            )
        )
    log.info("Added sessions.optimization_runs_blocked_by_researcher column")


def _ensure_sessions_optimization_gate_engaged_column() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("sessions"):
        return
    columns = {column["name"] for column in inspector.get_columns("sessions")}
    if "optimization_gate_engaged" in columns:
        return
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE sessions ADD COLUMN optimization_gate_engaged BOOLEAN NOT NULL DEFAULT 0")
        )
    log.info("Added sessions.optimization_gate_engaged column")


def _backfill_optimization_gate_engaged() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("sessions") or not inspector.has_table("messages"):
        return
    columns = {column["name"] for column in inspector.get_columns("sessions")}
    if "optimization_gate_engaged" not in columns:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE sessions SET optimization_gate_engaged = 1
                WHERE optimization_gate_engaged = 0
                AND EXISTS (
                    SELECT 1 FROM messages
                    WHERE messages.session_id = sessions.id
                    AND messages.role = 'user'
                    AND messages.visible_to_participant = 1
                )
                """
            )
        )
    with Session(engine) as db:
        rows = db.query(StudySession).filter(StudySession.optimization_gate_engaged.is_(False)).all()
        dirty = False
        for row in rows:
            if not row.problem_brief_json:
                continue
            try:
                brief = normalize_problem_brief(json.loads(row.problem_brief_json))
            except (json.JSONDecodeError, TypeError):
                continue
            oq = brief.get("open_questions") or []
            if any(isinstance(q, dict) for q in oq):
                row.optimization_gate_engaged = True
                dirty = True
        if dirty:
            db.commit()
            log.info("Backfilled optimization_gate_engaged from problem brief open_questions")


def _ensure_runs_session_index_column() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("runs"):
        return
    columns = {column["name"] for column in inspector.get_columns("runs")}
    if "session_run_index" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE runs ADD COLUMN session_run_index INTEGER"))
    log.info("Added runs.session_run_index column")


def _backfill_runs_session_index() -> None:
    with Session(engine) as db:
        runs = (
            db.query(OptimizationRun)
            .order_by(OptimizationRun.session_id.asc(), OptimizationRun.id.asc())
            .all()
        )
        next_index_by_session: dict[str, int] = {}
        dirty = False
        for run in runs:
            expected = next_index_by_session.get(run.session_id, 1)
            current = run.session_run_index
            assigned = current if isinstance(current, int) and current >= expected else expected
            if current != assigned:
                run.session_run_index = assigned
                dirty = True
            next_index_by_session[run.session_id] = assigned + 1
        if dirty:
            db.commit()
            log.info("Backfilled runs.session_run_index for %s runs", len(runs))
