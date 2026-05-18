"""Anchor goal_terms entries to brief items.

Each `goal_terms[key]` entry should be backed by at least one brief `items[]`
row (a `gathered` fact, plus `assumption` rows in agile/demo). The brief-update
LLM cites those rows by id in `evidence_item_ids`. This module enforces that
contract — primary check is the cited ids; secondary is an embedding-cosine
fallback against item text; tertiary is the per-port self-anchor hook
(`StudyProblemPort.is_goal_term_self_anchored`) for terms whose own
`properties` carry their justification, plus the closed-vocabulary opt-out
(`StudyProblemPort.auto_anchored_goal_term_keys`) for problems whose key set
is too tightly scoped for misuse to be plausible.

Problem-specific knowledge (which keys self-anchor on which property fields,
which keys can be auto-trusted) is owned by the port. This module stays
problem-agnostic.

Existing terms (already in `base_brief.goal_terms`) are tolerated without
evidence — enforcement only fires on **newly introduced** keys, so the
contract upgrades gracefully across older briefs.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Iterable

log = logging.getLogger(__name__)

_AGILE_LIKE_MODES = frozenset({"agile", "demo"})
# Cosine threshold for the embedding fallback. Tuned permissively — the goal
# is to catch obvious hallucinations ("worker_preference" appearing when no
# item mentions drivers/preferences), not to gate every borderline match.
_EMBEDDING_ANCHOR_THRESHOLD = 0.55

# Closed vocabulary of MEALpy algorithm names + plain-language aliases —
# the canonical source lives in `app.algorithm_catalog` so anchoring,
# prompts, and (future) frontend stay aligned. Matching is case-
# insensitive substring against item text.
from app.algorithm_catalog import (
    ALGORITHM_BRIEF_ALIASES as _ALGORITHM_BRIEF_ALIASES,
    ALGORITHM_BRIEF_ALIAS_MAP as _ALGORITHM_BRIEF_ALIAS_MAP,
)


def evidence_kinds_for_workflow(workflow_mode: str | None) -> frozenset[str]:
    mode = str(workflow_mode or "").strip().lower()
    if mode in _AGILE_LIKE_MODES:
        return frozenset({"gathered", "assumption"})
    return frozenset({"gathered"})


def _valid_item_ids(brief: dict[str, Any] | None, kinds: frozenset[str]) -> set[str]:
    if not isinstance(brief, dict):
        return set()
    items = brief.get("items")
    if not isinstance(items, list):
        return set()
    out: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in kinds:
            continue
        item_id = str(item.get("id") or "").strip()
        if item_id:
            out.add(item_id)
    return out


def _entry_anchor_text(key: str, entry: dict[str, Any]) -> str:
    """Embedding query text for a goal term. Combines the key name with any
    label-ish hint we can pull from the entry — keys like `lateness_penalty`
    on their own embed reasonably, but adding type/properties context helps.
    """
    parts: list[str] = [key.replace("_", " ")]
    term_type = entry.get("type") if isinstance(entry, dict) else None
    if isinstance(term_type, str) and term_type:
        parts.append(term_type)
    return " ".join(parts).strip()


def _vector_norm(vec: Iterable[float]) -> float:
    total = 0.0
    for v in vec:
        total += v * v
    return math.sqrt(total)


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    na = _vector_norm(a)
    nb = _vector_norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _embedding_anchored(
    *,
    keys: list[tuple[str, dict[str, Any]]],
    brief_items: list[dict[str, Any]],
    api_key: str | None,
    embedding_model: str | None = None,
) -> dict[str, bool]:
    """Best-effort embedding fallback. Returns a key→bool map.

    On missing api key or any embedding failure, every key resolves to False
    (the caller treats False as "not anchored") — the explicit-pointer path
    is the load-bearing one; embeddings are a backstop, not a gate.
    """
    out = {key: False for key, _ in keys}
    if not api_key or not keys or not brief_items:
        return out
    item_texts = [
        str(item.get("text") or "").strip()
        for item in brief_items
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    if not item_texts:
        return out

    try:
        from app.services.docs_index import _embed_texts
    except Exception as exc:  # pragma: no cover — defensive import
        log.warning("Embedding anchor check unavailable (%s)", exc)
        return out

    queries = [_entry_anchor_text(key, entry) for key, entry in keys]
    item_vectors = _embed_texts(
        api_key=api_key,
        texts=item_texts,
        task_type="RETRIEVAL_DOCUMENT",
        model=embedding_model,
    )
    if item_vectors is None:
        return out
    query_vectors = _embed_texts(
        api_key=api_key,
        texts=queries,
        task_type="RETRIEVAL_QUERY",
        model=embedding_model,
    )
    if query_vectors is None:
        return out

    for (key, _entry), q_vec in zip(keys, query_vectors):
        best = max((_cosine(q_vec, iv) for iv in item_vectors), default=0.0)
        out[key] = best >= _EMBEDDING_ANCHOR_THRESHOLD
    return out


def is_goal_term_anchored(
    *,
    key: str,
    entry: dict[str, Any],
    valid_item_ids: set[str],
    port: Any | None = None,
) -> bool:
    """Cheap per-entry anchor check — port self-anchor OR explicit cite.

    The embedding fallback is intentionally NOT inside this function: it
    requires a network call and should be done once per batch of unanchored
    keys, not per-key. See ``filter_unanchored_new_goal_terms``.
    """
    if not isinstance(entry, dict):
        return False
    if port is not None:
        try:
            if port.is_goal_term_self_anchored(key, entry):
                return True
        except Exception:  # pragma: no cover — defensive
            pass
    evidence = entry.get("evidence_item_ids")
    if isinstance(evidence, list):
        for eid in evidence:
            if isinstance(eid, str) and eid.strip() in valid_item_ids:
                return True
    return False


def filter_unanchored_new_goal_terms(
    *,
    base_brief: dict[str, Any] | None,
    proposed_goal_terms: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
    workflow_mode: str | None,
    api_key: str | None = None,
    test_problem_id: str | None = None,
    embedding_model: str | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Drop newly-introduced goal_term keys that have no evidence anchor.

    Existing keys (already present in ``base_brief.goal_terms``) are passed
    through unchanged — enforcement only applies to keys this patch / derive
    pass would *add*. Returns ``(filtered_goal_terms, dropped_keys)``.

    Anchor priority:
    1. Key declared in port.auto_anchored_goal_term_keys() (closed-vocabulary
       opt-out for problems whose key set is too small/intrinsic to misuse).
    2. Explicit ``evidence_item_ids`` resolves to a valid items[] id.
    3. Self-anchored properties (e.g. worker_preference + driver_preferences).
    4. Embedding cosine ≥ threshold against any item text (if api_key given).
    """
    if not isinstance(proposed_goal_terms, dict):
        return {}, []
    base_keys: set[str] = set()
    if isinstance(base_brief, dict):
        base_gt = base_brief.get("goal_terms")
        if isinstance(base_gt, dict):
            base_keys = {k for k in base_gt.keys() if isinstance(k, str)}

    port: Any | None = None
    auto_anchored: frozenset[str] = frozenset()
    if test_problem_id is not None:
        try:
            from app.problems.registry import get_study_port

            port = get_study_port(test_problem_id)
            auto_anchored = port.auto_anchored_goal_term_keys()
        except Exception:  # pragma: no cover — defensive, never gate on registry hiccups
            port = None
            auto_anchored = frozenset()

    kinds = evidence_kinds_for_workflow(workflow_mode)
    valid_ids = _valid_item_ids({"items": items}, kinds)

    cheap_anchored: dict[str, bool] = {}
    needs_embedding: list[tuple[str, dict[str, Any]]] = []
    for key, entry in proposed_goal_terms.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        if key in base_keys or key in auto_anchored:
            cheap_anchored[key] = True
            continue
        if is_goal_term_anchored(
            key=key, entry=entry, valid_item_ids=valid_ids, port=port
        ):
            cheap_anchored[key] = True
            continue
        cheap_anchored[key] = False
        needs_embedding.append((key, entry))

    embedding_results = _embedding_anchored(
        keys=needs_embedding,
        brief_items=items if isinstance(items, list) else [],
        api_key=api_key,
        embedding_model=embedding_model,
    )

    filtered: dict[str, dict[str, Any]] = {}
    dropped: list[str] = []
    for key, entry in proposed_goal_terms.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        if cheap_anchored.get(key) or embedding_results.get(key):
            filtered[key] = entry
        else:
            dropped.append(key)
    if dropped:
        log.info(
            "Goal-term anchoring dropped unanchored new keys: %s (workflow=%s)",
            dropped,
            workflow_mode,
        )
    return filtered, dropped


