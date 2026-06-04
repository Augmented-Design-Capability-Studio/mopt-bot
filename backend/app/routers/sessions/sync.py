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
from app.problem_brief import (
    CARRIER_ONLY_GOAL_TERM_KEYS,
    coerce_problem_brief_for_workflow,
    sync_problem_brief_from_panel as merge_brief_from_panel,
)
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


def _drift_message(entry: dict[str, Any]) -> str:
    """Plain-English message for a drift entry. Used as the issue message in
    pipeline verification AND as the LLM retry-feedback line so both sites
    speak the same language."""
    kind = entry.get("kind")
    key = entry.get("key") or ""
    if kind == "missing_in_panel":
        return (
            f"`{key}` is in the brief but not on the panel — re-derive so the "
            f"panel includes a weight + type entry for it."
        )
    if kind == "missing_in_brief":
        return (
            f"`{key}` is on the panel but not in the brief — drop the panel entry "
            f"or add a brief items[] row that anchors it."
        )
    if kind == "value_mismatch":
        field = entry.get("detail") or "field"
        brief_val = entry.get("brief_value")
        panel_val = entry.get("panel_value")
        return (
            f"`{key}.{field}` differs between brief ({brief_val!r}) and panel "
            f"({panel_val!r}). Align them to a single value."
        )
    if kind == "mirror_mismatch":
        field = entry.get("detail") or "mirror"
        return (
            f"Panel `{field}` doesn't match brief "
            f"`goal_terms.{key}.properties.{field}` — mirror the brief value into the panel."
        )
    if kind == "algorithm_mismatch":
        brief_val = entry.get("brief_value")
        panel_val = entry.get("panel_value")
        if brief_val and panel_val and brief_val != panel_val:
            return (
                f"Brief specifies algorithm `{brief_val}` but panel has `{panel_val}`. "
                f"Set the panel's `algorithm` to `{brief_val}`."
            )
        if brief_val and not panel_val:
            return (
                f"Brief specifies algorithm `{brief_val}` but panel `algorithm` is empty. "
                f"Set it to `{brief_val}`."
            )
        if panel_val and not brief_val:
            return (
                f"Panel has algorithm `{panel_val}` but the brief carrier "
                f"`goal_terms.search_strategy.properties.algorithm` is empty. "
                f"Set the carrier to `{panel_val}`."
            )
    return f"Brief ↔ panel drift on `{key}`."


def _drift_entry(
    *,
    kind: str,
    key: str,
    brief_value: Any = None,
    panel_value: Any = None,
    detail: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"kind": kind, "key": key}
    if brief_value is not None:
        entry["brief_value"] = brief_value
    if panel_value is not None:
        entry["panel_value"] = panel_value
    if detail:
        entry["detail"] = detail
    return entry


