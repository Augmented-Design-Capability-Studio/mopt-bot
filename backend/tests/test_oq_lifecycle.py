"""Tests for OQ + assumption lifecycle: per-row actions, structural anchor
resolution, and verifier checks (replace-flag ambiguity and ask-without-OQ).

Headline reproducers:
- P_l7 *"yes to both!"* (msg 1629): agent committed both goal_terms +
  gathered items but omitted the survivor list while setting
  `replace_open_questions=true`. Anchor resolver drops the OQs once the
  keys land AND gathered evidence is in place.
- P_l7 msg 1630 (Run #2 ack): tuning OQ for an already-committed key must
  survive the resolver (key is in base → not newly committed).
- P_l7 msg 1632 (non-run-ack): reply asks but no OQ in patch — verifier
  raises `ask_without_oq` when the LLM populates `question_clause`.
"""

from __future__ import annotations

from app.problem_brief import (
    merge_problem_brief_patch,
    normalize_problem_brief,
)
from app.routers.sessions.derivation import (
    _apply_oq_actions,
    _has_gathered_evidence_for_key,
    _resolve_anchored_provisional_rows,
)
from app.services.pipeline_verification import verify_brief_consistency


def _minimal_brief(**kwargs):
    base = {
        "goal_summary": "Minimize total travel time.",
        "items": [],
        "open_questions": [],
        "goal_terms": {},
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }
    base.update(kwargs)
    return base


def _canonical_weight_item(key: str, label: str = ""):
    """Build a synthesizer-style `config-weight-K` row for use in unit tests
    that skip the actual `_synthesize_canonical_weight_items` call."""
    return {
        "id": f"config-weight-{key}",
        "text": (label or f"{key} (synthesized).").strip(),
        "kind": "gathered",
        "source": "agent",
    }


# ---------------------------------------------------------------------------
# Layer 1: _apply_oq_actions
# ---------------------------------------------------------------------------


def test_oq_actions_drop_removes_the_row():
    brief = normalize_problem_brief(
        _minimal_brief(
            open_questions=[
                {"id": "q-keep", "text": "Still open?", "topic": "other"},
                {"id": "q-drop", "text": "Already covered.", "topic": "other"},
            ]
        )
    )
    after = _apply_oq_actions(brief, [{"id": "q-drop", "action": "drop"}])
    assert [q["id"] for q in after["open_questions"]] == ["q-keep"]


def test_oq_actions_mark_answered_sets_status_and_text():
    brief = normalize_problem_brief(
        _minimal_brief(
            open_questions=[
                {"id": "q-1", "text": "Capacity?", "topic": "other"},
            ]
        )
    )
    after = _apply_oq_actions(
        brief,
        [{"id": "q-1", "action": "mark_answered", "answer_text": "Add the soft penalty."}],
    )
    q = after["open_questions"][0]
    assert q["status"] == "answered"
    assert q["answer_text"] == "Add the soft penalty."


def test_oq_actions_mark_answered_without_text_is_noop():
    brief = normalize_problem_brief(
        _minimal_brief(
            open_questions=[{"id": "q-1", "text": "Capacity?", "topic": "other"}]
        )
    )
    after = _apply_oq_actions(
        brief, [{"id": "q-1", "action": "mark_answered", "answer_text": ""}]
    )
    assert after["open_questions"][0]["status"] == "open"


def test_oq_actions_rephrase_updates_text():
    brief = normalize_problem_brief(
        _minimal_brief(
            open_questions=[
                {"id": "q-1", "text": "Old phrasing?", "topic": "other"},
            ]
        )
    )
    after = _apply_oq_actions(
        brief,
        [{"id": "q-1", "action": "rephrase", "rephrased_text": "Tighter phrasing?"}],
    )
    assert after["open_questions"][0]["text"] == "Tighter phrasing?"


