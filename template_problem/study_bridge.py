"""Neutral JSON ↔ internal translation layer for the template problem.

Translates the panel-facing weight aliases to internal solver keys and
wraps the optimizer.  Only this file should import from optimizer.py so
study_port.py stays thin and testable.
"""

from __future__ import annotations

from typing import Any, Callable


def parse_problem_config(
    raw: dict[str, Any],
    filter_algorithm_params: Callable | None = None,
) -> dict[str, Any]:
    """Validate and normalise the panel problem JSON into solver kwargs.

    Args:
        raw: The ``problem`` sub-dict from the panel config.
        filter_algorithm_params: Callable from app.algorithm_catalog for stripping
                                 unsupported hyperparameters.

    Returns:
        A solver-ready config dict.  Raise ValueError for unrecoverable input errors.

    TODO: extract weights, algorithm, epochs, pop_size, random_seed, algorithm_params
    and translate weight aliases to internal solver keys if they differ.
    """
    raise NotImplementedError("TODO: implement parse_problem_config()")


def solve_request_to_result(
    body: dict[str, Any],
    timeout_sec: float,
    cancel_event: Any | None = None,
    filter_algorithm_params: Callable | None = None,
) -> dict[str, Any]:
    """Entry point called by study_port.solve_request_to_result().

    Args:
        body: Full request body (type, problem, optional extra fields).
        timeout_sec: Wall-clock timeout for the solver.
        cancel_event: Cooperative cancel event.
        filter_algorithm_params: Callable from app.algorithm_catalog.

    Returns:
        Result dict compatible with RunOut.result (cost, violations, metrics, schedule, …).
    """
    from template_problem.optimizer import solve, OptimizationCancelled  # noqa: F401

    problem_raw = body.get("problem") or body
    config = parse_problem_config(problem_raw, filter_algorithm_params=filter_algorithm_params)
    # TODO: call solve(config, timeout_sec, cancel_event) and format the output.
    raise NotImplementedError("TODO: implement solve_request_to_result()")
