import json
from types import SimpleNamespace

from app.problems.registry import get_study_port
from app.routers.sessions import sync

VrptwStudyPort = type(get_study_port("vrptw"))
_DEFAULT_PORT = get_study_port("vrptw")
_DEFAULT_WEIGHT_KEYS = _DEFAULT_PORT.weight_display_keys()
_W1 = _DEFAULT_WEIGHT_KEYS[0]
_W2 = _DEFAULT_WEIGHT_KEYS[1] if len(_DEFAULT_WEIGHT_KEYS) > 1 else _DEFAULT_WEIGHT_KEYS[0]


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
                    "weights": {_W1: 9.0, _W2: 1.0},
                    "locked_goal_terms": [_W1],
                    "algorithm": "GA",
                }
            }
        ),
        workflow_mode="agile",
        test_problem_id="vrptw",
        updated_at=None,
    )

    def _fake_derive(self, _brief):
        return {"problem": {"weights": {_W1: 1.0, _W2: 3.0}}}

    monkeypatch.setattr(VrptwStudyPort, "derive_problem_panel_from_brief", _fake_derive)

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief={"items": []},
        api_key=None,
        model_name=None,
    )

    assert panel is not None
    assert panel["problem"]["goal_terms"][_W1]["weight"] == 9.0
    assert panel["problem"]["goal_terms"][_W2]["weight"] == 3.0
    assert panel["problem"]["locked_goal_terms"] == [_W1]


def test_sync_panel_from_brief_normalizes_stale_locked_goal_terms(monkeypatch):
    row = SimpleNamespace(
        panel_config_json=json.dumps(
            {
                "problem": {
                    "weights": {_W1: 9.0},
                    "locked_goal_terms": [_W1, "ghost_key"],
                    "algorithm": "GA",
                }
            }
        ),
        workflow_mode="agile",
        test_problem_id="vrptw",
        updated_at=None,
    )

    def _fake_derive(self, _brief):
        return {"problem": {"weights": {_W1: 1.0, _W2: 3.0}}}

    monkeypatch.setattr(VrptwStudyPort, "derive_problem_panel_from_brief", _fake_derive)

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief={"items": []},
        api_key=None,
        model_name=None,
    )

    assert panel is not None
    assert panel["problem"]["goal_terms"][_W1]["weight"] == 9.0
    assert panel["problem"]["locked_goal_terms"] == [_W1]
    assert "ghost_key" not in panel["problem"]["locked_goal_terms"]


def test_sync_panel_from_brief_non_destructive_when_llm_omits_weight(monkeypatch):
    row = SimpleNamespace(
        panel_config_json=json.dumps(
            {
                "problem": {
                    "weights": {_W1: 2.0, _W2: 100.0},
                    "algorithm": "GA",
                }
            }
        ),
        workflow_mode="agile",
        test_problem_id="vrptw",
        updated_at=None,
    )

    def _fake_derive(self, _brief):
        return {"problem": {"weights": {_W1: 3.0}}}

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
    assert panel["problem"]["goal_terms"][_W1]["weight"] == 3.0
    assert panel["problem"]["goal_terms"][_W2]["weight"] == 100.0


def test_sync_preserves_manual_termination_and_init_controls(monkeypatch):
    row = SimpleNamespace(
        panel_config_json=json.dumps(
            {
                "problem": {
                    "weights": {_W1: 1.0},
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
                "weights": {_W1: 2.0},
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
                    "weights": {_W1: 1.0, _W2: 1000.0},
                    "constraint_types": {_W2: "hard"},
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
                "weights": {_W1: 1.0, _W2: 1000.0},
                "constraint_types": {_W2: "hard"},
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

