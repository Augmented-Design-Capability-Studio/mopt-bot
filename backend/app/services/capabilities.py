from __future__ import annotations

from app.algorithm_catalog import ALLOWED_ALGORITHM_PARAMS
from app.problems.registry import get_study_port
from app.services.chat_context_policy import ContextTemperature

_ALGO_FAMILY_MAP: dict[str, str] = {
    "GA": "evolutionary search",
    "PSO": "swarm search",
    "SA": "annealing-based search",
    "SwarmSA": "annealing-based swarm search",
    "ACOR": "ant-colony search",
}


def _algorithms_section(*, mention_mealpy: bool) -> str:
    families = [_ALGO_FAMILY_MAP.get(name, "stochastic search") for name in ALLOWED_ALGORITHM_PARAMS.keys()]
    deduped = list(dict.fromkeys(families))
    prefix = "Solver families available"
    if mention_mealpy:
        prefix += " (powered by MEALpy)"
    return f"{prefix}: " + ", ".join(deduped) + "."


def _goal_terms_section(test_problem_id: str | None) -> str:
    defs = get_study_port(test_problem_id).meta().weight_definitions
    if not defs:
        return "Goal terms can be tuned to shift optimization priorities."
    rows: list[str] = []
    for item in defs:
        direction = "reduce" if str(item.direction or "minimize").strip().lower() != "maximize" else "increase"
        rows.append(f"- {item.label}: {item.description} Higher emphasis pushes the solver to {direction} this term.")
    return "Goal terms you can adjust:\n" + "\n".join(rows)


def _visualizations_section(test_problem_id: str | None) -> str:
    visuals = get_study_port(test_problem_id).visualization_capabilities()
    if not visuals:
        return "Post-run visual summaries are available."
    return "Participant-visible post-run views:\n" + "\n".join(f"- {v}" for v in visuals)


def build_capabilities_block(
    *,
    test_problem_id: str | None,
    mention_mealpy: bool,
    temperature: ContextTemperature,
) -> str:
    if temperature == "cold":
        return "\n\n".join(
            [
                "Capabilities",
                _algorithms_section(mention_mealpy=mention_mealpy),
                "I can help translate business goals into optimization priorities, constraints, and run settings.",
                "Once you share concrete task details, I can recommend targeted tuning and explain expected trade-offs.",
            ]
        )
    return "\n\n".join(
        [
            "Capabilities",
            _algorithms_section(mention_mealpy=mention_mealpy),
            _goal_terms_section(test_problem_id),
            _visualizations_section(test_problem_id),
        ]
    )
