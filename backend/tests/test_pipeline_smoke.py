"""Smoke tests for pipeline verification module."""

import pytest

from app.services.pipeline_verification import (
    categorize_panel_issues,
    issues_to_audit_payload,
    verify_brief_consistency,
    verify_panel_consistency,
)


def test_agile_assumption_anchor_provenance_survives_to_synthesized_row():
    """P_0603: in agile the agent committed `capacity_penalty` post-run with an
    `item-…-update` evidence anchor of `kind: assumption` (correct agile
    provenance). But the apply layer DROPS that anchor before the synthesizer
    runs, and the synthesizer only read `goal_key`/`config-weight-*` rows — so the
    canonical row silently defaulted to `gathered`, erasing every agile
    assumption. The drop now carries the anchor's provenance forward."""
    from app.routers.sessions.derivation import (
        _drop_redundant_goal_term_anchors,
        _synthesize_canonical_weight_items,
    )

    merged = {
        "goal_terms": {"capacity_penalty": {"weight": 30.0, "type": "hard", "rank": 4,
            "evidence_item_ids": ["item-capacity-penalty-update"]}},
        "items": [{"id": "item-capacity-penalty-update", "text": "Capacity penalty → 30",
                   "kind": "assumption", "source": "agent"}],
        "open_questions": [],
    }
    out, prov = _drop_redundant_goal_term_anchors(
        base_brief={"goal_terms": {}, "items": []}, merged=merged)
    # Anchor dropped (no duplicate row), provenance captured.
    assert "item-capacity-penalty-update" not in {it["id"] for it in out["items"]}
    assert prov == {"capacity_penalty": ("assumption", "agent")}

    synth = _synthesize_canonical_weight_items(out, "vrptw", provenance_hints=prov)
    row = [it for it in synth["items"] if it["id"] == "config-weight-capacity_penalty"][0]
    assert (row["kind"], row["source"]) == ("assumption", "agent"), row

    # Strongest-wins: an assumption hint must NOT demote a user-confirmed fact.
    base2 = {"goal_terms": {}, "items": []}
    merged2 = {
        "goal_terms": {"travel_time": {"weight": 1.0, "type": "objective",
            "evidence_item_ids": ["item-tt"]}},
        "items": [{"id": "item-tt", "text": "minimize travel", "kind": "assumption", "source": "agent"},
                  {"id": "config-weight-travel_time", "goal_key": "travel_time",
                   "kind": "gathered", "source": "user", "text": "prior user-confirmed"}],
        "open_questions": [],
    }
    out2, prov2 = _drop_redundant_goal_term_anchors(base_brief=base2, merged=merged2)
    synth2 = _synthesize_canonical_weight_items(out2, "vrptw", provenance_hints=prov2)
    row2 = [it for it in synth2["items"] if it["id"] == "config-weight-travel_time"][0]
    assert (row2["kind"], row2["source"]) == ("gathered", "user"), row2


def test_synthesized_goal_term_justification_uses_port_phrase_not_agent_narration():
    """The participant-facing goal-term row must read as a brief 'why this term
    exists' justification (the port's clean phrase), never the agent's
    `ambiguity_note` — which narrates HOW it reasoned ("I read 'minimize travel
    time' as …") and leaks raw schema keys (`travel_time`, `waiting_time`)."""
    from app.problem_brief import synthesize_canonical_goal_term_items

    brief = {
        "goal_terms": {
            "travel_time": {
                "weight": 1.0, "type": "objective", "rank": 1,
                "ambiguity_note": {"chosen_rationale":
                    "I read 'minimize travel time' as shorter routes (travel_time) "
                    "rather than idle time (waiting_time)."},
            },
        },
        "items": [], "open_questions": [],
    }
    row = [r["text"] for r in synthesize_canonical_goal_term_items(brief, "vrptw")
           if r["id"] == "config-weight-travel_time"][0]
    assert "to minimize total driving minutes across all routes" in row
    assert "I read" not in row, "must not render the agent's narration"
    assert "travel_time" not in row and "waiting_time" not in row, "must not leak raw keys"


