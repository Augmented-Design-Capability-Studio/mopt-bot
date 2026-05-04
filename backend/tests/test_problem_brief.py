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


def test_normalize_promotes_answered_open_question_to_gathered():
    raw = _minimal_brief_payload(
        open_questions=[
            {"id": "q1", "text": "How many?", "status": "answered", "answer_text": "Ten."},
            {"id": "q2", "text": "Why?", "status": "open", "answer_text": None},
        ],
    )
    out = normalize_problem_brief(raw)
    texts = [q["text"] for q in out["open_questions"]]
    assert texts == ["Why?"]
    gathered_non_system = [
        i for i in out["items"] if str(i.get("kind")) == "gathered" and not str(i.get("id", "")).startswith("system")
    ]
    assert any(i.get("text") == "How many? — Ten." for i in gathered_non_system)
    assert any(i.get("id") == "item-gathered-from-question-q1" for i in gathered_non_system)


def test_gathered_oq_row_not_atomized_on_commas_and_and():
    """Promoted Q&A lines must stay one row; compound splitting would break on commas / and in the answer."""
    raw = _minimal_brief_payload(
        items=[
            {
                "id": "gathered-oq-x",
                "text": (
                    "Preferred zones? — We use A, B, and C with weight 5 for travel time and balance."
                ),
                "kind": "gathered",
                "source": "user",
                "status": "confirmed",
                "editable": True,
            }
        ],
    )
    out = normalize_problem_brief(raw)
    oq_rows = [i for i in out["items"] if str(i.get("id", "")).startswith("gathered-oq-")]
    assert len(oq_rows) == 1
    assert oq_rows[0]["text"].startswith("Preferred zones?")


def test_merge_replace_open_questions_true_without_open_questions_key_preserves():
    base = normalize_problem_brief(
        _minimal_brief_payload(
            open_questions=[{"id": "q-keep", "text": "Still open?", "status": "open", "answer_text": None}],
        )
    )
    merged = merge_problem_brief_patch(
        base,
        {"replace_editable_items": True, "replace_open_questions": True, "items": []},
    )
    assert [q["id"] for q in merged["open_questions"]] == ["q-keep"]


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


def test_merge_moves_answered_suffix_open_question_to_gathered():
    base = normalize_problem_brief(
        _minimal_brief_payload(
            open_questions=[
                {"id": "keep", "text": "Still open?", "status": "open", "answer_text": None},
            ],
        )
    )
    merged = merge_problem_brief_patch(
        base,
        {
            "open_questions": [
                "Shift limits? (Answered: 8h cap, balanced workload).",
            ],
        },
    )
    q_texts = [q["text"] for q in merged["open_questions"]]
    assert "Still open?" in q_texts
    assert not any("(answered" in q["text"].lower() for q in merged["open_questions"])
    gathered_texts = [i["text"] for i in merged["items"] if i.get("kind") == "gathered"]
    assert any("8h cap" in t for t in gathered_texts)


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


