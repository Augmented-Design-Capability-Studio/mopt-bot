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


def _grounded_goal_term_keys(
    problem_brief: dict[str, Any] | None,
    *,
    weight_slot_markers: dict[str, tuple[str, ...]],
) -> set[str]:
    grounded: set[str] = set()
    if not isinstance(problem_brief, dict):
        return grounded

    def _ground_from_text(text_value: Any) -> None:
        text = str(text_value or "").strip().lower()
        if not text:
            return
        for key, markers in weight_slot_markers.items():
            if key in grounded:
                continue
            for marker in markers:
                token = str(marker or "").strip().lower()
                if token and token in text:
                    grounded.add(key)
                    break

    items = problem_brief.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip().lower()
            if kind not in {"gathered", "assumption"}:
                continue
            item_id = str(item.get("id") or "").strip().lower()
            if item_id.startswith("config-weight-"):
                candidate = item_id.removeprefix("config-weight-").strip()
                if candidate:
                    grounded.add(candidate)
            _ground_from_text(item.get("text"))

    # Open questions also count as evidence the concept is in scope. This
    # matters in demo mode (and waterfall) where the agent often raises the
    # capacity / sparsity question as an OQ before any gathered row exists —
    # without this, validate_problem_goal_terms would reject the panel even
    # though the agent and participant both clearly know the concept applies.
    open_questions = problem_brief.get("open_questions")
    if isinstance(open_questions, list):
        for question in open_questions:
            if isinstance(question, str):
                _ground_from_text(question)
            elif isinstance(question, dict):
                _ground_from_text(question.get("text"))
                _ground_from_text(question.get("answer_text"))

    # Goal/run summaries are top-level prose surfaces and frequently carry the
    # canonical phrasing ("maximize value", "respect capacity") even when no
    # individual gathered row spells it out yet. Scanning them here closes the
    # cold-start grounding gap where a starter prompt's intent lives in the
    # summary but hasn't been split into items.
    _ground_from_text(problem_brief.get("goal_summary"))
    _ground_from_text(problem_brief.get("run_summary"))

    return grounded