def compute_brief_panel_drift(
    problem_brief: dict[str, Any] | None,
    panel_config: dict[str, Any] | None,
    test_problem_id: str | None = None,
) -> list[dict[str, Any]]:
    """Drift entries between ``brief.goal_terms`` and ``panel.problem.goal_terms``.

    Researcher-facing diagnostic. Surfaces three kinds of mismatch:

    - ``"missing_in_panel"`` / ``"missing_in_brief"``: a goal-term key in one
      side but not the other.
    - ``"value_mismatch"``: same key on both sides but ``weight``, ``type``, or
      ``locked`` differs.
    - ``"mirror_mismatch"``: a goal-term property that the active port mirrors
      to a top-level panel field (e.g. VRPTW's
      ``goal_terms.worker_preference.properties.driver_preferences`` ↔
      ``panel.problem.driver_preferences``) is out of sync.

    Returns ``[]`` when both inputs are absent — no inputs means no drift.
    Used by ``helpers.session_to_out`` to expose ``brief_panel_drift`` and by
    the researcher resync endpoint to label what changed.

    No cold-start suppression: starter panels deliberately ship without
    ``goal_terms`` now (the agent populates them via assumption / OQ once the
    conversation warms up), so a fresh session is naturally drift-free — both
    sides agree on the empty map. Any drift that surfaces here is real.
    """
    drift: list[dict[str, Any]] = []
    brief_goal_terms = (
        problem_brief.get("goal_terms")
        if isinstance(problem_brief, dict) and isinstance(problem_brief.get("goal_terms"), dict)
        else {}
    )
    panel_problem = None
    if isinstance(panel_config, dict):
        candidate = panel_config.get("problem")
        if isinstance(candidate, dict):
            panel_problem = candidate
        else:
            panel_problem = panel_config
    panel_goal_terms = (
        panel_problem.get("goal_terms")
        if isinstance(panel_problem, dict) and isinstance(panel_problem.get("goal_terms"), dict)
        else {}
    )
    # Carrier-only goal-term keys are excluded from the bidirectional key
    # check; their values live at top-level panel fields. Algorithm carrier
    # drift surfaces below via the dedicated `algorithm_mismatch` kind.
    brief_keys = {
        k for k in brief_goal_terms.keys()
        if isinstance(k, str) and k not in CARRIER_ONLY_GOAL_TERM_KEYS
    }
    panel_keys = {
        k for k in panel_goal_terms.keys()
        if isinstance(k, str) and k not in CARRIER_ONLY_GOAL_TERM_KEYS
    }
    for key in sorted(brief_keys - panel_keys):
        drift.append(_drift_entry(kind="missing_in_panel", key=key))
    for key in sorted(panel_keys - brief_keys):
        drift.append(_drift_entry(kind="missing_in_brief", key=key))
    for key in sorted(brief_keys & panel_keys):
        brief_entry = brief_goal_terms.get(key) if isinstance(brief_goal_terms.get(key), dict) else {}
        panel_entry = panel_goal_terms.get(key) if isinstance(panel_goal_terms.get(key), dict) else {}
        for field in ("weight", "type", "locked"):
            if field not in brief_entry and field not in panel_entry:
                continue
            brief_val = brief_entry.get(field)
            panel_val = panel_entry.get(field)
            if field == "weight":
                try:
                    if (
                        isinstance(brief_val, (int, float))
                        and not isinstance(brief_val, bool)
                        and isinstance(panel_val, (int, float))
                        and not isinstance(panel_val, bool)
                        and abs(float(brief_val) - float(panel_val)) < 1e-9
                    ):
                        continue
                except (TypeError, ValueError):
                    pass
            if brief_val == panel_val:
                continue
            drift.append(
                _drift_entry(
                    kind="value_mismatch",
                    key=key,
                    brief_value=brief_val,
                    panel_value=panel_val,
                    detail=field,
                )
            )

    # Algorithm carrier drift: the brief carries the chosen algorithm at
    # ``goal_terms.search_strategy.properties.algorithm``; the panel carries
    # it at ``panel.problem.algorithm``. Surface mismatches as a structured
    # entry so the same retry/feedback flow can target it.
    brief_algo: str | None = None
    ss_entry = brief_goal_terms.get("search_strategy") if isinstance(brief_goal_terms.get("search_strategy"), dict) else None
    if isinstance(ss_entry, dict):
        props = ss_entry.get("properties") if isinstance(ss_entry.get("properties"), dict) else None
        if isinstance(props, dict):
            raw = props.get("algorithm")
            if isinstance(raw, str) and raw.strip():
                brief_algo = raw.strip()
    panel_algo: str | None = None
    if isinstance(panel_problem, dict):
        raw_panel = panel_problem.get("algorithm")
        if isinstance(raw_panel, str) and raw_panel.strip():
            panel_algo = raw_panel.strip()
    if brief_algo and panel_algo and brief_algo != panel_algo:
        drift.append(
            _drift_entry(
                kind="algorithm_mismatch",
                key="search_strategy",
                brief_value=brief_algo,
                panel_value=panel_algo,
                detail="algorithm",
            )
        )
    elif brief_algo and not panel_algo:
        drift.append(
            _drift_entry(
                kind="algorithm_mismatch",
                key="search_strategy",
                brief_value=brief_algo,
                panel_value=None,
                detail="algorithm",
            )
        )
    # Note: panel_algo without brief_algo is NOT flagged — the panel's default
    # algorithm (e.g. GA) is a valid starting state before any brief mention.

    # Mirror-field drift: properties the active port mirrors to top-level
    # panel fields. The two stores must agree row-for-row.
    if test_problem_id is not None and isinstance(panel_problem, dict):
        try:
            from app.problems.registry import get_study_port

            port = get_study_port(test_problem_id)
            mirrors = port.goal_term_property_field_mirrors()
        except Exception:  # pragma: no cover — defensive
            mirrors = {}
        for goal_key, top_field in (mirrors or {}).items():
            brief_entry = brief_goal_terms.get(goal_key)
            if not isinstance(brief_entry, dict):
                continue
            brief_props = brief_entry.get("properties") if isinstance(brief_entry.get("properties"), dict) else {}
            brief_mirror_val = brief_props.get(top_field)
            panel_mirror_val = panel_problem.get(top_field)
            if brief_mirror_val == panel_mirror_val:
                continue
            if brief_mirror_val is None and panel_mirror_val in (None, [], {}, ""):
                continue
            if panel_mirror_val is None and brief_mirror_val in (None, [], {}, ""):
                continue
            drift.append(
                _drift_entry(
                    kind="mirror_mismatch",
                    key=goal_key,
                    brief_value=brief_mirror_val,
                    panel_value=panel_mirror_val,
                    detail=top_field,
                )
            )

    return drift


def _run_with_timeout(callable_obj, timeout_sec: float):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(callable_obj)
    try:
        return future.result(timeout=timeout_sec)
    finally:
        # Don't block on shutdown — if the LLM thread is still running after a
        # timeout, wait=True would hold the request handler open indefinitely.
        executor.shutdown(wait=False)


