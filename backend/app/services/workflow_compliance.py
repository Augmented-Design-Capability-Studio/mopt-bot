"""Deterministic post-derivation compliance check for workflow-mode invariants.

The chat + brief-update LLMs sometimes drift from workflow-specific rules
(e.g. waterfall replies that ask a clarifying question without recording it
as an ``open_questions`` entry, or agile/demo replies that claim a brief
change while the stored brief is unchanged).

This module is **regex-free**. The natural-language part of the question
("did the visible reply ask a question?", "did it claim a brief change?")
is answered by the brief-update LLM itself: it already sees the visible
reply and produces a structured ``visible_reply_intent`` field with two
booleans. We use those flags here and just compare them against the actual
brief delta — no substring matching on free-form text.

Violations are surfaced two ways:

1. ``logging.warning`` for terminal / journal visibility.
2. A hidden ``ChatMessage`` row (``kind="compliance"``,
   ``visible_to_participant=False``) so the researcher UI shows the issue
   inline at the exact turn it happened, and the violation persists across
   server restarts for later analysis.

Design notes:

- **No new LLM calls.** The intent classification is folded into the
  existing brief-update structured call (one extra field in its JSON
  schema), so this check stays effectively free at runtime.
- **No regex on natural language.** Every NL judgement comes from the
  brief-update LLM's ``visible_reply_intent``.
- **Read-only on the brief.** This module never mutates ``problem_brief``.
- **Problem-agnostic.** No domain key names live here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def _open_question_ids(brief: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for q in brief.get("open_questions") or []:
        if isinstance(q, dict):
            qid = str(q.get("id") or "")
            if qid:
                out.add(qid)
    return out


def _has_open_status_question(brief: dict[str, Any]) -> bool:
    for q in brief.get("open_questions") or []:
        if not isinstance(q, dict):
            continue
        status = str(q.get("status") or "open").strip().lower()
        if status == "open":
            return True
    return False


def _briefs_differ_in_editable_state(
    base: dict[str, Any], new: dict[str, Any]
) -> bool:
    """True iff the items, open_questions, goal_terms, or summaries differ."""
    keys = ("items", "open_questions", "goal_terms", "goal_summary", "run_summary")
    for k in keys:
        if base.get(k) != new.get(k):
            return True
    return False


def assess_workflow_compliance(
    *,
    workflow_mode: str | None,
    base_brief: dict[str, Any] | None,
    new_brief: dict[str, Any] | None,
    visible_reply_claims_brief_change: bool = False,
    visible_reply_asks_user_question: bool = False,
    is_run_acknowledgement: bool = False,
) -> list[str]:
    """Return a list of human-readable violation strings (empty when compliant).

    The two ``visible_reply_*`` booleans come from the brief-update LLM's
    ``visible_reply_intent`` field — they reflect the model's own judgement
    about what the visible reply did, so this function never has to inspect
    the reply text itself. Caller is expected to log each violation; this
    function never mutates the brief and never calls out to the network.
    """
    if not isinstance(base_brief, dict) or not isinstance(new_brief, dict):
        return []
    mode = str(workflow_mode or "").strip().lower()
    issues: list[str] = []

    if mode == "waterfall":
        if visible_reply_asks_user_question:
            base_ids = _open_question_ids(base_brief)
            new_ids = _open_question_ids(new_brief)
            added = new_ids - base_ids
            if not added and not _has_open_status_question(new_brief):
                issues.append(
                    "waterfall: visible reply asked a question but no open "
                    "questions are recorded (no new OQ added, no existing "
                    "open-status OQ remains)"
                )
        # Run-ack with material gaps: waterfall prompt asks for "one or two"
        # OQs unless the spec is fully covered. We can't know "fully covered"
        # cheaply, so only flag when the brief truly has zero OQs at all on a
        # run-ack — that's an unambiguous miss.
        if is_run_acknowledgement and not (new_brief.get("open_questions") or []):
            issues.append(
                "waterfall run-ack: brief has zero open questions after a "
                "run; specification likely incomplete"
            )

    elif mode in ("agile", "demo"):
        if visible_reply_claims_brief_change and not _briefs_differ_in_editable_state(
            base_brief, new_brief
        ):
            issues.append(
                f"{mode}: visible reply claimed a brief change "
                f"('Changes I made: ...' / 'I've added/bumped/...') but "
                f"the stored brief is unchanged"
            )

    return issues


_MISSING_OQ_TEMPLATES: dict[str, str] = {
    # Templated OQ texts keyed by `gate_status.missing` head item. These are
    # the only synthesised questions — anything else falls through to the
    # compliance warning. Templates are problem-agnostic and avoid naming
    # specific solver internals so they read as natural participant prompts.
    "search_strategy": (
        "Which search method should we use? Options include genetic "
        "search (GA), particle swarm (PSO), or simulated annealing (SA)."
    ),
    "goal_term": (
        "What is the primary objective you want to optimize for this run?"
    ),
}


def synthesize_missing_oq_for_waterfall(
    *,
    workflow_mode: str | None,
    base_brief: dict[str, Any] | None,
    new_brief: dict[str, Any] | None,
    visible_reply_asks_user_question: bool,
    gate_status: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Auto-repair: build a single OQ row when waterfall asks a question
    in chat but the LLM forgot to record it.

    Returns ``None`` when no synthesis is appropriate (mode != waterfall,
    no question asked, OQ delta already exists, gate has nothing to
    template against, or template not found). The returned dict is shaped
    like a fresh ``open_questions`` entry — caller is expected to append
    it to the brief and re-run coercion.

    Synthesis is **deterministic**: the OQ text is templated from
    ``gate_status.missing[0]`` (the highest-priority missing prerequisite),
    not parsed from the assistant's free-form reply. This keeps the auto-
    repair regex-free; the trade-off is it only fires for the prerequisites
    we have templates for (currently ``search_strategy``, ``goal_term``).
    Other unrecorded questions still surface as a compliance warning.
    """
    if str(workflow_mode or "").strip().lower() != "waterfall":
        return None
    if not visible_reply_asks_user_question:
        return None
    if not isinstance(base_brief, dict) or not isinstance(new_brief, dict):
        return None
    base_ids = _open_question_ids(base_brief)
    new_ids = _open_question_ids(new_brief)
    if (new_ids - base_ids) or _has_open_status_question(new_brief):
        # Either a new OQ was added this turn, or an open OQ already
        # captures whatever the question is. Nothing to repair.
        return None
    if not isinstance(gate_status, dict):
        return None
    missing = gate_status.get("missing") or []
    if not isinstance(missing, list) or not missing:
        return None
    head = str(missing[0] or "").strip()
    template = _MISSING_OQ_TEMPLATES.get(head)
    if not template:
        return None
    return {"text": template, "status": "open"}


