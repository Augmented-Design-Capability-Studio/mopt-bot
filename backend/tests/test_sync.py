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
                    "weights": {"travel_time": 9.0, "shift_overtime": 1.0},
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
        return {"problem": {"weights": {"travel_time": 1.0, "shift_overtime": 3.0}}}

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
    assert panel["problem"]["weights"]["shift_overtime"] == 3.0
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
        return {"problem": {"weights": {"travel_time": 1.0, "shift_overtime": 3.0}}}

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