def test_oq_actions_unknown_id_is_silent_noop():
    brief = normalize_problem_brief(
        _minimal_brief(open_questions=[{"id": "q-1", "text": "x", "topic": "other"}])
    )
    after = _apply_oq_actions(brief, [{"id": "q-stale", "action": "drop"}])
    assert [q["id"] for q in after["open_questions"]] == ["q-1"]


# ---------------------------------------------------------------------------
# Layer 2 helper: _has_gathered_evidence_for_key
# ---------------------------------------------------------------------------


def test_gathered_evidence_matches_canonical_id():
    items = [_canonical_weight_item("capacity_penalty", "Capacity (soft, 10).")]
    assert _has_gathered_evidence_for_key(items, "capacity_penalty")
    assert not _has_gathered_evidence_for_key(items, "lateness_penalty")


def test_gathered_evidence_matches_goal_key():
    items = [
        {
            "id": "item-gathered-cap",
            "text": "Capacity penalty (soft, weight 10.0).",
            "kind": "gathered",
            "source": "user",
            "goal_key": "capacity_penalty",
        }
    ]
    assert _has_gathered_evidence_for_key(items, "capacity_penalty")


def test_gathered_evidence_ignores_assumption_rows():
    items = [
        {
            "id": "item-assumption-cap",
            "text": "Capacity penalty (soft, weight 10.0).",
            "kind": "assumption",
            "source": "agent",
            "goal_key": "capacity_penalty",
        }
    ]
    assert not _has_gathered_evidence_for_key(items, "capacity_penalty")


# ---------------------------------------------------------------------------
# Layer 2: _resolve_anchored_provisional_rows
# ---------------------------------------------------------------------------


def test_anchored_oq_dropped_on_first_commit_with_gathered_evidence_waterfall():
    base = normalize_problem_brief(_minimal_brief())
    merged = normalize_problem_brief(
        _minimal_brief(
            items=[_canonical_weight_item("capacity_penalty")],
            open_questions=[
                {
                    "id": "q-cap",
                    "text": "Should I add a capacity penalty?",
                    "topic": "other",
                    "goal_key": "capacity_penalty",
                },
                {
                    "id": "q-unrelated",
                    "text": "Other thing?",
                    "topic": "other",
                },
            ],
            goal_terms={"capacity_penalty": {"weight": 10.0, "type": "soft"}},
        )
    )
    after = _resolve_anchored_provisional_rows(merged, "waterfall", base_brief=base)
    assert [q["id"] for q in after["open_questions"]] == ["q-unrelated"]


def test_anchored_tuning_oq_survives_when_key_already_in_base():
    """msg-1630 shape: capacity_penalty already in base, agent asks
    *"would you like to tighten the capacity weight?"* — the OQ proposes
    a tune, not an add. Resolver must leave it alone."""
    base = normalize_problem_brief(
        _minimal_brief(
            items=[_canonical_weight_item("capacity_penalty")],
            goal_terms={"capacity_penalty": {"weight": 1.0, "type": "soft"}},
        )
    )
    merged = normalize_problem_brief(
        _minimal_brief(
            items=[_canonical_weight_item("capacity_penalty")],
            open_questions=[
                {
                    "id": "oq-capacity-tuning",
                    "text": "Tighten capacity weight to 2.0?",
                    "topic": "other",
                    "goal_key": "capacity_penalty",
                },
            ],
            goal_terms={"capacity_penalty": {"weight": 1.0, "type": "soft"}},
        )
    )
    after = _resolve_anchored_provisional_rows(merged, "waterfall", base_brief=base)
    assert [q["id"] for q in after["open_questions"]] == ["oq-capacity-tuning"]