def _mirror_canonical_scalars_from_brief(
    next_problem: dict[str, Any],
    problem_brief: dict[str, Any] | None,
) -> None:
    """Deterministic brief → panel mirror for the canonical scalar fields.

    The brief is authoritative for ``goal_terms[K].{weight, type, rank}`` on
    chat-origin flows — those values are set by the chat LLM in the brief
    patch (which goes through S2 verification and is committed) before the
    panel-derive LLM ever runs. The panel-derive LLM is supposed to translate
    the brief into panel shape, not redecide those scalars; but its
    structured-output schema lets it emit any value in the enum, and it
    occasionally produces a value that disagrees with the brief (P_l7 msg
    1688 / 1690 — ``travel_time.type='objective'`` in brief but ``'soft'``
    in the derived panel). The S5 retry path re-runs the same LLM with
    feedback; the LLM can drift the same way twice and pause the pipeline.

    This helper closes that loop by overwriting the LLM's scalar emission
    with the brief's values immediately after derivation and before
    validation. Symmetric with the algorithm carrier mirror at
    ``sync_panel_from_problem_brief`` (which mirrors
    ``goal_terms.search_strategy.properties.{algorithm,epochs,pop_size}``
    deterministically from brief to panel) — same pattern, broader scope.

    Leaves alone:
    - ``properties``: legitimate per-rule structured translation owned by
      the LLM (e.g. VRPTW's ``driver_preferences`` list). Real drift here
      surfaces via ``port_companion`` mirror-mismatch checks.
    - ``locked``: researcher/panel-managed; owned by
      ``_canonicalize_locked_goal_terms``.
    - ``search_strategy``: carrier-only, already mirrored separately.
    - Any field the brief doesn't carry — the LLM/seed value wins when
      the brief has no opinion.

    The ``weights`` top-level field, when present, is kept in sync with
    ``goal_terms[K].weight`` so the drift check sees a coherent panel.
    """
    if not isinstance(problem_brief, dict):
        return
    brief_goal_terms = problem_brief.get("goal_terms")
    if not isinstance(brief_goal_terms, dict) or not brief_goal_terms:
        return
    panel_goal_terms = next_problem.get("goal_terms")
    if not isinstance(panel_goal_terms, dict) or not panel_goal_terms:
        return
    overrides: list[tuple[str, str, Any]] = []
    for key, brief_entry in brief_goal_terms.items():
        if not isinstance(key, str) or key in CARRIER_ONLY_GOAL_TERM_KEYS:
            continue
        if not isinstance(brief_entry, dict):
            continue
        panel_entry = panel_goal_terms.get(key)
        if not isinstance(panel_entry, dict):
            continue
        for field in ("weight", "type", "rank"):
            if field not in brief_entry:
                continue
            brief_val = brief_entry.get(field)
            if brief_val is None:
                continue
            if field == "weight":
                if not isinstance(brief_val, (int, float)) or isinstance(brief_val, bool):
                    continue
                brief_val = float(brief_val)
            elif field == "rank":
                if not isinstance(brief_val, int) or isinstance(brief_val, bool):
                    continue
            elif field == "type":
                if not isinstance(brief_val, str) or not brief_val.strip():
                    continue
                brief_val = brief_val.strip()
            if panel_entry.get(field) == brief_val:
                continue
            overrides.append((key, field, brief_val))
            panel_entry[field] = brief_val
    # Keep the top-level `weights` dict (if used by the port) in sync with
    # the mirrored goal_terms weights, so downstream consumers — including
    # the drift check — see a coherent panel.
    if overrides:
        weights = next_problem.get("weights")
        if isinstance(weights, dict) and weights:
            for key, field, value in overrides:
                if field == "weight" and key in weights:
                    weights[key] = float(value)
        # Keep the top-level `constraint_types` map in sync with the mirrored
        # types. The LLM panel-derive emits the legacy `weights` +
        # `constraint_types` form, and `sanitize_panel_config` (which runs
        # AFTER this mirror) re-derives `goal_terms[K].type` FROM
        # `constraint_types`. Its enum is {soft, hard, custom} — it cannot
        # express `objective` — so the objective term lands as a stale
        # `constraint_types[K]='soft'`. Without syncing it here, the mirror's
        # `goal_terms` correction to `objective` is silently undone by the
        # post-mirror sanitize, re-opening `travel_time.type` drift on every
        # turn that the retry can never clear (P_0602). Per the panel
        # convention (`CONSTRAINT_TYPES_SCHEMA`: "objective is the implicit
        # default when a key is omitted"), an objective term is REMOVED from
        # the map; any other type is written through.
        ctypes = next_problem.get("constraint_types")
        if isinstance(ctypes, dict):
            for key, field, value in overrides:
                if field != "type":
                    continue
                if value == "objective":
                    ctypes.pop(key, None)
                else:
                    ctypes[key] = value
        log.info(
            "Brief→panel scalar mirror overrode %d goal_term field(s): %s",
            len(overrides),
            [{"key": k, "field": f, "value": v} for k, f, v in overrides],
        )


