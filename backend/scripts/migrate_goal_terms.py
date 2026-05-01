from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Allow direct execution: `python scripts/migrate_goal_terms.py` from `backend/`.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.models import SessionSnapshot, StudySession
from app.problems.registry import DEFAULT_PROBLEM_ID, get_study_port


def _migrate_panel_blob(panel_json: str | None, problem_id: str) -> tuple[str | None, bool]:
    if not panel_json or not str(panel_json).strip():
        return panel_json, False
    try:
        raw = json.loads(panel_json)
    except Exception:
        return panel_json, False
    if not isinstance(raw, dict):
        return panel_json, False
    port = get_study_port(problem_id or DEFAULT_PROBLEM_ID)
    sanitized, _warnings = port.sanitize_panel_config(raw)
    new_json = json.dumps(sanitized)
    return new_json, new_json != panel_json


def migrate_goal_terms() -> tuple[int, int]:
    sessions_updated = 0
    snapshots_updated = 0
    with SessionLocal() as db:
        sessions = db.query(StudySession).all()
        for row in sessions:
            problem_id = getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID
            next_panel_json, changed = _migrate_panel_blob(row.panel_config_json, problem_id)
            if changed:
                row.panel_config_json = next_panel_json
                sessions_updated += 1

        snapshots = db.query(SessionSnapshot).all()
        for snap in snapshots:
            session = db.get(StudySession, snap.session_id)
            problem_id = (
                (getattr(session, "test_problem_id", None) if session is not None else None)
                or DEFAULT_PROBLEM_ID
            )
            next_panel_json, changed = _migrate_panel_blob(snap.panel_config_json, problem_id)
            if changed:
                snap.panel_config_json = next_panel_json
                snapshots_updated += 1

        db.commit()
    return sessions_updated, snapshots_updated


if __name__ == "__main__":
    s_count, ss_count = migrate_goal_terms()
    print(
        f"Goal-terms migration complete: updated {s_count} session panel(s), "
        f"{ss_count} snapshot panel(s)."
    )