def test_anchored_oq_survives_when_first_commit_lacks_gathered_evidence():
    """Defensive third gate: key landed but no items[] row visualizes it
    yet → keep the OQ (don't make the question disappear before the
    participant sees the answer in their Definition tab)."""
    base = normalize_problem_brief(_minimal_brief())
    merged = normalize_problem_brief(
        _minimal_brief(
            # No items[] referencing capacity_penalty — synth was bypassed.
            open_questions=[
                {
                    "id": "q-cap",
                    "text": "Should I add a capacity penalty?",
                    "topic": "other",
                    "goal_key": "capacity_penalty",
                },
            ],
            goal_terms={"capacity_penalty": {"weight": 10.0, "type": "soft"}},
        )
    )
    after = _resolve_anchored_provisional_rows(merged, "waterfall", base_brief=base)
    assert [q["id"] for q in after["open_questions"]] == ["q-cap"]


def test_anchored_oq_dropped_when_evidence_comes_via_items_anchor():
    """Gathered evidence detection via `goal_key` on a
    user-authored gathered row — covers the path where the LLM emits an
    items[] row anchored to the key without the canonical id pattern."""
    base = normalize_problem_brief(_minimal_brief())
    merged = normalize_problem_brief(
        _minimal_brief(
            items=[
                {
                    "id": "item-gathered-cap-user",
                    "text": "Capacity penalty (soft, weight 10.0) — user confirmed.",
                    "kind": "gathered",
                    "source": "user",
                    "goal_key": "capacity_penalty",
                },
            ],
            open_questions=[
                {
                    "id": "q-cap",
                    "text": "Should I add a capacity penalty?",
                    "topic": "other",
                    "goal_key": "capacity_penalty",
                },
            ],
            goal_terms={"capacity_penalty": {"weight": 10.0, "type": "soft"}},
        )
    )
    after = _resolve_anchored_provisional_rows(merged, "waterfall", base_brief=base)
    assert after["open_questions"] == []


def test_foundational_oq_with_anchor_is_not_dropped_by_resolver():
    """Foundational-topic OQs are owned by the server monitor state
    machine; the resolver must never touch them, even with an anchor."""
    base = normalize_problem_brief(_minimal_brief())
    merged = normalize_problem_brief(
        _minimal_brief(
            items=[_canonical_weight_item("search_strategy")],
            open_questions=[
                {
                    "id": "oq-monitor-algorithm",
                    "text": "Which search method?",
                    "topic": "search_strategy",
                    "goal_key": "search_strategy",
                },
            ],
            goal_terms={
                "search_strategy": {
                    "weight": 1.0,
                    "type": "custom",
                    "properties": {"algorithm": "GA"},
                }
            },
        )
    )
    after = _resolve_anchored_provisional_rows(merged, "waterfall", base_brief=base)
    assert [q["id"] for q in after["open_questions"]] == ["oq-monitor-algorithm"]


# ---------------------------------------------------------------------------
# Layer 2b: panel-save auto-close (sync_problem_brief_from_panel).
# Complements the LLM-driven resolver above with the panel-edit event path:
# when the user side-steps an OQ by editing the panel for the same key, the
# OQ becomes moot. Reproducer: PILOT_5 ``oq-reduce-capacity-weight`` /
# ``oq-re-tune-capacity`` — both proposed ``capacity_penalty`` tweaks the
# user instead made via the Config tab.
# ---------------------------------------------------------------------------


def test_panel_edit_closes_tuning_oq_on_changed_weight():
    """Tuning OQ asks to change capacity weight. User edits the weight via
    panel. OQ auto-closes (folded into a gathered/user row by the next
    normalize pass — see _promote_answered_open_questions_to_gathered)."""
    from app.problem_brief import sync_problem_brief_from_panel

    base = normalize_problem_brief(
        _minimal_brief(
            items=[_canonical_weight_item("capacity_penalty")],
            open_questions=[
                {
                    "id": "oq-reduce-capacity-weight",
                    "text": "Reduce capacity weight to 50?",
                    "topic": "other",
                    "goal_key": "capacity_penalty",
                }
            ],
            goal_terms={"capacity_penalty": {"weight": 100.0, "type": "hard", "rank": 1}},
        )
    )
    panel = {
        "problem": {
            "goal_terms": {
                "capacity_penalty": {"weight": 50.0, "type": "hard", "rank": 1},
            }
        }
    }
    out = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw")
    # The OQ should no longer be open. Either it was dropped entirely (no
    # longer present) or it survived only as a gathered row.
    open_ids = [q["id"] for q in out.get("open_questions") or [] if q.get("status") == "open"]
    assert "oq-reduce-capacity-weight" not in open_ids


