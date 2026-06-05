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
    CARRIER_ONLY_GOAL_TERM_KEYS,
    CONFIG_ITEM_PREFIX,
    merge_problem_brief_patch,
    normalize_problem_brief,
)

from . import helpers

log = logging.getLogger(__name__)
def _format_run_violations_summary(
    violations: Any, test_problem_id: str | None
) -> str:
    """Render a one-line plain-English violations summary via the port.

    Returns empty string when there are no violations or the port can't
    render them. The port returns a list of short clauses (e.g.
    ``["1 time-window stops late", "6 units over capacity"]``); we join
    with "; " for a single display line.
    """
    if not isinstance(violations, dict) or test_problem_id is None:
        return ""
    try:
        from app.problems.registry import get_study_port

        extras = get_study_port(test_problem_id).format_run_context_violation_details(
            violations
        )
    except Exception:  # pragma: no cover — defensive
        return ""
    if not isinstance(extras, list):
        return ""
    parts = [str(line).strip() for line in extras if isinstance(line, str) and line.strip()]
    return "; ".join(parts)


def _compute_delta_from_prev(
    latest_cost: Any, prev_entry: dict[str, Any] | None
) -> str:
    """Render a single-line cost delta vs. the previous run, or empty when
    there's nothing comparable. Uses raw arithmetic on the structured cost
    fields — no NL parsing."""
    if not isinstance(prev_entry, dict):
        return ""
    if not (isinstance(latest_cost, (int, float)) and not isinstance(latest_cost, bool)):
        return ""
    prev_cost = prev_entry.get("cost")
    if not (isinstance(prev_cost, (int, float)) and not isinstance(prev_cost, bool)):
        return ""
    prev_n = prev_entry.get("run_number")
    if not isinstance(prev_n, int):
        return ""
    diff = float(latest_cost) - float(prev_cost)
    if diff == 0:
        return f"same cost as Run #{prev_n}"
    sign = "+" if diff > 0 else "−"
    return f"{sign}{abs(diff):.2f} cost vs Run #{prev_n}"


def _build_run_summary_entry(
    latest: dict[str, Any],
    prev_entry: dict[str, Any] | None,
    test_problem_id: str | None,
) -> dict[str, Any] | None:
    """Build one ``RunSummaryEntry``-shaped dict from a ``recent_runs_summary``
    record + the previous structured entry for delta computation. Returns
    ``None`` when the input record lacks a usable ``run_number``."""
    run_number = latest.get("run_number")
    if not isinstance(run_number, int) or isinstance(run_number, bool):
        return None
    cost_raw = latest.get("cost")
    cost: float | None
    if isinstance(cost_raw, (int, float)) and not isinstance(cost_raw, bool):
        cost = float(cost_raw)
    else:
        cost = None
    return {
        "run_number": run_number,
        "cost": cost,
        "ok": bool(latest.get("ok")),
        "algorithm": str(latest.get("algorithm") or "").strip(),
        "violations_summary": _format_run_violations_summary(
            latest.get("violations"), test_problem_id
        ),
        "delta_from_prev": _compute_delta_from_prev(cost, prev_entry),
    }


