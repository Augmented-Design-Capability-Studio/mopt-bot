"""Fast smoke tests for the toy knapsack package (domain + MEALpy when installed)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def knapsack_path_first():
    """Temporarily prefer knapsack_problem on sys.path and restore shadowed `evaluator`/`instance`."""
    before_path = list(sys.path)
    saved_evaluator = sys.modules.pop("evaluator", None)
    saved_instance = sys.modules.pop("instance", None)
    sys.path.insert(0, str(ROOT))
    yield
    sys.path[:] = before_path
    if saved_evaluator is not None:
        sys.modules["evaluator"] = saved_evaluator
    else:
        sys.modules.pop("evaluator", None)
    if saved_instance is not None:
        sys.modules["instance"] = saved_instance
    else:
        sys.modules.pop("instance", None)


def test_get_items_deterministic(knapsack_path_first):
    from knapsack_problem.instance import get_items

    a, ca = get_items(42)
    b, cb = get_items(42)
    assert ca == cb == 50
    assert len(a) == len(b) == 22
    assert a[3].value == b[3].value


def test_mealpy_ga_smoke(knapsack_path_first):
    pytest.importorskip("mealpy")
    import importlib.util

    from knapsack_problem.instance import get_items

    path = ROOT / "mealpy_solve.py"
    spec = importlib.util.spec_from_file_location("_knapsack_mealpy_solve_testonly", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    solve = mod.solve

    items, cap = get_items(0)
    cost, sol, conv, runtime, algo = solve(
        items,
        cap,
        {"value_emphasis": 1.0, "capacity_overflow": 10.0},
        True,
        "GA",
        None,
        4,
        12,
        123,
        False,
        20,
        1e-4,
        cancel_event=None,
    )
    assert algo == "GA"
    assert isinstance(cost, float)
    assert sol.shape[0] == len(items)
    assert runtime >= 0
    assert isinstance(conv, list)
