"""The raw failure diagnostic (error_detail) is researcher-only.

Regression for session-73906e05: unexpected solve failures were swallowed into
an opaque "Optimization failed" and the researcher console only ever showed
"error". We now capture the real cause in error_detail — but it must never reach
participants, so run_to_out only emits it when include_detail is set (the run
router passes include_detail=True exclusively for researcher-authenticated
callers).
"""

from datetime import datetime, timezone

from app.models import OptimizationRun
from app.routers.sessions.helpers import run_to_out


def _failed_run() -> OptimizationRun:
    return OptimizationRun(
        id=7,
        session_run_index=2,
        session_id="s1",
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        run_type="optimize",
        ok=False,
        error_message="Optimization failed",
        error_detail="TypeError: float() argument must be a string or a real number, not 'NoneType'",
    )


def test_participant_never_receives_error_detail():
    out = run_to_out(_failed_run())  # default: participant-facing
    assert out.error_message == "Optimization failed"
    assert out.error_detail is None


def test_researcher_receives_error_detail():
    out = run_to_out(_failed_run(), include_detail=True)
    assert out.error_message == "Optimization failed"
    assert out.error_detail is not None
    assert "TypeError" in out.error_detail
