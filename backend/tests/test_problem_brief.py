"""Unit tests for problem brief normalization and merge helpers."""

from app.problem_brief import (
    CHAT_PROMPT_COLD_BACKEND_TEMPLATE,
    CHAT_PROMPT_COLD_SYSTEM_ITEM_TEXT,
    _brief_items_from_panel,
    cleanup_open_questions,
    default_problem_brief,
    is_chat_cold_start,
    locked_goal_terms_prompt_section,
    merge_problem_brief_patch,
    question_is_upload_related,
    coerce_problem_brief_for_workflow,
    normalize_problem_brief,
    resolve_upload_open_questions_after_upload,
    surface_problem_brief_for_chat_prompt,
    sync_problem_brief_from_panel,
)


def _minimal_brief_payload(**kwargs):
    base = {
        "goal_summary": "g",
        "items": [],
        "open_questions": [],
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }
    base.update(kwargs)
    return base


def test_merge_replace_open_questions_true_prunes_stale_questions():
    base = normalize_problem_brief(
        _minimal_brief_payload(
            open_questions=[
                {"id": "q-a", "text": "Stale?", "status": "open", "answer_text": None},
                {"id": "q-b", "text": "Still matters?", "status": "open", "answer_text": None},
            ],
        )
    )
    merged = merge_problem_brief_patch(
        base,
        {
            "replace_open_questions": True,
            "open_questions": [
                {"id": "q-b", "text": "Still matters?", "status": "open", "answer_text": None},
            ],
        },
    )
    assert [q["id"] for q in merged["open_questions"]] == ["q-b"]


def test_merge_keeps_prior_goal_summary_when_patch_sanitizes_to_empty():
    """A model patch that fails the sanitizer must not silently wipe a good prior summary."""
    base = normalize_problem_brief(
        _minimal_brief_payload(
            goal_summary="Maximize value picked from the bag without overflowing capacity."
        )
    )
    assert base["goal_summary"]
    # Patch contains only sanitizer-stripped tokens, so sanitized result is empty.
    merged = merge_problem_brief_patch(
        base, {"goal_summary": "tune pop_size and c1 for stability."}
    )
    # Prior summary is preserved instead of being clobbered.
    assert merged["goal_summary"] == base["goal_summary"]


def test_merge_clears_goal_summary_when_patch_explicitly_empty():
    base = normalize_problem_brief(_minimal_brief_payload(goal_summary="Old goal."))
    merged = merge_problem_brief_patch(base, {"goal_summary": ""})
    assert merged["goal_summary"] == ""


def test_cleanup_open_questions_deduplicates_without_inferred_pruning():
    brief = normalize_problem_brief(
        _minimal_brief_payload(
            open_questions=[
                {"id": "q1", "text": "Do we allow overtime?", "status": "open", "answer_text": None},
                {"id": "q2", "text": "do we allow overtime?", "status": "open", "answer_text": None},
                {"id": "q3", "text": "Any priority orders?", "status": "open", "answer_text": None},
            ]
        )
    )
    cleaned, meta = cleanup_open_questions(brief, infer_resolved=False)
    assert [q["id"] for q in cleaned["open_questions"]] == ["q1", "q3"]
    assert meta["removed_duplicates"] == 1
    assert meta["removed_inferred"] == 0


def test_resolve_upload_open_questions_after_upload_promotes_to_gathered():
    brief = normalize_problem_brief(
        _minimal_brief_payload(
            open_questions=[
                {
                    "id": "q-upload",
                    "text": "Please upload order and driver files before we proceed.",
                    "status": "open",
                    "answer_text": None,
                },
                {
                    "id": "q-policy",
                    "text": "Any overtime policy?",
                    "status": "open",
                    "answer_text": None,
                },
            ]
        )
    )
    updated = resolve_upload_open_questions_after_upload(brief, ["ORDERS.csv", "DRIVER_INFO.csv"])
    remaining_ids = [q["id"] for q in updated["open_questions"]]
    assert remaining_ids == ["q-policy"]
    gathered = [item for item in updated["items"] if item.get("kind") == "gathered"]
    upload_markers = [item for item in gathered if item.get("source") == "upload"]
    # One canonical upload-marker row, with the file names embedded as a clean statement
    # (the legacy "<question> — Uploaded file(s) received: …" promotion produced a verbose
    # row that overlapped with anything the LLM wrote about the upload).
    assert len(upload_markers) == 1
    assert upload_markers[0]["id"] == "item-gathered-upload"
    assert upload_markers[0]["text"] == "Source data file(s) uploaded: ORDERS.csv, DRIVER_INFO.csv."


