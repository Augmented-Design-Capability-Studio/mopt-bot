import json
from types import SimpleNamespace

from app.problems.registry import get_study_port
from app.routers.sessions import sync

VrptwStudyPort = type(get_study_port("vrptw"))


class _DummyDb:
    def commit(self) -> None:
        return None

    def refresh(self, _row) -> None:
        return None


def test_sync_panel_from_brief_preserves_locked_goal_terms(monkeypatch):
    row = SimpleNamespace(
        panel_config_json=json.dumps(
            {
                "problem": {
                    "weights": {"travel_time": 9.0, "shift_limit": 1.0},
                    "locked_goal_terms": ["travel_time"],
                    "algorithm": "GA",
                }
            }
        ),
        workflow_mode="agile",
        test_problem_id="vrptw",
        updated_at=None,
    )

    def _fake_derive(self, _brief):
        return {"problem": {"weights": {"travel_time": 1.0, "shift_limit": 3.0}}}

    monkeypatch.setattr(VrptwStudyPort, "derive_problem_panel_from_brief", _fake_derive)

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief={"items": []},
        api_key=None,
        model_name=None,
    )

    assert panel is not None
    assert panel["problem"]["weights"]["travel_time"] == 9.0
    assert panel["problem"]["weights"]["shift_limit"] == 3.0
    assert panel["problem"]["locked_goal_terms"] == ["travel_time"]


def test_sync_panel_from_brief_normalizes_stale_locked_goal_terms(monkeypatch):
    row = SimpleNamespace(
        panel_config_json=json.dumps(
            {
                "problem": {
                    "weights": {"travel_time": 9.0},
                    "locked_goal_terms": ["travel_time", "ghost_key"],
                    "algorithm": "GA",
                }
            }
        ),
        workflow_mode="agile",
        test_problem_id="vrptw",
        updated_at=None,
    )

    def _fake_derive(self, _brief):
        return {"problem": {"weights": {"travel_time": 1.0, "shift_limit": 3.0}}}

    monkeypatch.setattr(VrptwStudyPort, "derive_problem_panel_from_brief", _fake_derive)

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief={"items": []},
        api_key=None,
        model_name=None,
    )

    assert panel is not None
    assert panel["problem"]["weights"]["travel_time"] == 9.0
    assert panel["problem"]["locked_goal_terms"] == ["travel_time"]
    assert "ghost_key" not in panel["problem"]["locked_goal_terms"]


def test_sync_panel_from_brief_non_destructive_when_llm_omits_weight(monkeypatch):
    row = SimpleNamespace(
        panel_config_json=json.dumps(
            {
                "problem": {
                    "weights": {"travel_time": 2.0, "capacity_penalty": 100.0},
                    "algorithm": "GA",
                }
            }
        ),
        workflow_mode="agile",
        test_problem_id="vrptw",
        updated_at=None,
    )

    def _fake_derive(self, _brief):
        return {"problem": {"weights": {"travel_time": 3.0}}}

    monkeypatch.setattr(VrptwStudyPort, "derive_problem_panel_from_brief", _fake_derive)

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief={"items": []},
        api_key=None,
        model_name=None,
        preserve_missing_managed_fields=True,
    )

    assert panel is not None
    assert panel["problem"]["weights"]["travel_time"] == 3.0
    assert panel["problem"]["weights"]["capacity_penalty"] == 100.0


def test_sync_preserves_driver_preferences_when_worker_preference_locked(monkeypatch):
    current_prefs = [
        {
            "vehicle_idx": 0,
            "condition": "avoid_zone",
            "penalty": 2.0,
            "zone": 3,
            "aggregation": "per_stop",
        }
    ]
    derived_prefs = [
        {
            "vehicle_idx": 1,
            "condition": "order_priority",
            "penalty": 1.0,
            "order_priority": "standard",
            "aggregation": "per_stop",
        }
    ]
    row = SimpleNamespace(
        panel_config_json=json.dumps(
            {
                "problem": {
                    "weights": {"travel_time": 1.0, "worker_preference": 5.0},
                    "locked_goal_terms": ["worker_preference"],
                    "driver_preferences": current_prefs,
                    "algorithm": "GA",
                }
            }
        ),
        workflow_mode="agile",
        test_problem_id="vrptw",
        updated_at=None,
    )

    def _fake_derive(self, _brief):
        return {
            "problem": {
                "weights": {"travel_time": 9.0, "worker_preference": 99.0},
                "driver_preferences": derived_prefs,
            }
        }

    monkeypatch.setattr(VrptwStudyPort, "derive_problem_panel_from_brief", _fake_derive)

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief={"items": []},
        api_key=None,
        model_name=None,
    )

    assert panel is not None
    assert panel["problem"]["weights"]["worker_preference"] == 5.0
    assert panel["problem"]["driver_preferences"] == current_prefs


