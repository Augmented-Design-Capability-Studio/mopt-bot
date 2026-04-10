"""
QuickBite VRPTW — Generate a fake city map of delivery zones.

Creates a stylized map showing depot and zones A–E (Riverside, Harbor, Uptown,
Westgate, Northgate) for demonstration. Layout approximates relative distances
from the travel-time matrix.

Run from vrptw_problem/: python -m researcher.visualize_zone_map
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrptw_problem.traffic_api import ZONE_NAMES


# Layout: depot central, zones as neighborhoods (irregular, map-like)
# Based on travel times: A close, D farthest; B/C/E in between
# Coordinates scaled for a plausible "city blocks" feel
ZONE_COORDS = {
    0: (5.0, 5.0),   # Depot (central hub)
    1: (5.0, 8.5),   # A Riverside (north)
    2: (8.0, 6.5),   # B Harbor (northeast)
    3: (7.5, 3.0),   # C Uptown (southeast)
    4: (2.0, 2.5),   # D Westgate (southwest)
    5: (2.5, 7.5),   # E Northgate (northwest)
}

ZONE_LABELS = {
    0: "Depot",
    1: "A · Riverside",
    2: "B · Harbor",
    3: "C · Uptown",
    4: "D · Westgate",
    5: "E · Northgate",
}


def main() -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import matplotlib.patheffects as pe
    except ImportError:
        print("matplotlib required: pip install matplotlib")
        return

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect("equal")

    # Light background (map paper)
    ax.set_facecolor("#f5f0e6")
    fig.patch.set_facecolor("#f5f0e6")

    # Zone polygons (irregular "neighborhood" shapes)
    # Each zone is a rough polygon around its center
    zone_shapes = {
        0: [(4.2, 4.2), (5.8, 4.2), (5.8, 5.8), (4.2, 5.8)],  # Depot: square
        1: [(4.2, 7.8), (5.5, 9.0), (6.0, 8.2), (5.0, 7.5)],  # A: irregular
        2: [(7.2, 5.8), (8.8, 6.2), (8.5, 7.2), (7.5, 7.0)],  # B
        3: [(6.5, 2.2), (8.2, 2.8), (8.0, 3.8), (7.0, 3.2)],  # C
        4: [(1.2, 1.5), (2.5, 1.8), (2.8, 3.2), (1.8, 3.0)],  # D
        5: [(1.5, 6.8), (3.2, 8.0), (3.5, 7.2), (2.2, 6.5)],  # E
    }
    zone_colors = {
        0: "#2c3e50",   # Depot: dark
        1: "#3498db",   # A: blue
        2: "#1abc9c",   # B: teal
        3: "#9b59b6",   # C: purple
        4: "#e74c3c",   # D: red
        5: "#f39c12",   # E: orange
    }

    for zid, verts in zone_shapes.items():
        poly = mpatches.Polygon(verts, facecolor=zone_colors[zid], edgecolor="#333",
                                linewidth=2, alpha=0.7)
        ax.add_patch(poly)

    # Zone labels
    for zid, (x, y) in ZONE_COORDS.items():
        label = ZONE_LABELS[zid]
        color = "white" if zid == 0 else "#1a1a1a"
        weight = "bold" if zid == 0 else "normal"
        ax.annotate(label, (x, y), ha="center", va="center", fontsize=10,
                    color=color, weight=weight,
                    path_effects=[pe.withStroke(linewidth=0.5, foreground="#333")] if zid == 0 else [])

    # "Roads" (thin lines between depot and zones)
    depot = ZONE_COORDS[0]
    for zid in range(1, 6):
        ax.plot([depot[0], ZONE_COORDS[zid][0]], [depot[1], ZONE_COORDS[zid][1]],
                color="#888", linestyle="--", linewidth=0.8, alpha=0.5)

    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("QuickBite Delivery Zones", fontsize=14, fontweight="bold")
    for s in ax.spines.values():
        s.set_visible(False)

    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "zone_map.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
