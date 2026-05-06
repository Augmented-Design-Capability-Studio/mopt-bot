"""Structural brief→panel derivation for VRPTW.

Used as a deterministic fallback when the LLM-driven path
(``app.services.llm.generate_config_from_brief``) is unavailable.

This module **only** parses brief items that the panel→brief sync emitted with
known structural IDs (``config-weight-*``, ``config-search-strategy``,
``config-epochs``, …) — i.e. round-trip recovery.  It does **not** attempt
natural-language parsing of free-form participant text; that is the LLM's job.
The previous regex/keyword-marker layer was removed because every fix added one
new exception (negation, novel phrasing, etc.) without ever closing the
fundamental ambiguity of NLP-by-substring.

If the brief contains no structural IDs and no LLM is available, this returns
``None`` and the participant gets the starter panel until the LLM is reachable.
"""

from __future__ import annotations

import re
from typing import Any

from app.algorithm_catalog import DEFAULT_EPOCHS, DEFAULT_POP_SIZE

_ALGORITHM_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bparticle swarm\b|\bpso\b", re.IGNORECASE), "PSO"),
    (re.compile(r"\bgenetic algorithm\b|\bga\b", re.IGNORECASE), "GA"),
    (re.compile(r"\bswarmsa\b|\bswarm sa\b|swarm-based simulated annealing", re.IGNORECASE), "SwarmSA"),
    (re.compile(r"\bsimulated annealing\b|\bsa\b", re.IGNORECASE), "SA"),
    (re.compile(r"\bant colony\b|\bacor\b", re.IGNORECASE), "ACOR"),
)
_EXPLICIT_VALUE_RE = re.compile(
    r"\b(?:set to|weight(?:ed)? to|weight(?:ed)? at|target(?:ed)? at|target(?:ed)? of|target of|penalty of)\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_ITERATIONS_COMPACT_RE = re.compile(
    r"\bmax\s+iterations?\s+(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_EPOCHS_COMPACT_RE = re.compile(r"\bepochs?\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_POP_SWARM_SIZE_COMPACT_RE = re.compile(
    r"\b(?:population|swarm)\s+size\s+(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)


def _detect_algorithm_in_text(text: str) -> str | None:
    for pattern, algorithm in _ALGORITHM_PATTERNS:
        if pattern.search(text):
            return algorithm
    return None


def _default_algorithm_block(algorithm: str) -> dict[str, Any]:
    base = {
        "algorithm": algorithm,
        "epochs": DEFAULT_EPOCHS,
        "pop_size": DEFAULT_POP_SIZE,
    }
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


def _extract_structured_slots(problem_brief: dict[str, Any]) -> tuple[dict[str, float], dict[str, Any]]:
    """Read panel-synced config rows by stable id / text prefix.

    Items the panel→brief sync wrote out carry IDs like ``config-weight-<key>``
    or ``config-search-strategy``; that's the only signal we trust for
    deterministic recovery.  Free-form participant text without a config-* ID
    is left to the LLM.
    """
    weights: dict[str, float] = {}
    structured: dict[str, Any] = {
        "algorithm": None,
        "epochs": None,
        "pop_size": None,
        "max_shift_hours": None,
        "only_active_terms": None,
        "use_greedy_init": None,
        "early_stop": None,
        "early_stop_patience": None,
        "early_stop_epsilon": None,
        "random_seed": None,
    }
    # Free-form fallback for algorithm: any gathered/assumption row that names a
    # search method seeds `structured["algorithm"]` if no structurally-tagged
    # `config-search-strategy` row is present. This covers the common case where
    # the chat agent commits an algorithm choice via an assumption row (e.g.
    # *"Using genetic search (GA) with greedy initialization enabled."*) but
    # the panel-derive LLM forgets to emit `algorithm` in the same turn —
    # `_backfill_solver_fields_from_seed` then fills it from this seed value.
    for item in problem_brief.get("items", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").strip().lower() == "rejected":
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in {"gathered", "assumption"}:
            continue
        item_id = str(item.get("id") or "").strip()
        # Don't double-process structurally-tagged rows here; the canonical
        # loop below handles them with full overlay extraction.
        if item_id.startswith("config-"):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if structured["algorithm"] is None:
            algo = _detect_algorithm_in_text(text)
            if algo is not None:
                structured["algorithm"] = algo

    for item in problem_brief.get("items", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").strip().lower() == "rejected":
            continue
        item_id = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        lowered = text.lower()
        numeric_match = _EXPLICIT_VALUE_RE.search(text)
        numeric_value = float(numeric_match.group(1)) if numeric_match else None

        if item_id.startswith("config-weight-"):
            key = item_id.removeprefix("config-weight-")
            if numeric_value is not None:
                weights[key] = numeric_value
            continue
        if item_id == "config-search-strategy":
            structured["algorithm"] = _detect_algorithm_in_text(text)
            compact_epochs = _ITERATIONS_COMPACT_RE.search(text) or _EPOCHS_COMPACT_RE.search(text)
            if compact_epochs:
                val = float(compact_epochs.group(1))
                structured["epochs"] = int(val) if val.is_integer() else val
            compact_pop = _POP_SWARM_SIZE_COMPACT_RE.search(text)
            if compact_pop:
                val = float(compact_pop.group(1))
                structured["pop_size"] = int(val) if val.is_integer() else val
            tl = lowered
            if re.search(r"\bgreedy initialization on\b", tl):
                structured["use_greedy_init"] = True
            elif re.search(r"\bgreedy initialization off\b", tl):
                structured["use_greedy_init"] = False
            if re.search(r"\bstop early on plateau on\b", tl):
                structured["early_stop"] = True
            elif re.search(r"\bstop early on plateau off\b", tl):
                structured["early_stop"] = False
            mp = re.search(r"\bplateau patience\s+(\d+)\b", text, re.IGNORECASE)
            if mp:
                structured["early_stop_patience"] = int(mp.group(1))
            me = re.search(r"\bmin improvement epsilon\s+([0-9.eE+-]+)\b", text, re.IGNORECASE)
            if me:
                structured["early_stop_epsilon"] = float(me.group(1))
            mr = re.search(r"\brandom seed\s+(-?\d+)\b", text, re.IGNORECASE)
            if mr:
                structured["random_seed"] = int(mr.group(1))
            continue
        if item_id == "config-only-active-terms":
            if "only active objective terms should be applied" in lowered:
                structured["only_active_terms"] = True
            elif "inactive objective terms may also remain available" in lowered:
                structured["only_active_terms"] = False
            continue
        if item_id == "config-epochs" and numeric_value is not None:
            structured["epochs"] = int(numeric_value) if numeric_value.is_integer() else numeric_value
            continue
        if item_id == "config-pop-size" and numeric_value is not None:
            structured["pop_size"] = int(numeric_value) if numeric_value.is_integer() else numeric_value
            continue
        if item_id == "config-shift-hard-penalty" and numeric_value is not None:
            structured["max_shift_hours"] = numeric_value

    return weights, structured


def _structured_search_overlay_present(structured: dict[str, Any]) -> bool:
    return any(
        structured.get(k) is not None
        for k in (
            "use_greedy_init",
            "early_stop",
            "early_stop_patience",
            "early_stop_epsilon",
            "random_seed",
        )
    )


def derive_problem_panel_from_brief(
    problem_brief: dict[str, Any],
) -> dict[str, Any] | None:
    """Recover a panel from structurally-tagged brief items only.

    Returns ``None`` when the brief contains no recoverable config-* IDs — the
    LLM is the canonical path for anything else, and the caller will fall back
    to the starter panel.
    """
    if not isinstance(problem_brief, dict):
        return None

    weights, structured = _extract_structured_slots(problem_brief)
    has_signal = (
        bool(weights)
        or structured["algorithm"] is not None
        or structured["epochs"] is not None
        or structured["pop_size"] is not None
        or structured["max_shift_hours"] is not None
        or structured["only_active_terms"] is not None
        or _structured_search_overlay_present(structured)
    )
    if not has_signal:
        return None

    algorithm = structured["algorithm"] or "GA"
    algorithm_block = _default_algorithm_block(algorithm)
    if structured["epochs"] is not None:
        algorithm_block["epochs"] = structured["epochs"]
    if structured["pop_size"] is not None:
        algorithm_block["pop_size"] = structured["pop_size"]

    only_active_terms = structured["only_active_terms"]
    problem: dict[str, Any] = {
        "weights": weights,
        "only_active_terms": True if only_active_terms is None else only_active_terms,
        **algorithm_block,
    }
    if structured["max_shift_hours"] is not None:
        problem["max_shift_hours"] = structured["max_shift_hours"]
    if structured["use_greedy_init"] is not None:
        problem["use_greedy_init"] = bool(structured["use_greedy_init"])
    if structured["early_stop"] is not None:
        problem["early_stop"] = bool(structured["early_stop"])
    if structured["early_stop_patience"] is not None:
        problem["early_stop_patience"] = int(structured["early_stop_patience"])
    if structured["early_stop_epsilon"] is not None:
        problem["early_stop_epsilon"] = float(structured["early_stop_epsilon"])
    if structured["random_seed"] is not None:
        problem["random_seed"] = int(structured["random_seed"])
    return {"problem": problem}
