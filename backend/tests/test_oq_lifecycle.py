"""Tests for OQ + assumption lifecycle: per-row actions, structural anchor
resolution, and the verifier check that catches `replace_open_questions=true`
without a survivor list. The headline reproducer is the P_l7 session: agent
proposed two post-run weight OQs, user said "yes to both!", patch committed
the goal_terms + items but the OQs survived because the LLM omitted the
`open_questions` field while setting the replace flag.
"""

from __future__ import annotations

from app.problem_brief import (
    merge_problem_brief_patch,
    normalize_problem_brief,
)
from app.routers.sessions.derivation import (
    _apply_oq_actions,
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
    # Note: after this, the existing normalize pass will fold the answered
    # row into a gathered item; the action itself just writes status/text.
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
# Layer 2: _resolve_anchored_provisional_rows
# ---------------------------------------------------------------------------


def test_anchored_oq_dropped_once_goal_term_lands_waterfall():
    brief = normalize_problem_brief(
        _minimal_brief(
            open_questions=[
                {
                    "id": "q-cap",
                    "text": "Should I add a capacity penalty?",
                    "topic": "other",
                    "proposes_goal_term_key": "capacity_penalty",
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
    after = _resolve_anchored_provisional_rows(brief, "waterfall")
    assert [q["id"] for q in after["open_questions"]] == ["q-unrelated"]


def test_anchored_oq_kept_when_key_not_yet_committed():
    brief = normalize_problem_brief(
        _minimal_brief(
            open_questions=[
                {
                    "id": "q-cap",
                    "text": "Should I add a capacity penalty?",
                    "topic": "other",
                    "proposes_goal_term_key": "capacity_penalty",
                },
            ],
            goal_terms={"travel_time": {"weight": 1.0, "type": "objective"}},
        )
    )
    after = _resolve_anchored_provisional_rows(brief, "waterfall")
    assert [q["id"] for q in after["open_questions"]] == ["q-cap"]


def test_foundational_oq_with_anchor_is_not_dropped_by_resolver():
    # Foundational OQs are server-monitor owned; the resolver must not
    # touch them even if (somehow) they got tagged with an anchor.
    brief = normalize_problem_brief(
        _minimal_brief(
            open_questions=[
                {
                    "id": "oq-monitor-algorithm",
                    "text": "Which search method?",
                    "topic": "search_strategy",
                    "proposes_goal_term_key": "search_strategy",
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
    after = _resolve_anchored_provisional_rows(brief, "waterfall")
    assert [q["id"] for q in after["open_questions"]] == ["oq-monitor-algorithm"]


def test_anchored_assumption_stays_when_only_assumption_evidence_agile():
    brief = normalize_problem_brief(
        _minimal_brief(
            items=[
                {
                    "id": "item-assumption-cap",
                    "text": "Capacity penalty (soft, weight 10.0).",
                    "kind": "assumption",
                    "source": "agent",
                    "proposes_goal_term_key": "capacity_penalty",
                },
            ],
            goal_terms={"capacity_penalty": {"weight": 10.0, "type": "soft"}},
        )
    )
    after = _resolve_anchored_provisional_rows(brief, "agile")
    ids = [it["id"] for it in after["items"]]
    assert "item-assumption-cap" in ids


def test_anchored_assumption_dropped_when_user_gathered_evidence_lands_agile():
    brief = normalize_problem_brief(
        _minimal_brief(
            items=[
                {
                    "id": "item-assumption-cap",
                    "text": "Capacity penalty (soft, weight 10.0).",
                    "kind": "assumption",
                    "source": "agent",
                    "proposes_goal_term_key": "capacity_penalty",
                },
                {
                    "id": "item-gathered-cap",
                    "text": "Capacity penalty (soft, weight 10.0) — user-confirmed.",
                    "kind": "gathered",
                    "source": "user",
                    "proposes_goal_term_key": "capacity_penalty",
                },
            ],
            goal_terms={"capacity_penalty": {"weight": 10.0, "type": "soft"}},
        )
    )
    after = _resolve_anchored_provisional_rows(brief, "agile")
    ids = [it["id"] for it in after["items"]]
    assert "item-assumption-cap" not in ids
    assert "item-gathered-cap" in ids


def test_anchored_assumption_not_dropped_by_canonical_synth_row_alone():
    # The canonical config-weight-K row is synthesized with source="agent",
    # so it must NOT count as user-confirmation evidence.
    brief = normalize_problem_brief(
        _minimal_brief(
            items=[
                {
                    "id": "item-assumption-cap",
                    "text": "Capacity penalty (soft, weight 10.0).",
                    "kind": "assumption",
                    "source": "agent",
                    "proposes_goal_term_key": "capacity_penalty",
                },
                {
                    "id": "config-weight-capacity_penalty",
                    "text": "Capacity penalty (soft constraint, weight 10.0) — synthesized.",
                    "kind": "gathered",
                    "source": "agent",
                },
            ],
            goal_terms={"capacity_penalty": {"weight": 10.0, "type": "soft"}},
        )
    )
    after = _resolve_anchored_provisional_rows(brief, "agile")
    ids = [it["id"] for it in after["items"]]
    assert "item-assumption-cap" in ids


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
# P_l7 regression replay: full apply pipeline run on the recorded patch
# ---------------------------------------------------------------------------


def test_p_l7_yes_to_both_drops_both_oqs_via_resolver():
    """Replay of session 26f47919 (P_l7) message 1629.

    Pre-turn brief had two open OQs proposing capacity_penalty and
    lateness_penalty. The LLM patch added both goal_terms + gathered items
    but set `replace_open_questions=true` with the field omitted (so the
    merge preserved the OQs). With the anchor field set on the OQs, the
    deterministic resolver drops them once the goal_terms land — no
    reliance on the LLM remembering to include the survivor list.
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
                {
                    "id": "config-weight-travel_time",
                    "text": "Travel time (primary objective, weight 1.0).",
                    "kind": "gathered",
                    "source": "agent",
                },
            ],
            open_questions=[
                {
                    "id": "question-capacity-penalty",
                    "text": "Should I add a capacity penalty (soft, weight 10.0)?",
                    "topic": "other",
                    "proposes_goal_term_key": "capacity_penalty",
                },
                {
                    "id": "question-punctuality-penalty",
                    "text": "Should I add a lateness penalty (soft, weight 10.0)?",
                    "topic": "other",
                    "proposes_goal_term_key": "lateness_penalty",
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
    patch = {
        "items": [
            {
                "id": "item-gathered-capacity-penalty",
                "text": "Capacity penalty (soft, weight 10.0).",
                "kind": "gathered",
                "source": "user",
            },
            {
                "id": "item-gathered-punctuality-penalty",
                "text": "Lateness penalty (soft, weight 10.0).",
                "kind": "gathered",
                "source": "user",
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
    # Now run the deterministic resolver — both anchored OQs should drop.
    resolved = _resolve_anchored_provisional_rows(merged, "waterfall")
    assert resolved["open_questions"] == []
    assert "capacity_penalty" in resolved["goal_terms"]
    assert "lateness_penalty" in resolved["goal_terms"]
