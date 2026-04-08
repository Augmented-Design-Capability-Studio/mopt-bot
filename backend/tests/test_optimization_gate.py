import json
from datetime import datetime, timezone
from types import SimpleNamespace

from app.optimization_gate import can_run_optimization, intrinsic_optimization_ready_agile, intrinsic_optimization_ready_waterfall
from app.problem_brief import default_problem_brief, normalize_problem_brief
from app.routers.sessions import helpers as session_helpers


def test_intrinsic_agile_requires_goal_weight_and_algorithm():
    assert intrinsic_optimization_ready_agile(None) is False
    assert intrinsic_optimization_ready_agile({}) is False
    assert intrinsic_optimization_ready_agile({"weights": {"travel_time": 1}}) is False
    assert intrinsic_optimization_ready_agile({"algorithm": "PSO"}) is False
    panel_ok = json.loads(json.dumps({"problem": {"weights": {"travel_time": 1}, "algorithm": "GA"}}))
    assert intrinsic_optimization_ready_agile(panel_ok) is True
    assert intrinsic_optimization_ready_agile({"problem": {"weights": {"travel_time": 1}, "algorithm": "GA"}}) is True


def test_intrinsic_waterfall_requires_engagement():
    brief = normalize_problem_brief(default_problem_brief())
    assert intrinsic_optimization_ready_waterfall(brief, optimization_gate_engaged=False) is False
    assert intrinsic_optimization_ready_waterfall(brief, optimization_gate_engaged=True) is True


def test_intrinsic_waterfall_engaged_empty_oq_no_panel_fallback():
    brief = normalize_problem_brief(default_problem_brief())
    assert intrinsic_optimization_ready_waterfall(brief, optimization_gate_engaged=True) is True
    panel = json.loads(json.dumps({"problem": {"weights": {"travel_time": 10}}}))
    assert can_run_optimization("waterfall", False, False, panel, brief, optimization_gate_engaged=True) is True


def test_intrinsic_waterfall_blocks_open_question_when_engaged():
    brief = normalize_problem_brief(
        {
            **default_problem_brief(),
            "open_questions": [{"id": "q1", "text": "Why?", "status": "open", "answer_text": None}],
        }
    )
    assert intrinsic_optimization_ready_waterfall(brief, optimization_gate_engaged=True) is False


def test_can_run_researcher_override():
    brief = default_problem_brief()
    panel = {"weights": {}}
    assert can_run_optimization("waterfall", False, False, panel, brief, optimization_gate_engaged=False) is False
    assert can_run_optimization("waterfall", True, False, panel, brief, optimization_gate_engaged=False) is True


def test_can_run_agile_intrinsic():
    brief = default_problem_brief()
    panel = json.loads(json.dumps({"problem": {"weights": {"travel_time": 10}, "algorithm": "GA"}}))
    assert can_run_optimization("agile", False, False, panel, brief, optimization_gate_engaged=False) is True


def test_can_run_researcher_block_overrides_intrinsic():
    brief = default_problem_brief()
    panel = json.loads(json.dumps({"problem": {"weights": {"travel_time": 10}, "algorithm": "GA"}}))
    assert can_run_optimization("agile", True, True, panel, brief, optimization_gate_engaged=False) is False
    assert can_run_optimization("agile", False, True, panel, brief, optimization_gate_engaged=False) is False


def test_waterfall_participant_sync_clears_permit_when_open_questions():
    brief = normalize_problem_brief(
        {
            **default_problem_brief(),
            "open_questions": [{"id": "q1", "text": "Why?", "status": "open", "answer_text": None}],
        }
    )
    row = SimpleNamespace(
        workflow_mode="waterfall",
        panel_config_json=json.dumps({}),
        problem_brief_json=json.dumps(brief),
        optimization_allowed=True,
        optimization_gate_engaged=False,
        updated_at=datetime.now(timezone.utc),
    )
    assert session_helpers.sync_optimization_allowed_after_participant_mutation(row) is True
    assert row.optimization_allowed is False
    assert row.optimization_gate_engaged is True


def test_waterfall_participant_sync_sets_true_when_intrinsic_ready():
    brief = normalize_problem_brief(default_problem_brief())
    row = SimpleNamespace(
        workflow_mode="waterfall",
        panel_config_json=None,
        problem_brief_json=json.dumps(brief),
        optimization_allowed=False,
        optimization_gate_engaged=True,
        updated_at=datetime.now(timezone.utc),
    )
    assert session_helpers.sync_optimization_allowed_after_participant_mutation(row) is True
    assert row.optimization_allowed is True


def test_waterfall_participant_sync_no_op_when_already_allowed_and_ready():
    brief = normalize_problem_brief(default_problem_brief())
    row = SimpleNamespace(
        workflow_mode="waterfall",
        panel_config_json=None,
        problem_brief_json=json.dumps(brief),
        optimization_allowed=True,
        optimization_gate_engaged=True,
        updated_at=datetime.now(timezone.utc),
    )
    assert session_helpers.sync_optimization_allowed_after_participant_mutation(row) is False


def test_agile_participant_sync_sets_allowed_from_panel():
    row = SimpleNamespace(
        workflow_mode="agile",
        panel_config_json=json.dumps({"problem": {"weights": {"travel_time": 1}, "algorithm": "PSO"}}),
        problem_brief_json=json.dumps(default_problem_brief()),
        optimization_allowed=False,
        optimization_gate_engaged=False,
        updated_at=datetime.now(timezone.utc),
    )
    assert session_helpers.sync_optimization_allowed_after_participant_mutation(row) is True
    assert row.optimization_allowed is True


def test_agile_participant_sync_clears_allowed_when_panel_not_intrinsic_ready():
    row = SimpleNamespace(
        workflow_mode="agile",
        panel_config_json=None,
        problem_brief_json=json.dumps(default_problem_brief()),
        optimization_allowed=True,
        optimization_gate_engaged=False,
        updated_at=datetime.now(timezone.utc),
    )
    assert session_helpers.sync_optimization_allowed_after_participant_mutation(row) is True
    assert row.optimization_allowed is False