def consolidate_runs(
    brief: dict[str, Any],
    *,
    recent_runs_summary: list[dict[str, Any]] | None = None,
    is_run_acknowledgement: bool = False,
    test_problem_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Append (or replace) the latest run's structured entry in ``brief.runs``.

    Server-managed end-to-end: the LLM never writes to ``brief.runs`` — this
    is the sole canonical writer. Replaces the legacy ``consolidate_run_summary``
    rolling-string path (which drifted because the LLM had to maintain prose).

    Fires only on run-acknowledgement turns. No-op when ``is_run_acknowledgement``
    is false or when ``recent_runs_summary`` is empty. Idempotent on the same
    ``run_number`` (resume / retry paths just overwrite the entry).
    """
    normalized = normalize_problem_brief(brief)
    if not is_run_acknowledgement or not recent_runs_summary:
        return normalized, {"appended": 0}
    latest = recent_runs_summary[-1]
    if not isinstance(latest, dict):
        return normalized, {"appended": 0}

    existing_runs = list(normalized.get("runs") or [])
    latest_run_number = latest.get("run_number")
    # Previous entry for delta calc: most recent existing entry with a
    # different run_number.
    prev_entry = next(
        (
            r
            for r in reversed(existing_runs)
            if isinstance(r, dict) and r.get("run_number") != latest_run_number
        ),
        None,
    )
    new_entry = _build_run_summary_entry(latest, prev_entry, test_problem_id)
    if new_entry is None:
        return normalized, {"appended": 0}

    # Replace any existing entry with the same run_number (resume/retry), else append.
    out_runs = [
        r
        for r in existing_runs
        if not (isinstance(r, dict) and r.get("run_number") == new_entry["run_number"])
    ]
    out_runs.append(new_entry)

    updated = {**normalized, "runs": out_runs}
    return normalize_problem_brief(updated), {"appended": 1}


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

    # Live goal-term keys. A canonical ``config-weight-<key>`` row is SERVER-OWNED
    # — a deterministic projection of ``goal_terms`` re-synthesized every turn by
    # ``_synthesize_canonical_weight_items``. Its lifecycle follows the goal term,
    # not an LLM drop decision, so a ``drop`` targeting one is refused while the
    # term is still live (see the drop branch below).
    gt = brief.get("goal_terms")
    live_goal_keys: set[str] = (
        {k for k in gt if isinstance(k, str) and k.strip()} if isinstance(gt, dict) else set()
    )

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
            # Refuse to drop a canonical weight row whose goal term is still live.
            # The row is re-synthesized from ``goal_terms`` a few steps earlier in
            # the apply stage, so honoring the drop deletes the freshly-rebuilt row
            # and orphans an active solver term — leaving the Definition with no
            # line explaining a goal that's still in effect (P_0603: the agent
            # renamed the capacity row to ``…-run3`` and dropped the canonical id
            # while keeping ``capacity_penalty`` at weight 30). A genuine removal
            # retires the goal_term key instead; once it's gone no row is
            # synthesized and this guard is inert, so real deletions still work.
            if (
                item_id.startswith("config-weight-")
                and item_id[len("config-weight-"):] in live_goal_keys
            ):
                log.info(
                    "Refused assumption-action drop of canonical weight row %s; "
                    "goal_term still live",
                    item_id,
                )
                continue
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


def _apply_oq_actions(
    brief: dict[str, Any], actions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Apply per-row OQ lifecycle decisions emitted by the main-turn LLM.

    Symmetric to ``_apply_assumption_actions``. Actions:

    - ``keep``: no-op.
    - ``rephrase``: update only ``text`` to ``rephrased_text``; preserve
      status/topic/anchor.
    - ``drop``: remove the OQ entirely. Use when the answer is already
      represented elsewhere (e.g. a committed ``goal_terms[K]`` plus a
      synthesized ``config-weight-K`` row).
    - ``mark_answered``: write ``status="answered" + answer_text``. The
      next normalize pass folds the row into a gathered item via
      ``_promote_answered_open_questions_to_gathered``.

    Unknown ids / unknown actions are silently ignored — the same
    permissiveness as the assumption-action sibling, so stale state
    can't pause a turn. Foundational-topic OQs are not protected here
    on purpose: the server's monitor state machine re-adds them on the
    next pass if they were dropped prematurely.
    """
    if not actions:
        return brief
    questions = list(brief.get("open_questions") or [])
    by_id: dict[str, int] = {}
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        qid = str(question.get("id") or "").strip()
        if qid:
            by_id[qid] = index

    drop_ids: set[str] = set()
    for raw_action in actions:
        if not isinstance(raw_action, dict):
            continue
        qid = str(raw_action.get("id") or "").strip()
        action = str(raw_action.get("action") or "").strip().lower()
        if not qid or action not in {"keep", "rephrase", "drop", "mark_answered"}:
            continue
        # Server-managed companion OQs (`auto-oq-companion-<key>`) are owned by
        # `reconcile_companion_oqs`: they appear when a companion-bearing goal
        # term (e.g. VRPTW `worker_preference` → `driver_preferences`) has no
        # rules yet, and auto-drop the moment the rules land. The agent must NOT
        # be able to drop/mark_answered them while the companion is still empty
        # — doing so kills the only thing still asking for the rules and lets
        # the term vanish silently (observed in P_0603: agent dropped the
        # companion OQ, claimed "added", but no rules were ever committed).
        if qid.startswith("auto-oq-companion-") and action in {"drop", "mark_answered"}:
            continue
        if qid not in by_id:
            continue
        idx = by_id[qid]
        target = questions[idx]
        if not isinstance(target, dict):
            continue
        if action == "keep":
            continue
        if action == "drop":
            drop_ids.add(qid)
            continue
        if action == "rephrase":
            rephrased = str(raw_action.get("rephrased_text") or "").strip()
            if not rephrased:
                continue
            new_q = dict(target)
            new_q["text"] = rephrased
            questions[idx] = new_q
            continue
        if action == "mark_answered":
            answer_text = str(raw_action.get("answer_text") or "").strip()
            if not answer_text:
                # No answer to record — treat as a no-op rather than
                # silently flipping status without content.
                continue
            new_q = dict(target)
            new_q["status"] = "answered"
            new_q["answer_text"] = answer_text
            questions[idx] = new_q

    if drop_ids:
        questions = [
            q
            for q in questions
            if not (
                isinstance(q, dict)
                and str(q.get("id") or "").strip() in drop_ids
            )
        ]

    return {**brief, "open_questions": questions}


def _validated_algorithm_name(text: Any) -> str | None:
    """Return a canonical algorithm name if ``text`` names one, else None.

    Closed-vocabulary check only — never an open NL match. Accepts both a
    bare canonical token ("GA") and a phrase the user might type
    ("genetic search (GA)") by deferring to the same alias scanner the
    brief→panel seeds use. See [[feedback_no_regex_for_nl]]: this is an
    enum membership test against the fixed algorithm catalog, not keyword
    matching on free text.
    """
    from app.algorithm_catalog import normalize_algorithm_name
    from app.services.goal_term_anchoring import extract_algorithm_from_brief

    raw = str(text or "").strip()
    if not raw:
        return None
    direct = normalize_algorithm_name(raw)
    if direct:
        return direct
    return extract_algorithm_from_brief([{"text": raw}])


def _carrier_search_strategy_algorithm(brief: dict[str, Any] | None) -> str | None:
    """Return the algorithm stored in the search-strategy carrier
    (``goal_terms.search_strategy.properties.algorithm``), or None."""
    if not isinstance(brief, dict):
        return None
    gt = brief.get("goal_terms")
    if not isinstance(gt, dict):
        return None
    ss = gt.get("search_strategy")
    if not isinstance(ss, dict):
        return None
    props = ss.get("properties")
    if not isinstance(props, dict):
        return None
    algo = props.get("algorithm")
    return algo.strip() if isinstance(algo, str) and algo.strip() else None


def _set_search_strategy_algorithm(
    brief: dict[str, Any], algorithm: str
) -> dict[str, Any]:
    """Return a copy of ``brief`` with the search-strategy carrier set to
    ``algorithm`` (creating the nested containers as needed). Used to commit a
    participant's chat answer deterministically, so the choice doesn't depend
    on the LLM also having emitted the carrier itself."""
    out = deepcopy(brief)
    goal_terms = out.get("goal_terms")
    if not isinstance(goal_terms, dict):
        goal_terms = {}
        out["goal_terms"] = goal_terms
    entry = goal_terms.get("search_strategy")
    if not isinstance(entry, dict):
        entry = {}
        goal_terms["search_strategy"] = entry
    # Carrier-only or not, a goal_terms entry still needs the scalar trio
    # (weight/type/rank) or ``normalize_problem_brief`` drops it as malformed —
    # so a FRESHLY CREATED carrier (no agent-committed entry to update, e.g. a
    # user answering the search-strategy OQ in chat or the textarea) must be
    # completed here, else it vanishes on the next normalize and the OQ bounces
    # back open (P_lk). An existing (agent-committed) entry keeps its own scalars.
    if not isinstance(entry.get("weight"), (int, float)) or isinstance(entry.get("weight"), bool):
        entry["weight"] = 1.0
    if not (isinstance(entry.get("type"), str) and entry.get("type").strip()):
        entry["type"] = "custom"
    rank = entry.get("rank")
    if not (isinstance(rank, int) and not isinstance(rank, bool) and rank > 0):
        existing_ranks = [
            int(e["rank"])
            for k, e in goal_terms.items()
            if k != "search_strategy"
            and isinstance(e, dict)
            and isinstance(e.get("rank"), (int, float))
            and not isinstance(e.get("rank"), bool)
        ]
        entry["rank"] = (max(existing_ranks) + 1) if existing_ranks else 1
    props = entry.get("properties")
    if not isinstance(props, dict):
        props = {}
        entry["properties"] = props
    props["algorithm"] = algorithm
    return out


def gate_unauthorized_search_strategy_commit(
    *,
    effective_brief: dict[str, Any],
    base_brief: dict[str, Any],
    oq_actions: list[dict[str, Any]],
    workflow_mode: str | None,
    user_search_strategy_choice: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Waterfall-only structural gate: block algorithm commits the user
    never authorized.

    The search-strategy choice is one of the four canonical waterfall axes
    (see [[project_workflow_axes]]): in waterfall the algorithm lives as an
    open question until the **user** answers it. The main-turn LLM is not
    permitted to silently pick one. The prompt says so, but a prompt rule
    can't enforce ownership — observed in P_0529, where the upload turn
    forged ``goal_terms.search_strategy.properties.algorithm = "GA"``, added
    a ``source: user`` row, and dropped the open question, all without the
    participant ever choosing. See [[feedback_no_prompt_bandages]].

    Authorization (any one suffices):

    - the **base** (pre-turn) brief already carries a search-strategy signal
      (carrier or a gathered algorithm row). Because this gate runs every
      turn, a forged carrier never survives into base — so a base mention
      can only have come from a legitimate prior answer (the participant's
      OQ-textarea answer is promoted to a gathered row, which counts). This
      lets re-affirmations and tuning turns flow untouched; and
    - the LLM marks the OQ answered THIS turn via ``oq_actions`` with an
      ``answer_text`` that names a real algorithm — the *loose* chat-answer
      path the user explicitly wanted (answering OQs through chat is a
      feature). A forged-but-valid name can still slip through; that
      residual risk is accepted as the cost of chat answers.

    A bare ``drop`` is never authorization — dropping the question without
    an answer is exactly the forgery we're guarding against.

    When unauthorized, strip the algorithm carrier + any algorithm-bearing
    items the patch introduced, and refuse the ``drop`` / ``mark_answered``
    OQ actions targeting the search-strategy question. The downstream
    session monitor then re-adds the canonical OQ (the carrier is gone, so
    ``brief_mentions_search_strategy`` reads False again). Returns the
    possibly-stripped brief plus the OQ actions the caller should still
    apply.
    """
    if str(workflow_mode or "").strip().lower() != "waterfall":
        return effective_brief, oq_actions
    if not isinstance(effective_brief, dict):
        return effective_brief, oq_actions

    # Authorization by explicit participant choice: when the main-turn LLM
    # reports that the PARTICIPANT named an algorithm this turn (their answer to
    # the search-strategy question, as a structured field — not parsed from the
    # reply), commit it deterministically. The server, not the LLM, sets the
    # carrier, so a chat answer no longer depends on the model also emitting a
    # `mark_answered` OQ action it was told not to touch. The downstream monitor
    # then clears the OQ because the carrier now reads present. This is the
    # chat-side twin of the panel answer path (`classify_answered_open_questions`).
    user_choice = _validated_algorithm_name(user_search_strategy_choice)
    if user_choice:
        return _set_search_strategy_algorithm(effective_brief, user_choice), oq_actions

    # Resolve which OQ ids are the search-strategy question. The canonical
    # monitor id is the usual case; topic is the robust signal in case a
    # legacy/renamed row carries a different id.
    def _search_strategy_oq_ids(brief: dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        for q in brief.get("open_questions") or []:
            if not isinstance(q, dict):
                continue
            qid = str(q.get("id") or "").strip()
            if not qid:
                continue
            if qid == _MONITOR_OQ_ALGORITHM_ID or str(q.get("topic") or "").strip().lower() == "search_strategy":
                ids.add(qid)
        return ids

    ss_ids = _search_strategy_oq_ids(base_brief) | _search_strategy_oq_ids(effective_brief)

    # Already-authorized: the base brief carries a legitimate search-strategy
    # signal. Since this gate runs on every turn, a forged carrier can never
    # persist into base — so a base mention means the participant answered on
    # a prior turn (their OQ-textarea answer was promoted to a gathered row).
    from app.services.goal_term_anchoring import brief_mentions_search_strategy

    base_authorized = brief_mentions_search_strategy(
        base_brief, workflow_mode="waterfall"
    )

    loose_ok = False
    for action in oq_actions or []:
        if not isinstance(action, dict):
            continue
        if str(action.get("id") or "").strip() not in ss_ids:
            continue
        if str(action.get("action") or "").strip().lower() != "mark_answered":
            continue
        if _validated_algorithm_name(action.get("answer_text")):
            loose_ok = True
            break

    if base_authorized or loose_ok:
        return effective_brief, oq_actions

    # Unauthorized — strip the carrier and any algorithm-bearing item the
    # patch just introduced (preserve pre-existing rows by id, defensively).
    from app.services.goal_term_anchoring import extract_algorithm_from_brief

    gated = deepcopy(effective_brief)
    goal_terms = gated.get("goal_terms")
    if isinstance(goal_terms, dict) and "search_strategy" in goal_terms:
        goal_terms = {k: v for k, v in goal_terms.items() if k != "search_strategy"}
        gated["goal_terms"] = goal_terms

    base_item_ids = {
        str(i.get("id") or "")
        for i in (base_brief.get("items") or [])
        if isinstance(i, dict)
    }
    kept_items: list[Any] = []
    for item in gated.get("items") or []:
        if not isinstance(item, dict):
            kept_items.append(item)
            continue
        anchor = item.get("goal_key")
        is_ss_anchor = isinstance(anchor, str) and anchor.strip() == "search_strategy"
        is_new_algo_row = (
            str(item.get("id") or "") not in base_item_ids
            and extract_algorithm_from_brief([item]) is not None
        )
        if is_ss_anchor or is_new_algo_row:
            continue
        kept_items.append(item)
    gated["items"] = kept_items

    filtered_actions = [
        a
        for a in (oq_actions or [])
        if not (
            isinstance(a, dict)
            and str(a.get("id") or "").strip() in ss_ids
            and str(a.get("action") or "").strip().lower() in {"drop", "mark_answered"}
        )
    ]
    log.warning(
        "Waterfall search-strategy gate: stripped unauthorized algorithm "
        "commit (carrier + items) and refused %d OQ action(s)",
        len(oq_actions or []) - len(filtered_actions),
    )
    return gated, filtered_actions


def _locked_goal_term_keys(
    base_brief: dict[str, Any], base_panel: dict[str, Any] | None
) -> set[str]:
    """Keys the participant has locked, read from both representations.

    Lock is set by the user in two equivalent surfaces: the brief carries
    ``goal_terms[key].locked = true`` and the panel carries a
    ``locked_goal_terms`` id list. We honor either so the gate fires no matter
    which surface recorded the lock.
    """
    locked: set[str] = set()
    gt = base_brief.get("goal_terms") if isinstance(base_brief, dict) else None
    if isinstance(gt, dict):
        for key, entry in gt.items():
            if isinstance(key, str) and isinstance(entry, dict) and entry.get("locked") is True:
                locked.add(key)
    if isinstance(base_panel, dict):
        problem = base_panel.get("problem") if isinstance(base_panel.get("problem"), dict) else base_panel
        raw = problem.get("locked_goal_terms") if isinstance(problem, dict) else None
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, str) and entry.strip():
                    locked.add(entry.strip())
    return locked


def gate_locked_goal_term_changes(
    *,
    effective_brief: dict[str, Any],
    base_brief: dict[str, Any],
    base_panel: dict[str, Any] | None,
    test_problem_id: str | None = None,
) -> dict[str, Any]:
    """All-mode structural gate: the agent must not silently change a LOCKED
    goal term.

    A locked term is the participant's "hands off" — its value is frozen until
    they unlock it. When the merged brief would change a locked key's weight or
    type (or drop the key), revert that key to its base value and raise an open
    question asking the participant to approve unlocking + the change. This is
    the lifecycle's strongest "user input wins" rule, and it holds in every
    mode (waterfall already asks; agile would otherwise just demote to an
    assumption — but a *locked* term is the exception that forces an OQ). A
    prose rule can't enforce it; this gate does (cf.
    ``gate_unauthorized_search_strategy_commit``).
    """
    if not isinstance(effective_brief, dict) or not isinstance(base_brief, dict):
        return effective_brief
    locked_keys = _locked_goal_term_keys(base_brief, base_panel)
    if not locked_keys:
        return effective_brief

    base_gt = base_brief.get("goal_terms") if isinstance(base_brief.get("goal_terms"), dict) else {}
    merged_gt = effective_brief.get("goal_terms") if isinstance(effective_brief.get("goal_terms"), dict) else {}

    def _scalar(entry: Any, field: str) -> Any:
        return entry.get(field) if isinstance(entry, dict) else None

    reverted: list[str] = []
    next_gt = dict(merged_gt)
    for key in locked_keys:
        if key not in base_gt:
            continue  # nothing locked to protect
        base_entry = base_gt[key]
        if key not in merged_gt:
            # Agent dropped a locked term — restore it.
            next_gt[key] = deepcopy(base_entry)
            reverted.append(key)
            continue
        merged_entry = merged_gt[key]
        weight_changed = _scalar(base_entry, "weight") != _scalar(merged_entry, "weight")
        type_changed = _scalar(base_entry, "type") != _scalar(merged_entry, "type")
        if weight_changed or type_changed:
            next_gt[key] = deepcopy(base_entry)  # freeze: revert to locked value
            reverted.append(key)
    if not reverted:
        return effective_brief

    out = dict(effective_brief)
    out["goal_terms"] = next_gt
    open_questions = list(out.get("open_questions") or [])
    existing_locked_oq_keys = {
        str(q.get("goal_key") or "").strip()
        for q in open_questions
        if isinstance(q, dict)
        and str(q.get("id") or "").startswith("oq-locked-change-")
    }
    label_map: dict[str, str] = {}
    try:
        from app.problems.registry import get_study_port

        result = get_study_port(test_problem_id).weight_item_labels()
        if isinstance(result, dict):
            label_map = result
    except Exception:  # pragma: no cover — defensive
        label_map = {}
    for key in reverted:
        if key in existing_locked_oq_keys:
            continue
        label = label_map.get(key) or key.replace("_", " ").strip()
        open_questions.append(
            {
                "id": f"oq-locked-change-{key}",
                "text": (
                    f"The {label} setting is locked. Do you want to unlock it and "
                    f"apply the change I proposed?"
                ),
                "status": "open",
                "answer_text": None,
                "topic": "other",
                "goal_key": key,
            }
        )
    out["open_questions"] = open_questions
    log.warning(
        "Locked goal-term gate: reverted %d locked change(s) and raised OQ(s): %s",
        len(reverted),
        reverted,
    )
    return out


def _has_gathered_evidence_for_key(items: list[Any], key: str) -> bool:
    """True iff some ``kind: "gathered"`` row in ``items`` represents ``key``.

    Two structural matches count as evidence:
    - the row's id is exactly ``config-weight-<key>`` (the canonical row
      ``_synthesize_canonical_weight_items`` synthesizes from goal_terms);
    - the row carries ``goal_key=<key>`` (an LLM-authored gathered item
      that explicitly anchors to the same key, e.g. a
      ``item-gathered-capacity-penalty`` row).

    The OQ resolver gates its drop on this — the participant must already
    see the answer in their Definition tab's gathered info before the
    question disappears.
    """
    if not key:
        return False
    canonical_id = f"config-weight-{key}"
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip().lower() != "gathered":
            continue
        if str(item.get("id") or "") == canonical_id:
            return True
        anchor = item.get("goal_key")
        if isinstance(anchor, str) and anchor.strip() == key:
            return True
    return False


def _resolve_anchored_provisional_rows(
    brief: dict[str, Any],
    workflow_mode: str | None,
    base_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Drop OQs whose anchored goal_term just landed AND is visible in gathered info.

    The OQ resolver answers two questions:

    1. *Did the user just answer the OQ?* — proxied structurally by either
       *"the OQ's anchored key is committed in ``goal_terms`` this turn but
       wasn't in the base brief"* (a fresh commit) OR *"the anchored key's
       weight/type changed this turn"* (a tuning OQ the user answered by
       retuning — mirrors the panel-edit path's "user acted on the key, so
       the question is moot"). A tuning OQ whose key is untouched this turn
       still survives.
    2. *Does the brief actually surface the answer to the participant?* —
       checked via ``_has_gathered_evidence_for_key``. The canonical
       ``config-weight-K`` row that ``_synthesize_canonical_weight_items``
       emits immediately before this resolver runs satisfies the check on
       the normal path; an LLM-authored gathered row anchored to the same
       key also counts. This gate makes the contract explicit so future
       code paths that bypass synthesis can't silently delete OQs whose
       answers aren't yet visible.

    Both gates AND together with the existing skips:

    - Foundational-topic OQs (``topic`` in ``upload`` / ``primary_goal`` /
      ``search_strategy``) — server monitor state machine owns those.
    - OQs without ``goal_key`` — LLM owns lifecycle via ``oq_actions``.
    - Already-answered OQs (``status: "answered"``) — handled by
      ``_promote_answered_open_questions_to_gathered``.

    Assumption rows are intentionally NOT auto-resolved here. Promotion
    (``kind: "assumption" → "gathered"``) happens only via explicit
    ``assumption_actions: promote_to_gathered`` (already wired in
    ``_apply_assumption_actions``). An auto-trigger based on goal_term
    state was the wrong action (drop instead of promote) and the wrong
    trigger (relied on a parallel gathered+user item that mostly only
    lands when the LLM also remembers to emit ``assumption_actions``).
    A forgotten promotion leaves the row as ``kind: "assumption"`` —
    provisional but not wrong; the participant can still see it.

    Idempotent: rows already dropped on a prior turn just aren't there to
    drop again. ``base_brief=None`` is treated as "no keys in base" so
    legacy callers without the diff context get the previous behavior
    (every committed key counts as newly committed).
    """
    if not isinstance(brief, dict):
        return brief

    goal_terms = brief.get("goal_terms")
    merged_goal_term_keys: set[str] = set()
    if isinstance(goal_terms, dict):
        for key in goal_terms.keys():
            if isinstance(key, str):
                merged_goal_term_keys.add(key)
    if not merged_goal_term_keys:
        return brief

    base_gt: dict[str, Any] = {}
    base_goal_term_keys: set[str] = set()
    if isinstance(base_brief, dict):
        bgt = base_brief.get("goal_terms")
        if isinstance(bgt, dict):
            base_gt = bgt
            base_goal_term_keys = {k for k in bgt.keys() if isinstance(k, str)}
    newly_committed_keys = merged_goal_term_keys - base_goal_term_keys

    # Tuning OQs (anchored to a key already in base) resolve when the user's
    # answer RETUNES that key this turn — the same "the user acted on the key,
    # so the question is moot" rule the panel-edit path already applies
    # (`_auto_close_oqs_for_panel_edited_keys`). Without this, answering "yes"
    # to *"adjust the travel time weight?"* in chat bumped the weight but left
    # the OQ open (the main turn's `drop` is stripped on answered-OQ turns, so
    # the structural close has to happen here, not via the LLM action).
    def _scalar(entry: Any, field: str) -> Any:
        return entry.get(field) if isinstance(entry, dict) else None

    changed_keys: set[str] = set()
    for key in merged_goal_term_keys & base_goal_term_keys:
        m_entry, b_entry = goal_terms.get(key), base_gt.get(key)
        if _scalar(m_entry, "weight") != _scalar(b_entry, "weight") or _scalar(
            m_entry, "type"
        ) != _scalar(b_entry, "type"):
            changed_keys.add(key)

    if not newly_committed_keys and not changed_keys:
        return brief

    from app.problem_brief import is_goal_key_oq_resolved_by_keys

    resolving_keys = newly_committed_keys | changed_keys
    next_brief = dict(brief)
    items = list(next_brief.get("items") or [])
    questions = list(next_brief.get("open_questions") or [])
    kept_questions: list[dict[str, Any]] = []
    dropped_oq_ids: list[str] = []
    for q in questions:
        # Shared decision (panel-edit path uses the same predicate): is this an
        # open, non-foundational, goal_key OQ whose key was committed/retuned
        # this turn? If not, leave it untouched.
        if not is_goal_key_oq_resolved_by_keys(q, resolving_keys):
            kept_questions.append(q)
            continue
        anchor_key = str(q.get("goal_key") or "").strip()
        if not _has_gathered_evidence_for_key(items, anchor_key):
            # Key landed but the participant doesn't see it yet — keep the OQ.
            kept_questions.append(q)
            continue
        dropped_oq_ids.append(str(q.get("id") or ""))

    if dropped_oq_ids:
        log.info(
            "Anchored-OQ resolver dropped %d OQ(s) whose goal_term landed "
            "with visible gathered evidence: %s",
            len(dropped_oq_ids),
            dropped_oq_ids,
        )
        next_brief["open_questions"] = kept_questions

    return next_brief


