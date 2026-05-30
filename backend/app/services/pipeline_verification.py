"""Pipeline verification helpers (S2 + S5).

Deterministic checks that run on every chat turn:

- **S2 brief verification** (after the main-turn LLM):
  - Schema/shape sanity
  - Claim-vs-delta consistency (reply commits "I added X" but patch missing X)
  - Algorithm-commit consistency (reply names GA but structured carrier empty)
  - Workflow invariants (waterfall no-assumption-rows, run-ack contract)
  - Port companion checks (delegate to ``StudyProblemPort.verify_brief_companion``)
  - Goal-term anchoring (existing service)

- **S5 panel verification** (after config-derivation LLM):
  - Bidirectional goal-term key mapping (brief ↔ panel)
  - Algorithm carrier consistency (brief.goal_terms.search_strategy ↔ panel.problem.algorithm)
  - Per-port companion mirrors (e.g. VRPTW driver_preferences list)

Output shape (``list[PipelineIssue]``) is shared with the LLM-retry feedback
block and the participant-facing status bubble. Plain-English ``message``
is the single source of truth for what's surfaced to either consumer.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from app.problems.registry import get_study_port
from app.schemas import PipelineIssue
from app.services.goal_term_anchoring import (
    evidence_kinds_for_workflow,
    is_goal_term_anchored,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_dict(value: Any) -> bool:
    return not isinstance(value, dict) or not value


def _patch_is_empty(patch: dict[str, Any] | None) -> bool:
    """A patch is "empty" if it has no content fields that would mutate
    the brief. Schema-defined fields that don't carry edits (``replace_*``
    flags, ``topic_engaged_next``) don't count.
    """
    if not isinstance(patch, dict):
        return True
    mutating_keys = ("items", "goal_terms", "open_questions", "goal_summary", "unmodeled_requests")
    for k in mutating_keys:
        v = patch.get(k)
        if isinstance(v, dict) and v:
            return False
        if isinstance(v, list) and v:
            return False
        if isinstance(v, str) and v.strip():
            return False
    return True


# ---------------------------------------------------------------------------
# S2 — brief verification
# ---------------------------------------------------------------------------


def verify_brief_consistency(
    *,
    merged_brief: dict[str, Any],
    base_brief: dict[str, Any] | None,
    patch: dict[str, Any] | None,
    visible_reply: str,
    workflow_mode: str,
    test_problem_id: str | None = None,
    is_change_intent: bool = True,
    is_run_acknowledgement: bool = False,
    suppress_runack_invariant: bool = False,
    question_clause: str | None = None,
    change_clause: str | None = None,
) -> list[PipelineIssue]:
    """Run deterministic S2 checks against the freshly-merged brief.

    ``merged_brief`` is the brief AFTER the V2 LLM patch was applied
    (so anchor checks see the new goal_terms and items). ``patch`` is the
    raw patch the LLM emitted (used for claim/delta consistency).

    Returns an empty list on success. On any issue, ``message`` carries
    plain-English text for both the LLM retry block and the participant
    status bubble.
    """
    issues: list[PipelineIssue] = []
    mode = str(workflow_mode or "").strip().lower()

    # ---- Schema sanity (patch shape) ----
    if patch is not None and not isinstance(patch, dict):
        issues.append(
            PipelineIssue(
                category="schema_invalid",
                severity="error",
                subject="problem_brief_patch",
                message="The brief patch wasn't a JSON object — re-emit as `{ items, goal_terms, open_questions, ... }`.",
            )
        )
        return issues  # Bail out — nothing else makes sense if the shape is broken.

    # ---- Claim ↔ delta consistency ----
    # ``change_clause`` is the LLM's own structured tag for "the visible reply
    # commits to a change" — symmetric to ``question_clause`` for asks. Reading
    # the structured field is the canonical signal; the previous NL keyword
    # matcher (``_reply_claims_change``) is gone — false negatives on phrasings
    # outside the keyword list silently shipped claim-without-delta turns and
    # false positives flagged question-only replies that happened to mention
    # *"I've added similar before"*.
    claims_change = bool((change_clause or "").strip()) if isinstance(change_clause, str) else False
    patch_empty = _patch_is_empty(patch)
    if is_change_intent and claims_change and patch_empty:
        issues.append(
            PipelineIssue(
                category="claim_without_delta",
                severity="error",
                subject="problem_brief_patch",
                message=(
                    "Your reply commits to a change (e.g. \"I've added…\", \"updated…\") "
                    "but `problem_brief_patch` carries no items, goal_terms, or open_questions "
                    "to back the claim. Add the structural delta that matches what you said."
                ),
            )
        )

    # ---- replace_open_questions intent ambiguity ----
    # Catches the P_l7 failure: the LLM set the flag but omitted the
    # `open_questions` field entirely, leaving the merge to defensively
    # preserve the existing list (problem_brief.py: "common on cleanup
    # turns that only replace items"). The flag without a list is
    # genuinely ambiguous — force the LLM to either drop the flag or
    # commit to a survivor list (empty array is fine).
    if (
        isinstance(patch, dict)
        and patch.get("replace_open_questions") is True
        and "open_questions" not in patch
    ):
        issues.append(
            PipelineIssue(
                category="oq_replace_without_list",
                severity="error",
                subject="problem_brief_patch",
                message=(
                    "You set `replace_open_questions=true` but didn't include "
                    "the `open_questions` field. Either drop the flag and use "
                    "`oq_actions` for per-row decisions, or include the full "
                    "survivor list (empty array `[]` if every OQ should be "
                    "dropped)."
                ),
            )
        )

    # ---- Algorithm carrier consistency ----
    # Removed: the previous NL-substring detector ("uses GA" / "let's try PSO")
    # produced false positives on question phrasings like "would you prefer
    # GA, PSO, or SA?" — flagging the OQ as a commitment. The structured
    # carrier ``goal_terms.search_strategy.properties.algorithm`` is the
    # single source of truth for algorithm choice; S5 verifies it against the
    # panel structurally (see ``verify_panel_consistency``). Trust the
    # carrier; don't grep the visible reply.

    # ---- Reply asks a clarification → brief must carry an OQ ----
    # When the LLM self-tags the visible reply as containing a clarifying
    # question (`question_clause` non-empty), the brief must reflect it.
    # Satisfied by either (a) an OQ would land this turn (post-S3 monitor
    # enforcement — see below) or (b) the LLM explicitly retargeted an
    # existing OQ via `oq_actions` (`rephrase` or `mark_answered`). No NL
    # classification on the server side — we trust the LLM's self-tag.
    clause_text = (question_clause or "").strip() if isinstance(question_clause, str) else ""
    if is_change_intent and clause_text:
        # Preview what `_enforce_session_monitors` will add at S3 so the
        # check sees the brief as the participant will see it. Foundational-
        # topic OQs (upload / primary_goal / search_strategy) are owned by
        # the monitor state machine and aren't in the LLM's patch — without
        # this preview, the verifier would falsely flag the cold-start
        # primary-goal ask and pause the pipeline (Bug C in the plan).
        # Local import to dodge the circular module dependency that
        # derivation has on schemas/services already loaded.
        try:
            from app.routers.sessions.derivation import _enforce_session_monitors
            preview_brief = _enforce_session_monitors(
                merged_brief, workflow_mode, test_problem_id=test_problem_id
            )
        except Exception:  # pragma: no cover — defensive
            log.exception("Monitor preview raised; treating as no-op for ask_without_oq check")
            preview_brief = merged_brief
        new_oqs = _new_open_questions(base_brief, preview_brief)
        oq_actions = patch.get("oq_actions") if isinstance(patch, dict) else None
        retargets_existing = False
        if isinstance(oq_actions, list):
            for a in oq_actions:
                if not isinstance(a, dict):
                    continue
                action = str(a.get("action") or "").strip().lower()
                if action in {"rephrase", "mark_answered"}:
                    retargets_existing = True
                    break
        if not new_oqs and not retargets_existing:
            issues.append(
                PipelineIssue(
                    category="ask_without_oq",
                    severity="error",
                    subject="open_questions",
                    message=(
                        "Your visible reply asks the participant a clarifying "
                        f"question (\"{clause_text}\") but the brief carries no "
                        "matching open_question. Either add an OQ for the "
                        "question (set `goal_key` if it proposes a specific "
                        "goal_term), use `oq_actions` to "
                        "`rephrase`/`mark_answered` an existing OQ that "
                        "already covers it, or rephrase the reply to commit "
                        "a default instead of asking. Foundational-topic asks "
                        "(primary_goal / upload / search_strategy) are "
                        "server-managed — leave `question_clause` empty for those."
                    ),
                )
            )

    # ---- Workflow invariants ----
    if mode == "waterfall":
        # Waterfall has no assumption rows.
        items = merged_brief.get("items") if isinstance(merged_brief.get("items"), list) else []
        bad_assumption_ids = [
            str(it.get("id") or "")
            for it in items
            if isinstance(it, dict)
            and str(it.get("kind") or "").strip().lower() == "assumption"
        ]
        if bad_assumption_ids:
            issues.append(
                PipelineIssue(
                    category="workflow_invariant_violation",
                    severity="error",
                    subject="items",
                    message=(
                        "Waterfall mode does not use assumption rows — convert these to "
                        "open questions or gathered facts: "
                        + ", ".join(bid for bid in bad_assumption_ids if bid)
                    ),
                )
            )

    # ---- Run-acknowledgement invariants ----
    # Tutorial Runs 1+2 (any mode): the bubble drives the next step, so the
    # agent doesn't need to add a new assumption (agile) or OQ (waterfall).
    # Caller sets ``suppress_runack_invariant`` for those turns; we skip the
    # mode-specific check below. Demo always skipped (see comment further down).
    if is_run_acknowledgement and not suppress_runack_invariant:
        new_items = _new_items(base_brief, merged_brief)
        new_oqs = _new_open_questions(base_brief, merged_brief)
        if mode == "agile":
            has_new_assumption = any(
                isinstance(it, dict)
                and str(it.get("kind") or "").strip().lower() == "assumption"
                for it in new_items
            )
            if not has_new_assumption:
                issues.append(
                    PipelineIssue(
                        category="runack_invariant_violation",
                        severity="error",
                        subject="items",
                        message=(
                            "Agile run acknowledgements must add at least one "
                            "`kind: \"assumption\"` row summarizing what the run revealed "
                            "or what to try next."
                        ),
                    )
                )
        elif mode == "waterfall":
            if not new_oqs:
                issues.append(
                    PipelineIssue(
                        category="runack_invariant_violation",
                        severity="error",
                        subject="open_questions",
                        message=(
                            "Waterfall run acknowledgements must add at least one "
                            "open question to drive the next iteration."
                        ),
                    )
                )
        # Demo mode intentionally has no run-ack invariant: ``coerce_problem_brief_for_workflow``
        # drops assumption rows in demo, so requiring one would just create extra
        # retry pressure for an artifact the merge will immediately discard.

    # ---- Goal-term anchoring ----
    issues.extend(
        _check_goal_term_anchoring(
            merged_brief=merged_brief,
            base_brief=base_brief,
            workflow_mode=workflow_mode,
            test_problem_id=test_problem_id,
        )
    )

    # ---- Port companion check ----
    try:
        port = get_study_port(test_problem_id)
        port_issues = port.verify_brief_companion(merged_brief, visible_reply=visible_reply)
    except Exception:  # pragma: no cover — defensive
        log.exception("Port companion verification raised; treating as no-op")
        port_issues = []
    for raw in port_issues or []:
        if not isinstance(raw, dict):
            continue
        try:
            issues.append(PipelineIssue.model_validate(raw))
        except Exception:  # pragma: no cover — defensive
            log.warning("Skipping malformed port-issue: %r", raw)

    return issues


def _algorithm_from_brief(brief: dict[str, Any] | None) -> str | None:
    """Pull the committed algorithm out of the search-strategy carrier."""
    if not isinstance(brief, dict):
        return None
    gt = brief.get("goal_terms")
    ss = gt.get("search_strategy") if isinstance(gt, dict) else None
    props = ss.get("properties") if isinstance(ss, dict) else None
    algo = props.get("algorithm") if isinstance(props, dict) else None
    return str(algo).strip() if isinstance(algo, str) and algo.strip() else None


def _goal_term_label(key: str, labels: dict[str, str]) -> str:
    """Human label for a goal-term key (never leak the raw snake_case key)."""
    label = labels.get(key) if isinstance(labels, dict) else None
    if isinstance(label, str) and label.strip():
        return label.strip()
    return key.replace("_", " ").strip().capitalize()


def compute_material_brief_changes(
    base_brief: dict[str, Any] | None,
    merged_brief: dict[str, Any] | None,
    workflow_mode: str,
    test_problem_id: str | None = None,
) -> list[str]:
    """Deterministic, human-readable list of *material* (solver-affecting)
    changes between two brief states: goal-term adds / removes / retunes and a
    search-method change. Labels come from the port so no raw keys leak.

    Pure — no NL parsing, no LLM. New goal-term keys are reported only when
    they are anchored (would survive the apply layer), so a premature /
    under-specified term the server is about to drop doesn't show up as a
    phantom change. Existing-key retunes and removals are always real.

    Consumed by the S2 acknowledgement check (an LLM then judges, by meaning,
    whether the visible reply conveys each of these) and reusable as the basis
    for a participant-facing 'what changed this turn' log.
    """
    base = base_brief if isinstance(base_brief, dict) else {}
    merged = merged_brief if isinstance(merged_brief, dict) else {}
    base_gt = base.get("goal_terms") if isinstance(base.get("goal_terms"), dict) else {}
    merged_gt = merged.get("goal_terms") if isinstance(merged.get("goal_terms"), dict) else {}

    port: Any | None = None
    labels: dict[str, str] = {}
    try:
        port = get_study_port(test_problem_id)
        result = port.weight_item_labels()
        if isinstance(result, dict):
            labels = result
    except Exception:  # pragma: no cover — defensive
        port = None

    kinds = evidence_kinds_for_workflow(workflow_mode)
    items = merged.get("items") if isinstance(merged.get("items"), list) else []
    valid_ids = {
        str(it.get("id") or "")
        for it in items
        if isinstance(it, dict)
        and str(it.get("kind") or "").strip().lower() in kinds
        and str(it.get("id") or "").strip()
    }

    def _weight(entry: Any) -> float | None:
        if isinstance(entry, dict):
            w = entry.get("weight")
            if isinstance(w, (int, float)) and not isinstance(w, bool):
                return float(w)
        return None

    def _type(entry: Any) -> str | None:
        if isinstance(entry, dict):
            t = entry.get("type")
            if isinstance(t, str) and t.strip():
                return t.strip()
        return None

    out: list[str] = []
    # ``search_strategy`` is a carrier key, not a user-facing goal term — its
    # change surfaces through the algorithm diff below, not as "Added …".
    skip = {"search_strategy"}
    for key, entry in merged_gt.items():
        if not isinstance(key, str) or key in skip:
            continue
        label = _goal_term_label(key, labels)
        if key not in base_gt:
            if not is_goal_term_anchored(
                key=key, entry=entry, valid_item_ids=valid_ids, port=port
            ):
                continue  # premature / unanchored — server will drop it
            role = _type(entry) or "term"
            w = _weight(entry)
            out.append(
                f"Added {role} '{label}'" + (f" (weight {w:g})." if w is not None else ".")
            )
        else:
            old = base_gt[key]
            ow, nw = _weight(old), _weight(entry)
            ot, nt = _type(old), _type(entry)
            if ow is not None and nw is not None and abs(ow - nw) > 1e-6:
                out.append(f"Changed '{label}' weight from {ow:g} to {nw:g}.")
            if ot and nt and ot != nt:
                out.append(f"Changed '{label}' from {ot} to {nt}.")
    for key in base_gt:
        if isinstance(key, str) and key not in skip and key not in merged_gt:
            out.append(f"Removed '{_goal_term_label(key, labels)}'.")

    base_algo = _algorithm_from_brief(base)
    merged_algo = _algorithm_from_brief(merged)
    if base_algo != merged_algo:
        if merged_algo and not base_algo:
            out.append(f"Set the search method to {merged_algo}.")
        elif merged_algo and base_algo:
            out.append(f"Changed the search method from {base_algo} to {merged_algo}.")
        elif base_algo and not merged_algo:
            out.append(f"Removed the search method ({base_algo}).")
    return out


def _new_items(
    base_brief: dict[str, Any] | None,
    merged_brief: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    base_ids = {
        str(it.get("id") or "")
        for it in (base_brief.get("items") if isinstance(base_brief, dict) else None) or []
        if isinstance(it, dict)
    }
    out: list[dict[str, Any]] = []
    for it in (merged_brief.get("items") if isinstance(merged_brief, dict) else None) or []:
        if not isinstance(it, dict):
            continue
        if str(it.get("id") or "") not in base_ids:
            out.append(it)
    return out


def _new_open_questions(
    base_brief: dict[str, Any] | None,
    merged_brief: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    base_ids = {
        str(q.get("id") or "")
        for q in (base_brief.get("open_questions") if isinstance(base_brief, dict) else None) or []
        if isinstance(q, dict)
    }
    out: list[dict[str, Any]] = []
    for q in (merged_brief.get("open_questions") if isinstance(merged_brief, dict) else None) or []:
        if not isinstance(q, dict):
            continue
        if str(q.get("id") or "") not in base_ids:
            out.append(q)
    return out


def _check_goal_term_anchoring(
    *,
    merged_brief: dict[str, Any],
    base_brief: dict[str, Any] | None,
    workflow_mode: str,
    test_problem_id: str | None,
) -> list[PipelineIssue]:
    """Flag newly-added goal_term keys that lack any valid anchor.

    Mirrors the production anchoring filter but emits warnings instead of
    dropping the keys — verification's job is to surface; the merge layer
    still hard-drops unanchored adds as a defence-in-depth.
    """
    issues: list[PipelineIssue] = []
    goal_terms = merged_brief.get("goal_terms") if isinstance(merged_brief.get("goal_terms"), dict) else {}
    if not isinstance(goal_terms, dict) or not goal_terms:
        return issues
    base_keys: set[str] = set()
    if isinstance(base_brief, dict) and isinstance(base_brief.get("goal_terms"), dict):
        base_keys = {k for k in base_brief["goal_terms"].keys() if isinstance(k, str)}
    port: Any | None = None
    auto_anchored: frozenset[str] = frozenset()
    if test_problem_id is not None:
        try:
            port = get_study_port(test_problem_id)
        except Exception:  # pragma: no cover — defensive
            port = None
        # ``auto_anchored_goal_term_keys`` is on the ``StudyProblemPort``
        # Protocol but isn't a runtime requirement — VRPTW doesn't define
        # it, in which case ``getattr`` falls through to the empty default.
        # Catching the lookup separately from the registry lookup keeps
        # ``port`` available for ``is_goal_term_self_anchored`` (e.g.
        # ``worker_preference`` with non-empty rules, ``shift_limit`` with
        # ``max_shift_hours``) even when ``auto_anchored_goal_term_keys``
        # is missing. Same split as ``filter_unanchored_new_goal_terms``.
        if port is not None:
            try:
                fn = getattr(port, "auto_anchored_goal_term_keys", None)
                if callable(fn):
                    result = fn()
                    if isinstance(result, (frozenset, set)):
                        auto_anchored = frozenset(result)
            except Exception:  # pragma: no cover — defensive
                auto_anchored = frozenset()
    kinds = evidence_kinds_for_workflow(workflow_mode)
    items = merged_brief.get("items") if isinstance(merged_brief.get("items"), list) else []
    valid_ids = {
        str(it.get("id") or "")
        for it in items
        if isinstance(it, dict)
        and str(it.get("kind") or "").strip().lower() in kinds
        and str(it.get("id") or "").strip()
    }
    # Keys with a pending OQ asking about K are treated as "deferred to OQ" —
    # the apply layer (``filter_unanchored_new_goal_terms``) drops the
    # premature goal_term commit and lets the OQ stand alone. Don't double-
    # fire ``unanchored_goal_term`` on those keys; the LLM's intent of
    # "I'm asking, not committing" is already captured by the OQ row.
    pending_oq_keys: set[str] = set()
    open_questions = merged_brief.get("open_questions") if isinstance(merged_brief.get("open_questions"), list) else []
    for q in open_questions:
        if not isinstance(q, dict):
            continue
        if str(q.get("status") or "open").strip().lower() != "open":
            continue
        gk = q.get("goal_key")
        if isinstance(gk, str) and gk.strip():
            pending_oq_keys.add(gk.strip())
    for key, entry in goal_terms.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        if key in base_keys or key in auto_anchored:
            continue
        if key in pending_oq_keys:
            continue
        if not is_goal_term_anchored(key=key, entry=entry, valid_item_ids=valid_ids, port=port):
            issues.append(
                PipelineIssue(
                    category="unanchored_goal_term",
                    severity="error",
                    subject=f"goal_terms.{key}",
                    message=(
                        f"The new goal-term `{key}` has no evidence anchor in the brief. "
                        f"Either cite an items[] id under `evidence_item_ids`, populate "
                        f"the structured `properties` carrier, or omit the goal term."
                    ),
                )
            )
    return issues


# ---------------------------------------------------------------------------
# S5 — panel verification
# ---------------------------------------------------------------------------


_DRIFT_KIND_TO_CATEGORY: dict[str, str] = {
    "missing_in_panel": "brief_panel_mismatch",
    "missing_in_brief": "brief_panel_mismatch",
    "value_mismatch": "brief_panel_mismatch",
    "mirror_mismatch": "port_companion",
    "algorithm_mismatch": "brief_panel_algorithm_mismatch",
}


def verify_panel_consistency(
    *,
    brief: dict[str, Any],
    panel: dict[str, Any] | None,
    workflow_mode: str,
    test_problem_id: str | None = None,
) -> list[PipelineIssue]:
    """Run deterministic S5 checks against the derived panel.

    Schema sanity is handled here (panel shape, inner.problem present); the
    actual brief↔panel drift detection delegates to
    ``sync.compute_brief_panel_drift`` so the researcher diagnostic panel and
    the pipeline S5 stage share a single source of truth. Drift entries are
    converted to ``PipelineIssue`` via ``_DRIFT_KIND_TO_CATEGORY``.
    """
    from app.routers.sessions.sync import _drift_message, compute_brief_panel_drift

    issues: list[PipelineIssue] = []
    if not isinstance(panel, dict):
        issues.append(
            PipelineIssue(
                category="schema_invalid",
                severity="error",
                subject="panel",
                message="Panel was empty or malformed; expected `{ problem: {...} }`.",
            )
        )
        return issues
    inner = panel.get("problem")
    if not isinstance(inner, dict):
        issues.append(
            PipelineIssue(
                category="schema_invalid",
                severity="error",
                subject="panel.problem",
                message="Panel is missing the inner `problem` object.",
            )
        )
        return issues

    drift = compute_brief_panel_drift(brief, panel, test_problem_id=test_problem_id)
    for entry in drift:
        kind = entry.get("kind") or ""
        key = entry.get("key") or ""
        category = _DRIFT_KIND_TO_CATEGORY.get(kind, "brief_panel_mismatch")
        if kind == "algorithm_mismatch":
            subject = "algorithm"
        elif kind == "mirror_mismatch":
            subject = f"panel.{entry.get('detail') or key}"
        else:
            subject = f"goal_terms.{key}"
        issues.append(
            PipelineIssue(
                category=category,
                severity="error",
                subject=subject,
                message=_drift_message(entry),
            )
        )
    return issues


# ---------------------------------------------------------------------------
# Categorization helpers for the status-bubble sub-rows
# ---------------------------------------------------------------------------


def categorize_panel_issues(issues: Iterable[PipelineIssue]) -> dict[str, list[PipelineIssue]]:
    """Split S5 issues into 'goal_terms' vs 'algorithm' sub-rows."""
    out: dict[str, list[PipelineIssue]] = {"goal_terms": [], "algorithm": [], "other": []}
    for issue in issues:
        if issue.category == "brief_panel_algorithm_mismatch":
            out["algorithm"].append(issue)
        elif issue.category in ("brief_panel_mismatch", "port_companion"):
            out["goal_terms"].append(issue)
        else:
            out["other"].append(issue)
    return out


def issues_to_audit_payload(issues: Iterable[PipelineIssue]) -> list[dict[str, Any]]:
    """Convert PipelineIssue list to the dict shape ``generate_main_turn``
    expects under ``verification_issues``."""
    return [
        {
            "category": i.category,
            "severity": i.severity,
            "subject": i.subject,
            "message": i.message,
        }
        for i in issues
    ]
