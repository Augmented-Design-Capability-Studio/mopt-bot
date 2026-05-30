"""Smoke tests for pipeline verification module."""

import pytest

from app.services.pipeline_verification import (
    categorize_panel_issues,
    issues_to_audit_payload,
    verify_brief_consistency,
    verify_panel_consistency,
)


def test_strip_owned_fields_from_config_save_patch_drops_goal_terms():
    """Real user-reported case: rerank → ``handleReorder`` rewrites soft/
    objective weights to suggested values for the new ranks. Panel save
    mirrors those into the brief. Then the LLM's config_edit_ack patch
    re-emits ``goal_terms`` with the PRE-rerank values it had in context,
    causing S5 brief↔panel drift + a "(retried)" noisy status. The strip
    helper drops ``goal_terms`` from the patch so the panel-synced
    values stick."""
    from app.services.chat_pipeline_runner import _strip_owned_fields_from_config_save_patch

    patch = {
        "goal_terms": {
            "capacity_penalty": {"weight": 2.59, "type": "soft", "rank": 3},
            "lateness_penalty": {"weight": 3.89, "type": "soft", "rank": 2},
        },
        "items": [{"id": "ack", "text": "Reordered priorities.", "kind": "gathered", "source": "agent"}],
        "goal_summary": "Refined goal.",
    }
    out = _strip_owned_fields_from_config_save_patch(patch, is_config_save=True)
    assert "goal_terms" not in out, "Config-save patch must drop goal_terms"
    # Other fields are untouched — the LLM is still allowed to record the
    # user's edit as a gathered row or refine the goal summary.
    assert out["items"][0]["id"] == "ack"
    assert out["goal_summary"] == "Refined goal."


def test_strip_owned_fields_passes_through_when_not_config_save():
    """Inverse: on non-config-save turns (chat / run_ack / brief_edit_ack
    / etc.), the LLM is still the canonical writer of ``goal_terms``.
    The helper is a no-op."""
    from app.services.chat_pipeline_runner import _strip_owned_fields_from_config_save_patch

    patch = {
        "goal_terms": {"travel_time": {"weight": 5.0, "type": "objective", "rank": 1}},
    }
    out = _strip_owned_fields_from_config_save_patch(patch, is_config_save=False)
    assert "goal_terms" in out
    assert out["goal_terms"]["travel_time"]["weight"] == 5.0


def test_claim_without_delta():
    """LLM populates ``change_clause`` (its structured commit-tag) but the
    patch is empty → ``claim_without_delta`` fires. Previously this was
    detected by keyword-matching ``visible_reply`` (brittle); now we trust
    the LLM's own structured signal."""
    issues = verify_brief_consistency(
        merged_brief={"items": [], "goal_terms": {}, "open_questions": []},
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={},
        visible_reply="I've added a lateness penalty as soft.",
        workflow_mode="agile",
        change_clause="I've added a lateness penalty as soft.",
    )
    assert any(i.category == "claim_without_delta" for i in issues)


def test_claim_without_delta_silent_when_no_change_clause():
    """Inverse: empty ``change_clause`` (and empty patch) → no fire.
    Locks the structural read: we only flag when the LLM itself tagged the
    reply as committing a change. Keyword-matching the prose used to false-
    positive on questions like *"Would you like X? I've added similar
    before…"* — gone now."""
    issues = verify_brief_consistency(
        merged_brief={"items": [], "goal_terms": {}, "open_questions": []},
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={},
        visible_reply="Would you like me to add a lateness penalty? I've added similar before.",
        workflow_mode="agile",
        change_clause=None,
    )
    assert not any(i.category == "claim_without_delta" for i in issues)