def test_patch_structures_companion_rule_typed_into_def_row(monkeypatch):
    """P_0603: the participant types a rule after "Rules —" in the def panel's
    (server-synthesized) worker-preference row. The PATCH handler detects the
    edited row (text differs from what the carrier would synthesize) and runs the
    structured extractor to populate the carrier — deterministic, at the save,
    independent of the follow-up chat turn. The stale ``ambiguity_note`` is
    dropped. The live model is covered by the `live_gemini` suite."""
    from app.routers.sessions.router import _structure_companion_rule_edits
    from app.problem_brief import synthesize_canonical_goal_term_items
    from app.services import llm

    alice = {"vehicle_idx": 0, "condition": "avoid_zone", "penalty": 50.0, "zone": 4}
    carol = {"vehicle_idx": 2, "condition": "order_priority", "penalty": 50.0, "order_priority": "express"}
    base_carrier = {
        "goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft", "rank": 1,
            "ambiguity_note": {"chosen_rationale": "Mapped the zone preference to the worker_preference module."},
            "properties": {"driver_preferences": [alice]}}},
        "items": [], "open_questions": [],
    }
    synth_text = [r["text"] for r in synthesize_canonical_goal_term_items(base_carrier, "vrptw")
                  if r["id"] == "config-weight-worker_preference"][0]

    monkeypatch.setattr(llm, "extract_companion_rules", lambda **kw: [alice, carol])

    # Edited row (participant appended a rule) → carrier populated, note cleared.
    edited = dict(base_carrier)
    edited["items"] = [{"id": "config-weight-worker_preference", "goal_key": "worker_preference",
                        "kind": "gathered", "source": "user",
                        "text": synth_text + " and carol skips express orders"}]
    out = _structure_companion_rule_edits(
        incoming_brief=edited, test_problem_id="vrptw", api_key="k", model_name="m")
    wp = out["goal_terms"]["worker_preference"]
    assert wp["properties"]["driver_preferences"] == [alice, carol]
    assert "ambiguity_note" not in wp, "stale narration dropped on structuring"

    # Unedited row (text == synthesized baseline) → gate skips, no change.
    calls = {"n": 0}
    monkeypatch.setattr(llm, "extract_companion_rules", lambda **kw: (calls.__setitem__("n", calls["n"] + 1), [alice, carol])[1])
    unedited = {
        "goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft", "rank": 1,
            "properties": {"driver_preferences": [alice]}}},
        "items": [{"id": "config-weight-worker_preference", "goal_key": "worker_preference",
                   "kind": "gathered", "source": "user",
                   "text": [r["text"] for r in synthesize_canonical_goal_term_items(
                       {"goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft", "rank": 1,
                        "properties": {"driver_preferences": [alice]}}}}, "vrptw")
                       if r["id"] == "config-weight-worker_preference"][0]}],
        "open_questions": [],
    }
    out2 = _structure_companion_rule_edits(
        incoming_brief=unedited, test_problem_id="vrptw", api_key="k", model_name="m")
    assert out2["goal_terms"]["worker_preference"]["properties"]["driver_preferences"] == [alice]
    assert calls["n"] == 0, "unedited row must not call the extractor"


def test_apply_stage_threads_is_brief_edit_ack_param():
    """Regression: the companion extractor needs ``is_brief_edit_ack`` in the
    apply stage, but ``_apply_stage`` passed it through before declaring it as a
    parameter — a NameError that crashed the FIRST turn live (the offline suite
    stubs the LLM and never drove the kwarg). Assert the param exists on both the
    runner stage and the apply helper so the wiring can't silently break again."""
    import inspect
    from app.services.chat_pipeline_runner import _apply_stage
    from app.routers.sessions.derivation import apply_brief_patch_with_cleanup

    assert "is_brief_edit_ack" in inspect.signature(_apply_stage).parameters
    assert "is_brief_edit_ack" in inspect.signature(apply_brief_patch_with_cleanup).parameters
    assert "change_clause" in inspect.signature(apply_brief_patch_with_cleanup).parameters


