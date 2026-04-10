"""
QuickBite VRPTW — Visualize algorithm convergence (fair comparison).

Uses official (canonical) weights for a standard convergence check. Runs GA, PSO, SA,
SwarmSA, ACOR with a fixed time budget. Plots best cost vs runtime.

Run from vrptw_problem/: python -m researcher.visualize_convergence
"""

import sys
from pathlib import Path

_VRPTW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VRPTW_ROOT))

from optimizer import QuickBiteOptimizer
from user_input import (
    DEFAULT_WEIGHTS,
    DEFAULT_DRIVER_PREFERENCES,
    SHIFT_HARD_PENALTY,
)

# Fair comparison: fixed time budget (seconds) per algorithm
TIME_BUDGET = 120
# Epoch cap: others stop on time; SA stops at max epochs (no time limit)
MAX_EPOCHS = 100_000

POP_SIZE = 150
ALGORITHMS = ["GA", "PSO", "SA", "SwarmSA", "ACOR"]
COLORS = {"GA": "#e41a1c", "PSO": "#377eb8", "SA": "#4daf4a", "SwarmSA": "#ff7f00", "ACOR": "#984ea3"}


def evals_per_epoch(algo: str, pop_size: int, params: dict | None) -> int:
    """Approximate fitness evaluations per epoch for each algorithm."""
    params = params or {}
    if algo in ("GA", "PSO"):
        return pop_size
    if algo == "SA":
        return 1
    if algo == "SwarmSA":
        ms = params.get("max_sub_iter", 5)
        mc = params.get("move_count", 5)
        return pop_size * ms * mc
    if algo == "ACOR":
        return params.get("sample_count", 25)
    return pop_size


def estimate_total_evals(result, evals_pe: int) -> int:
    """Estimate total fitness evaluations from convergence history."""
    n = len(result.convergence) if result.convergence else 0
    return n * evals_pe


def convergence_to_time_series(result) -> tuple[list[float], list[float]]:
    """Convert convergence history to (times, costs). X = cumulative runtime in seconds."""
    conv = result.convergence
    if not conv:
        return [], []

    if result.epoch_times and len(result.epoch_times) == len(conv):
        # Use actual per-epoch times
        cum = 0.0
        times = []
        for t in result.epoch_times:
            cum += t
            times.append(cum)
    else:
        # Approximate: assume uniform time per epoch
        times = [(i + 1) / len(conv) * result.runtime for i in range(len(conv))]
    return times, conv


def main() -> None:
    params = {}
    optimizer = QuickBiteOptimizer(
        weights=DEFAULT_WEIGHTS,
        driver_preferences=DEFAULT_DRIVER_PREFERENCES,
        shift_hard_penalty=SHIFT_HARD_PENALTY,
        locked={},
        user_config_path=None,
    )

    print("Fair comparison: official weights, fixed time budget (SA stops at max epochs)")
    print(f"  Time budget: {TIME_BUDGET}s, pop_size: {POP_SIZE}")
    print()

    results = {}
    for algo in ALGORITHMS:
        if algo == "SA":
            termination = None  # SA stops at max epochs
            print(f"  {algo} (max {MAX_EPOCHS} epochs)...", end=" ", flush=True)
        else:
            termination = {"max_time": TIME_BUDGET}
            print(f"  {algo} (max {TIME_BUDGET}s)...", end=" ", flush=True)
        result = optimizer.solve(
            algorithm=algo,
            params=params,
            epochs=MAX_EPOCHS,
            pop_size=POP_SIZE,
            termination=termination,
        )
        results[algo] = result
        evals_pe = evals_per_epoch(algo, POP_SIZE, params)
        est_evals = estimate_total_evals(result, evals_pe)
        print(f"cost={result.best_cost:.0f}, {result.runtime:.1f}s, ~{est_evals:,} evals")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n[SKIP] matplotlib not installed — run: pip install matplotlib")
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    for algo in ALGORITHMS:
        r = results[algo]
        times, costs = convergence_to_time_series(r)
        if times and costs:
            ax.plot(times, costs, color=COLORS.get(algo, "gray"), label=algo, linewidth=1.5)
        else:
            ax.axhline(r.best_cost, color=COLORS.get(algo, "gray"),
                       label=f"{algo} (no history)", linestyle="--", linewidth=1)

    ax.set_xlabel("Runtime (seconds)")
    ax.set_ylabel("Best cost (official weights)")
    ax.set_title(f"Algorithm convergence (GA/PSO/SwarmSA/ACOR: {TIME_BUDGET}s, SA: max epochs)")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    ax.set_xlim(0, TIME_BUDGET)

    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "convergence.png"
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"\n[Saved] {out_path}")

    print("\n" + "=" * 70)
    print("  Algorithm | Best Cost | Runtime (s) | Est. Evals")
    print("-" * 70)
    for algo in ALGORITHMS:
        r = results[algo]
        evals_pe = evals_per_epoch(algo, POP_SIZE, params)
        est_evals = estimate_total_evals(r, evals_pe)
        print(f"  {algo:<9} | {r.best_cost:9.1f} | {r.runtime:11.1f} | {est_evals:>10,}")
    print("=" * 70)


if __name__ == "__main__":
    main()
