"""MOPT study port for the 0/1 knapsack benchmark (see ``mopt_manifest.toml``)."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.algorithm_catalog import canonical_algorithm_stored, filter_algorithm_params
from app.problems.exceptions import RunCancelled
from app.problems.types import TestProblemMeta, WeightDefinition

from knapsack_problem.panel_schema import panel_patch_response_json_schema


def _rebuild_goal_terms(problem: dict[str, Any]) -> None:
    constraint_types = (
        problem.get("constraint_types")
        if isinstance(problem.get("constraint_types"), dict)
        else {}
    )
    locked = (
        set(x for x in problem.get("locked_goal_terms", []) if isinstance(x, str))
        if isinstance(problem.get("locked_goal_terms"), list)
        else set()
    )
    order = (
        [k for k in problem.get("goal_term_order", []) if isinstance(k, str)]
        if isinstance(problem.get("goal_term_order"), list)
        else []
    )
    order_idx = {k: i + 1 for i, k in enumerate(order)}
    max_rank = len(order_idx)
    goal_terms: dict[str, Any] = {}
    for k, v in (problem.get("weights") or {}).items():
        if not isinstance(k, str) or not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        t = str(constraint_types.get(k) or "").strip().lower()
        term_type = t if t in {"soft", "hard", "custom"} else "objective"
        rank = order_idx.get(k)
        if rank is None:
            max_rank += 1
            rank = max_rank
        goal_terms[k] = {
            "weight": float(v),
            "type": term_type,
            "rank": rank,
            **({"locked": True} if k in locked else {}),
        }
    if goal_terms:
        problem["goal_terms"] = goal_terms


class KnapsackStudyPort:
    id = "knapsack"
    label = "0/1 Knapsack (toy)"

    def meta(self) -> TestProblemMeta:
        return TestProblemMeta(
            id=self.id,
            label=self.label,
            weight_definitions=[
                WeightDefinition("value_emphasis", "Total value", "Higher weight favors more packed value", direction="maximize"),
                WeightDefinition("capacity_overflow", "Capacity overflow", "Penalty when selection exceeds knapsack capacity", direction="minimize"),
                WeightDefinition("selection_sparsity", "Selection size", "Penalty for number of items picked", direction="minimize"),
            ],
            extension_ui="none",
            visualization_presets=["knapsack_selection"],
            primary_visualization="knapsack_selection",
            weight_display_keys=self.weight_display_keys(),
            worker_preference_key=None,
            gate_conditional_companions={},
        )

    def sanitize_panel_config(self, panel_config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        cfg = deepcopy(panel_config)
        problem = cfg.get("problem")
        if not isinstance(problem, dict):
            return cfg, []
        warnings: list[str] = []
        problem.pop("hard_constraints", None)
        problem.pop("soft_constraints", None)
        weights_raw = problem.get("weights")
        if weights_raw is None:
            problem.pop("weights", None)
        elif not isinstance(weights_raw, dict):
            problem.pop("weights", None)
            warnings.append("Ignored malformed `problem.weights`; expected an object.")
        else:
            clean: dict[str, Any] = {}
            allowed = {"value_emphasis", "capacity_overflow", "selection_sparsity"}
            for k, v in weights_raw.items():
                if k in allowed and isinstance(v, (int, float)) and not isinstance(v, bool):
                    clean[k] = float(v)
            problem["weights"] = clean
        ap_raw = problem.get("algorithm_params")
        if ap_raw is None:
            if isinstance(problem.get("weights"), dict):
                _rebuild_goal_terms(problem)
                problem.pop("weights", None)
                problem.pop("constraint_types", None)
            return cfg, warnings
        if not isinstance(ap_raw, dict):
            problem.pop("algorithm_params", None)
            warnings.append("Removed malformed `problem.algorithm_params`; expected an object.")
            return cfg, warnings
        algo = canonical_algorithm_stored(problem.get("algorithm"))
        if algo is None:
            problem.pop("algorithm_params", None)
            return cfg, warnings
        filtered, w = filter_algorithm_params(algo, ap_raw)
        if filtered:
            problem["algorithm_params"] = filtered
        else:
            problem.pop("algorithm_params", None)
        warnings.extend(w)
        if isinstance(problem.get("weights"), dict):
            _rebuild_goal_terms(problem)
            problem.pop("weights", None)
            problem.pop("constraint_types", None)
        return cfg, warnings

    def parse_problem_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        from knapsack_problem.study_bridge import parse_problem_config as _parse

        return _parse(raw, filter_algorithm_params=filter_algorithm_params)

    def solve_request_to_result(
        self,
        body: dict[str, Any],
        timeout_sec: float,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        from knapsack_problem.mealpy_solve import OptimizationCancelled
        from knapsack_problem.study_bridge import solve_request_to_result as _solve

        try:
            return _solve(
                body,
                timeout_sec,
                cancel_event,
                filter_algorithm_params=filter_algorithm_params,
            )
        except OptimizationCancelled:
            raise RunCancelled() from None

    def derive_problem_panel_from_brief(self, problem_brief: dict[str, Any]) -> dict[str, Any] | None:
        from knapsack_problem.brief_seed import derive_problem_panel_from_brief

        return derive_problem_panel_from_brief(problem_brief)

    def weight_item_labels(self) -> dict[str, str]:
        return {
            "value_emphasis": "Total packed value",
            "capacity_overflow": "Knapsack capacity overflow",
            "selection_sparsity": "Number of selected items",
        }

    def weight_display_keys(self) -> list[str]:
        return ["value_emphasis", "capacity_overflow", "selection_sparsity"]

    def auto_anchored_goal_term_keys(self) -> frozenset[str]:
        return frozenset(self.weight_display_keys())

    def gate_conditional_companions(self) -> dict[str, str]:
        return {}

    def companion_present(self, goal_term_key: str, value: Any) -> bool:
        if isinstance(value, list):
            return len(value) > 0
        return bool(value)

    def verify_brief_companion(
        self,
        brief: dict[str, Any],
        *,
        visible_reply: str | None = None,
    ) -> list[dict[str, Any]]:
        return []

    def goal_term_rationales(self) -> dict[str, str]:
        return {
            "value_emphasis": "to push the solver toward higher-value selections",
            "capacity_overflow": "to discourage exceeding the knapsack capacity",
            "selection_sparsity": "to keep the selection compact rather than grabbing everything",
        }

    def extra_managed_problem_fields(self) -> tuple[str, ...]:
        return ()

    def goal_term_property_field_mirrors(self) -> dict[str, str]:
        return {}

    def is_goal_term_self_anchored(self, key: str, entry: dict[str, Any]) -> bool:
        return False

    def normalize_goal_term_property(
        self, prop_key: str, prop_val: Any
    ) -> tuple[bool, Any] | None:
        return None

    def problem_brief_item_slot(self, item: dict[str, Any]) -> str | None:
        return None

    def brief_item_ids_to_strip_on_goal_term_removal(
        self,
        removed_keys: set[str],
        prior_goal_terms: dict[str, Any],
        brief_items: list[dict[str, Any]],
    ) -> set[str]:
        ids: set[str] = set()
        for key in removed_keys:
            entry = prior_goal_terms.get(key) if isinstance(prior_goal_terms, dict) else None
            if not isinstance(entry, dict):
                continue
            evidence = entry.get("evidence_item_ids")
            if isinstance(evidence, list):
                for eid in evidence:
                    if isinstance(eid, str) and eid:
                        ids.add(eid)
        return ids

    def synthesize_brief_items_from_goal_terms(
        self, goal_terms: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return []

    def format_run_context_violation_details(
        self, violations: dict[str, Any]
    ) -> list[str]:
        return []

    def visualization_capabilities(self) -> list[str]:
        return [
            "Convergence trend across iterations",
            "Run metric cards (cost, packed value, feasibility)",
            "Selected-items view for the latest run",
        ]


    def study_prompt_appendix(self) -> str | None:
        from knapsack_problem.study_prompts import KNAPSACK_STUDY_PROMPT_APPENDIX

        return KNAPSACK_STUDY_PROMPT_APPENDIX

    def config_derive_system_prompt(self) -> str:
        from knapsack_problem.study_prompts import KNAPSACK_CONFIG_DERIVE_SYSTEM_PROMPT

        return KNAPSACK_CONFIG_DERIVE_SYSTEM_PROMPT.strip()

    def panel_patch_response_json_schema(self) -> dict:
        return panel_patch_response_json_schema()

    def locked_companion_fields(self) -> dict[str, str]:
        return {}

    def prose_id_prefixes_for_goal_term(self, goal_term_key: str) -> tuple[str, ...]:
        return ()

    def goal_term_properties_schema(self) -> dict | None:
        # Knapsack has no typed child fields under goal_terms[key].properties;
        # default permissive shape from schema_shared is used.
        return None

    def mediocre_participant_starter_config(self) -> dict:
        from copy import deepcopy
        return deepcopy({
            "problem": {
                "weights": {
                    "value_emphasis": 1.0,
                    "capacity_overflow": 40.0,
                },
                "only_active_terms": True,
                "algorithm": "GA",
                "epochs": 24,
                "pop_size": 16,
                "random_seed": 42,
            }
        })

    def problem_brief_template_fields(self) -> dict[str, str]:
        return {
            "solver_scope": "general_metaheuristic_translation",
            "backend_template": "zero_one_knapsack",
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
        return f"Run #{session_run_number} finished. I've refreshed the selected-items view and convergence chart in the Results & Visualization panel."


STUDY_PORT = KnapsackStudyPort()
