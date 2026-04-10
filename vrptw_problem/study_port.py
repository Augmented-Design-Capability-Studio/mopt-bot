"""Backward-compatible re-exports. Prefer ``vrptw_study_meta`` / ``vrptw_study_port``."""

from __future__ import annotations

from vrptw_brief_seed import derive_problem_panel_from_brief
from vrptw_study_meta import (
    VRPTW_WEIGHT_DEFINITIONS,
    weight_item_labels,
    weight_slot_markers,
)

__all__ = [
    "VRPTW_WEIGHT_DEFINITIONS",
    "derive_problem_panel_from_brief",
    "weight_item_labels",
    "weight_slot_markers",
]