def _companion_row_prose(merged: dict[str, Any], key: str) -> str:
    """The participant-visible prose for a companion parent row (its synthesized
    ``config-weight-<key>`` items[] text), which on a definition-panel edit holds
    the rules the participant typed after "Rules —". Empty string if absent."""
    for it in (merged.get("items") or []):
        if isinstance(it, dict) and str(it.get("id") or "") == f"config-weight-{key}":
            return str(it.get("text") or "")
    return ""


def _extract_missing_companion_rules(
    *,
    merged: dict[str, Any],
    base_brief: dict[str, Any],
    patch_payload: dict[str, Any],
    test_problem_id: str | None,
    user_text: str,
    change_clause: str | None,
    is_brief_edit_ack: bool,
    api_key: str | None,
    model_name: str | None,
) -> dict[str, Any]:
    """For each companion-bearing goal term whose structured array didn't move
    this turn — on a claimed chat change OR a definition-panel edit —
    deterministically extract the rules from the participant's wording and the
    companion row's prose, and populate the carrier.

    Generic — driven by ``port.gate_conditional_companions`` + the port's
    extraction instructions; ports without those opt out (the extractor no-ops).
    Fail-safe: any error leaves ``merged`` untouched.
    """
    if not test_problem_id or not api_key or not model_name:
        return merged
    claimed = bool(change_clause and str(change_clause).strip())
    if not claimed and not is_brief_edit_ack:
        return merged  # only on a claimed change or a definition-panel edit
    try:
        from app.problems.registry import get_study_port
        from app.services import llm

        port = get_study_port(test_problem_id)
        gate_companions = port.gate_conditional_companions() or {}
    except Exception:  # pragma: no cover — never block on registry hiccups
        return merged
    if not gate_companions:
        return merged

    merged_gt = merged.get("goal_terms") if isinstance(merged.get("goal_terms"), dict) else {}
    base_gt = base_brief.get("goal_terms") if isinstance(base_brief.get("goal_terms"), dict) else {}
    patch_gt = (
        patch_payload.get("goal_terms")
        if isinstance(patch_payload, dict) and isinstance(patch_payload.get("goal_terms"), dict)
        else {}
    )

    def _arr(gt: dict[str, Any], k: str, f: str) -> Any:
        ent = gt.get(k) if isinstance(gt, dict) else None
        props = ent.get("properties") if isinstance(ent, dict) and isinstance(ent.get("properties"), dict) else {}
        return props.get(f) if isinstance(props, dict) else None

    out = merged
    for key, field in gate_companions.items():
        if key not in merged_gt:
            continue
        # Fire when: the agent committed the term + claimed a change (chat path),
        # OR this is a definition-panel edit (the user may have typed a rule into
        # the companion row's prose, which the agent then overwrote).
        if not ((claimed and key in patch_gt) or is_brief_edit_ack):
            continue
        merged_arr = _arr(merged_gt, key, field)
        base_arr = _arr(base_gt, key, field)
        if merged_arr != base_arr:
            continue  # agent already updated the carrier — nothing to fix
        current_rules = merged_arr if isinstance(merged_arr, list) else []
        # Source: chat wording + the companion row's prose from BOTH base (where a
        # def-panel "Rules —" edit lives — the agent often overwrites it in the
        # merged copy) and merged. The extractor returns the complete deduped list.
        source_text = "\n".join(
            t
            for t in [
                (user_text or "").strip(),
                _companion_row_prose(base_brief, key),
                _companion_row_prose(out, key),
            ]
            if t
        )
        new_rules = llm.extract_companion_rules(
            test_problem_id=test_problem_id,
            goal_term_key=key,
            companion_field=field,
            source_text=source_text,
            current_rules=current_rules,
            api_key=api_key,
            model_name=model_name,
        )
        if not isinstance(new_rules, list) or new_rules == current_rules:
            continue
        out = dict(out)
        gt = dict(out.get("goal_terms") or {})
        entry = dict(gt.get(key) or {})
        props = dict(entry.get("properties") or {})
        props[field] = new_rules
        entry["properties"] = props
        # The agent's ``ambiguity_note`` here is stale narration about rules it
        # failed to structure ("I've structured Alice and Carol together"); drop
        # it so the synthesized row falls back to the port's clean rationale.
        entry.pop("ambiguity_note", None)
        gt[key] = entry
        out["goal_terms"] = gt
        merged_gt = gt  # keep view consistent for any later companion keys
    return out


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
    oq_actions: list[dict[str, Any]] | None = None,
    change_clause: str | None = None,
    is_brief_edit_ack: bool = False,
    is_tutorial_active: bool = False,
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

    # Pass the turn-level cleanup flag so the wholesale ``replace_open_questions``
    # wipe is only honored on genuine cleanup turns (else it merges incrementally
    # and unresolved questions survive).
    merged = merge_problem_brief_patch(
        base_problem_brief, patch_payload, cleanup_mode_override=cleanup_mode
    )
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
        # Pending-OQ map for the premature-commit drop: when the LLM emits
        # both a new goal_term commit AND an OQ asking about that same key
        # (vague user input like *"there also are some driver preferences"*),
        # the commit is unfinished — drop it so the OQ stands alone as the
        # canonical open ask. The goal_term re-commits cleanly once the user
        # answers with specific rules.
        pending_oq_keys: set[str] = set()
        for q in merged.get("open_questions") or []:
            if not isinstance(q, dict):
                continue
            if str(q.get("status") or "open").strip().lower() != "open":
                continue
            gk = q.get("goal_key")
            if isinstance(gk, str) and gk.strip():
                pending_oq_keys.add(gk.strip())
        # Answered-OQ keys: the goal_key of every OQ this turn's oq_actions
        # RESOLVE (drop / mark_answered). These are the opposite of pending —
        # the participant just answered the ask about K, so the commit is
        # authorized and must NOT be premature-dropped. Resolved here, before
        # the filter, because ``_apply_oq_actions`` (which removes the OQ) runs
        # a step later in the caller — by the time the OQ is gone the link
        # between the answer and the goal term is lost. Without this an
        # "approve the proposed penalty" turn dropped both the term and the OQ.
        answered_oq_keys: set[str] = set()
        if oq_actions:
            resolving_ids = {
                str(a.get("id") or "").strip()
                for a in oq_actions
                if isinstance(a, dict)
                and str(a.get("action") or "").strip().lower() in {"drop", "mark_answered"}
            }
            if resolving_ids:
                for q in merged.get("open_questions") or []:
                    if not isinstance(q, dict):
                        continue
                    if str(q.get("id") or "").strip() not in resolving_ids:
                        continue
                    gk = q.get("goal_key")
                    if isinstance(gk, str) and gk.strip():
                        answered_oq_keys.add(gk.strip())
        filtered, dropped = filter_unanchored_new_goal_terms(
            base_brief=base_problem_brief,
            proposed_goal_terms=proposed_goal_terms,
            items=anchor_items,
            workflow_mode=workflow_mode,
            api_key=api_key,
            test_problem_id=test_problem_id,
            pending_oq_keys=pending_oq_keys,
            answered_oq_keys=answered_oq_keys,
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
    merged, _dropped_anchor_provenance = _drop_redundant_goal_term_anchors(
        base_brief=base_problem_brief, merged=merged
    )

    # Deterministic companion-rule extraction. The main-turn LLM is unreliable at
    # populating list companions (it acknowledges a rule in prose but omits the
    # structured array). When this turn committed a companion term + claimed a
    # change yet the array didn't move, run a focused structured-extraction call
    # on the participant's wording to populate it — far more reliable than the
    # main agent (P_0603: "added Dave" with no driver_preferences). Runs BEFORE
    # reconcile/synthesize so the populated array clears the companion OQ and the
    # synthesized row reflects the rules.
    merged = _extract_missing_companion_rules(
        merged=merged,
        base_brief=base_problem_brief,
        patch_payload=patch_payload,
        test_problem_id=test_problem_id,
        user_text=user_text,
        change_clause=change_clause,
        is_brief_edit_ack=is_brief_edit_ack,
        api_key=api_key,
        model_name=model_name,
    )

    # Reconcile auto-OQs for goal_terms with missing/present companions.
    # Mirrors the same call inside ``sync_problem_brief_from_panel`` so the
    # auto-OQ stays in lockstep on BOTH the user-edit path (panel save) and
    # the LLM-edit path (this chat-turn apply). Also catches legacy state
    # — sessions that entered an orphan-companion state before this fix
    # was in place get their auto-OQ added on the next chat turn.
    from app.problem_brief import reconcile_companion_oqs

    # Keep-vs-drop the empty companion term by whether this turn CLAIMED a
    # concrete child (B1 vs B2): a vague mention the agent should just ask about
    # (no change_clause) doesn't materialise a hollow new term — it's dropped and
    # the OQ carries the ask. A claimed concrete child (or a pre-existing term) is
    # kept so it shows up and the config/def rule editors can complete it.
    merged = reconcile_companion_oqs(
        merged,
        test_problem_id,
        base_brief=base_problem_brief,
        turn_claimed_change=bool(change_clause and str(change_clause).strip()),
    )

    # Canonical goal-term rows: synthesize a ``config-weight-<key>`` items[]
    # row for every surviving goal_terms key, with text in the canonical
    # ``{Label} ({type}, weight N) — {reasoning}.`` form. Runs AFTER the
    # anchor filter so we never synthesize rows for keys the filter just
    # dropped. Re-normalisation inside the helper triggers the slot
    # reconciler, which drops any LLM-authored row that collides with the
    # synthesized one.
    merged = _synthesize_canonical_weight_items(
        merged, test_problem_id, provenance_hints=_dropped_anchor_provenance
    )

    # Drop OQs whose anchored goal_term key was newly committed this turn
    # AND whose answer is already visible in gathered info. Runs after
    # canonical weight items have been synthesized so the resolver sees
    # the final goal_terms state and the canonical `config-weight-K` rows
    # that satisfy the gathered-evidence gate. Assumption-row promotion
    # is not auto-resolved — see the docstring of
    # _resolve_anchored_provisional_rows for the rationale.
    merged = _resolve_anchored_provisional_rows(
        merged, workflow_mode, base_brief=base_problem_brief
    )

    # ``goal_summary`` fallback: when the LLM commits a primary objective
    # but forgets to populate the headline ``goal_summary`` field, derive
    # one from the goal-term label so the Definition's top section reflects
    # what's actually committed. Only fires when the field is empty — any
    # LLM-set value wins.
    merged = _autofill_goal_summary_from_objective(merged, test_problem_id)

    # Run-acknowledgement turns: keep run outcomes out of the Definition's
    # gathered info. The run history is server-owned in ``brief.runs`` and the
    # participant reads each result in the chat reply + Results panel — so an
    # agent-authored "Run #N was feasible…" gathered row is pure clutter
    # (observed piling up in P_0602). Strip those here; canonical config rows
    # and anything the participant said are untouched.
    if is_run_acknowledgement:
        merged = _strip_agent_run_commentary(merged)

    consolidated, run_meta = consolidate_runs(
        merged,
        recent_runs_summary=recent_runs_summary,
        is_run_acknowledgement=is_run_acknowledgement,
        test_problem_id=test_problem_id,
    )
    consolidated = _enforce_session_monitors(
        consolidated,
        workflow_mode,
        test_problem_id=test_problem_id,
        is_run_acknowledgement=is_run_acknowledgement,
        is_tutorial_active=is_tutorial_active,
    )
    # The Definition's items[] is a projection of the structured model — keep
    # only the synthesized goal-term rows and the upload marker; sweep agent
    # free-form prose, orphan "interest" rows, and OQ-answer context rows. Runs
    # LAST (after the agent has drafted, so it can fold any free-text into a goal
    # term / goal_summary first) and never on load (which would strip a user's
    # note before the agent sees it).
    consolidated = _whitelist_structured_items(consolidated)
    return consolidated, {"removed_total": 0, **run_meta}


def _whitelist_structured_items(brief: dict[str, Any]) -> dict[str, Any]:
    """Restrict items[] to structured rows: synthesized ``config-*`` goal-term /
    search-strategy / companion rows, the single upload marker, and server-owned
    monitor rows (agile algorithm assumption / plateau advisory). Everything else
    (free-form agent prose, "user indicated interest in …" placeholders, OQ-answer
    context rows, user-typed notes) is dropped so the panel stays a clean,
    analyzable set of structured artifacts. ``goal_terms`` / ``goal_summary`` /
    ``search_strategy`` / ``open_questions`` / ``runs`` are untouched — the agent
    is told to merge any free-text meaning into those before this sweep.
    """
    if not isinstance(brief, dict):
        return brief
    items = brief.get("items")
    if not isinstance(items, list):
        return brief
    from app.problem_brief import _is_upload_marker_item

    # Server-owned monitor items that ARE structured artifacts (not free-form
    # agent prose) and must survive: the agile/demo algorithm assumption row and
    # the plateau advisory. Stable ids, re-enforced by _enforce_session_monitors.
    structured_monitor_ids = {_MONITOR_ITEM_ALGORITHM_ID, _MONITOR_ITEM_PLATEAU_ID}

    kept = [
        it
        for it in items
        if isinstance(it, dict)
        and (
            str(it.get("id") or "").startswith("config-")
            or str(it.get("id") or "") in structured_monitor_ids
            or _is_upload_marker_item(it)
        )
    ]
    if len(kept) == len(items):
        return brief
    out = dict(brief)
    out["items"] = kept
    return out


def _strip_agent_run_commentary(brief: dict[str, Any]) -> dict[str, Any]:
    """Remove agent-authored free-form gathered rows on a run-ack turn.

    Drops items where ``kind == "gathered"`` AND ``source == "agent"`` AND the
    id is NOT a canonical ``config-*`` row. That targets the agent's per-run
    narration (e.g. ``item-gathered-run-13-interpretation`` —
    "Run #13 was fully feasible…") while protecting:

    - the synthesized ``config-weight-*`` / ``config-search-strategy`` rows
      (canonical config, ``config-`` prefix),
    - the upload row and anything the participant stated (``source != agent``).

    Run outcomes belong in ``brief.runs`` and the chat reply, not as standing
    facts in the Definition. Idempotent — re-running finds nothing to drop and
    also retroactively clears rows added before this gate existed.
    """
    if not isinstance(brief, dict):
        return brief
    items = brief.get("items")
    if not isinstance(items, list):
        return brief
    kept: list[Any] = []
    dropped = 0
    for it in items:
        if (
            isinstance(it, dict)
            and str(it.get("kind") or "").strip().lower() == "gathered"
            and str(it.get("source") or "").strip().lower() == "agent"
            and not str(it.get("id") or "").startswith(CONFIG_ITEM_PREFIX)
        ):
            dropped += 1
            continue
        kept.append(it)
    if not dropped:
        return brief
    log.info("Run-ack: stripped %d agent run-commentary row(s) from gathered info", dropped)
    out = dict(brief)
    out["items"] = kept
    return out


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
) -> tuple[dict[str, Any], dict[str, tuple[str, str]]]:
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
        return merged, {}
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
        return merged, {}
    items_by_id = {
        str(it.get("id") or ""): it
        for it in (merged.get("items") or [])
        if isinstance(it, dict) and str(it.get("id") or "")
    }
    anchor_ids_to_drop: set[str] = set()
    # Provenance to carry forward to the synthesized config-weight-<key> row, so a
    # dropped agile `assumption` anchor isn't silently rewritten to `gathered`.
    dropped_provenance: dict[str, tuple[str, str]] = {}
    for key, entry in merged_gt.items():
        if not isinstance(key, str) or key in base_gt_keys:
            continue  # existing goal_term — leave its evidence alone
        if key in CARRIER_ONLY_GOAL_TERM_KEYS:
            # Carrier-only terms (e.g. ``search_strategy``) are SKIPPED by the
            # canonical synthesizer — no ``config-weight-<key>`` row is emitted to
            # replace the dropped anchor. Dropping the anchor (``config-search-
            # strategy``) here would leave the carrier without its required
            # items[] row, so the panel-sync legitimacy gate strips the algorithm
            # and the choice silently vanishes (P_0602: "sounds good" → GA never
            # reached the panel). Leave the anchor in place.
            continue
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
            if sid.startswith("config-weight-"):
                # The agent self-anchored to the CANONICAL row id. That row is
                # owned by the synthesizer (drop-and-replace by id), which also
                # preserves its provenance — dropping it here would erase an
                # agile `assumption` proposal before the synthesizer can read
                # its kind/source (P_0603). Leave it for the synthesizer.
                continue
            anchor_ids_to_drop.add(sid)
            anchor = items_by_id.get(sid)
            if isinstance(anchor, dict):
                akind = str(anchor.get("kind") or "").strip().lower()
                if akind in {"gathered", "assumption"}:
                    asrc = str(anchor.get("source") or "agent").strip().lower() or "agent"
                    dropped_provenance[key] = (akind, asrc)
    if not anchor_ids_to_drop:
        return merged, {}

    next_items = [
        it for it in (merged.get("items") or [])
        if not (isinstance(it, dict) and str(it.get("id") or "") in anchor_ids_to_drop)
    ]
    next_brief = dict(merged)
    next_brief["items"] = next_items
    return next_brief, dropped_provenance


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
_MONITOR_OQ_PLATEAU_ID = "oq-monitor-plateau"
_MONITOR_ITEM_PLATEAU_ID = "item-monitor-plateau"

