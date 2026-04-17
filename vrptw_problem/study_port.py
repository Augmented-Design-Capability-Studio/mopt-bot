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
    weight_slot_markers as meta_weight_slot_markers,
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
                WeightDefinition(key, label, desc)
                for key, label, desc in VRPTW_WEIGHT_DEFINITIONS
            ],
            extension_ui="vrptw_extras",
            visualization_presets=["fleet_gantt"],
            primary_visualization="fleet_gantt",
            weight_display_keys=meta_weight_display_keys(),
            worker_preference_key=meta_worker_preference_key(),
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

    def weight_slot_markers(self) -> dict[str, tuple[str, ...]]:
        return meta_weight_slot_markers()

    def weight_display_keys(self) -> list[str]:
        return meta_weight_display_keys()

    def worker_preference_key(self) -> str | None:
        return meta_worker_preference_key()

    def study_prompt_appendix(self) -> str | None:
        from vrptw_problem.study_prompts import VRPTW_STUDY_PROMPT_APPENDIX

        return VRPTW_STUDY_PROMPT_APPENDIX

    def config_derive_system_prompt(self) -> str:
        from vrptw_problem.study_prompts import VRPTW_CONFIG_DERIVE_SYSTEM_PROMPT

        return VRPTW_CONFIG_DERIVE_SYSTEM_PROMPT.strip()

    def panel_patch_response_json_schema(self) -> dict:
        return panel_patch_response_json_schema()

    def problem_brief_template_fields(self) -> dict[str, str]:
        return {
            "solver_scope": "general_metaheuristic_translation",
            "backend_template": "routing_time_windows",
        }

    def default_problem_brief_system_items(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "system-backend-template",
                "text": "Current backend template uses a routing and time-window optimization schema.",
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


STUDY_PORT = VrptwStudyPort()
