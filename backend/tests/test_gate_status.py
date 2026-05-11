"""Tests for ``gate_status`` — the structured prerequisite snapshot used in
chat / brief-update / maintenance prompts to decide what to ask vs. assume."""

from app.optimization_gate import gate_status
from app.problem_brief import default_problem_brief, normalize_problem_brief
from app.problems.registry import get_study_port

_W1 = get_study_port("vrptw").weight_display_keys()[0]


def _empty_brief() -> dict:
    return normalize_problem_brief(default_problem_brief())


def test_gate_status_waterfall_missing_both():
    s = gate_status(
        "waterfall",
        panel_config={"problem": {}},
        problem_brief=_empty_brief(),
        optimization_gate_engaged=False,
        problem_id="vrptw",
    )
    assert s["goal_term_present"] is False
    assert s["search_strategy_present"] is False
    assert s["ready_to_run"] is False
    # Phase order: goal_term first, then search_strategy.
    assert s["missing"][:2] == ["goal_term", "search_strategy"]
    assert "gate_engaged" in s["missing"]


def test_gate_status_waterfall_missing_only_search_strategy():
    panel = {"problem": {"weights": {_W1: 10}}}
    s = gate_status(
        "waterfall",
        panel_config=panel,
        problem_brief=_empty_brief(),
        optimization_gate_engaged=True,
        problem_id="vrptw",
    )
    assert s["goal_term_present"] is True
    assert s["search_strategy_present"] is False
    # Head item is what waterfall must ask about next.
    assert s["missing"][0] == "search_strategy"


def test_gate_status_waterfall_ready():
    panel = {"problem": {"weights": {_W1: 10}, "algorithm": "GA"}}
    s = gate_status(
        "waterfall",
        panel_config=panel,
        problem_brief=_empty_brief(),
        optimization_gate_engaged=True,
        problem_id="vrptw",
    )
    assert s["ready_to_run"] is True
    assert s["missing"] == []


def test_gate_status_agile_missing_search_strategy_signals_assumption_cue():
    panel = {"problem": {"weights": {_W1: 10}}}
    s = gate_status(
        "agile",
        panel_config=panel,
        problem_brief=_empty_brief(),
        optimization_gate_engaged=True,
        problem_id="vrptw",
    )
    # Agile reads the same flags as waterfall — opposite action (assume vs ask).
    assert s["goal_term_present"] is True
    assert s["search_strategy_present"] is False
    assert s["missing"] == ["search_strategy"]


def test_gate_status_demo_missing_goal_term():
    s = gate_status(
        "demo",
        panel_config={"problem": {}},
        problem_brief=_empty_brief(),
        optimization_gate_engaged=False,
        problem_id="vrptw",
    )
    assert s["missing"] == ["goal_term", "search_strategy"]
    # Demo doesn't gate on engagement.
    assert "gate_engaged" not in s["missing"]
