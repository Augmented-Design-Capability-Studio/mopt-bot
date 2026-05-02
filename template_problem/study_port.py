"""MOPT study port for the template problem (see ``mopt_manifest.toml``).

Copy this file to your problem directory and replace every TODO with real implementations.
The class name and STUDY_PORT singleton at the bottom are the only things the registry cares about.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.algorithm_catalog import canonical_algorithm_stored, filter_algorithm_params
from app.problems.exceptions import RunCancelled
from app.problems.types import TestProblemMeta, WeightDefinition


class TemplateProblemPort:
    # ------------------------------------------------------------------ #
    # Identity — must be unique across all registered problems             #
    # ------------------------------------------------------------------ #
    id = "template"          # TODO: short snake_case identifier, e.g. "tsp"
    label = "Template problem"   # TODO: human-readable display name

    # ------------------------------------------------------------------ #
    # Metadata exposed to the frontend via GET /meta/test-problems         #
    # ------------------------------------------------------------------ #
    def meta(self) -> TestProblemMeta:
        return TestProblemMeta(
            id=self.id,
            label=self.label,
            weight_definitions=[
                # TODO: list every objective/penalty the user can tune.
                # direction defaults to "minimize"; use "maximize" where appropriate.
                WeightDefinition("obj_a", "Objective A", "Description of what this penalizes/rewards."),
                WeightDefinition("obj_b", "Objective B", "Description of what this penalizes/rewards."),
            ],
            # "none" means no problem-specific React extension UI.
            # Set to your problem's id (e.g. "template") if you add a frontend/index.ts MODULE.
            extension_ui="none",
            visualization_presets=[],   # TODO: list preset ids (must match frontend viz tabs)
            primary_visualization=None, # TODO: default visualization tab id, or None
            weight_display_keys=self.weight_display_keys(),
            worker_preference_key=self.worker_preference_key(),
        )

    # ------------------------------------------------------------------ #
    # Panel config sanitization                                            #
    # Validates and normalises the JSON stored in session.panel_config     #
    # ------------------------------------------------------------------ #
    def sanitize_panel_config(self, panel_config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        cfg = deepcopy(panel_config)
        problem = cfg.get("problem")
        if not isinstance(problem, dict):
            return cfg, []
        warnings: list[str] = []

        # --- weights ---
        allowed_weights = {"obj_a", "obj_b"}  # TODO: add every weight key
        weights_raw = problem.get("weights")
        if weights_raw is None:
            problem.pop("weights", None)
        elif not isinstance(weights_raw, dict):
            problem.pop("weights", None)
            warnings.append("Ignored malformed `problem.weights`; expected an object.")
        else:
            clean: dict[str, Any] = {}
            for k, v in weights_raw.items():
                if k in allowed_weights and isinstance(v, (int, float)) and not isinstance(v, bool):
                    clean[k] = float(v)
            problem["weights"] = clean

        # --- algorithm_params ---
        ap_raw = problem.get("algorithm_params")
        if ap_raw is None:
            return cfg, warnings
        if not isinstance(ap_raw, dict):
            problem.pop("algorithm_params", None)
            warnings.append("Removed malformed `problem.algorithm_params`.")
            return cfg, warnings
        algo = canonical_algorithm_stored(problem.get("algorithm"))
        if algo is None:
            problem.pop("algorithm_params", None)
            return cfg, warnings
        filtered, w = filter_algorithm_params(algo, ap_raw)
        problem["algorithm_params"] = filtered if filtered else problem.pop("algorithm_params", None)
        warnings.extend(w)
        return cfg, warnings

    # ------------------------------------------------------------------ #
    # Config parsing — translate panel JSON into solver-ready kwargs       #
    # ------------------------------------------------------------------ #
    def parse_problem_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        # TODO: import and call your own parse function, or implement inline.
        # Must return a dict that your solve code can accept.
        from template_problem.study_bridge import parse_problem_config as _parse  # TODO
        return _parse(raw, filter_algorithm_params=filter_algorithm_params)

    # ------------------------------------------------------------------ #
    # Solver entry point                                                   #
    # ------------------------------------------------------------------ #
    def solve_request_to_result(
        self,
        body: dict[str, Any],
        timeout_sec: float,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        # TODO: import and call your solver.  Must raise RunCancelled() when
        # cancel_event signals cancellation (cooperative cancel).
        from template_problem.optimizer import OptimizationCancelled  # TODO
        from template_problem.study_bridge import solve_request_to_result as _solve  # TODO
        try:
            return _solve(body, timeout_sec, cancel_event, filter_algorithm_params=filter_algorithm_params)
        except OptimizationCancelled:
            raise RunCancelled() from None

    # ------------------------------------------------------------------ #
    # Deterministic brief → panel derivation (LLM fallback)               #
    # ------------------------------------------------------------------ #
    def derive_problem_panel_from_brief(self, problem_brief: dict[str, Any]) -> dict[str, Any] | None:
        # TODO: implement a deterministic (no LLM) derivation of the panel
        # config from the saved problem brief.  Return None if not derivable.
        from template_problem.brief_seed import derive_problem_panel_from_brief  # TODO
        return derive_problem_panel_from_brief(problem_brief)

    # ------------------------------------------------------------------ #
    # Label / marker helpers for brief ↔ panel sync                       #
    # ------------------------------------------------------------------ #
    def weight_item_labels(self) -> dict[str, str]:
        # TODO: human labels used when syncing gathered info back into the panel.
        return {
            "obj_a": "Objective A (description)",
            "obj_b": "Objective B (description)",
        }

    def weight_slot_markers(self) -> dict[str, tuple[str, ...]]:
        # TODO: substrings used to atomize brief items into weight slots.
        return {
            "obj_a": ("objective a", "metric a"),
            "obj_b": ("objective b", "metric b"),
        }

    # ------------------------------------------------------------------ #
    # Gate metadata                                                        #
    # ------------------------------------------------------------------ #
    def weight_display_keys(self) -> list[str]:
        # TODO: ordered list of weight keys that count toward "at least one
        # goal term" for the agile optimization gate.  Exclude purely
        # parametric keys that should not independently satisfy the gate.
        return ["obj_a", "obj_b"]

    def worker_preference_key(self) -> str | None:
        # TODO: return the weight key whose UI block is conditional on a
        # worker-preference list being non-empty, or None if not applicable.
        return None

    def visualization_capabilities(self) -> list[str]:
        # TODO: describe what participants see after each run.
        return [
            "Convergence trend across iterations",
            "Run metric summary cards",
        ]

    # ------------------------------------------------------------------ #
    # LLM prompt contributions                                             #
    # ------------------------------------------------------------------ #
    def study_prompt_appendix(self) -> str | None:
        # TODO: return domain-specific text appended to the chat system prompt,
        # or None to omit.
        from template_problem.study_prompts import STUDY_PROMPT_APPENDIX  # TODO
        return STUDY_PROMPT_APPENDIX

    def config_derive_system_prompt(self) -> str:
        # TODO: instructions for the LLM when deriving a structured panel config
        # from the problem brief.
        from template_problem.study_prompts import CONFIG_DERIVE_SYSTEM_PROMPT  # TODO
        return CONFIG_DERIVE_SYSTEM_PROMPT.strip()

    # ------------------------------------------------------------------ #
    # Gemini structured-output schema                                      #
    # ------------------------------------------------------------------ #
    def panel_patch_response_json_schema(self) -> dict:
        # TODO: return the Gemini response_json_schema for a { "problem": ... } patch.
        from template_problem.panel_schema import panel_patch_response_json_schema  # TODO
        return panel_patch_response_json_schema()

    # ------------------------------------------------------------------ #
    # Companion fields — preserved when a weight key is locked             #
    # ------------------------------------------------------------------ #
    def locked_companion_fields(self) -> dict[str, str]:
        # TODO: return { weight_key: companion_field_name } for any weights
        # whose companion data (e.g. a list field) must be preserved when locked.
        # Return {} if no such coupling exists.
        return {}

    # ------------------------------------------------------------------ #
    # Starter config — pushed by researcher at session start               #
    # ------------------------------------------------------------------ #
    def mediocre_participant_starter_config(self) -> dict:
        # TODO: return a deliberately sparse starting config.  Should leave
        # obvious room for improvement to encourage participant exploration.
        return deepcopy({
            "problem": {
                "weights": {
                    "obj_a": 1.0,
                },
                "algorithm": "GA",
                "epochs": 24,
                "pop_size": 16,
                "random_seed": 42,
            }
        })

    # ------------------------------------------------------------------ #
    # Problem brief template fields                                        #
    # ------------------------------------------------------------------ #
    def problem_brief_template_fields(self) -> dict[str, str]:
        # TODO: return solver_scope / backend_template values for new sessions.
        return {
            "solver_scope": "general_metaheuristic_translation",
            "backend_template": "template_problem",  # TODO: rename
        }

    def default_problem_brief_system_items(self) -> list[dict[str, Any]]:
        # TODO: return system-level items inserted into a new session's brief.
        # These describe the backend to the LLM without exposing the domain name.
        return [
            {
                "id": "system-backend-template",
                "text": "Current backend template uses a [TODO: describe the problem schema here].",
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
        return f"Run #{session_run_number} finished — cost {cost:.2f}."


STUDY_PORT = TemplateProblemPort()
