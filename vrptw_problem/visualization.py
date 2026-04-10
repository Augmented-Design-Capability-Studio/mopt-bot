"""
Visualization for QuickBite VRPTW: Gantt charts and route maps.

Useful for viewing optimization results. Color = driver; hatching = express/violation.
Optional: show locked assignments, driver preference indicators, shift-over markers.
"""

from pathlib import Path
from typing import Optional, Any

from vrptw_problem.reporter import get_gantt_data
from vrptw_problem.traffic_api import ZONE_NAMES
from vrptw_problem.vehicles import VEHICLES
from vrptw_problem.orders import get_orders, Order

# Fake 2D coordinates for zones (Depot center, A–E roughly by travel time)
ZONE_COORDS = {
    0: (0.0, 0.0),   # Depot
    1: (0.0, 1.0),   # A Riverside
    2: (0.95, 0.3),  # B Harbor
    3: (0.6, -0.8),  # C Uptown
    4: (-0.6, -0.8), # D Westgate
    5: (-0.95, 0.3), # E Northgate
}

VEHICLE_COLORS = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00"]


def _get_route_zone_sequence(routes: list[list[int]], orders: list[Order]) -> list[list[tuple[int, int]]]:
    """For each vehicle, return list of (order_idx, zone) in visit order. Includes depot start/end."""
    sequences = []
    for route in routes:
        seq = [(0, 0)]
        for o_idx in route:
            seq.append((o_idx, orders[o_idx].zone))
        seq.append((0, 0))
        sequences.append(seq)
    return sequences


