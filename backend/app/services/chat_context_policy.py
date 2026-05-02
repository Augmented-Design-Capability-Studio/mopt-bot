from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ContextTemperature = Literal["cold", "warm", "hot"]
ExecutionMode = Literal["read_only_simulated", "propose_patch", "apply_patch"]


@dataclass(frozen=True)
class ChatContextProfile:
    temperature: ContextTemperature
    execution_mode: ExecutionMode = "read_only_simulated"


def _has_non_system_items(problem_brief: dict[str, Any] | None) -> bool:
    brief = problem_brief or {}
    items = brief.get("items") if isinstance(brief.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind in {"gathered", "assumption"} and str(item.get("text") or "").strip():
            return True
    return False


def _has_open_questions(problem_brief: dict[str, Any] | None) -> bool:
    brief = problem_brief or {}
    questions = brief.get("open_questions") if isinstance(brief.get("open_questions"), list) else []
    return len(questions) > 0


def _has_goal_summary(problem_brief: dict[str, Any] | None) -> bool:
    brief = problem_brief or {}
    return bool(str(brief.get("goal_summary") or "").strip())


def _has_saved_problem_config(current_panel: dict[str, Any] | None) -> bool:
    panel = current_panel or {}
    problem = panel.get("problem") if isinstance(panel.get("problem"), dict) else {}
    if not isinstance(problem, dict) or not problem:
        return False
    has_weights = isinstance(problem.get("weights"), dict) and bool(problem.get("weights"))
    has_algorithm = bool(str(problem.get("algorithm") or "").strip())
    return has_weights or has_algorithm


def resolve_context_profile(
    *,
    user_text: str,
    current_problem_brief: dict[str, Any] | None,
    current_panel: dict[str, Any] | None,
    recent_runs_summary: list[dict[str, Any]] | None,
    execution_mode: ExecutionMode = "read_only_simulated",
) -> ChatContextProfile:
    has_runs = bool(recent_runs_summary)
    has_goal_summary = _has_goal_summary(current_problem_brief)
    has_non_system_items = _has_non_system_items(current_problem_brief)
    has_questions = _has_open_questions(current_problem_brief)
    has_panel = _has_saved_problem_config(current_panel)
    _ = user_text

    if has_runs or has_panel:
        return ChatContextProfile(temperature="hot", execution_mode=execution_mode)
    if has_goal_summary or has_non_system_items or has_questions:
        return ChatContextProfile(temperature="warm", execution_mode=execution_mode)
    return ChatContextProfile(temperature="cold", execution_mode=execution_mode)


def build_temperature_guardrails_block(temperature: ContextTemperature) -> str:
    if temperature == "cold":
        return (
            "Conversation temperature: COLD\n"
            "- Stay problem-agnostic and domain-neutral.\n"
            "- Do not leak benchmark/module identity or hidden implementation details.\n"
            "- Explain capabilities in general terms and ask one practical clarification when needed."
        )
    if temperature == "warm":
        return (
            "Conversation temperature: WARM\n"
            "- You may use active-module user-facing docs and visible session context.\n"
            "- Keep internal aliases, hidden keys, and benchmark internals undisclosed.\n"
            "- Keep explanations concise and business-friendly."
        )
    return (
        "Conversation temperature: HOT\n"
        "- Ground responses in visible config/run context and active-module user docs.\n"
        "- Give concrete next-step guidance while preserving hidden internals.\n"
        "- Keep replies short and operationally focused."
    )


def build_execution_mode_block(execution_mode: ExecutionMode) -> str:
    if execution_mode == "apply_patch":
        return (
            "Execution capability mode: APPLY_PATCH\n"
            "- You can propose and apply implementation edits when asked."
        )
    if execution_mode == "propose_patch":
        return (
            "Execution capability mode: PROPOSE_PATCH\n"
            "- You can draft implementation changes but do not claim they were applied."
        )
    return (
        "Execution capability mode: READ_ONLY_SIMULATED\n"
        "- Maintain the persona of a flexible optimization agent. When discussing what you"
        " 'built' or 'implemented', use plain-language engineering descriptions without"
        " revealing internal configuration details or library names. Do not output source"
        " code or claim you modified files; redirect to behavior and outcomes instead."
    )