def test_coerce_waterfall_converts_assumptions_into_open_questions():
    brief = normalize_problem_brief(
        _minimal_brief_payload(
            items=[
                {
                    "id": "a1",
                    "text": "Assume moderate workload balance unless stated otherwise.",
                    "kind": "assumption",
                    "source": "agent",
                    "status": "active",
                    "editable": True,
                }
            ],
            open_questions=[],
        )
    )
    coerced = coerce_problem_brief_for_workflow(brief, "waterfall")
    assert not any(i.get("kind") == "assumption" for i in coerced["items"])
    assert any(
        q.get("status") == "open" and "confirm or correct" in str(q.get("text") or "").lower()
        for q in coerced.get("open_questions") or []
    )


def test_coerce_demo_drops_assumptions_silently():
    """Demo mode drops assumption rows without converting them to OQs.

    Reasoning: the prompt requires a proper OQ-with-choices for tunable defaults
    (search algorithm etc.) to already exist when the agent commits to one. If
    the agent slips and emits an assumption alongside, we don't want a
    'Confirm or correct: …' OQ that reads as a foregone conclusion — we want
    no row at all. The working value still lives on the panel, so the run
    continues to work."""
    brief = normalize_problem_brief(
        _minimal_brief_payload(
            items=[
                {
                    "id": "a-algo",
                    "text": "Using Genetic Algorithm for initial exploration.",
                    "kind": "assumption",
                    "source": "agent",
                    "status": "active",
                    "editable": True,
                },
                {
                    "id": "g-1",
                    "text": "Knapsack capacity is 50 units.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "active",
                    "editable": True,
                },
            ],
            open_questions=[
                {"id": "q-algo", "text": "Which search method should I use?", "status": "open"}
            ],
        )
    )
    coerced = coerce_problem_brief_for_workflow(brief, "demo")
    # Assumption row is gone.
    assert not any(i.get("kind") == "assumption" for i in coerced["items"])
    # Gathered rows are preserved as-is.
    assert any(
        i.get("kind") == "gathered" and "capacity is 50" in str(i.get("text") or "").lower()
        for i in coerced["items"]
    )
    # No "Confirm or correct" OQ was synthesized from the assumption.
    assert not any(
        "confirm or correct" in str(q.get("text") or "").lower()
        for q in coerced.get("open_questions") or []
    )
    # Pre-existing OQs are preserved.
    assert any(
        "search method" in str(q.get("text") or "").lower()
        for q in coerced.get("open_questions") or []
    )


def test_coerce_agile_keeps_assumptions():
    """Agile is the only mode that legitimately wants assumption rows visible in the brief."""
    brief = normalize_problem_brief(
        _minimal_brief_payload(
            items=[
                {
                    "id": "a1",
                    "text": "Using Genetic Algorithm for initial exploration.",
                    "kind": "assumption",
                    "source": "agent",
                    "status": "active",
                    "editable": True,
                }
            ],
            open_questions=[],
        )
    )
    coerced = coerce_problem_brief_for_workflow(brief, "agile")
    assert any(i.get("kind") == "assumption" for i in coerced["items"])


def test_brief_items_from_panel_always_shows_strategy_if_algorithm_present():
    """Now search strategy details (iterations/population) are explicitly shown even if other params are default."""
    panel = {"problem": {"algorithm": "GA", "algorithm_params": {"pc": 0.9, "pm": 0.05}}}
    items = _brief_items_from_panel(panel)
    texts = [i["text"] for i in items]
    assert any("search strategy: ga" in t.lower() for t in texts)
    # Check that it includes default iterations/population (100/50).
    s = [t for t in texts if "search strategy:" in t.lower()][0]
    assert "iterations 100" in s
    assert "population size 50" in s
    # But still omits default algorithm-specific params (pc, pm).
    assert "pc=" not in s
    assert "pm=" not in s


def test_normalize_does_not_split_commas_inside_parentheses():
    raw = _minimal_brief_payload(
        items=[
            {
                "id": "goal-travel-time",
                "text": "Minimize overall travel time (Objective, Weight 1.0).",
                "kind": "gathered",
                "source": "user",
            },
            {
                "id": "constraint-capacity",
                "text": "Enforce vehicle capacity limits (Hard constraint, Weight 1000.0).",
                "kind": "gathered",
                "source": "user",
            },
        ]
    )
    out = normalize_problem_brief(raw)
    gathered = [item for item in out["items"] if item["kind"] == "gathered"]
    assert [g["id"] for g in gathered] == ["goal-travel-time", "constraint-capacity"]
    assert gathered[0]["text"] == "Minimize overall travel time (Objective, Weight 1.0)."
    assert gathered[1]["text"] == "Enforce vehicle capacity limits (Hard constraint, Weight 1000.0)."


