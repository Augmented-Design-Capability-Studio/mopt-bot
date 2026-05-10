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

    def weight_display_keys(self) -> list[str]:
        return meta_weight_display_keys()

    def worker_preference_key(self) -> str | None:
        return meta_worker_preference_key()

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
        from vrptw_problem.brief_seed import synthesize_driver_preference_items
        return synthesize_driver_preference_items(goal_terms)

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


STUDY_PORT = VrptwStudyPort()
