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
            worker_preference_key=self.worker_preference_key(),
        )

    def sanitize_panel_config(self, panel_config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        cfg = deepcopy(panel_config)
        problem = cfg.get("problem")
        if not isinstance(problem, dict):
            return cfg, []
        warnings: list[str] = []
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

    def worker_preference_key(self) -> str | None:
        return None

    def weight_slot_markers(self) -> dict[str, tuple[str, ...]]:
        return {
            "value_emphasis": ("value", "profit", "packed value"),
            "capacity_overflow": ("capacity", "overflow", "weight limit"),
            "selection_sparsity": ("sparsity", "fewer items", "compact"),
        }

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

    def default_problem_brief_system_items(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "system-backend-template",
                "text": "Current backend template uses a 0/1 knapsack packing schema with a fixed item set.",
                "kind": "system",
                "source": "system",
                "status": "confirmed",
                "editable": False,
            },
            {
                "id": "system-translation-layer",
                "text": "The assistant may discuss the task in general optimization terms and translate that intent into the active solver configuration.",
                "kind": "system",
                "source": "system",
                "status": "confirmed",
                "editable": False,
            },
            {
                "id": "system-schema-scope",
                "text": "Final configuration fields map onto the currently supported backend rather than an arbitrary custom codebase.",
                "kind": "system",
                "source": "system",
                "status": "confirmed",
                "editable": False,
            },
        ]

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
        if cost is None:
            return f"Run #{session_run_number} finished (cost not recorded)."
        summary_parts = [f"Run #{session_run_number} finished — cost {cost:.2f}"]
        if not result:
            return summary_parts[0] + "."
        vis = (result.get("visualization") or {}).get("payload") or {}
        m = result.get("metrics") or {}
        total_value = float(vis.get("total_value") or 0.0)
        total_weight = float(vis.get("total_weight") or m.get("workload_variance") or 0.0)
        capacity = float(vis.get("capacity") or 0.0)
        feasible = bool(vis.get("feasible", m.get("knapsack_feasible", False)))
        overflow = float(m.get("knapsack_overflow", 0.0))
        selected = int(m.get("driver_preference_units", 0))
        v = result.get("violations") or {}
        cap_flag = int(v.get("capacity_units_over", 0))
        cap_suffix = f" / capacity {capacity:.1f}" if capacity > 0 else ""
        detail_bits: list[str] = [
            f"{selected} items selected",
            f"packed value {total_value:.1f}",
            f"packed weight {total_weight:.1f}{cap_suffix}",
        ]
        if feasible and overflow <= 0 and not cap_flag:
            detail_bits.append("feasible packing")
        else:
            if overflow > 0 or cap_flag:
                detail_bits.append("over capacity (penalty in cost)")
            else:
                detail_bits.append("infeasible or penalized layout")
        summary_parts.append(" · ".join(detail_bits))
        weight_warnings = result.get("weight_warnings") or []
        for w in weight_warnings:
            summary_parts.append(f"Note: {w}")
        return ". ".join(summary_parts) + "."


STUDY_PORT = KnapsackStudyPort()