def test_panel_edit_leaves_untouched_oqs_alone():
    """OQ about ``travel_time`` survives a panel edit that only touches
    ``capacity_penalty`` — different key, user hasn't acted on it yet."""
    from app.problem_brief import sync_problem_brief_from_panel

    base = normalize_problem_brief(
        _minimal_brief(
            items=[
                _canonical_weight_item("travel_time"),
                _canonical_weight_item("capacity_penalty"),
            ],
            open_questions=[
                {
                    "id": "oq-travel-tune",
                    "text": "Raise travel time weight?",
                    "topic": "other",
                    "goal_key": "travel_time",
                }
            ],
            goal_terms={
                "travel_time": {"weight": 1.0, "type": "objective", "rank": 1},
                "capacity_penalty": {"weight": 100.0, "type": "hard", "rank": 2},
            },
        )
    )
    panel = {
        "problem": {
            "goal_terms": {
                "travel_time": {"weight": 1.0, "type": "objective", "rank": 1},
                "capacity_penalty": {"weight": 80.0, "type": "hard", "rank": 2},
            }
        }
    }
    out = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw")
    open_ids = [q["id"] for q in out.get("open_questions") or [] if q.get("status") == "open"]
    assert "oq-travel-tune" in open_ids


def test_panel_rerank_does_not_close_oqs_about_cascade_shifted_keys():
    """Real bug reported: user reranks goal terms in the panel; the frontend's
    ``handleReorder`` auto-rewrites the weights of cascade-affected keys to
    suggested values for their new rank positions. The naive "weight changed
    → user acted on K" rule false-closed OQs about keys the user never
    actively touched (e.g. the LLM had asked *"Would you like to adjust the
    weight of travel_time (currently 1.0)?"*, then the user reranked OTHER
    terms; travel_time's weight was auto-shifted to 7.13 and the OQ closed).
    A weight change that's coincident with a rank change is a cascade — only
    treat it as an active edit when the rank did NOT change."""
    from app.problem_brief import sync_problem_brief_from_panel

    base = normalize_problem_brief(
        _minimal_brief(
            items=[
                _canonical_weight_item("travel_time"),
                _canonical_weight_item("lateness_penalty"),
                _canonical_weight_item("capacity_penalty"),
            ],
            open_questions=[
                {
                    "id": "oq-tt-tune",
                    "text": "Would you like to adjust the weight of travel_time (currently 1.0)?",
                    "topic": "other",
                    "goal_key": "travel_time",
                }
            ],
            goal_terms={
                "travel_time": {"weight": 1.0, "type": "objective", "rank": 1},
                "lateness_penalty": {"weight": 50.0, "type": "soft", "rank": 2},
                "capacity_penalty": {"weight": 20.0, "type": "hard", "rank": 3},
            },
        )
    )
    # User reranks (drags capacity to rank 1). The frontend rewrites all the
    # cascade weights too — so every key's rank+weight both shift in the diff.
    panel = {
        "problem": {
            "goal_terms": {
                "capacity_penalty": {"weight": 2.59, "type": "hard", "rank": 1},
                "lateness_penalty": {"weight": 3.89, "type": "soft", "rank": 2},
                "travel_time": {"weight": 7.13, "type": "objective", "rank": 3},
            }
        }
    }
    out = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw", origin="user")
    open_ids = [q["id"] for q in out.get("open_questions") or [] if q.get("status") == "open"]
    assert "oq-tt-tune" in open_ids, (
        "OQ about travel_time must survive a pure rerank — the user didn't "
        "actively touch travel_time, only the rerank cascade did."
    )


