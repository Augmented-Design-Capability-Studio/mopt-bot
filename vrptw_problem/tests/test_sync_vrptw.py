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


def test_brief_seed_extracts_algorithm_from_freeform_assumption_text():
    """Regression: when the chat agent commits an algorithm choice via an
    assumption row (e.g. *"Using genetic search (GA) with greedy initialization
    enabled."*) without a structurally-tagged ``config-search-strategy`` ID,
    the deterministic seed must still surface ``algorithm`` so
    ``_backfill_solver_fields_from_seed`` can fill it into the panel when the
    LLM panel-derive turn forgets it.

    Without this safety net, the user observed an inconsistency: the brief
    said GA but the panel had no algorithm field, so the run button stayed
    disabled until they manually edited the config.
    """
    from vrptw_problem.brief_seed import derive_problem_panel_from_brief

    brief = {
        "items": [
            {
                "id": "item-001",
                "kind": "gathered",
                "text": "Fleet consists of 5 drivers.",
                "source": "user",
            },
            {
                "id": "item-assum-alg",
                "kind": "assumption",
                "text": "Using genetic search (GA) with greedy initialization enabled for a balanced starting population.",
                "source": "agent",
            },
        ],
        "open_questions": [],
        "goal_summary": "",
    }
    derived = derive_problem_panel_from_brief(brief)
    assert derived is not None, "brief with an algorithm mention should produce a seed panel"
    assert derived["problem"].get("algorithm") == "GA", (
        f"GA mention in assumption text should seed algorithm=GA; got {derived['problem'].get('algorithm')!r}"
    )


def test_brief_seed_skips_algorithm_when_no_mention():
    """The free-form scan must not invent an algorithm when none is mentioned —
    otherwise it would mask cold-start briefs and bypass the LLM."""
    from vrptw_problem.brief_seed import derive_problem_panel_from_brief

    brief = {
        "items": [
            {"id": "g1", "kind": "gathered", "text": "Fleet has 5 drivers.", "source": "user"},
            {"id": "g2", "kind": "gathered", "text": "30 orders to deliver today.", "source": "user"},
        ],
        "open_questions": [],
        "goal_summary": "Minimize total driving time.",
    }
    derived = derive_problem_panel_from_brief(brief)
    # No algorithm mention → no seed signal → returns None per docstring.
    assert derived is None


def _alice_zone_d_rule():
    return {
        "vehicle_idx": 0,
        "condition": "avoid_zone",
        "zone": 4,
        "penalty": 50,
    }


def test_brief_seed_recovers_driver_preferences_from_goal_terms_no_llm():
    """Brief carries `goal_terms.worker_preference.properties.driver_preferences`;
    deterministic derive must produce a panel with that rule at top-level
    `driver_preferences` after the panel-side overlay runs.

    This is the chat→panel path the original bug regressed: structured rules
    in the brief must reach the panel without any prose parsing or LLM call.
    """
    from vrptw_problem.brief_seed import derive_problem_panel_from_brief
    from vrptw_problem.study_bridge import sanitize_panel_weights

    brief = {
        "items": [],
        "open_questions": [],
        "goal_summary": "",
        "goal_terms": {
            "worker_preference": {
                "weight": 1.0,
                "type": "soft",
                "properties": {"driver_preferences": [_alice_zone_d_rule()]},
            }
        },
    }
    derived = derive_problem_panel_from_brief(brief)
    assert derived is not None
    assert derived["problem"]["weights"]["worker_preference"] == 1.0

    # Run through sanitize_panel_weights so `_apply_goal_terms_overlay`
    # projects properties.driver_preferences → top-level driver_preferences.
    sanitized, _warnings = sanitize_panel_weights(derived)
    prefs = sanitized["problem"].get("driver_preferences", [])
    assert len(prefs) == 1
    assert prefs[0]["vehicle_idx"] == 0
    assert prefs[0]["zone"] == 4


def test_panel_to_brief_mirror_carries_driver_preferences_via_goal_terms():
    """Panel-side manual add must become first-class brief data so the next
    chat turn's LLM sees the rule via the brief's structured carrier."""
    from app.problem_brief import default_problem_brief, sync_problem_brief_from_panel

    base = default_problem_brief("vrptw")
    panel = {
        "problem": {
            "goal_terms": {
                "worker_preference": {
                    "weight": 5.0,
                    "type": "soft",
                    "properties": {"driver_preferences": [_alice_zone_d_rule()]},
                }
            }
        }
    }
    next_brief = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw")
    rules = next_brief["goal_terms"]["worker_preference"]["properties"]["driver_preferences"]
    assert rules == [_alice_zone_d_rule()]
    assert next_brief["goal_terms"]["worker_preference"]["weight"] == 5.0