def test_sync_problem_brief_from_panel_preserves_assumption_provenance():
    """Agent-introduced assumption rows must not be silently promoted to gathered
    via the panel round-trip. When the existing brief has an assumption row
    populating a config slot, the panel-derived row inherits assumption/agent."""
    base = normalize_problem_brief(
        _minimal_brief_payload(
            items=[
                {
                    "id": "config-weight-capacity_penalty",
                    "text": "Load capacity is a soft constraint term (weight 5.0).",
                    "kind": "assumption",
                    "source": "agent",
                },
            ],
        )
    )
    panel = {
        "problem": {
            "weights": {"capacity_penalty": 5.0},
            "constraint_types": {"capacity_penalty": "soft"},
        }
    }
    out = sync_problem_brief_from_panel(base, panel)
    capacity_rows = [
        item for item in out["items"]
        if item.get("id") == "config-weight-capacity_penalty"
    ]
    assert len(capacity_rows) == 1
    assert capacity_rows[0]["kind"] == "assumption"
    assert capacity_rows[0]["source"] == "agent"


def test_sync_problem_brief_from_panel_keeps_existing_gathered_as_gathered():
    """If the existing slot row is gathered, panel sync must not regress it to assumption."""
    base = normalize_problem_brief(
        _minimal_brief_payload(
            items=[
                {
                    "id": "config-weight-travel_time",
                    "text": "Travel time is a primary objective term (weight 2.0).",
                    "kind": "gathered",
                    "source": "user",
                },
            ],
        )
    )
    panel = {"problem": {"weights": {"travel_time": 3.0}}}
    out = sync_problem_brief_from_panel(base, panel)
    rows = [item for item in out["items"] if item.get("id") == "config-weight-travel_time"]
    assert len(rows) == 1
    assert rows[0]["kind"] == "gathered"


def test_is_chat_cold_start_flag_and_content_fallback():
    """Cold-start is OR'd between the LLM-judged ``topic_engaged`` flag and a
    content-based fallback (user/upload-sourced items, non-empty
    goal_summary). The fallback exists because the LLM is unreliable at
    emitting ``topic_engaged_next``; without it, the server stayed stuck at
    "cold" through engaged conversations and monitors never ran.

    Agent-only items still don't warm the conversation — that's the case the
    flag is meant to catch when LLM judgment IS reliable."""
    b = default_problem_brief("knapsack")
    assert is_chat_cold_start(b) is True

    # Flag flips warm.
    assert is_chat_cold_start({**b, "topic_engaged": True}) is False

    # goal_summary set flips warm via the content fallback.
    assert is_chat_cold_start({**b, "goal_summary": "Maximize value"}) is False

    # User-sourced gathered item flips warm via the content fallback.
    b_with_gathered = _minimal_brief_payload(
        goal_summary="",
        open_questions=[],
        items=[
            {
                "id": "g1",
                "text": "User wants sparsity",
                "kind": "gathered",
                "source": "user",
                "status": "confirmed",
                "editable": True,
            }
        ],
    )
    assert is_chat_cold_start(b_with_gathered) is False

    # Agent-only item does NOT flip warm (deliberate — that's a starter
    # default or pre-confirmation assumption, not participant engagement).
    b_with_agent_only = _minimal_brief_payload(
        goal_summary="",
        items=[
            {"id": "a1", "text": "Default GA", "kind": "assumption", "source": "agent"}
        ],
    )
    assert is_chat_cold_start(b_with_agent_only) is True


def test_warmth_flag_is_sticky_one_way():
    """``topic_engaged_next`` only flips False→True; ``False`` is never honored
    so a later off-topic detour doesn't re-leak the cold-start sandbox."""
    warm_base = normalize_problem_brief(
        _minimal_brief_payload(goal_summary="", topic_engaged=True)
    )
    # Patch tries to downgrade. Must be ignored.
    out = merge_problem_brief_patch(warm_base, {"topic_engaged_next": False})
    assert out["topic_engaged"] is True

    # Patch leaves it warm.
    out = merge_problem_brief_patch(warm_base, {"topic_engaged_next": True})
    assert out["topic_engaged"] is True

    # Cold base, true patch → warm.
    cold_base = normalize_problem_brief(_minimal_brief_payload(goal_summary=""))
    assert cold_base["topic_engaged"] is False
    out = merge_problem_brief_patch(cold_base, {"topic_engaged_next": True})
    assert out["topic_engaged"] is True

    # Cold base, no patch field → still cold.
    out = merge_problem_brief_patch(cold_base, {"items": []})
    assert out["topic_engaged"] is False


# ---------------------------------------------------------------------------
# goal_terms structured carrier (driver_preferences fix)
# ---------------------------------------------------------------------------


