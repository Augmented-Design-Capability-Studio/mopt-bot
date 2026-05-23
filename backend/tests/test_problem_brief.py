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


def test_merge_preserves_goal_summary_when_patch_empty():
    base = normalize_problem_brief(_minimal_brief_payload(goal_summary="Old goal."))
    merged = merge_problem_brief_patch(base, {"goal_summary": ""})
    assert merged["goal_summary"] == "Old goal."


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


def test_unmodeled_request_drops_when_closest_match_becomes_active_goal_term():
    """PILOT_5 contradiction reproducer: agent logs "Capacity limit..." as
    unmodeled with closest_match=capacity_penalty, then later capacity_penalty
    is added to goal_terms (e.g. via panel save). The stale unmodeled row
    must drop so the brief doesn't simultaneously say "we don't model X"
    and "we're tuning X"."""
    base = normalize_problem_brief(
        _minimal_brief_payload(
            unmodeled_requests=[
                {
                    "user_text": "Capacity limit: trucks loaded once at depot",
                    "closest_match": "capacity_penalty",
                    "rationale": "Vehicle capacity is a structural hard constraint.",
                },
                {
                    "user_text": "Driver gossip preferences",
                    "rationale": "Out of scope — social dynamics aren't tunable.",
                },
            ],
        )
    )
    # Goal term capacity_penalty lands via a panel save.
    patch = {
        "goal_terms": {
            "capacity_penalty": {"weight": 100.0, "type": "hard", "rank": 1},
        }
    }
    out = merge_problem_brief_patch(base, patch)
    rows = out["unmodeled_requests"]
    texts = [r["user_text"] for r in rows]
    assert "Capacity limit: trucks loaded once at depot" not in texts, (
        "Stale unmodeled row must drop once capacity_penalty is in goal_terms"
    )
    # Unrelated rows (no closest_match, or closest_match not in goal_terms) survive.
    assert "Driver gossip preferences" in texts


def test_goal_key_legacy_field_names_still_deserialize():
    """Legacy briefs in the DB store anchors under ``proposes_goal_term_key``
    (on items + OQs) or ``references_goal_term_key`` (on items only). The
    normalizer must read those during the rollout and emit the unified
    ``goal_key`` field, so prior sessions don't lose their anchors when the
    new code reads them."""
    raw = _minimal_brief_payload(
        items=[
            {
                "id": "legacy-proposes",
                "text": "Capacity penalty (soft, weight 5.0) — agent suggestion.",
                "kind": "assumption",
                "source": "agent",
                "proposes_goal_term_key": "capacity_penalty",
            },
            {
                "id": "legacy-references",
                "text": "Travel time (objective, weight 1.0) — gathered.",
                "kind": "gathered",
                "source": "user",
                "references_goal_term_key": "travel_time",
            },
            {
                "id": "fresh",
                "text": "Workload balance (soft, weight 1.0) — fresh row.",
                "kind": "assumption",
                "source": "agent",
                "goal_key": "workload_balance",
            },
        ],
        open_questions=[
            {
                "id": "legacy-oq",
                "text": "Add lateness penalty?",
                "topic": "other",
                "proposes_goal_term_key": "lateness_penalty",
            }
        ],
    )
    out = normalize_problem_brief(raw)
    items_by_id = {i["id"]: i for i in out["items"]}
    assert items_by_id["legacy-proposes"]["goal_key"] == "capacity_penalty"
    assert items_by_id["legacy-references"]["goal_key"] == "travel_time"
    assert items_by_id["fresh"]["goal_key"] == "workload_balance"
    # Old field names must NOT survive — the normalizer writes only the new name.
    for item in out["items"]:
        assert "proposes_goal_term_key" not in item
        assert "references_goal_term_key" not in item
    oq = out["open_questions"][0]
    assert oq["goal_key"] == "lateness_penalty"
    assert "proposes_goal_term_key" not in oq


