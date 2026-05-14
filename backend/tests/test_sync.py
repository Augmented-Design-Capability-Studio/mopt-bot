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


def test_panel_derive_drops_goal_terms_not_in_brief():
    """Brief-as-source enforcement: when the LLM-derived panel proposes a
    goal-term key (e.g. ``travel_time``) that the brief's ``goal_terms`` map
    doesn't list, the merge drops it so the panel can't unilaterally invent
    objectives from prose alone. Keys already on the current panel and keys
    the brief explicitly carries both pass through."""
    current_problem = {"goal_terms": {}}
    derived_problem = {
        "weights": {"travel_time": 1.0},
        "goal_terms": {"travel_time": {"weight": 1.0, "type": "objective"}},
    }
    brief = {
        "goal_summary": "",
        "items": [
            {"id": "u1", "text": "Find optimal paths for my drivers", "kind": "gathered", "source": "user"}
        ],
        "open_questions": [],
        "goal_terms": {},  # brief has NOT committed to any goal term yet
    }
    merged = sync._merge_non_destructive_managed_fields(
        current_problem,
        derived_problem,
        problem_brief=brief,
        workflow_mode="agile",
        api_key=None,
        test_problem_id="vrptw",
    )
    assert merged.get("goal_terms", {}) == {}, merged.get("goal_terms")
    # Legacy weights map also pruned so the downstream sanitize rebuild can't
    # resurrect travel_time from a stale projection.
    assert "travel_time" not in (merged.get("weights") or {})


def test_panel_derive_drops_panel_only_goal_terms_when_brief_doesnt_carry_them():
    """Strict-subset enforcement: if a key is on the current panel but NOT
    in the brief, drop it. Otherwise one turn's stray LLM-derived weight
    sticks forever via the ``preserve_missing_managed_fields`` carry-over,
    and the drift banner permanently shows ``missing_in_brief``."""
    current_problem = {
        "goal_terms": {"travel_time": {"weight": 1.0, "type": "objective"}}
    }
    derived_problem = {
        "weights": {"travel_time": 1.0},
        "goal_terms": {"travel_time": {"weight": 1.0, "type": "objective"}},
    }
    brief = {
        "goal_summary": "",
        "items": [],
        "open_questions": [],
        "goal_terms": {},
    }
    merged = sync._merge_non_destructive_managed_fields(
        current_problem,
        derived_problem,
        problem_brief=brief,
        workflow_mode="agile",
        api_key=None,
        test_problem_id="vrptw",
    )
    assert merged.get("goal_terms", {}) == {}, merged.get("goal_terms")


def test_panel_derive_keeps_goal_terms_present_in_brief():
    """Sanity check: when the brief explicitly carries a goal term, the
    panel-derive translation passes through as before."""
    current_problem = {"goal_terms": {}}
    derived_problem = {
        "weights": {"travel_time": 1.0},
        "goal_terms": {"travel_time": {"weight": 1.0, "type": "objective"}},
    }
    brief = {
        "goal_summary": "Travel time is the main objective.",
        "items": [
            {"id": "u1", "text": "Minimize travel time.", "kind": "gathered", "source": "user"}
        ],
        "open_questions": [],
        "goal_terms": {"travel_time": {"weight": 1.0, "type": "objective"}},
    }
    merged = sync._merge_non_destructive_managed_fields(
        current_problem,
        derived_problem,
        problem_brief=brief,
        workflow_mode="agile",
        api_key=None,
        test_problem_id="vrptw",
    )
    assert "travel_time" in merged.get("goal_terms", {})


def test_validate_problem_goal_terms_rejects_missing_type():
    """Structural validation: missing/invalid `type` enum still raises.

    Brief grounding (the old marker-based hallucination check) was removed
    entirely; the schema is now the closed key vocabulary.
    """
    with pytest.raises(sync.GoalTermValidationError) as excinfo:
        sync.validate_problem_goal_terms(
            problem={
                "goal_terms": {
                    "travel_time": {"weight": 1.0},
                }
            },
        )
    assert any(r["code"] == "goal_term_type_invalid" for r in excinfo.value.reasons)


_ENGAGED_BRIEF_STUB = {
    "goal_summary": "Optimize fleet routes.",
    "items": [
        {"id": "user-1", "text": "I want to optimize routing.", "kind": "gathered", "source": "user"}
    ],
    "open_questions": [],
}