def _well_formed_alice_zone_d_rule():
    return {
        "vehicle_idx": 0,
        "condition": "avoid_zone",
        "zone": 4,
        "penalty": 50,
    }


def test_merge_appends_unmodeled_requests_with_dedupe():
    """``unmodeled_requests`` is an append-only audit trail of participant
    asks the panel can't model. Subsequent turns must accumulate new rows
    without re-emitting old ones."""
    base = normalize_problem_brief(
        _minimal_brief_payload(
            unmodeled_requests=[
                {
                    "user_text": "penalty for driving during 7-9am peak hours",
                    "closest_match": "travel_time",
                    "rationale": "Peak-window penalties are absorbed into travel_time via the traffic profile.",
                }
            ],
        )
    )
    patch = {
        "unmodeled_requests": [
            # Re-emit of an existing row — must dedupe.
            {
                "user_text": "Penalty for driving during 7-9am peak hours",
                "closest_match": "travel_time",
                "rationale": "duplicate",
            },
            # New row — must append.
            {
                "user_text": "penalty for starting earlier than shift starts",
                "rationale": "Shift-start enforcement is not modeled.",
            },
            # Malformed — must skip.
            {"closest_match": "travel_time"},
        ]
    }
    out = merge_problem_brief_patch(base, patch)
    rows = out["unmodeled_requests"]
    assert len(rows) == 2
    texts = [r["user_text"] for r in rows]
    assert texts[0] == "penalty for driving during 7-9am peak hours"
    assert texts[1] == "penalty for starting earlier than shift starts"
    # Original rationale survived dedupe.
    assert "Peak-window" in rows[0]["rationale"]


def test_normalize_preserves_goal_terms_with_driver_preferences():
    raw = _minimal_brief_payload(
        goal_terms={
            "worker_preference": {
                "weight": 1.0,
                "type": "soft",
                "properties": {
                    "driver_preferences": [_well_formed_alice_zone_d_rule()],
                },
            }
        },
    )
    out = normalize_problem_brief(raw)
    rules = out["goal_terms"]["worker_preference"]["properties"]["driver_preferences"]
    assert len(rules) == 1
    assert rules[0]["vehicle_idx"] == 0
    assert rules[0]["zone"] == 4
    assert out["goal_terms"]["worker_preference"]["type"] == "soft"


def test_normalize_drops_malformed_driver_preference_keeps_well_formed():
    raw = _minimal_brief_payload(
        goal_terms={
            "worker_preference": {
                "weight": 1.0,
                "type": "soft",
                "properties": {
                    "driver_preferences": [
                        _well_formed_alice_zone_d_rule(),
                        {"vehicle_idx": 99, "condition": "avoid_zone", "zone": 4, "penalty": 1},  # bad vid
                        {"vehicle_idx": 1, "condition": "bogus", "penalty": 1},  # bad condition
                        {"vehicle_idx": 1, "condition": "avoid_zone", "zone": 9, "penalty": 1},  # bad zone
                        {"vehicle_idx": 1, "condition": "avoid_zone", "zone": 2, "penalty": -5},  # negative penalty
                    ],
                },
            }
        },
    )
    out = normalize_problem_brief(raw)
    rules = out["goal_terms"]["worker_preference"]["properties"]["driver_preferences"]
    assert len(rules) == 1
    assert rules[0]["zone"] == 4


def test_normalize_drops_malformed_goal_term_entry_keeps_others():
    raw = _minimal_brief_payload(
        goal_terms={
            "worker_preference": {"weight": 1.0, "type": "soft"},
            "broken": {"type": "objective"},  # missing weight → drop entry
            "travel_time": {"weight": 5.0, "type": "objective"},
        },
    )
    out = normalize_problem_brief(raw)
    assert "broken" not in out["goal_terms"]
    assert set(out["goal_terms"].keys()) == {"worker_preference", "travel_time"}


def test_merge_goal_terms_deep_merges_per_key():
    base = normalize_problem_brief(
        _minimal_brief_payload(
            goal_terms={
                "travel_time": {"weight": 5.0, "type": "objective"},
                "worker_preference": {
                    "weight": 1.0,
                    "type": "soft",
                    "properties": {
                        "driver_preferences": [_well_formed_alice_zone_d_rule()],
                    },
                },
            },
        )
    )
    # Patch only worker_preference; travel_time must survive untouched.
    merged = merge_problem_brief_patch(
        base,
        {
            "goal_terms": {
                "worker_preference": {
                    "weight": 2.0,
                    "type": "soft",
                    "properties": {
                        "driver_preferences": [
                            {
                                "vehicle_idx": 1,
                                "condition": "order_priority",
                                "order_priority": "express",
                                "penalty": 10,
                            }
                        ]
                    },
                }
            }
        },
    )
    # travel_time preserved.
    assert merged["goal_terms"]["travel_time"]["weight"] == 5.0
    # worker_preference top-level updated.
    assert merged["goal_terms"]["worker_preference"]["weight"] == 2.0
    # driver_preferences replaced wholesale (atomic list semantics).
    rules = merged["goal_terms"]["worker_preference"]["properties"]["driver_preferences"]
    assert len(rules) == 1
    assert rules[0]["condition"] == "order_priority"