def test_referenced_goal_term_text_rerendered_live():
    """PILOT_5 reproducer: LLM emits an assumption item describing
    travel_time with weight 15 in the text — but live weight is 20. With
    ``goal_key`` set, the normalizer re-renders the
    parenthesized middle from live ``goal_terms`` state, preserving the
    LLM's label phrasing and rationale."""
    raw = _minimal_brief_payload(
        items=[
            {
                "id": "assumption-rebalance-travel-time",
                "text": "Travel time efficiency (custom locked, weight 15.0) — adjusting slightly to balance against punctuality.",
                "kind": "assumption",
                "source": "agent",
                "goal_key": "travel_time",
            },
        ],
        goal_terms={
            "travel_time": {"weight": 20.0, "type": "custom", "rank": 1},
        },
    )
    out = normalize_problem_brief(raw)
    item = next(i for i in out["items"] if i["id"] == "assumption-rebalance-travel-time")
    assert "weight 20" in item["text"], item["text"]
    assert "weight 15" not in item["text"], item["text"]
    # Label and rationale preserved.
    assert item["text"].startswith("Travel time efficiency ("), item["text"]
    assert "adjusting slightly to balance against punctuality" in item["text"]


def test_referenced_goal_term_text_no_op_when_key_missing():
    """If the referenced key isn't in goal_terms (LLM proposing something
    not yet committed), leave text alone — don't strip information."""
    raw = _minimal_brief_payload(
        items=[
            {
                "id": "assumption-future-shift-limit",
                "text": "Max shift hours (custom locked, weight 5.0) — proposed.",
                "kind": "assumption",
                "source": "agent",
                "goal_key": "shift_limit",
            },
        ],
        goal_terms={},
    )
    out = normalize_problem_brief(raw)
    item = next(i for i in out["items"] if i["id"] == "assumption-future-shift-limit")
    assert "weight 5" in item["text"]


def test_referenced_goal_term_text_skips_non_canonical_shape():
    """Free-form item text that doesn't follow ``<Label> (<role>, weight N)
    — <rationale>`` is left untouched. Partial parsing would be fragile."""
    raw = _minimal_brief_payload(
        items=[
            {
                "id": "assumption-prose",
                "text": "The solver hit a plateau on travel_time tuning.",
                "kind": "assumption",
                "source": "agent",
                "goal_key": "travel_time",
            },
        ],
        goal_terms={
            "travel_time": {"weight": 20.0, "type": "custom", "rank": 1},
        },
    )
    out = normalize_problem_brief(raw)
    item = next(i for i in out["items"] if i["id"] == "assumption-prose")
    assert item["text"] == "The solver hit a plateau on travel_time tuning."


def test_normalize_drops_legacy_run_summary_string_silently():
    """Legacy briefs in the DB store a ``run_summary`` rolling string. The
    structured ``runs`` array replaces it; normalize must silently drop the
    string field without crashing. Canonical run data lives in the
    OptimizationRun table, so no migration of the string is required —
    ``consolidate_runs`` refills ``brief.runs`` from there on the next
    run-acknowledgement turn."""
    raw = _minimal_brief_payload(
        run_summary="Run #3 cost 1500, 2 violations.",
    )
    out = normalize_problem_brief(raw)
    assert "run_summary" not in out
    assert out["runs"] == []


def test_normalize_coerces_runs_with_dedup_and_sort():
    """``runs`` is server-written but ``normalize_problem_brief`` runs every
    read (snapshots, PATCH round-trips). Defensive coercion: drop entries
    missing a usable ``run_number``, de-dup duplicates by ``run_number``
    (keep the most recent occurrence), and sort by ``run_number``."""
    raw = _minimal_brief_payload(
        runs=[
            # Out-of-order, duplicate run #2 (second one wins), and a junk row.
            {"run_number": 2, "cost": 100.0, "ok": True, "algorithm": "GA",
             "violations_summary": "", "delta_from_prev": ""},
            {"junk": True},
            {"run_number": 1, "cost": 200.0, "ok": False, "algorithm": "PSO",
             "violations_summary": "5 over capacity", "delta_from_prev": ""},
            {"run_number": 2, "cost": 99.0, "ok": True, "algorithm": "GA",
             "violations_summary": "", "delta_from_prev": "−1.00 cost vs Run #1"},
        ],
    )
    out = normalize_problem_brief(raw)
    assert [r["run_number"] for r in out["runs"]] == [1, 2]
    # The later #2 entry wins.
    assert out["runs"][1]["cost"] == 99.0
    assert out["runs"][1]["delta_from_prev"] == "−1.00 cost vs Run #1"


