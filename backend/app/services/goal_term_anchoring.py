"""Anchor goal_terms entries to brief items.

Each `goal_terms[key]` entry should be backed by at least one brief `items[]`
row (a `gathered` fact, plus `assumption` rows in agile/demo). The brief-update
LLM cites those rows by id in `evidence_item_ids`. This module enforces that
contract — primary check is the cited ids; secondary is an embedding-cosine
fallback against item text; tertiary is the per-port auto-anchor for terms
whose own `properties` carry their justification (e.g. VRPTW's
`worker_preference` is implicitly anchored when it has driver-preference rules).

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

# Canonical MEALpy algorithm names + aliases the participant might use.
# Closed vocabulary by design (5 algorithms only). Matching is case-insensitive
# substring against item text — robust enough for this small a key set, and
# avoids reintroducing the brittle regex-against-NL patterns we've been moving
# away from for everything else.
_ALGORITHM_BRIEF_ALIASES: tuple[str, ...] = (
    "ga",
    "genetic algorithm",
    "genetic search",
    "evolutionary search",
    "pso",
    "particle swarm",
    "swarm search",
    "sa",
    "simulated annealing",
    "annealing search",
    "swarmsa",
    "swarm-based simulated annealing",
    "acor",
    "ant colony",
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


def _self_anchored_by_properties(key: str, entry: dict[str, Any]) -> bool:
    """Per-port auto-anchor: a goal_term whose own structured properties carry
    the user-stated rules is implicitly anchored. The structured rule list is
    its own justification — there's no separate prose row to cite.
    """
    props = entry.get("properties") if isinstance(entry, dict) else None
    if not isinstance(props, dict):
        return False
    if key == "worker_preference":
        rules = props.get("driver_preferences")
        if isinstance(rules, list) and rules:
            return True
    if key == "shift_limit":
        if "max_shift_hours" in props:
            return True
    return False


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
        api_key=api_key, texts=item_texts, task_type="RETRIEVAL_DOCUMENT"
    )
    if item_vectors is None:
        return out
    query_vectors = _embed_texts(
        api_key=api_key, texts=queries, task_type="RETRIEVAL_QUERY"
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
) -> bool:
    """Cheap per-entry anchor check — explicit cite OR self-anchored properties.

    The embedding fallback is intentionally NOT inside this function: it
    requires a network call and should be done once per batch of unanchored
    keys, not per-key. See ``filter_unanchored_new_goal_terms``.
    """
    if not isinstance(entry, dict):
        return False
    if _self_anchored_by_properties(key, entry):
        return True
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
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Drop newly-introduced goal_term keys that have no evidence anchor.

    Existing keys (already present in ``base_brief.goal_terms``) are passed
    through unchanged — enforcement only applies to keys this patch / derive
    pass would *add*. Returns ``(filtered_goal_terms, dropped_keys)``.

    Anchor priority:
    1. Explicit ``evidence_item_ids`` resolves to a valid items[] id.
    2. Self-anchored properties (e.g. worker_preference + driver_preferences).
    3. Embedding cosine ≥ threshold against any item text (if api_key given).
    """
    if not isinstance(proposed_goal_terms, dict):
        return {}, []
    base_keys: set[str] = set()
    if isinstance(base_brief, dict):
        base_gt = base_brief.get("goal_terms")
        if isinstance(base_gt, dict):
            base_keys = {k for k in base_gt.keys() if isinstance(k, str)}

    kinds = evidence_kinds_for_workflow(workflow_mode)
    valid_ids = _valid_item_ids({"items": items}, kinds)

    cheap_anchored: dict[str, bool] = {}
    needs_embedding: list[tuple[str, dict[str, Any]]] = []
    for key, entry in proposed_goal_terms.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        if key in base_keys:
            cheap_anchored[key] = True
            continue
        if is_goal_term_anchored(key=key, entry=entry, valid_item_ids=valid_ids):
            cheap_anchored[key] = True
            continue
        cheap_anchored[key] = False
        needs_embedding.append((key, entry))

    embedding_results = _embedding_anchored(
        keys=needs_embedding,
        brief_items=items if isinstance(items, list) else [],
        api_key=api_key,
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


def algorithm_mentioned_in_brief(items: list[dict[str, Any]] | None) -> bool:
    """Return True iff at least one brief item names a known search algorithm.

    Used by the panel-derive merge to decide whether the LLM is allowed to
    overwrite the current panel's algorithm / epochs / pop_size /
    algorithm_params fields. If no item names an algorithm, the LLM's choice
    is treated as unsolicited and the current panel value is preserved.

    Closed 5-algorithm vocabulary; case-insensitive substring match. Word-
    boundary checked for the short aliases (`ga`, `sa`, `pso`, `acor`) to
    avoid false positives like "garbage" or "psoriasis".
    """
    if not isinstance(items, list):
        return False
    short_aliases = frozenset({"ga", "sa", "pso", "acor"})
    for item in items:
        if not isinstance(item, dict):
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