def log_workflow_compliance(
    *,
    session_id: str,
    workflow_mode: str | None,
    base_brief: dict[str, Any] | None,
    new_brief: dict[str, Any] | None,
    visible_reply_claims_brief_change: bool = False,
    visible_reply_asks_user_question: bool = False,
    is_run_acknowledgement: bool = False,
    persist: bool = True,
) -> list[str]:
    """Run :func:`assess_workflow_compliance`, log warnings, and (optionally)
    persist a hidden ``ChatMessage`` row so the researcher UI sees each
    violation inline at the exact turn it happened.

    The persistence path opens its own short-lived DB session so callers
    don't need to thread one through. If persistence fails (DB lock, model
    import error, etc.) we still log and return the issues — the compliance
    check must never block derivation.

    Returns the issue list so callers can also surface it elsewhere (tests,
    future repair pass).
    """
    issues = assess_workflow_compliance(
        workflow_mode=workflow_mode,
        base_brief=base_brief,
        new_brief=new_brief,
        visible_reply_claims_brief_change=visible_reply_claims_brief_change,
        visible_reply_asks_user_question=visible_reply_asks_user_question,
        is_run_acknowledgement=is_run_acknowledgement,
    )
    for issue in issues:
        log.warning("Workflow compliance issue (session %s): %s", session_id, issue)

    if issues and persist:
        try:
            _persist_compliance_message(
                session_id=session_id,
                workflow_mode=workflow_mode,
                issues=issues,
                is_run_acknowledgement=is_run_acknowledgement,
            )
        except Exception:  # pragma: no cover — never block derivation
            log.exception(
                "Failed to persist compliance message for session %s", session_id
            )

    return issues


def _persist_compliance_message(
    *,
    session_id: str,
    workflow_mode: str | None,
    issues: list[str],
    is_run_acknowledgement: bool,
) -> None:
    """Write one hidden ``ChatMessage`` summarising the issues for this turn."""
    from app.database import SessionLocal
    from app.models import ChatMessage

    summary = (
        f"Workflow compliance ({workflow_mode or 'unknown'}): "
        f"{len(issues)} issue(s) — " + "; ".join(issues)
    )
    meta = {
        "workflow_mode": workflow_mode,
        "is_run_acknowledgement": bool(is_run_acknowledgement),
        "issues": list(issues),
    }
    with SessionLocal() as db:
        db.add(
            ChatMessage(
                session_id=session_id,
                role="system",
                content=summary,
                visible_to_participant=False,
                kind="compliance",
                meta_json=json.dumps(meta, ensure_ascii=False),
            )
        )
        db.commit()