def test_consolidate_runs_appends_entry_on_run_ack():
    """On a run-acknowledgement turn, ``consolidate_runs`` builds a structured
    entry from ``recent_runs_summary[-1]`` and appends it to ``brief.runs``."""
    from app.routers.sessions.derivation import consolidate_runs

    base = normalize_problem_brief(_minimal_brief_payload())
    recent = [{
        "run_id": 42,
        "run_number": 1,
        "ok": True,
        "cost": 353.98,
        "algorithm": "GA",
        "violations": None,
    }]
    out, meta = consolidate_runs(
        base,
        recent_runs_summary=recent,
        is_run_acknowledgement=True,
        test_problem_id="vrptw",
    )
    assert meta["appended"] == 1
    assert len(out["runs"]) == 1
    entry = out["runs"][0]
    assert entry["run_number"] == 1
    assert entry["cost"] == 353.98
    assert entry["algorithm"] == "GA"
    assert entry["delta_from_prev"] == ""  # No previous run to compare against.


def test_consolidate_runs_computes_delta_from_prev():
    """Second run-ack: the entry's ``delta_from_prev`` carries the cost diff
    versus the previous structured entry. Deterministic arithmetic, no LLM."""
    from app.routers.sessions.derivation import consolidate_runs

    brief = normalize_problem_brief(_minimal_brief_payload(
        runs=[{
            "run_number": 1, "cost": 500.0, "ok": True, "algorithm": "GA",
            "violations_summary": "", "delta_from_prev": "",
        }],
    ))
    recent = [{
        "run_id": 99,
        "run_number": 2,
        "ok": True,
        "cost": 350.0,
        "algorithm": "GA",
        "violations": None,
    }]
    out, _ = consolidate_runs(
        brief, recent_runs_summary=recent, is_run_acknowledgement=True,
        test_problem_id="vrptw",
    )
    assert len(out["runs"]) == 2
    assert out["runs"][1]["delta_from_prev"] == "−150.00 cost vs Run #1"


def test_consolidate_runs_idempotent_on_same_run_number():
    """Resume/retry paths can call ``consolidate_runs`` twice for the same
    run. The second call replaces the entry in place (no duplicate row)."""
    from app.routers.sessions.derivation import consolidate_runs

    brief = normalize_problem_brief(_minimal_brief_payload())
    recent = [{
        "run_id": 7, "run_number": 1, "ok": True, "cost": 100.0,
        "algorithm": "GA", "violations": None,
    }]
    out_a, _ = consolidate_runs(
        brief, recent_runs_summary=recent, is_run_acknowledgement=True,
        test_problem_id="vrptw",
    )
    out_b, _ = consolidate_runs(
        out_a, recent_runs_summary=recent, is_run_acknowledgement=True,
        test_problem_id="vrptw",
    )
    assert len(out_b["runs"]) == 1


def test_consolidate_runs_noop_when_not_run_ack():
    """Non-run-ack turns must not touch ``brief.runs`` (no false appends from
    chat / config_edit_ack / brief_edit_ack flavors)."""
    from app.routers.sessions.derivation import consolidate_runs

    brief = normalize_problem_brief(_minimal_brief_payload())
    recent = [{
        "run_id": 7, "run_number": 1, "ok": True, "cost": 100.0,
        "algorithm": "GA", "violations": None,
    }]
    out, meta = consolidate_runs(
        brief, recent_runs_summary=recent, is_run_acknowledgement=False,
        test_problem_id="vrptw",
    )
    assert meta["appended"] == 0
    assert out["runs"] == []


def test_priority_line_renders_from_ranks():
    """``priority_line`` is server-managed — recomputed from
    ``goal_terms[K].rank`` on every normalize pass and ignored if the LLM
    tries to emit a value."""
    raw = _minimal_brief_payload(
        goal_terms={
            "lateness_penalty": {"weight": 5.0, "type": "soft", "rank": 2},
            "travel_time": {"weight": 10.0, "type": "objective", "rank": 1},
            "capacity_penalty": {"weight": 100.0, "type": "hard", "rank": 3},
        },
        # LLM tries to emit a bogus priority line — must be overwritten.
        priority_line="Priority order: 1) gossip, 2) magic, 3) vibes.",
    )
    out = normalize_problem_brief(raw)
    assert out["priority_line"] == (
        "Priority order: 1) travel_time, 2) lateness_penalty, 3) capacity_penalty."
    )


def test_priority_line_empty_when_no_ranks():
    """Brief with no ranked goal terms → empty priority line (frontend hides
    the section). No spurious "Priority order: ." rendering."""
    raw = _minimal_brief_payload(goal_terms={})
    out = normalize_problem_brief(raw)
    assert out["priority_line"] == ""


