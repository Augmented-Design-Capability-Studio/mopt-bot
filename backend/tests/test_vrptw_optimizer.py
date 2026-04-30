from types import SimpleNamespace

import numpy as np

import vrptw_problem.optimizer as optimizer_module
from vrptw_problem.encoder import VECTOR_LEN
from vrptw_problem.optimizer import QuickBiteOptimizer


def test_quickbite_optimizer_uses_mealpy_starting_solutions(monkeypatch):
    captured_instances = []

    class FakeModel:
        def __init__(self, *args, **kwargs):
            self.last_kwargs = None
            captured_instances.append(self)

        def solve(self, problem, **kwargs):
            self.problem = problem
            self.last_kwargs = kwargs
            return SimpleNamespace(solution=np.zeros(VECTOR_LEN, dtype=float))

    monkeypatch.setattr(
        optimizer_module,
        "FloatVar",
        lambda lb, ub: SimpleNamespace(lb=np.asarray(lb), ub=np.asarray(ub)),
    )
    monkeypatch.setattr(optimizer_module, "GA", SimpleNamespace(BaseGA=FakeModel))
    monkeypatch.setattr(
        optimizer_module,
        "encode_greedy_solution",
        lambda orders, locked_assignments=None, rng=None: np.arange(VECTOR_LEN, dtype=float),
    )

    solver = QuickBiteOptimizer(seed=7)

    solver.solve(algorithm="GA", epochs=1, pop_size=5, use_greedy_init=True)

    assert len(captured_instances) == 1
    assert "starting_solutions" in captured_instances[0].last_kwargs
    assert "starting_positions" not in captured_instances[0].last_kwargs
    assert len(captured_instances[0].last_kwargs["starting_solutions"]) == 5


def test_quickbite_optimizer_merges_candidate_and_greedy_seeds(monkeypatch):
    captured_instances = []

    class FakeModel:
        def __init__(self, *args, **kwargs):
            self.last_kwargs = None
            captured_instances.append(self)

        def solve(self, problem, **kwargs):
            self.problem = problem
            self.last_kwargs = kwargs
            return SimpleNamespace(solution=np.zeros(VECTOR_LEN, dtype=float))

    monkeypatch.setattr(
        optimizer_module,
        "FloatVar",
        lambda lb, ub: SimpleNamespace(lb=np.asarray(lb), ub=np.asarray(ub)),
    )
    monkeypatch.setattr(optimizer_module, "GA", SimpleNamespace(BaseGA=FakeModel))
    monkeypatch.setattr(
        optimizer_module,
        "encode_greedy_solution",
        lambda orders, locked_assignments=None, rng=None: np.arange(VECTOR_LEN, dtype=float) + 10.0,
    )

    solver = QuickBiteOptimizer(seed=11)
    candidate = np.arange(VECTOR_LEN, dtype=float)
    solver.solve(
        algorithm="GA",
        epochs=1,
        pop_size=6,
        use_greedy_init=True,
        initial_solutions=[candidate],
    )

    assert len(captured_instances) == 1
    starts = captured_instances[0].last_kwargs["starting_solutions"]
    assert len(starts) == 6
    assert np.allclose(np.asarray(starts[0]), candidate)