def test_merge_goal_terms_replace_flag_overwrites_full_map():
    base = normalize_problem_brief(
        _minimal_brief_payload(
            goal_terms={
                "travel_time": {"weight": 5.0, "type": "objective"},
                "worker_preference": {"weight": 1.0, "type": "soft"},
            },
        )
    )
    merged = merge_problem_brief_patch(
        base,
        {
            "replace_goal_terms": True,
            "goal_terms": {
                "lateness_penalty": {"weight": 7.0, "type": "objective"},
            },
        },
    )
    assert set(merged["goal_terms"].keys()) == {"lateness_penalty"}


def test_sync_problem_brief_from_panel_mirrors_goal_terms():
    """Manual UI-side preference adds become first-class brief data."""
    base = default_problem_brief("vrptw")
    panel = {
        "problem": {
            "goal_terms": {
                "worker_preference": {
                    "weight": 5.0,
                    "type": "soft",
                    "properties": {
                        "driver_preferences": [_well_formed_alice_zone_d_rule()],
                    },
                }
            }
        }
    }
    out = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw")
    rules = out["goal_terms"]["worker_preference"]["properties"]["driver_preferences"]
    assert rules == [_well_formed_alice_zone_d_rule()]
    assert out["goal_terms"]["worker_preference"]["weight"] == 5.0


def test_sync_problem_brief_from_panel_strips_supporting_items_on_removal():
    """Removing ``worker_preference`` from the panel must cascade — both the
    auto-synthesized ``config-driver-pref-*`` row and a user-prose row that
    the LLM cited as evidence have to be pruned from the brief. Otherwise the
    next derive pass re-introduces the term via self-anchor."""
    base = default_problem_brief("vrptw")
    user_item_id = "user-alice-zone-d-1"
    base["items"] = [
        {
            "id": "config-driver-pref-0-zone-D",
            "text": "Alice avoids deliveries in Zone D (Westgate) (penalty 50.0).",
            "kind": "gathered",
            "source": "agent",
        },
        {
            "id": user_item_id,
            "text": "Alice avoids zone D.",
            "kind": "gathered",
            "source": "user",
        },
        {
            "id": "user-unrelated-1",
            "text": "Total travel time is the main objective.",
            "kind": "gathered",
            "source": "user",
        },
    ]
    base["goal_terms"] = {
        "worker_preference": {
            "weight": 1.0,
            "type": "soft",
            "properties": {
                "driver_preferences": [_well_formed_alice_zone_d_rule()],
            },
            "evidence_item_ids": [user_item_id],
        }
    }

    # Panel save with worker_preference removed (other terms unchanged).
    panel_after_removal = {"problem": {"goal_terms": {}}}
    out = sync_problem_brief_from_panel(
        base, panel_after_removal, test_problem_id="vrptw"
    )

    item_ids = {item["id"] for item in out["items"]}
    assert "config-driver-pref-0-zone-D" not in item_ids
    assert user_item_id not in item_ids
    assert "user-unrelated-1" in item_ids
    assert "worker_preference" not in out["goal_terms"]


def test_apply_brief_patch_anchors_goal_terms_against_user_message(monkeypatch):
    """When the brief-update LLM emits a goal_term + evidence cite to the user
    message (which doesn't yet exist as a brief item), the anchor must pass
    via the virtual user-message item injected at the anchor call site.
    Without this, agile turns where the user says 'minimize travel time'
    but the LLM forgets to also emit a matching items[] row get their
    goal_terms silently dropped — and the workflow-compliance check flags
    'visible reply claimed a brief change but the stored brief is unchanged'."""
    from app.routers.sessions.derivation import apply_brief_patch_with_cleanup

    # No api_key → embedding fallback skipped; anchor must succeed via the
    # virtual item's evidence_item_ids cite.
    base = default_problem_brief("vrptw")
    patch_payload = {
        "items": [],
        "goal_terms": {
            "travel_time": {
                "weight": 1.0,
                "type": "objective",
                "evidence_item_ids": ["__virtual_user_message__"],
            }
        },
    }
    out, _meta = apply_brief_patch_with_cleanup(
        base_problem_brief=base,
        patch_payload=patch_payload,
        history_lines=[],
        api_key="",
        model_name="",
        workflow_mode="agile",
        current_panel=None,
        recent_runs_summary=[],
        researcher_steers=[],
        test_problem_id="vrptw",
        enable_auto_open_question_cleanup=False,
        user_text="I want to minimize travel time please",
    )
    assert "travel_time" in (out.get("goal_terms") or {}), out


