import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.problems.registry import DEFAULT_PROBLEM_ID


def utcnow():
    return datetime.now(timezone.utc)


class StudySession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    workflow_mode: Mapped[str] = mapped_column(String(16), default="waterfall")
    participant_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    panel_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    problem_brief_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_revision: Mapped[int] = mapped_column(Integer, default=0)
    brief_status: Mapped[str] = mapped_column(String(16), default="idle")
    config_status: Mapped[str] = mapped_column(String(16), default="idle")
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    optimization_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    optimization_runs_blocked_by_researcher: Mapped[bool] = mapped_column(Boolean, default=False)
    participant_tutorial_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_step_override: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tutorial_chat_started: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_uploaded_files: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_definition_tab_visited: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_definition_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_config_tab_visited: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_config_first_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_config_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_first_run_done: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_second_run_done: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_run_summary_read: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_results_inspected: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_explain_used: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_candidate_marked: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_third_run_done: Mapped[bool] = mapped_column(Boolean, default=False)
    tutorial_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    optimization_gate_engaged: Mapped[bool] = mapped_column(Boolean, default=False)
    gemini_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    gemini_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_problem_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_PROBLEM_ID)
    # Incremented on researcher reset so participant UIs can hard-reload and drop stale state.
    content_reset_revision: Mapped[int] = mapped_column(Integer, default=0)

    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan"
    )
    runs: Mapped[list["OptimizationRun"]] = relationship(
        "OptimizationRun", back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    visible_to_participant: Mapped[bool] = mapped_column(Boolean, default=True)
    kind: Mapped[str] = mapped_column(String(32), default="chat")
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["StudySession"] = relationship("StudySession", back_populates="messages")


class SessionSnapshot(Base):
    """Stores brief+panel state before runs or manual saves for session continuity."""

    __tablename__ = "session_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_type: Mapped[str] = mapped_column(String(32), default="before_run")
    problem_brief_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    panel_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class OptimizationRun(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_run_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run_type: Mapped[str] = mapped_column(String(32), default="optimize")
    request_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["StudySession"] = relationship("StudySession", back_populates="runs")
