"""
QuickBite VRPTW — Basic demo: run all 5 algorithms and compare results.

Run from vrptw_problem/: python basic_demo.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vrptw_problem.orders import get_orders, print_order_table
from vrptw_problem.optimizer import QuickBiteOptimizer
from vrptw_problem.reporter import print_report
from vrptw_problem.evaluator import VEHICLES


def main() -> None:
    # Print order table at startup
    orders = get_orders(seed=None)
    print_order_table(orders)

    optimizer = QuickBiteOptimizer(seed=42)
    results = {}
    algorithms = ["GA", "PSO", "SA", "SwarmSA", "ACOR"]

    for algo in algorithms:
        result = optimizer.solve(
            algorithm=algo,
            epochs=100,
            pop_size=50,
        )
        results[algo] = result

    # Validation (sanity checks)
    all_orders = set(range(30))
    for algo, r in results.items():
        covered = set()
        for route in r.routes:
            for o in route:
                covered.add(o)
        assert covered == all_orders, f"{algo}: Not all 30 orders covered (got {len(covered)})"
        assert len(covered) == 30, f"{algo}: Duplicate or missing orders"

        shift_durations = r.metrics.get("shift_durations", [])
        for i, sd in enumerate(shift_durations):
            if sd > 8 * 60:
                print(f"  [WARN] {algo}: Vehicle {i} exceeds 8h (got {sd/60:.1f}h)")
        for i, (vehicle, route) in enumerate(zip(VEHICLES, r.routes)):
            load = sum(orders[o].size for o in route)
            if load > vehicle.capacity:
                print(f"  [WARN] {algo}: Vehicle {i} capacity exceeded ({load}/{vehicle.capacity})")

    # Comparison table
    print("\n" + "=" * 60)
    print("  Algorithm | Cost   | Runtime | TW Violations | Workload Var")
    print("-" * 60)
    for algo in algorithms:
        r = results[algo]
        tw = r.metrics.get("tw_violation_count", 0)
        var = r.metrics.get("workload_variance", 0)
        print(f"  {algo:<9} | {r.best_cost:6.1f} | {r.runtime:5.1f}s  | {tw:14} | {var:.2f}")
    print("=" * 60)

    # Print detailed report for best result
    best_algo = min(results, key=lambda a: results[a].best_cost)
    print_report(results[best_algo])


if __name__ == "__main__":
    main()