def test_apply_stage_answered_oq_turn_does_not_nameerror(monkeypatch):
    """Regression: ``_apply_stage`` referenced ``is_answered_open_question``
    without receiving it as a parameter, so EVERY applied turn raised
    ``NameError`` at the answer-save OQ-action guard. The offline suite
    missed it because the default Gemini stub pauses the pipeline at S1
    (drafting) before apply ever runs.

    Drive the apply path directly with an answer-save turn carrying a
    ``drop`` OQ action (the guard's trigger). The session id is
    intentionally absent, so apply runs through the guard and returns
    ``None`` at the missing-row check.

    ``_apply_stage`` swallows exceptions into a ``paused`` status, so a
    bare ``assert result is None`` would pass even with the bug. We instead
    record the status calls and assert NO ``paused`` (crash) state — pre-fix
    the NameError surfaces as ``paused`` + "Couldn't apply the patch …"."""
    from app.schemas import ChatTurnResponse, OQMaintenanceItem
    from app.services import pipeline_status
    from app.services.chat_pipeline_runner import _apply_stage

    calls: list[dict] = []
    monkeypatch.setattr(pipeline_status, "update_stage", lambda **k: calls.append(k))
    monkeypatch.setattr(pipeline_status, "fail_pipeline", lambda **k: calls.append({"fail_pipeline": True, **k}))

    turn = ChatTurnResponse(
        assistant_message="Here's why time windows matter…",
        problem_brief_patch=None,
        oq_actions=[OQMaintenanceItem(id="q1", action="drop")],
    )
    result = _apply_stage(
        message_id=0,
        turn=turn,
        session_id="missing-session-regression",
        revision=0,
        base_problem_brief={"items": [], "goal_terms": {}, "open_questions": []},
        base_panel=None,
        workflow_mode="waterfall",
        history_lines=[],
        api_key="",
        model_name="",
        researcher_steers=None,
        recent_runs_summary=None,
        is_run_acknowledgement=False,
        is_config_save=False,
        user_text="why do time windows matter?",
        test_problem_id="vrptw",
        is_answered_open_question=True,
    )
    # Missing session row → graceful None, reached WITHOUT crashing en route.
    assert result is None
    paused = [c for c in calls if c.get("state") == "paused"]
    assert not paused, f"_apply_stage crashed on an answer-save turn: {paused}"


def test_classify_user_search_strategy_choice_fail_safe():
    """Missing key or empty message → None (never blocks the turn)."""
    from app.services.llm import classify_user_search_strategy_choice

    assert classify_user_search_strategy_choice(
        user_text="ant colony", api_key=None, model_name=None
    ) is None
    assert classify_user_search_strategy_choice(
        user_text="   ", api_key="k", model_name="m"
    ) is None


def test_has_open_search_strategy_oq():
    """The gate's classifier only fires while the search-strategy OQ is open."""
    from app.services.chat_pipeline_runner import _has_open_search_strategy_oq

    open_oq = {"open_questions": [{"id": "oq-monitor-algorithm", "topic": "search_strategy", "status": "open"}]}
    answered = {"open_questions": [{"id": "oq-monitor-algorithm", "topic": "search_strategy", "status": "answered"}]}
    assert _has_open_search_strategy_oq(open_oq) is True
    assert _has_open_search_strategy_oq(answered) is False
    assert _has_open_search_strategy_oq({"open_questions": []}) is False


def test_compute_material_brief_changes_detects_add_retune_remove_algo():
    """The deterministic diff names solver-affecting changes in plain language
    (the input the LLM acknowledgement check judges against)."""
    from app.services.pipeline_verification import compute_material_brief_changes

    base = {
        "items": [],
        "goal_terms": {
            "capacity_penalty": {"weight": 10.0, "type": "soft", "rank": 1},
            "workload_balance": {"weight": 2.0, "type": "soft", "rank": 2},
        },
    }
    merged = {
        "items": [{"id": "ev1", "text": "minimize travel", "kind": "gathered", "source": "user"}],
        "goal_terms": {
            "capacity_penalty": {"weight": 30.0, "type": "soft", "rank": 1},  # retune
            # added (anchored via ev1):
            "travel_time": {"weight": 1.0, "type": "objective", "rank": 3, "evidence_item_ids": ["ev1"]},
            "search_strategy": {"properties": {"algorithm": "GA"}},  # algorithm set
            # workload_balance removed
        },
    }
    changes = compute_material_brief_changes(base, merged, "agile", "vrptw")
    assert any("added" in c.lower() for c in changes)
    assert any("10" in c and "30" in c for c in changes)
    assert any("removed" in c.lower() for c in changes)
    assert any("search method" in c.lower() and "ga" in c.lower() for c in changes)
    # search_strategy is reported via the algorithm line, never as "Added 'Search strategy'".
    assert not any("search strategy" in c.lower() and "added" in c.lower() for c in changes)


def test_compute_material_brief_changes_skips_unanchored_new_key():
    """A new goal term with no evidence anchor is about to be dropped by the
    apply layer, so it must NOT show up as a phantom change."""
    from app.services.pipeline_verification import compute_material_brief_changes

    base = {"items": [], "goal_terms": {}}
    merged = {"items": [], "goal_terms": {"travel_time": {"weight": 1.0, "type": "objective"}}}
    assert compute_material_brief_changes(base, merged, "agile", "vrptw") == []


