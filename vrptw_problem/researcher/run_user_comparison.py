"""
Run optimizer for each sample user config and report official evaluation.

Uses the same vehicles, orders, and traffic for everyone. Each user's
objective function (from their config) drives the optimizer. The official
evaluator then scores how well each solution performs on the canonical
objective and constraint satisfaction.

Run from vrptw_problem/: python -m researcher.run_user_comparison
Or: cd vrptw_problem && python -m researcher.run_user_comparison
"""

import sys
from pathlib import Path

# Add vrptw_problem to path so we can import evaluator, orders, etc.
_SCRIPT_DIR = Path(__file__).resolve().parent
_VRPTW_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_VRPTW_ROOT))

from optimizer import QuickBiteOptimizer
from user_input import load_user_input
from researcher.official_evaluator import (
    full_official_evaluation,
    print_official_report,
    print_cost_breakdown_comparison,
)
from researcher.comparison_viz import save_comparison_figures
from orders import get_orders

DATA_DIR = _VRPTW_ROOT / "data"
OUTPUT_DIR = _SCRIPT_DIR / "output"
USER_CONFIGS = [
    ("Novice", DATA_DIR / "user_novice.json"),
    ("Intermediate", DATA_DIR / "user_intermediate.json"),
    ("Expert", DATA_DIR / "user_expert.json"),
    ("Expert (no lock)", DATA_DIR / "user_expert_no_lock.json"),
]


def main() -> None:
    orders = get_orders(seed=None)
    results: list[tuple[str, object, dict]] = []

    for label, config_path in USER_CONFIGS:
        if not config_path.exists():
            print(f"[SKIP] {label}: {config_path} not found")
            continue

        user_config = load_user_input(config_path)
        optimizer = QuickBiteOptimizer(user_config_path=config_path)

        print(f"\n>>> Running optimizer for {label}...")
        algorithm = user_config.get("algorithm", "GA")
        algorithm_params = user_config.get("algorithm_params")
        epochs = user_config.get("epochs", 80)
        pop_size = user_config.get("pop_size", 60)
        result = optimizer.solve(
            algorithm=algorithm,
            params=algorithm_params,
            epochs=epochs,
            pop_size=pop_size,
        )

        # Build full user_config for official evaluator (include inferred constraints)
        full_config = load_user_input(config_path)

        eval_result = full_official_evaluation(
            routes=result.routes,
            user_config=full_config,
            orders=orders,
            random_seed=42,
        )

        print_official_report(eval_result, user_label=label)
        results.append((label, result, eval_result))

    # Cost breakdown: Expert vs Intermediate
    if results:
        print_cost_breakdown_comparison([(label, ev) for label, _, ev in results])

    # Visual comparison: Gantt charts + route maps
    if results:
        try:
            paths = save_comparison_figures(results, output_dir=OUTPUT_DIR)
            print(f"\n[Visualization] Saved to {OUTPUT_DIR}:")
            for p in paths:
                print(f"  {p.name}")
        except Exception as e:
            print(f"\n[Visualization] Failed: {e}")
            print("  Install matplotlib: pip install matplotlib")

    print("\n[Done] All users compared.")
    print("\nSummary: Lower Official Cost = better solution quality under canonical objective.")


if __name__ == "__main__":
    main()
