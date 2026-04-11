from __future__ import annotations

import re
from typing import Any

from app.algorithm_catalog import DEFAULT_EPOCHS, DEFAULT_POP_SIZE

_ENTRY_SPLIT_RE = re.compile(r"[\n\r]+|(?<=[.!?;])\s+")
_ALGORITHM_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bparticle swarm\b|\bpso\b", re.IGNORECASE), "PSO"),
    (re.compile(r"\bgenetic algorithm\b|\bga\b", re.IGNORECASE), "GA"),
    (re.compile(r"\bswarmsa\b|\bswarm sa\b|swarm-based simulated annealing", re.IGNORECASE), "SwarmSA"),
    (re.compile(r"\bsimulated annealing\b|\bsa\b", re.IGNORECASE), "SA"),
    (re.compile(r"\bant colony\b|\bacor\b", re.IGNORECASE), "ACOR"),
)

_STRONG_TERMS = ("hard", "strict", "must", "required", "enforce", "invalid")
_MODERATE_TERMS = ("moderate", "baseline", "some", "light")
_PRIMARY_TERMS = ("top priority", "primary", "first", "most important", "critical")
_SECONDARY_TERMS = ("secondary", "relatively even", "light", "minor")
_NEGATION_TERMS = (
    "ignore",
    "ignored",
    "irrelevant",
    "not important",
    "not a priority",
    "not required",
    "deprioritize",
    "de-emphasize",
    "less important",
    "don't care",
    "do not care",
)

