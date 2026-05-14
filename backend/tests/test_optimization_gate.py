import json
from datetime import datetime, timezone
from types import SimpleNamespace

from app.optimization_gate import (
    _qualifying_goal_term_present,
    can_run_optimization,
    intrinsic_optimization_ready,
)
from app.problem_brief import default_problem_brief, normalize_problem_brief
from app.problems.registry import get_study_port
from app.routers.sessions import helpers as session_helpers

# Default problem keys used for problem-agnostic backend gate tests.
_DEFAULT_PORT = get_study_port("vrptw")
_DEFAULT_WDK = _DEFAULT_PORT.weight_display_keys()
_DEFAULT_GCC = _DEFAULT_PORT.gate_conditional_companions()
_W1 = _DEFAULT_WDK[0]


def _brief() -> dict:
    return default_problem_brief()


def test_intrinsic_requires_goal_weight_and_algorithm_in_agile():
    """Agile: algorithm + qualifying goal term + gate_engaged are all required."""
    brief = _brief()
    args = dict(workflow_mode="agile", problem_brief=brief, optimization_gate_engaged=True, problem_id="vrptw")
    assert intrinsic_optimization_ready(panel_config=None, **args) is False
    assert intrinsic_optimization_ready(panel_config={}, **args) is False
    assert intrinsic_optimization_ready(panel_config={"weights": {_W1: 1}}, **args) is False  # no algo
    assert intrinsic_optimization_ready(panel_config={"algorithm": "PSO"}, **args) is False  # no weight
    panel_ok = json.loads(json.dumps({"problem": {"weights": {_W1: 1}, "algorithm": "GA"}}))
    assert intrinsic_optimization_ready(panel_config=panel_ok, **args) is True


def test_intrinsic_requires_gate_engaged_across_all_modes():
    """Strict symmetry: agile / waterfall / demo all require gate_engaged."""
    brief = _brief()
    panel = {"problem": {"weights": {_W1: 1}, "algorithm": "GA"}}
    for mode in ("agile", "waterfall", "demo"):
        assert intrinsic_optimization_ready(
            workflow_mode=mode,
            panel_config=panel,
            problem_brief=brief,
            optimization_gate_engaged=False,
            problem_id="vrptw",
        ) is False, f"{mode} should not be ready without gate_engaged"
        assert intrinsic_optimization_ready(
            workflow_mode=mode,
            panel_config=panel,
            problem_brief=brief,
            optimization_gate_engaged=True,
            problem_id="vrptw",
        ) is True, f"{mode} should be ready with gate_engaged"


def test_intrinsic_waterfall_blocks_on_open_questions():
    """Only waterfall enforces the open-questions check."""
    panel = {"problem": {"weights": {_W1: 1}, "algorithm": "GA"}}
    brief_with_oq = normalize_problem_brief(
        {
            **_brief(),
            "open_questions": [{"id": "q1", "text": "Why?", "status": "open", "answer_text": None}],
        }
    )
    args = dict(panel_config=panel, problem_brief=brief_with_oq, optimization_gate_engaged=True, problem_id="vrptw")
    assert intrinsic_optimization_ready(workflow_mode="waterfall", **args) is False
    # Agile and demo ignore open questions.
    assert intrinsic_optimization_ready(workflow_mode="agile", **args) is True
    assert intrinsic_optimization_ready(workflow_mode="demo", **args) is True


def test_qualifying_goal_term_companion_required_semantics():
    """A goal-term key with a registered companion contributes to the gate
    iff the companion is present — weight alone is NOT sufficient.

    Implements the "require a defined property if that's the only goal term"
    rule: when a companion-having key is the only thing the participant has
    touched, the gate stays closed until they actually supply the property.
    """
    wdk = ["alpha", "beta"]
    gcc = {"alpha": "alpha_companion", "beta": "beta_companion"}

    # Companion alone opens the gate (no weight needed).
    assert _qualifying_goal_term_present({"alpha_companion": [{"x": 1}]}, wdk, gcc) is True
    assert _qualifying_goal_term_present({"beta_companion": [{"y": 1}]}, wdk, gcc) is True
    # Empty companions and no weights → closed.
    assert _qualifying_goal_term_present({"alpha_companion": [], "beta_companion": []}, wdk, gcc) is False
    # Weight alone on a companion-required key does NOT open the gate.
    assert _qualifying_goal_term_present({"weights": {"alpha": 1}}, wdk, gcc) is False
    # Weight + companion both present → opens.
    assert _qualifying_goal_term_present(
        {"weights": {"alpha": 1}, "alpha_companion": [{"x": 1}]}, wdk, gcc
    ) is True