def test_panel_to_brief_merges_driver_preferences_into_one_row():
    """Driver-preference rules are merged INLINE into the single
    `config-weight-worker_preference` def row (no separate `config-driver-pref-*`
    rows), so the term shows its companion detail in one row that also carries
    the lock toggle (goal_key). Works whether the companion is nested under
    `goal_terms[key].properties` or mirrored to a top-level panel field."""
    from app.problem_brief import _brief_items_from_panel

    panel = {
        "problem": {
            "goal_terms": {
                "worker_preference": {
                    "weight": 1.0,
                    "type": "soft",
                    "properties": {
                        "driver_preferences": [
                            _alice_zone_d_rule(),
                            {
                                "vehicle_idx": 2,
                                "condition": "order_priority",
                                "order_priority": "express",
                                "penalty": 50,
                            },
                            {
                                "vehicle_idx": 3,
                                "condition": "shift_over_limit",
                                "limit_minutes": 390,
                                "penalty": 50,
                            },
                        ]
                    },
                },
            }
        }
    }
    items = _brief_items_from_panel(panel, test_problem_id="vrptw")
    # No separate per-rule rows.
    assert not [it for it in items if str(it["id"]).startswith("config-driver-pref-")]
    wp = next(it for it in items if it["id"] == "config-weight-worker_preference")
    # All three rules merged into the one row, which anchors for the lock toggle.
    assert wp.get("goal_key") == "worker_preference"
    assert "Alice avoids Zone D" in wp["text"]
    assert "Carol skips express-priority orders" in wp["text"]
    assert "Dave caps shifts at 6.5h" in wp["text"]


def test_brief_synthesis_drops_stale_rows_when_rule_removed(monkeypatch):
    """When a structured rule disappears from goal_terms, its prose row must
    not survive on the next brief patch — `_synthesize_goal_term_prose_items`
    drops items whose id-prefix is owned by the port."""
    from app.problem_brief import normalize_problem_brief
    from app.routers.sessions.derivation import _synthesize_goal_term_prose_items

    # Brief still has a stale `config-driver-pref-0-zone-D` row from a prior
    # turn, but the structured carrier no longer mentions Alice/Zone D.
    brief = normalize_problem_brief({
        "items": [
            {
                "id": "config-driver-pref-0-zone-D",
                "text": "Alice avoids deliveries in Zone D as a soft preference.",
                "kind": "gathered",
                "source": "agent",
            },
        ],
        "goal_terms": {
            "worker_preference": {
                "weight": 1.0,
                "type": "soft",
                "properties": {"driver_preferences": []},
            }
        },
    })
    next_brief = _synthesize_goal_term_prose_items(brief, test_problem_id="vrptw")
    ids = {it["id"] for it in next_brief["items"]}
    assert "config-driver-pref-0-zone-D" not in ids


def test_existing_lock_preserve_test_still_works_with_goal_terms_present(monkeypatch):
    """Regression: ensure the new `goal_terms` brief carrier doesn't break the
    existing lock/preserve flow. Goal_terms in the brief should round-trip
    cleanly through the lock-preserve sync."""
    current_prefs = [_alice_zone_d_rule()]
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

    def _fake_derive(self, brief):
        # Brief now has goal_terms — the deterministic path can pick it up,
        # but for this test we bypass it with a fixed derivation.
        return {
            "problem": {
                "weights": {"travel_time": 9.0, "worker_preference": 99.0},
                "driver_preferences": [
                    {"vehicle_idx": 1, "condition": "order_priority",
                     "order_priority": "standard", "penalty": 1.0,
                     "aggregation": "per_stop"}
                ],
            }
        }

    monkeypatch.setattr(VrptwStudyPort, "derive_problem_panel_from_brief", _fake_derive)

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief={
            "items": [],
            "goal_terms": {
                "worker_preference": {
                    "weight": 5.0,
                    "type": "soft",
                    "properties": {"driver_preferences": current_prefs},
                }
            },
        },
        api_key=None,
        model_name=None,
    )

    assert panel is not None
    # Lock honored: locked weight stayed at 5.0.
    assert panel["problem"]["goal_terms"]["worker_preference"]["weight"] == 5.0
    # Lock honored: driver_preferences from current panel (not derived) preserved.
    assert panel["problem"]["driver_preferences"] == current_prefs
