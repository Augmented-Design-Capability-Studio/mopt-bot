"""Brief→panel derivation for knapsack.

The previous regex-marker layer was removed: knapsack briefs don't carry
structurally-tagged config IDs (no panel→brief sync writes them out the way
VRPTW's ``config-weight-*`` rows do), so there's nothing deterministic to
recover from text alone.  Returning ``None`` lets the sync layer fall back to
the starter panel and wait for the LLM (see
``app.services.llm.generate_config_from_brief``).
"""

from __future__ import annotations

from typing import Any


def derive_problem_panel_from_brief(problem_brief: dict[str, Any]) -> dict[str, Any] | None:
    return None