def test_companion_rule_extraction_fallback_populates_hollow_append(monkeypatch):
    """P_0603: the agent committed `worker_preference` and claimed "added Dave"
    but emitted no `driver_preferences` (array unchanged from base). The
    deterministic extractor fallback fires (term in patch + claim + array
    unchanged) and populates the carrier. The LLM extraction itself is stubbed
    here — the live model is covered by the `live_gemini` suite."""
    from app.routers.sessions.derivation import _extract_missing_companion_rules
    from app.services import llm

    alice = [{"vehicle_idx": 0, "condition": "avoid_zone", "penalty": 50.0, "zone": 4}]
    dave = {"vehicle_idx": 3, "condition": "shift_over_limit", "penalty": 50.0, "limit_minutes": 390.0}
    base = {"items": [], "goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft",
            "properties": {"driver_preferences": list(alice)}}}}
    merged = {  # agent re-sent the term hollow — array still just Alice
        "items": [], "goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft",
            "properties": {"driver_preferences": list(alice)}}}}
    patch = {"goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft"}}}

    captured = {}
    def _fake_extract(**kw):
        captured.update(kw)
        return alice + [dave]
    monkeypatch.setattr(llm, "extract_companion_rules", _fake_extract)

    out = _extract_missing_companion_rules(
        merged=merged, base_brief=base, patch_payload=patch, test_problem_id="vrptw",
        user_text="Also dave doesn't like working past 6.5h shift?",
        change_clause="I've added the shift-duration preference for Dave.",
        is_brief_edit_ack=False, api_key="k", model_name="m",
    )
    rules = out["goal_terms"]["worker_preference"]["properties"]["driver_preferences"]
    assert rules == alice + [dave], "extractor result must populate the carrier"
    assert "Also dave" in captured["source_text"], "participant wording must be the extraction source"
    assert "ambiguity_note" not in out["goal_terms"]["worker_preference"], "stale narration dropped"

    # Definition-panel path: no chat claim, but a def edit — the user typed Dave
    # into the companion row's prose (lives in BASE; the agent overwrote it in
    # merged). Trigger fires off is_brief_edit_ack and reads the base prose.
    base_def = {
        "items": [{"id": "config-weight-worker_preference", "goal_key": "worker_preference",
                   "kind": "gathered", "source": "user",
                   "text": "Worker preferences — Rules — Alice avoids Zone D. and dave avoids shifts over 6.5h"}],
        "goal_terms": {"worker_preference": {"properties": {"driver_preferences": list(alice)}}},
    }
    merged_def = {  # agent overwrote the row back to Alice-only, hollow goal term
        "items": [{"id": "config-weight-worker_preference", "goal_key": "worker_preference",
                   "kind": "gathered", "source": "agent", "text": "Worker preferences — Rules — Alice avoids Zone D."}],
        "goal_terms": {"worker_preference": {"properties": {"driver_preferences": list(alice)}}},
    }
    cap2 = {}
    def _fake2(**kw):
        cap2.update(kw); return alice + [dave]
    monkeypatch.setattr(llm, "extract_companion_rules", _fake2)
    out_def = _extract_missing_companion_rules(
        merged=merged_def, base_brief=base_def, patch_payload={}, test_problem_id="vrptw",
        user_text="Definition edited: 1 fact edited.", change_clause=None,
        is_brief_edit_ack=True, api_key="k", model_name="m",
    )
    assert out_def["goal_terms"]["worker_preference"]["properties"]["driver_preferences"] == alice + [dave]
    assert "dave avoids shifts" in cap2["source_text"], "def-edit prose (from base) must reach the extractor"

    # No trigger when nothing claimed AND not a def edit.
    monkeypatch.setattr(llm, "extract_companion_rules", lambda **kw: alice + [dave])
    out2 = _extract_missing_companion_rules(
        merged={"items": [], "goal_terms": {"worker_preference": {"properties": {"driver_preferences": list(alice)}}}},
        base_brief=base, patch_payload=patch, test_problem_id="vrptw",
        user_text="x", change_clause=None, is_brief_edit_ack=False, api_key="k", model_name="m",
    )
    assert out2["goal_terms"]["worker_preference"]["properties"]["driver_preferences"] == alice

    # No trigger when the agent already changed the array (don't override it).
    out3 = _extract_missing_companion_rules(
        merged={"items": [], "goal_terms": {"worker_preference": {"properties": {"driver_preferences": alice + [dave]}}}},
        base_brief=base, patch_payload=patch, test_problem_id="vrptw",
        user_text="x", change_clause="added dave", is_brief_edit_ack=False, api_key="k", model_name="m",
    )
    assert out3["goal_terms"]["worker_preference"]["properties"]["driver_preferences"] == alice + [dave]


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


