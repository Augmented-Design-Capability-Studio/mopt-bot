"""Light checks that benchmark appendix is omitted when the chat is cold."""

from app.problem_brief import default_problem_brief
from app.problems.registry import get_study_port
from app.services import llm


def test_system_prompt_openers_skip_appendix_when_cold_knapsack():
    apx = get_study_port("knapsack").study_prompt_appendix() or ""
    assert "0/1 knapsack" in apx
    parts = llm._system_prompt_openers("knapsack", default_problem_brief("knapsack"))
    assert len(parts) == 1
    joined = "\n\n".join(parts)
    assert "0/1 knapsack" not in joined


def test_system_prompt_openers_includes_appendix_when_warm_knapsack():
    b = default_problem_brief("knapsack")
    b = {**b, "goal_summary": "Pack high value under capacity."}
    parts = llm._system_prompt_openers("knapsack", b)
    assert len(parts) == 2
    assert "0/1 knapsack" in parts[1]
