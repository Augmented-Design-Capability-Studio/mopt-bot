from vrptw_problem.encoder import VECTOR_LEN, encode_greedy_solution
from vrptw_problem.orders import get_orders


def test_encode_greedy_solution_default_orders_does_not_raise():
    orders = get_orders(seed=None)

    vec = encode_greedy_solution(orders)

    assert len(vec) == VECTOR_LEN