def _mirror_locked_from_brief(
    next_problem: dict[str, Any],
    problem_brief: dict[str, Any] | None,
) -> None:
    """Mirror the participant's lock from the brief into the panel.

    Lock is one state per concept shown in two surfaces: the Definition-tab
    lock toggle writes ``brief.goal_terms[key].locked``; the Problem Config
    lock button writes ``panel.problem.locked_goal_terms``. The reverse
    direction (panel → brief) already carries ``locked`` via
    ``merge_brief_from_panel``; this is the forward direction so a lock set on
    the Definition tab reaches the panel list (and an explicit unlock removes
    it). Only keys the panel actually carries are touched, so the list never
    references a non-existent term. Keys the brief doesn't mention are left
    alone — the panel's existing lock (e.g. a researcher/Config lock) wins
    when the brief has no opinion.
    """
    if not isinstance(problem_brief, dict):
        return
    brief_goal_terms = problem_brief.get("goal_terms")
    if not isinstance(brief_goal_terms, dict) or not brief_goal_terms:
        return
    panel_goal_terms = next_problem.get("goal_terms")
    panel_keys = set(panel_goal_terms.keys()) if isinstance(panel_goal_terms, dict) else set()

    current = next_problem.get("locked_goal_terms")
    locked: list[str] = [k for k in current if isinstance(k, str)] if isinstance(current, list) else []
    locked_set = set(locked)
    for key, entry in brief_goal_terms.items():
        if not isinstance(key, str) or key not in panel_keys or not isinstance(entry, dict):
            continue
        flag = entry.get("locked")
        if flag is True and key not in locked_set:
            locked.append(key)
            locked_set.add(key)
        elif flag is False and key in locked_set:
            locked = [k for k in locked if k != key]
            locked_set.discard(key)
    if locked:
        next_problem["locked_goal_terms"] = locked
    else:
        next_problem.pop("locked_goal_terms", None)


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