def test_panel_weight_only_edit_still_closes_oq():
    """Inverse of the rerank-cascade test: a standalone weight edit (no rank
    change) IS a user action on K and should still close OQs about K. Locks
    the active-edit case so the cascade fix doesn't over-shoot."""
    from app.problem_brief import sync_problem_brief_from_panel

    base = normalize_problem_brief(
        _minimal_brief(
            items=[_canonical_weight_item("travel_time")],
            open_questions=[
                {
                    "id": "oq-tt-tune",
                    "text": "Adjust travel_time weight?",
                    "topic": "other",
                    "goal_key": "travel_time",
                }
            ],
            goal_terms={
                "travel_time": {"weight": 1.0, "type": "objective", "rank": 1},
            },
        )
    )
    panel = {
        "problem": {
            "goal_terms": {
                "travel_time": {"weight": 5.0, "type": "objective", "rank": 1},
            }
        }
    }
    out = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw", origin="user")
    open_ids = [q["id"] for q in out.get("open_questions") or [] if q.get("status") == "open"]
    assert "oq-tt-tune" not in open_ids, (
        "Standalone weight edit (no rank change) must still close OQs about K."
    )


def test_panel_edit_does_not_close_foundational_oq():
    """Foundational-topic OQs (e.g. search_strategy) are owned by the
    monitor state machine, never touched by the panel-edit auto-closer."""
    from app.problem_brief import sync_problem_brief_from_panel

    base = normalize_problem_brief(
        _minimal_brief(
            items=[_canonical_weight_item("capacity_penalty")],
            open_questions=[
                {
                    "id": "oq-monitor-algorithm",
                    "text": "Which search method?",
                    "topic": "search_strategy",
                    "goal_key": "search_strategy",
                }
            ],
            goal_terms={
                "capacity_penalty": {"weight": 100.0, "type": "hard", "rank": 1},
                "search_strategy": {
                    "weight": 1.0,
                    "type": "custom",
                    "rank": 2,
                    "properties": {"algorithm": "GA"},
                },
            },
        )
    )
    # User edits a weight — search_strategy is not in the panel's goal_terms
    # (carrier-only) and even if it were, foundational topic should survive.
    panel = {
        "problem": {
            "goal_terms": {
                "capacity_penalty": {"weight": 80.0, "type": "hard", "rank": 1},
            }
        }
    }
    out = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw")
    open_ids = [q["id"] for q in out.get("open_questions") or [] if q.get("status") == "open"]
    assert "oq-monitor-algorithm" in open_ids


# ---------------------------------------------------------------------------
# Layer 2 (agile): assumption rows are NEVER auto-resolved.
# Promotion is the right action and only happens via explicit
# `assumption_actions: promote_to_gathered` (handled in
# `_apply_assumption_actions`).
# ---------------------------------------------------------------------------


def test_anchored_assumption_never_auto_dropped_agile():
    """Even with a parallel gathered+user item carrying the same anchor,
    the resolver leaves the assumption row alone. Promotion is explicit-only."""
    base = normalize_problem_brief(_minimal_brief())
    merged = normalize_problem_brief(
        _minimal_brief(
            items=[
                {
                    "id": "item-assumption-cap",
                    "text": "Capacity penalty (soft, weight 10.0).",
                    "kind": "assumption",
                    "source": "agent",
                    "goal_key": "capacity_penalty",
                },
                {
                    "id": "item-gathered-cap",
                    "text": "Capacity penalty (soft, weight 10.0) — user-confirmed.",
                    "kind": "gathered",
                    "source": "user",
                    "goal_key": "capacity_penalty",
                },
            ],
            goal_terms={"capacity_penalty": {"weight": 10.0, "type": "soft"}},
        )
    )
    after = _resolve_anchored_provisional_rows(merged, "agile", base_brief=base)
    ids = [it["id"] for it in after["items"]]
    assert "item-assumption-cap" in ids
    assert "item-gathered-cap" in ids


