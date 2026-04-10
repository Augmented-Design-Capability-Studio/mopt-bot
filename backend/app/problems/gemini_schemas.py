"""Gemini JSON-schema helpers.

Benchmark-specific panel patch schemas live under each ``*_problem/`` tree
(``knapsack_panel_schema``, ``vrptw_panel_schema``). This module keeps shared
fragments and backward-compatible re-exports.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.problems.schema_shared import (
    ALGORITHM_PARAMS_SCHEMA,
    wrap_panel_patch_schema,
)

__all__ = [
    "ALGORITHM_PARAMS_SCHEMA",
    "wrap_panel_patch_schema",
    "knapsack_panel_patch_response_json_schema",
    "vrptw_panel_patch_response_json_schema",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ensure_domain_path(dirname: str) -> None:
    s = str((_repo_root() / dirname).resolve())
    if s not in sys.path:
        sys.path.insert(0, s)


def knapsack_panel_patch_response_json_schema() -> dict[str, Any]:
    _ensure_domain_path("knapsack_problem")
    from knapsack_panel_schema import knapsack_panel_patch_response_json_schema as _fn

    return _fn()


def vrptw_panel_patch_response_json_schema() -> dict[str, Any]:
    _ensure_domain_path("vrptw_problem")
    from vrptw_panel_schema import vrptw_panel_patch_response_json_schema as _fn

    return _fn()