def _merge_non_destructive_managed_fields(
    current_problem: dict,
    derived_problem: dict,
    *,
    problem_brief: dict | None = None,
    workflow_mode: str | None = None,
    api_key: str | None = None,
    test_problem_id: str | None = None,
    embedding_model: str | None = None,
) -> dict:
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
        # goal_terms.properties still recovers the mirrored field. The pairing is
        # problem-specific (e.g. VRPTW mirrors `worker_preference.properties.driver_preferences`
        # ↔ panel `driver_preferences`), supplied by the active port.
        property_field_mirrors: dict[str, str] = {}
        if test_problem_id is not None:
            try:
                from app.problems.registry import get_study_port

                property_field_mirrors = (
                    get_study_port(test_problem_id).goal_term_property_field_mirrors()
                )
            except Exception:  # pragma: no cover — defensive
                property_field_mirrors = {}
        for goal_key, top_field in property_field_mirrors.items():
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
        # Anchor check: drop newly-derived goal_term keys (those NOT present in
        # `current_goal_terms`) that have no evidence in the brief items[].
        # Existing keys are preserved unconditionally so retunes don't regress.
        if problem_brief is not None:
            from app.services.goal_term_anchoring import filter_unanchored_new_goal_terms

            base_for_filter = {"goal_terms": current_goal_terms}
            # Same premature-commit drop as in apply_brief_patch_with_cleanup —
            # when the LLM derives a goal_term commit that's still answered
            # by an open OQ in the brief, defer it to the OQ.
            pending_oq_keys: set[str] = set()
            for q in (problem_brief or {}).get("open_questions") or []:
                if not isinstance(q, dict):
                    continue
                if str(q.get("status") or "open").strip().lower() != "open":
                    continue
                gk = q.get("goal_key")
                if isinstance(gk, str) and gk.strip():
                    pending_oq_keys.add(gk.strip())
            filtered, dropped = filter_unanchored_new_goal_terms(
                base_brief=base_for_filter,
                proposed_goal_terms=merged_goal_terms,
                items=list((problem_brief or {}).get("items") or []),
                workflow_mode=workflow_mode,
                api_key=api_key,
                test_problem_id=test_problem_id,
                embedding_model=embedding_model,
                pending_oq_keys=pending_oq_keys,
            )
            if dropped:
                log.warning(
                    "Panel-derive dropped unanchored goal_terms keys: %s",
                    dropped,
                )
                merged_goal_terms = filtered
        merged["goal_terms"] = merged_goal_terms

    # Brief-as-source-of-truth (strict subset + fill-missing). The panel-
    # derive LLM can translate ``brief.goal_terms`` into a panel, but it
    # cannot *propose* new goal-term keys — neither from prose in
    # ``brief.items[]`` nor from a ``current_panel.goal_terms`` carry-over.
    # The brief-update model owns that proposal; once brief.goal_terms drops
    # a key, it must drop from the panel too.
    #
    # **Two-way enforcement:** the brief is authoritative in BOTH directions
    # — panel keys not in brief get dropped (strict subset), AND brief keys
    # the LLM derivation omitted get filled in deterministically. The fill
    # path matters because the LLM occasionally drops a brief.goal_terms key
    # under prompt bloat (observed with ``workload_balance``: brief has the
    # key with a valid ``evidence_item_ids`` cite, but the derived panel
    # comes back missing it, leaving a permanent "Brief ↔ Problem Config
    # drift" banner that no "Sync to config" click can clear).
    if problem_brief is not None:
        merged_goal_terms_final = _goal_terms_from_problem(merged)
        brief_goal_terms_raw = (
            (problem_brief or {}).get("goal_terms")
            if isinstance((problem_brief or {}).get("goal_terms"), dict)
            else {}
        )
        allowed_keys = {
            k
            for k in (brief_goal_terms_raw.keys() if isinstance(brief_goal_terms_raw, dict) else [])
            if isinstance(k, str)
        }
        unauthorized = [k for k in list(merged_goal_terms_final.keys()) if k not in allowed_keys]
        if unauthorized:
            log.warning(
                "Panel-derive dropped goal_terms not in brief: %s",
                unauthorized,
            )
            for k in unauthorized:
                merged_goal_terms_final.pop(k, None)
            # Keep the legacy `weights` map in lockstep so the downstream
            # `_rebuild_goal_terms_metadata` (study_bridge) can't resurrect the
            # dropped keys from a stale weights projection.
            if isinstance(merged.get("weights"), dict):
                for k in unauthorized:
                    merged["weights"].pop(k, None)
        # Fill brief keys the LLM derivation forgot. We trust the brief: the
        # entry already passed the brief-side anchor check during the chat
        # turn that introduced the key, and the panel anchor filter above
        # would have dropped it from ``merged_goal_terms`` had it failed
        # there. Strip ``evidence_item_ids`` since that's brief-side
        # bookkeeping; the panel sanitizer doesn't expect it.
        missing_from_panel = [
            k for k in allowed_keys if k not in merged_goal_terms_final
        ]
        if missing_from_panel and isinstance(brief_goal_terms_raw, dict):
            for key in missing_from_panel:
                src_entry = brief_goal_terms_raw.get(key)
                if not isinstance(src_entry, dict):
                    continue
                copied = deepcopy(src_entry)
                copied.pop("evidence_item_ids", None)
                merged_goal_terms_final[key] = copied
                # Mirror into the legacy weights map when the entry has a
                # numeric weight, so ``_rebuild_goal_terms_metadata`` and
                # other weights-projection consumers see it.
                weight_val = copied.get("weight")
                if isinstance(weight_val, (int, float)) and not isinstance(weight_val, bool):
                    weights_map = merged.get("weights")
                    if not isinstance(weights_map, dict):
                        weights_map = {}
                        merged["weights"] = weights_map
                    weights_map[key] = float(weight_val)
            log.info(
                "Panel-derive filled brief.goal_terms keys the LLM omitted: %s",
                missing_from_panel,
            )

        # Brief-as-source-of-truth, third case: keys present in BOTH brief
        # and panel must use the BRIEF's weight/type/properties. The LLM
        # derivation sometimes returns the *current* panel value (or omits
        # the field entirely, falling back to current via the merge above)
        # — so a brief-side bump like ``workload_balance.weight = 2.0``
        # never reaches the panel and S5 verify flags brief↔panel drift
        # in a loop that Retry can't break. The brief is the source of
        # truth for committed weights; force-overwrite.
        weight_overwrites: list[str] = []
        if isinstance(brief_goal_terms_raw, dict):
            for key, brief_entry in brief_goal_terms_raw.items():
                if key not in merged_goal_terms_final:
                    continue
                if not isinstance(brief_entry, dict):
                    continue
                panel_entry = merged_goal_terms_final[key]
                if not isinstance(panel_entry, dict):
                    continue
                for field in ("weight", "type", "rank", "locked", "properties"):
                    if field not in brief_entry:
                        continue
                    brief_val = brief_entry[field]
                    if panel_entry.get(field) != brief_val:
                        panel_entry[field] = deepcopy(brief_val) if isinstance(brief_val, (dict, list)) else brief_val
                        if field == "weight":
                            weight_overwrites.append(key)
                            # Keep legacy weights map in lockstep.
                            if isinstance(brief_val, (int, float)) and not isinstance(brief_val, bool):
                                weights_map = merged.get("weights")
                                if not isinstance(weights_map, dict):
                                    weights_map = {}
                                    merged["weights"] = weights_map
                                weights_map[key] = float(brief_val)
        if weight_overwrites:
            log.info(
                "Panel-derive overwrote panel weights with brief values for: %s",
                weight_overwrites,
            )
        if unauthorized or missing_from_panel or weight_overwrites:
            merged["goal_terms"] = merged_goal_terms_final

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
    # Search-strategy grounding: the LLM is told to derive algorithm /
    # epochs / pop_size / params only when the brief names an algorithm, but
    # it sometimes switches GA→PSO mid-conversation off a casual mention.
    # Enforce server-side: if no brief item names an algorithm (canonical or
    # alias), treat the LLM's search-strategy choice as unsolicited and keep
    # the current panel's values. Existing terms are unaffected.
    if problem_brief is not None:
        from app.services.goal_term_anchoring import algorithm_mentioned_in_brief

        items_for_check = list((problem_brief or {}).get("items") or [])
        if not algorithm_mentioned_in_brief(items_for_check, workflow_mode=workflow_mode):
            search_strategy_keys = ("algorithm", "epochs", "pop_size", "algorithm_params")
            switched: list[str] = []
            for key in search_strategy_keys:
                derived_val = merged.get(key)
                current_val = current_problem.get(key)
                if derived_val is None:
                    continue
                if current_val is not None and derived_val != current_val:
                    switched.append(key)
                    merged[key] = deepcopy(current_val)
                elif current_val is None and key != "algorithm":
                    # No prior value for budget/params is fine — fresh derive.
                    pass
            if switched:
                log.info(
                    "Panel-derive preserved current search strategy (no algorithm mention in brief): %s",
                    switched,
                )
    return merged