# Plateau nudge tuning. Two consecutive completed runs on the SAME algorithm
# whose costs land within this relative tolerance count as "stalled" — the
# solver isn't making meaningful progress, so it's worth reconsidering the
# search strategy (swap the algorithm or give it more iterations).
_PLATEAU_MIN_RUNS = 2
_PLATEAU_COST_REL_TOLERANCE = 0.02

_MONITOR_OQ_UPLOAD_TEXT = (
    "Please use the **Upload file(s)...** button in the chat footer to share "
    "your data so we can set up a baseline run."
)
_MONITOR_OQ_GOAL_TEXT = (
    "What's your primary optimization goal? Tell me which priority should drive "
    "the search."
)
def _port_supported_algorithms(test_problem_id: str | None) -> tuple[str, ...]:
    """Resolve the active port's algorithm option list.

    StudyProblemPort is a structural Protocol, so default methods on the
    Protocol class are *not* inherited by concrete port classes that don't
    subclass it. We defensively ``getattr`` the hook and fall back to the
    catalog-wide canonical names — that keeps the change additive: existing
    ports get the full algorithm list for free, and ports that want to
    restrict the choices just define the method.
    """
    from app.algorithm_catalog import CANONICAL_ALGORITHM_NAMES
    from app.problems.registry import get_study_port

    port = get_study_port(test_problem_id)
    fn = getattr(port, "supported_algorithm_names", None)
    if callable(fn):
        try:
            result = fn()
        except Exception:  # pragma: no cover — defensive
            return CANONICAL_ALGORITHM_NAMES
        if isinstance(result, (tuple, list)) and result:
            return tuple(result)
    return CANONICAL_ALGORITHM_NAMES


