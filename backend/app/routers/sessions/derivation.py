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
    consolidated = _enforce_session_monitors(consolidated, workflow_mode)
    return consolidated, {"removed_total": 0, **run_meta}


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
        _append_oq(_MONITOR_OQ_GOAL_ID, _MONITOR_OQ_GOAL_TEXT, "primary_goal")

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
    if not extras:
        return brief
    next_brief = dict(brief)
    base_items = list(brief.get("items") or [])
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


