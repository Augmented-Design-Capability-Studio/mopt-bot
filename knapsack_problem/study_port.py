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
                WeightDefinition("value_emphasis", "Total value", "Higher weight favors more packed value"),
                WeightDefinition("capacity_overflow", "Capacity overflow", "Penalty when selection exceeds knapsack capacity"),
                WeightDefinition("selection_sparsity", "Selection size", "Penalty for number of items picked"),
            ],
            extension_ui="none",
            visualization_presets=["knapsack_selection"],
            primary_visualization="knapsack_selection",
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


STUDY_PORT = KnapsackStudyPort()
