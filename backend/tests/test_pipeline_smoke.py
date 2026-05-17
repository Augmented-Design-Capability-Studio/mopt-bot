"""Smoke tests for pipeline verification module."""

import pytest

from app.services.pipeline_verification import (
    categorize_panel_issues,
    issues_to_audit_payload,
    verify_brief_consistency,
    verify_panel_consistency,
)


def test_claim_without_delta():
    issues = verify_brief_consistency(
        merged_brief={"items": [], "goal_terms": {}, "open_questions": []},
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={},
        visible_reply="I've added a lateness penalty as soft.",
        workflow_mode="agile",
    )
    assert any(i.category == "claim_without_delta" for i in issues)


def test_demo_runack_has_no_invariant():
    """Demo mode silently drops assumption rows via workflow coercion, so
    the verifier doesn't impose a run-ack invariant on it (no retry pressure
    for an artifact the merge will discard)."""
    issues = verify_brief_consistency(
        merged_brief={
            "items": [{"id": "i1", "text": "foo", "kind": "gathered"}],
            "goal_terms": {},
            "open_questions": [],
        },
        base_brief={
            "items": [{"id": "i1", "text": "foo", "kind": "gathered"}],
            "goal_terms": {},
            "open_questions": [],
        },
        patch={},
        visible_reply="Run #1 completed with cost 100.",
        workflow_mode="demo",
        is_run_acknowledgement=True,
    )
    assert not any(i.category == "runack_invariant_violation" for i in issues)


def test_agile_runack_missing_assumption():
    issues = verify_brief_consistency(
        merged_brief={
            "items": [{"id": "i1", "text": "foo", "kind": "gathered"}],
            "goal_terms": {},
            "open_questions": [],
        },
        base_brief={
            "items": [{"id": "i1", "text": "foo", "kind": "gathered"}],
            "goal_terms": {},
            "open_questions": [],
        },
        patch={},
        visible_reply="Run #1 completed with cost 100.",
        workflow_mode="agile",
        is_run_acknowledgement=True,
    )
    assert any(i.category == "runack_invariant_violation" for i in issues)


def test_waterfall_runack_missing_oq():
    issues = verify_brief_consistency(
        merged_brief={
            "items": [{"id": "i1", "text": "foo", "kind": "gathered"}],
            "goal_terms": {},
            "open_questions": [],
        },
        base_brief={
            "items": [{"id": "i1", "text": "foo", "kind": "gathered"}],
            "goal_terms": {},
            "open_questions": [],
        },
        patch={},
        visible_reply="Run #1 completed with cost 100.",
        workflow_mode="waterfall",
        is_run_acknowledgement=True,
    )
    assert any(i.category == "runack_invariant_violation" for i in issues)


def test_waterfall_no_assumption_invariant():
    issues = verify_brief_consistency(
        merged_brief={
            "items": [{"id": "bad", "text": "...", "kind": "assumption"}],
            "goal_terms": {},
            "open_questions": [],
        },
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={"items": [{"id": "bad", "text": "...", "kind": "assumption"}]},
        visible_reply="Sure, noted.",
        workflow_mode="waterfall",
    )
    assert any(i.category == "workflow_invariant_violation" for i in issues)


def test_panel_algorithm_mismatch():
    issues = verify_panel_consistency(
        brief={
            "goal_terms": {
                "search_strategy": {"properties": {"algorithm": "GA"}},
                "travel_time": {"weight": 100, "type": "objective"},
            }
        },
        panel={
            "problem": {
                "algorithm": "PSO",
                "goal_terms": {"travel_time": {"weight": 100, "type": "objective"}},
            }
        },
        workflow_mode="agile",
    )
    assert any(i.category == "brief_panel_algorithm_mismatch" for i in issues)


def test_panel_key_missing_in_brief():
    issues = verify_panel_consistency(
        brief={"goal_terms": {}},
        panel={"problem": {"goal_terms": {"phantom_key": {"weight": 1, "type": "soft"}}}},
        workflow_mode="agile",
    )
    cats = [i.category for i in issues]
    assert "brief_panel_mismatch" in cats


def test_categorize_panel_issues():
    from app.schemas import PipelineIssue

    bucketed = categorize_panel_issues(
        [
            PipelineIssue(category="brief_panel_mismatch", subject="goal_terms.foo", message="x"),
            PipelineIssue(category="brief_panel_algorithm_mismatch", subject="algorithm", message="y"),
            PipelineIssue(category="port_companion", subject="panel.driver_preferences", message="z"),
        ]
    )
    assert len(bucketed["goal_terms"]) == 2
    assert len(bucketed["algorithm"]) == 1
    assert len(bucketed["other"]) == 0


def test_issues_to_audit_payload_roundtrip():
    from app.schemas import PipelineIssue

    payload = issues_to_audit_payload(
        [PipelineIssue(category="claim_without_delta", message="m", subject="s")]
    )
    assert payload == [
        {"category": "claim_without_delta", "severity": "error", "subject": "s", "message": "m"}
    ]


def test_agile_runack_with_assumption_ok():
    """Agile run-ack with a fresh assumption row passes the invariant."""
    issues = verify_brief_consistency(
        merged_brief={
            "items": [
                {"id": "i1", "text": "foo", "kind": "gathered"},
                {"id": "i2-new", "text": "Try adjusting X", "kind": "assumption"},
            ],
            "goal_terms": {},
            "open_questions": [],
        },
        base_brief={
            "items": [{"id": "i1", "text": "foo", "kind": "gathered"}],
            "goal_terms": {},
            "open_questions": [],
        },
        patch={"items": [{"id": "i2-new", "text": "Try adjusting X", "kind": "assumption"}]},
        visible_reply="Run #1 done. Suggest trying X next.",
        workflow_mode="agile",
        is_run_acknowledgement=True,
    )
    # Should NOT have the runack invariant violation since a new assumption was added.
    cats = [i.category for i in issues]
    assert "runack_invariant_violation" not in cats, cats


def test_waterfall_runack_with_oq_ok():
    """Waterfall run-ack with a fresh OQ passes the invariant."""
    issues = verify_brief_consistency(
        merged_brief={
            "items": [{"id": "i1", "text": "foo", "kind": "gathered"}],
            "goal_terms": {},
            "open_questions": [{"id": "oq-new", "text": "What should we try next?"}],
        },
        base_brief={
            "items": [{"id": "i1", "text": "foo", "kind": "gathered"}],
            "goal_terms": {},
            "open_questions": [],
        },
        patch={"open_questions": [{"id": "oq-new", "text": "What should we try next?"}]},
        visible_reply="Run #1 done. Asking what you'd like to try next.",
        workflow_mode="waterfall",
        is_run_acknowledgement=True,
    )
    cats = [i.category for i in issues]
    assert "runack_invariant_violation" not in cats, cats


def test_vrptw_port_companion_routed():
    issues = verify_brief_consistency(
        merged_brief={
            "items": [],
            "goal_terms": {
                "worker_preference": {
                    "weight": 50,
                    "type": "soft",
                    "properties": {"driver_preferences": []},
                }
            },
            "open_questions": [],
        },
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={"goal_terms": {"worker_preference": {"weight": 50, "type": "soft"}}},
        visible_reply="Added worker preference handling.",
        workflow_mode="agile",
        test_problem_id="vrptw",
    )
    # Should include the VRPTW port_companion issue about empty driver_preferences.
    assert any(
        i.category == "port_companion" and "driver_preferences" in i.subject for i in issues
    )