def test_agile_runack_satisfied_by_updated_assumption():
    """Re-tuning an EXISTING assumption (same id, new weight/text) on a run-ack
    turn satisfies the agile invariant — it need not be a brand-new row."""
    issues = verify_brief_consistency(
        merged_brief={
            "items": [
                {
                    "id": "a1",
                    "text": "Lateness penalty (weight 5)",
                    "kind": "assumption",
                    "source": "agent",
                },
            ],
            "goal_terms": {},
            "open_questions": [],
        },
        base_brief={
            "items": [
                {
                    "id": "a1",
                    "text": "Lateness penalty (weight 2)",
                    "kind": "assumption",
                    "source": "agent",
                },
            ],
            "goal_terms": {},
            "open_questions": [],
        },
        patch={},
        visible_reply="Run #2 still had late arrivals, so I bumped the lateness penalty to 5.",
        workflow_mode="agile",
        is_run_acknowledgement=True,
    )
    assert not any(i.category == "runack_invariant_violation" for i in issues)


def test_agile_runack_unchanged_assumption_does_not_satisfy():
    """An unchanged carry-over assumption (same id, identical content) does NOT
    satisfy the invariant — the turn must reflect something the run revealed."""
    row = {
        "id": "a1",
        "text": "Lateness penalty (weight 2)",
        "kind": "assumption",
        "source": "agent",
    }
    issues = verify_brief_consistency(
        merged_brief={"items": [dict(row)], "goal_terms": {}, "open_questions": []},
        base_brief={"items": [dict(row)], "goal_terms": {}, "open_questions": []},
        patch={},
        visible_reply="Run #2 completed with cost 100.",
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


def test_companion_pattern_keep_vs_drop_is_generic_across_terms():
    """The companion goal-term pattern is driven solely by the port's
    ``gate_conditional_companions`` declaration, so a SECOND companion term
    (VRPTW ``shift_limit`` → ``max_shift_hours``) gets identical keep-vs-drop
    behavior with zero term-specific code — proving the pattern is reusable, not
    worker_preference-special."""
    from app.problem_brief import reconcile_companion_oqs

    def _brief():
        return {
            "items": [], "open_questions": [],
            "goal_terms": {"shift_limit": {"weight": 500.0, "type": "soft",
                                           "properties": {"max_shift_hours": None}}},
        }

    kept = reconcile_companion_oqs(
        _brief(), "vrptw", base_brief={"goal_terms": {}}, turn_claimed_change=True
    )
    assert "shift_limit" in kept["goal_terms"], "claimed concrete companion keeps the term"
    assert any(q["id"] == "auto-oq-companion-shift_limit" for q in kept["open_questions"])

    dropped = reconcile_companion_oqs(
        _brief(), "vrptw", base_brief={"goal_terms": {}}, turn_claimed_change=False
    )
    assert "shift_limit" not in dropped["goal_terms"], "vague no-claim new companion is dropped"
    assert any(q["id"] == "auto-oq-companion-shift_limit" for q in dropped["open_questions"])


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


def test_reconcile_keep_vs_drop_by_claim():
    """Companion-goal-term pattern B1 vs B2 (keep-vs-drop the empty term):

    - **Claimed concrete child** (``turn_claimed_change=True``) but the agent
      left the carrier empty → KEEP the term + OQ. The participant gave a rule,
      so the term must show up (config/def can complete it; never silently lost).
    - **Vague mention, no claim** (``turn_claimed_change=False``) + new this turn
      → DROP the term; the OQ / agent question carries the ask. No empty term
      materialises for a vague "I want driver preferences".
    - **Pre-existing** term is always kept (non-destructive), claim or not.

    OQ text stays participant-friendly (no raw schema keys)."""
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

    # B2: concrete child claimed but carrier empty → KEPT + OQ.
    kept = reconcile_companion_oqs(
        _brief(), "vrptw", base_brief={"goal_terms": {}}, turn_claimed_change=True
    )
    assert "worker_preference" in kept["goal_terms"], "claimed concrete child must keep the term"
    auto = [q for q in kept["open_questions"] if str(q.get("id") or "").startswith("auto-oq-companion-")]
    assert len(auto) == 1 and auto[0]["goal_key"] == "worker_preference"
    assert "`" not in auto[0]["text"] and "driver_preferences" not in auto[0]["text"], (
        "participant-facing OQ must not leak raw schema keys"
    )

    # B1: vague, no claim, new this turn → DROPPED + OQ.
    dropped = reconcile_companion_oqs(
        _brief(), "vrptw", base_brief={"goal_terms": {}}, turn_claimed_change=False
    )
    assert "worker_preference" not in dropped["goal_terms"], "vague no-claim new term must be dropped"
    auto_b1 = [q for q in dropped["open_questions"] if str(q.get("id") or "").startswith("auto-oq-companion-")]
    assert len(auto_b1) == 1 and auto_b1[0]["goal_key"] == "worker_preference"

    # Pre-existing (key in base) → kept even without a claim.
    out_old = reconcile_companion_oqs(
        _brief(), "vrptw",
        base_brief={"goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft"}}},
        turn_claimed_change=False,
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


