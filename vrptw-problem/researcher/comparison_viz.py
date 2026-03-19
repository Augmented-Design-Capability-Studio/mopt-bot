"""
Comparison visualization for QuickBite user study.

Combines Gantt charts and route maps from multiple user results
for side-by-side / stacked comparison.
"""

from pathlib import Path
from typing import Optional

from reporter import get_gantt_data
from visualization import plot_gantt, plot_route_map, save_result_figures
from orders import get_orders


def save_comparison_figures(
    results: list[tuple[str, object, dict]],
    output_dir: Optional[Path] = None,
    random_seed: int = 42,
) -> list[Path]:
    """
    Save per-user figures and combined comparison charts.

    results: list of (label, result, eval_result)
    output_dir: where to save. Default: researcher/output/
    Returns: list of saved file paths.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if output_dir is None:
        output_dir = Path(__file__).resolve().parent / "output"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    orders = get_orders(seed=None)
    saved: list[Path] = []

    # Per-user: Gantt + map (reuses user-facing save_result_figures)
    for label, result, _ in results:
        path = save_result_figures(
            result,
            output_dir / f"user_{label.lower()}.png",
            title=label,
            random_seed=random_seed,
        )
        saved.append(path)

    # Combined: route maps side by side
    n = len(results)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5))
    if n == 1:
        axes = [axes]
    for ax, (label, result, eval_result) in zip(axes, results):
        plot_route_map(
            result.routes, orders,
            title=f"{label}\nOfficial: {eval_result['official_cost']:.0f}",
            ax=ax,
        )
    fig.suptitle("Route comparison by user", fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()
    path = output_dir / "comparison_routes.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close()
    saved.append(path)

    # Combined: Gantt charts stacked
    fig, axes = plt.subplots(n, 1, figsize=(12, 3 * n), sharex=True)
    if n == 1:
        axes = [axes]
    for ax, (label, result, eval_result) in zip(axes, results):
        gantt_data = get_gantt_data(result, random_seed=random_seed)
        plot_gantt(
            gantt_data,
            title=f"{label} (official cost: {eval_result['official_cost']:.0f})",
            ax=ax,
            routes=result.routes,
            orders=orders,
            locked_assignments=getattr(result, "locked_assignments", None) or {},
            driver_preferences=getattr(result, "driver_preferences", None) or [],
            shift_durations=(result.metrics or {}).get("shift_durations"),
        )
    fig.suptitle("Gantt comparison by user", fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()
    path = output_dir / "comparison_gantt.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close()
    saved.append(path)

    return saved
