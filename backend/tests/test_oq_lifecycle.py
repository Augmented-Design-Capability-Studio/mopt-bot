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
    _enforce_session_monitors,
    _has_gathered_evidence_for_key,
    _resolve_anchored_provisional_rows,
    _set_search_strategy_algorithm,
    gate_locked_goal_term_changes,
    gate_unauthorized_search_strategy_commit,
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


def test_dedupes_duplicate_add_proposals_for_absent_concept():
    """Two OPEN questions both proposing to ADD the same not-yet-existing
    concept (same goal_key, no committed goal_term) collapse to one — the
    `oq-lateness` + `oq-lateness-explanation` re-ask. Keeps the first."""
    brief = normalize_problem_brief(
        _minimal_brief(
            goal_terms={},  # lateness_penalty NOT committed yet → add-proposals
            open_questions=[
                {"id": "oq-lateness", "text": "Add a lateness penalty?", "topic": "other", "goal_key": "lateness_penalty"},
                {"id": "oq-lateness-explanation", "text": "Should I add a lateness penalty?", "topic": "other", "goal_key": "lateness_penalty"},
            ],
        )
    )
    assert [q["id"] for q in brief["open_questions"]] == ["oq-lateness"]


def test_tuning_question_coexists_with_existing_concept_state():
    """The correction: a question is a pending DECISION, not the concept's
    state. A tuning/change question about a concept that already has an
    assumption (or gathered fact) is NOT a duplicate — it must coexist.
    Here `lateness_penalty` is committed and has an assumption row, yet a
    'raise the weight?' question about it survives."""
    brief = normalize_problem_brief(
        _minimal_brief(
            goal_terms={"lateness_penalty": {"weight": 5.0, "type": "soft", "rank": 1}},
            items=[
                {
                    "id": "item-assumption-late",
                    "text": "Lateness penalty (soft, weight 5) — assumed to push punctuality.",
                    "kind": "assumption",
                    "source": "agent",
                    "goal_key": "lateness_penalty",
                },
            ],
            open_questions=[
                {"id": "oq-late-tune", "text": "Raise the lateness weight to 30?", "topic": "other", "goal_key": "lateness_penalty"},
            ],
        )
    )
    assert [q["id"] for q in brief["open_questions"]] == ["oq-late-tune"]


def test_keeps_distinct_absent_concept_add_proposals():
    """Add-proposals for two DIFFERENT absent concepts both survive — dedup
    only collapses same-key duplicates."""
    brief = normalize_problem_brief(
        _minimal_brief(
            goal_terms={},
            open_questions=[
                {"id": "oq-late", "text": "Add lateness?", "topic": "other", "goal_key": "lateness_penalty"},
                {"id": "oq-cap", "text": "Add capacity?", "topic": "other", "goal_key": "capacity_penalty"},
                {"id": "oq-free", "text": "Anything else?", "topic": "other"},
            ],
        )
    )
    assert [q["id"] for q in brief["open_questions"]] == ["oq-late", "oq-cap", "oq-free"]


def test_one_state_per_goal_key_gathered_beats_assumption():
    """INV2: a concept can't be both gathered and assumption at once. When both
    LLM-authored rows exist for one goal_key, the gathered (user-confirmed) one
    wins and the assumption is dropped."""
    brief = normalize_problem_brief(
        _minimal_brief(
            goal_terms={"lateness_penalty": {"weight": 5.0, "type": "soft", "rank": 1}},
            items=[
                {"id": "g-late", "text": "Lateness penalty soft weight 5.", "kind": "gathered", "source": "user", "goal_key": "lateness_penalty"},
                {"id": "a-late", "text": "Assume a lateness penalty.", "kind": "assumption", "source": "agent", "goal_key": "lateness_penalty"},
            ],
        )
    )
    states = [(i["id"], i["kind"]) for i in brief["items"]
              if i.get("goal_key") == "lateness_penalty" and i["kind"] in ("gathered", "assumption")]
    assert states == [("g-late", "gathered")]