def test_normalize_drops_unmodeled_rows_resolved_by_existing_goal_terms():
    """Even without a fresh patch, normalize_problem_brief cleans up stale
    unmodeled rows whose closest_match is already in goal_terms — fixes
    sessions where the contradiction predates the fix."""
    raw = _minimal_brief_payload(
        goal_terms={
            "travel_time": {"weight": 1.0, "type": "objective", "rank": 1},
        },
        unmodeled_requests=[
            {
                "user_text": "Traffic during peak",
                "closest_match": "travel_time",
                "rationale": "Covered by travel_time via traffic profile.",
            },
        ],
    )
    out = normalize_problem_brief(raw)
    assert out["unmodeled_requests"] == []


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
    """`replace_goal_terms=true` only takes effect on cleanup turns
    (paired with `cleanup_mode=true`). Outside cleanup, the merge falls
    back to deep-merge so an incomplete LLM patch can't silently wipe
    committed terms like ``travel_time``. See the 26f4-session bug:
    LLM set the replace flag mid-conversation while emitting only
    ``search_strategy``, dropping ``travel_time`` and leaving
    ``goal_summary`` / synthesized items[] referencing a term the
    panel no longer had.
    """
    base = normalize_problem_brief(
        _minimal_brief_payload(
            goal_terms={
                "travel_time": {"weight": 5.0, "type": "objective"},
                "worker_preference": {"weight": 1.0, "type": "soft"},
            },
        )
    )
    # Without cleanup_mode: replace flag is ignored, deep-merge runs.
    merged_no_cleanup = merge_problem_brief_patch(
        base,
        {
            "replace_goal_terms": True,
            "goal_terms": {
                "lateness_penalty": {"weight": 7.0, "type": "objective"},
            },
        },
    )
    assert set(merged_no_cleanup["goal_terms"].keys()) == {
        "travel_time",
        "worker_preference",
        "lateness_penalty",
    }
    # With cleanup_mode=true: replace honored, full map swapped.
    merged_cleanup = merge_problem_brief_patch(
        base,
        {
            "cleanup_mode": True,
            "replace_goal_terms": True,
            "goal_terms": {
                "lateness_penalty": {"weight": 7.0, "type": "objective"},
            },
        },
    )
    assert set(merged_cleanup["goal_terms"].keys()) == {"lateness_penalty"}


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


def test_sync_problem_brief_from_panel_user_origin_tags_config_rows_source_user():
    """User-triggered panel save → synthesized config-weight-K rows must
    carry ``source: "user"`` (not "agent"). LLM-triggered re-derivations
    keep the default ``source: "agent"``."""
    base = default_problem_brief("vrptw")
    panel = {
        "problem": {
            "goal_terms": {
                "travel_time": {"weight": 1.0, "type": "objective", "rank": 1},
                "capacity_penalty": {"weight": 100.0, "type": "hard", "rank": 2},
            }
        }
    }
    out_user = sync_problem_brief_from_panel(
        base, panel, test_problem_id="vrptw", origin="user"
    )
    config_rows_user = [i for i in out_user["items"] if i["id"].startswith("config-weight-")]
    assert config_rows_user, "Expected config-weight-* rows from panel sync"
    assert all(i["source"] == "user" for i in config_rows_user)

    out_agent = sync_problem_brief_from_panel(
        base, panel, test_problem_id="vrptw"
    )  # default origin="agent"
    config_rows_agent = [i for i in out_agent["items"] if i["id"].startswith("config-weight-")]
    assert all(i["source"] == "agent" for i in config_rows_agent)


def test_sync_problem_brief_from_panel_promotes_assumption_on_type_change():
    """User changing ``type`` (soft → hard) for K is a structural lock-in →
    prior assumption row about K is promoted to ``gathered / source: user``."""
    base = normalize_problem_brief({
        "goal_summary": "",
        "items": [
            {
                "id": "assumption-capacity-soft-default",
                "text": "Capacity penalty (soft constraint, weight 100.0) — keep loads safe.",
                "kind": "assumption",
                "source": "agent",
                "goal_key": "capacity_penalty",
            },
        ],
        "open_questions": [],
        "goal_terms": {
            "capacity_penalty": {"weight": 100.0, "type": "soft", "rank": 1},
        },
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    })
    # User flips type to hard via panel.
    panel = {
        "problem": {
            "goal_terms": {
                "capacity_penalty": {"weight": 100.0, "type": "hard", "rank": 1},
            }
        }
    }
    out = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw", origin="user")
    promoted = next(i for i in out["items"] if i["id"] == "assumption-capacity-soft-default")
    assert promoted["kind"] == "gathered"
    assert promoted["source"] == "user"


