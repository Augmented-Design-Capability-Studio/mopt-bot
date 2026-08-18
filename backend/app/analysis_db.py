"""Separate SQLite store for the session-coding analysis tool.

This is a *second* database, fully isolated from the study DB (``app.database``).
Loaded session copies plus all manual coding output (annotations, notes, video
timing, pauses) live here so the expensive coding labour is durable and directly
joinable by the downstream quantitative notebook — and so the study DB is never
touched by the analysis tool.
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings
from app.database import _resolve_sqlite_url, _sqlite_connect_args


class AnalysisBase(DeclarativeBase):
    """Declarative base for analysis-only models.

    Distinct from the study ``Base`` so ``create_all`` on either engine only
    ever materialises its own tables — the two schemas never cross-create.
    """


def get_analysis_engine():
    settings = get_settings()
    url = _resolve_sqlite_url(settings.analysis_database_url)
    return create_engine(
        url,
        connect_args=_sqlite_connect_args(url),
        pool_pre_ping=True,
    )


analysis_engine = get_analysis_engine()
AnalysisSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=analysis_engine)


def get_analysis_db():
    db = AnalysisSessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_analysis_db_shape() -> None:
    """Create any missing analysis tables. Idempotent; safe on every startup.

    Importing the models registers them on ``AnalysisBase.metadata`` before the
    ``create_all`` call.
    """
    from app.analysis import models  # noqa: F401  (registers tables)

    AnalysisBase.metadata.create_all(bind=analysis_engine)
    _ensure_loaded_runs_error_detail_column()
    _ensure_loaded_sessions_locked_column()


def _ensure_loaded_runs_error_detail_column() -> None:
    """create_all only creates missing tables, never adds columns to existing
    ones. Add loaded_runs.error_detail on pre-existing analysis DBs so imported
    archives can carry the researcher-only failure diagnostic."""
    inspector = inspect(analysis_engine)
    if not inspector.has_table("loaded_runs"):
        return
    columns = {column["name"] for column in inspector.get_columns("loaded_runs")}
    if "error_detail" in columns:
        return
    with analysis_engine.begin() as conn:
        conn.execute(text("ALTER TABLE loaded_runs ADD COLUMN error_detail TEXT"))


def _ensure_loaded_sessions_locked_column() -> None:
    """Add loaded_sessions.locked on pre-existing analysis DBs (create_all won't
    alter an existing table). Existing rows default to unlocked."""
    inspector = inspect(analysis_engine)
    if not inspector.has_table("loaded_sessions"):
        return
    columns = {column["name"] for column in inspector.get_columns("loaded_sessions")}
    if "locked" in columns:
        return
    with analysis_engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE loaded_sessions ADD COLUMN locked BOOLEAN NOT NULL DEFAULT 0")
        )
