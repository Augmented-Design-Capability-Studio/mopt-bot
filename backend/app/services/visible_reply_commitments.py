"""Deterministic detection and structural-carrier injection for commits made
in a visible chat reply.

The chat-turn LLM is supposed to emit a structured ``problem_brief_patch``
alongside any visible commitment ("I've set search strategy to GA"), but it
sometimes drops the structural carrier even when the visible reply commits.
The resulting symptom is the participant-visible run button staying greyed
out because the assumption row that anchors the algorithm never landed.

This module provides:

- :func:`extract_algorithm_commitment` — closed-vocabulary scan of a visible
  reply for a canonical algorithm name (GA / PSO / SA / SwarmSA / ACOR).
- :func:`brief_mentions_algorithm` — check whether the merged brief
  (base + patch) already carries an items[] row that anchors that algorithm.
- :func:`inject_algorithm_assumption` — synthesize and append a `kind:
  "assumption"` row to a brief patch so brief→panel derivation can pick the
  algorithm up.
- :func:`speculative_intrinsic_gate_ready` — predict whether the intrinsic
  gate would be ready after a synthetic algorithm injection lands. Used to
  decide whether the agent's run-invitation phrasing is going to mismatch the
  actual run-button state.

All helpers are pure (no LLM, no DB) and reuse the existing closed-vocabulary
table from :mod:`app.algorithm_catalog` so the detection vocabulary stays
aligned with the post-merge anchor / extract logic in
:mod:`app.services.goal_term_anchoring`.

Scope: agile mode only. Waterfall files algorithm choice as an open question
(no proactive default), demo treats it as an OQ-not-assumption (per the
demo workflow guidance), so the structural carrier semantics this module
enforces only apply to agile.
"""

from __future__ import annotations

import logging
from typing import Any

from app.algorithm_catalog import (
    ALGORITHM_BRIEF_ALIAS_MAP,
    ALGORITHM_NICKNAMES_PARTICIPANT,
)

log = logging.getLogger(__name__)


_SHORT_ALIASES = frozenset({"ga", "sa", "pso", "acor"})


def extract_algorithm_commitment(text: str | None) -> str | None:
    """Scan ``text`` for the first canonical algorithm name mentioned.

    Mirrors :func:`goal_term_anchoring.extract_algorithm_from_brief` so the
    pre-release detection vocabulary stays aligned with the post-merge
    anchor / extract logic. Longest alias wins (so "swarm-based simulated
    annealing" resolves to ``SwarmSA`` rather than ``SA``). Short acronym
    aliases (``ga``, ``sa``, ``pso``, ``acor``) are word-boundary checked
    so prose like "saga" or "Gandalf" doesn't false-positive.

    Returns the canonical algorithm name (``GA``, ``PSO``, ``SA``,
    ``SwarmSA``, ``ACOR``) or ``None`` when no alias is mentioned.
    """
    if not text:
        return None
    lowered = text.lower()
    aliases_by_length = sorted(
        ALGORITHM_BRIEF_ALIAS_MAP.items(),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )
    for alias, canonical in aliases_by_length:
        if alias not in lowered:
            continue
        if alias in _SHORT_ALIASES:
            idx = 0
            while True:
                pos = lowered.find(alias, idx)
                if pos < 0:
                    break
                before_ok = pos == 0 or not lowered[pos - 1].isalnum()
                after_pos = pos + len(alias)
                after_ok = after_pos >= len(lowered) or not lowered[after_pos].isalnum()
                if before_ok and after_ok:
                    return canonical
                idx = pos + 1
        else:
            return canonical
    return None


def brief_mentions_algorithm(brief: dict[str, Any] | None, algorithm: str) -> bool:
    """True iff the brief's items[] already carries a row whose text names
    ``algorithm`` (canonical name or any alias). Same closed-vocabulary scan
    as :func:`extract_algorithm_commitment`.

    Caller passes the *merged* brief (base + patch) so we don't double-emit.
    """
    if not isinstance(brief, dict):
        return False
    items_raw = brief.get("items")
    if not isinstance(items_raw, list):
        return False
    canonical_target = algorithm.strip()
    if not canonical_target:
        return False
    for item in items_raw:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        found = extract_algorithm_commitment(text)
        if found is not None and found.lower() == canonical_target.lower():
            return True
    return False


def _participant_nickname_for(algorithm: str) -> str:
    """Return a participant-facing label like 'genetic search (GA)' so the
    synthesized assumption row reads naturally in the Definition tab.

    Falls back to the canonical name if the catalog hasn't enumerated a
    nickname for the algorithm (defensive — both lists are kept in sync in
    :mod:`app.algorithm_catalog`).
    """
    canonical = algorithm.strip()
    for nickname in ALGORITHM_NICKNAMES_PARTICIPANT:
        if f"({canonical})" in nickname:
            return nickname
    return canonical


def synthesize_algorithm_assumption_row(algorithm: str) -> dict[str, Any]:
    """Build the assumption items[] row that anchors ``algorithm`` in the
    brief. Stable id (``item-assumption-algorithm-<algo>``) so re-injection
    on a subsequent turn doesn't accumulate duplicate rows.
    """
    canonical = algorithm.strip()
    nickname = _participant_nickname_for(canonical)
    return {
        "id": f"item-assumption-algorithm-{canonical.lower()}",
        "text": f"Search strategy is set to {nickname} as a starting point — change anytime.",
        "kind": "assumption",
        "source": "agent",
        "status": "active",
        "editable": True,
    }


