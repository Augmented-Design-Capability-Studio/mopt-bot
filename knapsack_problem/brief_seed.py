"""Brief→panel derivation for knapsack.

A minimal deterministic seed: when the brief carries a gathered/assumption
row that names a search algorithm (e.g. *"Genetic search is being used."*),
return a partial panel with that algorithm set. The sync layer merges this
seed into the panel via ``_backfill_solver_fields_from_seed`` so the run
gate's ``search_strategy_present`` check passes even when the LLM panel-
derive omits ``algorithm`` from its output.

This mirrors VRPTW's behaviour (where ``derive_problem_panel_from_brief``
seeds algorithm from brief text via the same closed alias vocabulary) so
the run gate becomes consistent across problems. No regex over natural
language — the extraction is a closed 5-algorithm enum lookup defined
once in ``algorithm_catalog.ALGORITHM_BRIEF_ALIAS_MAP``.

Anything beyond algorithm extraction stays the responsibility of the LLM
panel-derive: knapsack briefs don't carry structurally-tagged config IDs,
so there's no other deterministic signal to recover.
"""

from __future__ import annotations

from typing import Any

from app.algorithm_catalog import DEFAULT_EPOCHS, DEFAULT_POP_SIZE, default_algorithm_params


def derive_problem_panel_from_brief(problem_brief: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(problem_brief, dict):
        return None
    items = problem_brief.get("items")
    if not isinstance(items, list):
        return None

    from app.services.goal_term_anchoring import extract_algorithm_from_brief

    algorithm = extract_algorithm_from_brief(items)
    if algorithm is None:
        return None

    return {
        "problem": {
            "algorithm": algorithm,
            "algorithm_params": default_algorithm_params(algorithm),
            "epochs": DEFAULT_EPOCHS,
            "pop_size": DEFAULT_POP_SIZE,
        }
    }