def test_check_changes_acknowledged_fail_safe():
    """Missing key or empty change list → None (never blocks the turn)."""
    from app.services.llm import check_changes_acknowledged

    assert check_changes_acknowledged(
        visible_reply="hi", changes=["Added X."], api_key=None, model_name=None
    ) is None
    assert check_changes_acknowledged(
        visible_reply="hi", changes=[], api_key="k", model_name="m"
    ) is None


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


def test_tutorial_runack_suppression_waterfall():
    """Tutorial Runs 1+2 in waterfall: caller sets ``suppress_runack_invariant``
    so the 'must add new OQ on a run-ack' rule doesn't fire."""
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
        visible_reply="Run #1 packed over capacity as expected.",
        workflow_mode="waterfall",
        is_run_acknowledgement=True,
        suppress_runack_invariant=True,
    )
    assert not any(i.category == "runack_invariant_violation" for i in issues)


def test_tutorial_runack_suppression_agile():
    """Tutorial suppression is symmetric: agile's 'must add new assumption'
    invariant is skipped too."""
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
        visible_reply="Run #1 packed over capacity as expected.",
        workflow_mode="agile",
        is_run_acknowledgement=True,
        suppress_runack_invariant=True,
    )
    assert not any(i.category == "runack_invariant_violation" for i in issues)


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


def test_vrptw_port_companion_severity_is_error_on_bare_empty():
    """PILOT_5 reproducer: LLM commits worker_preference with empty rules and
    no prose row. Used to be `warn` (verifier passed, broken brief shipped).
    Now an `error` so the retry loop forces the LLM to take one of the three
    documented exits."""
    issues = verify_brief_consistency(
        merged_brief={
            "items": [],
            "goal_terms": {
                "worker_preference": {
                    "weight": 1.0,
                    "type": "soft",
                    "properties": {"driver_preferences": []},
                }
            },
            "open_questions": [],
        },
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={"goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft"}}},
        visible_reply="I've added worker preferences.",
        workflow_mode="agile",
        test_problem_id="vrptw",
    )
    matching = [
        i for i in issues
        if i.category == "port_companion" and "driver_preferences" in i.subject
    ]
    assert matching, "Bare-empty worker_preference must surface a port_companion issue"
    assert all(i.severity == "error" for i in matching), (
        f"Bare-empty case must be error, got {[i.severity for i in matching]}"
    )


def test_reconcile_companion_oqs_adds_oq_for_orphan_goal_term():
    """When a goal_term has its port-required companion empty (user cleared
    rules via panel, or LLM committed empty), auto-park an OQ asking about
    it. The OQ silences the ``port_companion`` verifier and surfaces the
    question to the participant + LLM. Generic — works for any port
    declaring ``gate_conditional_companions``."""
    from app.problem_brief import reconcile_companion_oqs

    brief = {
        "goal_summary": "",
        "items": [],
        "open_questions": [],
        "goal_terms": {
            "worker_preference": {"weight": 1.0, "type": "soft", "rank": 1, "properties": {"driver_preferences": []}},
        },
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }
    out = reconcile_companion_oqs(brief, "vrptw")
    auto_oqs = [
        q for q in out["open_questions"]
        if isinstance(q, dict) and str(q.get("id") or "").startswith("auto-oq-companion-")
    ]
    assert len(auto_oqs) == 1
    assert auto_oqs[0]["goal_key"] == "worker_preference"
    assert auto_oqs[0]["status"] == "open"


def test_reconcile_companion_oqs_drops_oq_when_companion_populated():
    """Inverse: once the companion is populated (user added a rule), the
    auto-OQ drops on the next reconcile pass — idempotent state-machine."""
    from app.problem_brief import reconcile_companion_oqs

    brief = {
        "goal_summary": "",
        "items": [],
        "open_questions": [
            {
                "id": "auto-oq-companion-worker_preference",
                "text": "Configure rules?",
                "status": "open",
                "answer_text": None,
                "topic": "other",
                "goal_key": "worker_preference",
            }
        ],
        "goal_terms": {
            "worker_preference": {
                "weight": 1.0, "type": "soft", "rank": 1,
                "properties": {"driver_preferences": [{"vehicle_idx": 0, "condition": "avoid_zone", "zone": 1, "penalty": 50}]},
            },
        },
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }
    out = reconcile_companion_oqs(brief, "vrptw")
    auto_oqs = [
        q for q in out["open_questions"]
        if isinstance(q, dict) and str(q.get("id") or "").startswith("auto-oq-companion-")
    ]
    assert auto_oqs == []