def test_sync_problem_brief_from_panel_does_not_promote_on_weight_only_change():
    """Weight tuning isn't a lock-in signal — prior assumption rows survive
    as-is. The user is exploring values, not committing to framing."""
    base = normalize_problem_brief({
        "goal_summary": "",
        "items": [
            {
                "id": "assumption-cap-tune",
                "text": "Capacity penalty (soft constraint, weight 100.0) — tuning.",
                "kind": "assumption",
                "source": "agent",
                "goal_key": "capacity_penalty",
            },
        ],
        "open_questions": [],
        "goal_terms": {
            "capacity_penalty": {"weight": 100.0, "type": "soft", "rank": 1},
        },
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    })
    # User changes weight only.
    panel = {
        "problem": {
            "goal_terms": {
                "capacity_penalty": {"weight": 50.0, "type": "soft", "rank": 1},
            }
        }
    }
    out = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw", origin="user")
    unchanged = next(i for i in out["items"] if i["id"] == "assumption-cap-tune")
    assert unchanged["kind"] == "assumption"
    assert unchanged["source"] == "agent"


def test_sync_problem_brief_from_panel_does_not_promote_on_rank_cascade():
    """Reordering ranks cascade: moving one term shifts ranks for others.
    Per Fix 8 rule, we can't tell which key the user actively moved from
    the diff alone, so no prior assumption rows are promoted."""
    base = normalize_problem_brief({
        "goal_summary": "",
        "items": [
            {
                "id": "assumption-travel-pref",
                "text": "Travel time (primary objective, weight 1.0) — agent suggestion.",
                "kind": "assumption",
                "source": "agent",
                "goal_key": "travel_time",
            },
            {
                "id": "assumption-cap-pref",
                "text": "Capacity penalty (soft constraint, weight 5.0) — agent suggestion.",
                "kind": "assumption",
                "source": "agent",
                "goal_key": "capacity_penalty",
            },
        ],
        "open_questions": [],
        "goal_terms": {
            "travel_time": {"weight": 1.0, "type": "objective", "rank": 1},
            "capacity_penalty": {"weight": 5.0, "type": "soft", "rank": 2},
        },
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    })
    # User reorders (swap ranks). No weight/type changes.
    panel = {
        "problem": {
            "goal_terms": {
                "travel_time": {"weight": 1.0, "type": "objective", "rank": 2},
                "capacity_penalty": {"weight": 5.0, "type": "soft", "rank": 1},
            }
        }
    }
    out = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw", origin="user")
    travel_item = next(i for i in out["items"] if i["id"] == "assumption-travel-pref")
    cap_item = next(i for i in out["items"] if i["id"] == "assumption-cap-pref")
    assert travel_item["kind"] == "assumption", "rank cascade must NOT promote"
    assert cap_item["kind"] == "assumption", "rank cascade must NOT promote"


def test_sync_problem_brief_from_panel_promotes_on_newly_added_key():
    """User adds a brand-new goal_term via panel → user took the suggestion.
    Prior assumption row about K is promoted."""
    base = normalize_problem_brief({
        "goal_summary": "",
        "items": [
            {
                "id": "assumption-add-lateness",
                "text": "Lateness penalty (soft constraint, weight 10.0) — proposed.",
                "kind": "assumption",
                "source": "agent",
                "goal_key": "lateness_penalty",
            },
        ],
        "open_questions": [],
        "goal_terms": {},
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    })
    panel = {
        "problem": {
            "goal_terms": {
                "lateness_penalty": {"weight": 10.0, "type": "soft", "rank": 1},
            }
        }
    }
    out = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw", origin="user")
    promoted = next(i for i in out["items"] if i["id"] == "assumption-add-lateness")
    assert promoted["kind"] == "gathered"
    assert promoted["source"] == "user"