_NEUTRAL_MANAGED_PROBLEM_FIELDS: tuple[str, ...] = (
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


def _managed_problem_fields(port: Any | None = None) -> tuple[str, ...]:
    """Managed keys are re-derived from brief each turn unless preserve mode is requested.

    Combines the neutral solver-shaped fields with any port-supplied extras
    (e.g. VRPTW's ``driver_preferences``, ``max_shift_hours``,
    ``locked_assignments``). Order is preserved and duplicates are dropped.
    """
    if port is None:
        return _NEUTRAL_MANAGED_PROBLEM_FIELDS
    try:
        extras = tuple(port.extra_managed_problem_fields())
    except Exception:  # pragma: no cover — defensive
        extras = ()
    seen: set[str] = set()
    out: list[str] = []
    for key in _NEUTRAL_MANAGED_PROBLEM_FIELDS + extras:
        if not isinstance(key, str) or key in seen:
            continue
        out.append(key)
        seen.add(key)
    return tuple(out)


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
    commit: bool = True,
) -> tuple[dict | None, list[str]]:
    """Sync the panel from the brief.

    Returns ``(panel, weight_warnings)`` where ``panel`` is ``None`` when the
    brief is too sparse and the LLM is unavailable to derive one.

    Raises ``GoalTermValidationError`` only for **structural** validator errors
    (shape / type / order).  Brief-grounding mismatches were ripped out — the
    LLM's structured-output schema already restricts the key vocabulary, so the
    old marker-based hallucination check produced more friction than value.

    When ``commit=False`` the function stages ``row.panel_config_json`` but
    leaves the commit to the caller, so brief + panel updates can be made
    transactional in the participant brief PATCH handler.
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
    for key in _managed_problem_fields(port):
        next_problem.pop(key, None)
    companion_fields = port.locked_companion_fields()

    derived_problem = deepcopy(derived_panel["problem"])
    derived_problem = _canonicalize_locked_goal_terms(current_problem, derived_problem, companion_fields)
    if preserve_missing_managed_fields:
        derived_problem = _merge_non_destructive_managed_fields(
            current_problem,
            derived_problem,
            problem_brief=problem_brief,
            workflow_mode=workflow_mode or row.workflow_mode,
            api_key=api_key,
            test_problem_id=test_problem_id,
            embedding_model=helpers.embedding_model_for(row),
        )
    next_problem.update(derived_problem)
    if seed_panel is None:
        seed_panel = port.derive_problem_panel_from_brief(problem_brief)
    next_problem = _backfill_solver_fields_from_seed(seed_panel, next_problem)

    # Workflow-legitimacy gate: search-strategy panel fields must be backed by
    # a corresponding brief row (gathered/assumption naming an algorithm, or a
    # search-strategy slot mirrored from a prior panel). Without this, problem
    # ports that hard-default an algorithm in their brief→panel seed (e.g.
    # VRPTW's ``"GA" if any goal-term signal``) would expose a search-strategy
    # block before the agent has discussed it with the participant — which
    # both breaks waterfall's "ask before configure" rule and misleads agile.
    # The check is problem-agnostic; problem-specific knowledge stays in the
    # ports' slot detection and the closed algorithm-name vocabulary.
    from app.services.goal_term_anchoring import (
        SEARCH_STRATEGY_PANEL_FIELDS,
        brief_mentions_search_strategy,
    )

    if not brief_mentions_search_strategy(
        problem_brief,
        test_problem_id=test_problem_id,
        workflow_mode=workflow_mode or row.workflow_mode,
    ):
        for key in SEARCH_STRATEGY_PANEL_FIELDS:
            next_problem.pop(key, None)
    else:
        # Carrier→panel deterministic mirror. The LLM-driven panel derivation
        # (governed by STUDY_CHAT_SEARCH_STRATEGY_ANCHORING) treats `brief.items[]`
        # as the only evidence for emitting search-strategy fields. In tutorial
        # mode the chat LLM may commit the algorithm via the structured carrier
        # (``goal_terms.search_strategy.properties.algorithm``) and skip the
        # items[] row, so LLM-derive omits panel.algorithm and S5 catches the
        # drift in a retry loop. The carrier is canonical — if it carries a
        # value and the panel slot is empty, mirror it deterministically.
        ss_carrier = (
            problem_brief.get("goal_terms", {}).get("search_strategy", {}).get("properties", {})
            if isinstance(problem_brief, dict)
            else {}
        )
        if isinstance(ss_carrier, dict):
            for carrier_key in ("algorithm", "epochs", "pop_size"):
                carrier_val = ss_carrier.get(carrier_key)
                if carrier_key == "algorithm":
                    # The carrier is canonical for the algorithm choice — it
                    # WINS over a default/stale panel value (the seed's GA
                    # default, or an LLM-derive that ignored the carrier), not
                    # just fills an empty slot. A chat answer commits the
                    # carrier (e.g. ACOR); without overriding, the panel keeps
                    # its default GA and S5 reports a permanent ACOR↔GA drift
                    # the participant can't clear. Safe against clobbering a
                    # user's panel edit: a panel save runs the reverse mirror
                    # (panel→brief) first, so the carrier already matches.
                    if isinstance(carrier_val, str) and carrier_val.strip():
                        next_problem[carrier_key] = carrier_val.strip()
                else:
                    # epochs / pop_size: same authoritative rule as algorithm —
                    # when the carrier carries a real positive number it WINS
                    # over a default/stale panel value, not just fills an empty
                    # slot. (A falsy 0 is treated as "unset" and left alone.)
                    if (
                        isinstance(carrier_val, (int, float))
                        and not isinstance(carrier_val, bool)
                        and carrier_val
                    ):
                        next_problem[carrier_key] = carrier_val

    # Brief → panel deterministic mirror for `goal_terms[K].{weight, type,
    # rank}`. The brief is authoritative for those scalars on chat-origin
    # flows; the LLM panel-derive occasionally emits values that disagree
    # with the brief (P_l7 msg 1688 / 1690 — travel_time.type='objective'
    # in brief vs 'soft' in derived panel), which paused the pipeline at
    # S5 because the S5 chat-origin retry path re-runs the same LLM with
    # the same input and can drift the same way twice. The mirror runs
    # after the LLM derive and locked/managed-field merges and before the
    # validator, so the persisted panel always agrees with the brief on
    # the canonical scalars. See ``_mirror_canonical_scalars_from_brief``.
    _mirror_canonical_scalars_from_brief(next_problem, problem_brief)
    # Forward-mirror the participant's lock (Definition-tab toggle writes
    # brief.goal_terms[key].locked) into the panel's locked_goal_terms so the
    # Config lock control reflects the same single per-concept lock state.
    _mirror_locked_from_brief(next_problem, problem_brief)

    # Drop stale `goal_term_order` entries whose keys were filtered out of
    # `goal_terms` above (unauthorized/unanchored sweeps) or that were carried
    # over from `current_problem` without being re-derived. Without this, the
    # validator below wedges the session in an unrecoverable "Retry sync" loop
    # — the participant has no UI surface to edit the order list.
    order_raw = next_problem.get("goal_term_order")
    if isinstance(order_raw, list):
        present_keys = (
            set(next_problem["goal_terms"].keys())
            if isinstance(next_problem.get("goal_terms"), dict)
            else set()
        )
        cleaned_order = [k for k in order_raw if isinstance(k, str) and k in present_keys]
        if cleaned_order != order_raw:
            next_problem["goal_term_order"] = cleaned_order

    # Structural errors only — raises GoalTermValidationError on shape / type / order bugs.
    validate_problem_goal_terms(problem=next_problem)

    next_panel["problem"] = next_problem
    merged, weight_warnings = port.sanitize_panel_config(next_panel)
    if merged == current_panel:
        return merged, weight_warnings

    log.info("Participant synced panel_config from brief: %s", merged)
    row.panel_config_json = json.dumps(merged)
    row.updated_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
        db.refresh(row)
    return merged, weight_warnings


def realign_panel_scalars_from_brief(
    row: StudySession, db: Session, problem_brief: dict, *, commit: bool = True
) -> dict:
    """Deterministically force the panel's canonical goal-term scalars
    (``weight`` / ``type`` / ``rank``) to match the brief, then persist.
    Idempotent.

    The brief is authoritative for those scalars on chat / brief-origin turns.
    The LLM panel-derive can disagree (and re-disagree the *same* way on a
    retry), and a panel that drifted on an earlier turn stays stuck if a later
    turn skips the derive — so the verifier keeps reporting the mismatch
    (e.g. ``travel_time.type`` objective↔soft) and "Retry" never clears it.
    Running this deterministic mirror right before S5 verification guarantees
    the canonical scalars always agree, so that class of drift can't pause the
    pipeline regardless of what the LLM emitted or whether the derive ran.
    """
    panel = helpers.panel_dict(row)
    if not isinstance(panel, dict):
        return panel
    problem = panel.get("problem")
    if not isinstance(problem, dict):
        return panel
    from app.problems.registry import get_study_port

    _mirror_canonical_scalars_from_brief(problem, problem_brief)
    tpid = getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID
    merged, _warnings = get_study_port(tpid).sanitize_panel_config(panel)
    if merged == helpers.panel_dict(row):
        return merged  # already aligned — no write
    row.panel_config_json = json.dumps(merged)
    row.updated_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
        db.refresh(row)
    return merged


def gapfill_brief_companions_from_panel(
    row: StudySession, db: Session, problem_brief: dict, *, commit: bool = True
) -> dict:
    """Populate the brief's companion mirror fields from the derived panel when
    the brief never recorded them.

    The agent sometimes commits a companion-bearing goal term HOLLOW — e.g.
    ``shift_limit`` with no ``properties.max_shift_hours`` (it parks the value in
    ``ambiguity_note`` narration). The panel-derive step still extracts the value
    into the panel (``max_shift_hours = 8``). The result is a ``mirror_mismatch``
    the LLM retry can never clear (brief ``None`` vs panel ``8``) — and the def
    row never shows the cap. This copies the panel value back into the brief's
    ``goal_terms[K].properties[field]``, re-synthesizes the canonical def rows so
    the companion summary (cap / rules) surfaces, and persists.

    Only fills a field the brief never recorded (absent key) — an explicitly
    EMPTY value (e.g. the user cleared ``driver_preferences``) is respected and
    NOT resurrected from a stale panel. Returns the (possibly updated) brief.
    """
    if not isinstance(problem_brief, dict):
        return problem_brief
    panel = helpers.panel_dict(row)
    problem = panel.get("problem") if isinstance(panel, dict) else None
    if not isinstance(problem, dict):
        return problem_brief
    tpid = getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID
    try:
        from app.problems.registry import get_study_port

        mirrors = get_study_port(tpid).goal_term_property_field_mirrors() or {}
    except Exception:  # pragma: no cover — defensive
        return problem_brief
    brief_gt = problem_brief.get("goal_terms")
    if not isinstance(brief_gt, dict) or not mirrors:
        return problem_brief
    _EMPTY = (None, [], {}, "")
    changed = False
    for key, field in mirrors.items():
        entry = brief_gt.get(key)
        if not isinstance(entry, dict):
            continue
        props = entry.get("properties") if isinstance(entry.get("properties"), dict) else None
        # Only gap-fill a field the brief NEVER recorded (truly hollow), so an
        # explicitly-cleared value isn't resurrected from the panel.
        if props is not None and field in props:
            continue
        panel_val = problem.get(field)
        if panel_val in _EMPTY:
            continue
        if not isinstance(props, dict):
            props = {}
            entry["properties"] = props
        props[field] = panel_val
        changed = True
    if not changed:
        return problem_brief
    from app.routers.sessions.derivation import _synthesize_canonical_weight_items

    updated = _synthesize_canonical_weight_items(problem_brief, tpid)
    row.problem_brief_json = json.dumps(updated)
    row.updated_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
        db.refresh(row)
    return updated


def sync_problem_brief_from_panel(
    row: StudySession,
    db: Session,
    panel_config: dict,
    *,
    origin: str = "user",
) -> dict:
    """Mirror a saved panel back into the brief.

    Default ``origin`` is ``"user"`` because this router-level wrapper is
    only called from the PATCH /panel handler — the path participants take
    when they click Save in the Config tab. LLM-driven re-derivations go
    through ``sync_panel_from_problem_brief`` (the opposite direction).
    """
    current_problem_brief = helpers.problem_brief_dict(row)
    tpid = getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID
    next_problem_brief = merge_brief_from_panel(
        current_problem_brief, panel_config, test_problem_id=tpid, origin=origin
    )
    next_problem_brief = coerce_problem_brief_for_workflow(next_problem_brief, row.workflow_mode)
    if next_problem_brief == current_problem_brief:
        return current_problem_brief
    row.problem_brief_json = json.dumps(next_problem_brief)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return next_problem_brief
