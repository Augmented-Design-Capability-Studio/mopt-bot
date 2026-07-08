"""Separate SQLite store for the session-coding analysis tool.

This is a *second* database, fully isolated from the study DB (``app.database``).
Loaded session copies plus all manual coding output (annotations, notes, video
timing, pauses) live here so the expensive coding labour is durable and directly
joinable by the downstream quantitative notebook — and so the study DB is never
touched by the analysis tool.
"""

from __future__ import annotations

from sqlalchemy import create_engine
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