def test_one_state_per_goal_key_exempts_synthesized_companion_rows():
    """INV2 exception: server-synthesized rows (``config-`` namespace) are not
    collapsed — a companion-bearing key legitimately has several of them."""
    brief = normalize_problem_brief(
        _minimal_brief(
            goal_terms={"worker_preference": {"weight": 1.0, "type": "soft", "rank": 1}},
            items=[
                {"id": "config-driver-pref-1-a", "text": "Driver 1 avoids zone A.", "kind": "gathered", "source": "agent", "goal_key": "worker_preference"},
                {"id": "config-driver-pref-2-b", "text": "Driver 2 avoids zone B.", "kind": "gathered", "source": "agent", "goal_key": "worker_preference"},
            ],
        )
    )
    pref_ids = [i["id"] for i in brief["items"] if i.get("goal_key") == "worker_preference"]
    assert pref_ids == ["config-driver-pref-1-a", "config-driver-pref-2-b"]


def test_tuning_oq_resolves_when_its_key_is_retuned():
    """P_0529 follow-up: answering "yes" to *"adjust the travel time weight?"*
    in chat bumps the weight, but the OQ lingered because the main turn's
    `drop` is stripped on answered-OQ turns and the resolver only closed
    NEWLY-committed keys. A tuning OQ must close when its already-committed
    key is actually retuned this turn (mirrors the panel-edit path)."""
    tuning_oq = {
        "id": "oq-travel-tuning",
        "text": "Would you like to adjust the travel time weight (currently 1.0)?",
        "topic": "other",
        "goal_key": "travel_time",
    }
    base = normalize_problem_brief(
        _minimal_brief(
            goal_terms={"travel_time": {"weight": 1.0, "type": "objective", "rank": 1}},
            open_questions=[dict(tuning_oq)],
        )
    )
    merged = normalize_problem_brief(
        _minimal_brief(
            items=[_canonical_weight_item("travel_time")],
            goal_terms={"travel_time": {"weight": 3.0, "type": "objective", "rank": 1}},  # retuned
            open_questions=[dict(tuning_oq)],
        )
    )
    after = _resolve_anchored_provisional_rows(merged, "waterfall", base_brief=base)
    assert after["open_questions"] == []


def test_tuning_oq_survives_when_key_untouched():
    """Negative: a tuning OQ whose key is NOT changed this turn stays open —
    the close fires on a real retune, not merely on the key being present."""
    tuning_oq = {
        "id": "oq-travel-tuning",
        "text": "Adjust the travel time weight?",
        "topic": "other",
        "goal_key": "travel_time",
    }
    base = normalize_problem_brief(
        _minimal_brief(
            goal_terms={"travel_time": {"weight": 1.0, "type": "objective", "rank": 1}},
            open_questions=[dict(tuning_oq)],
        )
    )
    merged = normalize_problem_brief(
        _minimal_brief(
            items=[_canonical_weight_item("travel_time")],
            goal_terms={"travel_time": {"weight": 1.0, "type": "objective", "rank": 1}},  # unchanged
            open_questions=[dict(tuning_oq)],
        )
    )
    after = _resolve_anchored_provisional_rows(merged, "waterfall", base_brief=base)
    assert [q["id"] for q in after["open_questions"]] == ["oq-travel-tuning"]


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
    """The resolver only drops OPEN QUESTIONS, never assumption items —
    promotion is an explicit user/LLM action (`assumption_actions`), not a
    silent resolver side effect. The assumption is the only state for this
    key here (the gathered+assumption-for-one-key case is owned by INV2,
    `_reconcile_problem_brief_items`; see
    ``test_one_state_per_goal_key_gathered_beats_assumption``)."""
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
            ],
            goal_terms={"capacity_penalty": {"weight": 10.0, "type": "soft"}},
        )
    )
    after = _resolve_anchored_provisional_rows(merged, "agile", base_brief=base)
    ids = [it["id"] for it in after["items"]]
    assert "item-assumption-cap" in ids


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


# ---------------------------------------------------------------------------
# Waterfall search-strategy authorization gate (P_0529 regression)
# ---------------------------------------------------------------------------


