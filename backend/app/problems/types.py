from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WeightDefinition:
    """One tunable objective/penalty term in the participant panel."""

    key: str
    label: str
    description: str = ""
    direction: str = "minimize"  # "minimize" (penalty/cost) | "maximize" (benefit, negated internally)


@dataclass
class TestProblemMeta:
    """JSON-serializable metadata for GET /meta/test-problems and the participant UI."""

    id: str
    label: str
    weight_definitions: list[WeightDefinition] = field(default_factory=list)
    extension_ui: str = "none"
    visualization_presets: list[str] = field(default_factory=list)
    primary_visualization: str | None = None
    # Ordered weight keys used for the agile gate check (subset/superset of weight_definitions).
    # If empty, the gate falls back to problem-agnostic any-weight logic.
    weight_display_keys: list[str] = field(default_factory=list)
    # Singular legacy convenience field — kept for back-compat with frontend
    # extras panels that need to know which weight key has the worker-pref UI.
    # When more than one companion-required goal term exists,
    # ``gate_conditional_companions`` is the authoritative map.
    worker_preference_key: str | None = None
    # Map of goal-term key → companion panel-field name. Mirrors the port's
    # ``gate_conditional_companions()``; consumed by the frontend gate.
    gate_conditional_companions: dict[str, str] = field(default_factory=dict)

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "weight_definitions": [
                {"key": w.key, "label": w.label, "description": w.description or None, "direction": w.direction}
                for w in self.weight_definitions
            ],
            "extension_ui": self.extension_ui,
            "visualization_presets": list(self.visualization_presets),
            "primary_visualization": self.primary_visualization,
            "weight_display_keys": list(self.weight_display_keys),
            "worker_preference_key": self.worker_preference_key,
            "gate_conditional_companions": dict(self.gate_conditional_companions),
        }