def _monitor_algorithm_oq_text(test_problem_id: str | None) -> str:
    """Canonical waterfall OQ text, listing whatever algorithms the active
    port surfaces. Hardcoding the option list here would drift the moment a
    new port restricted the set (or the canonical catalog grew); deriving it
    keeps the participant prompt aligned with the actual choices the
    optimizer will accept."""
    from app.algorithm_catalog import format_algorithm_choices_phrase

    phrase = format_algorithm_choices_phrase(_port_supported_algorithms(test_problem_id))
    if not phrase:
        return "Which search strategy should we use?"
    return f"Which search strategy should we use? Options include {phrase}."


def _monitor_algorithm_item_text(
    test_problem_id: str | None, algorithm: str | None = None
) -> str:
    """Agile/demo assumption-row text. Reflects the COMMITTED carrier algorithm
    when one is given (so the visible assumption tracks what the solver will
    actually run); otherwise names the port's first supported algorithm as the
    starting point. Falls back to GA if the port returns an empty list
    (defensive — shouldn't happen with the default impl)."""
    from app.algorithm_catalog import ALGORITHM_PARTICIPANT_NICKNAMES_MAP

    supported = _port_supported_algorithms(test_problem_id)
    default = supported[0] if supported else "GA"
    chosen = algorithm if (algorithm in ALGORITHM_PARTICIPANT_NICKNAMES_MAP) else default
    nickname = ALGORITHM_PARTICIPANT_NICKNAMES_MAP.get(chosen, chosen)
    return f"Search strategy is set to {nickname} as a starting point — change anytime."


