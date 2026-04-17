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
    # The weight key whose display is conditional on driver_preferences being non-empty (None = no such key).
    worker_preference_key: str | None = None

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
        }