def test_sync_problem_brief_from_panel_agent_origin_does_not_promote():
    """LLM-driven re-derivation (origin=agent) must NEVER promote prior
    assumption rows — the user wasn't involved."""
    base = normalize_problem_brief({
        "goal_summary": "",
        "items": [
            {
                "id": "assumption-cap-pref",
                "text": "Capacity penalty (soft constraint, weight 100.0) — agent.",
                "kind": "assumption",
                "source": "agent",
                "goal_key": "capacity_penalty",
            },
        ],
        "open_questions": [],
        "goal_terms": {
            "capacity_penalty": {"weight": 100.0, "type": "soft", "rank": 1},
        },
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    })
    panel = {
        "problem": {
            "goal_terms": {
                "capacity_penalty": {"weight": 100.0, "type": "hard", "rank": 1},
            }
        }
    }
    # Even though type changed, origin=agent → no promotion.
    out = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw")
    unchanged = next(i for i in out["items"] if i["id"] == "assumption-cap-pref")
    assert unchanged["kind"] == "assumption"


def test_sync_problem_brief_from_panel_preserves_search_strategy_carrier():
    """``search_strategy`` lives only in the brief — the panel never carries it.
    A user panel save must not drop the brief's ``goal_terms.search_strategy``
    entry even though the panel's ``goal_terms`` map omits it. Lock-in for the
    PILOT_5 wipe (snap 293→294)."""
    base = default_problem_brief("vrptw")
    base["goal_terms"] = {
        "search_strategy": {
            "weight": 1.0,
            "type": "custom",
            "rank": 2,
            "evidence_item_ids": ["item-search-strategy"],
            "properties": {"algorithm": "GA"},
        },
        "travel_time": {
            "weight": 1.0,
            "type": "objective",
            "rank": 1,
        },
    }
    # Panel save adds a new term (capacity_penalty) — the panel's goal_terms
    # never includes search_strategy. Pre-fix, this overwrite dropped it.
    panel = {
        "problem": {
            "goal_terms": {
                "travel_time": {"weight": 1.0, "type": "objective", "rank": 1},
                "capacity_penalty": {"weight": 100.0, "type": "hard", "rank": 4},
            }
        }
    }
    out = sync_problem_brief_from_panel(base, panel, test_problem_id="vrptw")
    assert "search_strategy" in out["goal_terms"], (
        "search_strategy must survive panel→brief sync (carrier-only key)"
    )
    assert out["goal_terms"]["search_strategy"]["properties"]["algorithm"] == "GA"
    # Other panel-side terms still mirror correctly.
    assert "capacity_penalty" in out["goal_terms"]
    assert "travel_time" in out["goal_terms"]


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
        workflow_mode="agile",
        recent_runs_summary=[],
        test_problem_id="vrptw",
        user_text="I want to minimize travel time please",
    )
    assert "travel_time" in (out.get("goal_terms") or {}), out


def test_apply_brief_patch_seeds_goal_terms_from_extraction(monkeypatch):
    """When the LLM brief patch lands goal_summary but no goal_terms on a
    cold start, the canonical-concept extractor seeds the missing keys
    and the synthesizer renders the matching config-weight-<key> rows."""
    from app.routers.sessions import derivation
    from app.routers.sessions.derivation import apply_brief_patch_with_cleanup

    captured: dict[str, object] = {}

    def _fake_extract(*, merged_brief, user_text, api_key, model_name, test_problem_id):
        captured["called"] = True
        captured["user_text"] = user_text
        captured["test_problem_id"] = test_problem_id
        return {
            "value_emphasis": {
                "weight": 1.0,
                "type": "objective",
                "rank": 1,
                "ambiguity_note": {"chosen_rationale": "User asked to maximize value."},
            },
            "capacity_overflow": {
                "weight": 40.0,
                "type": "soft",
                "rank": 2,
                "ambiguity_note": {
                    "chosen_rationale": "User asked to stay under the capacity limit."
                },
            },
        }

    monkeypatch.setattr(
        "app.services.goal_term_extraction.extract_canonical_goal_terms",
        _fake_extract,
    )

    base = default_problem_brief("knapsack")
    patch_payload = {
        "goal_summary": "Maximize total value without exceeding capacity.",
        "items": [
            {
                "id": "item-001",
                "text": "Knapsack capacity is set to 50 units.",
                "kind": "gathered",
                "source": "user",
            },
        ],
    }
    out, _meta = apply_brief_patch_with_cleanup(
        base_problem_brief=base,
        patch_payload=patch_payload,
        workflow_mode="waterfall",
        recent_runs_summary=[],
        test_problem_id="knapsack",
        user_text="I want to maximize the value without exceeding capacity.",
        api_key="test-key",
        model_name="test-model",
    )
    assert captured.get("called") is True
    out_keys = set((out.get("goal_terms") or {}).keys())
    assert "value_emphasis" in out_keys, out_keys
    assert "capacity_overflow" in out_keys, out_keys
    # Canonical config-weight rows synthesized from the seeded goal_terms.
    item_ids = {it.get("id") for it in out.get("items") or [] if isinstance(it, dict)}
    assert "config-weight-value_emphasis" in item_ids, item_ids
    assert "config-weight-capacity_overflow" in item_ids, item_ids
    # Monitor must NOT fire the goal-term OQ now that goal_terms is non-empty.
    oq_ids = {q.get("id") for q in out.get("open_questions") or [] if isinstance(q, dict)}
    assert "oq-monitor-goal" not in oq_ids, oq_ids