SEARCH_STRATEGY_PANEL_FIELDS: tuple[str, ...] = (
    "algorithm",
    "algorithm_params",
    "epochs",
    "pop_size",
    "early_stop",
    "early_stop_patience",
    "early_stop_epsilon",
    "use_greedy_init",
    "random_seed",
)


_SEARCH_STRATEGY_BRIEF_SLOTS: frozenset[str] = frozenset(
    {"search_strategy", "algorithm", "epochs", "pop_size"}
)


def brief_mentions_search_strategy(
    brief: dict[str, Any] | None,
    *,
    test_problem_id: str | None = None,
    workflow_mode: str | None = None,
) -> bool:
    """Return True iff the brief carries a recorded signal that justifies
    a search-strategy panel block.

    Three signals (any one is sufficient):

    1. **Structured carrier.** ``brief.goal_terms.search_strategy.properties.algorithm``
       holds a non-empty algorithm name. This is the canonical structured
       store for the algorithm choice — when the LLM commits it via the
       brief patch, the carrier alone is the source of truth. Previously
       this signal was missing here, so a brief carrying ``"GA"`` in the
       carrier but no separate items[] row got its panel ``algorithm``
       stripped by ``sync_panel_from_problem_brief``'s workflow-legitimacy
       gate, then S5 verify_panel flagged brief↔panel drift in a loop.
    2. **Slot-tagged item.** A brief item whose id resolves to a search-
       strategy slot (``search_strategy``, ``algorithm``, ``epochs``,
       ``pop_size``, or any ``algorithm_param:*``).
    3. **Algorithm name mentioned in text.** The closed-vocabulary text
       scanner so chat-only mentions (e.g. *"let's start with GA"*) count
       even before the panel has been synced.

    The gate is workflow-agnostic and problem-agnostic: it only asks
    whether the brief has a recorded reason to expose search-strategy
    fields in the saved panel.
    """
    if not isinstance(brief, dict):
        return False
    # Structured carrier check — runs FIRST because it's the canonical
    # signal and doesn't depend on items[] being populated.
    goal_terms = brief.get("goal_terms")
    if isinstance(goal_terms, dict):
        ss_entry = goal_terms.get("search_strategy")
        if isinstance(ss_entry, dict):
            props = ss_entry.get("properties")
            if isinstance(props, dict):
                algo = props.get("algorithm")
                if isinstance(algo, str) and algo.strip():
                    return True
    raw_items = brief.get("items")
    items: list[dict[str, Any]] = (
        [item for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )
    if not items:
        return False
    if algorithm_mentioned_in_brief(items, workflow_mode=workflow_mode):
        return True
    try:
        from app.problem_brief import problem_brief_item_slot
    except Exception:  # pragma: no cover — defensive import
        return False
    accepted_kinds = evidence_kinds_for_workflow(workflow_mode) if workflow_mode is not None else {"gathered", "assumption"}
    for item in items:
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in accepted_kinds:
            continue
        slot = problem_brief_item_slot(item, test_problem_id=test_problem_id)
        if slot is None:
            continue
        if slot in _SEARCH_STRATEGY_BRIEF_SLOTS or slot.startswith("algorithm_param:"):
            return True
    return False


def extract_algorithm_from_brief(items: list[dict[str, Any]] | None) -> str | None:
    """Return the first canonical algorithm name mentioned in any brief item.

    Closed 5-algorithm vocabulary (single source of truth:
    ``ALGORITHM_BRIEF_ALIAS_MAP``). Scan order is by descending alias length
    so longer/more-specific aliases win — e.g. *"swarm-based simulated
    annealing"* resolves to ``SwarmSA`` rather than ``SA``.

    Used by problem-port brief→panel seeds so that when the brief carries a
    gathered/assumption row naming an algorithm (e.g. *"Genetic search is
    being used."*), the deterministic seed can populate ``panel.algorithm``
    even when the LLM panel-derive omits it. Returns ``None`` when no item
    text contains an alias. Word-boundary checked for the 2-3 char acronyms
    (``ga``, ``sa``, ``pso``, ``acor``) to avoid false positives.
    """
    if not isinstance(items, list):
        return None
    short_aliases = frozenset({"ga", "sa", "pso", "acor"})
    aliases_by_length = sorted(
        _ALGORITHM_BRIEF_ALIAS_MAP.items(),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").lower()
        if not text:
            continue
        for alias, canonical in aliases_by_length:
            if alias not in text:
                continue
            if alias in short_aliases:
                idx = 0
                while True:
                    pos = text.find(alias, idx)
                    if pos < 0:
                        break
                    before_ok = pos == 0 or not text[pos - 1].isalnum()
                    after_pos = pos + len(alias)
                    after_ok = after_pos >= len(text) or not text[after_pos].isalnum()
                    if before_ok and after_ok:
                        return canonical
                    idx = pos + 1
            else:
                return canonical
    return None


def algorithm_mentioned_in_brief(
    items: list[dict[str, Any]] | None,
    workflow_mode: str | None = None,
) -> bool:
    """Return True iff at least one brief item names a known search algorithm.

    Used by the panel-derive merge to decide whether the LLM is allowed to
    overwrite the current panel's algorithm / epochs / pop_size /
    algorithm_params fields. If no item names an algorithm, the LLM's choice
    is treated as unsolicited and the current panel value is preserved.

    When ``workflow_mode`` is provided, only items of an accepted
    ``kind`` count as evidence (waterfall: ``gathered`` only; agile/demo:
    ``gathered`` or ``assumption``). When ``None`` (back-compat default),
    every kind is accepted.

    Closed 5-algorithm vocabulary; case-insensitive substring match. Word-
    boundary checked for the short aliases (`ga`, `sa`, `pso`, `acor`) to
    avoid false positives like "garbage" or "psoriasis".
    """
    if not isinstance(items, list):
        return False
    accepted_kinds = (
        evidence_kinds_for_workflow(workflow_mode) if workflow_mode is not None else None
    )
    short_aliases = frozenset({"ga", "sa", "pso", "acor"})
    for item in items:
        if not isinstance(item, dict):
            continue
        if accepted_kinds is not None:
            kind = str(item.get("kind") or "").strip().lower()
            if kind not in accepted_kinds:
                continue
        text = str(item.get("text") or "").lower()
        if not text:
            continue
        for alias in _ALGORITHM_BRIEF_ALIASES:
            if alias not in text:
                continue
            if alias in short_aliases:
                # Require word boundaries for the 2-3 char acronyms.
                idx = 0
                while True:
                    pos = text.find(alias, idx)
                    if pos < 0:
                        break
                    before_ok = pos == 0 or not text[pos - 1].isalnum()
                    after_pos = pos + len(alias)
                    after_ok = after_pos >= len(text) or not text[after_pos].isalnum()
                    if before_ok and after_ok:
                        return True
                    idx = pos + 1
            else:
                return True
    return False
