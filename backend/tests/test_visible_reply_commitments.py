"""Unit tests for the deterministic visible-reply commitment helpers.

These cover the GA-bug failure mode reported by the user: agent's visible
reply commits "I've set search strategy to genetic search (GA)" but the
brief patch doesn't carry an items[] row anchoring the algorithm, so the
Run button stays greyed out. The helpers provide:

- a closed-vocabulary scanner over the visible reply,
- a synthesizer that injects the missing assumption row, and
- a speculative gate probe that predicts post-merge run-readiness.
"""

from __future__ import annotations

import json

import pytest

from app.problem_brief import default_problem_brief
from app.problems.registry import get_study_port
from app.services.visible_reply_commitments import (
    brief_mentions_algorithm,
    extract_algorithm_commitment,
    inject_algorithm_assumption,
    speculative_brief_after_patch,
    speculative_intrinsic_gate_ready,
    synthesize_algorithm_assumption_row,
)

_PORT = get_study_port("vrptw")
_W1 = _PORT.weight_display_keys()[0]


def test_extract_algorithm_commitment_canonical_acronyms():
    """Each canonical acronym should be detectable when surrounded by
    word boundaries — this is the form the agile prompt is supposed to
    produce ("Search strategy is set to GA …")."""
    assert extract_algorithm_commitment("Search strategy is set to GA.") == "GA"
    assert extract_algorithm_commitment("Using PSO for this run.") == "PSO"
    assert extract_algorithm_commitment("I've defaulted to SA.") == "SA"
    assert extract_algorithm_commitment("Trying ACOR as a starting point.") == "ACOR"


def test_extract_algorithm_commitment_plain_language_aliases():
    """The agile prompt also uses friendly nicknames ("genetic search").
    Detection must match what the panel-derive's brief-extract does so the
    safety net's injection vocabulary matches the downstream extractor."""
    assert (
        extract_algorithm_commitment("I'm starting from genetic search as a baseline.")
        == "GA"
    )
    assert (
        extract_algorithm_commitment("Falling back to simulated annealing.") == "SA"
    )
    assert (
        extract_algorithm_commitment("Using particle swarm optimization here.") == "PSO"
    )
    # Long alias must win over the short alias inside it (SwarmSA includes SA).
    assert (
        extract_algorithm_commitment(
            "Switching to swarm-based simulated annealing for the next run."
        )
        == "SwarmSA"
    )


def test_extract_algorithm_commitment_word_boundary_for_short_aliases():
    """Short acronyms (ga, sa) must be word-boundary checked or every word
    containing those letters would false-positive."""
    assert extract_algorithm_commitment("saga is a great movie") is None
    assert extract_algorithm_commitment("the gateway is open") is None
    # Trailing punctuation still counts as a boundary.
    assert extract_algorithm_commitment("Algorithm: GA!") == "GA"


def test_extract_algorithm_commitment_returns_none_for_unrelated_text():
    assert extract_algorithm_commitment("") is None
    assert extract_algorithm_commitment(None) is None
    assert extract_algorithm_commitment("Let me know your goal first.") is None


def test_synthesize_algorithm_assumption_row_has_stable_id_and_kind():
    """Stable id keeps repeat injections idempotent; kind/source must be
    `assumption`/`agent` to honour agile's structured-carrier contract."""
    row = synthesize_algorithm_assumption_row("GA")
    assert row["id"] == "item-assumption-algorithm-ga"
    assert row["kind"] == "assumption"
    assert row["source"] == "agent"
    assert "GA" in row["text"]
    # Nickname surfaces too so the Definition tab reads naturally.
    assert "genetic search" in row["text"].lower()


def test_brief_mentions_algorithm_finds_anchor_text():
    brief = default_problem_brief("vrptw")
    brief["items"] = [
        {"id": "g-1", "text": "Search strategy is set to genetic search (GA).", "kind": "assumption", "source": "agent"}
    ]
    assert brief_mentions_algorithm(brief, "GA") is True
    assert brief_mentions_algorithm(brief, "PSO") is False
    # Empty / malformed inputs are safe.
    assert brief_mentions_algorithm(None, "GA") is False
    assert brief_mentions_algorithm({}, "GA") is False