def test_cleanup_open_questions_infers_resolved_when_fact_overlap_is_high():
    brief = normalize_problem_brief(
        _minimal_brief_payload(
            goal_summary="Dispatching and overtime policy are now specified.",
            items=[
                {
                    "id": "g1",
                    "text": "Overtime policy allows up to 2 extra hours per worker.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                }
            ],
            open_questions=[
                {"id": "q1", "text": "Do we allow overtime per worker?", "status": "open", "answer_text": None},
                {"id": "q2", "text": "Which depot should serve zone B?", "status": "open", "answer_text": None},
            ],
        )
    )
    cleaned, meta = cleanup_open_questions(brief, infer_resolved=True)
    assert [q["id"] for q in cleaned["open_questions"]] == ["q2"]
    assert meta["removed_inferred"] == 1


def test_question_is_upload_related_detects_upload_prompts():
    assert question_is_upload_related({"text": "Can you upload ORDERS.csv and DRIVER_INFO.csv?"}) is True
    assert question_is_upload_related({"text": "Should we penalize late arrivals?"}) is False


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


def test_resolve_upload_open_questions_replaces_legacy_q_a_promotion():
    """Retro-fix: a brief that already has a legacy 'Question — Uploaded file(s) received: …'
    gathered row from the prior behavior should be reconciled to the canonical marker on
    the next upload turn."""
    brief = normalize_problem_brief(
        _minimal_brief_payload(
            items=[
                {
                    "id": "item-gathered-from-question-q-upload",
                    "text": (
                        "Please upload order and driver files before we proceed. — "
                        "Uploaded file(s) received: ORDERS.csv."
                    ),
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                }
            ],
            open_questions=[],
        )
    )
    updated = resolve_upload_open_questions_after_upload(brief, ["ORDERS.csv", "DRIVER_INFO.csv"])
    gathered = [item for item in updated["items"] if item.get("kind") == "gathered"]
    upload_markers = [item for item in gathered if item.get("source") == "upload"]
    assert len(upload_markers) == 1
    assert upload_markers[0]["text"] == "Source data file(s) uploaded: ORDERS.csv, DRIVER_INFO.csv."
    # Legacy Q — A row removed; only the canonical marker remains.
    assert not any(
        item["id"].startswith("item-gathered-from-question-") for item in gathered
    )


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


def test_brief_items_from_panel_include_non_default_ga_param_only():
    panel = {"problem": {"algorithm": "GA", "algorithm_params": {"pc": 0.8, "pm": 0.05}}}
    items = _brief_items_from_panel(panel)
    texts = [i["text"] for i in items]
    assert len(texts) == 1
    assert "Search strategy: GA" in texts[0]
    assert "pc=0.8" in texts[0]
    assert "iterations 100" in texts[0]
    assert "pm=0.05" not in texts[0]


def test_brief_items_from_panel_skip_keys_not_allowed_for_algorithm():
    panel = {"problem": {"algorithm": "GA", "algorithm_params": {"pc": 0.85, "w": 0.4}}}
    items = _brief_items_from_panel(panel)
    texts = [i["text"] for i in items]
    assert len(texts) == 1
    assert "pc=0.85" in texts[0]
    assert "w=0.4" not in texts[0]


def test_brief_items_from_panel_includes_greedy_init_early_stop_and_seed():
    panel = {
        "problem": {
            "algorithm": "GA",
            "algorithm_params": {"pc": 0.9, "pm": 0.05},
            "use_greedy_init": False,
            "early_stop": True,
            "early_stop_patience": 12,
            "early_stop_epsilon": 0.0002,
            "random_seed": 99,
        }
    }
    items = _brief_items_from_panel(panel)
    texts = [i["text"] for i in items]
    s = [t for t in texts if "search strategy:" in t.lower()][0]
    assert "greedy initialization off" in s.lower()
    assert "stop early on plateau on" in s.lower()
    assert "plateau patience 12" in s.lower()
    assert "min improvement epsilon" in s.lower()
    assert "random seed 99" in s.lower()


def test_normalize_goal_summary_strips_numeric_weight_details():
    raw = _minimal_brief_payload(
        goal_summary="Optimize travel time (weight 1) and keep deadline penalty 50 while using GA for 120 epochs."
    )
    out = normalize_problem_brief(raw)
    summary = out["goal_summary"]
    # Numeric annotations are stripped, but qualitative wording survives.
    assert summary  # non-empty
    assert "weight 1" not in summary
    assert "penalty 50" not in summary
    assert "120 epochs" not in summary
    # Bare English words remain (knapsack-style "weight"/"penalty" vocabulary is fine).
    assert "travel time" in summary.lower()


def test_normalize_goal_summary_preserves_knapsack_vocabulary():
    """Knapsack uses 'weight' as a domain term, not a solver config key."""
    raw = _minimal_brief_payload(
        goal_summary="Maximize total value packed into the bag without exceeding the weight capacity."
    )
    out = normalize_problem_brief(raw)
    assert out["goal_summary"]
    assert "weight" in out["goal_summary"].lower()


def test_normalize_goal_summary_drops_real_config_tokens():
    """Genuine solver-config tokens (pop_size, c1, c2, …) still get clauses dropped."""
    raw = _minimal_brief_payload(
        goal_summary="Pack high-value items into the bag; tune pop_size and c1 for stability."
    )
    out = normalize_problem_brief(raw)
    assert "pop_size" not in out["goal_summary"]
    assert "c1" not in out["goal_summary"]
    assert "Pack high-value items" in out["goal_summary"]


def test_normalize_atomizes_compound_gathered_item():
    raw = _minimal_brief_payload(
        items=[
            {
                "id": "fact-1",
                "text": "Active objectives: Total travel time (weight 1) and workload balance (weight 5).",
                "kind": "gathered",
                "source": "user",
                "status": "confirmed",
                "editable": True,
            }
        ]
    )
    out = normalize_problem_brief(raw)
    gathered = [item for item in out["items"] if item["kind"] == "gathered" and item["id"].startswith("fact-1")]
    assert len(gathered) >= 2


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


def test_locked_goal_terms_prompt_section_lists_keys():
    text = locked_goal_terms_prompt_section(
        {"problem": {"locked_goal_terms": ["lateness_penalty", "shift_limit"]}}
    )
    assert text is not None
    assert "lateness_penalty" in text
    assert "shift_limit" in text
    assert "Locked goal terms" in text


def test_locked_goal_terms_prompt_section_empty_when_none():
    assert locked_goal_terms_prompt_section({}) is None
    assert locked_goal_terms_prompt_section({"problem": {}}) is None


def test_sync_problem_brief_from_panel_reinjects_weights_after_cleanup_style_merge():
    """After cleanup, LLM rows may omit numbers; panel overlay restores canonical weight lines."""
    merged = normalize_problem_brief(
        _minimal_brief_payload(
            items=[
                {
                    "id": "g-soft",
                    "text": "We care about travel time and deadlines.",
                    "kind": "gathered",
                    "source": "agent",
                    "status": "confirmed",
                    "editable": True,
                },
            ],
        )
    )
    panel = {
        "problem": {
            "weights": {"travel_time": 7.5, "lateness_penalty": 12.0},
            "algorithm": "GA",
        }
    }
    out = sync_problem_brief_from_panel(merged, panel)
    texts = [i.get("text", "") for i in out["items"] if i.get("kind") == "gathered"]
    joined = " ".join(texts)
    assert "7.5" in joined
    assert "12" in joined
    assert "Travel time" in joined or "travel" in joined.lower()


def test_sync_problem_brief_from_panel_writes_goal_term_types_before_values():
    merged = normalize_problem_brief(_minimal_brief_payload(items=[]))
    panel = {
        "problem": {
            "weights": {
                "travel_time": 2.0,
                "capacity_penalty": 80.0,
                "shift_limit": 500.0,
                "workload_balance": 9.0,
            },
            "constraint_types": {
                "capacity_penalty": "soft",
                "shift_limit": "hard",
                "workload_balance": "custom",
            },
        }
    }
    out = sync_problem_brief_from_panel(merged, panel)
    texts = [i.get("text", "") for i in out["items"] if i.get("kind") == "gathered"]
    assert "Travel time is a primary objective term (weight 2.0)." in texts
    assert "Load capacity is a soft constraint term (weight 80.0)." in texts
    assert "Shift limit is a hard constraint term (weight 500.0)." in texts
    assert "Workload balance uses a custom locked value (weight 9.0)." in texts


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


def test_sync_problem_brief_from_panel_new_slot_defaults_to_gathered():
    """A weight that was not previously in the brief defaults to gathered/agent (current behavior)."""
    base = normalize_problem_brief(_minimal_brief_payload(items=[]))
    panel = {"problem": {"weights": {"travel_time": 2.0}}}
    out = sync_problem_brief_from_panel(base, panel)
    rows = [item for item in out["items"] if item.get("id") == "config-weight-travel_time"]
    assert len(rows) == 1
    assert rows[0]["kind"] == "gathered"
    assert rows[0]["source"] == "agent"


def test_normalize_atomizes_constraint_handling_gathered_item():
    raw = _minimal_brief_payload(
        items=[
            {
                "id": "ch-1",
                "text": (
                    "Constraint handling: Capacity violations (weight 100), "
                    "deadline/priority misses (weight 50), and 8h shift limits (hard penalty 1000)."
                ),
                "kind": "gathered",
                "source": "user",
                "status": "confirmed",
                "editable": True,
            }
        ]
    )
    out = normalize_problem_brief(raw)
    gathered = [
        item
        for item in out["items"]
        if item["kind"] == "gathered" and str(item.get("id", "")).startswith("ch-1")
    ]
    assert len(gathered) >= 3
    texts = [g["text"] for g in gathered]
    assert any(t.startswith("Constraint handling:") and "Capacity" in t for t in texts)
    assert any("deadline" in t.lower() and "miss" in t.lower() for t in texts)
    assert any("8h" in t and "shift" in t.lower() for t in texts)


def test_is_chat_cold_start_default_brief_knapsack():
    b = default_problem_brief("knapsack")
    assert is_chat_cold_start(b) is True
    b2 = {**b, "goal_summary": "Maximize value"}
    assert is_chat_cold_start(b2) is False


def test_is_chat_cold_start_gathered_makes_warm():
    b = _minimal_brief_payload(
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
    assert is_chat_cold_start(b) is False


def test_surface_problem_brief_for_chat_prompt_cold_masks():
    b = default_problem_brief("knapsack")
    surf = surface_problem_brief_for_chat_prompt(b, cold=True)
    assert surf is not b
    assert surf["backend_template"] == CHAT_PROMPT_COLD_BACKEND_TEMPLATE
    for it in surf["items"]:
        if it.get("kind") == "system":
            assert it["text"] == CHAT_PROMPT_COLD_SYSTEM_ITEM_TEXT


def test_surface_problem_brief_warm_unmodified_reference():
    b = default_problem_brief("vrptw")
    out = surface_problem_brief_for_chat_prompt(b, cold=False)
    assert out is b