def plot_gantt(
    gantt_data: list[dict],
    title: str = "QuickBite Routes",
    ax=None,
    routes: Optional[list[list[int]]] = None,
    orders: Optional[list[Order]] = None,
    locked_assignments: Optional[dict[int, int]] = None,
    driver_preferences: Optional[list[dict]] = None,
    shift_durations: Optional[list[float]] = None,
) -> None:
    """
    Plot a Gantt chart: time vs vehicle, one bar per visit.

    Color = driver. Hatching: Express = diagonal stripes, Violation = cross-hatch.
    If routes/orders: load/capacity, overflow tint.
    If locked_assignments, driver_preferences, shift_durations: constraint markers.
    gantt_data: from reporter.get_gantt_data(result)
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    import matplotlib.patheffects as pe

    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4))

    # Per-vehicle load and capacity (when routes/orders provided)
    load_cap: dict[int, tuple[int, int]] = {}
    if routes is not None and orders is not None:
        for vid, route in enumerate(routes):
            load = sum(orders[o_idx].size for o_idx in route)
            cap = VEHICLES[vid].capacity if vid < len(VEHICLES) else load
            load_cap[vid] = (load, cap)

    by_vehicle: dict[int, list[dict]] = {}
    for v in gantt_data:
        vid = v["vehicle_id"]
        if vid not in by_vehicle:
            by_vehicle[vid] = []
        by_vehicle[vid].append(v)

    y_pos = 0
    y_ticks = []
    y_labels = []
    label_colors = []

    for vid in sorted(by_vehicle.keys()):
        visits = by_vehicle[vid]
        name = visits[0]["vehicle_name"] if visits else f"V{vid}"
        if vid in load_cap:
            load, cap = load_cap[vid]
            y_labels.append(f"{name}  {load}/{cap}")
            label_colors.append("#c00" if load > cap else "black")
        else:
            y_labels.append(name)
            label_colors.append("black")

        overflow = vid in load_cap and load_cap[vid][0] > load_cap[vid][1]
        if overflow:
            ax.axhspan(y_pos - 0.55, y_pos + 0.55, color="#c00", alpha=0.12, zorder=0)

        y_ticks.append(y_pos)
        # Row suffix for shift_over_hours
        row_suffix = ""
        if shift_durations and vid < len(shift_durations):
            sd_h = shift_durations[vid] / 60.0  # shift_durations are minutes
            for r in (driver_preferences or []):
                rc = r.get("condition", "")
                if r.get("vehicle_idx") == vid and rc in (
                    "shift_over_hours", "shift_over_limit",
                ):
                    lim_h = (r.get("limit_minutes") or (r.get("hours", 6.5) * 60)) / 60.0
                    if sd_h > lim_h:
                        row_suffix = f" (>{lim_h:.1f}h)"
                    break

        for v in visits:
            start = v["arrival_time"] / 60
            duration = (v["departure_time"] - v["arrival_time"]) / 60
            color = VEHICLE_COLORS[vid % len(VEHICLE_COLORS)]
            hatch = ""
            if v.get("is_violation"):
                hatch = "xx"
            elif v.get("is_express"):
                hatch = "//"
            ax.barh(
                y_pos, duration, left=start, height=0.85,
                color=color, edgecolor="black", linewidth=0.5,
                hatch=hatch if hatch else None,
            )
            ax.axvline(v["window_open"] / 60, color="gray", alpha=0.3, linewidth=0.5)

            # Constraint markers (small text)
            locked = dict(locked_assignments or {})
            if locked and isinstance(next(iter(locked.keys())), str):
                locked = {int(k): int(v) for k, v in locked.items()}
            o_idx = v.get("order_idx", -1)
            is_locked = o_idx >= 0 and locked.get(o_idx) == vid
            zone = v.get("zone", "")
            is_zone_d = zone == "D" and any(
                r.get("vehicle_idx") == vid and r.get("condition") == "zone_d"
                for r in (driver_preferences or [])
            )
            is_express_pref = v.get("is_express") and any(
                r.get("vehicle_idx") == vid and r.get("condition") == "express_order"
                for r in (driver_preferences or [])
            )
            # Bar label: order number (no "O") + markers on new line
            order_id = v.get("order_id", "")
            order_num = order_id.lstrip("O") or order_id
            markers = []
            if is_locked:
                markers.append("L")
            if is_zone_d:
                markers.append("D")
            if is_express_pref:
                markers.append("E")
            label = order_num
            if markers:
                label = f"{order_num}\n{' '.join(markers)}" if order_num else " ".join(markers)
            if label and duration > 0.05:  # skip label on very narrow bars
                mid_x = start + duration / 2
                ax.text(mid_x, y_pos, label.strip(), ha="center", va="center",
                        fontsize=6, color="white", weight="bold",
                        path_effects=[pe.withStroke(linewidth=1, foreground="black")])

        if row_suffix:
            y_labels[-1] = y_labels[-1] + row_suffix
        y_pos += 1.2

    ax.set_yticks(y_ticks)
    ax.set_yticklabels(y_labels)
    for t, c in zip(ax.get_yticklabels(), label_colors):
        t.set_color(c)
    ax.set_xlabel("Time (hours since midnight)")
    ax.set_title(title)
    ax.set_xlim(7.5, 18)

    legend_elements = [
        Patch(facecolor=VEHICLE_COLORS[i], edgecolor="black", label=VEHICLES[i].name)
        for i in range(min(len(VEHICLES), len(VEHICLE_COLORS)))
    ]
    legend_elements.extend([
        Patch(facecolor="white", edgecolor="black", hatch="//", label="Express"),
        Patch(facecolor="white", edgecolor="black", hatch="xx", label="TW violation"),
        Patch(facecolor="#c00", edgecolor="none", alpha=0.3, label="Capacity overflow"),
    ])
    has_constraints = bool(locked_assignments or driver_preferences)
    if has_constraints:
        from matplotlib.lines import Line2D
        legend_elements.append(
            Line2D([0], [0], color="none", label="L=Locked D=ZoneD E=Express")
        )
    ax.legend(handles=legend_elements, loc="upper right", fontsize=8)


def plot_route_map(
    routes: list[list[int]],
    orders: list[Order],
    title: str = "Route Map",
    ax=None,
) -> None:
    """Plot a fake 2D map: zones as points, vehicle routes as paths."""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(8, 8))

    for zid, (x, y) in ZONE_COORDS.items():
        label = ZONE_NAMES[zid]
        color = "#333" if zid == 0 else "#666"
        size = 120 if zid == 0 else 80
        ax.scatter(x, y, s=size, c=color, zorder=5, edgecolors="black", linewidths=1.5)
        ax.annotate(label, (x, y), xytext=(0, 8), textcoords="offset points",
                    ha="center", fontsize=10, fontweight="bold")

    sequences = _get_route_zone_sequence(routes, orders)
    for v_idx, seq in enumerate(sequences):
        xs = [ZONE_COORDS[z][0] for _, z in seq]
        ys = [ZONE_COORDS[z][1] for _, z in seq]
        color = VEHICLE_COLORS[v_idx % len(VEHICLE_COLORS)]
        ax.plot(xs, ys, color=color, linewidth=1.5, alpha=0.8, zorder=2,
                label=VEHICLES[v_idx].name)

    ax.set_aspect("equal")
    ax.legend(loc="upper left", fontsize=8)
    ax.set_title(title)
    ax.set_xlim(-1.4, 1.4)
    ax.set_ylim(-1.4, 1.4)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def save_result_figures(
    result,
    output_path: Path,
    title: str = "",
    random_seed: int = 42,
) -> Path:
    """
    Save Gantt + route map for a single optimization result.

    result: SolveResult (has .routes)
    output_path: where to save (e.g. output/my_result.png)
    title: optional suptitle
    Returns: output_path
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    orders = get_orders(seed=None)
    gantt_data = get_gantt_data(result, random_seed=random_seed)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), height_ratios=[1, 1.2])
    plot_gantt(
        gantt_data,
        title="Gantt" if not title else f"{title} — Gantt",
        ax=ax1,
        routes=result.routes,
        orders=orders,
        locked_assignments=getattr(result, "locked_assignments", None) or {},
        driver_preferences=getattr(result, "driver_preferences", None) or [],
        shift_durations=(result.metrics or {}).get("shift_durations"),
    )
    plot_route_map(result.routes, orders, title="Routes" if not title else f"{title} — Routes", ax=ax2)
    if title:
        fig.suptitle(title, fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close()
    return output_path