def test_ask_without_oq_satisfied_by_reaffirmed_open_oq():
    """P_0602 regression: the reply re-asks a clarifying question the brief
    already tracks (``oq-punctuality-tradeoff`` carried open from a prior
    turn), and the LLM re-emits that OQ by id in the patch. The participant
    still sees a matching open question, so ``ask_without_oq`` must NOT fire —
    even though the OQ is not *new* this turn. Before the fix, the retry was
    unwinnable (re-emitting the same id isn't "new"; mark_answered/rephrase
    would be wrong for an unanswered question)."""
    from app.services.pipeline_verification import verify_brief_consistency

    oq = {
        "id": "oq-punctuality-tradeoff",
        "text": "Would you like me to increase the weight on the lateness penalty?",
        "topic": "other",
        "goal_key": "lateness_penalty",
        "status": "open",
    }
    issues = verify_brief_consistency(
        merged_brief={"items": [], "goal_terms": {}, "open_questions": [oq]},
        base_brief={"items": [], "goal_terms": {}, "open_questions": [dict(oq)]},
        patch={"open_questions": [dict(oq)]},  # re-emitted by id, still open
        visible_reply=oq["text"],
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        question_clause=oq["text"],
    )
    assert not any(i.category == "ask_without_oq" for i in issues), [i.category for i in issues]