def test_reconcile_companion_oqs_does_not_double_up_with_existing_oq():
    """If an LLM-emitted OQ with matching ``goal_key`` already covers the
    question, the auto-monitor doesn't add a second one — it defers to
    whichever question is already in play."""
    from app.problem_brief import reconcile_companion_oqs

    brief = {
        "goal_summary": "",
        "items": [],
        "open_questions": [
            {
                "id": "llm-emitted-oq",
                "text": "Which drivers and what conditions?",
                "status": "open",
                "answer_text": None,
                "topic": "other",
                "goal_key": "worker_preference",
            }
        ],
        "goal_terms": {
            "worker_preference": {"weight": 1.0, "type": "soft", "rank": 1, "properties": {"driver_preferences": []}},
        },
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }
    out = reconcile_companion_oqs(brief, "vrptw")
    auto_oqs = [
        q for q in out["open_questions"]
        if isinstance(q, dict) and str(q.get("id") or "").startswith("auto-oq-companion-")
    ]
    assert auto_oqs == [], "Auto-OQ must not double up with an existing LLM-emitted OQ on the same goal_key"


def test_reconcile_companion_oqs_drops_oq_when_goal_term_removed():
    """Stale auto-OQ cleanup: if the goal_term is no longer in the brief
    (LLM dropped it, user removed it), the auto-OQ also drops."""
    from app.problem_brief import reconcile_companion_oqs

    brief = {
        "goal_summary": "",
        "items": [],
        "open_questions": [
            {
                "id": "auto-oq-companion-worker_preference",
                "text": "Configure rules?",
                "status": "open",
                "answer_text": None,
                "topic": "other",
                "goal_key": "worker_preference",
            }
        ],
        "goal_terms": {
            "travel_time": {"weight": 1.0, "type": "objective", "rank": 1},
            # worker_preference no longer here
        },
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }
    out = reconcile_companion_oqs(brief, "vrptw")
    auto_oqs = [
        q for q in out["open_questions"]
        if isinstance(q, dict) and str(q.get("id") or "").startswith("auto-oq-companion-")
    ]
    assert auto_oqs == []


def test_reconcile_defers_new_underspecified_term_but_keeps_preexisting():
    """A companion-having goal term the agent introduces THIS turn without its
    specifics is deferred — dropped, with an OQ asking for the specifics (so the
    participant never sees a hollow term). A PRE-EXISTING term whose companion
    is empty is kept (non-destructive placeholder) and only gets the OQ. The OQ
    text is participant-friendly (no raw schema keys)."""
    from app.problem_brief import reconcile_companion_oqs

    def _brief():
        return {
            "goal_summary": "",
            "items": [],
            "open_questions": [],
            "goal_terms": {
                "worker_preference": {
                    "weight": 1.0, "type": "soft", "rank": 1,
                    "properties": {"driver_preferences": []},
                },
            },
            "solver_scope": "general_metaheuristic_translation",
            "backend_template": "routing_time_windows",
        }

    # New this turn (key absent from base) → dropped + OQ.
    out_new = reconcile_companion_oqs(_brief(), "vrptw", base_brief={"goal_terms": {}})
    assert "worker_preference" not in out_new["goal_terms"], "hollow new term must be deferred"
    auto = [q for q in out_new["open_questions"] if str(q.get("id") or "").startswith("auto-oq-companion-")]
    assert len(auto) == 1 and auto[0]["goal_key"] == "worker_preference"
    assert "`" not in auto[0]["text"] and "driver_preferences" not in auto[0]["text"], (
        "participant-facing OQ must not leak raw schema keys"
    )

    # Pre-existing (key in base) → kept + OQ (non-destructive).
    out_old = reconcile_companion_oqs(
        _brief(), "vrptw",
        base_brief={"goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft"}}},
    )
    assert "worker_preference" in out_old["goal_terms"], "pre-existing term must be kept"
    auto2 = [q for q in out_old["open_questions"] if str(q.get("id") or "").startswith("auto-oq-companion-")]
    assert len(auto2) == 1


