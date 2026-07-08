"""Analysis-only ORM models (bound to ``AnalysisBase`` / the analysis DB).

A loaded session is a self-contained *duplicate* of a study session — the
subset of columns the coding tool renders — plus the manual coding output
(annotations, notes, pauses) and the video↔DB clock alignment metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.analysis_db import AnalysisBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LoadedSession(AnalysisBase):
    __tablename__ = "loaded_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    participant_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workflow_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    test_problem_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(16), default="db")  # db | json | live
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # --- video ↔ DB clock alignment / coding metadata ---
    video_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    video_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    # offset = iso_epoch − video_pos, established once by anchoring a DB-visible
    # event to the playhead. epoch(any event) = video_pos + clock_offset_sec.
    clock_offset_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Canonical t0 = first observed keystroke (video-marked).
    t0_video_pos: Mapped[float | None] = mapped_column(Float, nullable=True)
    t0_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    t0_epoch: Mapped[float | None] = mapped_column(Float, nullable=True)

    messages: Mapped[list["LoadedMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    runs: Mapped[list["LoadedRun"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list["LoadedSnapshot"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    pauses: Mapped[list["Pause"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class LoadedMessage(AnalysisBase):
    __tablename__ = "loaded_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loaded_session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("loaded_sessions.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ts_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ts_epoch: Mapped[float | None] = mapped_column(Float, nullable=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    visible_to_participant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["LoadedSession"] = relationship(back_populates="messages")


class LoadedRun(AnalysisBase):
    __tablename__ = "loaded_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loaded_session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("loaded_sessions.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_run_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ts_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ts_epoch: Mapped[float | None] = mapped_column(Float, nullable=True)
    run_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    request_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["LoadedSession"] = relationship(back_populates="runs")


class LoadedSnapshot(AnalysisBase):
    __tablename__ = "loaded_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loaded_session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("loaded_sessions.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ts_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ts_epoch: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    problem_brief_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    panel_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["LoadedSession"] = relationship(back_populates="snapshots")


class Annotation(AnalysisBase):
    """A manual coded row (code/marker) or a note attached to a DB event."""

    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loaded_session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("loaded_sessions.id", ondelete="CASCADE"), index=True
    )
    anno_type: Mapped[str] = mapped_column(String(16), default="code")  # code | note | marker
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    color: Mapped[str | None] = mapped_column(String(24), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Standalone rows carry a video position; a note attached to a DB event
    # instead sets row_ref (e.g. "message:123") and inherits that row's time.
    video_pos_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    row_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    session: Mapped["LoadedSession"] = relationship(back_populates="annotations")


class Pause(AnalysisBase):
    """A participant break; its duration is subtracted from subsequent
    ``time_since_start`` values."""

    __tablename__ = "pauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loaded_session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("loaded_sessions.id", ondelete="CASCADE"), index=True
    )
    start_video_pos: Mapped[float] = mapped_column(Float)
    end_video_pos: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["LoadedSession"] = relationship(back_populates="pauses")
