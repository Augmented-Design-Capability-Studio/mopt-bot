from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WeightDefinition:
    """One tunable objective/penalty term in the participant panel."""

    key: str
    label: str
    description: str = ""


@dataclass
class TestProblemMeta:
    """JSON-serializable metadata for GET /meta/test-problems and the participant UI."""

    id: str
    label: str
    weight_definitions: list[WeightDefinition] = field(default_factory=list)
    extension_ui: str = "none"
    visualization_presets: list[str] = field(default_factory=list)
    primary_visualization: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "weight_definitions": [
                {"key": w.key, "label": w.label, "description": w.description or None}
                for w in self.weight_definitions
            ],
            "extension_ui": self.extension_ui,
            "visualization_presets": list(self.visualization_presets),
            "primary_visualization": self.primary_visualization,
        }