def test_ask_without_oq_still_fires_when_ask_is_unrecorded():
    """Guard: the reply asks a clarifying question but the LLM records NO
    matching OQ (empty patch open_questions, no new OQ, no oq_actions). The
    ask is genuinely unrecorded, so ``ask_without_oq`` MUST still fire — an
    unrelated leftover OQ must not mask it (the fix ties the pass to the LLM
    re-emitting the OQ, not to a bare 'any open OQ exists')."""
    from app.services.pipeline_verification import verify_brief_consistency

    leftover = {
        "id": "oq-unrelated",
        "text": "Some unrelated leftover question?",
        "topic": "other",
        "goal_key": "shift_limit",
        "status": "open",
    }
    issues = verify_brief_consistency(
        merged_brief={"items": [], "goal_terms": {}, "open_questions": [leftover]},
        base_brief={"items": [], "goal_terms": {}, "open_questions": [dict(leftover)]},
        patch={"open_questions": []},  # LLM recorded nothing for the new ask
        visible_reply="Should I add a brand-new penalty for idle time?",
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        question_clause="Should I add a brand-new penalty for idle time?",
    )
    assert any(i.category == "ask_without_oq" for i in issues), [i.category for i in issues]


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


def test_answered_oq_key_keeps_commit_even_when_pending_and_unanchored():
    """When the participant ANSWERS an OQ about key K (the turn's oq_actions
    resolve it), the goal_term commit for K must survive even though the OQ
    is still technically open at filter time and the term has no items[]
    anchor yet. ``answered_oq_keys`` takes precedence over the premature
    ``pending_oq_keys`` drop. Regression for P_0602: "approve the two
    proposed penalties as hard" silently lost both penalties because the
    filter premature-dropped them while ``_apply_oq_actions`` dropped the
    OQs a step later — erasing the approval entirely."""
    from app.services.goal_term_anchoring import filter_unanchored_new_goal_terms

    proposed = {
        "capacity_penalty": {"weight": 10.0, "type": "hard"},
        "lateness_penalty": {"weight": 10.0, "type": "hard"},
    }
    filtered, dropped = filter_unanchored_new_goal_terms(
        base_brief={"goal_terms": {}},
        proposed_goal_terms=proposed,
        items=[],  # no anchoring items yet — synthesis happens after the filter
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        # Both keys are pending (OQ still open at filter time) AND answered
        # (this turn's oq_actions drop them). Answered must win.
        pending_oq_keys={"capacity_penalty", "lateness_penalty"},
        answered_oq_keys={"capacity_penalty", "lateness_penalty"},
    )
    assert "capacity_penalty" in filtered
    assert "lateness_penalty" in filtered
    assert not dropped


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


def test_companion_overclaim_suppressed_for_extractor_covered_term():
    """`worker_preference` has a deterministic rule extractor
    (``companion_extraction_instructions``), so the S2 over-claim check no longer
    fires/retries on a hollow commit — the apply stage / def-save extractor
    populate the carrier reliably instead. This is what removes the "failed a
    bunch of times" retries the participant saw (P_0603). The check still applies
    to companion terms a port does NOT cover with an extractor."""
    from app.services.pipeline_verification import verify_brief_consistency

    issues = verify_brief_consistency(
        merged_brief={"goal_terms": {}, "items": [], "open_questions": []},
        base_brief={"goal_terms": {}},
        patch={"goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft", "rank": 5}}},
        visible_reply="I've added those driver preferences.",
        workflow_mode="agile",
        test_problem_id="vrptw",
        change_clause="I've added those driver preferences for Alice and Carol.",
    )
    assert not any(i.category == "port_companion" for i in issues), [i.category for i in issues]


def test_companion_overclaim_silent_when_asking_or_populated():
    from app.services.pipeline_verification import verify_brief_consistency

    # No change_clause (the agent is ASKING for details) → no fire.
    asking = verify_brief_consistency(
        merged_brief={"goal_terms": {}, "items": [], "open_questions": []},
        base_brief={"goal_terms": {}},
        patch={"goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft", "rank": 5}}},
        visible_reply="Which driver has which preference?",
        workflow_mode="agile",
        test_problem_id="vrptw",
        change_clause=None,
    )
    assert not any(i.category == "port_companion" for i in asking)

    # Companion populated → no fire.
    populated = verify_brief_consistency(
        merged_brief={"goal_terms": {}, "items": [], "open_questions": []},
        base_brief={"goal_terms": {}},
        patch={"goal_terms": {"worker_preference": {"weight": 1.0, "type": "soft", "rank": 5,
            "properties": {"driver_preferences": [
                {"vehicle_idx": 0, "condition": "avoid_zone", "zone": 4, "penalty": 50}]}}}},
        visible_reply="I've added those driver preferences.",
        workflow_mode="agile",
        test_problem_id="vrptw",
        change_clause="I've added those driver preferences.",
    )
    assert not any(i.category == "port_companion" for i in populated)