def _monitor_goal_oq_text(test_problem_id: str | None) -> str:
    """Generic canonical goal-term OQ text.

    Previously this enumerated every weight label the active port exposed
    (``weight_item_labels()``), which for VRPTW produced a 7-item dump
    ("travel time, shift limit, workload balance, …") — too revealing for a
    cold-start participant who hasn't yet seen the Definition tab. The
    generic phrasing avoids leaking the full benchmark vocabulary while
    still asking the question. Per-port specifics surface naturally in the
    LLM-driven chat reply that prompts this OQ.

    ``test_problem_id`` is retained on the signature for backwards
    compatibility with existing call sites; the text itself is now
    problem-agnostic.
    """
    return _MONITOR_OQ_GOAL_TEXT

def _current_brief_algorithm(brief: dict[str, Any]) -> str | None:
    """The algorithm currently configured in the brief carrier, or None."""
    gt = brief.get("goal_terms") if isinstance(brief, dict) else None
    if isinstance(gt, dict):
        ss = gt.get("search_strategy")
        if isinstance(ss, dict):
            props = ss.get("properties")
            if isinstance(props, dict):
                algo = props.get("algorithm")
                if isinstance(algo, str) and algo.strip():
                    return algo.strip()
    return None


def _detect_run_plateau(brief: dict[str, Any]) -> tuple[str, float] | None:
    """Return ``(algorithm, latest_cost)`` when the last ``_PLATEAU_MIN_RUNS``
    completed runs stalled — same algorithm, costs within
    ``_PLATEAU_COST_REL_TOLERANCE`` — AND that algorithm is still the one
    configured (the participant hasn't already switched away). Else None.

    Reads only the server-managed ``brief.runs`` structured entries, so the
    signal is deterministic (no LLM, no NL parsing). The "still configured"
    guard auto-clears the nudge the moment the participant changes the
    algorithm, even before the next run.
    """
    if not isinstance(brief, dict):
        return None
    runs = brief.get("runs")
    if not isinstance(runs, list):
        return None
    completed = [
        r
        for r in runs
        if isinstance(r, dict)
        and r.get("ok")
        and isinstance(r.get("cost"), (int, float))
        and not isinstance(r.get("cost"), bool)
    ]
    if len(completed) < _PLATEAU_MIN_RUNS:
        return None
    window = completed[-_PLATEAU_MIN_RUNS:]
    algos = {str(r.get("algorithm") or "").strip() for r in window}
    if len(algos) != 1:
        return None
    algo = next(iter(algos))
    if not algo:
        return None
    current = _current_brief_algorithm(brief)
    if current and current != algo:
        return None  # participant already switched — nothing to nudge
    costs = [float(r["cost"]) for r in window]
    base = max(abs(costs[0]), 1e-9)
    if (max(costs) - min(costs)) / base > _PLATEAU_COST_REL_TOLERANCE:
        return None
    return algo, costs[-1]


