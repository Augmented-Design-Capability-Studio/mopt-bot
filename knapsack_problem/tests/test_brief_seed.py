"""Tests for knapsack's ``derive_problem_panel_from_brief``.

The seed exists so the run-gate's ``search_strategy_present`` check can
pass deterministically once the brief carries a gathered/assumption row
naming an algorithm (e.g. *"Genetic search is being used."*). Without
this seed the LLM panel-derive is the only path to ``panel.algorithm``,
and when it omits the field the gate stays unmet — symptomatic of the
"choose a search strategy" Run-button hint in waterfall + knapsack.
"""

from knapsack_problem.brief_seed import derive_problem_panel_from_brief


def test_returns_none_when_brief_has_no_algorithm_mention():
    brief = {
        "items": [
            {
                "id": "g1",
                "text": "Maximize value within capacity.",
                "kind": "gathered",
                "source": "user",
            }
        ]
    }
    assert derive_problem_panel_from_brief(brief) is None


def test_returns_none_when_brief_has_no_items():
    assert derive_problem_panel_from_brief({}) is None
    assert derive_problem_panel_from_brief({"items": []}) is None
    assert derive_problem_panel_from_brief({"items": None}) is None


def test_seeds_algorithm_when_brief_mentions_genetic_search():
    brief = {
        "items": [
            {
                "id": "g1",
                "text": "Genetic search is being used.",
                "kind": "gathered",
                "source": "user",
            }
        ]
    }
    seed = derive_problem_panel_from_brief(brief)
    assert seed is not None
    inner = seed.get("problem") or {}
    assert inner.get("algorithm") == "GA"
    # The seed includes default budget so _backfill_solver_fields_from_seed
    # can fill them when the LLM panel-derive omits epochs/pop_size too.
    assert isinstance(inner.get("epochs"), int)
    assert isinstance(inner.get("pop_size"), int)
    assert isinstance(inner.get("algorithm_params"), dict)


def test_seeds_pso_when_brief_mentions_swarm_search():
    brief = {
        "items": [
            {
                "id": "g1",
                "text": "Using swarm search for this run.",
                "kind": "assumption",
                "source": "agent",
            }
        ]
    }
    seed = derive_problem_panel_from_brief(brief)
    assert seed is not None
    assert seed["problem"]["algorithm"] == "PSO"


def test_seeds_swarmsa_not_sa_for_compound_phrase():
    """Sanity-check the longest-match rule end-to-end via the seed."""
    brief = {
        "items": [
            {
                "id": "g1",
                "text": "Swarm-based simulated annealing as the search method.",
                "kind": "gathered",
                "source": "user",
            }
        ]
    }
    seed = derive_problem_panel_from_brief(brief)
    assert seed is not None
    assert seed["problem"]["algorithm"] == "SwarmSA"
