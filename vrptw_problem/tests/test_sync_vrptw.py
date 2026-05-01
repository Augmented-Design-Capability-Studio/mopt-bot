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
    assert panel["problem"]["goal_terms"]["worker_preference"]["weight"] == 5.0
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


def test_vrptw_sanitize_drops_legacy_constraint_lists_and_builds_goal_terms():
    port = get_study_port("vrptw")
    panel, _warnings = port.sanitize_panel_config(
        {
            "problem": {
                "weights": {"travel_time": 7.13, "capacity_penalty": 500, "lateness_penalty": 100},
                "constraint_types": {"lateness_penalty": "hard", "capacity_penalty": "hard"},
                "hard_constraints": ["capacity_penalty"],
                "soft_constraints": ["travel_time", "algorithm_params", "algorithm"],
                "locked_goal_terms": ["lateness_penalty"],
                "algorithm": "GA",
            }
        }
    )
    problem = panel["problem"]
    assert "hard_constraints" not in problem
    assert "soft_constraints" not in problem
    assert "weights" not in problem
    assert "constraint_types" not in problem
    assert "goal_terms" in problem
    assert problem["goal_terms"]["travel_time"]["type"] == "objective"
    assert problem["goal_terms"]["travel_time"]["rank"] == 1
    assert problem["goal_terms"]["capacity_penalty"]["type"] == "hard"
    assert problem["goal_terms"]["capacity_penalty"]["rank"] == 2
    assert problem["goal_terms"]["lateness_penalty"]["locked"] is True


def test_vrptw_parse_problem_config_accepts_goal_terms_overlay():
    port = get_study_port("vrptw")
    parsed = port.parse_problem_config(
        {
            "goal_terms": {
                "travel_time": {"weight": 7.13, "type": "objective"},
                "capacity_penalty": {"weight": 500, "type": "hard"},
                "lateness_penalty": {"weight": 100, "type": "hard", "locked": True},
                "worker_preference": {
                    "weight": 12,
                    "type": "soft",
                    "properties": {
                        "driver_preferences": [
                            {"vehicle_idx": 0, "condition": "avoid_zone", "zone": 4, "penalty": 8}
                        ]
                    },
                },
                "shift_limit": {
                    "weight": 400,
                    "type": "hard",
                    "properties": {"max_shift_hours": 7.5},
                },
            },
            "algorithm": "GA",
            "epochs": 100,
            "pop_size": 50,
        }
    )
    assert parsed["weights"]["w1"] == 7.13
    assert parsed["weights"]["w4"] == 500.0
    assert parsed["weights"]["w3"] == 100.0
    assert parsed["weights"]["w6"] == 12.0
    assert parsed["weights"]["w2"] == 400.0
    assert parsed["max_shift_hours"] == 7.5
    assert len(parsed["driver_preferences"]) == 1
    assert parsed["driver_preferences"][0]["condition"] == "avoid_zone"
