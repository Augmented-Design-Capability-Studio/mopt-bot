"""Panel and problem brief sync logic."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import StudySession
from app.problem_brief import coerce_problem_brief_for_workflow, sync_problem_brief_from_panel as merge_brief_from_panel
from app.problems.registry import DEFAULT_PROBLEM_ID

from . import helpers

log = logging.getLogger(__name__)
_GOAL_TERM_TYPE_VALUES = frozenset({"objective", "soft", "hard", "custom"})
_GOAL_TERM_VALIDATION_PREFIX = "goal_term_validation:"


class GoalTermValidationError(ValueError):
    """Raised when derived/saved goal terms are inconsistent with the brief."""

    def __init__(self, reasons: list[dict[str, str]]) -> None:
        self.reasons = reasons
        super().__init__(self.detail_text())

    def detail_text(self) -> str:
        if not self.reasons:
            return "Goal-term validation failed."
        reason_summary = "; ".join(
            f"{r.get('code', 'goal_term_invalid')}: {r.get('message', 'invalid goal term state')}"
            for r in self.reasons
        )
        return f"Goal-term validation failed: {reason_summary}"

    def processing_error_text(self) -> str:
        return f"{_GOAL_TERM_VALIDATION_PREFIX}{json.dumps(self.reasons, ensure_ascii=True)}"


def validate_problem_goal_terms(
    *,
    problem: dict[str, Any] | None,
    **_unused: Any,
) -> None:
    """Structural validation only: shape, ``type`` enum, ``goal_term_order`` refs.

    Brief-grounding (the old marker-based hallucination check) was removed:
    each problem's structured-output schema already restricts the LLM to a
    closed key set, so a "key the brief doesn't mention" is at worst an extra
    row the participant can delete — not a save-blocker.  Keeping a substring
    grounding pass meant maintaining per-problem marker tables that constantly
    drifted from real chat phrasings; ripping them out is the simplification.

    ``**_unused`` accepts ``problem_brief`` / ``weight_slot_markers`` /
    ``check_grounding`` from older callers without breaking imports during the
    transition.

    Raises:
        GoalTermValidationError: when the panel has a structural bug.
    """
    if not isinstance(problem, dict):
        return
    goal_terms = problem.get("goal_terms")
    if not isinstance(goal_terms, dict):
        return

    structural: list[dict[str, str]] = []
    present_keys: set[str] = set()
    for key, entry in goal_terms.items():
        if not isinstance(key, str):
            continue
        present_keys.add(key)
        if not isinstance(entry, dict):
            structural.append(
                {
                    "code": "goal_term_shape_invalid",
                    "message": f"goal_terms['{key}'] must be an object.",
                }
            )
            continue
        term_type = str(entry.get("type") or "").strip().lower()
        if term_type not in _GOAL_TERM_TYPE_VALUES:
            structural.append(
                {
                    "code": "goal_term_type_invalid",
                    "message": f"goal_terms['{key}'].type must be one of objective|soft|hard|custom.",
                }
            )

    order_raw = problem.get("goal_term_order")
    if isinstance(order_raw, list):
        for raw_key in order_raw:
            if not isinstance(raw_key, str):
                structural.append(
                    {
                        "code": "goal_term_order_invalid",
                        "message": "goal_term_order must contain only string keys.",
                    }
                )
                continue
            if raw_key not in present_keys:
                structural.append(
                    {
                        "code": "goal_term_order_invalid",
                        "message": f"goal_term_order references missing key '{raw_key}'.",
                    }
                )

    if structural:
        raise GoalTermValidationError(structural)


def _weights_from_problem(problem: dict[str, Any]) -> dict[str, float]:
    weights = problem.get("weights")
    if isinstance(weights, dict):
        return {
            key: float(value)
            for key, value in weights.items()
            if isinstance(key, str) and isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    goal_terms = problem.get("goal_terms")
    if isinstance(goal_terms, dict):
        out: dict[str, float] = {}
        for key, entry in goal_terms.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                continue
            value = entry.get("weight")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[key] = float(value)
        return out
    return {}


def _goal_terms_from_problem(problem: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = problem.get("goal_terms")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, entry in raw.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        weight = entry.get("weight")
        term_type = str(entry.get("type") or "").strip().lower()
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            continue
        if term_type not in _GOAL_TERM_TYPE_VALUES:
            continue
        out[key] = deepcopy(entry)
        out[key]["weight"] = float(weight)
    return out


def _apply_weight_overrides_to_goal_terms(problem: dict[str, Any], overrides: dict[str, float]) -> None:
    goal_terms = problem.get("goal_terms")
    if not isinstance(goal_terms, dict):
        return
    for key, value in overrides.items():
        entry = goal_terms.get(key)
        if isinstance(entry, dict):
            entry["weight"] = float(value)


def _run_with_timeout(callable_obj, timeout_sec: float):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(callable_obj)
    try:
        return future.result(timeout=timeout_sec)
    finally:
        # Don't block on shutdown — if the LLM thread is still running after a
        # timeout, wait=True would hold the request handler open indefinitely.
        executor.shutdown(wait=False)


def _canonicalize_locked_goal_terms(
    current_problem: dict,
    derived_problem: dict,
    companion_fields: dict[str, str],
) -> dict:
    locked_raw = current_problem.get("locked_goal_terms")
    if not isinstance(locked_raw, list):
        locked_raw = []
    locked_goal_terms = [key for key in locked_raw if isinstance(key, str)]

    current_weights = _weights_from_problem(current_problem)
    current_weight_keys: set[str] = set(current_weights.keys())

    lockable_keys = set(current_weight_keys)
    canonical_locked = [key for key in locked_goal_terms if key in lockable_keys]

    if canonical_locked:
        derived_weights = _weights_from_problem(derived_problem)
        if derived_weights:
            merged_weights = dict(derived_weights)
            for key in canonical_locked:
                if key in current_weight_keys:
                    merged_weights[key] = float(current_weights[key])
            if isinstance(derived_problem.get("weights"), dict):
                derived_problem["weights"] = merged_weights
            _apply_weight_overrides_to_goal_terms(derived_problem, merged_weights)

    for locked_key, companion_field in companion_fields.items():
        if locked_key in canonical_locked:
            companion = current_problem.get(companion_field)
            if isinstance(companion, list):
                derived_problem[companion_field] = deepcopy(companion)
            else:
                derived_problem[companion_field] = []

    if canonical_locked:
        derived_problem["locked_goal_terms"] = canonical_locked
    else:
        derived_problem.pop("locked_goal_terms", None)
    return derived_problem


def _merge_non_destructive_managed_fields(current_problem: dict, derived_problem: dict) -> dict:
    managed_keys = (
        "goal_terms",
        "weights",
        "constraint_types",
        "only_active_terms",
        "algorithm",
        "algorithm_params",
        "epochs",
        "pop_size",
        "early_stop",
        "early_stop_patience",
        "early_stop_epsilon",
        "use_greedy_init",
    )
    always_preserve_current_if_present = frozenset(
        {
            "early_stop",
            "early_stop_patience",
            "early_stop_epsilon",
            "use_greedy_init",
            # Researcher-controlled switch: never overwritten by brief→panel derivation.
            "only_active_terms",
        }
    )
    merged = deepcopy(derived_problem)
    current_goal_terms = _goal_terms_from_problem(current_problem)
    derived_goal_terms = _goal_terms_from_problem(merged)
    derived_constraint_types_raw = merged.get("constraint_types")
    derived_constraint_types: dict[str, str] = (
        {
            k: str(v).strip().lower()
            for k, v in derived_constraint_types_raw.items()
            if isinstance(k, str)
            and isinstance(v, str)
            and str(v).strip().lower() in _GOAL_TERM_TYPE_VALUES
        }
        if isinstance(derived_constraint_types_raw, dict)
        else {}
    )
    if current_goal_terms:
        merged_goal_terms = deepcopy(current_goal_terms)
        # Stale nested properties would otherwise be re-projected onto top-level fields
        # by `_apply_goal_terms_overlay`, clobbering the LLM's fresh values. Drop nested
        # copies only for the keys the LLM derived authoritative top-level values for —
        # if the LLM omitted them, keep the current properties so the round-trip via
        # goal_terms.properties still recovers driver_preferences / max_shift_hours.
        _properties_overrides = (
            ("worker_preference", "driver_preferences"),
            ("shift_limit", "max_shift_hours"),
        )
        for goal_key, top_field in _properties_overrides:
            if top_field not in derived_problem:
                continue
            entry = merged_goal_terms.get(goal_key)
            if not isinstance(entry, dict):
                continue
            props = entry.get("properties")
            if isinstance(props, dict):
                props.pop(top_field, None)
                if not props:
                    entry.pop("properties", None)
        for key, entry in derived_goal_terms.items():
            current_entry = merged_goal_terms.get(key)
            if isinstance(current_entry, dict):
                # Take fields from the LLM derivation; fall back to current only when omitted.
                # `type` must be honoured here — otherwise constraint-type changes ("make this
                # hard") never reach the panel, since the derived entry's type would be dropped.
                current_entry["weight"] = float(entry.get("weight", current_entry.get("weight", 0.0)))
                if "rank" in entry:
                    current_entry["rank"] = entry["rank"]
                if "type" in entry:
                    current_entry["type"] = entry["type"]
                if "locked" in entry:
                    current_entry["locked"] = entry["locked"]
                if "properties" in entry:
                    current_entry["properties"] = deepcopy(entry["properties"])
            else:
                merged_goal_terms[key] = deepcopy(entry)
        # The LLM derivation typically emits `weights` + `constraint_types` (not a full
        # `goal_terms` map). Seed merged_goal_terms with new entries for any derived weights
        # that weren't already in the prior panel — otherwise `_apply_goal_terms_overlay`
        # (called next, in `sanitize_panel_weights`) would rebuild `weights` from this map
        # and drop those new keys, silently erasing newly-introduced terms like `shift_limit`
        # or `worker_preference`. Also overlay derived constraint_types onto existing entries
        # so type changes ("make capacity hard") aren't reverted by the preserved old `type`.
        derived_inner_weights = merged.get("weights")
        if isinstance(derived_inner_weights, dict):
            for key, value in derived_inner_weights.items():
                if not isinstance(key, str):
                    continue
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                if key in merged_goal_terms:
                    continue
                merged_goal_terms[key] = {
                    "weight": float(value),
                    "type": derived_constraint_types.get(key, "objective"),
                }
        for key, ctype in derived_constraint_types.items():
            entry = merged_goal_terms.get(key)
            if isinstance(entry, dict):
                entry["type"] = ctype
        merged["goal_terms"] = merged_goal_terms
    current_weights = _weights_from_problem(current_problem)
    derived_weights = _weights_from_problem(merged)
    if current_weights:
        combined = dict(current_weights)
        combined.update(derived_weights)
        if isinstance(merged.get("weights"), dict):
            merged["weights"] = deepcopy(combined)
        _apply_weight_overrides_to_goal_terms(merged, combined)
    for key in managed_keys:
        if key in {"weights", "goal_terms"}:
            continue
        if key in always_preserve_current_if_present and key in current_problem:
            merged[key] = deepcopy(current_problem[key])
            continue
        if key not in merged and key in current_problem:
            merged[key] = deepcopy(current_problem[key])
    return merged


def _managed_problem_fields() -> tuple[str, ...]:
    """Managed keys are re-derived from brief each turn unless preserve mode is requested."""
    return (
        "goal_terms",
        "weights",
        "constraint_types",
        "only_active_terms",
        "algorithm",
        "algorithm_params",
        "epochs",
        "pop_size",
        "max_shift_hours",
        "driver_preferences",
        "locked_assignments",
        "early_stop",
        "early_stop_patience",
        "early_stop_epsilon",
        "use_greedy_init",
    )


def _backfill_solver_fields_from_seed(
    seed_panel: dict | None,
    problem: dict[str, Any],
) -> dict[str, Any]:
    """Fill algorithm / budget / params omitted by a partial LLM panel patch."""
    if not isinstance(seed_panel, dict):
        return problem
    seed = seed_panel.get("problem")
    if not isinstance(seed, dict):
        return problem

    out = deepcopy(problem)
    seed_algo = str(seed.get("algorithm") or "").strip()

    if not str(out.get("algorithm") or "").strip() and seed_algo:
        out["algorithm"] = seed["algorithm"]

    out_algo = str(out.get("algorithm") or "").strip()

    if out.get("epochs") is None and seed.get("epochs") is not None:
        out["epochs"] = seed["epochs"]
    if out.get("pop_size") is None and seed.get("pop_size") is not None:
        out["pop_size"] = seed["pop_size"]

    ap = out.get("algorithm_params")
    need_params = not isinstance(ap, dict) or len(ap) == 0
    if need_params and isinstance(seed.get("algorithm_params"), dict) and out_algo and seed_algo:
        if out_algo == seed_algo:
            out["algorithm_params"] = deepcopy(seed["algorithm_params"])

    if "use_greedy_init" not in out and isinstance(seed.get("use_greedy_init"), bool):
        out["use_greedy_init"] = seed["use_greedy_init"]

    return out


def sync_panel_from_problem_brief(
    row: StudySession,
    db: Session,
    problem_brief: dict,
    api_key: str | None = None,
    model_name: str | None = None,
    workflow_mode: str | None = None,
    recent_runs_summary: list | None = None,
    preserve_missing_managed_fields: bool = False,
) -> tuple[dict | None, list[str]]:
    """Sync the panel from the brief.

    Returns ``(panel, weight_warnings)`` where ``panel`` is ``None`` when the
    brief is too sparse and the LLM is unavailable to derive one.

    Raises ``GoalTermValidationError`` only for **structural** validator errors
    (shape / type / order).  Brief-grounding mismatches were ripped out — the
    LLM's structured-output schema already restricts the key vocabulary, so the
    old marker-based hallucination check produced more friction than value.
    """
    from app.problems.registry import get_study_port
    from app.services.llm import generate_config_from_brief

    test_problem_id = getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID
    port = get_study_port(test_problem_id)

    current_panel = helpers.panel_dict(row)
    derived_panel: dict | None = None
    seed_panel: dict | None = None
    if api_key and model_name:
        timeout_sec = get_settings().derivation_timeout_sec
        try:
            derived_panel = _run_with_timeout(
                lambda: generate_config_from_brief(
                    brief=problem_brief,
                    current_panel=None,
                    api_key=api_key,
                    model_name=model_name,
                    workflow_mode=workflow_mode or row.workflow_mode,
                    recent_runs_summary=recent_runs_summary,
                    test_problem_id=test_problem_id,
                ),
                timeout_sec,
            )
        except FuturesTimeoutError:
            log.warning("Config derivation timed out for session %s; falling back to deterministic seed", row.id)
    if derived_panel is None:
        seed_panel = port.derive_problem_panel_from_brief(problem_brief)
        derived_panel = seed_panel
    if derived_panel is None:
        return None, []

    next_panel = deepcopy(current_panel) if isinstance(current_panel, dict) else {}
    current_problem = deepcopy(next_panel.get("problem")) if isinstance(next_panel.get("problem"), dict) else {}
    next_problem = deepcopy(current_problem)
    for key in _managed_problem_fields():
        next_problem.pop(key, None)
    companion_fields = port.locked_companion_fields()

    derived_problem = deepcopy(derived_panel["problem"])
    derived_problem = _canonicalize_locked_goal_terms(current_problem, derived_problem, companion_fields)
    if preserve_missing_managed_fields:
        derived_problem = _merge_non_destructive_managed_fields(current_problem, derived_problem)
    next_problem.update(derived_problem)
    if seed_panel is None:
        seed_panel = port.derive_problem_panel_from_brief(problem_brief)
    next_problem = _backfill_solver_fields_from_seed(seed_panel, next_problem)

    # Structural errors only — raises GoalTermValidationError on shape / type / order bugs.
    validate_problem_goal_terms(problem=next_problem)

    next_panel["problem"] = next_problem
    merged, weight_warnings = port.sanitize_panel_config(next_panel)
    if merged == current_panel:
        return merged, weight_warnings

    log.info("Participant synced panel_config from brief: %s", merged)
    row.panel_config_json = json.dumps(merged)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return merged, weight_warnings


def sync_problem_brief_from_panel(
    row: StudySession,
    db: Session,
    panel_config: dict,
) -> dict:
    current_problem_brief = helpers.problem_brief_dict(row)
    tpid = getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID
    next_problem_brief = merge_brief_from_panel(
        current_problem_brief, panel_config, test_problem_id=tpid
    )
    next_problem_brief = coerce_problem_brief_for_workflow(next_problem_brief, row.workflow_mode)
    if next_problem_brief == current_problem_brief:
        return current_problem_brief
    row.problem_brief_json = json.dumps(next_problem_brief)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return next_problem_brief