def test_verify_brief_retry_path_threads_session_id(monkeypatch):
    """Regression: the run-invitation gate added to the verify-brief RETRY path
    referenced ``session_id``, which wasn't a parameter of
    ``_run_verify_brief_stage`` — so every turn that retried crashed with
    NameError. The offline suite missed it (the Gemini stub pauses at drafting
    before the retry path runs). Drive the retry path directly and assert it
    completes without crashing."""
    from app.schemas import ChatTurnResponse
    from app.services import llm, pipeline_status
    from app.services.chat_pipeline_runner import _run_verify_brief_stage

    calls: list[dict] = []
    monkeypatch.setattr(pipeline_status, "update_stage", lambda **k: calls.append(k))
    monkeypatch.setattr(pipeline_status, "fail_pipeline", lambda **k: calls.append({"fail": True, **k}))
    # The retry returns a clean turn that flags a run invitation (so the
    # gate — and the previously-undefined session_id — is exercised).
    retry = ChatTurnResponse(
        assistant_message="Ready when you are.", problem_brief_patch=None, is_run_invitation=True
    )
    monkeypatch.setattr(llm, "generate_main_turn", lambda **k: retry)

    # First turn: claims a change with an empty patch → claim_without_delta →
    # forces the one retry.
    turn = ChatTurnResponse(
        assistant_message="I've added a lateness penalty.",
        problem_brief_patch=None,
        change_clause="I've added a lateness penalty.",
    )
    _run_verify_brief_stage(
        message_id=0,
        session_id="missing-session-regression",
        turn=turn,
        user_text="x",
        history_lines=[],
        api_key="",
        model_name="",
        base_problem_brief={"items": [], "goal_terms": {}, "open_questions": []},
        base_panel=None,
        workflow_mode="agile",
        researcher_steers=None,
        recent_runs_summary=None,
        is_run_acknowledgement=False,
        is_brief_edit_ack=False,
        is_config_save=False,
        is_upload_context=False,
        is_answered_open_question=False,
        is_tutorial_active=False,
        suppress_runack_invariant=False,
        test_problem_id="vrptw",
        gate_status=None,
    )
    # Reached the retry-persist path (with the gate) without a NameError; the
    # clean retry cleared the issue, so no pause.
    assert not [c for c in calls if c.get("state") == "paused"], calls


