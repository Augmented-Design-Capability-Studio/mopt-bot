"""Canonical algorithm names and algorithm_params keys (must match plugin implementations)."""

from __future__ import annotations

from typing import Any, Sequence

# Defaults for top-level search configuration.
DEFAULT_EPOCHS = 100
DEFAULT_POP_SIZE = 50


# Closed vocabulary of MEALpy algorithm acronyms used everywhere as the
# canonical key set: structured-output schemas, the optimizer registry,
# and the brief-anchor "did the user mention an algorithm?" check.
CANONICAL_ALGORITHM_NAMES: tuple[str, ...] = ("GA", "PSO", "SA", "SwarmSA", "ACOR")


# Plain-language aliases the participant or LLM may use in chat. Lowercase
# so callers can do case-insensitive substring matching without re-casing.
# Single source of truth — duplicated lists in prompts or anchoring should
# import from here, not redeclare.
ALGORITHM_BRIEF_ALIASES: tuple[str, ...] = (
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


# Alias → canonical algorithm map used by brief-extraction. Same vocabulary
# as ``ALGORITHM_BRIEF_ALIASES`` (single source of truth); kept as a separate
# mapping so callers can recover the canonical name rather than just a bool.
# Order is irrelevant for callers — lookup is by alias key with a longest-
# match scan, so "swarm-based simulated annealing" resolves to SwarmSA even
# though "simulated annealing" alone resolves to SA.
ALGORITHM_BRIEF_ALIAS_MAP: dict[str, str] = {
    # GA
    "ga": "GA",
    "genetic algorithm": "GA",
    "genetic search": "GA",
    "evolutionary search": "GA",
    # PSO
    "pso": "PSO",
    "particle swarm": "PSO",
    "swarm search": "PSO",
    # SA
    "sa": "SA",
    "simulated annealing": "SA",
    "annealing search": "SA",
    # SwarmSA
    "swarmsa": "SwarmSA",
    "swarm-based simulated annealing": "SwarmSA",
    # ACOR
    "acor": "ACOR",
    "ant colony": "ACOR",
}


# Participant-facing nickname per canonical algorithm. Single source of truth
# for option-listing in prompts (waterfall OQ phrasing, agile "starting from
# GA — say if you'd prefer …" lines). Add a new entry here when the canonical
# set grows.
ALGORITHM_PARTICIPANT_NICKNAMES_MAP: dict[str, str] = {
    "GA": "genetic search (GA)",
    "PSO": "swarm search (PSO)",
    "SA": "annealing search (SA)",
    "SwarmSA": "swarm-based simulated annealing (SwarmSA)",
    "ACOR": "ant colony (ACOR)",
}

# Ordered tuple, kept for compatibility with callers that want a positional
# list aligned with ``CANONICAL_ALGORITHM_NAMES``.
ALGORITHM_NICKNAMES_PARTICIPANT: tuple[str, ...] = tuple(
    ALGORITHM_PARTICIPANT_NICKNAMES_MAP[name] for name in CANONICAL_ALGORITHM_NAMES
)


def format_algorithm_choices_phrase(algorithms: Sequence[str]) -> str:
    """Render an Oxford-comma list of participant-facing algorithm names.

    Unknown / unrecognized acronyms are dropped (they have no participant
    nickname). Returns ``""`` when the resulting list is empty — callers
    should fall back to a generic phrasing in that case.

    Examples:
        ``("GA", "PSO", "SA")`` → ``"genetic search (GA), swarm search (PSO),
        or annealing search (SA)"``
    """
    nicknames = [
        ALGORITHM_PARTICIPANT_NICKNAMES_MAP[name]
        for name in algorithms
        if name in ALGORITHM_PARTICIPANT_NICKNAMES_MAP
    ]
    if not nicknames:
        return ""
    if len(nicknames) == 1:
        return nicknames[0]
    if len(nicknames) == 2:
        return f"{nicknames[0]} or {nicknames[1]}"
    head = ", ".join(nicknames[:-1])
    return f"{head}, or {nicknames[-1]}"

# Allowed algorithm_params keys per algorithm — same filter sets as optimizer model construction.
ALLOWED_ALGORITHM_PARAMS: dict[str, frozenset[str]] = {
    "GA": frozenset({"pc", "pm"}),
    "PSO": frozenset({"c1", "c2", "w"}),
    "SA": frozenset({"temp_init", "cooling_rate"}),
    "SwarmSA": frozenset(
        {
            "max_sub_iter",
            "t0",
            "t1",
            "move_count",
            "mutation_rate",
            "mutation_step_size",
            "mutation_step_size_damp",
        }
    ),
    "ACOR": frozenset({"sample_count", "intent_factor", "zeta"}),
}

# Defaults match standard discovery metrics; keep in sync with active solvers.
DEFAULT_ALGORITHM_PARAMS: dict[str, dict[str, float | int]] = {
    "GA": {"pc": 0.9, "pm": 0.05},
    "PSO": {"c1": 2.05, "c2": 2.05, "w": 0.4},
    "SA": {"temp_init": 100, "cooling_rate": 0.99},
    "SwarmSA": {
        "max_sub_iter": 5,
        "t0": 1000,
        "t1": 1,
        "move_count": 5,
        "mutation_rate": 0.1,
        "mutation_step_size": 0.1,
        "mutation_step_size_damp": 0.99,
    },
    "ACOR": {"sample_count": 25, "intent_factor": 0.5, "zeta": 1.0},
}


def normalize_algorithm_name(raw: str) -> str | None:
    s = str(raw or "").strip().upper()
    if s == "SWARMSA":
        return "SwarmSA"
    if s in ("GA", "PSO", "SA", "ACOR"):
        return s
    return None


def canonical_algorithm_stored(raw: Any) -> str | None:
    """Same normalization as adapter.parse_problem_config uses for stored `algorithm` strings."""
    return normalize_algorithm_name(str(raw or "GA"))


def allowed_param_keys(algorithm: str) -> frozenset[str]:
    return ALLOWED_ALGORITHM_PARAMS.get(algorithm, frozenset())


def default_algorithm_params(algorithm: str) -> dict[str, float | int]:
    return dict(DEFAULT_ALGORITHM_PARAMS.get(algorithm, {}))


def filter_algorithm_params(
    algorithm: str,
    params: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """
    Keep only keys allowed for `algorithm`. None / missing input stays None.
    Returns (filtered_dict_or_None, warnings for dropped keys).
    """
    if params is None:
        return None, []
    if not isinstance(params, dict):
        return None, ["algorithm_params was not an object; ignored."]
    allowed = allowed_param_keys(algorithm)
    if not allowed:
        if params:
            return None, [f"algorithm_params ignored for unknown algorithm {algorithm!r}."]
        return None, []
    out: dict[str, Any] = {}
    warnings: list[str] = []
    for k, v in params.items():
        ks = str(k)
        if ks in allowed:
            out[ks] = v
        else:
            warnings.append(
                f"Algorithm parameter {ks!r} is not used by {algorithm}; it was removed from the configuration."
            )
    return out, warnings


def param_value_is_default(algorithm: str, key: str, value: Any) -> bool:
    """True if value matches catalog default for this algorithm+key (numeric tolerant)."""
    defaults = DEFAULT_ALGORITHM_PARAMS.get(algorithm) or {}
    if key not in defaults:
        return False
    d = defaults[key]
    if isinstance(value, bool) or isinstance(d, bool):
        return value == d
    try:
        fv = float(value)
        fd = float(d)
    except (TypeError, ValueError):
        return False
    return abs(fv - fd) <= 1e-9 * max(1.0, abs(fd))
