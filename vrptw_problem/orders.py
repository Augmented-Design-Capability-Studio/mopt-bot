"""
Order definitions and generation for QuickBite Fleet Scheduling.

Default orders are loaded from data/default_orders.json if present;
otherwise generated with seed=0 and optionally saved.
"""

import json
import numpy as np
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from traffic_api import ZONE_NAMES


# Default path for serialized orders (relative to package root)
DEFAULT_ORDERS_PATH = Path(__file__).parent / "data" / "default_orders.json"


@dataclass
class Order:
    """A delivery order."""
    order_id: str
    zone: int
    size: int
    priority: str  # "express" or "standard"
    time_window_open: int  # minutes since midnight
    time_window_close: int
    service_time: int  # 10 for standard, 15 for express


def generate_orders(seed: int = 0) -> list[Order]:
    """
    Generate 30 orders deterministically using numpy seed.

    Returns:
        List of Order objects.
    """
    rng = np.random.RandomState(seed)

    orders = []
    for i in range(30):
        order_id = f"O{i:02d}"
        zone = int(rng.randint(1, 6))  # zones 1-5
        size = int(rng.choice([1, 2, 3, 4, 5]))
        priority = "express" if rng.random() < 0.25 else "standard"

        # time_window_open: random time 08:00-14:00 in 30-min increments
        slot = rng.randint(0, 13)  # 0..12
        time_window_open = 480 + slot * 30

        duration = int(rng.choice([60, 90, 120, 150]))
        time_window_close = time_window_open + duration

        service_time = 15 if priority == "express" else 10

        orders.append(Order(
            order_id=order_id,
            zone=zone,
            size=size,
            priority=priority,
            time_window_open=time_window_open,
            time_window_close=time_window_close,
            service_time=service_time,
        ))

    return orders


def _order_to_dict(o: Order) -> dict:
    """Convert Order to JSON-serializable dict."""
    return asdict(o)


def _dict_to_order(d: dict) -> Order:
    """Convert dict to Order."""
    return Order(
        order_id=d["order_id"],
        zone=int(d["zone"]),
        size=int(d["size"]),
        priority=d["priority"],
        time_window_open=int(d["time_window_open"]),
        time_window_close=int(d["time_window_close"]),
        service_time=int(d["service_time"]),
    )


def load_default_orders(path: Optional[Path] = None) -> list[Order]:
    """
    Load default orders from file. If file does not exist, generate with seed=0.

    Args:
        path: Optional path to JSON file. Defaults to data/default_orders.json.

    Returns:
        List of Order objects.
    """
    p = path if path is not None else DEFAULT_ORDERS_PATH
    if p.exists():
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return [_dict_to_order(d) for d in data]
    return generate_orders(seed=0)


def save_default_orders(orders: list[Order], path: Optional[Path] = None) -> None:
    """
    Save orders to JSON file.

    Args:
        orders: List of Order objects.
        path: Optional path. Defaults to data/default_orders.json.
    """
    p = path if path is not None else DEFAULT_ORDERS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump([_order_to_dict(o) for o in orders], f, indent=2)


def get_orders(seed: Optional[int] = None, path: Optional[Path] = None) -> list[Order]:
    """
    Return orders for optimization.

    - If seed is None: load default (from file or generate(0)).
    - If seed is int: generate_orders(seed).

    Args:
        seed: Random seed for generation, or None for default.
        path: Optional path to default orders file.

    Returns:
        List of Order objects.
    """
    if seed is None:
        return load_default_orders(path=path)
    return generate_orders(seed=seed)


def print_order_table(orders: list[Order]) -> None:
    """Print the full order table for visibility and reproducibility."""
    print("\n=== QuickBite Orders (30) ===\n")
    print(f"{'ID':<6} {'Zone':<6} {'Size':<6} {'Priority':<10} "
          f"{'Window Open':<14} {'Window Close':<14} {'Svc':<5}")
    print("-" * 70)
    for o in orders:
        open_str = f"{o.time_window_open // 60:02d}:{o.time_window_open % 60:02d}"
        close_str = f"{o.time_window_close // 60:02d}:{o.time_window_close % 60:02d}"
        print(f"{o.order_id:<6} {ZONE_NAMES[o.zone]:<6} {o.size:<6} {o.priority:<10} "
              f"{open_str:<14} {close_str:<14} {o.service_time:<5}")
    print()
