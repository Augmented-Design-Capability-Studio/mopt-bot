from __future__ import annotations

from typing import Any


def derive_problem_panel_from_brief(
    problem_brief: dict[str, Any],
    test_problem_id: str | None = None,
) -> dict[str, Any] | None:
    """Deterministically derive a panel ``problem`` block from the saved brief."""
    from app.problems.registry import get_study_port

    port = get_study_port(test_problem_id)
    return port.derive_problem_panel_from_brief(problem_brief)
