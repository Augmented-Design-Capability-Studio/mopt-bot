"""Background derivation and message append logic."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from copy import deepcopy
from datetime import datetime, timezone
from threading import Thread
from typing import Any

from app.config import get_settings
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ChatMessage, StudySession
from app.schemas import ProblemBriefUpdateTurn
from app.problem_brief import (
    cleanup_open_questions,
    coerce_problem_brief_for_workflow,
    merge_problem_brief_patch,
    normalize_problem_brief,
    problem_brief_item_slot,
    sync_problem_brief_from_panel,
)

from . import helpers, sync

log = logging.getLogger(__name__)
OPEN_QUESTION_CLEANUP_MESSAGE = (
    "Clean up open questions only: remove resolved or duplicate questions, keep still-ambiguous ones open."
)
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


def _is_bookkeeping(raw: dict[str, Any]) -> bool:
    text = str(raw.get("text") or "").strip().lower()
    return any(snippet in text for snippet in _RUN_BOOKKEEPING_TEXT_SNIPPETS)


def _sanitize_run_ack_patch_payload(
    patch_payload: dict[str, Any],
    *,
    workflow_mode: str | None = None,
    test_problem_id: str | None = None,
) -> dict[str, Any]:
    """
    Keep run-ack brief edits compact: allow open-question curation plus durable
    config-slot rows. Drop per-run/session bookkeeping rows to prevent
    Definition growth across runs.

    Cite-chain exemption: any items[] row whose ``id`` appears as
    ``evidence_item_ids`` on a ``goal_terms`` entry in this same patch is
    kept regardless of slot/kind. Without this exemption, a post-run agent
    commitment to two new goal terms (e.g. *"I've added a punctuality
    penalty and a capacity penalty after the run"*) lands as
    ``goal_terms`` entries cited against items the sanitizer would
    otherwise drop — and the brief-side anchor check then drops the
    goal-term keys too because their cites no longer resolve. The
    exemption keeps the chain intact while still scrubbing pure
    bookkeeping rows.
    """
    sanitized = dict(patch_payload)
    raw_items = sanitized.get("items")
    if not isinstance(raw_items, list):
        sanitized["replace_editable_items"] = False
        return sanitized

    # Collect cite ids referenced by patch.goal_terms — these items must
    # survive the slot filter or the cited goal-term keys lose their
    # anchor and get dropped downstream.
    cited_ids: set[str] = set()
    patch_goal_terms = sanitized.get("goal_terms")
    if isinstance(patch_goal_terms, dict):
        for entry in patch_goal_terms.values():
            if not isinstance(entry, dict):
                continue
            evidence = entry.get("evidence_item_ids")
            if not isinstance(evidence, list):
                continue
            for eid in evidence:
                if isinstance(eid, str) and eid.strip():
                    cited_ids.add(eid.strip())

    mode = str(workflow_mode or "").strip().lower()
    kept_items: list[dict[str, Any]] = []
    kept_agile_assumption_count = 0
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id") or "").strip()
        # Cite-chain exemption — preserve regardless of slot/kind/bookkeeping
        # text so the goal-term entries citing this id keep their anchor. A
        # cited row IS load-bearing for the commitment even when its rationale
        # naturally references a run (e.g. "Added lateness_penalty after Run
        # #1 showed time-window misses"). If the participant doesn't want the
        # row, they remove it and the cascade-strip takes the goal term down
        # too.
        if item_id and item_id in cited_ids:
            kept_items.append(raw)
            continue
        kind = str(raw.get("kind") or "").strip().lower()
        # On run-ack turns we normally keep only durable config-slot rows. Agile is allowed
        # a very small provisional assumption update to support iterative refinement.
        if kind == "assumption" and mode == "agile":
            if not _is_bookkeeping(raw) and kept_agile_assumption_count < 1:
                kept_items.append(raw)
                kept_agile_assumption_count += 1
            continue
        slot = problem_brief_item_slot(raw, test_problem_id=test_problem_id)
        if slot and not _is_bookkeeping(raw):
            kept_items.append(raw)

    sanitized["items"] = kept_items
    sanitized["replace_editable_items"] = False
    return sanitized


def sanitize_run_ack_patch_payload(
    patch_payload: dict[str, Any],
    *,
    workflow_mode: str | None = None,
    test_problem_id: str | None = None,
) -> dict[str, Any]:
    """Public wrapper for run-ack patch sanitization."""
    return _sanitize_run_ack_patch_payload(
        patch_payload, workflow_mode=workflow_mode, test_problem_id=test_problem_id
    )


def apply_open_question_cleanup_pass(
    *,
    problem_brief: dict[str, Any],
    history_lines: list[tuple[str, str]],
    user_text: str,
    api_key: str,
    model_name: str,
    workflow_mode: str,
    current_panel: dict[str, Any] | None,
    recent_runs_summary: list[dict[str, Any]],
    researcher_steers: list[str],
    test_problem_id: str | None,
    infer_resolved: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    LLM-first open-question cleanup with conservative deterministic fallback.
    """
    base = normalize_problem_brief(problem_brief)
    llm_used = False
    llm_pruned = False
    if infer_resolved and api_key.strip():
        try:
            from app.services.llm import generate_problem_brief_update

            turn = generate_problem_brief_update(
                user_text=user_text,
                history_lines=history_lines,
                api_key=api_key,
                model_name=model_name,
                current_problem_brief=base,
                workflow_mode=workflow_mode,
                current_panel=current_panel,
                recent_runs_summary=recent_runs_summary or None,
                researcher_steers=researcher_steers or None,
                cleanup_mode=True,
                test_problem_id=test_problem_id,
            )
            if turn is not None:
                llm_used = True
                patch = turn.problem_brief_patch if isinstance(turn.problem_brief_patch, dict) else None
                if patch is not None and "open_questions" in patch:
                    candidate = merge_problem_brief_patch(
                        base,
                        {"open_questions": patch.get("open_questions"), "replace_open_questions": True},
                    )
                    if len(candidate.get("open_questions") or []) <= len(base.get("open_questions") or []):
                        base = candidate
                        llm_pruned = True
        except Exception:
            log.exception("Open-question cleanup model pass failed")
    cleaned, cleanup_meta = cleanup_open_questions(
        base, infer_resolved=(infer_resolved and not llm_pruned)
    )
    return cleaned, {
        "llm_used": llm_used,
        "llm_pruned": llm_pruned,
        **cleanup_meta,
    }


def _patch_likely_resolves_open_questions(
    base_problem_brief: dict[str, Any],
    patch_payload: dict[str, Any],
) -> bool:
    """Heuristic gate for the second-pass OQ-cleanup LLM call.

    The second LLM pass (`apply_open_question_cleanup_pass` with
    `infer_resolved=True`) is only useful when the patch plausibly resolves
    some open question. It's pure waste on patches that only edit weights,
    swap algorithms, or refine prose — and actively harmful when the patch
    is *adding* new OQs (the cleanup LLM has been observed to prune the
    OQs that were just added, especially in waterfall after a run).

    "Could resolve an OQ" is approximated as: the patch is a deliberate
    full-list replace (`replace_open_questions=True`), OR adds at least
    one new `gathered` row (the typical shape of a fact that retires an
    OQ). Adding-only OQs without a replace flag does NOT trigger the
    cleanup pass.
    """
    if not isinstance(patch_payload, dict):
        return False
    if (
        "open_questions" in patch_payload
        and bool(patch_payload.get("replace_open_questions"))
    ):
        return True
    incoming_items = patch_payload.get("items")
    if not isinstance(incoming_items, list):
        return False
    base_ids = {
        str(item.get("id") or "")
        for item in (base_problem_brief.get("items") or [])
        if isinstance(item, dict)
    }
    for item in incoming_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip().lower() != "gathered":
            continue
        item_id = str(item.get("id") or "")
        if item_id and item_id in base_ids:
            continue
        return True
    return False


def apply_brief_patch_with_cleanup(
    *,
    base_problem_brief: dict[str, Any],
    patch_payload: dict[str, Any],
    history_lines: list[tuple[str, str]],
    api_key: str,
    model_name: str,
    workflow_mode: str,
    current_panel: dict[str, Any] | None,
    recent_runs_summary: list[dict[str, Any]],
    researcher_steers: list[str],
    test_problem_id: str | None,
    enable_auto_open_question_cleanup: bool = True,
    is_run_acknowledgement: bool = False,
    cleanup_mode: bool = False,
    user_text: str = "",
    embedding_model: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Shared patch-merge pipeline used by definition cleanup and OQ cleanup-triggered flows.

    The second-pass OQ cleanup LLM call is skipped on chat-turn patches that
    don't plausibly resolve any open question (weights-only edits, algorithm
    swaps, prose tweaks). It still runs unconditionally for explicit cleanup,
    run acknowledgements, and patches that touch open_questions or add new
    gathered rows.
    """
    from app.services.goal_term_anchoring import filter_unanchored_new_goal_terms

    merged = merge_problem_brief_patch(base_problem_brief, patch_payload)
    merged = _synthesize_goal_term_prose_items(merged, test_problem_id)
    # Anchor check: drop newly-added goal_terms keys that have no evidence in
    # `items[]` (explicit `evidence_item_ids` cite, self-anchored properties,
    # or embedding cosine fallback). Existing keys in the prior brief are
    # untouched. This is the brief-side gate; sync.py applies the same gate
    # on the panel-derive side.
    proposed_goal_terms = merged.get("goal_terms") if isinstance(merged.get("goal_terms"), dict) else {}
    if proposed_goal_terms:
        # Include the current user message as a virtual evidence item for
        # embedding-based anchoring. The user's own words are the most direct
        # justification for any goal term proposed this turn — e.g.
        # "I want to minimize travel time" anchors `travel_time` even when
        # the LLM forgets to emit a matching `items[]` row. The virtual item
        # is anchor-only; it does NOT get saved into the brief.
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
    # The cleanup pass calls the LLM with `infer_resolved=True` and may return
    # an empty open_questions list — replacing OQs the LLM just added. Run-ack
    # used to *force* this pass on every run, which was the regression that
    # silently pruned waterfall OQs. Run-ack now uses the same
    # `_patch_likely_resolves_open_questions` heuristic as ordinary turns:
    # cleanup only fires when something in the patch could plausibly retire
    # an existing OQ (full-list replace OR a new gathered row).
    skip_oq_cleanup_pass = (
        not enable_auto_open_question_cleanup
        or merged == base_problem_brief
        or (
            not cleanup_mode
            and not _patch_likely_resolves_open_questions(base_problem_brief, patch_payload)
        )
    )
    if skip_oq_cleanup_pass:
        consolidated, run_meta = consolidate_run_summary(
            merged,
            recent_runs_summary=recent_runs_summary,
            cleanup_mode=cleanup_mode,
            is_run_acknowledgement=is_run_acknowledgement,
            test_problem_id=test_problem_id,
        )
        consolidated = _validate_goal_term_backing(
            consolidated, api_key, model_name, test_problem_id
        )
        consolidated = _enforce_session_monitors(consolidated, workflow_mode)
        return consolidated, {"removed_total": 0, **run_meta}
    cleaned, meta = apply_open_question_cleanup_pass(
        problem_brief=merged,
        history_lines=history_lines,
        user_text=OPEN_QUESTION_CLEANUP_MESSAGE,
        api_key=api_key,
        model_name=model_name,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
        researcher_steers=researcher_steers,
        test_problem_id=test_problem_id,
        infer_resolved=True,
    )
    consolidated, run_meta = consolidate_run_summary(
        cleaned,
        recent_runs_summary=recent_runs_summary,
        cleanup_mode=cleanup_mode,
        is_run_acknowledgement=is_run_acknowledgement,
        test_problem_id=test_problem_id,
    )
    consolidated = _validate_goal_term_backing(
        consolidated, api_key, model_name, test_problem_id
    )
    consolidated = _enforce_session_monitors(consolidated, workflow_mode)
    return consolidated, {**meta, **run_meta}


def _validate_goal_term_backing(
    brief: dict[str, Any],
    api_key: str | None,
    model_name: str | None,
    test_problem_id: str | None,
) -> dict[str, Any]:
    """Iteration-3 semantic validator: ensures every key in
    ``brief.goal_terms`` has an explicit backing row in ``brief.items[]``.

    Calls a focused, dedicated LLM (see ``validate_goal_term_backing`` in
    ``llm.py``). For each unbacked key, appends a ``kind: assumption``
    items[] row with stable id ``item-validator-{key}`` describing the
    agent's inference. The participant sees the inference in the Definition
    tab and can confirm / edit / remove (removal triggers the cascade-strip
    that takes the goal term down with it).

    Skips silently when there are no goal terms to validate, when no
    api_key / model_name is available, or when the LLM call fails — drift
    stays at zero in the latter case but a stale unbacked goal term may
    persist until the next turn re-runs the validator.
    """
    if not isinstance(brief, dict):
        return brief
    if not api_key or not model_name:
        return brief
    goal_terms = brief.get("goal_terms")
    if not isinstance(goal_terms, dict) or not goal_terms:
        return brief

    try:
        from app.services.llm import validate_goal_term_backing

        result = validate_goal_term_backing(
            brief,
            api_key=api_key,
            model_name=model_name,
            test_problem_id=test_problem_id,
        )
    except Exception as exc:  # pragma: no cover — defensive
        log.warning("Goal-term backing validator failed: %s", exc)
        return brief

    entries = result.get("assumptions_to_add") if isinstance(result, dict) else []
    fresh_summary = (
        str(result.get("updated_goal_summary") or "").strip()
        if isinstance(result, dict)
        else ""
    )
    if not entries and not fresh_summary:
        return brief

    next_brief = deepcopy(brief)
    items = list(next_brief.get("items") or [])
    existing_ids = {str(i.get("id") or "") for i in items if isinstance(i, dict)}
    appended = 0
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("goal_term_key") or "").strip()
        text = str(entry.get("text") or "").strip()
        if not key or not text:
            continue
        item_id = f"item-validator-{key}"
        if item_id in existing_ids:
            continue
        items.append(
            {
                "id": item_id,
                "text": text,
                "kind": "assumption",
                "source": "agent",
            }
        )
        existing_ids.add(item_id)
        appended += 1
    if appended:
        log.info("Goal-term backing validator added %d assumption row(s)", appended)
        next_brief["items"] = items
    if fresh_summary and fresh_summary != str(next_brief.get("goal_summary") or "").strip():
        log.info("Goal-term backing validator refreshed goal_summary")
        next_brief["goal_summary"] = fresh_summary
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
_MONITOR_OQ_GOAL_TEXT = (
    "What's your primary optimization goal? For example, minimize total "
    "travel time, meet customer time windows, balance driver workload, or "
    "another priority."
)
_MONITOR_OQ_ALGORITHM_TEXT = (
    "Which search strategy should we use? Common choices: genetic search "
    "(GA), particle swarm (PSO), or simulated annealing (SA)."
)
_MONITOR_ITEM_ALGORITHM_TEXT = (
    "Search strategy is set to genetic search (GA) as a starting point — "
    "change anytime."
)


def _enforce_session_monitors(
    brief: dict[str, Any], workflow_mode: str | None
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
    from app.services.goal_term_anchoring import algorithm_mentioned_in_brief

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

    def _append_oq(oq_id: str, text: str) -> None:
        open_questions.append({
            "id": oq_id,
            "text": text,
            "status": "open",
            "answer_text": None,
        })

    # Monitor 1: upload
    has_upload = any(
        isinstance(i, dict) and str(i.get("source") or "").strip().lower() == "upload"
        for i in items
    )
    if has_upload:
        _drop_oq(_MONITOR_OQ_UPLOAD_ID)
    elif not _has_oq(_MONITOR_OQ_UPLOAD_ID):
        _append_oq(_MONITOR_OQ_UPLOAD_ID, _MONITOR_OQ_UPLOAD_TEXT)

    # Monitor 2: goal term
    goal_terms = next_brief.get("goal_terms")
    has_goal = isinstance(goal_terms, dict) and bool(goal_terms)
    if has_goal:
        _drop_oq(_MONITOR_OQ_GOAL_ID)
    elif not _has_oq(_MONITOR_OQ_GOAL_ID):
        _append_oq(_MONITOR_OQ_GOAL_ID, _MONITOR_OQ_GOAL_TEXT)

    # Monitor 3: search strategy
    has_algorithm = algorithm_mentioned_in_brief(items, workflow_mode=workflow)
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
            _append_oq(_MONITOR_OQ_ALGORITHM_ID, _MONITOR_OQ_ALGORITHM_TEXT)
        # Drop any agile-mode assumption that may be lingering.
        _drop_item(_MONITOR_ITEM_ALGORITHM_ID)

    next_brief["items"] = items
    next_brief["open_questions"] = open_questions
    return next_brief


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


def _run_with_timeout(callable_obj, timeout_sec: float):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(callable_obj)
    try:
        return future.result(timeout=timeout_sec)
    finally:
        # Don't block on shutdown — if the LLM thread is still running after a
        # timeout, wait=True would hold the request handler open indefinitely.
        executor.shutdown(wait=False)


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


def compute_brief_after_user_turn(
    *,
    user_text: str,
    history_lines: list[tuple[str, str]],
    api_key: str,
    model_name: str,
    base_problem_brief: dict[str, Any],
    base_panel: dict[str, Any] | None,
    workflow_mode: str,
    recent_runs_summary: list[dict[str, Any]] | None = None,
    researcher_steers: list[str] | None = None,
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    visible_assistant_message: str | None = None,
    gate_status: dict[str, Any] | None = None,
    embedding_model: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, "ProblemBriefUpdateTurn"]:
    """Synchronous probe variant of the brief-update pipeline.

    Runs the brief-update LLM once and merges its patch with the base brief,
    returning ``(merged_brief, panel_patch_or_None, brief_turn)`` **without**
    persisting anything. Used by the pre-release probe in the router to
    predict what the brief would look like after this turn commits, so the
    router can decide whether the visible reply's claims line up with what
    the structured patch actually delivered.

    On any failure (LLM exception, parse error, merge error) the function
    falls back to ``(base_problem_brief, None, empty_brief_turn)`` so the
    probe can still proceed with a degraded prediction rather than crash.
    """
    from app.schemas import ProblemBriefUpdateTurn
    from app.services.llm import generate_problem_brief_update

    empty_turn = ProblemBriefUpdateTurn(problem_brief_patch=None)
    try:
        brief_turn = generate_problem_brief_update(
            user_text=user_text,
            history_lines=history_lines,
            api_key=api_key,
            model_name=model_name,
            current_problem_brief=base_problem_brief,
            workflow_mode=workflow_mode,
            current_panel=base_panel,
            recent_runs_summary=recent_runs_summary,
            researcher_steers=researcher_steers,
            cleanup_mode=False,
            is_run_acknowledgement=False,
            is_answered_open_question=False,
            is_config_save=False,
            is_upload_context=False,
            is_tutorial_active=is_tutorial_active,
            test_problem_id=test_problem_id,
            visible_assistant_message=visible_assistant_message,
            gate_status=gate_status,
        )
    except Exception:
        log.exception("compute_brief_after_user_turn: brief-update LLM failed")
        return (base_problem_brief, None, empty_turn)

    if brief_turn is None or brief_turn.problem_brief_patch is None:
        return (base_problem_brief, None, brief_turn or empty_turn)

    try:
        merged_brief, panel_patch = apply_brief_patch_with_cleanup(
            base_problem_brief=base_problem_brief,
            patch_payload=brief_turn.problem_brief_patch,
            history_lines=history_lines,
            api_key=api_key,
            model_name=model_name,
            workflow_mode=workflow_mode,
            current_panel=base_panel,
            recent_runs_summary=recent_runs_summary or [],
            researcher_steers=researcher_steers or [],
            test_problem_id=test_problem_id,
            user_text=user_text,
        )
        return (merged_brief, panel_patch, brief_turn)
    except Exception:
        log.exception("compute_brief_after_user_turn: brief patch merge failed")
        return (base_problem_brief, None, brief_turn)


def update_message_after_verification(
    *,
    message_id: int,
    new_content: str | None,
    set_verified_after_retry: bool,
) -> None:
    """Lift the ``meta.verifying`` flag on the assistant draft after the
    async verification pipeline finishes (or fails).

    - ``new_content`` rewrites the message body when the retry produced a
      different draft; pass ``None`` to leave the body untouched.
    - ``set_verified_after_retry`` records that a retry path was taken so
      researcher review can spot turns the probe touched.

    Called from the verification pipeline; safe to invoke even when the
    message row no longer exists (best-effort cleanup).
    """
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None:
            return
        meta: dict[str, Any] = {}
        if msg.meta_json:
            try:
                parsed = json.loads(msg.meta_json)
                if isinstance(parsed, dict):
                    meta = parsed
            except json.JSONDecodeError:
                meta = {}
        meta["verifying"] = False
        if set_verified_after_retry:
            meta["verified_after_retry"] = True
        msg.meta_json = json.dumps(meta, ensure_ascii=False)
        if new_content is not None:
            msg.content = new_content
        db.commit()


# Substring-only commit-phrase detector. Regex-free per project preference
# ([[feedback_no_regex_for_nl]]). Used by the recovery path in
# `_run_background_derivation` to spot a chat-turn that committed in the
# visible reply but emitted an empty `problem_brief_patch`.
_COMMIT_PHRASES: tuple[str, ...] = (
    "changes i made",
    "i've added",
    "i've set",
    "i'm using",
    "i've configured",
    "primary objective",
    "as a baseline",
    "default to",
    "i've defaulted",
    "i've enabled",
)


def _visible_reply_commits(visible_assistant_message: str | None) -> bool:
    """True iff the visible reply uses commit phrasing — the marker that
    tells the recovery path the brief patch can't legitimately be empty
    on this turn."""
    if not visible_assistant_message:
        return False
    text = visible_assistant_message.lower()
    return any(phrase in text for phrase in _COMMIT_PHRASES)


def _run_background_derivation(
    *,
    session_id: str,
    revision: int,
    user_text: str,
    workflow_mode: str,
    api_key: str,
    model_name: str,
    history_lines: list[tuple[str, str]],
    researcher_steers: list[str],
    recent_runs_summary: list[dict[str, Any]],
    base_problem_brief: dict[str, Any],
    base_panel: dict[str, Any] | None,
    cleanup_requested: bool,
    clear_requested: bool,
    is_run_acknowledgement: bool = False,
    is_answered_open_question: bool = False,
    is_config_save: bool = False,
    is_upload_context: bool = False,
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    visible_assistant_message: str | None = None,
    skip_brief_update_llm: bool = False,
    gate_status: dict[str, Any] | None = None,
    chat_turn_brief_patch: dict[str, Any] | None = None,
    chat_turn_replace_editable_items: bool = False,
    chat_turn_replace_open_questions: bool = False,
    chat_turn_cleanup_mode: bool = False,
    embedding_model: str | None = None,
) -> None:
    """Unified background pipeline for one chat turn.

    ``embedding_model`` is accepted for caller-API symmetry with the
    verification pipeline (which threads the session's embedding model
    through). Downstream LLM/embedding code reads the model from the
    session row directly; the kwarg here is reserved for future per-call
    overrides.

    Steps (all sequential — no parallel threads, so OQ maintenance and the
    brief-update merge cannot race):

    1. Brief-update LLM (skipped when ``skip_brief_update_llm=True``, e.g.
       on concept-question turns where the chat-turn classifier returned
       ``change_intent=False`` — we still want OQ maintenance to run on
       those turns to honour dismissals like *"skip this for now"*).
    2. Patch merge + ``filter_unanchored_new_goal_terms``.
    3. ``coerce_problem_brief_for_workflow`` (waterfall: assumption → OQ;
       demo: drop assumption rows).
    4. **OQ maintenance** — single focused Gemini call that owns add /
       drop / keep / rephrase end-to-end.
    5. Panel re-derivation + ``sync_optimization_allowed_after_participant_mutation``.
    6. ``log_workflow_compliance``.

    Folding OQ maintenance into this pipeline (instead of running it in a
    parallel thread) was needed because the prior parallel design had a
    race: BG derivation could write a new OQ from coercion AFTER the
    standalone maintenance pass had already taken its snapshot, then the
    maintenance write (with ``replace_open_questions=True``) wiped the
    fresh OQ. Sequencing avoids that entirely.
    """
    try:
        from app.services.llm import generate_problem_brief_update
        timeout_sec = get_settings().derivation_timeout_sec
        # Recovery: the chat-turn LLM is supposed to emit BOTH visible reply
        # and a matching patch in one structured call, but it sometimes drops
        # the patch even when its visible reply commits. Detect that
        # condition (commit phrasing in the visible reply + missing /
        # contentless patch) and fall back to the separate brief-update LLM
        # to fill the gap. Cheaper than re-running the whole structured call,
        # and only happens on suspicious turns — the common case stays a
        # single round-trip.
        commit_phrases_present = _visible_reply_commits(visible_assistant_message)
        patch_has_content = isinstance(chat_turn_brief_patch, dict) and any(
            chat_turn_brief_patch.get(k)
            for k in ("items", "goal_terms", "open_questions", "goal_summary")
        )
        if chat_turn_brief_patch is not None and patch_has_content:
            # The chat-turn LLM already produced a structured patch in the
            # same call as the visible reply (unified-call architecture in
            # generate_visible_chat_reply). Use it directly — no second LLM
            # round-trip.
            brief_turn = ProblemBriefUpdateTurn(
                problem_brief_patch=chat_turn_brief_patch,
                replace_editable_items=chat_turn_replace_editable_items,
                replace_open_questions=chat_turn_replace_open_questions,
                cleanup_mode=chat_turn_cleanup_mode,
            )
        elif (
            chat_turn_brief_patch is not None
            and not patch_has_content
            and not commit_phrases_present
        ):
            # Chat-turn emitted an empty patch and visible reply didn't claim
            # any change — this is the legitimate "no brief update needed"
            # case. Honour it.
            brief_turn = ProblemBriefUpdateTurn(
                problem_brief_patch=None,
                replace_editable_items=chat_turn_replace_editable_items,
                replace_open_questions=chat_turn_replace_open_questions,
                cleanup_mode=chat_turn_cleanup_mode,
            )
        elif skip_brief_update_llm:
            brief_turn = None  # Treated below as "no brief patch this turn".
        else:
            try:
                brief_turn = _run_with_timeout(
                    lambda: generate_problem_brief_update(
                        user_text=user_text,
                        history_lines=history_lines,
                        api_key=api_key,
                        model_name=model_name,
                        current_problem_brief=base_problem_brief,
                        workflow_mode=workflow_mode,
                        current_panel=base_panel,
                        recent_runs_summary=recent_runs_summary or None,
                        researcher_steers=researcher_steers or None,
                        cleanup_mode=cleanup_requested,
                        is_run_acknowledgement=is_run_acknowledgement,
                        is_answered_open_question=is_answered_open_question,
                        is_config_save=is_config_save,
                        is_upload_context=is_upload_context,
                        is_tutorial_active=is_tutorial_active,
                        test_problem_id=test_problem_id,
                        visible_assistant_message=visible_assistant_message,
                        gate_status=gate_status,
                    ),
                    timeout_sec,
                )
            except FuturesTimeoutError as exc:
                raise TimeoutError("Brief derivation timed out") from exc

        # `brief_turn is None` means the structured call failed (network /
        # parse / SDK error) — distinct from `brief_turn` returning empty
        # which means the LLM legitimately decided no patch was needed.
        # Surface the failure path so the participant gets a retry chip
        # instead of silently no-op.
        if brief_turn is None and not skip_brief_update_llm:
            persist_processing_failure(
                session_id,
                revision,
                "Brief-update structured call failed",
            )
            return

        patch_payload: dict[str, Any] | None = None
        if brief_turn is not None and brief_turn.problem_brief_patch:
            patch_payload = dict(brief_turn.problem_brief_patch)
        elif clear_requested:
            patch_payload = {"items": [], "open_questions": []}
        elif cleanup_requested:
            log.warning("Cleanup requested but model returned no brief patch for session %s", session_id)

        # Deterministic safety net for agile algorithm commitments: when the
        # visible reply named a search strategy (e.g. *"I've set GA as a
        # starting point"*) but neither the chat-turn nor the brief-update
        # LLM emitted the matching assumption row, synthesize one here so
        # the panel-derive picks up `algorithm=<canonical>` and the run gate
        # opens. Without this, the participant sees the agent confidently
        # commit to GA but the Run button stays greyed out — the GA-bug
        # symptom this safety net was added to address.
        if str(workflow_mode or "").strip().lower() == "agile":
            try:
                from app.services.visible_reply_commitments import (
                    extract_algorithm_commitment,
                    inject_algorithm_assumption,
                )

                committed_algo = extract_algorithm_commitment(visible_assistant_message)
                if committed_algo is not None:
                    new_patch, did_inject = inject_algorithm_assumption(
                        patch_payload, base_problem_brief, committed_algo
                    )
                    if did_inject:
                        log.info(
                            "Agile safety net injected algorithm=%s assumption row for session %s "
                            "(visible reply committed but brief patch lacked the row)",
                            committed_algo,
                            session_id,
                        )
                        patch_payload = new_patch
            except Exception:  # pragma: no cover — never block derivation on the safety net
                log.exception("Algorithm-commitment safety-net injection failed for session %s", session_id)

        effective_problem_brief = base_problem_brief
        if patch_payload is not None:
            if is_run_acknowledgement:
                patch_payload = _sanitize_run_ack_patch_payload(
                    patch_payload,
                    workflow_mode=workflow_mode,
                    test_problem_id=test_problem_id,
                )
            elif (
                cleanup_requested
                or (brief_turn is not None and brief_turn.cleanup_mode)
                or (brief_turn is not None and brief_turn.replace_editable_items)
            ):
                patch_payload["replace_editable_items"] = True
            if clear_requested:
                patch_payload["replace_open_questions"] = True
            elif brief_turn is not None and brief_turn.replace_open_questions:
                patch_payload["replace_open_questions"] = True
            effective_problem_brief, meta = apply_brief_patch_with_cleanup(
                base_problem_brief=base_problem_brief,
                patch_payload=patch_payload,
                history_lines=history_lines,
                api_key=api_key,
                model_name=model_name,
                workflow_mode=workflow_mode,
                current_panel=base_panel,
                recent_runs_summary=recent_runs_summary,
                researcher_steers=researcher_steers,
                test_problem_id=test_problem_id,
                enable_auto_open_question_cleanup=True,
                is_run_acknowledgement=is_run_acknowledgement,
                cleanup_mode=cleanup_requested
                or bool(brief_turn is not None and brief_turn.cleanup_mode),
                user_text=user_text,
            )
            if int(meta.get("removed_total", 0)) > 0:
                log.info("Auto open-question cleanup removed %s question(s)", meta.get("removed_total"))
            if (
                cleanup_requested
                or (brief_turn is not None and brief_turn.cleanup_mode)
            ) and base_panel:
                effective_problem_brief = sync_problem_brief_from_panel(
                    effective_problem_brief, base_panel, test_problem_id=test_problem_id
                )

        # Apply workflow-specific invariants (waterfall: assumptions → OQs;
        # demo: drop assumptions). Idempotent on already-coerced briefs, so
        # safe to run on the no-patch path too.
        effective_problem_brief = coerce_problem_brief_for_workflow(
            effective_problem_brief, workflow_mode
        )

        # OQ maintenance — single focused Gemini call that owns add / drop /
        # keep / rephrase end-to-end. Runs **inside** this pipeline (not in
        # a parallel thread) so it sequences AFTER the patch merge and the
        # workflow coercion. The earlier parallel-thread design had a race:
        # the standalone maintenance pass would snapshot OQs, the LLM would
        # decide based on that snapshot, then between the snapshot and the
        # write the BG derivation could append a fresh "Confirm or correct"
        # OQ from coercion — and the maintenance write (with
        # ``replace_open_questions=True``) would wipe it. Sequencing fixes
        # that. Skipped only on synthetic / non-conversational turns whose
        # OQ contract is owned by a more-specific path.
        should_maintain_oqs = not (
            cleanup_requested
            or clear_requested
            or is_run_acknowledgement
            or is_upload_context
            or is_config_save
            or is_answered_open_question
        )
        if (
            should_maintain_oqs
            and api_key
            and api_key.strip()
            and visible_assistant_message
            and visible_assistant_message.strip()
        ):
            try:
                from app.services.llm import maintain_definition_state

                current_oqs_for_maintenance = list(
                    effective_problem_brief.get("open_questions") or []
                )
                mode_lower = str(workflow_mode or "").strip().lower()
                # In agile/demo, assumption rows participate in the
                # lifecycle pass too (modify-promote, drop, rephrase).
                # Waterfall briefs never have assumption rows, so the
                # current_assumptions input stays None on those turns.
                current_assumptions: list[dict[str, Any]] = []
                if mode_lower in ("agile", "demo"):
                    for item in (effective_problem_brief.get("items") or []):
                        if not isinstance(item, dict):
                            continue
                        if str(item.get("kind") or "").strip().lower() != "assumption":
                            continue
                        item_id = str(item.get("id") or "").strip()
                        text_val = str(item.get("text") or "").strip()
                        if item_id and text_val:
                            current_assumptions.append(
                                {"id": item_id, "text": text_val}
                            )

                # Fast-path skip: nothing for the LLM to act on. Skip when
                # there are no current OQs, no current assumptions worth
                # acting on, and the visible reply contains no question
                # marker. This keeps cold and trivially-acknowledging
                # turns free of the maintenance round-trip.
                visible_has_question = "?" in (visible_assistant_message or "")
                if (
                    current_oqs_for_maintenance
                    or current_assumptions
                    or visible_has_question
                ):
                    recent_gathered_texts = [
                        str(item.get("text") or "")
                        for item in (effective_problem_brief.get("items") or [])
                        if isinstance(item, dict)
                        and str(item.get("kind") or "").strip().lower() == "gathered"
                        and str(item.get("text") or "").strip()
                    ][-8:]
                    maintain_result = maintain_definition_state(
                        workflow_mode=workflow_mode,
                        user_message=user_text,
                        visible_reply=visible_assistant_message,
                        current_open_questions=current_oqs_for_maintenance,
                        current_assumptions=current_assumptions or None,
                        recent_gathered=recent_gathered_texts,
                        api_key=api_key,
                        model_name=model_name,
                        test_problem_id=test_problem_id,
                        gate_status=gate_status,
                    )
                    if maintain_result is not None:
                        from app.problem_brief import merge_problem_brief_patch

                        new_oqs = maintain_result.get("open_questions") or []
                        effective_problem_brief = merge_problem_brief_patch(
                            effective_problem_brief,
                            {
                                "open_questions": new_oqs,
                                "replace_open_questions": True,
                            },
                        )

                        # Apply assumption-row decisions in agile/demo. The
                        # actions mutate items[] in place by id; provenance
                        # on promote_to_gathered follows ORIGIN — the user
                        # locked it in, so we set source="user" (memory:
                        # feedback_provenance_origin_not_phrasing).
                        if (
                            mode_lower in ("agile", "demo")
                            and maintain_result.get("assumption_actions")
                        ):
                            effective_problem_brief = _apply_assumption_actions(
                                effective_problem_brief,
                                maintain_result["assumption_actions"],
                            )

                        # Re-coerce in case maintenance left an assumption
                        # implication (it shouldn't — this is defensive).
                        effective_problem_brief = coerce_problem_brief_for_workflow(
                            effective_problem_brief, workflow_mode
                        )
            except Exception:  # pragma: no cover — never block derivation
                log.exception(
                    "Definition-maintenance step failed for session %s", session_id
                )

        # Deterministic post-derivation compliance check. Logs warnings when
        # the chat / brief-update LLMs drift from mode-specific rules (e.g.
        # waterfall reply asks a question but no OQ recorded; agile/demo
        # claims a brief change but the brief is unchanged). The natural-
        # language judgement ("did the reply ask a question / claim a
        # change?") is reported by the brief-update LLM via its structured
        # `visible_reply_intent` field — no regex over chat text. The check
        # itself is pure set/diff logic and runs in microseconds. Skipped
        # when the brief-update call was bypassed (no intent data) or
        # failed to populate `visible_reply_intent`.
        try:
            intent = getattr(brief_turn, "visible_reply_intent", None) if brief_turn else None
            if intent is not None:
                from app.services.workflow_compliance import (
                    log_workflow_compliance,
                    synthesize_missing_oq_for_waterfall,
                )
                # Waterfall auto-repair: when the visible reply asked a
                # question but the LLM didn't land an OQ AND we know what's
                # missing from the gate, synthesise a templated OQ. This is
                # a safety net — the prompt-side rules in §4 are the
                # primary path. Synthesis text is deterministic (templated
                # from gate_status.missing), not parsed from the reply.
                synthesised = synthesize_missing_oq_for_waterfall(
                    workflow_mode=workflow_mode,
                    base_brief=base_problem_brief,
                    new_brief=effective_problem_brief,
                    visible_reply_asks_user_question=bool(
                        getattr(intent, "asks_user_question", False)
                    ),
                    gate_status=gate_status,
                )
                if synthesised is not None:
                    from app.problem_brief import merge_problem_brief_patch

                    effective_problem_brief = merge_problem_brief_patch(
                        effective_problem_brief,
                        {
                            "open_questions": [synthesised],
                            "replace_open_questions": False,
                        },
                    )
                    effective_problem_brief = coerce_problem_brief_for_workflow(
                        effective_problem_brief, workflow_mode
                    )
                    log.info(
                        "Synthesised waterfall OQ for session %s (template=%s)",
                        session_id,
                        synthesised["text"][:60],
                    )

                log_workflow_compliance(
                    session_id=session_id,
                    workflow_mode=workflow_mode,
                    base_brief=base_problem_brief,
                    new_brief=effective_problem_brief,
                    visible_reply_claims_brief_change=bool(
                        getattr(intent, "claims_brief_change", False)
                    ),
                    visible_reply_asks_user_question=bool(
                        getattr(intent, "asks_user_question", False)
                    ),
                    is_run_acknowledgement=is_run_acknowledgement,
                )
        except Exception:  # pragma: no cover — never block derivation on the check
            log.exception("Workflow compliance check failed for session %s", session_id)

        with SessionLocal() as db:
            row = db.get(StudySession, session_id)
            if row is None or row.status != "active" or row.processing_revision != revision:
                return
            if effective_problem_brief != helpers.problem_brief_dict(row):
                row.problem_brief_json = json.dumps(effective_problem_brief)
            row.brief_status = "ready"
            row.config_status = "pending"
            row.processing_error = None
            helpers.touch_session(row)
            db.commit()
            db.refresh(row)

            # On a config-save turn the participant just authored the panel via
            # the form; re-deriving the panel from the brief here can flip
            # goal-term types or weights back (the LLM/heuristic derivation is
            # not guaranteed to reproduce the exact panel the user just saved).
            # The PATCH endpoint already synced the brief from that panel, so
            # the brief and panel are consistent — skip the panel re-derivation.
            if not is_config_save:
                # If the hidden brief pass made no effective change, skip the config LLM and use
                # heuristic derivation only (same stability as sync when the brief is unchanged).
                brief_unchanged = json.dumps(
                    normalize_problem_brief(effective_problem_brief), sort_keys=True, default=str
                ) == json.dumps(normalize_problem_brief(base_problem_brief), sort_keys=True, default=str)
                config_api_key = None if brief_unchanged else api_key

                sync.sync_panel_from_problem_brief(
                    row,
                    db,
                    effective_problem_brief,
                    api_key=config_api_key,
                    model_name=model_name,
                    workflow_mode=workflow_mode,
                    recent_runs_summary=recent_runs_summary,
                    preserve_missing_managed_fields=True,
                )

            row = db.get(StudySession, session_id)
            if row is None or row.processing_revision != revision:
                return
            row.brief_status = "ready"
            row.config_status = helpers.desired_config_status(row)
            row.processing_error = None
            helpers.touch_session(row)
            helpers.sync_optimization_allowed_after_participant_mutation(row)
            db.commit()
    except sync.GoalTermValidationError as exc:
        log.exception("Background derivation goal-term validation failed for session %s", session_id)
        with SessionLocal() as db:
            row = db.get(StudySession, session_id)
            if row is not None and row.processing_revision == revision:
                helpers.fail_processing_state(row, exc.processing_error_text())
                append_message(
                    db,
                    session_id,
                    "assistant",
                    "I could not sync the configuration because goal terms were inconsistent with the current definition. "
                    "Please retry sync after confirming the Definition items cover each goal term.",
                    True,
                    kind="panel",
                )
                db.commit()
        return
    except Exception:
        log.exception("Background derivation failed for session %s", session_id)
        persist_processing_failure(session_id, revision, "Background problem derivation failed")


def launch_background_derivation(**kwargs: Any) -> None:
    thread = Thread(
        target=_run_background_derivation,
        kwargs=kwargs,
        daemon=True,
        name=f"session-derive-{kwargs['session_id']}",
    )
    thread.start()


# NOTE: ``launch_background_oq_maintenance`` was removed. OQ maintenance
# now lives **inside** ``_run_background_derivation`` as a sequential step
# after the patch merge + workflow coercion. The separate-thread design had
# a race: the standalone task would snapshot OQs, the LLM would decide based
# on that snapshot, and BG derivation could append a fresh "Confirm or
# correct: …" OQ from coercion in between — then the maintenance write
# (with ``replace_open_questions=True``) would wipe it. Sequencing fixes it.
# The chat handler now launches the unified pipeline on every real turn,
# passing ``skip_brief_update_llm=True`` when ``change_intent=False`` so
# OQ maintenance still runs (e.g. for dismissals like *"skip this for now"*).