def test_apply_brief_patch_skips_extractor_when_goal_terms_already_set(monkeypatch):
    """The extractor is gated on cold start — once any goal_term is in
    base.goal_terms, it never fires, so retired keys aren't resurrected."""
    from app.routers.sessions.derivation import apply_brief_patch_with_cleanup

    def _fake_extract(**kwargs):
        raise AssertionError("Extractor must not run when base.goal_terms is non-empty")

    monkeypatch.setattr(
        "app.services.goal_term_extraction.extract_canonical_goal_terms",
        _fake_extract,
    )

    base = default_problem_brief("knapsack")
    base["goal_terms"] = {
        "value_emphasis": {"weight": 1.0, "type": "objective", "rank": 1}
    }
    apply_brief_patch_with_cleanup(
        base_problem_brief=base,
        patch_payload={"goal_summary": "Still maximizing value."},
        workflow_mode="agile",
        recent_runs_summary=[],
        test_problem_id="knapsack",
        user_text="keep maximizing value",
        api_key="test-key",
        model_name="test-model",
    )


def test_apply_brief_patch_runack_strip_waterfall_drops_new_oqs():
    """Tutorial Runs 1+2 in waterfall: a post-run patch trying to add new
    open_questions is stripped server-side. Existing OQs survive."""
    from app.routers.sessions.derivation import apply_brief_patch_with_cleanup

    base = default_problem_brief("knapsack")
    base["open_questions"] = [
        {
            "id": "oq-existing",
            "text": "Pre-existing question to keep.",
            "status": "open",
            "answer_text": None,
            "topic": "other",
        }
    ]
    base["items"] = [
        {
            "id": "item-001",
            "text": "Knapsack capacity is set to 50 units.",
            "kind": "gathered",
            "source": "user",
        }
    ]
    base["goal_terms"] = {
        "value_emphasis": {"weight": 1.0, "type": "objective", "rank": 1},
        "capacity_overflow": {"weight": 40.0, "type": "soft", "rank": 2},
    }
    patch_payload = {
        "open_questions": [
            {
                "id": "oq-existing",
                "text": "Pre-existing question to keep.",
                "status": "open",
                "answer_text": None,
                "topic": "other",
            },
            {
                "id": "oq-refine-capacity",
                "text": "Should I bump capacity penalty?",
                "status": "open",
                "answer_text": None,
                "topic": "other",
            },
        ],
        "replace_open_questions": True,
    }
    out, _meta = apply_brief_patch_with_cleanup(
        base_problem_brief=base,
        patch_payload=patch_payload,
        workflow_mode="waterfall",
        recent_runs_summary=[],
        test_problem_id="knapsack",
        user_text="Run #1 just completed - cost -55.78...",
        is_run_acknowledgement=True,
        suppress_runack_invariant=True,
    )
    oq_ids = {q.get("id") for q in out.get("open_questions") or [] if isinstance(q, dict)}
    assert "oq-existing" in oq_ids, oq_ids
    assert "oq-refine-capacity" not in oq_ids, oq_ids