def test_monitor_inserts_upload_oq_when_warm_and_no_upload(monkeypatch):
    """Server-side state machine: warm conversation, no upload item yet →
    insert the upload OQ with the stable monitor id. Idempotent across
    re-calls."""
    from app.routers.sessions.derivation import (
        _MONITOR_OQ_UPLOAD_ID,
        _enforce_session_monitors,
    )

    brief = normalize_problem_brief({
        "goal_summary": "Optimize fleet routes.",
        "items": [
            {"id": "u1", "text": "I need to optimize routes.", "kind": "gathered", "source": "user"}
        ],
        "open_questions": [],
        "goal_terms": {},
        "topic_engaged": True,
    })
    out = _enforce_session_monitors(brief, "agile")
    oq_ids = [str(q.get("id") or "") for q in out["open_questions"]]
    assert _MONITOR_OQ_UPLOAD_ID in oq_ids
    # Idempotent: re-enforcing doesn't duplicate.
    out2 = _enforce_session_monitors(out, "agile")
    assert oq_ids.count(_MONITOR_OQ_UPLOAD_ID) == [
        str(q.get("id") or "") for q in out2["open_questions"]
    ].count(_MONITOR_OQ_UPLOAD_ID)


def test_monitor_drops_upload_oq_once_upload_lands():
    """Once a ``source: upload`` item appears, the monitor drops the OQ."""
    from app.routers.sessions.derivation import (
        _MONITOR_OQ_UPLOAD_ID,
        _MONITOR_OQ_UPLOAD_TEXT,
        _enforce_session_monitors,
    )

    brief = normalize_problem_brief({
        "goal_summary": "Optimize fleet routes.",
        "items": [
            {
                "id": "item-gathered-upload",
                "text": "Source data file(s) uploaded: orders.csv.",
                "kind": "gathered",
                "source": "upload",
            }
        ],
        "open_questions": [
            {"id": _MONITOR_OQ_UPLOAD_ID, "text": _MONITOR_OQ_UPLOAD_TEXT, "status": "open"}
        ],
        "goal_terms": {},
        "topic_engaged": True,
    })
    out = _enforce_session_monitors(brief, "agile")
    oq_ids = {str(q.get("id") or "") for q in out["open_questions"]}
    assert _MONITOR_OQ_UPLOAD_ID not in oq_ids


def test_monitor_goal_oq_both_workflows():
    """Goal monitor inserts an OQ in both agile and waterfall when
    ``brief.goal_terms`` is empty."""
    from app.routers.sessions.derivation import (
        _MONITOR_OQ_GOAL_ID,
        _enforce_session_monitors,
    )

    base = normalize_problem_brief({
        "goal_summary": "Optimize fleet routes.",
        "items": [
            {"id": "item-gathered-upload", "text": "Source data file(s) uploaded.", "kind": "gathered", "source": "upload"}
        ],
        "open_questions": [],
        "goal_terms": {},
        "topic_engaged": True,
    })
    for workflow in ("agile", "waterfall"):
        out = _enforce_session_monitors(base, workflow)
        oq_ids = {str(q.get("id") or "") for q in out["open_questions"]}
        assert _MONITOR_OQ_GOAL_ID in oq_ids, workflow


def test_monitor_algorithm_assumption_agile_oq_waterfall():
    """Agile gets an algorithm ``kind: assumption`` row; waterfall gets an OQ."""
    from app.routers.sessions.derivation import (
        _MONITOR_ITEM_ALGORITHM_ID,
        _MONITOR_OQ_ALGORITHM_ID,
        _enforce_session_monitors,
    )

    base = normalize_problem_brief({
        "goal_summary": "Optimize fleet routes.",
        "items": [
            {"id": "u1", "text": "Minimize travel time.", "kind": "gathered", "source": "user"}
        ],
        "open_questions": [],
        "goal_terms": {"travel_time": {"weight": 1.0, "type": "objective"}},
        "topic_engaged": True,
    })

    out_agile = _enforce_session_monitors(base, "agile")
    item_ids_agile = {str(i.get("id") or "") for i in out_agile["items"]}
    assert _MONITOR_ITEM_ALGORITHM_ID in item_ids_agile
    oq_ids_agile = {str(q.get("id") or "") for q in out_agile["open_questions"]}
    assert _MONITOR_OQ_ALGORITHM_ID not in oq_ids_agile

    out_waterfall = _enforce_session_monitors(base, "waterfall")
    oq_ids_waterfall = {str(q.get("id") or "") for q in out_waterfall["open_questions"]}
    assert _MONITOR_OQ_ALGORITHM_ID in oq_ids_waterfall
    item_ids_waterfall = {str(i.get("id") or "") for i in out_waterfall["items"]}
    assert _MONITOR_ITEM_ALGORITHM_ID not in item_ids_waterfall