def test_anchored_assumption_survives_tuning_case_agile():
    """Key already in base, assumption row proposing a tune → keep."""
    base = normalize_problem_brief(
        _minimal_brief(
            items=[_canonical_weight_item("capacity_penalty")],
            goal_terms={"capacity_penalty": {"weight": 1.0, "type": "soft"}},
        )
    )
    merged = normalize_problem_brief(
        _minimal_brief(
            items=[
                _canonical_weight_item("capacity_penalty"),
                {
                    "id": "item-assumption-tune",
                    "text": "Tuning capacity penalty up to 2.0 as a working setting.",
                    "kind": "assumption",
                    "source": "agent",
                    "goal_key": "capacity_penalty",
                },
            ],
            goal_terms={"capacity_penalty": {"weight": 2.0, "type": "soft"}},
        )
    )
    after = _resolve_anchored_provisional_rows(merged, "agile", base_brief=base)
    ids = [it["id"] for it in after["items"]]
    assert "item-assumption-tune" in ids


# ---------------------------------------------------------------------------
# Verifier: replace_open_questions=true without the list
# ---------------------------------------------------------------------------


def test_verifier_flags_replace_flag_without_list():
    issues = verify_brief_consistency(
        merged_brief={"items": [], "goal_terms": {}, "open_questions": []},
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={"replace_open_questions": True, "items": []},
        visible_reply="I've added the penalty.",
        workflow_mode="waterfall",
    )
    assert any(i.category == "oq_replace_without_list" for i in issues)


def test_verifier_does_not_flag_when_list_is_included():
    issues = verify_brief_consistency(
        merged_brief={"items": [], "goal_terms": {}, "open_questions": []},
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={"replace_open_questions": True, "open_questions": []},
        visible_reply="I've added the penalty.",
        workflow_mode="waterfall",
    )
    assert not any(i.category == "oq_replace_without_list" for i in issues)


# ---------------------------------------------------------------------------
# Verifier: ask_without_oq (Fix B — question_clause activation)
# ---------------------------------------------------------------------------


def test_ask_without_oq_raised_when_no_new_oq_lands():
    issues = verify_brief_consistency(
        merged_brief={"items": [], "goal_terms": {}, "open_questions": []},
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={},
        visible_reply=(
            "Would you like me to increase the workload balance weight, or "
            "explore a different search strategy?"
        ),
        workflow_mode="waterfall",
        question_clause=(
            "Would you like me to increase the workload balance weight, or "
            "explore a different search strategy?"
        ),
    )
    assert any(i.category == "ask_without_oq" for i in issues)


def test_ask_without_oq_silent_when_oq_lands_in_merged():
    new_oq = {
        "id": "q-workload",
        "text": "Increase workload balance weight?",
        "topic": "other",
        "goal_key": "workload_balance",
    }
    issues = verify_brief_consistency(
        merged_brief={"items": [], "goal_terms": {}, "open_questions": [new_oq]},
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={"open_questions": [new_oq]},
        visible_reply="Would you like me to increase the workload balance weight?",
        workflow_mode="waterfall",
        question_clause="Would you like me to increase the workload balance weight?",
    )
    assert not any(i.category == "ask_without_oq" for i in issues)


def test_ask_without_oq_silent_when_oq_actions_rephrases_existing_oq():
    existing_oq = {
        "id": "q-existing",
        "text": "Older phrasing of the same question?",
        "topic": "other",
    }
    issues = verify_brief_consistency(
        merged_brief={"items": [], "goal_terms": {}, "open_questions": [existing_oq]},
        base_brief={"items": [], "goal_terms": {}, "open_questions": [existing_oq]},
        patch={
            "oq_actions": [
                {"id": "q-existing", "action": "rephrase", "rephrased_text": "Tighter."}
            ]
        },
        visible_reply="Would you like me to tighten this further?",
        workflow_mode="waterfall",
        question_clause="Would you like me to tighten this further?",
    )
    assert not any(i.category == "ask_without_oq" for i in issues)


