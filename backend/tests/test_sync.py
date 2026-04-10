import json
from types import SimpleNamespace

from app.routers.sessions import sync


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
                    "weights": {"travel_time": 9.0, "fuel_cost": 1.0},
                    "locked_goal_terms": ["travel_time"],
                    "algorithm": "GA",
                }
            }
        ),
        workflow_mode="agile",
        updated_at=None,
    )

    monkeypatch.setattr(
        "app.problem_config_seed.derive_problem_panel_from_brief",
        lambda _brief: {"problem": {"weights": {"travel_time": 1.0, "fuel_cost": 3.0}}},
    )

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief={"items": []},
        api_key=None,
        model_name=None,
    )

    assert panel is not None
    assert panel["problem"]["weights"]["travel_time"] == 9.0
    assert panel["problem"]["weights"]["fuel_cost"] == 3.0
    assert panel["problem"]["locked_goal_terms"] == ["travel_time"]
