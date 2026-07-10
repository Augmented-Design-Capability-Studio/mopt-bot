"""MOPT study port for the VRPTW fleet benchmark (see ``mopt_manifest.toml``)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.problems.types import TestProblemMeta, WeightDefinition

from vrptw_problem import study_bridge
from vrptw_problem.panel_schema import panel_patch_response_json_schema
from vrptw_problem.study_meta import (
    VRPTW_WEIGHT_DEFINITIONS,
    weight_item_labels as meta_weight_item_labels,
    weight_display_keys as meta_weight_display_keys,
    worker_preference_key as meta_worker_preference_key,
)





class VrptwStudyPort:
    id = "vrptw"
    label = "Fleet scheduling (VRPTW)"

    def meta(self) -> TestProblemMeta:
        return TestProblemMeta(
            id=self.id,
            label=self.label,
            weight_definitions=[
                WeightDefinition(key, label, desc, direction=direction)
                for key, label, desc, direction in VRPTW_WEIGHT_DEFINITIONS
            ],
            extension_ui="vrptw_extras",
            visualization_presets=["fleet_gantt"],
            primary_visualization="fleet_gantt",
            weight_display_keys=meta_weight_display_keys(),
            worker_preference_key=meta_worker_preference_key(),
            gate_conditional_companions=self.gate_conditional_companions(),
        )

    def sanitize_panel_config(self, panel_config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        return study_bridge.sanitize_panel_weights(panel_config)

    def parse_problem_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        return study_bridge.parse_problem_config(raw)

    def solve_request_to_result(
        self,
        body: dict[str, Any],
        timeout_sec: float,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        return study_bridge.solve_request_to_result(body, timeout_sec, cancel_event=cancel_event)

    def derive_problem_panel_from_brief(self, problem_brief: dict[str, Any]) -> dict[str, Any] | None:
        from vrptw_problem.brief_seed import derive_problem_panel_from_brief as _derive

        return _derive(problem_brief)

    def weight_item_labels(self) -> dict[str, str]:
        return meta_weight_item_labels()

    def goal_term_rationales(self) -> dict[str, str]:
        # One-clause rationales the synthesizer tacks onto each
        # ``config-weight-<key>`` row so participants see WHY a term is
        # active, not just its name + type + weight.
        return {
            "travel_time": "to minimize total driving minutes across all routes",
            "shift_limit": "to discourage shifts that exceed the configured max-hours cap",
            "lateness_penalty": "to keep deliveries within their time windows",
            "capacity_penalty": "to discourage overloading vehicles past their capacity",
            "workload_balance": "to distribute drive + service time fairly across drivers",
            "worker_preference": "to honour per-driver preference rules",
            "express_miss_penalty": "to prioritise express / VIP / SLA orders on time",
            "waiting_time": "to reduce driver idle time before time windows open",
        }

    def weight_display_keys(self) -> list[str]:
        return meta_weight_display_keys()

    def gate_conditional_companions(self) -> dict[str, str]:
        return {
            meta_worker_preference_key(): "driver_preferences",
            "shift_limit": "max_shift_hours",
        }

    def companion_present(self, goal_term_key: str, value: Any) -> bool:
        # max_shift_hours must be a positive number — zero is not a meaningful cap.
        if goal_term_key == "shift_limit":
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value > 0
            )
        # driver_preferences and any future list companion: present iff non-empty.
        if isinstance(value, list):
            return len(value) > 0
        return bool(value)

    def companion_open_question_text(self, goal_term_key: str) -> str | None:
        # Asked when the agent recognises one of these terms but doesn't yet
        # have the specifics. Plain, participant-facing wording (no raw keys).
        if goal_term_key == meta_worker_preference_key():
            return (
                "Which drivers have preferences, and what should each one avoid "
                "or stick to (for example, a specific zone)?"
            )
        if goal_term_key == "shift_limit":
            return "What is the longest shift a driver should work, in hours?"
        return None

    def companion_extraction_instructions(self, goal_term_key: str) -> str | None:
        # Only the worker_preference rule LIST benefits from free-text extraction;
        # the scalar shift cap is trivially carried by the panel/agent already.
        if goal_term_key == meta_worker_preference_key():
            from vrptw_problem.study_prompts import DRIVER_PREFERENCES_BRIEF_CONTRACT

            return DRIVER_PREFERENCES_BRIEF_CONTRACT
        return None

    def visualization_capabilities(self) -> list[str]:
        return [
            "Convergence trend across iterations",
            "Run metric cards (cost, travel, workload spread)",
            "Constraint-violation summary cards",
            "Fleet schedule timeline and route details",
        ]

    def study_prompt_appendix(self) -> str | None:
        from vrptw_problem.study_prompts import VRPTW_STUDY_PROMPT_APPENDIX

        return VRPTW_STUDY_PROMPT_APPENDIX

    def config_derive_system_prompt(self) -> str:
        from vrptw_problem.study_prompts import VRPTW_CONFIG_DERIVE_SYSTEM_PROMPT

        return VRPTW_CONFIG_DERIVE_SYSTEM_PROMPT.strip()

    def panel_patch_response_json_schema(self) -> dict:
        return panel_patch_response_json_schema()

    def locked_companion_fields(self) -> dict[str, str]:
        return {"worker_preference": "driver_preferences"}

    def prose_id_prefixes_for_goal_term(self, goal_term_key: str) -> tuple[str, ...]:
        # Driver-preference prose rows live under `config-driver-pref-*`.
        # When a structured `goal_terms.worker_preference` patch arrives,
        # incoming items with this prefix should be deduped against the
        # synthesized rows to prevent stale duplicates surviving a refresh.
        if goal_term_key == "worker_preference":
            return ("config-driver-pref-",)
        return ()

    def goal_term_properties_schema(self) -> dict | None:
        from .panel_schema import VRPTW_GOAL_TERM_PROPERTIES_SCHEMA
        return VRPTW_GOAL_TERM_PROPERTIES_SCHEMA

    def goal_term_property_field_mirrors(self) -> dict[str, str]:
        return {
            "worker_preference": "driver_preferences",
            "shift_limit": "max_shift_hours",
        }

    def extra_managed_problem_fields(self) -> tuple[str, ...]:
        return ("max_shift_hours", "driver_preferences", "locked_assignments")

    def normalize_goal_term_property(
        self, prop_key: str, prop_val: Any
    ) -> tuple[bool, Any] | None:
        from vrptw_problem.goal_term_properties import normalize_goal_term_property

        return normalize_goal_term_property(prop_key, prop_val)

    def problem_brief_item_slot(self, item: dict[str, Any]) -> str | None:
        item_id = str(item.get("id") or "")
        if not item_id:
            return None
        if item_id == "config-shift-hard-penalty":
            return "weight:shift_limit"
        if item_id.startswith("config-weight-"):
            weight_key = item_id.removeprefix("config-weight-")
            # Backward-compat renames for legacy stored ids; canonical
            # `_brief_items_from_panel` now writes the renamed forms directly.
            if weight_key == "deadline_penalty":
                return "weight:lateness_penalty"
            if weight_key == "priority_penalty":
                return "weight:express_miss_penalty"
            return None  # generic config-weight-* handled by neutral slot
        if item_id.startswith("config-driver-pref-"):
            # Each rule has a stable suffix (e.g. `0-zone-D`); slot id mirrors
            # it so duplicate rules collapse via the slot reconciler while
            # distinct rules (different vehicle/condition/discriminator) coexist.
            return f"driver_pref:{item_id.removeprefix('config-driver-pref-')}"
        return None

    def format_run_context_violation_details(
        self, violations: dict[str, Any]
    ) -> list[str]:
        out: list[str] = []
        tw = violations.get("time_window_stop_count")
        cap = violations.get("capacity_units_over")
        if isinstance(tw, (int, float)) and not isinstance(tw, bool):
            out.append(f"time-window stops over {int(tw)}")
        if isinstance(cap, (int, float)) and not isinstance(cap, bool):
            out.append(f"capacity units over {int(cap)}")
        return out

    def brief_item_ids_to_strip_on_goal_term_removal(
        self,
        removed_keys: set[str],
        prior_goal_terms: dict[str, Any],
        brief_items: list[dict[str, Any]],
    ) -> set[str]:
        """VRPTW cascade: also strip auto-synthesized prose rows tied to a
        removed term. Otherwise removing ``worker_preference`` would leave the
        ``config-driver-pref-*`` rows that ``synthesize_brief_items_from_goal_terms``
        generated, and the next derive pass would re-introduce the rule set."""
        ids: set[str] = set()
        # Evidence-cite items (the LLM-explicit dependency) — neutral default.
        for key in removed_keys:
            entry = prior_goal_terms.get(key) if isinstance(prior_goal_terms, dict) else None
            if not isinstance(entry, dict):
                continue
            evidence = entry.get("evidence_item_ids")
            if isinstance(evidence, list):
                for eid in evidence:
                    if isinstance(eid, str) and eid:
                        ids.add(eid)
        # Auto-rows: scan all items once and match against per-key prefixes /
        # known stable ids. Keep matching conditions in sync with
        # ``problem_brief_item_slot`` and ``synthesize_brief_items_from_goal_terms``.
        if not isinstance(brief_items, list):
            return ids
        for item in brief_items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "")
            if not item_id:
                continue
            if "worker_preference" in removed_keys and item_id.startswith(
                "config-driver-pref-"
            ):
                ids.add(item_id)
            if "shift_limit" in removed_keys and (
                item_id == "config-shift-hard-penalty"
                or item_id == "config-weight-shift_limit"
            ):
                ids.add(item_id)
        return ids

    def is_goal_term_self_anchored(self, key: str, entry: dict[str, Any]) -> bool:
        """VRPTW: `worker_preference` self-anchors when its rule list is non-empty;
        `shift_limit` self-anchors when it carries a `max_shift_hours` value.
        """
        props = entry.get("properties") if isinstance(entry, dict) else None
        if not isinstance(props, dict):
            return False
        if key == "worker_preference":
            rules = props.get("driver_preferences")
            return isinstance(rules, list) and bool(rules)
        if key == "shift_limit":
            return "max_shift_hours" in props
        return False

    def synthesize_brief_items_from_goal_terms(
        self, goal_terms: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """No separate companion rows. Companion detail (driver-preference
        rules, shift cap) is merged INLINE into each term's single
        ``config-weight-<key>`` def row via ``goal_term_companion_summary`` —
        one row per concept that also carries the lock toggle. The
        ``config-driver-pref-`` prefix stays owned (see
        ``prose_id_prefixes_for_goal_term``) so legacy standalone rows from
        older sessions get pruned on the next refresh."""
        return []

    def goal_term_companion_summary(self, goal_term_key: str, entry: dict[str, Any]) -> str | None:
        """Merge a term's companion detail into its def row.

        - ``shift_limit`` → the max-shift-hours cap.
        - ``worker_preference`` → the per-driver rules, one concise clause each.
        """
        if not isinstance(entry, dict):
            return None
        props = entry.get("properties")
        if not isinstance(props, dict):
            return None

        if goal_term_key == "shift_limit":
            hours = props.get("max_shift_hours")
            if not isinstance(hours, (int, float)) or isinstance(hours, bool) or hours <= 0:
                return None
            h = float(hours)
            hours_str = str(int(h)) if h.is_integer() else str(h)
            return f"Cap: {hours_str} hours per driver."

        if goal_term_key == meta_worker_preference_key():
            rules = props.get("driver_preferences")
            if not isinstance(rules, list) or not rules:
                return None
            from vrptw_problem.brief_seed import (
                _DRIVER_NAMES_BY_INDEX,
                _ZONE_LETTERS_BY_INDEX,
            )

            clauses: list[str] = []
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                vid = rule.get("vehicle_idx")
                driver = (
                    _DRIVER_NAMES_BY_INDEX.get(vid, f"Driver {vid}")
                    if isinstance(vid, int)
                    else "A driver"
                )
                cond = str(rule.get("condition") or "").strip().lower()
                if cond == "avoid_zone":
                    zl = (
                        _ZONE_LETTERS_BY_INDEX.get(rule.get("zone"))
                        if isinstance(rule.get("zone"), int)
                        else None
                    )
                    if zl:
                        clauses.append(f"{driver} avoids Zone {zl}")
                elif cond == "order_priority":
                    pr = str(rule.get("order_priority") or "").strip().lower()
                    if pr in {"express", "standard"}:
                        clauses.append(f"{driver} skips {pr}-priority orders")
                elif cond == "shift_over_limit":
                    lim = rule.get("limit_minutes")
                    if isinstance(lim, (int, float)) and not isinstance(lim, bool) and lim > 0:
                        hrs = float(lim) / 60.0
                        hs = f"{hrs:.1f}".rstrip("0").rstrip(".")
                        clauses.append(f"{driver} caps shifts at {hs}h")
            if not clauses:
                return None
            return "Rules — " + "; ".join(clauses) + "."

        return None

    def verify_brief_companion(
        self,
        brief: dict[str, Any],
        *,
        visible_reply: str | None = None,
    ) -> list[dict[str, Any]]:
        """Port-level structural checks for VRPTW briefs (S2 verification).

        Catches the structured/prose mismatches that the prior safety-net
        LLM was patching after the fact:

        - ``worker_preference`` is in ``goal_terms`` but
          ``properties.driver_preferences`` is empty/missing AND there are
          no synthesized prose rows referencing driver preferences.
        - ``shift_limit`` is in ``goal_terms`` but
          ``properties.max_shift_hours`` is missing or non-positive.
        - A driver-preference prose row exists in ``items[]`` but the
          structured rule list is empty.

        Returns issue dicts in the standardized verification shape.
        """
        out: list[dict[str, Any]] = []
        if not isinstance(brief, dict):
            return out
        goal_terms = brief.get("goal_terms") if isinstance(brief.get("goal_terms"), dict) else {}
        items = brief.get("items") if isinstance(brief.get("items"), list) else []

        wp_entry = goal_terms.get("worker_preference") if isinstance(goal_terms, dict) else None
        if isinstance(wp_entry, dict):
            props = wp_entry.get("properties") if isinstance(wp_entry.get("properties"), dict) else {}
            rules = props.get("driver_preferences") if isinstance(props, dict) else None
            has_rules = isinstance(rules, list) and len(rules) > 0
            has_prose_rule = any(
                isinstance(it, dict)
                and str(it.get("id") or "").startswith("config-driver-pref-")
                for it in items
            )
            # A pending OQ that anchors back to ``worker_preference`` is the
            # third acceptable exit — the LLM has parked the question with the
            # participant. Don't double-fire while we're waiting on a human.
            open_questions = brief.get("open_questions") if isinstance(brief.get("open_questions"), list) else []
            has_pending_oq = any(
                isinstance(q, dict)
                and q.get("goal_key") == "worker_preference"
                and str(q.get("status") or "open").strip().lower() == "open"
                for q in open_questions
            )
            if not has_rules and not has_pending_oq:
                out.append(
                    {
                        "category": "port_companion",
                        # Severity is now error in both branches — the bare-empty
                        # case used to be warn and slipped past the verifier,
                        # letting the LLM ship "I've added worker preferences"
                        # while the structured carrier was empty.
                        "severity": "error",
                        "subject": "worker_preference.driver_preferences",
                        "message": (
                            "The brief commits a `worker_preference` goal term but the structured "
                            "`properties.driver_preferences` rule list is empty — populate it with "
                            "explicit vehicle/condition/penalty rules."
                            if has_prose_rule
                            else
                            "`worker_preference` goal term is present without structured rules. "
                            "Pick one of: (a) populate `properties.driver_preferences` with explicit "
                            "vehicle/condition/penalty rules; (b) drop the goal term; (c) add an "
                            "`open_questions` row with "
                            "`goal_key: \"worker_preference\"` asking the user for "
                            "specific rules."
                        ),
                    }
                )

        sl_entry = goal_terms.get("shift_limit") if isinstance(goal_terms, dict) else None
        if isinstance(sl_entry, dict):
            props = sl_entry.get("properties") if isinstance(sl_entry.get("properties"), dict) else {}
            cap = props.get("max_shift_hours") if isinstance(props, dict) else None
            if (
                cap is None
                or isinstance(cap, bool)
                or not isinstance(cap, (int, float))
                or cap <= 0
            ):
                out.append(
                    {
                        "category": "port_companion",
                        "severity": "error",
                        "subject": "shift_limit.max_shift_hours",
                        "message": (
                            "The brief commits a `shift_limit` goal term but the structured "
                            "`properties.max_shift_hours` value is missing or non-positive. Set "
                            "it to the maximum shift length in hours."
                        ),
                    }
                )

        return out

    def mediocre_participant_starter_config(self) -> dict:
        from copy import deepcopy
        return deepcopy({
            "problem": {
                "weights": {
                    "travel_time": 1.0,
                    "workload_balance": 4.0,
                },
                "only_active_terms": True,
                "algorithm": "SA",
                "algorithm_params": {"temp_init": 40, "cooling_rate": 0.92},
                "epochs": 18,
                "pop_size": 12,
                "random_seed": 42,
            }
        })

    def problem_brief_template_fields(self) -> dict[str, str]:
        return {
            "solver_scope": "general_metaheuristic_translation",
            "backend_template": "routing_time_windows",
        }

    def format_optimization_run_chat_summary(
        self,
        *,
        session_run_number: int,
        run_ok: bool,
        cost: float | None,
        result: dict[str, Any] | None,
        error_message: str | None,
    ) -> str:
        if not run_ok:
            return f"Run #{session_run_number} failed: {error_message or 'error'}."
        return f"Run #{session_run_number} finished. I've updated the fleet schedule timeline and route details for this run — open them in the Results & Visualization panel."

    # Traffic is stochastic, so a single-seed canonical score is noisy (a schedule
    # can swing ±100s of cost by seed). Average over this many traffic draws.
    _CANON_SEEDS = 10
    _MAX_SHIFT_MIN = 8.0 * 60
    _N_ORDERS = 30

    def canonical_evaluation_for_result(self, result_json: dict[str, Any]) -> dict[str, Any] | None:
        """Re-score a run's produced schedule under the OFFICIAL (canonical)
        objective AND check the true hard constraints — averaged over several
        traffic seeds so the value is robust, not a lucky single draw.

        Returns mean canonical cost + its std (for error bars), the fraction of
        seeds that are feasible, and a robust ``feasible`` flag (feasible on the
        large majority of traffic draws). Hard constraints (per the handout):
        lateness (time-window), capacity overflow, shift (>8h); plus full order
        coverage. None if the result has no usable schedule.
        """
        try:
            import numpy as np

            from vrptw_problem.orders import get_orders
            from vrptw_problem.researcher.official_evaluator import evaluate_official

            raw = ((result_json or {}).get("schedule") or {}).get("routes")
            if not raw:
                return None
            routes = [
                r.get("task_indices", [])
                for r in sorted(raw, key=lambda x: x.get("vehicle_index", 0))
            ]
            orders = get_orders(seed=None)
            # Order coverage is traffic-independent — check once.
            flat = [o for route in routes for o in route]
            covered = set(flat) == set(range(self._N_ORDERS)) and len(flat) == len(set(flat))

            costs, feas, lateness, capacity, shift_over = [], [], [], [], []
            for s in range(self._CANON_SEEDS):
                cost, m = evaluate_official(routes, orders, np.random.RandomState(s))
                late = float(m.get("tw_violation_min", 0) or 0)
                cap = float(m.get("capacity_overflow", 0) or 0)
                shifts = m.get("shift_durations", []) or []
                over = any(sd > self._MAX_SHIFT_MIN for sd in shifts)
                costs.append(float(cost))
                lateness.append(late)
                capacity.append(cap)
                shift_over.append(over)
                feas.append(late == 0 and cap == 0 and not over and covered)

            feasible_frac = float(np.mean(feas))
            return {
                "canonical_cost": float(np.mean(costs)),
                "canonical_cost_std": float(np.std(costs)),
                "feasible_frac": feasible_frac,
                "feasible": feasible_frac >= 0.8,  # robust: valid on most traffic draws
                "lateness_min": float(np.mean(lateness)),
                "capacity_overflow": float(np.mean(capacity)),
                "shift_over_8h": float(np.mean(shift_over)) > 0.5,
                "all_orders_covered": bool(covered),
            }
        except Exception:
            return None

    def canonical_cost_for_result(self, result_json: dict[str, Any]) -> float | None:
        """Canonical cost only (thin wrapper over ``canonical_evaluation_for_result``)."""
        ev = self.canonical_evaluation_for_result(result_json)
        return ev["canonical_cost"] if ev else None

    def hard_constraint_origins(self, briefs: list[dict[str, Any]]) -> dict[str, str]:
        """Classify who ORIGINATED each hard constraint, from structured brief
        provenance across a session's snapshots (no text parsing):

        - user_volunteered: entered as a `gathered` item, no OQ raised.
        - agent_asked:      an open_question with that goal_key was raised
                            (waterfall's ask-then-confirm; the OQ drops on commit).
        - agent_assumed:    entered as a `kind: assumption` item (agile fait accompli).
        - mixed / present_other / absent otherwise.
        """
        HARD = ("lateness_penalty", "capacity_penalty", "shift_limit")
        out: dict[str, str] = {}
        last_terms = (briefs[-1].get("goal_terms") or {}) if briefs else {}
        for k in HARD:
            gathered = assumed = oq_any = False
            for b in briefs:
                for it in (b.get("items") or []):
                    if it.get("goal_key") == k:
                        if it.get("kind") == "assumption":
                            assumed = True
                        elif it.get("kind") == "gathered":
                            gathered = True
                for q in (b.get("open_questions") or []):
                    if q.get("goal_key") == k:
                        oq_any = True
            if assumed and oq_any:
                out[k] = "mixed"
            elif assumed:
                out[k] = "agent_assumed"
            elif oq_any:
                out[k] = "agent_asked"
            elif gathered:
                out[k] = "user_volunteered"
            elif k in last_terms:
                out[k] = "present_other"
            else:
                out[k] = "absent"
        return out

    def formulation_quality_for_config(self, panel_config: dict[str, Any]) -> dict[str, Any] | None:
        """Score how well a config captures the true problem (specification level).

        All-positive score, no deductions:
            formulation_score = coverage + hard_bonus + objective_bonus
          - coverage        : +1 per canonical term identified (present & active) — max 7
                              (travel_time + 3 hard + 3 soft).
          - hard_bonus      : +1 per hard constraint correctly BINDING (type 'hard'
                              OR weight > every non-hard term's weight) — max 3.
          - objective_bonus : +1 if travel_time is present AND not marked 'hard'
                              (i.e., it's serving as the target, not a constraint).

        Soft/preference terms only earn their coverage point (their type is up to
        interpretation). ``objective_as_hard`` and ``soft_as_hard`` are reported as
        DESCRIPTIVE behavioral columns and are NOT part of the score. Feasibility
        (computed separately over traffic seeds) is the outcome cross-check.
        """
        try:
            HARD = ("lateness_penalty", "capacity_penalty", "shift_limit")
            OBJECTIVE = ("travel_time",)
            SOFT = ("worker_preference", "workload_balance", "express_miss_penalty")

            prob = (panel_config or {}).get("problem") or panel_config or {}
            gts = prob.get("goal_terms") or {}
            weights = prob.get("weights") or {}

            def wt(key: str, term: Any) -> float | None:
                w = term.get("weight") if isinstance(term, dict) else None
                if w is None:
                    w = weights.get(key)
                try:
                    return float(w)
                except (TypeError, ValueError):
                    return None

            def active(key: str, term: Any) -> bool:
                w = wt(key, term)
                return w is not None and w != 0

            non_hard_ws = [wt(k, v) for k, v in gts.items() if k not in HARD and wt(k, v) is not None]
            max_non_hard = max(non_hard_ws) if non_hard_ws else 0.0

            hard_status: dict[str, str] = {}
            for k in HARD:
                v = gts.get(k)
                if not v:
                    hard_status[k] = "absent"
                    continue
                t = v.get("type") if isinstance(v, dict) else None
                w = wt(k, v)
                if t == "hard":
                    hard_status[k] = "hard"
                elif w is not None and w > max_non_hard and w > 0:
                    hard_status[k] = "binding_by_weight"
                elif active(k, v):
                    hard_status[k] = "weak"
                else:
                    hard_status[k] = "absent"

            def covered(k: str) -> bool:
                return k in gts and active(k, gts[k])

            # coverage = every goal term the user defined (present & active), REGARDLESS
            # of type; the algorithm carrier is not a requirement, so it's excluded.
            NON_REQUIREMENT = ("search_strategy", "algorithm")
            coverage = sum(1 for k, v in gts.items() if k not in NON_REQUIREMENT and active(k, v))
            # hard_bonus = # hard constraints correctly binding.
            hard_bonus = sum(1 for s in hard_status.values() if s in ("hard", "binding_by_weight"))
            # objective_bonus = travel_time present AND not marked hard (serving as target).
            objective_present = covered("travel_time")
            objective_as_hard = int(
                objective_present
                and isinstance(gts.get("travel_time"), dict)
                and gts["travel_time"].get("type") == "hard"
            )
            objective_bonus = int(objective_present and not objective_as_hard)
            soft_covered = sum(1 for k in SOFT if covered(k))
            soft_as_hard = sum(
                1 for k in SOFT
                if isinstance(gts.get(k), dict) and gts[k].get("type") == "hard"
            )
            return {
                "coverage": coverage,
                "hard_bonus": hard_bonus,
                "objective_present": objective_present,
                "objective_bonus": objective_bonus,
                "soft_covered": soft_covered,
                "hard_status": hard_status,
                # --- descriptive behavioral columns, NOT part of the score ---
                "objective_as_hard": objective_as_hard,
                "soft_as_hard": soft_as_hard,
                "n_custom_hard": sum(
                    1 for k in HARD
                    if isinstance(gts.get(k), dict) and gts[k].get("type") == "custom"
                ),
                # Score = coverage + hard_bonus + objective_bonus (higher = better).
                "formulation_score": coverage + hard_bonus + objective_bonus,
            }
        except Exception:
            return None


STUDY_PORT = VrptwStudyPort()
