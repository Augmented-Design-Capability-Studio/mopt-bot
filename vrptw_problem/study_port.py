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
                WeightDefinition(key, label, desc, direction=direction)
                for key, label, desc, direction in VRPTW_WEIGHT_DEFINITIONS
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

    def locked_companion_fields(self) -> dict[str, str]:
        return {"worker_preference": "driver_preferences"}

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
        if result:
            v = result.get("violations") or {}
            tw_stops = int(v.get("time_window_stop_count", 0))
            tw_mins = float(v.get("time_window_minutes_over", 0))
            cap_over = int(v.get("capacity_units_over", 0))
            prio_miss = int(v.get("priority_deadline_misses", 0))
            shift_pen = float(v.get("shift_limit_penalty", 0))
            m = result.get("metrics") or {}
            travel = float(m.get("total_travel_minutes", 0))
            wl_var = float(m.get("workload_variance", 0))
            viol_strs: list[str] = []
            if tw_stops:
                viol_strs.append(f"{tw_stops} time-window stops late ({tw_mins:.1f} min over)")
            if cap_over:
                viol_strs.append(f"{cap_over} units over capacity")
            if prio_miss:
                viol_strs.append(f"{prio_miss} priority-order deadline misses")
            if shift_pen:
                viol_strs.append("shift limit exceeded")
            if viol_strs:
                summary_parts.append("Violations: " + "; ".join(viol_strs))
            else:
                summary_parts.append("No constraint violations")
            summary_parts.append(f"Travel: {travel:.1f} min · workload variance: {wl_var:.1f}")
            weight_warnings = result.get("weight_warnings") or []
            for w in weight_warnings:
                summary_parts.append(f"Note: {w}")
        return ". ".join(summary_parts) + "."


STUDY_PORT = VrptwStudyPort()