def test_visible_reply_commit_detector():
    """The commit-phrase detector decides when the recovery path should
    fall back to the brief-update LLM. False on small-talk, true on the
    'Changes I made / I've set / primary objective / as a baseline' family."""
    from app.routers.sessions.derivation import _visible_reply_commits

    assert _visible_reply_commits(None) is False
    assert _visible_reply_commits("") is False
    assert _visible_reply_commits("Hello! What would you like to optimize?") is False

    assert _visible_reply_commits(
        "Changes I made: Added travel-time emphasis to prioritize route efficiency."
    ) is True
    assert _visible_reply_commits(
        "I've set total travel time as your primary objective."
    ) is True
    assert _visible_reply_commits(
        "I'm using genetic search (GA) as a baseline."
    ) is True
    assert _visible_reply_commits(
        "I've defaulted to GA — change anytime."
    ) is True


def test_grounding_discipline_included_in_brief_update_prompt():
    """The grounding discipline must reach the merged system instruction so
    the LLM doesn't confabulate goal terms or algorithms that aren't in the
    current brief on acknowledgement turns."""
    from app.services.llm import _build_brief_update_system_instruction

    system = _build_brief_update_system_instruction(
        current_problem_brief={
            "goal_summary": "",
            "items": [],
            "open_questions": [],
            "topic_engaged": True,
        },
        workflow_mode="agile",
        test_problem_id="vrptw",
    )
    flat = " ".join(system.split())
    assert "Grounding discipline" in system
    assert "Confabulation" in flat or "Forbidden claims" in flat
    assert "Acknowledgement turns are especially risky" in flat


def test_goal_term_backing_validator_adds_assumption_rows(monkeypatch):
    """The semantic validator (separate LLM call) fills in assumption items
    for goal_terms keys that lack explicit backing. Stable id
    ``item-validator-{key}`` keeps re-runs idempotent."""
    from app.routers.sessions.derivation import _validate_goal_term_backing

    monkeypatch.setattr(
        "app.services.llm.validate_goal_term_backing",
        lambda brief, api_key, model_name, test_problem_id: {
            "assumptions_to_add": [
                {
                    "goal_term_key": "travel_time",
                    "text": "Assumed travel time as primary objective based on the routing framing. Confirm or remove.",
                }
            ],
            "updated_goal_summary": "",
        },
    )

    brief = {
        "goal_summary": "Existing summary kept as-is.",
        "items": [
            {
                "id": "user-1",
                "text": "Optimize delivery routing",
                "kind": "gathered",
                "source": "user",
            }
        ],
        "open_questions": [],
        "goal_terms": {
            "travel_time": {"weight": 1.0, "type": "objective"}
        },
    }
    out = _validate_goal_term_backing(brief, api_key="fake-key", model_name="g", test_problem_id="vrptw")
    assert any(
        i.get("id") == "item-validator-travel_time"
        and i.get("kind") == "assumption"
        and i.get("source") == "agent"
        for i in out["items"]
    )

    # Idempotent: a second pass with the same mocked response doesn't duplicate.
    out2 = _validate_goal_term_backing(out, api_key="fake-key", model_name="g", test_problem_id="vrptw")
    validator_rows = [
        i for i in out2["items"] if str(i.get("id") or "").startswith("item-validator-")
    ]
    assert len(validator_rows) == 1


