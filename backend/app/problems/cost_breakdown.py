"""Shared per-goal-term cost-contribution builder.

Each problem only needs to declare a tuple of :class:`CostTermSpec` rows that
say "this submitted alias maps to this weight key × this metric key" — the
actual list-construction, type-coercion, and submitted-alias filter live here
so problem modules stay minimal and consistent.

The frontend renders the result via ``GoalTermCostBreakdown.tsx``; only terms
the participant's config submitted are emitted (filter is applied here on the
backend so the participant never sees terms they didn't configure).
"""

from __future__ import annotations

from typing import Any, Iterable, NamedTuple


class CostTermSpec(NamedTuple):
    """Static descriptor for one term in a problem's cost formula.

    Attributes:
        key: Participant-facing alias matching what they submit in
            ``problem.weights`` (e.g. ``"travel_time"``, ``"value_emphasis"``).
            Filter lookup uses this; the frontend renders cards keyed by it.
        label: Human label shown on the breakdown card.
        weight_key: Key in the runtime weights dict the solver evaluated against
            (often the same as ``key``; differs for VRPTW which uses ``w1``..``w8``
            internally).
        metric_key: Key in the metrics dict that the weight multiplies.
        metric_unit: Short unit string for display ("min", "units", ""…).
    """

    key: str
    label: str
    weight_key: str
    metric_key: str
    metric_unit: str


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def build_goal_term_contributions(
    specs: Iterable[CostTermSpec],
    submitted_aliases: Iterable[str],
    weights: dict[str, Any],
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build per-term contribution rows filtered to the participant's submitted aliases.

    Args:
        specs: Per-problem cost-term descriptors.
        submitted_aliases: Aliases actually present in the run's submitted weights.
            Other terms are omitted so participants never see goal terms they
            didn't configure.
        weights: Full weights dict the solver evaluated against.
        metrics: Raw metrics dict from the problem's evaluator.
    """
    submitted = {str(a) for a in submitted_aliases}
    out: list[dict[str, Any]] = []
    for spec in specs:
        if spec.key not in submitted:
            continue
        weight = _coerce_float(weights.get(spec.weight_key))
        metric_value = _coerce_float(metrics.get(spec.metric_key))
        out.append({
            "key": spec.key,
            "label": spec.label,
            "weight": weight,
            "metric_value": metric_value,
            "metric_unit": spec.metric_unit,
            "weighted_cost": weight * metric_value,
        })
    return out