def test_sync_replaces_driver_preferences_when_not_derived(monkeypatch):
    row = SimpleNamespace(
        panel_config_json=json.dumps(
            {
                "problem": {
                    "weights": {"travel_time": 1.0, "worker_preference": 5.0},
                    "driver_preferences": [
                        {
                            "vehicle_idx": 0,
                            "condition": "avoid_zone",
                            "penalty": 3.0,
                            "zone": 3,
                            "aggregation": "per_stop",
                        }
                    ],
                    "algorithm": "GA",
                }
            }
        ),
        workflow_mode="agile",
        test_problem_id="vrptw",
        updated_at=None,
    )

    def _fake_derive(self, _brief):
        return {"problem": {"weights": {"travel_time": 2.0}, "algorithm": "PSO"}}

    monkeypatch.setattr(VrptwStudyPort, "derive_problem_panel_from_brief", _fake_derive)

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief={"items": []},
        api_key=None,
        model_name=None,
    )

    assert panel is not None
    assert panel["problem"].get("driver_preferences", []) == []


def test_sync_preserves_manual_termination_and_init_controls(monkeypatch):
    row = SimpleNamespace(
        panel_config_json=json.dumps(
            {
                "problem": {
                    "weights": {"travel_time": 1.0},
                    "algorithm": "GA",
                    "early_stop": False,
                    "early_stop_patience": 77,
                    "early_stop_epsilon": 0.005,
                    "use_greedy_init": True,
                }
            }
        ),
        workflow_mode="agile",
        test_problem_id="vrptw",
        updated_at=None,
    )

    def _fake_derive(self, _brief):
        return {
            "problem": {
                "weights": {"travel_time": 2.0},
                "algorithm": "PSO",
                "early_stop": True,
                "early_stop_patience": 3,
                "early_stop_epsilon": 1e-6,
                "use_greedy_init": False,
            }
        }

    monkeypatch.setattr(VrptwStudyPort, "derive_problem_panel_from_brief", _fake_derive)

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief={"items": []},
        api_key=None,
        model_name=None,
        preserve_missing_managed_fields=True,
    )

    assert panel is not None
    assert panel["problem"]["algorithm"] == "PSO"
    assert panel["problem"]["early_stop"] is False
    assert panel["problem"]["early_stop_patience"] == 77
    assert abs(float(panel["problem"]["early_stop_epsilon"]) - 0.005) < 1e-12
    assert panel["problem"]["use_greedy_init"] is True


def test_sync_backfills_search_strategy_when_llm_returns_weights_only(monkeypatch):
    """LLM panel patches may omit algorithm/epochs; deterministic brief seed fills them."""
    row = SimpleNamespace(
        panel_config_json=json.dumps(
            {
                "problem": {
                    "weights": {"travel_time": 1.0, "capacity_penalty": 1000.0},
                    "constraint_types": {"capacity_penalty": "hard"},
                    "hard_constraints": ["capacity_penalty"],
                    "soft_constraints": ["travel_time"],
                }
            }
        ),
        workflow_mode="agile",
        test_problem_id="vrptw",
        updated_at=None,
        id="test-session",
    )
    brief = {
        "items": [
            {
                "kind": "gathered",
                "text": "Confirmed Genetic Algorithm (GA) as the search strategy.",
                "status": "active",
                "source": "user",
            },
            {
                "kind": "gathered",
                "text": "Setting default search budget of 100 epochs with a population size of 50.",
                "status": "active",
                "source": "agent",
            },
        ]
    }

    def _fake_llm(**_kwargs):
        return {
            "problem": {
                "weights": {"travel_time": 1.0, "capacity_penalty": 1000.0},
                "constraint_types": {"capacity_penalty": "hard"},
                "hard_constraints": ["capacity_penalty"],
                "soft_constraints": ["travel_time"],
            }
        }

    monkeypatch.setattr("app.services.llm.generate_config_from_brief", _fake_llm)

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief=brief,
        api_key="fake-key",
        model_name="fake-model",
    )

    assert panel is not None
    prob = panel["problem"]
    assert prob["algorithm"] == "GA"
    assert prob["epochs"] == 100
    assert prob["pop_size"] == 50
    assert prob["algorithm_params"] == {"pc": 0.9, "pm": 0.05}
