import json
from types import SimpleNamespace

import pytest

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

    panel, _warnings, _grounding = sync.sync_panel_from_problem_brief(
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

    panel, _warnings, _grounding = sync.sync_panel_from_problem_brief(
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

    panel, _warnings, _grounding = sync.sync_panel_from_problem_brief(
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

    panel, _warnings, _grounding = sync.sync_panel_from_problem_brief(
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

    panel, _warnings, _grounding = sync.sync_panel_from_problem_brief(
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


def test_validate_problem_goal_terms_rejects_missing_type():
    with pytest.raises(sync.GoalTermValidationError) as excinfo:
        sync.validate_problem_goal_terms(
            problem={
                "goal_terms": {
                    "travel_time": {"weight": 1.0},
                }
            },
            problem_brief={"items": [{"id": "config-weight-travel_time", "kind": "gathered", "text": "travel"}]},
            weight_slot_markers={"travel_time": ("travel",)},
        )
    assert any(r["code"] == "goal_term_type_invalid" for r in excinfo.value.reasons)


def test_validate_problem_goal_terms_returns_grounding_warnings_without_raising():
    """Hallucination-style mismatches are returned as warnings, not raised. The
    panel save proceeds; downstream surfaces the warning as participant advice."""
    warnings = sync.validate_problem_goal_terms(
        problem={
            "goal_terms": {
                "travel_time": {"weight": 1.0, "type": "objective"},
                "capacity_penalty": {"weight": 1000.0, "type": "hard"},
            }
        },
        problem_brief={
            "items": [
                {"id": "config-weight-travel_time", "kind": "gathered", "text": "minimize travel time"}
            ]
        },
        weight_slot_markers={"travel_time": ("travel",), "capacity_penalty": ("capacity",)},
    )
    keys = {w["key"] for w in warnings if w["code"] == "goal_term_hallucinated"}
    assert keys == {"capacity_penalty"}


def test_validate_problem_goal_terms_check_grounding_false_returns_no_warnings():
    """User-driven panel saves skip grounding entirely — the participant is authoritative."""
    warnings = sync.validate_problem_goal_terms(
        problem={
            "goal_terms": {
                "capacity_penalty": {"weight": 1000.0, "type": "hard"},
            }
        },
        problem_brief={"items": [], "open_questions": [], "goal_summary": ""},
        weight_slot_markers={"capacity_penalty": ("capacity",)},
        check_grounding=False,
    )
    assert warnings == []


def test_validate_problem_goal_terms_cold_start_no_grounding_signal_passes():
    """Cold-start tolerance: when the brief has no grounded keys at all (sparse
    cold-start brief), the validator does NOT flag every panel key as
    hallucinated. The structured-output schema's allowed-key set is the
    primary defense in this window — the marker check has nothing to anchor on
    yet, so insisting on grounding here would flunk the very first turn."""
    # No items match any marker; brief is essentially empty.
    sync.validate_problem_goal_terms(
        problem={
            "goal_terms": {
                "travel_time": {"weight": 1.0, "type": "objective"},
                "capacity_penalty": {"weight": 1000.0, "type": "hard"},
            }
        },
        problem_brief={"items": [], "open_questions": [], "goal_summary": ""},
        weight_slot_markers={"travel_time": ("travel",), "capacity_penalty": ("capacity",)},
    )


def test_validate_problem_goal_terms_grounds_via_goal_summary():
    """`_grounded_goal_term_keys` scans `goal_summary` text — useful when the
    starter prompt's intent has been folded into the summary but not yet split
    into items. A panel key whose marker appears in the summary should ground."""
    warnings = sync.validate_problem_goal_terms(
        problem={
            "goal_terms": {
                "travel_time": {"weight": 1.0, "type": "objective"},
                "capacity_penalty": {"weight": 1000.0, "type": "hard"},
            }
        },
        problem_brief={
            "items": [],
            "open_questions": [],
            "goal_summary": "Minimize travel time across the fleet.",
        },
        weight_slot_markers={"travel_time": ("travel",), "capacity_penalty": ("capacity",)},
    )
    flagged = {w["key"] for w in warnings if w["code"] == "goal_term_hallucinated"}
    assert flagged == {"capacity_penalty"}


def test_validate_problem_goal_terms_grounds_via_open_question_text():
    """OQ text grounds goal terms — covers demo mode where the agent surfaces
    capacity / sparsity context as an OQ before any gathered row exists."""
    warnings = sync.validate_problem_goal_terms(
        problem={
            "goal_terms": {
                "capacity_penalty": {"weight": 100.0, "type": "hard"},
            }
        },
        problem_brief={
            "items": [],
            "open_questions": [
                {"id": "q1", "text": "How strict is the capacity limit?", "status": "open"}
            ],
            "goal_summary": "",
        },
        weight_slot_markers={"capacity_penalty": ("capacity",)},
    )
    assert warnings == []


def test_grounding_advice_message_returns_none_when_empty():
    assert sync.grounding_advice_message([]) is None
    assert sync.grounding_advice_message([{"code": "other", "message": "x"}]) is None


def test_grounding_advice_message_includes_keys():
    msg = sync.grounding_advice_message([
        {"code": "goal_term_hallucinated", "key": "capacity_overflow", "message": "..."},
        {"code": "goal_term_hallucinated", "key": "selection_sparsity", "message": "..."},
    ])
    assert msg is not None
    assert "`capacity_overflow`" in msg
    assert "`selection_sparsity`" in msg
    assert "Problem Config" in msg


def test_sync_panel_from_brief_commits_with_grounding_warnings(monkeypatch):
    """Hallucination-style grounding mismatches no longer block the save. The panel
    commits in a single LLM call and the ungrounded keys flow out as warnings."""
    row = SimpleNamespace(
        panel_config_json=json.dumps({"problem": {"algorithm": "GA"}}),
        workflow_mode="agile",
        test_problem_id="vrptw",
        updated_at=None,
        id="retry-session",
    )
    calls = {"count": 0}

    def _fake_llm(**_kwargs):
        calls["count"] += 1
        return {
            "problem": {
                "goal_terms": {
                    "travel_time": {"weight": 1.0, "type": "objective"},
                    "capacity_penalty": {"weight": 1000.0, "type": "hard"},
                }
            }
        }

    monkeypatch.setattr("app.services.llm.generate_config_from_brief", _fake_llm)

    panel, _weight_warnings, grounding_warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief={
            "items": [{"id": "config-weight-travel_time", "kind": "gathered", "text": "minimize travel"}]
        },
        api_key="fake-key",
        model_name="fake-model",
    )
    assert panel is not None
    assert calls["count"] == 1, "no retry-with-feedback loop"
    flagged = {w["key"] for w in grounding_warnings if w["code"] == "goal_term_hallucinated"}
    assert flagged == {"capacity_penalty"}