def test_unanchored_goal_term_silenced_by_pending_oq():
    """Real user-reported case: LLM commits ``worker_preference`` with empty
    rules AND emits a clarifying question. Three checks used to fire in
    conflict — ``ask_without_oq``, ``port_companion``, and
    ``unanchored_goal_term``. Adding an OQ satisfied the first two via the
    Fix 5 "OQ exit", but ``unanchored_goal_term`` still fired because it
    didn't recognize the OQ as a valid anchor. Now the verifier treats a
    pending OQ with matching ``goal_key`` as "deferred to OQ" and skips
    the unanchored fire — symmetric with the apply-time
    ``filter_unanchored_new_goal_terms`` drop that parks the premature
    commit so only the OQ stands."""
    issues = verify_brief_consistency(
        merged_brief={
            "items": [],
            "goal_terms": {
                "worker_preference": {
                    "weight": 1.0,
                    "type": "soft",
                    "properties": {"driver_preferences": []},
                }
            },
            "open_questions": [
                {
                    "id": "oq-driver-pref-rules",
                    "text": "Which drivers / conditions / penalties?",
                    "topic": "other",
                    "goal_key": "worker_preference",
                    "status": "open",
                }
            ],
        },
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={"goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft"}}},
        visible_reply="Which drivers / conditions / penalties?",
        workflow_mode="agile",
        test_problem_id="vrptw",
        question_clause="Which drivers / conditions / penalties?",
    )
    assert not any(i.category == "unanchored_goal_term" for i in issues), (
        "Pending OQ with goal_key=K must silence unanchored_goal_term for K."
    )
    # The other two checks (ask_without_oq, port_companion) should also be
    # silent in this state — verified separately by their own dedicated tests.


def test_premature_goal_term_commit_dropped_by_anchor_filter():
    """At apply time, when a NEW goal_term lands with empty companion AND
    an OQ with matching ``goal_key`` exists, ``filter_unanchored_new_goal_terms``
    drops the commit. The OQ stands alone — when the user answers with
    rules, the LLM re-commits the goal_term cleanly with populated
    ``properties.driver_preferences``."""
    from app.services.goal_term_anchoring import filter_unanchored_new_goal_terms

    filtered, dropped = filter_unanchored_new_goal_terms(
        base_brief={"goal_terms": {}},
        proposed_goal_terms={
            "worker_preference": {
                "weight": 1.0,
                "type": "soft",
                "properties": {"driver_preferences": []},
            }
        },
        items=[],
        workflow_mode="agile",
        test_problem_id="vrptw",
        pending_oq_keys={"worker_preference"},
    )
    assert "worker_preference" not in filtered
    assert "worker_preference" in dropped


def test_filter_does_not_drop_goal_term_with_populated_rules_even_with_pending_oq():
    """Inverse: if the LLM legitimately populates the companion rules AND
    has an OQ for the same key (e.g. asking a follow-up question), the
    goal_term is properly anchored and stays. The premature-drop rule only
    triggers on UNanchored commits, not anchored ones."""
    from app.services.goal_term_anchoring import filter_unanchored_new_goal_terms

    filtered, dropped = filter_unanchored_new_goal_terms(
        base_brief={"goal_terms": {}},
        proposed_goal_terms={
            "worker_preference": {
                "weight": 1.0,
                "type": "soft",
                "properties": {
                    "driver_preferences": [
                        {"vehicle_idx": 0, "condition": "avoid_zone", "zone": 1, "penalty": 50}
                    ],
                },
            }
        },
        items=[],
        workflow_mode="agile",
        test_problem_id="vrptw",
        pending_oq_keys={"worker_preference"},
    )
    assert "worker_preference" in filtered
    assert "worker_preference" not in dropped


def test_vrptw_port_companion_silenced_by_pending_oq():
    """Third exit (option c in the message): if the LLM has parked the
    question via an open_questions row that anchors back to
    worker_preference, the verifier doesn't double-fire — we're waiting on
    the participant, not the model."""
    issues = verify_brief_consistency(
        merged_brief={
            "items": [],
            "goal_terms": {
                "worker_preference": {
                    "weight": 1.0,
                    "type": "soft",
                    "properties": {"driver_preferences": []},
                }
            },
            "open_questions": [
                {
                    "id": "oq-driver-pref-rules",
                    "text": "Which drivers / conditions / penalty values would you like?",
                    "topic": "other",
                    "goal_key": "worker_preference",
                    "status": "open",
                }
            ],
        },
        base_brief={"items": [], "goal_terms": {}, "open_questions": []},
        patch={"goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft"}}},
        visible_reply="I'll set up worker preferences once you tell me the rules.",
        workflow_mode="agile",
        test_problem_id="vrptw",
    )
    assert not any(
        i.category == "port_companion" and "driver_preferences" in i.subject
        for i in issues
    ), "Pending OQ on worker_preference should silence the bare-empty companion fire"
