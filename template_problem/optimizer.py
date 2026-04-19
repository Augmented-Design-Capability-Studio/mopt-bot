"""Solver wrapper for the template problem.

Wraps MEALpy (or another solver) and exposes a single solve() function that
the study bridge calls.  Cooperative cancellation is handled via cancel_event.
"""

from __future__ import annotations

from typing import Any


class OptimizationCancelled(Exception):
    """Raised when the solver detects a cancellation signal."""


def solve(
    problem_config: dict[str, Any],
    timeout_sec: float = 120.0,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    """Run the solver and return a result dict.

    Args:
        problem_config: Parsed problem config from study_bridge.parse_problem_config().
        timeout_sec: Wall-clock timeout; solver should respect this.
        cancel_event: Threading event; poll .is_set() in the objective function and
                      raise OptimizationCancelled when it fires.

    Returns:
        A result dict compatible with the shape returned by the existing solve ports.
        Must include at minimum: ``cost`` (float), ``violations`` (dict), ``metrics`` (dict).

    TODO:
        1. Import and configure your MEALpy problem class.
        2. In the objective function, check: if cancel_event and cancel_event.is_set(): raise OptimizationCancelled
        3. Run the solver and collect the best solution.
        4. Call the evaluator to compute cost + violations + metrics.
        5. Build and return the result payload.
    """
    raise NotImplementedError("TODO: implement solve()")
