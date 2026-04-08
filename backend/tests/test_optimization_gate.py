import json

from app.optimization_gate import can_run_optimization, intrinsic_optimization_ready_agile, intrinsic_optimization_ready_waterfall
from app.problem_brief import default_problem_brief, normalize_problem_brief


def test_intrinsic_agile_requires_solver_surface():
    assert intrinsic_optimization_ready_agile(None) is False
    assert intrinsic_optimization_ready_agile({}) is False
    assert intrinsic_optimization_ready_agile({"weights": {"travel_time": 1}}) is True
    assert intrinsic_optimization_ready_agile({"problem": {"weights": {"travel_time": 1}}}) is True
    assert intrinsic_optimization_ready_agile({"algorithm": "PSO"}) is True


def test_intrinsic_waterfall_empty_questions_needs_milestone():
    brief = normalize_problem_brief(default_problem_brief())
    assert intrinsic_optimization_ready_waterfall(brief) is False
    brief2 = {**brief, "goal_summary": "Minimize cost"}
    assert intrinsic_optimization_ready_waterfall(normalize_problem_brief(brief2)) is True


def test_intrinsic_waterfall_blocks_open_question():
    brief = normalize_problem_brief(
        {
            **default_problem_brief(),
            "goal_summary": "x",
            "open_questions": [{"id": "q1", "text": "Why?", "status": "open", "answer_text": None}],
        }
    )
    assert intrinsic_optimization_ready_waterfall(brief) is False


def test_can_run_researcher_override():
    brief = default_problem_brief()
    panel = {"weights": {}}
    assert can_run_optimization("waterfall", False, panel, brief) is False
    assert can_run_optimization("waterfall", True, panel, brief) is True


def test_can_run_agile_intrinsic():
    brief = default_problem_brief()
    panel = json.loads(json.dumps({"problem": {"weights": {"travel_time": 10}}}))
    assert can_run_optimization("agile", False, panel, brief) is True