def test_companion_overclaim_does_not_pause_after_retries(monkeypatch):
    """P_0603: the LLM keeps committing a hollow ``worker_preference`` (no
    ``driver_preferences``) while the reply over-claims it. The over-claim
    retry gives the model a best-effort chance, but when every retry is still
    hollow we must NOT dead-end in a pause — the turn proceeds so apply (S3)'s
    ``reconcile_companion_oqs`` drops the hollow term and parks a natural
    companion OQ. ``port_companion`` is the one verifier issue that defers to
    the deterministic gate instead of pausing."""
    from app.schemas import ChatTurnResponse
    from app.services import llm, pipeline_status
    from app.services.chat_pipeline_runner import _run_verify_brief_stage

    calls: list[dict] = []
    monkeypatch.setattr(pipeline_status, "update_stage", lambda **k: calls.append(k))
    monkeypatch.setattr(pipeline_status, "fail_pipeline", lambda **k: calls.append({"fail": True, **k}))
    # No genuine change to "claim" beyond the hollow term, so the delta auditor
    # has nothing to flag — isolate the over-claim port_companion issue.
    monkeypatch.setattr(llm, "check_changes_acknowledged", lambda **k: [])

    hollow = ChatTurnResponse(
        assistant_message="I've added those driver preferences for Alice and Carol.",
        problem_brief_patch={
            "goal_terms": {
                "worker_preference": {
                    "weight": 1.0,
                    "type": "soft",
                    "properties": {"driver_preferences": []},
                }
            }
        },
        change_clause="I've added those driver preferences for Alice and Carol.",
    )
    # Every retry returns the same hollow over-claim — the model never structures
    # the rules, mirroring the live P_0603 failure.
    monkeypatch.setattr(llm, "generate_main_turn", lambda **k: hollow)

    _run_verify_brief_stage(
        message_id=0,
        session_id="companion-overclaim-regression",
        turn=hollow,
        user_text="Alice doesn't like zone d; carol doesn't like express orders",
        history_lines=[],
        api_key="",
        model_name="",
        base_problem_brief={"items": [], "goal_terms": {}, "open_questions": []},
        base_panel=None,
        workflow_mode="agile",
        researcher_steers=None,
        recent_runs_summary=None,
        is_run_acknowledgement=False,
        is_brief_edit_ack=False,
        is_config_save=False,
        is_upload_context=False,
        is_answered_open_question=False,
        is_tutorial_active=False,
        suppress_runack_invariant=False,
        test_problem_id="vrptw",
        gate_status=None,
    )
    # Best-effort retry exhausted, only port_companion left → graceful proceed,
    # NOT a pause. The deterministic companion-OQ gate handles it in apply.
    assert not [c for c in calls if c.get("state") == "paused"], calls
    assert not [c for c in calls if c.get("fail")], calls
    assert any(c.get("state") == "success" for c in calls), calls


def test_runack_missing_assumption_does_not_pause_after_retries(monkeypatch):
    """P_0603 (post-run #7): on an agile run-ack the LLM never adds/updates an
    assumption row. The retries give it a best-effort chance, but when every
    attempt still lacks one we must NOT dead-end in a pause — pausing here used
    to take down the *deterministic* run summary (``consolidate_runs`` runs in
    apply/S3, which a pause skips) and corrupt plateau detection. The turn must
    proceed so S3 writes ``brief.runs``."""
    from app.schemas import ChatTurnResponse
    from app.services import llm, pipeline_status
    from app.services.chat_pipeline_runner import _run_verify_brief_stage

    calls: list[dict] = []
    monkeypatch.setattr(pipeline_status, "update_stage", lambda **k: calls.append(k))
    monkeypatch.setattr(pipeline_status, "fail_pipeline", lambda **k: calls.append({"fail": True, **k}))
    monkeypatch.setattr(llm, "check_changes_acknowledged", lambda **k: [])

    # A pure acknowledgement with no new/updated assumption row.
    ack = ChatTurnResponse(
        assistant_message="Run #7 completed with cost 1,200 — no constraint violations.",
        problem_brief_patch=None,
    )
    monkeypatch.setattr(llm, "generate_main_turn", lambda **k: ack)

    _run_verify_brief_stage(
        message_id=0,
        session_id="runack-no-assumption-regression",
        turn=ack,
        user_text="",
        history_lines=[],
        api_key="",
        model_name="",
        base_problem_brief={"items": [], "goal_terms": {}, "open_questions": []},
        base_panel=None,
        workflow_mode="agile",
        researcher_steers=None,
        recent_runs_summary=[{"run_number": 7, "cost": 1200.0, "ok": True, "algorithm": "GA"}],
        is_run_acknowledgement=True,
        is_brief_edit_ack=False,
        is_config_save=False,
        is_upload_context=False,
        is_answered_open_question=False,
        is_tutorial_active=False,
        suppress_runack_invariant=False,
        test_problem_id="vrptw",
        gate_status=None,
    )
    # Best-effort retry exhausted, only runack_invariant_violation left →
    # graceful proceed so apply (S3) still consolidates run #7's summary entry.
    assert not [c for c in calls if c.get("state") == "paused"], calls
    assert not [c for c in calls if c.get("fail")], calls
    assert any(c.get("state") == "success" for c in calls), calls