def test_inject_algorithm_assumption_adds_row_when_missing():
    """The GA-bug scenario: chat-turn produced a patch with goal_terms but
    no algorithm row. Injection must add the row and report `did_inject`."""
    base = default_problem_brief("vrptw")
    base["items"] = [
        {"id": "g-user-1", "text": "User wants to minimize total travel time.", "kind": "gathered", "source": "user"}
    ]
    patch = {
        "items": [
            {"id": "g-user-1", "text": "User wants to minimize total travel time.", "kind": "gathered", "source": "user"}
        ],
        "goal_terms": {
            _W1: {"weight": 1.0, "type": "objective", "evidence_item_ids": ["g-user-1"]}
        },
    }
    new_patch, did_inject = inject_algorithm_assumption(patch, base, "GA")
    assert did_inject is True
    assert new_patch is not None
    new_items = new_patch.get("items") or []
    assert any(
        item.get("id") == "item-assumption-algorithm-ga"
        and item.get("kind") == "assumption"
        for item in new_items
    )
    # Original input must not be mutated.
    assert all(
        item.get("id") != "item-assumption-algorithm-ga"
        for item in patch.get("items") or []
    )


def test_inject_algorithm_assumption_is_idempotent_when_base_already_has_it():
    base = default_problem_brief("vrptw")
    base["items"] = [
        {
            "id": "item-assumption-algorithm-ga",
            "text": "Search strategy is set to genetic search (GA) as a starting point — change anytime.",
            "kind": "assumption",
            "source": "agent",
        }
    ]
    new_patch, did_inject = inject_algorithm_assumption({}, base, "GA")
    assert did_inject is False


def test_inject_algorithm_assumption_is_idempotent_when_patch_already_has_it():
    """If the patch ALREADY carries an items[] row mentioning the algorithm
    (the LLM did its job), injection must be a no-op."""
    base = default_problem_brief("vrptw")
    patch = {
        "items": [
            {
                "id": "g-foo",
                "text": "Going with genetic search as a baseline.",
                "kind": "assumption",
                "source": "agent",
            }
        ]
    }
    new_patch, did_inject = inject_algorithm_assumption(patch, base, "GA")
    assert did_inject is False


def test_inject_algorithm_assumption_handles_none_patch():
    """When the chat-turn returned no patch at all (consolidated success
    path), injection must synthesize a fresh patch dict."""
    base = default_problem_brief("vrptw")
    new_patch, did_inject = inject_algorithm_assumption(None, base, "GA")
    assert did_inject is True
    assert new_patch is not None
    assert any(
        item.get("id") == "item-assumption-algorithm-ga"
        for item in new_patch.get("items") or []
    )


def test_speculative_brief_after_patch_unions_items():
    base = default_problem_brief("vrptw")
    base["items"] = [{"id": "a", "text": "x", "kind": "gathered", "source": "user"}]
    patch = {
        "items": [
            {"id": "a", "text": "x", "kind": "gathered", "source": "user"},  # dedupe
            {"id": "b", "text": "y", "kind": "assumption", "source": "agent"},
        ],
        "goal_terms": {"travel_time": {"weight": 1.0, "type": "objective"}},
    }
    merged = speculative_brief_after_patch(base, patch)
    item_ids = {item.get("id") for item in merged.get("items") or []}
    assert item_ids == {"a", "b"}
    assert "travel_time" in (merged.get("goal_terms") or {})


def test_speculative_gate_predicts_run_ready_after_ga_injection():
    """The probe should return True for an agile setup where the brief has
    a goal_terms weight and the visible reply commits to GA — even if the
    panel doesn't yet have algorithm set (BG would set it from the brief
    via panel-derive)."""
    base = default_problem_brief("vrptw")
    panel = json.loads(
        json.dumps({"problem": {"weights": {_W1: 1.0}, "algorithm": ""}})
    )
    patch = {
        "items": [
            {
                "id": "g-1",
                "text": "User wants to minimize travel time.",
                "kind": "gathered",
                "source": "user",
            }
        ],
        "goal_terms": {
            _W1: {
                "weight": 1.0,
                "type": "objective",
                "evidence_item_ids": ["g-1"],
            }
        },
    }
    # Without the algorithm commit, the speculative panel still has algorithm=""
    # — gate must remain closed.
    assert (
        speculative_intrinsic_gate_ready(
            "agile",
            base,
            panel,
            patch,
            algorithm_commitment=None,
            problem_id="vrptw",
        )
        is False
    )
    # With the algorithm commit, the speculative panel gets algorithm=GA and
    # the gate opens — this is the path the pre-release probe relies on.
    assert (
        speculative_intrinsic_gate_ready(
            "agile",
            base,
            panel,
            patch,
            algorithm_commitment="GA",
            problem_id="vrptw",
        )
        is True
    )


def test_speculative_gate_stays_closed_when_no_goal_term():
    """If no goal-term weight is in the brief AND none in the panel, even
    a fresh algorithm commit shouldn't open the gate — the agent's reply
    has more than one structural gap."""
    base = default_problem_brief("vrptw")
    panel = {"problem": {"weights": {}, "algorithm": ""}}
    assert (
        speculative_intrinsic_gate_ready(
            "agile",
            base,
            panel,
            None,
            algorithm_commitment="GA",
            problem_id="vrptw",
        )
        is False
    )