def test_apply_brief_patch_runack_strip_agile_drops_new_assumptions_and_goal_terms():
    """Tutorial Runs 1+2 in agile: a post-run patch trying to add new
    assumption rows or new goal_terms keys is stripped server-side.
    Existing assumption edits + retunes survive."""
    from app.routers.sessions.derivation import apply_brief_patch_with_cleanup

    base = default_problem_brief("knapsack")
    base["items"] = [
        {
            "id": "item-existing-assumption",
            "text": "Existing assumption row.",
            "kind": "assumption",
            "source": "agent",
        }
    ]
    base["goal_terms"] = {
        "value_emphasis": {"weight": 1.0, "type": "objective", "rank": 1},
    }
    patch_payload = {
        "items": [
            # Existing assumption: should survive
            {
                "id": "item-existing-assumption",
                "text": "Existing assumption row, refined.",
                "kind": "assumption",
                "source": "agent",
            },
            # NEW assumption: should be stripped
            {
                "id": "item-new-assumption",
                "text": "Lateness penalty seems worth trying next.",
                "kind": "assumption",
                "source": "agent",
            },
        ],
        "goal_terms": {
            # Existing goal-term update: should survive
            "value_emphasis": {"weight": 2.0, "type": "objective", "rank": 1},
            # NEW goal-term: should be stripped
            "selection_sparsity": {"weight": 0.5, "type": "soft", "rank": 2},
        },
    }
    out, _meta = apply_brief_patch_with_cleanup(
        base_problem_brief=base,
        patch_payload=patch_payload,
        workflow_mode="agile",
        recent_runs_summary=[],
        test_problem_id="knapsack",
        user_text="Run #1 just completed - cost -55.78...",
        is_run_acknowledgement=True,
        suppress_runack_invariant=True,
    )
    item_ids = {it.get("id") for it in out.get("items") or [] if isinstance(it, dict)}
    assert "item-existing-assumption" in item_ids, item_ids
    assert "item-new-assumption" not in item_ids, item_ids
    gt = out.get("goal_terms") or {}
    assert "value_emphasis" in gt, gt
    # New goal_terms keys stripped:
    assert "selection_sparsity" not in gt, gt
    # The retune of value_emphasis weight came through:
    assert gt["value_emphasis"]["weight"] == 2.0, gt


def test_apply_brief_patch_runack_strip_off_lets_new_entries_through():
    """When suppress_runack_invariant=False (default — Run 3+ or non-tutorial),
    the strip doesn't fire and new OQs/assumptions pass through normally."""
    from app.routers.sessions.derivation import apply_brief_patch_with_cleanup

    base = default_problem_brief("knapsack")
    base["goal_terms"] = {
        "value_emphasis": {"weight": 1.0, "type": "objective", "rank": 1},
    }
    patch_payload = {
        "open_questions": [
            {
                "id": "oq-new",
                "text": "Want to bump the penalty?",
                "status": "open",
                "answer_text": None,
                "topic": "other",
            }
        ],
        "replace_open_questions": True,
    }
    out, _meta = apply_brief_patch_with_cleanup(
        base_problem_brief=base,
        patch_payload=patch_payload,
        workflow_mode="waterfall",
        recent_runs_summary=[],
        test_problem_id="knapsack",
        user_text="Run #3 just completed.",
        is_run_acknowledgement=True,
        suppress_runack_invariant=False,
    )
    oq_ids = {q.get("id") for q in out.get("open_questions") or [] if isinstance(q, dict)}
    assert "oq-new" in oq_ids, oq_ids


def test_apply_brief_patch_strips_non_vocab_goal_term_keys():
    """LLM-hallucinated goal_term keys (e.g. ``total_value`` paraphrasing
    ``value_emphasis`` for knapsack) must be stripped before they reach the
    anchor filter or panel-derive — otherwise S5 reports ``missing_in_panel``
    drift in a loop on every retry."""
    from app.routers.sessions.derivation import apply_brief_patch_with_cleanup

    base = default_problem_brief("knapsack")
    patch_payload = {
        "items": [
            {
                "id": "item-user-1",
                "text": "Maximize total packed value.",
                "kind": "gathered",
                "source": "user",
            }
        ],
        "goal_terms": {
            # Real knapsack key — should survive.
            "value_emphasis": {
                "weight": 1.0,
                "type": "objective",
                "evidence_item_ids": ["item-user-1"],
            },
            # Hallucinated paraphrase — must be stripped.
            "total_value": {
                "weight": 1.0,
                "type": "objective",
                "evidence_item_ids": ["item-user-1"],
            },
            # Another hallucination.
            "efficient_packing": {
                "weight": 1.0,
                "type": "soft",
                "evidence_item_ids": ["item-user-1"],
            },
        },
    }
    out, _meta = apply_brief_patch_with_cleanup(
        base_problem_brief=base,
        patch_payload=patch_payload,
        workflow_mode="agile",
        recent_runs_summary=[],
        test_problem_id="knapsack",
        user_text="Maximize total packed value.",
    )
    out_keys = set((out.get("goal_terms") or {}).keys())
    assert "value_emphasis" in out_keys, out_keys
    assert "total_value" not in out_keys, out_keys
    assert "efficient_packing" not in out_keys, out_keys


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
