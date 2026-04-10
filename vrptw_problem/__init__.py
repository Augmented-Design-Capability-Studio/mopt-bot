"""QuickBite Fleet Scheduling - VRPTW metaheuristic solver."""

try:
    from .traffic_api import get_travel_time, ZONE_NAMES
    from .orders import Order, generate_orders, get_orders, print_order_table
    from .encoder import decode_solution, encode_random_solution
    from .evaluator import evaluate_solution, simulate_routes, VEHICLES
    from .optimizer import QuickBiteOptimizer, SolverConfig, SolveResult
    from .reporter import print_report, get_gantt_data
    from .user_input import DEFAULT_WEIGHTS, load_user_input
except ImportError:  # script/sys.path or pytest import without package parent
    from traffic_api import get_travel_time, ZONE_NAMES
    from orders import Order, generate_orders, get_orders, print_order_table
    from encoder import decode_solution, encode_random_solution
    from evaluator import evaluate_solution, simulate_routes, VEHICLES
    from optimizer import QuickBiteOptimizer, SolverConfig, SolveResult
    from reporter import print_report, get_gantt_data
    from user_input import DEFAULT_WEIGHTS, load_user_input

__all__ = [
    "get_travel_time",
    "ZONE_NAMES",
    "Order",
    "generate_orders",
    "get_orders",
    "print_order_table",
    "decode_solution",
    "encode_random_solution",
    "evaluate_solution",
    "simulate_routes",
    "VEHICLES",
    "QuickBiteOptimizer",
    "SolverConfig",
    "SolveResult",
    "print_report",
    "get_gantt_data",
    "DEFAULT_WEIGHTS",
    "load_user_input",
]