def validate_problem_goal_terms(
    *,
    problem: dict[str, Any] | None,
    problem_brief: dict[str, Any] | None,
    weight_slot_markers: dict[str, tuple[str, ...]],
    check_grounding: bool = True,
) -> list[dict[str, str]]:
    """Validate goal-term structure and (optionally) check brief grounding.

    Splits results by severity:

    * **Structural errors** — shape, ``type`` enum, ``goal_term_order`` referencing
      missing keys.  These are panel data-integrity bugs and **block the save**:
      raised as ``GoalTermValidationError``.
    * **Grounding warnings** — panel ``goal_terms`` keys that brief markers don't
      recognise.  The structured-output schema (``panel_patch_response_json_schema``)
      already restricts the LLM to a closed key set per problem, so an "ungrounded"
      key is a soft signal, not a deadlock.  Returned to the caller (which surfaces
      them as participant-facing advice) and **do not block** the save.

    Returning warnings instead of raising on grounding decouples marker maintenance
    from panel save-ability: novel chat phrasings ("cap weight at 50") can no longer
    deadlock the participant, and the per-problem marker tables stay small without
    needing to grow whenever a user invents a new way to phrase a constraint.

    Args:
        problem: Panel ``problem`` dict to validate.
        problem_brief: Brief used to compute marker grounding for warnings.
        weight_slot_markers: Per-problem markers (from the study port).
        check_grounding: If False, skip grounding warnings entirely (used for
            user-driven panel saves where the participant is authoritative).

    Returns:
        List of grounding-warning reason dicts (each ``{"code": ..., "message": ...}``).
        May be empty.

    Raises:
        GoalTermValidationError: When the panel has structural errors that must
        block the save.
    """
    if not isinstance(problem, dict):
        return []
    goal_terms = problem.get("goal_terms")
    if not isinstance(goal_terms, dict):
        return []

    structural: list[dict[str, str]] = []
    grounding: list[dict[str, str]] = []
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

    if check_grounding:
        grounded_keys = _grounded_goal_term_keys(problem_brief, weight_slot_markers=weight_slot_markers)
        if grounded_keys:
            # Brief has at least one marker hit; anything in the panel that
            # isn't grounded becomes a soft warning (not a save-blocker).
            ungrounded = sorted(present_keys - grounded_keys)
            for key in ungrounded:
                grounding.append(
                    {
                        "code": "goal_term_hallucinated",
                        "key": key,
                        "message": f"goal term '{key}' is not grounded in definition items.",
                    }
                )
        elif present_keys:
            # Cold-start: brief has no marker hits anywhere. The schema already
            # restricts the key vocabulary, so just log and pass through.
            log.info(
                "Goal-term grounding skipped: brief has no marker signal yet; "
                "trusting schema-restricted panel keys %s",
                sorted(present_keys),
            )

    if structural:
        raise GoalTermValidationError(structural)
    return grounding


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
    if current_goal_terms:
        merged_goal_terms = deepcopy(current_goal_terms)
        for key, entry in derived_goal_terms.items():
            current_entry = merged_goal_terms.get(key)
            if isinstance(current_entry, dict):
                # Preserve canonical semantics from the current panel, but keep new weight/rank values.
                current_entry["weight"] = float(entry.get("weight", current_entry.get("weight", 0.0)))
                if "rank" in entry:
                    current_entry["rank"] = entry["rank"]
            else:
                merged_goal_terms[key] = deepcopy(entry)
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
) -> tuple[dict | None, list[str], list[dict[str, str]]]:
    """Sync the panel from the brief.

    Returns ``(panel, weight_warnings, grounding_warnings)``.

    * ``panel`` is the persisted panel (or ``None`` if the brief was too sparse to
      derive anything).
    * ``weight_warnings`` come from the per-problem ``sanitize_panel_config``.
    * ``grounding_warnings`` are non-blocking notices about goal-term keys the
      validator's brief markers didn't recognise.  Callers should surface them as
      participant-facing advice (the panel is still committed).

    Raises:
        GoalTermValidationError: only for **structural** validator errors
        (shape, type, order).  Hallucination-style grounding mismatches no longer
        block the save — they're returned as warnings.
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
        return None, [], []

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

    # Structural errors raise; grounding mismatches return as advisory warnings.
    grounding_warnings = validate_problem_goal_terms(
        problem=next_problem,
        problem_brief=problem_brief,
        weight_slot_markers=port.weight_slot_markers(),
    )
    if grounding_warnings:
        log.info(
            "Goal-term grounding warnings (non-blocking) for session %s: %s",
            row.id,
            grounding_warnings,
        )

    next_panel["problem"] = next_problem
    merged, weight_warnings = port.sanitize_panel_config(next_panel)
    if merged == current_panel:
        return merged, weight_warnings, grounding_warnings

    log.info("Participant synced panel_config from brief: %s", merged)
    row.panel_config_json = json.dumps(merged)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return merged, weight_warnings, grounding_warnings


def grounding_advice_message(grounding_warnings: list[dict[str, str]]) -> str | None:
    """Format participant-facing advice from grounding warnings.

    Surfaced as a non-blocking assistant chat note; the panel still commits.
    Returns ``None`` when there's nothing to say.
    """
    keys = sorted({w.get("key") for w in grounding_warnings if isinstance(w, dict) and w.get("key")})
    keys = [k for k in keys if isinstance(k, str)]
    if not keys:
        return None
    quoted = ", ".join(f"`{k}`" for k in keys)
    plural = "terms" if len(keys) > 1 else "term"
    return (
        f"Heads up: I added the goal {plural} {quoted} to Problem Config based on the brief, "
        f"but couldn't tie {('them' if len(keys) > 1 else 'it')} to a specific Definition item. "
        f"If {('they' if len(keys) > 1 else 'it')} doesn't match your goals, remove "
        f"{('them' if len(keys) > 1 else 'it')} from the Problem Config tab."
    )


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