def test_qualifying_goal_term_companion_key_rides_alongside_non_companion_weight():
    """When a companion-required key has weight-only but a non-companion key
    is also weighted, the non-companion key opens the gate. The companion
    key just doesn't contribute — but it doesn't block either.
    """
    wdk = ["plain", "with_companion"]
    gcc = {"with_companion": "structured_data"}

    # plain has weight, with_companion has weight but empty companion → gate opens via plain.
    assert _qualifying_goal_term_present(
        {"weights": {"plain": 1, "with_companion": 1}}, wdk, gcc
    ) is True
    # Same but with_companion's weight removed → still opens via plain.
    assert _qualifying_goal_term_present(
        {"weights": {"plain": 1}}, wdk, gcc
    ) is True
    # Drop the plain weight → only with_companion's weight-only remains → closed.
    assert _qualifying_goal_term_present(
        {"weights": {"with_companion": 1}}, wdk, gcc
    ) is False


def test_qualifying_goal_term_uses_port_companion_predicate():
    """Scalar companions use the port's predicate; the default's list-only
    check would always return False for a number, so the predicate hook
    matters for problems like VRPTW's shift_limit / max_shift_hours.
    """
    wdk = ["shifty"]
    gcc = {"shifty": "max_hours"}

    def positive_number(_key: str, value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0

    # max_hours=0 fails the predicate even though it's "set".
    assert _qualifying_goal_term_present({"max_hours": 0}, wdk, gcc, companion_present=positive_number) is False
    # max_hours=8 passes.
    assert _qualifying_goal_term_present({"max_hours": 8}, wdk, gcc, companion_present=positive_number) is True


def test_qualifying_goal_term_falls_back_to_any_weight_when_no_display_keys():
    """When the port supplies no display keys (empty list), any weight counts."""
    assert _qualifying_goal_term_present({"weights": {"foo": 1}}, [], {}) is True
    assert _qualifying_goal_term_present({}, [], {}) is False


def test_vrptw_gate_blocks_worker_preference_weight_without_driver_preferences():
    """VRPTW: setting `worker_preference` weight alone (no `driver_preferences`)
    is the 'companion-required goal term as the only term' case — gate stays
    closed. This is a behaviour change from the prior implementation, which
    had dead code that effectively let weight-alone open the gate."""
    panel = {"problem": {"weights": {"worker_preference": 1.0}, "algorithm": "GA"}}
    assert intrinsic_optimization_ready(
        workflow_mode="agile",
        panel_config=panel,
        problem_brief=_brief(),
        optimization_gate_engaged=True,
        problem_id="vrptw",
    ) is False


def test_vrptw_gate_opens_when_driver_preferences_set_without_weight():
    """VRPTW: `driver_preferences` non-empty opens the gate even without an
    explicit `worker_preference` weight, since the companion IS the content."""
    panel = {
        "problem": {
            "weights": {},
            "driver_preferences": [{"vehicle_idx": 0, "condition": "avoid_zone", "zone": 1, "penalty": 5.0}],
            "algorithm": "GA",
        }
    }
    assert intrinsic_optimization_ready(
        workflow_mode="agile",
        panel_config=panel,
        problem_brief=_brief(),
        optimization_gate_engaged=True,
        problem_id="vrptw",
    ) is True


def test_vrptw_gate_blocks_shift_limit_weight_with_zero_max_shift_hours():
    """VRPTW: `shift_limit` is now also a gate-conditional companion goal term.
    A weight without a positive `max_shift_hours` is meaningless ('penalty above
    zero hours'), so the gate stays closed."""
    panel = {
        "problem": {
            "weights": {"shift_limit": 1.0},
            "max_shift_hours": 0,
            "algorithm": "GA",
        }
    }
    assert intrinsic_optimization_ready(
        workflow_mode="agile",
        panel_config=panel,
        problem_brief=_brief(),
        optimization_gate_engaged=True,
        problem_id="vrptw",
    ) is False
    # Same panel but with a positive max_shift_hours → opens.
    panel["problem"]["max_shift_hours"] = 8.0
    assert intrinsic_optimization_ready(
        workflow_mode="agile",
        panel_config=panel,
        problem_brief=_brief(),
        optimization_gate_engaged=True,
        problem_id="vrptw",
    ) is True


def test_can_run_requires_uploaded_data_in_every_mode():
    """Strict symmetry: every mode requires has_uploaded_data."""
    brief = _brief()
    panel = json.loads(json.dumps({"problem": {"weights": {_W1: 10}, "algorithm": "GA"}}))
    for mode in ("agile", "waterfall", "demo"):
        assert can_run_optimization(
            mode, False, False, panel, brief,
            has_uploaded_data=False, optimization_gate_engaged=True,
        ) is False, f"{mode} should block without uploaded data"


def test_can_run_agile_intrinsic():
    brief = _brief()
    panel = json.loads(json.dumps({"problem": {"weights": {_W1: 10}, "algorithm": "GA"}}))
    assert can_run_optimization(
        "agile", False, False, panel, brief, optimization_gate_engaged=True,
    ) is True


def test_can_run_researcher_block_overrides_intrinsic():
    brief = _brief()
    panel = json.loads(json.dumps({"problem": {"weights": {_W1: 10}, "algorithm": "GA"}}))
    assert can_run_optimization("agile", True, True, panel, brief, optimization_gate_engaged=True) is False
    assert can_run_optimization("agile", False, True, panel, brief, optimization_gate_engaged=True) is False


def test_waterfall_participant_sync_clears_permit_when_open_questions():
    brief = normalize_problem_brief(
        {
            **_brief(),
            "open_questions": [{"id": "q1", "text": "Why?", "status": "open", "answer_text": None}],
        }
    )
    row = SimpleNamespace(
        workflow_mode="waterfall",
        test_problem_id="vrptw",
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
    brief = _brief()
    row = SimpleNamespace(
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        panel_config_json=json.dumps({"problem": {"weights": {_W1: 10}, "algorithm": "GA"}}),
        problem_brief_json=json.dumps(brief),
        optimization_allowed=False,
        optimization_gate_engaged=True,
        updated_at=datetime.now(timezone.utc),
    )
    assert session_helpers.sync_optimization_allowed_after_participant_mutation(row) is True
    assert row.optimization_allowed is True


def test_agile_participant_sync_sets_allowed_from_panel():
    row = SimpleNamespace(
        workflow_mode="agile",
        test_problem_id="vrptw",
        panel_config_json=json.dumps({"problem": {"weights": {_W1: 1}, "algorithm": "PSO"}}),
        problem_brief_json=json.dumps(_brief()),
        optimization_allowed=False,
        optimization_gate_engaged=True,
        updated_at=datetime.now(timezone.utc),
    )
    assert session_helpers.sync_optimization_allowed_after_participant_mutation(row) is True
    assert row.optimization_allowed is True


def test_agile_participant_sync_clears_allowed_when_panel_not_intrinsic_ready():
    row = SimpleNamespace(
        workflow_mode="agile",
        test_problem_id="vrptw",
        panel_config_json=None,
        problem_brief_json=json.dumps(_brief()),
        optimization_allowed=True,
        optimization_gate_engaged=False,
        updated_at=datetime.now(timezone.utc),
    )
    assert session_helpers.sync_optimization_allowed_after_participant_mutation(row) is True
    assert row.optimization_allowed is False
