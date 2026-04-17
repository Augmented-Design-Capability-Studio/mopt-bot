from __future__ import annotations

from typing import Any, Protocol

from app.problems.types import TestProblemMeta, WeightDefinition


class StudyProblemPort(Protocol):
    """Backend integration surface for one metaheuristic benchmark."""

    id: str
    label: str

    def meta(self) -> TestProblemMeta: ...

    def sanitize_panel_config(self, panel_config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Deep-copy safe sanitize of panel_config (typically problem.weights + algorithm_params)."""

    def parse_problem_config(self, raw: dict[str, Any]) -> dict[str, Any]: ...

    def solve_request_to_result(
        self,
        body: dict[str, Any],
        timeout_sec: float,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        """Same contract as historical solve_request_to_result (optimize / evaluate)."""

    def derive_problem_panel_from_brief(self, problem_brief: dict[str, Any]) -> dict[str, Any] | None: ...

    def weight_item_labels(self) -> dict[str, str]:
        """Human labels for problem_brief / panel sync (goal term keys)."""

    def weight_slot_markers(self) -> dict[str, tuple[str, ...]]:
        """Substrings for atomizing brief lines into weight slots."""

    def weight_display_keys(self) -> list[str]:
        """Ordered weight keys used for the agile-mode gate check and config-panel display order.

        Keys that appear in the saved panel weights and in this list count toward the 'at least one
        goal term' requirement for agile optimization readiness.  The list should exclude purely
        parametric keys (e.g. VRPTW ``waiting_time`` which is threshold-driven) that should not
        independently satisfy the gate.  If the list is empty the gate falls back to any-weight
        logic (same as demo mode).
        """

    def worker_preference_key(self) -> str | None:
        """Weight key whose UI block is shown conditionally on driver_preferences being non-empty.

        Returns None if the problem has no such concept (e.g. knapsack).
        VRPTW returns ``"worker_preference"``.
        """

    def study_prompt_appendix(self) -> str | None:
        """Extra structured-prompt text for the study chat model (problem-specific)."""

    def config_derive_system_prompt(self) -> str:
        """System instructions for LLM structured derivation of ``problem`` from the brief."""

    def panel_patch_response_json_schema(self) -> dict[str, Any]:
        """Gemini ``response_json_schema`` for a ``{ "problem": ... }`` object."""

    def default_problem_brief_system_items(self) -> list[dict[str, Any]]:
        """Optional system items inserted into default_problem_brief for this problem."""

    def locked_companion_fields(self) -> dict[str, str]:
        """Map of weight key → companion field preserved when that key is locked.

        When a weight key is in ``locked_goal_terms``, the corresponding companion
        field (if any) should also be copied from the current config into the derived
        config so the lock is effective end-to-end.

        Return an empty dict for problems without weight-companion coupling.
        Example: VRPTW returns ``{"worker_preference": "driver_preferences"}``.
        """

    def mediocre_participant_starter_config(self) -> dict:
        """Return a deliberately sparse panel config for new study sessions.

        Should leave obvious room for improvement so participants can explore
        meaningful changes through chat.  Returned dict is a deep-copy (safe to mutate).
        """

    def problem_brief_template_fields(self) -> dict[str, str]:
        """solver_scope, backend_template, etc. for new sessions."""