def test_ask_without_oq_silent_when_question_clause_empty():
    """No `question_clause` populated → verifier doesn't fire even if reply ends with '?'."""
    issues = verify_brief_consistency(
        merged_brief={"items": [], "goal_terms": {}, "open_questions": []},
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={},
        visible_reply="What's the cost trend? Just checking.",
        workflow_mode="waterfall",
        question_clause=None,
    )
    assert not any(i.category == "ask_without_oq" for i in issues)


def test_ask_without_oq_silent_on_cold_start_primary_goal_ask():
    """Regression test for Bug C: first-turn primary-goal ask must not pause the pipeline.

    The first message of a fresh session warms the brief (topic_engaged: True)
    but commits no goal_terms / no items yet. The agent's reply asks about
    the primary objective — a foundational-topic ask. The LLM ideally leaves
    `question_clause` empty (per the prompt carve-out), but as defense in
    depth the verifier also dry-runs `_enforce_session_monitors` which will
    add the canonical `oq-monitor-goal` row in S3. So even when the LLM
    populates `question_clause` for the foundational ask, the verifier sees
    the monitor's incoming OQ and stays silent.
    """
    base_brief = {
        "goal_summary": "",
        "items": [],
        "goal_terms": {},
        "open_questions": [],
        "topic_engaged": False,
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }
    merged_brief = {
        "goal_summary": "",
        "items": [],
        "goal_terms": {},
        "open_questions": [],
        # The first patch flips this on. Monitors fire when warm + empty.
        "topic_engaged": True,
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }
    issues = verify_brief_consistency(
        merged_brief=merged_brief,
        base_brief=base_brief,
        patch={"topic_engaged_next": True},
        visible_reply=(
            "That's a great start. Would you like to set travel time as your "
            "primary objective, or also consider workload balance?"
        ),
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        question_clause=(
            "Would you like to set travel time as your primary objective, "
            "or also consider workload balance?"
        ),
    )
    assert not any(i.category == "ask_without_oq" for i in issues)


# ---------------------------------------------------------------------------
# P_l7 regression replays
# ---------------------------------------------------------------------------


def test_p_l7_yes_to_both_drops_both_oqs_via_resolver():
    """Replay of session 26f47919 (P_l7) message 1629.

    Pre-turn brief had two open OQs proposing capacity_penalty and
    lateness_penalty. The LLM patch added both goal_terms + gathered items
    but set `replace_open_questions=true` with the field omitted (so the
    merge preserved the OQs). With the anchor field on the OQs and on the
    LLM's gathered items, the deterministic resolver drops them once
    BOTH keys land AND gathered evidence is visible.
    """
    base_brief = normalize_problem_brief(
        _minimal_brief(
            items=[
                {
                    "id": "item-gathered-upload",
                    "text": "Source data file(s) uploaded.",
                    "kind": "gathered",
                    "source": "upload",
                },
                _canonical_weight_item("travel_time"),
            ],
            open_questions=[
                {
                    "id": "question-capacity-penalty",
                    "text": "Should I add a capacity penalty (soft, weight 10.0)?",
                    "topic": "other",
                    "goal_key": "capacity_penalty",
                },
                {
                    "id": "question-punctuality-penalty",
                    "text": "Should I add a lateness penalty (soft, weight 10.0)?",
                    "topic": "other",
                    "goal_key": "lateness_penalty",
                },
            ],
            goal_terms={
                "travel_time": {"weight": 1.0, "type": "objective", "rank": 1},
                "search_strategy": {
                    "weight": 1.0,
                    "type": "custom",
                    "rank": 2,
                    "properties": {"algorithm": "GA"},
                },
            },
        )
    )
    # Patch shape mirrors the recorded v2_turn_snapshot — note the missing
    # `open_questions` field paired with `replace_open_questions: true`.
    # Items[] carry the anchor (this is what the new prompt asks the LLM to do).
    patch = {
        "items": [
            {
                "id": "item-gathered-capacity-penalty",
                "text": "Capacity penalty (soft, weight 10.0).",
                "kind": "gathered",
                "source": "user",
                "goal_key": "capacity_penalty",
            },
            {
                "id": "item-gathered-punctuality-penalty",
                "text": "Lateness penalty (soft, weight 10.0).",
                "kind": "gathered",
                "source": "user",
                "goal_key": "lateness_penalty",
            },
        ],
        "goal_terms": {
            "capacity_penalty": {
                "weight": 10.0,
                "type": "soft",
                "rank": 3,
                "evidence_item_ids": ["item-gathered-capacity-penalty"],
            },
            "lateness_penalty": {
                "weight": 10.0,
                "type": "soft",
                "rank": 4,
                "evidence_item_ids": ["item-gathered-punctuality-penalty"],
            },
        },
        "replace_open_questions": True,
    }
    merged = merge_problem_brief_patch(base_brief, patch)
    # Sanity: both goal_terms landed.
    assert "capacity_penalty" in merged["goal_terms"]
    assert "lateness_penalty" in merged["goal_terms"]
    # And the legacy defensive merge preserved the OQs (the bug we're fixing).
    assert len(merged["open_questions"]) == 2
    # Now run the deterministic resolver — both anchored OQs should drop
    # because (a) the keys are newly committed (not in base) and (b) the
    # gathered items[] rows the LLM emitted satisfy the evidence gate.
    resolved = _resolve_anchored_provisional_rows(
        merged, "waterfall", base_brief=base_brief
    )
    assert resolved["open_questions"] == []
    assert "capacity_penalty" in resolved["goal_terms"]
    assert "lateness_penalty" in resolved["goal_terms"]