def test_run_ack_sanitizer_preserves_cite_chain():
    """Run-ack turns commit goal_terms with ``evidence_item_ids`` cites to
    items the LLM emits in the same patch. The sanitizer's slot filter
    used to drop those items because they don't match a ``config-weight-*``
    id, severing the cite chain and causing the brief-side anchor to drop
    the goal-term keys too. With the cite-chain exemption, the items
    survive the sanitizer regardless of slot/kind."""
    from app.routers.sessions.derivation import sanitize_run_ack_patch_payload

    patch = {
        "items": [
            {
                "id": "g-late-1",
                "text": "Added lateness_penalty after Run #1 showed time-window misses.",
                "kind": "gathered",
                "source": "agent",
            },
            {
                "id": "g-cap-1",
                "text": "Added capacity_penalty after Run #1 showed capacity overflows.",
                "kind": "gathered",
                "source": "agent",
            },
            {
                "id": "bookkeeping-run-1",
                "text": "Run #1 completed at 14:23 with cost 1234.",
                "kind": "gathered",
                "source": "agent",
            },
        ],
        "goal_terms": {
            "lateness_penalty": {
                "weight": 10.0,
                "type": "soft",
                "evidence_item_ids": ["g-late-1"],
            },
            "capacity_penalty": {
                "weight": 15.0,
                "type": "soft",
                "evidence_item_ids": ["g-cap-1"],
            },
        },
    }
    out = sanitize_run_ack_patch_payload(
        patch, workflow_mode="agile", test_problem_id="vrptw"
    )
    kept_ids = {item["id"] for item in out["items"]}
    # Cited items must survive — without them the goal_terms lose their
    # anchor downstream.
    assert "g-late-1" in kept_ids
    assert "g-cap-1" in kept_ids
    # Pure bookkeeping rows still get dropped.
    assert "bookkeeping-run-1" not in kept_ids


def test_goal_term_backing_validator_refreshes_goal_summary(monkeypatch):
    """When the validator returns an ``updated_goal_summary``, the brief's
    goal_summary is replaced. Empty string from the LLM means "leave the
    existing summary alone" — idempotency check."""
    from app.routers.sessions.derivation import _validate_goal_term_backing

    monkeypatch.setattr(
        "app.services.llm.validate_goal_term_backing",
        lambda brief, api_key, model_name, test_problem_id: {
            "assumptions_to_add": [],
            "updated_goal_summary": "Optimize delivery routes for minimum total travel time.",
        },
    )

    brief = {
        "goal_summary": "",
        "items": [
            {"id": "u1", "text": "User picked travel time.", "kind": "gathered", "source": "user"}
        ],
        "open_questions": [],
        "goal_terms": {"travel_time": {"weight": 1.0, "type": "objective"}},
    }
    out = _validate_goal_term_backing(brief, api_key="fake-key", model_name="g", test_problem_id="vrptw")
    assert out["goal_summary"] == "Optimize delivery routes for minimum total travel time."

    # Idempotency: the LLM returning empty updated_goal_summary preserves
    # the existing summary.
    monkeypatch.setattr(
        "app.services.llm.validate_goal_term_backing",
        lambda brief, api_key, model_name, test_problem_id: {
            "assumptions_to_add": [],
            "updated_goal_summary": "",
        },
    )
    out2 = _validate_goal_term_backing(out, api_key="fake-key", model_name="g", test_problem_id="vrptw")
    assert out2["goal_summary"] == out["goal_summary"]


def test_hard_constraint_discipline_included_in_brief_update_prompt():
    """The hard-constraint section must be present in the brief-update
    system instruction so the LLM doesn't fabricate goal terms for
    each-once / capacity-cap / locked-assignment phrasings."""
    from app.services.llm import _build_brief_update_system_instruction

    system = _build_brief_update_system_instruction(
        current_problem_brief={
            "goal_summary": "",
            "items": [],
            "open_questions": [],
            "topic_engaged": True,
        },
        workflow_mode="agile",
        test_problem_id="vrptw",
    )
    flat = " ".join(system.split())
    assert "Hard-constraint recognition" in system
    assert "Don't fabricate a goal term" in flat
    # The three clauses added so the agent explains WHY, pushes back on
    # incomplete framings, and is permitted to clarify on cold turns.
    assert "one-sentence WHY" in flat
    assert "Push back on incomplete framings" in flat
    assert "cold-start does not block it" in flat
    # Persona-leak guard: the rule must explicitly forbid meta-framework
    # phrasing so the agent stays in programmer voice.
    assert '"this study"' in flat
    assert "programmer voice" in flat
    # VRPTW per-port hard constraint specifics also flow in via the appendix.
    assert "Every task is served exactly once" in system


def test_monitor_skips_when_cold():
    """Cold-start sessions get no monitor rows — the agent hasn't engaged
    yet, surfacing three OQs immediately would be hostile."""
    from app.routers.sessions.derivation import (
        _MONITOR_OQ_GOAL_ID,
        _MONITOR_OQ_UPLOAD_ID,
        _enforce_session_monitors,
    )

    brief = normalize_problem_brief({
        "goal_summary": "",
        "items": [],
        "open_questions": [],
        "goal_terms": {},
        # topic_engaged defaults False → cold
    })
    out = _enforce_session_monitors(brief, "agile")
    oq_ids = {str(q.get("id") or "") for q in (out.get("open_questions") or [])}
    assert _MONITOR_OQ_UPLOAD_ID not in oq_ids
    assert _MONITOR_OQ_GOAL_ID not in oq_ids
