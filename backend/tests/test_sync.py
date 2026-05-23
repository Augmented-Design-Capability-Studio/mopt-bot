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


def test_sync_drops_stale_goal_term_order_after_brief_removes_keys(monkeypatch):
    """Regression: a session whose current panel carries `goal_term_order` for
    keys the brief no longer lists must not wedge in a "Retry sync" loop.

    Repro: brief carries only `capacity_penalty`; current panel has
    `goal_term_order=['travel_time','lateness_penalty','capacity_penalty']`
    from an earlier turn. The unauthorized-key sweep drops travel_time /
    lateness_penalty from `goal_terms`, leaving order pointing at missing keys
    — which used to raise `goal_term_order_invalid` on every retry.
    """
    row = SimpleNamespace(
        panel_config_json=json.dumps(
            {
                "problem": {
                    "weights": {
                        "travel_time": 1.0,
                        "lateness_penalty": 50.0,
                        "capacity_penalty": 5.0,
                    },
                    "goal_terms": {
                        "travel_time": {"weight": 1.0, "type": "objective"},
                        "lateness_penalty": {"weight": 50.0, "type": "soft"},
                        "capacity_penalty": {"weight": 5.0, "type": "soft"},
                    },
                    "goal_term_order": ["travel_time", "lateness_penalty", "capacity_penalty"],
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
                "weights": {"capacity_penalty": 10.0},
                "goal_terms": {"capacity_penalty": {"weight": 10.0, "type": "soft"}},
            }
        }

    monkeypatch.setattr(VrptwStudyPort, "derive_problem_panel_from_brief", _fake_derive)

    brief = {
        "goal_summary": "Penalize over-capacity routes.",
        "items": [
            {"id": "u1", "text": "Penalize over-capacity routes.", "kind": "gathered", "source": "user"}
        ],
        "open_questions": [],
        "goal_terms": {"capacity_penalty": {"weight": 10.0, "type": "soft"}},
    }

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief=brief,
        api_key=None,
        model_name=None,
        preserve_missing_managed_fields=True,
    )

    assert panel is not None
    order = panel["problem"].get("goal_term_order", [])
    assert "travel_time" not in order
    assert "lateness_penalty" not in order


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
        "runs": [],
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


# ---------------------------------------------------------------------------
# Brief → panel canonical-scalar mirror (P_l7 regression)
# ---------------------------------------------------------------------------


def test_mirror_canonical_scalars_overrides_panel_with_brief_values():
    """Brief is authoritative for goal_terms[K].{weight,type,rank} on
    chat-origin flows. The panel-derive LLM occasionally emits values that
    disagree with the brief (P_l7 msg 1688: travel_time.type='objective' in
    brief, 'soft' in derived panel). The mirror rewrites the panel scalars
    from the brief before validation."""
    next_problem = {
        "goal_terms": {
            "travel_time": {"weight": 1.0, "type": "soft", "rank": 3},
            "capacity_penalty": {"weight": 1.0, "type": "soft", "rank": 2},
        },
        "weights": {"travel_time": 1.0, "capacity_penalty": 1.0},
    }
    brief = {
        "goal_terms": {
            "travel_time": {"weight": 7.66, "type": "objective", "rank": 1},
            "capacity_penalty": {"weight": 10.0, "type": "hard", "rank": 2},
        }
    }
    sync._mirror_canonical_scalars_from_brief(next_problem, brief)
    tt = next_problem["goal_terms"]["travel_time"]
    assert tt["type"] == "objective"
    assert tt["weight"] == 7.66
    assert tt["rank"] == 1
    cp = next_problem["goal_terms"]["capacity_penalty"]
    assert cp["type"] == "hard"
    assert cp["weight"] == 10.0
    # Top-level weights dict stays consistent with the mirrored scalars.
    assert next_problem["weights"]["travel_time"] == 7.66
    assert next_problem["weights"]["capacity_penalty"] == 10.0


def test_mirror_canonical_scalars_does_not_touch_properties():
    """Properties (per-rule structured data) belong to the LLM's
    translation job. The mirror covers scalars only."""
    rule = {
        "vehicle_idx": 0,
        "condition": "avoid_zone",
        "penalty": 50,
        "zone": 4,
    }
    next_problem = {
        "goal_terms": {
            "worker_preference": {
                "weight": 1.0,
                "type": "soft",
                "rank": 4,
                "properties": {"driver_preferences": [rule]},
            },
        },
    }
    brief = {
        "goal_terms": {
            "worker_preference": {
                "weight": 1.0,
                "type": "soft",
                "rank": 4,
                # brief carries a different (older) rule set; mirror must NOT
                # touch the panel's properties.
                "properties": {"driver_preferences": []},
            }
        }
    }
    sync._mirror_canonical_scalars_from_brief(next_problem, brief)
    assert next_problem["goal_terms"]["worker_preference"]["properties"] == {
        "driver_preferences": [rule]
    }


def test_mirror_canonical_scalars_skips_locked_field():
    """Locked is panel/researcher-owned. Mirror leaves it alone."""
    next_problem = {
        "goal_terms": {
            "travel_time": {
                "weight": 1.0,
                "type": "soft",
                "rank": 3,
                "locked": True,
            },
        },
    }
    brief = {
        "goal_terms": {
            "travel_time": {
                "weight": 7.66,
                "type": "objective",
                "rank": 1,
                "locked": False,  # brief disagrees
            }
        }
    }
    sync._mirror_canonical_scalars_from_brief(next_problem, brief)
    assert next_problem["goal_terms"]["travel_time"]["locked"] is True


def test_mirror_canonical_scalars_skips_search_strategy_carrier():
    """`search_strategy` is a carrier-only key — already handled by the
    algorithm/epochs/pop_size mirror block. The scalar mirror must skip it
    so the two mirrors don't fight over the same entry."""
    next_problem = {
        "goal_terms": {
            "search_strategy": {
                "weight": 1.0,
                "type": "custom",
                "rank": 2,
                "properties": {"algorithm": "PSO"},
            },
        },
    }
    brief = {
        "goal_terms": {
            "search_strategy": {
                "weight": 1.0,
                "type": "objective",  # would be wrong to mirror this
                "rank": 1,
                "properties": {"algorithm": "GA"},
            }
        }
    }
    sync._mirror_canonical_scalars_from_brief(next_problem, brief)
    # Scalar mirror left the panel's search_strategy alone.
    ss = next_problem["goal_terms"]["search_strategy"]
    assert ss["type"] == "custom"
    assert ss["rank"] == 2


def test_mirror_canonical_scalars_no_op_when_brief_lacks_key():
    """If the brief doesn't carry a key the panel has, the mirror leaves
    it alone — strict-subset enforcement is the responsibility of
    `_merge_non_destructive_managed_fields`."""
    next_problem = {
        "goal_terms": {
            "travel_time": {"weight": 5.0, "type": "soft"},
        },
    }
    brief = {"goal_terms": {}}
    sync._mirror_canonical_scalars_from_brief(next_problem, brief)
    assert next_problem["goal_terms"]["travel_time"]["type"] == "soft"
    assert next_problem["goal_terms"]["travel_time"]["weight"] == 5.0


def test_p_l7_replay_panel_derive_yields_no_brief_panel_mismatch(monkeypatch):
    """End-to-end P_l7 msg-1688 replay through sync_panel_from_problem_brief.

    Fixture: brief has travel_time.type='objective' (the user's stated
    primary objective). The panel-derive LLM is mocked to (incorrectly)
    emit travel_time.type='soft' — the exact divergence that paused
    P_l7. After the deterministic scalar mirror runs, the persisted
    panel agrees with the brief; `verify_panel_consistency` reports no
    `brief_panel_mismatch` on travel_time.
    """
    from app.services import pipeline_verification as verifier
    from app.services import llm as llm_module

    row = SimpleNamespace(
        panel_config_json=json.dumps(
            {
                "problem": {
                    "weights": {},
                    "goal_terms": {"travel_time": {"weight": 1.0, "type": "objective"}},
                    "algorithm": "GA",
                }
            }
        ),
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        id="p_l7_replay",
        updated_at=None,
    )
    brief = {
        "goal_summary": "Minimize total travel time across all routes.",
        "items": [
            {
                "id": "config-weight-travel_time",
                "text": "Travel time (primary objective, weight 7.66) — minimize driving minutes.",
                "kind": "gathered",
                "source": "agent",
            },
            {
                "id": "item-gathered-algorithm-ga",
                "text": "Search strategy is genetic search (GA).",
                "kind": "gathered",
                "source": "user",
            },
        ],
        "open_questions": [],
        "goal_terms": {
            "travel_time": {"weight": 7.66, "type": "objective", "rank": 1},
            "search_strategy": {
                "weight": 1.0,
                "type": "custom",
                "rank": 2,
                "properties": {"algorithm": "GA"},
            },
        },
    }

    def _faulty_derive(**kwargs):
        # Mimic the bug: LLM emits travel_time.type='soft' (wrong) plus the
        # full goal_terms entry the brief carries.
        return {
            "problem": {
                "goal_terms": {
                    "travel_time": {"weight": 1.0, "type": "soft", "rank": 3},
                },
                "weights": {"travel_time": 1.0},
                "algorithm": "GA",
            }
        }

    monkeypatch.setattr(llm_module, "generate_config_from_brief", _faulty_derive)

    panel, _warnings = sync.sync_panel_from_problem_brief(
        row=row,
        db=_DummyDb(),
        problem_brief=brief,
        api_key="test",
        model_name="test",
        workflow_mode="waterfall",
        commit=False,
    )

    assert panel is not None
    tt = panel["problem"]["goal_terms"]["travel_time"]
    assert tt["type"] == "objective", tt
    assert tt["weight"] == 7.66, tt
    assert tt["rank"] == 1, tt

    issues = verifier.verify_panel_consistency(
        brief=brief,
        panel=panel,
        workflow_mode="waterfall",
        test_problem_id="vrptw",
    )
    travel_time_drifts = [
        i for i in issues
        if i.category == "brief_panel_mismatch" and "travel_time" in (i.subject or "")
    ]
    assert travel_time_drifts == [], [i.message for i in travel_time_drifts]
