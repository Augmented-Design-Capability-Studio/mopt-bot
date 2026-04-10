from __future__ import annotations

from datetime import datetime, timezone

from app.models import ChatMessage, OptimizationRun, SessionSnapshot
from app.routers.sessions import helpers
from app.session_export import EXPORT_SCHEMA_VERSION, build_export_timeline


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_build_export_timeline_sorts_and_labels():
    s1 = SessionSnapshot(
        id=1,
        session_id="x",
        created_at=_dt("2025-01-02T00:00:00+00:00"),
        event_type="before_run",
        problem_brief_json="{}",
        panel_config_json=None,
    )
    m1 = ChatMessage(
        id=10,
        session_id="x",
        created_at=_dt("2025-01-01T12:00:00+00:00"),
        role="user",
        content="hello",
        visible_to_participant=True,
        kind="chat",
        meta_json=None,
    )
    r1 = OptimizationRun(
        id=5,
        session_id="x",
        session_run_index=0,
        created_at=_dt("2025-01-03T00:00:00+00:00"),
        run_type="optimize",
        request_json="{}",
        result_json="{}",
        cost=1.0,
        reference_cost=None,
        ok=True,
        error_message=None,
    )
    tl = build_export_timeline([m1], [r1], [s1], run_number=helpers.run_number)
    assert [x["kind"] for x in tl] == ["message", "snapshot", "run"]
    assert tl[0]["label"] == "user/chat"
    assert tl[1]["label"] == "before_run"
    assert tl[1]["payload_summary"] == "brief=yes panel=no"
    assert tl[2]["ref"]["run_number"] == helpers.run_number(r1)  # 0 is falsy in run_number(); falls back to id


def test_export_schema_version_constant():
    assert EXPORT_SCHEMA_VERSION == 2
