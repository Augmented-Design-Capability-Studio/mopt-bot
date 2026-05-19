"""Deterministic brief-merge helpers used by the chat pipeline apply stage."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ChatMessage, StudySession
from app.problem_brief import (
    merge_problem_brief_patch,
    normalize_problem_brief,
)

from . import helpers

log = logging.getLogger(__name__)
_RUN_BOOKKEEPING_TEXT_SNIPPETS: tuple[str, ...] = (
    "run #",
    "just completed",
    "finished run",
    "previous run",
    "latest run",
    "this run",
    "after this run",
    "upload file",
    "uploaded file",
)


def _is_run_related_text(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if any(snippet in lowered for snippet in _RUN_BOOKKEEPING_TEXT_SNIPPETS):
        return True
    return False


def _format_run_context_line(run: dict[str, Any], test_problem_id: str | None = None) -> str:
    run_number = run.get("run_number")
    algorithm = str(run.get("algorithm") or "").strip()
    cost = run.get("cost")
    ok = bool(run.get("ok"))
    status = "succeeded" if ok else "failed"
    details: list[str] = [f"Run #{run_number}" if run_number else "Latest run", status]
    if isinstance(cost, (int, float)):
        details.append(f"cost {cost:.2f}")
    if algorithm:
        details.append(f"algorithm {algorithm}")
    violations = run.get("violations")
    if isinstance(violations, dict) and test_problem_id is not None:
        try:
            from app.problems.registry import get_study_port

            extras = get_study_port(test_problem_id).format_run_context_violation_details(
                violations
            )
        except Exception:  # pragma: no cover — defensive
            extras = []
        for line in extras:
            if isinstance(line, str) and line.strip():
                details.append(line.strip())
    return ", ".join(details) + "."


def consolidate_run_summary(
    brief: dict[str, Any],
    *,
    recent_runs_summary: list[dict[str, Any]] | None = None,
    cleanup_mode: bool = False,
    is_run_acknowledgement: bool = False,
    test_problem_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """
    Maintain a single rolling run summary. On cleanup, migrate run-related noisy rows/questions
    into this summary and remove them from their sections.
    """
    normalized = normalize_problem_brief(brief)
    existing = str(normalized.get("run_summary") or "").strip()
    moved_items = 0
    moved_questions = 0
    notes: list[str] = []
    items = list(normalized.get("items") or [])
    questions = list(normalized.get("open_questions") or [])

    if cleanup_mode:
        kept_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip().lower()
            text = str(item.get("text") or "").strip()
            if kind in {"gathered", "assumption"} and _is_run_related_text(text):
                moved_items += 1
                if text:
                    notes.append(text)
                continue
            kept_items.append(item)
        items = kept_items

        kept_questions: list[dict[str, Any]] = []
        for question in questions:
            if not isinstance(question, dict):
                continue
            text = str(question.get("text") or "").strip()
            if _is_run_related_text(text):
                moved_questions += 1
                if text:
                    notes.append(text)
                continue
            kept_questions.append(question)
        questions = kept_questions

    recent_line = ""
    if recent_runs_summary:
        latest = recent_runs_summary[-1]
        if isinstance(latest, dict):
            recent_line = _format_run_context_line(latest, test_problem_id=test_problem_id).strip()
    parts: list[str] = []
    if existing:
        parts.append(existing)
    if recent_line and (is_run_acknowledgement or cleanup_mode):
        parts.append(recent_line)
    if notes and cleanup_mode:
        unique = list(dict.fromkeys(n for n in notes if n.strip()))
        if unique:
            parts.append(f"Cleanup consolidated run notes: {'; '.join(unique[:2])}.")

    next_summary = " ".join(parts).strip()
    if next_summary:
        next_summary = next_summary[-420:]
        if next_summary[0].islower():
            next_summary = next_summary[0].upper() + next_summary[1:]
        if next_summary[-1] not in ".!?":
            next_summary += "."

    updated = {
        **normalized,
        "items": items,
        "open_questions": questions,
        "run_summary": next_summary,
    }
    return normalize_problem_brief(updated), {"moved_items": moved_items, "moved_questions": moved_questions}


def _apply_assumption_actions(
    brief: dict[str, Any], actions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Apply per-row assumption decisions returned by the maintenance LLM.

    Each action carries a target ``id`` and one of:
    - ``keep``: no-op.
    - ``rephrase``: update only ``text``; preserve kind/source.
    - ``drop``: remove the items[] row.
    - ``promote_to_gathered``: lock the row in. Sets ``kind="gathered"`` and
      ``source="user"`` because the user originated the lock-in (see
      ``feedback_provenance_origin_not_phrasing``). ``rephrased_text``
      becomes the new ``text``.

    Unknown ids and unknown actions are ignored. The caller re-runs
    ``coerce_problem_brief_for_workflow`` after this so any residual
    workflow invariants still hold.
    """
    if not actions:
        return brief
    items = list(brief.get("items") or [])
    items_by_id: dict[str, int] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if item_id:
            items_by_id[item_id] = index

    drop_ids: set[str] = set()
    for raw_action in actions:
        if not isinstance(raw_action, dict):
            continue
        item_id = str(raw_action.get("id") or "").strip()
        action = str(raw_action.get("action") or "").strip().lower()
        if not item_id or action not in {
            "keep",
            "rephrase",
            "drop",
            "promote_to_gathered",
        }:
            continue
        if item_id not in items_by_id:
            # Stale id (the row was already replaced or removed by an earlier
            # step in this turn). Silently skip.
            continue
        idx = items_by_id[item_id]
        target = items[idx]
        if not isinstance(target, dict):
            continue
        # Only act on rows that are actually assumption rows. If the LLM
        # tries to mutate a gathered row, ignore the action — gathered
        # rows have their own lifecycle (chat-side correction or
        # cleanup pass).
        if str(target.get("kind") or "").strip().lower() != "assumption":
            continue
        if action == "keep":
            continue
        if action == "drop":
            drop_ids.add(item_id)
            continue
        rephrased = str(raw_action.get("rephrased_text") or "").strip()
        if action == "rephrase":
            if not rephrased:
                continue  # nothing to apply
            new_item = dict(target)
            new_item["text"] = rephrased
            items[idx] = new_item
            continue
        if action == "promote_to_gathered":
            if not rephrased:
                # Promotion without rephrased_text — fall back to the
                # current text. The kind/source flip is the load-bearing
                # piece; the wording can stay.
                rephrased = str(target.get("text") or "").strip()
            new_item = dict(target)
            new_item["kind"] = "gathered"
            new_item["source"] = "user"
            if rephrased:
                new_item["text"] = rephrased
            items[idx] = new_item

    if drop_ids:
        items = [
            item
            for item in items
            if not (
                isinstance(item, dict)
                and str(item.get("id") or "").strip() in drop_ids
            )
        ]

    return {**brief, "items": items}