def test_drift_detector_flags_missing_keys_and_value_mismatch():
    brief = {
        **_ENGAGED_BRIEF_STUB,
        "goal_terms": {
            "travel_time": {"weight": 1.0, "type": "objective"},
            "lateness_penalty": {"weight": 50.0, "type": "soft"},
        },
    }
    panel = {
        "problem": {
            "goal_terms": {
                "travel_time": {"weight": 1.0, "type": "objective"},
                # lateness_penalty missing in panel
                "capacity_penalty": {"weight": 100.0, "type": "hard"},  # extra
            }
        }
    }
    drift = sync.compute_brief_panel_drift(brief, panel, test_problem_id="vrptw")
    kinds = [(d["kind"], d["key"]) for d in drift]
    assert ("missing_in_panel", "lateness_penalty") in kinds
    assert ("missing_in_brief", "capacity_penalty") in kinds


def test_drift_detector_flags_per_field_value_mismatch():
    brief = {
        **_ENGAGED_BRIEF_STUB,
        "goal_terms": {
            "travel_time": {"weight": 1.0, "type": "objective"},
        },
    }
    panel = {
        "problem": {
            "goal_terms": {
                "travel_time": {"weight": 5.0, "type": "soft", "locked": True},
            }
        }
    }
    drift = sync.compute_brief_panel_drift(brief, panel, test_problem_id="vrptw")
    details = sorted(d["detail"] for d in drift if d["kind"] == "value_mismatch")
    assert details == ["locked", "type", "weight"]


def test_drift_detector_flags_mirror_field_mismatch():
    """The VRPTW port mirrors ``goal_terms.worker_preference.properties.driver_preferences``
    to ``panel.problem.driver_preferences``. Drift between these two stores is
    the most likely brief↔config disagreement after a botched LLM merge."""
    rule_a = {"vehicle_idx": 0, "condition": "avoid_zone", "zone": 4, "penalty": 50}
    rule_b = {"vehicle_idx": 1, "condition": "avoid_zone", "zone": 4, "penalty": 50}
    brief = {
        **_ENGAGED_BRIEF_STUB,
        "goal_terms": {
            "worker_preference": {
                "weight": 1.0,
                "type": "soft",
                "properties": {"driver_preferences": [rule_a]},
            }
        },
    }
    panel = {
        "problem": {
            "goal_terms": {
                "worker_preference": {
                    "weight": 1.0,
                    "type": "soft",
                    "properties": {"driver_preferences": [rule_a]},
                }
            },
            "driver_preferences": [rule_b],
        }
    }
    drift = sync.compute_brief_panel_drift(brief, panel, test_problem_id="vrptw")
    mirror_entries = [d for d in drift if d["kind"] == "mirror_mismatch"]
    assert len(mirror_entries) == 1
    assert mirror_entries[0]["key"] == "worker_preference"
    assert mirror_entries[0]["detail"] == "driver_preferences"


def test_drift_detector_empty_starter_panel_is_drift_free():
    """A fresh starter panel ships without ``goal_terms`` — the agent populates
    the first goal term via assumption (agile) / OQ (waterfall) once the
    conversation warms up. Both sides therefore agree on the empty map and
    no drift should surface."""
    cold_brief = {
        "goal_summary": "",
        "run_summary": "",
        "items": [],
        "open_questions": [],
        "goal_terms": {},
    }
    # Mirrors VRPTW's post-change starter: algorithm + search-strategy fields,
    # no `weights` / `goal_terms`.
    panel = {
        "problem": {
            "algorithm": "SA",
            "epochs": 18,
            "pop_size": 12,
        }
    }
    drift = sync.compute_brief_panel_drift(cold_brief, panel, test_problem_id="vrptw")
    assert drift == []


def test_drift_detector_returns_empty_when_aligned():
    rule = {"vehicle_idx": 0, "condition": "avoid_zone", "zone": 4, "penalty": 50}
    brief = {
        **_ENGAGED_BRIEF_STUB,
        "goal_terms": {
            "travel_time": {"weight": 1.0, "type": "objective"},
            "worker_preference": {
                "weight": 1.0,
                "type": "soft",
                "properties": {"driver_preferences": [rule]},
            },
        },
    }
    panel = {
        "problem": {
            "goal_terms": {
                "travel_time": {"weight": 1.0, "type": "objective"},
                "worker_preference": {
                    "weight": 1.0,
                    "type": "soft",
                    "properties": {"driver_preferences": [rule]},
                },
            },
            "driver_preferences": [rule],
        }
    }
    drift = sync.compute_brief_panel_drift(brief, panel, test_problem_id="vrptw")
    assert drift == []
