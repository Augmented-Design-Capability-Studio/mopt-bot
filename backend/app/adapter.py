"""
Backward-compatible re-exports for VRPTW study bridge.

Dispatch for multi-problem sessions uses ``app.problems.registry.get_study_port``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.problems.exceptions import RunCancelled

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VRPTW_ROOT = (_REPO_ROOT / "vrptw_problem").resolve()
_s = str(_VRPTW_ROOT)
if _s not in sys.path:
    sys.path.insert(0, _s)

import vrptw_study_bridge as _bridge

# Re-export symbols used by tests and legacy imports
WEIGHT_ALIASES = _bridge.WEIGHT_ALIASES
WEIGHT_ALIAS_REVERSE = _bridge.WEIGHT_ALIAS_REVERSE
ensure_vrptw_on_path = _bridge.ensure_vrptw_on_path
neutral_violations = _bridge.neutral_violations
parse_problem_config = _bridge.parse_problem_config
run_evaluate_routes = _bridge.run_evaluate_routes
run_optimize = _bridge.run_optimize
routes_to_neutral = _bridge.routes_to_neutral
sanitize_panel_weights = _bridge.sanitize_panel_weights
solve_request_to_result = _bridge.solve_request_to_result
translate_weights = _bridge.translate_weights
translate_weights_strict = _bridge.translate_weights_strict

__all__ = [
    "RunCancelled",
    "WEIGHT_ALIASES",
    "WEIGHT_ALIAS_REVERSE",
    "ensure_vrptw_on_path",
    "neutral_violations",
    "parse_problem_config",
    "run_evaluate_routes",
    "run_optimize",
    "routes_to_neutral",
    "sanitize_panel_weights",
    "solve_request_to_result",
    "translate_weights",
    "translate_weights_strict",
]