def apply_brief_patch_with_cleanup(
    *,
    base_problem_brief: dict[str, Any],
    patch_payload: dict[str, Any],
    workflow_mode: str,
    recent_runs_summary: list[dict[str, Any]],
    test_problem_id: str | None,
    is_run_acknowledgement: bool = False,
    cleanup_mode: bool = False,
    user_text: str = "",
    api_key: str | None = None,
    model_name: str | None = None,
    suppress_runack_invariant: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deterministic patch-merge pipeline used by the apply stage (S3).

    Pipeline:
    1. Merge the LLM patch into the base brief (per-port shape rules).
    2. Synthesize port-specific prose items from the merged ``goal_terms``
       (each port's ``synthesize_brief_items_from_goal_terms`` decides what
       prose rows mirror its structured carriers).
    3. Drop newly-introduced ``goal_terms`` keys that lack any evidence
       anchor (explicit ``evidence_item_ids``, port-declared self-anchored
       properties, or embedding-cosine fallback). Existing keys pass
       through unconditionally so re-tunes never regress.
    4. Maintain the rolling ``run_summary`` (deterministic — folds the
       latest ``recent_runs_summary[-1]`` line into the brief's summary
       on run-ack / cleanup turns).
    5. Re-enforce server-managed monitor OQs (upload / goal / algorithm).

    No LLM calls live in this function — the main-turn already owns OQ
    lifecycle, goal-term backing, and structured-carrier population. The
    deterministic anchoring filter remains as a hard gate.
    """
    from app.services.goal_term_anchoring import filter_unanchored_new_goal_terms

    merged = merge_problem_brief_patch(base_problem_brief, patch_payload)
    # Tutorial Runs 1+2 run-ack strip: the bubble drives the next step, so a
    # post-run agent reply that adds new OQs (waterfall) or new assumption
    # rows / goal_term keys (agile) is exactly the noise we want to suppress.
    # The prompt nudge in STUDY_CHAT_TUTORIAL_GUARDRAILS asks the LLM to
    # skip these, but it's not always honored — strip them server-side so
    # behavior is deterministic. Symmetric across modes; never strips
    # entries that were already in base (so retunes / answered OQs survive).
    if suppress_runack_invariant:
        merged = _strip_runack_additions(merged, base_problem_brief)
    # Closed-vocabulary strip: drop any goal_terms key the active port doesn't
    # recognise. Each port owns a fixed set of weight keys
    # (``weight_display_keys()``) plus the carrier-only ``search_strategy``;
    # anything else is an LLM hallucination (e.g. ``total_value`` paraphrasing
    # ``value_emphasis``). Stripping here, before anchor filtering and panel
    # derivation, means the brief never carries keys the panel can't admit —
    # which previously surfaced as `missing_in_panel` drift on every retry.
    merged = _strip_unknown_goal_term_keys(merged, test_problem_id)

    # Cold-start canonical-concept extraction. When the V2 brief patch landed
    # only `goal_summary` / setup prose but no structured `goal_terms` AND
    # the brief had nothing prior, run a port-aware structured-output Gemini
    # call to seed the canonical keys the participant explicitly named.
    # Gated on (base.goal_terms empty AND merged.goal_terms empty) so user
    # retirements on later turns stay sticky — the extractor never fires
    # after any goal term has been committed.
    base_gt = (
        base_problem_brief.get("goal_terms")
        if isinstance(base_problem_brief, dict)
        and isinstance(base_problem_brief.get("goal_terms"), dict)
        else {}
    )
    merged_gt = (
        merged.get("goal_terms")
        if isinstance(merged.get("goal_terms"), dict)
        else {}
    )
    if not base_gt and not merged_gt and api_key and model_name:
        from app.services.goal_term_extraction import extract_canonical_goal_terms

        seeds = extract_canonical_goal_terms(
            merged_brief=merged,
            user_text=user_text or "",
            api_key=api_key,
            model_name=model_name,
            test_problem_id=test_problem_id,
        )
        if seeds:
            merged = dict(merged)
            merged["goal_terms"] = seeds

    merged = _synthesize_goal_term_prose_items(merged, test_problem_id)

    proposed_goal_terms = (
        merged.get("goal_terms") if isinstance(merged.get("goal_terms"), dict) else {}
    )
    if proposed_goal_terms:
        # The user's own words are the most direct justification for any
        # goal term proposed this turn ("I want to minimize travel time"
        # anchors ``travel_time`` even when the LLM forgets the items[]
        # row). The virtual item is anchor-only — never saved into the brief.
        anchor_items = list(merged.get("items") or [])
        clean_user_text = (user_text or "").strip()
        if clean_user_text:
            anchor_items.append(
                {
                    "id": "__virtual_user_message__",
                    "text": clean_user_text,
                    "kind": "gathered",
                    "source": "user",
                }
            )
        filtered, dropped = filter_unanchored_new_goal_terms(
            base_brief=base_problem_brief,
            proposed_goal_terms=proposed_goal_terms,
            items=anchor_items,
            workflow_mode=workflow_mode,
            api_key=api_key,
            test_problem_id=test_problem_id,
        )
        if dropped:
            log.warning(
                "Brief patch dropped unanchored goal_terms keys: %s",
                dropped,
            )
            merged = dict(merged)
            merged["goal_terms"] = filtered

    # Drop LLM-emitted "goal-term anchor" rows: items that are (a) NEW this
    # turn (not in base.items by id) AND (b) cited by a NEW goal_term's
    # `evidence_item_ids`. These rows describe the same goal-term as the
    # canonical `config-weight-<key>` row about to be synthesized — keeping
    # both gives the participant two near-identical lines. The anchor
    # filter above already consumed the citation, so dropping the cited
    # item here is safe. Existing items (carried over from prior turns)
    # are NEVER dropped; only fresh anchors this patch introduced.
    merged = _drop_redundant_goal_term_anchors(
        base_brief=base_problem_brief, merged=merged
    )

    # Canonical goal-term rows: synthesize a ``config-weight-<key>`` items[]
    # row for every surviving goal_terms key, with text in the canonical
    # ``{Label} ({type}, weight N) — {reasoning}.`` form. Runs AFTER the
    # anchor filter so we never synthesize rows for keys the filter just
    # dropped. Re-normalisation inside the helper triggers the slot
    # reconciler, which drops any LLM-authored row that collides with the
    # synthesized one.
    merged = _synthesize_canonical_weight_items(merged, test_problem_id)

    # ``goal_summary`` fallback: when the LLM commits a primary objective
    # but forgets to populate the headline ``goal_summary`` field, derive
    # one from the goal-term label so the Definition's top section reflects
    # what's actually committed. Only fires when the field is empty — any
    # LLM-set value wins.
    merged = _autofill_goal_summary_from_objective(merged, test_problem_id)

    consolidated, run_meta = consolidate_run_summary(
        merged,
        recent_runs_summary=recent_runs_summary,
        cleanup_mode=cleanup_mode,
        is_run_acknowledgement=is_run_acknowledgement,
        test_problem_id=test_problem_id,
    )
    consolidated = _enforce_session_monitors(
        consolidated, workflow_mode, test_problem_id=test_problem_id
    )
    return consolidated, {"removed_total": 0, **run_meta}


def _strip_runack_additions(
    merged: dict[str, Any], base_problem_brief: dict[str, Any]
) -> dict[str, Any]:
    """Tutorial Runs 1+2 hard gate: drop new OQs / new assumption items /
    new goal_term keys the agent tried to add on this run-ack turn.

    Caller computes ``suppress_runack_invariant`` for the symmetric tutorial
    case (waterfall: would-be new OQ, agile: would-be new assumption) and
    only invokes this strip when the flag is set. Everything already in
    base survives — answers to existing OQs, retunes of existing
    ``goal_terms`` entries, and ack edits to existing assumption rows all
    pass through.
    """
    if not isinstance(merged, dict):
        return merged
    base = base_problem_brief if isinstance(base_problem_brief, dict) else {}
    base_oq_ids = {
        str(q.get("id") or "")
        for q in (base.get("open_questions") or [])
        if isinstance(q, dict)
    }
    base_item_ids = {
        str(it.get("id") or "")
        for it in (base.get("items") or [])
        if isinstance(it, dict)
    }
    base_gt_keys = {
        k
        for k in (
            base.get("goal_terms").keys()
            if isinstance(base.get("goal_terms"), dict)
            else []
        )
        if isinstance(k, str)
    }

    next_brief = dict(merged)
    next_oqs = [
        q
        for q in (merged.get("open_questions") or [])
        if isinstance(q, dict) and str(q.get("id") or "") in base_oq_ids
    ]
    if len(next_oqs) != len(merged.get("open_questions") or []):
        log.info(
            "Tutorial run-ack strip dropped %d new open_questions",
            len(merged.get("open_questions") or []) - len(next_oqs),
        )
    next_brief["open_questions"] = next_oqs

    next_items = []
    dropped_item_count = 0
    for it in merged.get("items") or []:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "").strip().lower()
        item_id = str(it.get("id") or "")
        if kind == "assumption" and item_id not in base_item_ids:
            dropped_item_count += 1
            continue
        next_items.append(it)
    if dropped_item_count:
        log.info(
            "Tutorial run-ack strip dropped %d new assumption items",
            dropped_item_count,
        )
    next_brief["items"] = next_items

    if isinstance(merged.get("goal_terms"), dict):
        filtered_gt = {
            k: v for k, v in merged["goal_terms"].items() if k in base_gt_keys
        }
        if len(filtered_gt) != len(merged["goal_terms"]):
            log.info(
                "Tutorial run-ack strip dropped %d new goal_terms keys: %s",
                len(merged["goal_terms"]) - len(filtered_gt),
                sorted(set(merged["goal_terms"].keys()) - base_gt_keys),
            )
        next_brief["goal_terms"] = filtered_gt
    return next_brief


def _strip_unknown_goal_term_keys(
    brief: dict[str, Any], test_problem_id: str | None
) -> dict[str, Any]:
    """Drop goal_terms keys outside the active port's closed vocabulary.

    Each port declares its weight keys via ``weight_display_keys()`` — that's
    the closed set the panel admits. Plus ``search_strategy`` is the
    carrier-only key for the algorithm choice. Anything else the LLM emits
    (e.g. ``total_value`` instead of ``value_emphasis``, ``efficient_packing``
    instead of ``capacity_overflow``) is a paraphrase the panel can't honor
    and would surface as ``missing_in_panel`` drift on every chat turn.

    Strip them deterministically here, before the anchor filter and before
    panel derivation, so the brief never carries unknown keys.
    """
    if not isinstance(brief, dict):
        return brief
    goal_terms = brief.get("goal_terms")
    if not isinstance(goal_terms, dict) or not goal_terms:
        return brief
    try:
        from app.problems.registry import get_study_port

        port = get_study_port(test_problem_id) if test_problem_id is not None else None
        allowed = set(port.weight_display_keys()) if port else set()
    except Exception:  # pragma: no cover — defensive
        allowed = set()
    if not allowed:
        return brief
    allowed = allowed | {"search_strategy"}
    unknown = [k for k in goal_terms.keys() if isinstance(k, str) and k not in allowed]
    if not unknown:
        return brief
    log.info(
        "Dropping non-vocabulary brief.goal_terms keys: %s (allowed=%s)",
        unknown,
        sorted(allowed),
    )
    next_brief = dict(brief)
    next_brief["goal_terms"] = {k: v for k, v in goal_terms.items() if k not in unknown}
    return next_brief


def _drop_redundant_goal_term_anchors(
    *,
    base_brief: dict[str, Any] | None,
    merged: dict[str, Any],
) -> dict[str, Any]:
    """Drop LLM-emitted items[] rows that double as goal-term anchors.

    Pattern this fixes: the LLM emits ``goal_terms.travel_time = {weight,
    type, evidence_item_ids: ["item-primary-travel-time"]}`` AND a matching
    items[] row ``{id: "item-primary-travel-time", text: "Total travel
    time (objective, weight 1.0) — minimizing overall distance…"}``.
    The synthesizer is about to emit ``config-weight-travel_time`` with
    essentially the same content — the participant ends up seeing two
    near-identical rows.

    Rule (purely structural, no NL):
    - An items[] row is dropped iff its id is **new this turn** (not in
      ``base.items`` by id) **AND** it's cited by the ``evidence_item_ids``
      of a goal_term that is **also new this turn** (not in
      ``base.goal_terms`` by key).
    - Existing items (carried from prior turns) and items cited by
      already-existing goal_terms are NEVER touched — keeps user-curated
      context safe.
    """
    if not isinstance(merged, dict):
        return merged
    base_item_ids: set[str] = set()
    base_gt_keys: set[str] = set()
    if isinstance(base_brief, dict):
        for it in (base_brief.get("items") or []):
            if isinstance(it, dict):
                base_item_ids.add(str(it.get("id") or ""))
        base_gt = base_brief.get("goal_terms")
        if isinstance(base_gt, dict):
            base_gt_keys = {k for k in base_gt.keys() if isinstance(k, str)}

    merged_gt = merged.get("goal_terms")
    if not isinstance(merged_gt, dict):
        return merged
    anchor_ids_to_drop: set[str] = set()
    for key, entry in merged_gt.items():
        if not isinstance(key, str) or key in base_gt_keys:
            continue  # existing goal_term — leave its evidence alone
        if not isinstance(entry, dict):
            continue
        evidence = entry.get("evidence_item_ids")
        if not isinstance(evidence, list):
            continue
        for eid in evidence:
            if not isinstance(eid, str):
                continue
            sid = eid.strip()
            if not sid or sid in base_item_ids:
                continue  # only drop NEW anchors, never existing items
            anchor_ids_to_drop.add(sid)
    if not anchor_ids_to_drop:
        return merged

    next_items = [
        it for it in (merged.get("items") or [])
        if not (isinstance(it, dict) and str(it.get("id") or "") in anchor_ids_to_drop)
    ]
    next_brief = dict(merged)
    next_brief["items"] = next_items
    return next_brief


def _autofill_goal_summary_from_objective(
    brief: dict[str, Any], test_problem_id: str | None
) -> dict[str, Any]:
    """If ``goal_summary`` is empty and at least one ``goal_terms`` entry
    has ``type: "objective"`` with positive weight, synthesize a short
    qualitative sentence from the goal-term label(s) so the Definition's
    headline reflects the committed objective.

    Single objective → *"Minimize <label>."*; multiple objectives → a
    short conjunction. The LLM is supposed to set ``goal_summary`` itself
    (per prompt discipline) but this fallback prevents the headline from
    staying blank when it forgets — observed on plain "minimize travel
    time" answers where ``goal_terms.travel_time`` got committed but
    ``goal_summary`` stayed empty.
    """
    if not isinstance(brief, dict):
        return brief
    if str(brief.get("goal_summary") or "").strip():
        return brief
    goal_terms = brief.get("goal_terms")
    if not isinstance(goal_terms, dict) or not goal_terms:
        return brief
    objective_labels: list[str] = []
    try:
        from app.problems.registry import get_study_port

        port = get_study_port(test_problem_id)
        labels = port.weight_item_labels() or {}
    except Exception:  # pragma: no cover — defensive
        labels = {}
    for key, entry in goal_terms.items():
        if key == "search_strategy":
            continue
        if not isinstance(entry, dict):
            continue
        gtype = str(entry.get("type") or "").strip().lower()
        if gtype != "objective":
            continue
        weight = entry.get("weight")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            continue
        if weight <= 0:
            continue
        label = labels.get(key) or key.replace("_", " ")
        # Keep the label lowercase mid-sentence so it reads naturally.
        objective_labels.append(label[0].lower() + label[1:] if label else key)
    if not objective_labels:
        return brief
    if len(objective_labels) == 1:
        summary = f"Minimize {objective_labels[0]}."
    elif len(objective_labels) == 2:
        summary = f"Minimize {objective_labels[0]} and {objective_labels[1]}."
    else:
        head = ", ".join(objective_labels[:-1])
        summary = f"Minimize {head}, and {objective_labels[-1]}."
    next_brief = dict(brief)
    next_brief["goal_summary"] = summary
    return next_brief


# Stable ids for the three server-side monitor rows. Idempotent: re-emission
# overwrites the same slot rather than duplicating.
_MONITOR_OQ_UPLOAD_ID = "oq-monitor-upload"
_MONITOR_OQ_GOAL_ID = "oq-monitor-goal"
_MONITOR_OQ_ALGORITHM_ID = "oq-monitor-algorithm"
_MONITOR_ITEM_ALGORITHM_ID = "item-monitor-algorithm-default"

_MONITOR_OQ_UPLOAD_TEXT = (
    "Please use the **Upload file(s)...** button in the chat footer to share "
    "your data so we can set up a baseline run."
)
_MONITOR_OQ_GOAL_TEXT_FALLBACK = (
    "What's your primary optimization goal? Tell me which priority should drive "
    "the search."
)
_MONITOR_OQ_ALGORITHM_TEXT = (
    "Which search strategy should we use? Common choices: genetic search "
    "(GA), particle swarm (PSO), or simulated annealing (SA)."
)
_MONITOR_ITEM_ALGORITHM_TEXT = (
    "Search strategy is set to genetic search (GA) as a starting point — "
    "change anytime."
)


def _monitor_goal_oq_text(test_problem_id: str | None) -> str:
    """Build the canonical goal-term OQ text from the active port's labels.

    Per-port `weight_item_labels()` are the natural-language names the
    participant already sees in the Definition tab. Pulling examples from
    them keeps the monitor OQ aligned with the active benchmark instead of
    hardcoding one problem's vocabulary (which previously leaked VRPTW
    examples like "minimize total travel time" into knapsack sessions).
    """
    try:
        from app.problems.registry import get_study_port

        port = get_study_port(test_problem_id) if test_problem_id is not None else None
        labels_map = port.weight_item_labels() if port else {}
        display_keys = port.weight_display_keys() if port else []
    except Exception:  # pragma: no cover — defensive
        labels_map = {}
        display_keys = []
    ordered = [labels_map[k] for k in display_keys if k in labels_map and labels_map[k]]
    if not ordered:
        ordered = [v for v in (labels_map or {}).values() if v]
    if not ordered:
        return _MONITOR_OQ_GOAL_TEXT_FALLBACK
    if len(ordered) == 1:
        examples = ordered[0]
    elif len(ordered) == 2:
        examples = f"{ordered[0]} or {ordered[1]}"
    else:
        head = ", ".join(ordered[:-1])
        examples = f"{head}, or {ordered[-1]}"
    return (
        "What's your primary optimization goal? For example, you could prioritize "
        f"{examples}, or name another priority."
    )

def _enforce_session_monitors(
    brief: dict[str, Any],
    workflow_mode: str | None,
    test_problem_id: str | None = None,
) -> dict[str, Any]:
    """Server-side state machine: keep the three "what's still missing" rows
    in lockstep with brief state. Three monitors, each idempotent via a stable
    id — once satisfied, the matching row is dropped; once again missing, it's
    re-inserted on the next turn.

    1. **Upload** — warm AND no ``source: upload`` item → OQ asking for the
       upload. Clears once the participant uploads.
    2. **Goal term** — warm AND ``brief.goal_terms`` empty → OQ asking for
       the primary objective. Both workflows; clears once any goal term is
       committed.
    3. **Search strategy** — warm AND no algorithm mention in brief items.
       Agile / demo → ``kind: assumption`` row defaulting to GA. Waterfall →
       OQ asking the participant to pick.

    The check uses ``is_chat_cold_start`` to gate warmth — cold sessions get
    no monitor rows, so a "hi" turn doesn't immediately surface three OQs.
    """
    from app.problem_brief import is_chat_cold_start
    from app.services.goal_term_anchoring import brief_mentions_search_strategy

    if not isinstance(brief, dict):
        return brief
    if is_chat_cold_start(brief):
        return brief

    workflow = str(workflow_mode or "").strip().lower()
    is_agile_or_demo = workflow in {"agile", "demo"}

    next_brief = deepcopy(brief)
    items = list(next_brief.get("items") or [])
    open_questions = list(next_brief.get("open_questions") or [])

    def _has_oq(oq_id: str) -> bool:
        return any(
            isinstance(q, dict) and str(q.get("id") or "") == oq_id
            for q in open_questions
        )

    def _has_item(item_id: str) -> bool:
        return any(
            isinstance(i, dict) and str(i.get("id") or "") == item_id
            for i in items
        )

    def _drop_oq(oq_id: str) -> None:
        nonlocal open_questions
        open_questions = [
            q for q in open_questions
            if not (isinstance(q, dict) and str(q.get("id") or "") == oq_id)
        ]

    def _drop_item(item_id: str) -> None:
        nonlocal items
        items = [
            i for i in items
            if not (isinstance(i, dict) and str(i.get("id") or "") == item_id)
        ]

    def _append_oq(oq_id: str, text: str, topic: str) -> None:
        open_questions.append({
            "id": oq_id,
            "text": text,
            "status": "open",
            "answer_text": None,
            "topic": topic,
        })

    # Monitor 1: upload
    has_upload = any(
        isinstance(i, dict) and str(i.get("source") or "").strip().lower() == "upload"
        for i in items
    )
    if has_upload:
        _drop_oq(_MONITOR_OQ_UPLOAD_ID)
    elif not _has_oq(_MONITOR_OQ_UPLOAD_ID):
        _append_oq(_MONITOR_OQ_UPLOAD_ID, _MONITOR_OQ_UPLOAD_TEXT, "upload")

    # Monitor 2: goal term
    goal_terms = next_brief.get("goal_terms")
    has_goal = isinstance(goal_terms, dict) and bool(goal_terms)
    if has_goal:
        _drop_oq(_MONITOR_OQ_GOAL_ID)
    elif not _has_oq(_MONITOR_OQ_GOAL_ID):
        _append_oq(
            _MONITOR_OQ_GOAL_ID,
            _monitor_goal_oq_text(test_problem_id),
            "primary_goal",
        )

    # Monitor 3: search strategy
    # Use brief_mentions_search_strategy (carrier-aware) instead of the
    # text-only algorithm_mentioned_in_brief. Without this, an LLM that
    # committed `goal_terms.search_strategy.properties.algorithm = "GA"`
    # via the structured carrier but no items[] row mentioning GA would
    # be considered "no algorithm" — and the monitor would re-add
    # `oq-monitor-algorithm` alongside the canonical one stored by the
    # PATCH path. (Observed in the 26f4 session: counter-question on
    # the algorithm OQ → router's reset + this monitor re-add gave the
    # participant two algorithm OQs.)
    has_algorithm = brief_mentions_search_strategy(
        next_brief, workflow_mode=workflow
    )
    if is_agile_or_demo:
        if has_algorithm:
            _drop_item(_MONITOR_ITEM_ALGORITHM_ID)
        elif not _has_item(_MONITOR_ITEM_ALGORITHM_ID):
            items.append({
                "id": _MONITOR_ITEM_ALGORITHM_ID,
                "text": _MONITOR_ITEM_ALGORITHM_TEXT,
                "kind": "assumption",
                "source": "agent",
            })
        # Drop any waterfall OQ that may be lingering from a workflow switch.
        _drop_oq(_MONITOR_OQ_ALGORITHM_ID)
    else:
        if has_algorithm:
            _drop_oq(_MONITOR_OQ_ALGORITHM_ID)
        elif not _has_oq(_MONITOR_OQ_ALGORITHM_ID):
            _append_oq(_MONITOR_OQ_ALGORITHM_ID, _MONITOR_OQ_ALGORITHM_TEXT, "search_strategy")
        # Drop any agile-mode assumption that may be lingering.
        _drop_item(_MONITOR_ITEM_ALGORITHM_ID)

    # No tag-dedup loop is needed any more: foundational-topic OQs from the
    # LLM are stripped at merge time in `merge_problem_brief_patch` (the
    # required `topic` enum on the OQ schema gives the boundary check
    # everything it needs). The only OQs that reach this point are
    # canonical monitor rows we added above plus the LLM's `topic="other"`
    # clarifications, and those never duplicate each other by construction.

    next_brief["items"] = items
    next_brief["open_questions"] = open_questions
    return next_brief


def _synthesize_canonical_weight_items(
    brief: dict[str, Any], test_problem_id: str | None
) -> dict[str, Any]:
    """Refresh canonical ``config-weight-<key>`` rows from ``brief.goal_terms``.

    Every goal-term key gets exactly one row whose text follows
    ``{Label} ({type}, weight N) — {reasoning}.`` so the Definition surfaces
    the three pieces the spec requires (reasoning, type, weight) for every
    gathered/assumption row that describes a goal term. Previously this
    synthesis only fired on panel→brief sync — the forward path
    (LLM patch → brief) left users with whatever free-text item the LLM
    chose to emit, often missing weight + type.

    Drop-and-replace by id prefix: any existing ``config-weight-<key>``
    row is removed before the freshly-computed set is appended, so a key
    whose weight/type/rationale changed this turn surfaces the new values.
    """
    from app.problem_brief import (
        normalize_problem_brief,
        synthesize_canonical_goal_term_items,
    )

    if not isinstance(brief, dict):
        return brief
    extras = synthesize_canonical_goal_term_items(brief, test_problem_id)
    base_items = list(brief.get("items") or [])
    has_stale = any(
        isinstance(item, dict)
        and str(item.get("id") or "").startswith("config-weight-")
        for item in base_items
    )
    # Both branches need to run: even when no new extras are produced (e.g.
    # the brief's only goal_term is the carrier-only `search_strategy`, or
    # `goal_terms` was wiped this turn), stale `config-weight-*` rows from
    # prior turns must still be dropped. Previously the early-return on
    # empty extras left stale rows behind, producing the
    # 26f4-session pattern: items[] showed
    # `Travel time (primary objective, weight 1.0)` even though
    # `goal_terms.travel_time` was already gone — so the brief and the
    # panel disagreed silently.
    if not extras and not has_stale:
        return brief
    next_brief = dict(brief)
    kept_items = [
        item
        for item in base_items
        if not (
            isinstance(item, dict)
            and str(item.get("id") or "").startswith("config-weight-")
        )
    ]
    kept_items.extend(extras)
    next_brief["items"] = kept_items
    return normalize_problem_brief(next_brief)


def _synthesize_goal_term_prose_items(
    brief: dict[str, Any], test_problem_id: str | None
) -> dict[str, Any]:
    """Refresh participant-facing prose rows synthesized from `brief.goal_terms`
    (e.g. VRPTW driver-preference rules → `config-driver-pref-*`).

    For every goal-term key the port "owns" prose-row prefixes for
    (via `prose_id_prefixes_for_goal_term`), this drops all existing items
    matching those prefixes before re-adding the freshly synthesized set.
    That way removing a rule (or all rules) is reflected in the Definition
    on the next turn without stale rows hanging around.
    """
    from app.problem_brief import normalize_problem_brief
    from app.problems.registry import get_study_port

    if not isinstance(brief, dict):
        return brief
    goal_terms = brief.get("goal_terms") or {}
    if not isinstance(goal_terms, dict):
        return brief

    try:
        port = get_study_port(test_problem_id)
        owned_prefixes: set[str] = set()
        for key in goal_terms:
            if not isinstance(key, str):
                continue
            for prefix in port.prose_id_prefixes_for_goal_term(key):
                if isinstance(prefix, str) and prefix:
                    owned_prefixes.add(prefix)
        extras = (
            port.synthesize_brief_items_from_goal_terms(goal_terms)
            if goal_terms
            else []
        )
    except AttributeError:
        return brief

    if not owned_prefixes and not extras:
        return brief

    next_brief = dict(brief)
    base_items = list(brief.get("items") or [])
    # Drop stale items the synthesizer owns — id-prefix only, never text.
    kept_items = [
        item
        for item in base_items
        if not (
            isinstance(item, dict)
            and any(
                str(item.get("id") or "").startswith(prefix)
                for prefix in owned_prefixes
            )
        )
    ]
    seen_ids = {
        str(item.get("id") or "")
        for item in kept_items
        if isinstance(item, dict)
    }
    for extra in extras:
        if not isinstance(extra, dict):
            continue
        item_id = str(extra.get("id") or "").strip()
        if not item_id or item_id in seen_ids:
            continue
        kept_items.append(extra)
        seen_ids.add(item_id)
    next_brief["items"] = kept_items
    return normalize_problem_brief(next_brief)


def append_message(
    db: Session,
    session_id: str,
    role: str,
    content: str,
    visible: bool,
    kind: str = "chat",
    meta: dict[str, Any] | None = None,
) -> ChatMessage:
    m = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        visible_to_participant=visible,
        kind=kind,
        meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
    )
    db.add(m)
    s = db.get(StudySession, session_id)
    if s:
        s.updated_at = datetime.now(timezone.utc)
        if role == "user" and visible:
            s.optimization_gate_engaged = True
    db.commit()
    db.refresh(m)
    return m


def persist_processing_failure(session_id: str, revision: int, detail: str) -> None:
    with SessionLocal() as db:
        row = db.get(StudySession, session_id)
        if row is None or row.processing_revision != revision:
            return
        helpers.fail_processing_state(row, detail)
        db.commit()


def _read_session_processing_revision(db: Session, session_id: str) -> int | None:
    """Read the live ``processing_revision`` for a session, bypassing the
    identity-map cache. Used by the BG-derivation race-protection checks: we
    need the *committed* DB value (which a concurrent participant PATCH may
    have just bumped), not the snapshot SQLAlchemy holds for our staged row.
    """
    return db.execute(
        select(StudySession.processing_revision).where(StudySession.id == session_id)
    ).scalar()