def _ss_carrier_brief(**kwargs):
    """Merged brief shape after an upload turn that FORGED a GA carrier:
    travel_time committed, search_strategy carrier populated, and the
    canonical algorithm OQ already gone (the LLM dropped it)."""
    base = _minimal_brief(
        items=[
            {"id": "upload-marker", "text": "Uploaded ORDERS.csv", "kind": "gathered", "source": "upload"},
            {
                "id": "config-search-strategy-ga",
                "text": "Search strategy: genetic search (GA).",
                "kind": "gathered",
                "source": "user",
                "goal_key": "search_strategy",
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
        topic_engaged=True,
    )
    base.update(kwargs)
    return normalize_problem_brief(base)


def test_waterfall_gate_strips_forged_algorithm_and_refuses_drop():
    """P_0529 replay: upload turn forged a GA carrier and dropped the
    still-open search-strategy OQ. Waterfall gate must strip the carrier +
    the source:user algorithm row and veto the drop action; the monitor
    then re-adds the canonical OQ."""
    base_brief = normalize_problem_brief(
        _minimal_brief(
            items=[{"id": "upload-marker", "text": "Uploaded ORDERS.csv", "kind": "gathered", "source": "upload"}],
            goal_terms={"travel_time": {"weight": 1.0, "type": "objective", "rank": 1}},
            open_questions=[
                {
                    "id": "oq-monitor-algorithm",
                    "text": "Which search strategy should we use?",
                    "topic": "search_strategy",
                    "status": "open",
                }
            ],
            topic_engaged=True,
        )
    )
    effective = _ss_carrier_brief()
    oq_actions = [{"id": "oq-monitor-algorithm", "action": "drop", "answer_text": None}]

    gated, gated_actions = gate_unauthorized_search_strategy_commit(
        effective_brief=effective,
        base_brief=base_brief,
        oq_actions=oq_actions,
        workflow_mode="waterfall",
    )
    # Carrier + forged row gone; real objective survives.
    assert "search_strategy" not in gated["goal_terms"]
    assert "travel_time" in gated["goal_terms"]
    assert not any(i.get("goal_key") == "search_strategy" for i in gated["items"])
    # Drop action vetoed.
    assert gated_actions == []
    # Monitor re-adds the canonical OQ now the carrier reads absent.
    restored = _enforce_session_monitors(gated, "waterfall", test_problem_id="vrptw")
    assert any(q["id"] == "oq-monitor-algorithm" for q in restored["open_questions"])


def test_waterfall_gate_allows_loose_chat_answer():
    """Loose path: when the participant answers in chat and the LLM marks
    the search-strategy OQ answered with a real algorithm name, the carrier
    is authorized and survives."""
    base_brief = normalize_problem_brief(
        _minimal_brief(
            items=[{"id": "upload-marker", "text": "Uploaded ORDERS.csv", "kind": "gathered", "source": "upload"}],
            goal_terms={"travel_time": {"weight": 1.0, "type": "objective", "rank": 1}},
            open_questions=[
                {
                    "id": "oq-monitor-algorithm",
                    "text": "Which search strategy should we use?",
                    "topic": "search_strategy",
                    "status": "open",
                }
            ],
            topic_engaged=True,
        )
    )
    effective = _ss_carrier_brief()
    oq_actions = [
        {"id": "oq-monitor-algorithm", "action": "mark_answered", "answer_text": "genetic search (GA)"}
    ]
    gated, gated_actions = gate_unauthorized_search_strategy_commit(
        effective_brief=effective,
        base_brief=base_brief,
        oq_actions=oq_actions,
        workflow_mode="waterfall",
    )
    assert gated["goal_terms"]["search_strategy"]["properties"]["algorithm"] == "GA"
    assert gated_actions == oq_actions  # untouched


def test_waterfall_gate_honors_prior_answered_oq():
    """If the participant already answered the OQ on a prior turn (textarea
    save → status answered), later carrier writes are authorized."""
    base_brief = normalize_problem_brief(
        _minimal_brief(
            goal_terms={"travel_time": {"weight": 1.0, "type": "objective", "rank": 1}},
            open_questions=[
                {
                    "id": "oq-monitor-algorithm",
                    "text": "Which search strategy should we use?",
                    "topic": "search_strategy",
                    "status": "answered",
                    "answer_text": "GA",
                }
            ],
            topic_engaged=True,
        )
    )
    effective = _ss_carrier_brief()
    gated, gated_actions = gate_unauthorized_search_strategy_commit(
        effective_brief=effective,
        base_brief=base_brief,
        oq_actions=[],
        workflow_mode="waterfall",
    )
    assert gated["goal_terms"]["search_strategy"]["properties"]["algorithm"] == "GA"


def test_waterfall_gate_noop_in_agile():
    """Agile commits the algorithm as a fait-accompli assumption — the gate
    must never fire outside waterfall."""
    effective = _ss_carrier_brief()
    gated, gated_actions = gate_unauthorized_search_strategy_commit(
        effective_brief=effective,
        base_brief=_minimal_brief(),
        oq_actions=[{"id": "oq-monitor-algorithm", "action": "drop"}],
        workflow_mode="agile",
    )
    assert gated["goal_terms"]["search_strategy"]["properties"]["algorithm"] == "GA"
    assert gated_actions == [{"id": "oq-monitor-algorithm", "action": "drop"}]


def test_waterfall_gate_commits_user_chat_choice_even_without_carrier():
    """P_0529 recurrence: the participant answered the search-strategy OQ in
    chat ("ant colony" / "ACOR") but the algorithm never committed and the OQ
    stayed. Now the main turn reports the participant's choice via
    ``user_search_strategy_choice``; the gate commits the carrier
    deterministically (even if the LLM forgot to set it) and the monitor
    clears the OQ."""
    base_brief = normalize_problem_brief(
        _minimal_brief(
            items=[{"id": "upload-marker", "text": "Uploaded ORDERS.csv", "kind": "gathered", "source": "upload"}],
            goal_terms={"travel_time": {"weight": 1.0, "type": "objective", "rank": 1}},
            open_questions=[
                {
                    "id": "oq-monitor-algorithm",
                    "text": "Which search strategy should we use?",
                    "topic": "search_strategy",
                    "status": "open",
                }
            ],
            topic_engaged=True,
        )
    )
    # Effective brief has NO carrier — the LLM only reported the user's choice.
    effective = normalize_problem_brief(
        _minimal_brief(
            items=list(base_brief["items"]),
            goal_terms={"travel_time": {"weight": 1.0, "type": "objective", "rank": 1}},
            open_questions=list(base_brief["open_questions"]),
            topic_engaged=True,
        )
    )

    for user_words in ("ant colony", "ACOR"):
        gated, _actions = gate_unauthorized_search_strategy_commit(
            effective_brief=effective,
            base_brief=base_brief,
            oq_actions=[],
            workflow_mode="waterfall",
            user_search_strategy_choice=user_words,
        )
        # Carrier committed (canonical), regardless of how the user phrased it.
        assert gated["goal_terms"]["search_strategy"]["properties"]["algorithm"] == "ACOR"
        # Monitor now reads the carrier present → clears the search-strategy OQ.
        restored = _enforce_session_monitors(gated, "waterfall", test_problem_id="vrptw")
        assert not any(q["id"] == "oq-monitor-algorithm" for q in restored["open_questions"])


def test_waterfall_gate_ignores_invalid_user_choice():
    """An unrecognized ``user_search_strategy_choice`` must NOT authorize a
    commit — it falls through to the normal forgery guard (no carrier present,
    nothing to authorize)."""
    base_brief = normalize_problem_brief(_minimal_brief(topic_engaged=True))
    effective = _ss_carrier_brief()  # carries a forged GA, no real answer
    gated, _actions = gate_unauthorized_search_strategy_commit(
        effective_brief=effective,
        base_brief=base_brief,
        oq_actions=[{"id": "oq-monitor-algorithm", "action": "drop"}],
        workflow_mode="waterfall",
        user_search_strategy_choice="please just pick something good",
    )
    # Not a real algorithm name → no authorization → forged carrier stripped.
    assert "search_strategy" not in gated["goal_terms"]


def test_set_search_strategy_algorithm_creates_normalize_surviving_carrier():
    """P_lk: a participant answering the search-strategy OQ ("Use GA") commits a
    FRESH carrier — there's no agent-committed entry to update. The carrier must
    be created with the full scalar trio (weight/type/rank), or
    ``normalize_problem_brief`` drops it as malformed on the very next turn and
    the OQ bounces back open. An existing entry keeps its own scalars."""
    base = normalize_problem_brief(
        _minimal_brief(
            goal_terms={"value_emphasis": {"weight": 1.0, "type": "objective", "rank": 1}},
            topic_engaged=True,
        )
    )
    out = _set_search_strategy_algorithm(base, "GA")
    ss = out["goal_terms"]["search_strategy"]
    assert ss["properties"]["algorithm"] == "GA"
    assert isinstance(ss["weight"], (int, float))
    assert isinstance(ss["type"], str) and ss["type"].strip()
    assert ss["rank"] == 2  # next available after value_emphasis (rank 1)
    # Survives a normalize round-trip (the malformed-carrier drop is what bit P_lk).
    renorm = normalize_problem_brief(out)
    assert "search_strategy" in renorm["goal_terms"]
    assert (
        renorm["goal_terms"]["search_strategy"]["properties"]["algorithm"] == "GA"
    )


def test_agile_algorithm_assumption_row_stays_visible_after_carrier_set():
    """P_lk (agile): the algorithm is an ASSUMPTION the participant must SEE and
    can override — the tutorial gates on it. The carrier-only ``search_strategy``
    term has no synthesized config-weight row, so the monitor's assumption row is
    its only visible representation on the chat path. Committing the carrier must
    NOT erase that row (the old bug dropped it the moment ``brief_mentions`` went
    True, leaving the algorithm invisible). The row tracks the committed
    algorithm; it survives the items[] whitelist; waterfall still shows an OQ."""
    from app.routers.sessions.derivation import (
        _MONITOR_ITEM_ALGORITHM_ID,
        _MONITOR_OQ_ALGORITHM_ID,
        _set_search_strategy_algorithm,
        apply_brief_patch_with_cleanup,
    )

    base = normalize_problem_brief(
        _minimal_brief(
            items=[{"id": "item-gathered-upload", "text": "Uploaded ORDERS.csv",
                    "kind": "gathered", "source": "upload"}],
            goal_terms={"value_emphasis": {"weight": 1.0, "type": "objective", "rank": 1}},
            topic_engaged=True,
        )
    )
    committed = _set_search_strategy_algorithm(base, "SA")  # agent assumed SA

    out, _meta = apply_brief_patch_with_cleanup(
        base_problem_brief=committed,
        patch_payload={},
        workflow_mode="agile",
        recent_runs_summary=[],
        test_problem_id="knapsack",
        user_text="ok",
    )
    final = _enforce_session_monitors(out, "agile", test_problem_id="knapsack")
    algo_rows = [
        it for it in final["items"] if it.get("id") == _MONITOR_ITEM_ALGORITHM_ID
    ]
    assert algo_rows, "agile algorithm assumption row must stay visible"
    assert algo_rows[0]["kind"] == "assumption"
    assert "annealing" in algo_rows[0]["text"].lower(), algo_rows[0]["text"]
    # No OQ in agile (the algorithm is an assumption, not a question).
    assert not any(q.get("id") == _MONITOR_OQ_ALGORITHM_ID for q in final["open_questions"])

    # Waterfall: no assumption row, an OQ instead.
    wf = _enforce_session_monitors(base, "waterfall", test_problem_id="knapsack")
    assert not any(it.get("id") == _MONITOR_ITEM_ALGORITHM_ID for it in wf["items"])
    assert any(q.get("id") == _MONITOR_OQ_ALGORITHM_ID for q in wf["open_questions"])


def test_locked_gate_reverts_change_and_raises_oq_brief_lock():
    """All-mode lock guard: an agent change to a term locked via
    ``goal_terms[key].locked`` is reverted to the locked value and an OQ is
    raised asking the participant to approve unlocking + the change."""
    base = normalize_problem_brief(_minimal_brief(
        goal_terms={"capacity_penalty": {"weight": 10.0, "type": "hard", "rank": 1, "locked": True}},
    ))
    merged = normalize_problem_brief(_minimal_brief(
        goal_terms={"capacity_penalty": {"weight": 30.0, "type": "hard", "rank": 1, "locked": True}},
    ))
    out = gate_locked_goal_term_changes(
        effective_brief=merged, base_brief=base, base_panel=None, test_problem_id="vrptw"
    )
    assert out["goal_terms"]["capacity_penalty"]["weight"] == 10.0  # frozen
    oq = [q for q in out["open_questions"] if q["id"] == "oq-locked-change-capacity_penalty"]
    assert len(oq) == 1 and oq[0]["goal_key"] == "capacity_penalty"


def test_locked_gate_honors_panel_lock_list():
    """Lock recorded via the panel's ``locked_goal_terms`` id list is honored
    even when the brief entry isn't flagged — the two surfaces are equivalent."""
    base = normalize_problem_brief(_minimal_brief(
        goal_terms={"travel_time": {"weight": 1.0, "type": "objective", "rank": 1}},
    ))
    merged = normalize_problem_brief(_minimal_brief(
        goal_terms={"travel_time": {"weight": 9.0, "type": "objective", "rank": 1}},
    ))
    panel = {"problem": {"locked_goal_terms": ["travel_time"]}}
    out = gate_locked_goal_term_changes(
        effective_brief=merged, base_brief=base, base_panel=panel, test_problem_id="vrptw"
    )
    assert out["goal_terms"]["travel_time"]["weight"] == 1.0
    assert any(q["id"] == "oq-locked-change-travel_time" for q in out["open_questions"])


def test_locked_gate_passes_unlocked_change_through():
    """An unlocked term changes freely — no revert, no OQ."""
    base = normalize_problem_brief(_minimal_brief(
        goal_terms={"travel_time": {"weight": 1.0, "type": "objective", "rank": 1}},
    ))
    merged = normalize_problem_brief(_minimal_brief(
        goal_terms={"travel_time": {"weight": 9.0, "type": "objective", "rank": 1}},
    ))
    out = gate_locked_goal_term_changes(
        effective_brief=merged, base_brief=base, base_panel=None, test_problem_id="vrptw"
    )
    assert out["goal_terms"]["travel_time"]["weight"] == 9.0
    assert not any(str(q["id"]).startswith("oq-locked-change-") for q in out["open_questions"])


def test_locked_gate_noop_when_locked_term_unchanged():
    """Locked but untouched → no spurious OQ."""
    base = normalize_problem_brief(_minimal_brief(
        goal_terms={"capacity_penalty": {"weight": 10.0, "type": "hard", "rank": 1, "locked": True}},
    ))
    merged = normalize_problem_brief(_minimal_brief(
        goal_terms={"capacity_penalty": {"weight": 10.0, "type": "hard", "rank": 1, "locked": True}},
    ))
    out = gate_locked_goal_term_changes(
        effective_brief=merged, base_brief=base, base_panel=None, test_problem_id="vrptw"
    )
    assert not any(str(q["id"]).startswith("oq-locked-change-") for q in out["open_questions"])


def test_foundational_ask_warms_brief_same_turn():
    """Fix B: the agent's first 'what's your primary goal?' reply carries a
    foundational-topic OQ in its patch. We strip the LLM's copy but flip
    topic_engaged so the canonical goal monitor fires the SAME turn."""
    base_brief = normalize_problem_brief(
        _minimal_brief(goal_summary="", goal_terms={}, open_questions=[], topic_engaged=False)
    )
    merged = merge_problem_brief_patch(
        base_brief,
        {
            "open_questions": [
                {
                    "id": "question-primary-goal",
                    "text": "What is your primary goal for the fleet?",
                    "topic": "primary_goal",
                    "status": "open",
                }
            ],
        },
    )
    assert merged["topic_engaged"] is True
    # Warm + empty goal_terms → monitor surfaces the canonical goal OQ.
    after = _enforce_session_monitors(merged, "waterfall", test_problem_id="vrptw")
    assert any(q["id"] == "oq-monitor-goal" for q in after["open_questions"])


def test_answered_oq_proposing_goal_term_makes_one_canonical_row_no_prose(monkeypatch):
    """Answering an OQ that proposes a goal term seeds the term and yields its
    single canonical config-weight row — NOT a separate
    item-gathered-from-question prose row duplicating it."""
    from app.routers.sessions.router import _route_oq_answers_through_classifier
    from app.schemas import OpenQuestionClassification, OpenQuestionGoalTermProposal

    def _fake_classify(**kwargs):
        return [
            OpenQuestionClassification(
                question_id="oq-wb",
                bucket="gathered",
                rephrased_text="Workload balance enabled as a soft constraint.",
                goal_term_proposal=OpenQuestionGoalTermProposal(
                    key="workload_balance", type="soft"
                ),
            )
        ]

    monkeypatch.setattr(
        "app.services.llm.classify_answered_open_questions", _fake_classify
    )

    incoming = {
        "items": [
            {"id": "item-gathered-upload", "text": "data", "kind": "gathered", "source": "upload"}
        ],
        "open_questions": [
            {"id": "oq-wb", "text": "Add workload balance as a priority?",
             "status": "answered", "answer_text": "yes please", "goal_key": "workload_balance"}
        ],
        "goal_terms": {},
    }
    out = _route_oq_answers_through_classifier(
        incoming_brief=incoming,
        persisted_open_questions=[],
        workflow_mode="waterfall",
        api_key="x",
        model_name="m",
        test_problem_id="vrptw",
    )
    ids = {i["id"] for i in out["items"]}
    assert not any("from-question" in i for i in ids), ids  # no duplicate prose row
    assert "config-weight-workload_balance" in ids  # single canonical row
    assert "workload_balance" in out["goal_terms"]  # term seeded
    assert not any(q["id"] == "oq-wb" for q in out["open_questions"])  # OQ consumed


def test_answered_oq_declining_tuning_of_existing_term_makes_no_prose(monkeypatch):
    """Declining a tuning OQ about an EXISTING term ('not now') must not leave a
    no-op prose row ('Capacity penalty remains at weight 1.0 …') beside the
    term's canonical weight row. The OQ's goal_key is the signal."""
    from app.routers.sessions.router import _route_oq_answers_through_classifier
    from app.schemas import OpenQuestionClassification

    def _fake_classify(**kwargs):
        return [
            OpenQuestionClassification(
                question_id="question-capacity-weight",
                bucket="gathered",
                rephrased_text="Capacity penalty remains at a weight of 1.0, treating load limits as a soft constraint.",
                goal_term_proposal=None,  # decline → nothing new to add
            )
        ]

    monkeypatch.setattr(
        "app.services.llm.classify_answered_open_questions", _fake_classify
    )

    incoming = {
        "items": [
            {"id": "config-weight-capacity_penalty",
             "text": "Load capacity (soft constraint, weight 1.0) — to discourage overloading.",
             "kind": "gathered", "source": "agent", "goal_key": "capacity_penalty"}
        ],
        "open_questions": [
            {"id": "question-capacity-weight",
             "text": "Should I increase the capacity penalty weight (currently 1.0)?",
             "status": "answered", "answer_text": "not now", "goal_key": "capacity_penalty"}
        ],
        "goal_terms": {"capacity_penalty": {"weight": 1.0, "type": "soft", "rank": 1}},
    }
    out = _route_oq_answers_through_classifier(
        incoming_brief=incoming,
        persisted_open_questions=[],
        workflow_mode="waterfall",
        api_key="x",
        model_name="m",
        test_problem_id="vrptw",
    )
    ids = {i["id"] for i in out["items"]}
    assert not any("from-question" in i for i in ids), ids  # no no-op prose row
    assert "config-weight-capacity_penalty" in ids  # canonical row stays
    assert not any(q["id"] == "question-capacity-weight" for q in out["open_questions"])


def test_apply_oq_actions_refuses_to_drop_companion_oq():
    """Server-managed companion OQs (`auto-oq-companion-<key>`) must survive an
    agent drop/mark_answered while the companion is still empty — otherwise the
    only thing still asking for the rules dies and the term vanishes silently
    (P_0603: agent dropped the driver-preferences companion OQ, claimed
    'added', but no rules were committed)."""
    from app.routers.sessions.derivation import _apply_oq_actions

    brief = {
        "open_questions": [
            {"id": "auto-oq-companion-worker_preference", "text": "Which driver…?",
             "status": "open", "goal_key": "worker_preference"},
            {"id": "question-other", "text": "Something else?", "status": "open"},
        ]
    }
    out = _apply_oq_actions(
        brief,
        [
            {"id": "auto-oq-companion-worker_preference", "action": "drop"},
            {"id": "question-other", "action": "drop"},
        ],
    )
    ids = {q["id"] for q in out["open_questions"]}
    assert "auto-oq-companion-worker_preference" in ids  # protected
    assert "question-other" not in ids  # normal drop still works


# ---------------------------------------------------------------------------
# Canonical weight rows are server-owned (a projection of goal_terms): an
# assumption-action `drop` must not orphan a live goal term, but a genuine
# retirement still drops the row. Plus the post-apply self-heal safety net.
# Reproducer: P_0603 Run #3 ack — agent renamed the capacity row to `…-run3`
# and dropped the canonical id while keeping `capacity_penalty` at weight 30,
# so the synthesized canonical row was deleted and the term lost its def line.
# ---------------------------------------------------------------------------


def test_assumption_drop_refused_for_canonical_row_of_live_term():
    from app.routers.sessions.derivation import _apply_assumption_actions

    brief = {
        "items": [
            {
                "id": "config-weight-capacity_penalty",
                "text": "Load capacity (soft constraint, weight 30.0).",
                "kind": "assumption",
                "source": "agent",
                "goal_key": "capacity_penalty",
            },
        ],
        "goal_terms": {"capacity_penalty": {"weight": 30.0, "type": "soft", "rank": 1}},
    }
    out = _apply_assumption_actions(
        brief, [{"id": "config-weight-capacity_penalty", "action": "drop"}]
    )
    ids = {it["id"] for it in out["items"]}
    assert "config-weight-capacity_penalty" in ids  # guard kept the live term's row


def test_assumption_drop_allowed_when_term_retired():
    """Genuine removal still works: once the goal_term key is gone the row is no
    longer server-owned, so the drop proceeds."""
    from app.routers.sessions.derivation import _apply_assumption_actions

    brief = {
        "items": [
            {
                "id": "config-weight-capacity_penalty",
                "text": "Load capacity (soft constraint, weight 30.0).",
                "kind": "assumption",
                "source": "agent",
                "goal_key": "capacity_penalty",
            },
        ],
        "goal_terms": {},  # term retired this turn
    }
    out = _apply_assumption_actions(
        brief, [{"id": "config-weight-capacity_penalty", "action": "drop"}]
    )
    ids = {it["id"] for it in out["items"]}
    assert "config-weight-capacity_penalty" not in ids  # retired -> drop honored


def test_heal_orphaned_goal_term_rows_rebuilds_missing_row():
    """Safety net: a live goal term with no canonical row gets its row rebuilt."""
    from app.routers.sessions.derivation import _heal_orphaned_goal_term_rows

    brief = normalize_problem_brief(
        _minimal_brief(
            items=[
                {
                    "id": "item-gathered-upload",
                    "text": "Source data file(s) uploaded.",
                    "kind": "gathered",
                    "source": "upload",
                }
            ],
            goal_terms={
                "capacity_penalty": {
                    "weight": 30.0,
                    "type": "soft",
                    "rank": 1,
                    "evidence_item_ids": ["config-weight-capacity_penalty"],
                }
            },
        )
    )
    out = _heal_orphaned_goal_term_rows(brief, "vrptw")
    ids = {it["id"] for it in out["items"]}
    assert "config-weight-capacity_penalty" in ids  # rebuilt the orphaned row


def test_heal_orphaned_goal_term_rows_noop_when_rows_present():
    """The net does not fire (and never duplicates) on a clean brief."""
    from app.routers.sessions.derivation import _heal_orphaned_goal_term_rows

    brief = normalize_problem_brief(
        _minimal_brief(
            items=[
                {
                    "id": "config-weight-capacity_penalty",
                    "text": "Load capacity (soft constraint, weight 30.0).",
                    "kind": "assumption",
                    "source": "agent",
                    "goal_key": "capacity_penalty",
                }
            ],
            goal_terms={
                "capacity_penalty": {
                    "weight": 30.0,
                    "type": "soft",
                    "rank": 1,
                    "evidence_item_ids": ["config-weight-capacity_penalty"],
                }
            },
        )
    )
    out = _heal_orphaned_goal_term_rows(brief, "vrptw")
    cap_rows = [it for it in out["items"] if it["id"] == "config-weight-capacity_penalty"]
    assert len(cap_rows) == 1  # not rebuilt, not duplicated