_SIGNAL_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "travel_time": (
        re.compile(r"\btravel time\b", re.IGNORECASE),
        re.compile(r"\btravel[_\s-]?time\b", re.IGNORECASE),
        re.compile(r"\boperating time\b", re.IGNORECASE),
        re.compile(r"\bmakespan\b", re.IGNORECASE),
        # Avoid bare "duration" — matches "shift duration" (shift hard penalty) and corrupts seeding.
        re.compile(r"\broute duration\b", re.IGNORECASE),
        re.compile(r"\btrip duration\b", re.IGNORECASE),
        re.compile(r"\broute length\b", re.IGNORECASE),
        re.compile(r"\bdistance\b", re.IGNORECASE),
        re.compile(r"\btransit\b", re.IGNORECASE),
        # Fuel / mileage language is the same route-minute pressure as travel (no separate fuel product term).
        re.compile(r"\bfuel\b", re.IGNORECASE),
        re.compile(r"\bmileage\b", re.IGNORECASE),
        re.compile(r"\boperating cost\b", re.IGNORECASE),
        re.compile(r"\bfuel cost\b", re.IGNORECASE),
    ),
    "shift_limit": (
        re.compile(r"\bshift_limit\b", re.IGNORECASE),
        re.compile(r"\bshift_hard_penalty\b", re.IGNORECASE),
        re.compile(r"\bshift limit\b", re.IGNORECASE),
        re.compile(r"\bshift overtime\b", re.IGNORECASE),
        re.compile(r"\bovertime minutes\b", re.IGNORECASE),
        re.compile(r"\bminutes over shift\b", re.IGNORECASE),
        re.compile(r"\bbeyond ([\d.]+)\s*h(?:ours)?\b", re.IGNORECASE),
        re.compile(r"\bexceed max shift\b", re.IGNORECASE),
        re.compile(r"\bhours over limit\b", re.IGNORECASE),
        re.compile(r"\blong shift penalty\b", re.IGNORECASE),
    ),
    "deadline_penalty": (
        re.compile(r"\bdeadline(?:s)?\b", re.IGNORECASE),
        re.compile(r"\blate(?: arrival| arrivals|ness)?\b", re.IGNORECASE),
        re.compile(r"\btime window(?:s)?\b", re.IGNORECASE),
        re.compile(r"\bpunctual(?:ity)?\b", re.IGNORECASE),
        re.compile(r"\bon[- ]time\b", re.IGNORECASE),
    ),
    "capacity_penalty": (
        re.compile(r"\bcapacity\b", re.IGNORECASE),
        re.compile(r"\boverload\b", re.IGNORECASE),
        re.compile(r"\bload limit\b", re.IGNORECASE),
        re.compile(r"\bvehicle capacity\b", re.IGNORECASE),
        re.compile(r"\bcapacity[_\s-]?violation\b", re.IGNORECASE),
    ),
    "workload_balance": (
        re.compile(r"\bbalanced workload\b", re.IGNORECASE),
        re.compile(r"\bbalance(?:d)? workload\b", re.IGNORECASE),
        re.compile(r"\bworkload balance\b", re.IGNORECASE),
        re.compile(r"\bworkload[_\s-]?balance\b", re.IGNORECASE),
        re.compile(r"\bfair(?:ness)?\b", re.IGNORECASE),
        re.compile(r"\bequitab(?:le|ility)\b", re.IGNORECASE),
    ),
    "worker_preference": (
        re.compile(r"\bworker preference\b", re.IGNORECASE),
        re.compile(r"\bdriver preference\b", re.IGNORECASE),
        re.compile(r"\bzone avoidance\b", re.IGNORECASE),
        re.compile(r"\bprefer to avoid\b", re.IGNORECASE),
    ),
    "priority_penalty": (
        re.compile(r"\bpriority order\b", re.IGNORECASE),
        re.compile(r"\bpriority orders\b", re.IGNORECASE),
        re.compile(r"\bexpress\b", re.IGNORECASE),
        re.compile(r"\bvip\b", re.IGNORECASE),
        re.compile(r"\bsla\b", re.IGNORECASE),
        re.compile(r"\burgent\b", re.IGNORECASE),
        re.compile(r"\bpriority[_\s-]?deadline\b", re.IGNORECASE),
    ),
    "max_shift_hours": (
        re.compile(r"\bshift duration\b", re.IGNORECASE),
        # Omit bare "shift limit" (singular) — collides with the weight name "Shift limit weight …".
        re.compile(r"\bdriver shift limits?\b", re.IGNORECASE),
        re.compile(r"\bshift limits?\s+(?:are\s+)?(?:strict|treated as strict)\b", re.IGNORECASE),
        re.compile(r"\bshift compliance\b", re.IGNORECASE),
        re.compile(r"\bmaximum shift\b", re.IGNORECASE),
        re.compile(r"\bmax hours\b", re.IGNORECASE),
        re.compile(r"\bovertime limit\b", re.IGNORECASE),
        re.compile(r"\bmax_shift_hours\b", re.IGNORECASE),
    ),
}
_EXPLICIT_VALUE_RE = re.compile(
    r"\b(?:"
    r"set to|"
    r"is set to|"
    r"should be|"
    r"is|"
    r"equals?|"
    r"at|"
    r"to|"
    r"weight|"
    r"weight(?:ed)? to|"
    r"weight(?:ed)? at|"
    r"target(?:ed)? at|"
    r"target(?:ed)? of|"
    r"target of|"
    r"penalty of|"
    r"penalty|"
    r"penalty is|"
    r"use"
    r")\s+(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_ALGORITHM_PARAM_RE = re.compile(
    r"\balgorithm parameter\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+is set to\s+([^\s]+)",
    re.IGNORECASE,
)
# Panel→brief uses "Search strategy: PSO (…, c1=1.8, w=0.55)." — recover params on round-trip.
_STRATEGY_LINE_PARAM_EQ_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*([^\s,)]+)")
_STRATEGY_LINE_SKIP_KEYS = frozenset(
    {"search", "strategy", "max", "iterations", "iteration", "population", "swarm", "size"}
)
# Panel→brief sync uses compact phrases ("max iterations 33") without "set to …" wording.
_ITERATIONS_COMPACT_RE = re.compile(
    r"\b(?:max\s+)?iterations?\s+(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_EPOCHS_COMPACT_RE = re.compile(r"\bepochs?\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_POP_SWARM_SIZE_COMPACT_RE = re.compile(
    r"\b(?:population|swarm)\s+size\s+(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_EPOCH_POP_MARKERS = frozenset(("epoch", "epochs", "iteration", "iterations"))
_POP_MARKERS = frozenset(("population size", "swarm size"))


def _brief_entries(problem_brief: dict[str, Any]) -> list[str]:
    entries: list[str] = []
    for item in problem_brief.get("items", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").strip().lower() == "rejected":
            continue
        if str(item.get("kind") or "").strip().lower() == "system":
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


def _contains_negation(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in _NEGATION_TERMS)


def _contains_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _detect_algorithm(entries: list[str]) -> str | None:
    for text in reversed(entries):
        for pattern, algorithm in _ALGORITHM_PATTERNS:
            if pattern.search(text):
                return algorithm
    return None


def _default_algorithm_block(algorithm: str) -> dict[str, Any]:
    # Centralized defaults from app.algorithm_catalog. GA/PSO/SA all start here.
    base = {
        "algorithm": algorithm,
        "epochs": DEFAULT_EPOCHS,
        "pop_size": DEFAULT_POP_SIZE,
    }
    # Specific algorithm_params defaults.
    params: dict[str, dict[str, Any]] = {
        "GA": {"pc": 0.9, "pm": 0.05},
        "PSO": {"c1": 2.0, "c2": 2.0, "w": 0.4},
        "SA": {"temp_init": 100, "cooling_rate": 0.99},
        "SwarmSA": {
            "max_sub_iter": 10,
            "t0": 1.0,
            "t1": 0.01,
            "move_count": 5,
            "mutation_rate": 0.1,
            "mutation_step_size": 0.1,
            "mutation_step_size_damp": 0.99,
        },
        "ACOR": {"sample_count": 25, "intent_factor": 0.5, "zeta": 1.0},
    }
    base["algorithm_params"] = params.get(algorithm, params["GA"]).copy()
    return base


def _mentions(entries: list[str], key: str) -> list[str]:
    return [
        text
        for text in entries
        if _contains_any(text, _SIGNAL_PATTERNS[key]) and not _contains_negation(text)
    ]


def _extract_explicit_value(entries: list[str]) -> float | None:
    for text in reversed(entries):
        match = _EXPLICIT_VALUE_RE.search(text)
        if match:
            return float(match.group(1))
    return None


def _extract_explicit_value_for_key(entries: list[str], key: str) -> float | None:
    patterns = _SIGNAL_PATTERNS[key]
    for text in reversed(entries):
        for match in _EXPLICIT_VALUE_RE.finditer(text):
            prefix = text[: match.start()]
            if any(pattern.search(prefix[-120:]) for pattern in patterns):
                return float(match.group(1))
    return _extract_explicit_value(entries)


def _extract_numeric_setting(entries: list[str], markers: tuple[str, ...]) -> float | None:
    marker_set = frozenset(markers)
    for text in reversed(entries):
        lowered = text.lower()
        if not any(marker in lowered for marker in markers):
            continue
        match = _EXPLICIT_VALUE_RE.search(text)
        if match:
            return float(match.group(1))
        if marker_set & _EPOCH_POP_MARKERS:
            m2 = _ITERATIONS_COMPACT_RE.search(text) or _EPOCHS_COMPACT_RE.search(text)
            if m2:
                return float(m2.group(1))
        if marker_set & _POP_MARKERS:
            m2 = _POP_SWARM_SIZE_COMPACT_RE.search(text)
            if m2:
                return float(m2.group(1))
    return None


def _extract_algorithm_params(entries: list[str]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for text in entries:
        match = _ALGORITHM_PARAM_RE.search(text)
        if not match:
            continue
        raw_value = match.group(2).strip().rstrip(".,;:")
        lowered = raw_value.lower()
        if lowered in {"true", "false"}:
            params[match.group(1)] = lowered == "true"
            continue
        try:
            number = float(raw_value)
        except ValueError:
            params[match.group(1)] = raw_value
            continue
        params[match.group(1)] = int(number) if number.is_integer() else number
    for text in entries:
        if "search strategy:" not in text.lower():
            continue
        for match in _STRATEGY_LINE_PARAM_EQ_RE.finditer(text):
            name = match.group(1)
            if name.lower() in _STRATEGY_LINE_SKIP_KEYS:
                continue
            if name in params:
                continue
            raw_value = match.group(2).strip().rstrip(".,;:")
            lowered = raw_value.lower()
            if lowered in {"true", "false"}:
                params[name] = lowered == "true"
                continue
            try:
                number = float(raw_value)
            except ValueError:
                params[name] = raw_value
                continue
            params[name] = int(number) if number.is_integer() else number
    return params


def _extract_only_active_terms(entries: list[str]) -> bool | None:
    for text in reversed(entries):
        lowered = text.lower()
        if "only active objective terms should be applied" in lowered:
            return True
        if "inactive objective terms may also remain available" in lowered:
            return False
    return None


def derive_problem_panel_from_brief(
    problem_brief: dict[str, Any],
) -> dict[str, Any] | None:
    """Deterministically derive a full problem block from the saved brief."""
    if not isinstance(problem_brief, dict):
        return None

    entries = _brief_entries(problem_brief)
    fragments = _entry_fragments(problem_brief)
    if not fragments:
        return None

    weights: dict[str, float] = {}
    explicit_algorithm = _detect_algorithm(fragments)

    travel_entries = _mentions(fragments, "travel_time")
    if travel_entries:
        weights["travel_time"] = _extract_explicit_value_for_key(travel_entries, "travel_time") or 1.0

    shift_limit_entries = _mentions(fragments, "shift_limit")
    shift_limit_explicit: float | None = None
    if shift_limit_entries:
        shift_limit_explicit = _extract_explicit_value_for_key(shift_limit_entries, "shift_limit")
        weights["shift_limit"] = float(shift_limit_explicit) if shift_limit_explicit is not None else 500.0

    capacity_entries = _mentions(fragments, "capacity_penalty")
    if capacity_entries:
        weights["capacity_penalty"] = _extract_explicit_value_for_key(capacity_entries, "capacity_penalty") or (
            1000.0
            if any(any(term in text.lower() for term in _STRONG_TERMS) for text in capacity_entries)
            else 100.0
        )

    deadline_entries = _mentions(fragments, "deadline_penalty")
    if deadline_entries:
        explicit_value = _extract_explicit_value_for_key(deadline_entries, "deadline_penalty")
        if explicit_value is not None:
            weights["deadline_penalty"] = explicit_value
        elif any(any(term in text.lower() for term in _PRIMARY_TERMS) for text in deadline_entries):
            weights["deadline_penalty"] = 120.0
        elif any(any(term in text.lower() for term in _MODERATE_TERMS) for text in deadline_entries):
            weights["deadline_penalty"] = 50.0
        else:
            weights["deadline_penalty"] = 75.0

    workload_entries = _mentions(fragments, "workload_balance")
    if workload_entries:
        weights["workload_balance"] = _extract_explicit_value_for_key(workload_entries, "workload_balance") or (
            5.0 if any(any(term in text.lower() for term in _SECONDARY_TERMS) for text in workload_entries) else 10.0
        )
    worker_pref_entries = _mentions(fragments, "worker_preference")
    if worker_pref_entries:
        weights["worker_preference"] = _extract_explicit_value_for_key(worker_pref_entries, "worker_preference") or 10.0
    priority_entries = _mentions(fragments, "priority_penalty")
    if priority_entries:
        weights["priority_penalty"] = _extract_explicit_value_for_key(priority_entries, "priority_penalty") or 100.0

    shift_threshold_entries = _mentions(fragments, "max_shift_hours")
    max_shift_hours = None
    if shift_threshold_entries:
        max_shift_hours = _extract_explicit_value_for_key(shift_threshold_entries, "max_shift_hours") or 8.0
        # If they mentioned shift limits, give w2 a boost
        weights["shift_limit"] = max(weights.get("shift_limit", 0), 500.0)
    
    # Also check if w2 patterns captured a specific threshold like "beyond 6.5 hours"
    if max_shift_hours is None and shift_limit_entries:
        if shift_limit_explicit is None:
            weights["shift_limit"] = max(weights.get("shift_limit", 0), 500.0)
        for text in shift_limit_entries:
            match = re.search(r"beyond ([\d.]+)\s*h(?:ours)?", text, re.IGNORECASE)
            if match:
                max_shift_hours = float(match.group(1))
                break
        if max_shift_hours is None:
            max_shift_hours = 8.0

    algorithm_params = _extract_algorithm_params(fragments)
    epochs = _extract_numeric_setting(fragments, ("epoch", "epochs", "iteration", "iterations"))
    pop_size = _extract_numeric_setting(fragments, ("population size", "swarm size"))
    only_active_terms = _extract_only_active_terms(fragments)

    if (
        not weights
        and max_shift_hours is None
        and explicit_algorithm is None
        and not algorithm_params
        and epochs is None
        and pop_size is None
        and only_active_terms is None
    ):
        return None

    algorithm = explicit_algorithm or "GA"
    algorithm_block = _default_algorithm_block(algorithm)
    if algorithm_params:
        algorithm_block["algorithm_params"] = algorithm_params
    if epochs is not None:
        algorithm_block["epochs"] = int(epochs) if epochs.is_integer() else epochs
    if pop_size is not None:
        algorithm_block["pop_size"] = int(pop_size) if pop_size.is_integer() else pop_size
    
    problem: dict[str, Any] = {
        "weights": weights,
        "only_active_terms": True if only_active_terms is None else only_active_terms,
        **algorithm_block,
    }
    if max_shift_hours is not None:
        problem["max_shift_hours"] = max_shift_hours
    return {"problem": problem}