def inject_algorithm_assumption(
    brief_patch: dict[str, Any] | None,
    base_brief: dict[str, Any] | None,
    algorithm: str,
) -> tuple[dict[str, Any] | None, bool]:
    """If ``algorithm`` is not already anchored in ``base_brief`` merged with
    ``brief_patch``, append a synthesized assumption row to ``brief_patch``
    and return the augmented patch. Returns ``(patch, did_inject)``.

    Does NOT mutate the caller's inputs. Returns a fresh patch dict (or the
    original reference when nothing changed) so callers can branch on
    ``did_inject`` for logging / pipeline-decision purposes.
    """
    canonical = algorithm.strip()
    if not canonical:
        return brief_patch, False

    if brief_mentions_algorithm(base_brief, canonical):
        return brief_patch, False

    patch_items_raw = (brief_patch or {}).get("items") if isinstance(brief_patch, dict) else None
    patch_items = [item for item in patch_items_raw if isinstance(item, dict)] if isinstance(patch_items_raw, list) else []
    for item in patch_items:
        text = item.get("text")
        if isinstance(text, str):
            found = extract_algorithm_commitment(text)
            if found is not None and found.lower() == canonical.lower():
                return brief_patch, False

    new_row = synthesize_algorithm_assumption_row(canonical)
    new_patch: dict[str, Any] = dict(brief_patch) if isinstance(brief_patch, dict) else {}
    existing_items = list(new_patch.get("items") or [])
    existing_items.append(new_row)
    new_patch["items"] = existing_items
    return new_patch, True


def speculative_brief_after_patch(
    base_brief: dict[str, Any] | None,
    brief_patch: dict[str, Any] | None,
) -> dict[str, Any]:
    """Cheap merge: union of base brief items[] + patch items[], plus the
    patch's goal_terms / open_questions overrides. NOT a full pipeline merge
    (no anchor / coercion / OQ maintenance) — strictly for the speculative
    intrinsic-gate probe.

    Equivalent to a light version of ``merge_problem_brief_patch`` that skips
    the heavier passes. Using the real merge here would risk import cycles
    and double the cost of the probe.
    """
    from copy import deepcopy

    out: dict[str, Any] = deepcopy(base_brief) if isinstance(base_brief, dict) else {}
    if not isinstance(brief_patch, dict):
        return out

    if isinstance(brief_patch.get("items"), list):
        existing = list(out.get("items") or [])
        existing_ids = {
            str(item.get("id") or "")
            for item in existing
            if isinstance(item, dict)
        }
        for item in brief_patch["items"]:
            if not isinstance(item, dict):
                continue
            iid = str(item.get("id") or "")
            if iid and iid in existing_ids:
                continue
            existing.append(item)
            if iid:
                existing_ids.add(iid)
        out["items"] = existing

    if isinstance(brief_patch.get("goal_terms"), dict):
        merged_gt = dict(out.get("goal_terms") or {})
        for k, v in brief_patch["goal_terms"].items():
            if isinstance(k, str):
                merged_gt[k] = v
        out["goal_terms"] = merged_gt

    return out


def speculative_intrinsic_gate_ready(
    workflow_mode: str,
    base_brief: dict[str, Any] | None,
    base_panel: dict[str, Any] | None,
    brief_patch: dict[str, Any] | None,
    algorithm_commitment: str | None,
    problem_id: str | None,
    optimization_gate_engaged: bool = True,
) -> bool:
    """Predict whether ``intrinsic_optimization_ready`` would pass once
    ``brief_patch`` lands and the algorithm (if committed) is reflected on
    the panel.

    The real gate reads from the *panel* (``inner.algorithm``) and the brief
    (``goal_terms``). The panel gets updated by background derivation, so at
    pre-release time we synthesize a *speculative* panel that mirrors what
    sync would produce: original panel ∪ {algorithm: <commitment>} when an
    algorithm was committed and the panel doesn't already have one. We then
    run the existing gate function against (speculative_brief,
    speculative_panel) — no duplicated gate logic.

    ``optimization_gate_engaged`` defaults to True because speculation
    answers "what will the gate state be after this turn commits?" and a
    user-visible turn flips the engagement flag at commit time. Callers
    that want to model a non-engaging turn (e.g. a synthetic run-ack
    before any visible chat) can pass False explicitly.
    """
    from copy import deepcopy

    from app.optimization_gate import intrinsic_optimization_ready

    speculative_brief = speculative_brief_after_patch(base_brief, brief_patch)
    speculative_panel = deepcopy(base_panel) if isinstance(base_panel, dict) else {}
    if algorithm_commitment:
        inner = speculative_panel.get("problem") if isinstance(speculative_panel.get("problem"), dict) else None
        if inner is None:
            inner = speculative_panel
        existing_algo = str(inner.get("algorithm") or "").strip() if isinstance(inner, dict) else ""
        if not existing_algo and isinstance(inner, dict):
            inner["algorithm"] = algorithm_commitment

    return intrinsic_optimization_ready(
        workflow_mode,
        speculative_panel,
        speculative_brief,
        optimization_gate_engaged=optimization_gate_engaged,
        problem_id=problem_id,
    )