def _plateau_options_phrase(test_problem_id: str | None, exclude_algo: str) -> str:
    """Port's algorithm options for the nudge, minus the stalled one."""
    from app.algorithm_catalog import format_algorithm_choices_phrase

    supported = tuple(
        a for a in _port_supported_algorithms(test_problem_id) if a != exclude_algo
    )
    return format_algorithm_choices_phrase(supported)


def _plateau_oq_text(test_problem_id: str | None, algo: str, cost: float) -> str:
    """Plain-language stall question (both modes) — the participant decides."""
    from app.algorithm_catalog import ALGORITHM_PARTICIPANT_NICKNAMES_MAP

    nick = ALGORITHM_PARTICIPANT_NICKNAMES_MAP.get(algo, algo)
    phrase = _plateau_options_phrase(test_problem_id, algo)
    options = (
        f" You could switch to {phrase}, or give the current one more iterations."
        if phrase
        else ""
    )
    return (
        f"The last couple of runs have stalled around a cost of {round(cost):,} "
        f"with {nick}. Want to try a different search strategy?{options}"
    )


def _enforce_session_monitors(
    brief: dict[str, Any],
    workflow_mode: str | None,
    test_problem_id: str | None = None,
    *,
    is_run_acknowledgement: bool = False,
    is_tutorial_active: bool = False,
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
            "goal_key": None,
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
        # The algorithm choice is an ASSUMPTION in agile/demo and must stay
        # VISIBLE as a row the participant sees and can override — the tutorial
        # gates on it (P_lk). The carrier-only `search_strategy` term has no
        # synthesized config-weight row, and the canonical `config-search-
        # strategy` row is only minted on a panel save (brief→panel doesn't run
        # on a chat turn), so THIS monitor row is the algorithm's visible
        # representation on the chat path. So: DON'T drop it the moment the
        # carrier is set (the old bug — the agent committing GA erased the only
        # visible assumption). Keep it in lockstep with the committed carrier
        # algorithm; step aside only when a real `config-search-strategy` row
        # already shows the choice (e.g. after a panel save).
        if _has_item("config-search-strategy"):
            _drop_item(_MONITOR_ITEM_ALGORITHM_ID)
        else:
            carrier_algo = _carrier_search_strategy_algorithm(next_brief)
            _drop_item(_MONITOR_ITEM_ALGORITHM_ID)
            items.append({
                "id": _MONITOR_ITEM_ALGORITHM_ID,
                "text": _monitor_algorithm_item_text(test_problem_id, carrier_algo),
                "kind": "assumption",
                "source": "agent",
            })
        # Drop any waterfall OQ that may be lingering from a workflow switch.
        _drop_oq(_MONITOR_OQ_ALGORITHM_ID)
    else:
        if has_algorithm:
            _drop_oq(_MONITOR_OQ_ALGORITHM_ID)
        elif not _has_oq(_MONITOR_OQ_ALGORITHM_ID):
            _append_oq(
                _MONITOR_OQ_ALGORITHM_ID,
                _monitor_algorithm_oq_text(test_problem_id),
                "search_strategy",
            )
        # Drop any agile-mode assumption that may be lingering.
        _drop_item(_MONITOR_ITEM_ALGORITHM_ID)

    # Monitor 4: plateau nudge. When the last couple of completed runs stalled
    # on the still-configured algorithm, suggest a search-strategy rethink via an
    # OQ — in BOTH workflows (researcher choice: symmetric plateau handling. The
    # agent used to silently auto-switch in agile; now agile ASKS like waterfall
    # so the participant owns the call in both). ADD only on a run-ack turn so it
    # surfaces "once in a while" (right after a run), not on every chat message;
    # DROP once the plateau clears, keeping it self-healing. SUPPRESSED during the
    # tutorial (runs are too similar to justify it and it's a learning context) —
    # drop any lingering plateau OQ/row and skip.
    plateau = _detect_run_plateau(next_brief)
    if is_tutorial_active or plateau is None:
        _drop_oq(_MONITOR_OQ_PLATEAU_ID)
        _drop_item(_MONITOR_ITEM_PLATEAU_ID)
    else:
        algo, cost = plateau
        # Clear the legacy agile advisory row (older builds wrote one); the OQ
        # is the only surface now.
        _drop_item(_MONITOR_ITEM_PLATEAU_ID)
        if is_run_acknowledgement and not _has_oq(_MONITOR_OQ_PLATEAU_ID):
            _append_oq(
                _MONITOR_OQ_PLATEAU_ID,
                _plateau_oq_text(test_problem_id, algo, cost),
                "search_strategy",
            )

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
    brief: dict[str, Any],
    test_problem_id: str | None,
    provenance_hints: dict[str, tuple[str, str]] | None = None,
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
    extras = synthesize_canonical_goal_term_items(
        brief, test_problem_id, provenance_hints=provenance_hints
    )
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


def _heal_orphaned_goal_term_rows(
    brief: dict[str, Any], test_problem_id: str | None
) -> dict[str, Any]:
    """Post-apply safety net: ensure every live goal term still has its canonical
    ``config-weight-<key>`` row.

    The canonical row is a deterministic projection of ``goal_terms``
    (``synthesize_canonical_goal_term_items``). If some step removed it while the
    goal term stayed live — e.g. an ``assumption_actions`` drop landing on the
    freshly-synthesized row (P_0603) — the participant is left with an active
    solver term and no line explaining it. This rebuilds only the **missing** rows
    and logs when it does, so a clean turn is untouched and a fired log flags a
    real anomaly to chase. It is NOT an unconditional re-synthesis and never
    rewrites or drops rows that are present.

    Runs as the last brief mutation in the apply stage (after
    ``_apply_assumption_actions`` / monitors), so it backstops any source of
    canonical-row loss, present or future.
    """
    if not isinstance(brief, dict):
        return brief
    from app.problem_brief import (
        normalize_problem_brief,
        synthesize_canonical_goal_term_items,
    )

    canonical = synthesize_canonical_goal_term_items(brief, test_problem_id)
    if not canonical:
        return brief
    existing_ids = {
        str(it.get("id") or "")
        for it in (brief.get("items") or [])
        if isinstance(it, dict)
    }
    missing = [
        row
        for row in canonical
        if isinstance(row, dict) and str(row.get("id") or "") not in existing_ids
    ]
    if not missing:
        return brief
    healed_keys = [str(row.get("id") or "")[len("config-weight-"):] for row in missing]
    log.warning(
        "Healed orphaned goal-term row(s) with no items[] line: %s", healed_keys
    )
    next_brief = dict(brief)
    next_brief["items"] = list(brief.get("items") or []) + missing
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


