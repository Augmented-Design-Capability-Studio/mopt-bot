"""Fixed 0/1 knapsack instance (deterministic from seed)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

N_ITEMS = 22
DEFAULT_CAPACITY = 50


@dataclass(frozen=True)
class Item:
    index: int
    weight: int
    value: int


def get_items(seed: int = 0) -> tuple[list[Item], int]:
    rng = np.random.RandomState(seed)
    items: list[Item] = []
    for i in range(N_ITEMS):
        w = int(rng.randint(3, 12))
        v = int(rng.randint(5, 25))
        items.append(Item(i, w, v))
    return items, DEFAULT_CAPACITY
