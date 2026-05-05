"""Deterministic panel seeding from problem brief (knapsack vocabulary)."""

from __future__ import annotations

import re
from typing import Any

# Re-use algorithm / numeric extraction from VRPTW seed (duplicated minimal subset)
_ENTRY_SPLIT_RE = re.compile(r"[\n\r]+|(?<=[.!?;])\s+")
_ALGORITHM_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bparticle swarm\b|\bpso\b", re.IGNORECASE), "PSO"),
    (re.compile(r"\bgenetic algorithm\b|\bga\b", re.IGNORECASE), "GA"),
    (re.compile(r"\bswarmsa\b|\bswarm sa\b|swarm-based simulated annealing", re.IGNORECASE), "SwarmSA"),
    (re.compile(r"\bsimulated annealing\b|\bsa\b", re.IGNORECASE), "SA"),
    (re.compile(r"\bant colony\b|\bacor\b", re.IGNORECASE), "ACOR"),
)
_EXPLICIT_VALUE_RE = re.compile(
    r"\b(?:set to|is set to|weight(?:ed)? to|target(?:ed)? at|penalty of|penalty is|use)\s+(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_ITERATIONS_COMPACT_RE = re.compile(r"\b(?:max\s+)?iterations?\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_EPOCHS_COMPACT_RE = re.compile(r"\bepochs?\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_POP_SWARM_SIZE_COMPACT_RE = re.compile(
    r"\b(?:population|swarm)\s+size\s+(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)


def _brief_entries(problem_brief: dict[str, Any]) -> list[str]:
    entries: list[str] = []
    for item in problem_brief.get("items", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip().lower() not in {"gathered", "assumption"}:
            continue
        text = str(item.get("text") or "").strip()
        if text:
            entries.append(text)
    return entries


def _entry_fragments(problem_brief: dict[str, Any]) -> list[str]:
    fragments: list[str] = []
    for entry in _brief_entries(problem_brief):
        parts = [part.strip(" ,") for part in _ENTRY_SPLIT_RE.split(entry) if part.strip(" ,")]
        fragments.extend(parts or [entry])
    return fragments


def _detect_algorithm(entries: list[str]) -> str | None:
    for text in reversed(entries):
        for pattern, algorithm in _ALGORITHM_PATTERNS:
            if pattern.search(text):
                return algorithm
    return None


def _default_algorithm_block(algorithm: str) -> dict[str, Any]:
    defaults: dict[str, dict[str, Any]] = {
        "GA": {"algorithm": "GA", "algorithm_params": {"pc": 0.9, "pm": 0.05}, "epochs": 80, "pop_size": 40},
        "PSO": {"algorithm": "PSO", "algorithm_params": {"c1": 2.0, "c2": 2.0, "w": 0.4}, "epochs": 80, "pop_size": 50},
        "SA": {
            "algorithm": "SA",
            "algorithm_params": {"temp_init": 100, "cooling_rate": 0.99},
            "epochs": 120,
            "pop_size": 40,
        },
        "SwarmSA": {
            "algorithm": "SwarmSA",
            "algorithm_params": {
                "max_sub_iter": 10,
                "t0": 1.0,
                "t1": 0.01,
                "move_count": 5,
                "mutation_rate": 0.1,
                "mutation_step_size": 0.1,
                "mutation_step_size_damp": 0.99,
            },
            "epochs": 80,
            "pop_size": 40,
        },
        "ACOR": {
            "algorithm": "ACOR",
            "algorithm_params": {"sample_count": 25, "intent_factor": 0.5, "zeta": 1.0},
            "epochs": 80,
            "pop_size": 40,
        },
    }
    return defaults.get(algorithm, defaults["GA"]).copy()


def _extract_numeric_setting(entries: list[str], markers: tuple[str, ...]) -> float | None:
    marker_set = frozenset(markers)
    epoch_markers = frozenset(("epoch", "epochs", "iteration", "iterations"))
    pop_markers = frozenset(("population size", "swarm size"))
    for text in reversed(entries):
        lowered = text.lower()
        if not any(marker in lowered for marker in markers):
            continue
        match = _EXPLICIT_VALUE_RE.search(text)
        if match:
            return float(match.group(1))
        if marker_set & epoch_markers:
            m2 = _ITERATIONS_COMPACT_RE.search(text) or _EPOCHS_COMPACT_RE.search(text)
            if m2:
                return float(m2.group(1))
        if marker_set & pop_markers:
            m2 = _POP_SWARM_SIZE_COMPACT_RE.search(text)
            if m2:
                return float(m2.group(1))
    return None


_SIGNALS: dict[str, tuple[re.Pattern[str], ...]] = {
    "value_emphasis": (
        re.compile(r"\bvalue\b", re.IGNORECASE),
        re.compile(r"\bprofit\b", re.IGNORECASE),
        re.compile(r"\bpacking value\b", re.IGNORECASE),
    ),
    "capacity_overflow": (
        # Keep this tuple in sync with `KnapsackStudyPort.weight_slot_markers`
        # (study_port.py) so the deterministic seed and the validator agree on
        # what counts as capacity-related text in a brief item.
        re.compile(r"\bcapacity\b", re.IGNORECASE),
        re.compile(r"\boverflow\b", re.IGNORECASE),
        re.compile(r"\bweight limit\b", re.IGNORECASE),
        re.compile(r"\bweight cap\b", re.IGNORECASE),
        re.compile(r"\bweight constraint\b", re.IGNORECASE),
        re.compile(r"\bbag weight\b", re.IGNORECASE),
        re.compile(r"\bload limit\b", re.IGNORECASE),
    ),
    "selection_sparsity": (
        # Keep this tuple in sync with `KnapsackStudyPort.weight_slot_markers`
        # (study_port.py); the validator uses the markers tuple, this one
        # drives the deterministic seed fallback when the LLM derivation is
        # unavailable.
        re.compile(r"\bsparsity\b", re.IGNORECASE),
        re.compile(r"\bfewer items\b", re.IGNORECASE),
        re.compile(r"\bcompact\b", re.IGNORECASE),
        re.compile(r"\bselection size\b", re.IGNORECASE),
        re.compile(r"\bselected items\b", re.IGNORECASE),
        re.compile(r"\bnumber of items\b", re.IGNORECASE),
        re.compile(r"\bitem count\b", re.IGNORECASE),
        re.compile(r"\bsmaller bag\b", re.IGNORECASE),
        re.compile(r"\blighter knapsack\b", re.IGNORECASE),
    ),
}


def _mentions(entries: list[str], key: str) -> list[str]:
    pats = _SIGNALS[key]
    return [text for text in entries if any(p.search(text) for p in pats)]


def _extract_for_key(entries: list[str], key: str) -> float | None:
    pats = _SIGNALS[key]
    for text in reversed(entries):
        for match in _EXPLICIT_VALUE_RE.finditer(text):
            prefix = text[: match.start()]
            if any(p.search(prefix[-120:]) for p in pats):
                return float(match.group(1))
    for text in reversed(entries):
        m = _EXPLICIT_VALUE_RE.search(text)
        if m:
            return float(m.group(1))
    return None


def derive_problem_panel_from_brief(problem_brief: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(problem_brief, dict):
        return None
    fragments = _entry_fragments(problem_brief)
    if not fragments:
        return None

    weights: dict[str, float] = {}
    for key in _SIGNALS:
        hits = _mentions(fragments, key)
        if hits:
            v = _extract_for_key(hits, key)
            weights[key] = v if v is not None else (1.0 if key == "value_emphasis" else 10.0)

    explicit_algorithm = _detect_algorithm(fragments)
    epochs = _extract_numeric_setting(fragments, ("epoch", "epochs", "iteration", "iterations"))
    pop_size = _extract_numeric_setting(fragments, ("population size", "swarm size"))

    if not weights and explicit_algorithm is None and epochs is None and pop_size is None:
        return None

    algorithm = explicit_algorithm or "GA"
    algorithm_block = _default_algorithm_block(algorithm)
    if epochs is not None:
        algorithm_block["epochs"] = int(epochs) if epochs.is_integer() else epochs
    if pop_size is not None:
        algorithm_block["pop_size"] = int(pop_size) if pop_size.is_integer() else pop_size

    problem: dict[str, Any] = {
        "weights": weights,
        "only_active_terms": True,
        **algorithm_block,
    }
    return {"problem": problem}
