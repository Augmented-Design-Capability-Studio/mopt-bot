"""Deterministic brief → panel derivation for the template problem.

Called when LLM derivation is unavailable or times out.  Parse brief items
using heuristics and return a best-effort panel config dict.
"""

from __future__ import annotations

from typing import Any


def derive_problem_panel_from_brief(problem_brief: dict[str, Any]) -> dict[str, Any] | None:
    """Return a best-effort panel config derived from the problem brief.

    Args:
        problem_brief: The normalised brief dict (gathered_info, assumptions,
                       open_questions, solver_scope, backend_template).

    Returns:
        A ``{ "problem": { ... } }`` dict, or None if insufficient info.
    """
    # TODO: implement deterministic extraction.
    # Pattern: scan brief items for known keywords, map to weight keys and
    # algorithm settings, return a minimal valid panel config.
    #
    # Example pattern from knapsack:
    #   items = problem_brief.get("items", [])
    #   weights: dict[str, float] = {}
    #   for item in items:
    #       text = item.get("text", "").lower()
    #       if "value" in text or "profit" in text:
    #           weights["value_emphasis"] = 1.0
    #   if not weights:
    #       return None
    #   return {"problem": {"weights": weights, "algorithm": "GA", "epochs": 50, "pop_size": 20}}

    return None
