"""Session snapshot storage for brief+panel continuity."""

from __future__ import annotations

import logging

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import SessionSnapshot, StudySession

log = logging.getLogger(__name__)

KEEP_SNAPSHOTS_PER_SESSION = 10
EVENT_BEFORE_RUN = "before_run"
EVENT_MANUAL_SAVE = "manual_save"


def create_snapshot(
    db: Session,
    session_id: str,
    event_type: str,
    *,
    problem_brief_json: str | None = None,
    panel_config_json: str | None = None,
) -> SessionSnapshot | None:
    """Create a snapshot of the session's brief and panel. Prunes old snapshots."""
    row = db.query(StudySession).filter(StudySession.id == session_id).first()
    if row is None:
        return None

    brief = problem_brief_json if problem_brief_json is not None else row.problem_brief_json
    panel = panel_config_json if panel_config_json is not None else row.panel_config_json

    snapshot = SessionSnapshot(
        session_id=session_id,
        event_type=event_type,
        problem_brief_json=brief,
        panel_config_json=panel,
    )
    db.add(snapshot)
    db.flush()

    _prune_snapshots(db, session_id)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def _prune_snapshots(db: Session, session_id: str) -> None:
    """Keep at most KEEP_SNAPSHOTS_PER_SESSION per session, deleting oldest first."""
    snapshots = (
        db.query(SessionSnapshot.id)
        .filter(SessionSnapshot.session_id == session_id)
        .order_by(SessionSnapshot.id.desc())
        .all()
    )
    if len(snapshots) <= KEEP_SNAPSHOTS_PER_SESSION:
        return
    ids_to_delete = [s.id for s in snapshots[KEEP_SNAPSHOTS_PER_SESSION:]]
    db.execute(delete(SessionSnapshot).where(SessionSnapshot.id.in_(ids_to_delete)))
