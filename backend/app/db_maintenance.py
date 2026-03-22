from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.models import OptimizationRun

log = logging.getLogger(__name__)


def ensure_database_shape() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_sessions_problem_brief_column()
    _ensure_sessions_participant_number_column()
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