def test_p_l7_msg_1630_tuning_oq_survives():
    """Replay of session 26f47919 (P_l7) message 1630, post-fix.

    Run #2 ack: capacity_penalty already in base; agent asks
    *"would you like to tighten the capacity weight further?"* and emits
    an OQ anchored to capacity_penalty. The resolver must NOT drop the
    OQ — the key was already in base, so it's a tuning question.
    """
    base_brief = normalize_problem_brief(
        _minimal_brief(
            items=[_canonical_weight_item("capacity_penalty")],
            goal_terms={
                "capacity_penalty": {"weight": 1.0, "type": "soft", "rank": 3},
            },
        )
    )
    patch = {
        "open_questions": [
            {
                "id": "oq-capacity-tuning",
                "text": "Tighten the capacity penalty weight to 2.0?",
                "topic": "other",
                "goal_key": "capacity_penalty",
            },
        ],
        "replace_open_questions": True,
    }
    merged = merge_problem_brief_patch(base_brief, patch)
    resolved = _resolve_anchored_provisional_rows(
        merged, "waterfall", base_brief=base_brief
    )
    assert [q["id"] for q in resolved["open_questions"]] == ["oq-capacity-tuning"]


def test_p_l7_msg_1632_ask_without_oq_raised():
    """Replay of session 26f47919 (P_l7) message 1632, post-fix.

    Non-run-ack turn. Reply asks *"should we increase the weight on
    workload balance, or explore a different search strategy?"* but the
    patch carries only `run_summary` — no OQ, no oq_actions. With the
    LLM now populating `question_clause`, the verifier raises
    `ask_without_oq`.
    """
    base_brief = {
        "items": [],
        "goal_terms": {
            "travel_time": {"weight": 1.0, "type": "objective"},
        },
        "open_questions": [],
    }
    issues = verify_brief_consistency(
        merged_brief=base_brief,
        base_brief=base_brief,
        patch={},
        visible_reply=(
            "What specific adjustment would you like to make next — for "
            "instance, should we increase the weight on workload balance "
            "to ensure more equitable shift durations, or would you like "
            "to explore a different search strategy?"
        ),
        workflow_mode="waterfall",
        question_clause=(
            "Should we increase the weight on workload balance, or explore "
            "a different search strategy?"
        ),
    )
    assert any(i.category == "ask_without_oq" for i in issues)
