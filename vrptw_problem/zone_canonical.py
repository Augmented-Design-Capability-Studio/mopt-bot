"""Canonical zone identities for VRPTW zones (including depot as 0)."""

from __future__ import annotations

from typing import Final

ZONE_ID_TO_LETTER: Final[dict[int, str]] = {
    0: "DEPOT",
    1: "A",
    2: "B",
    3: "C",
    4: "D",
    5: "E",
}

ZONE_ID_TO_NAME: Final[dict[int, str]] = {
    0: "Depot",
    1: "Riverside",
    2: "Harbor",
    3: "Uptown",
    4: "Westgate",
    5: "Northgate",
}

ZONE_LETTER_TO_ID: Final[dict[str, int]] = {v: k for k, v in ZONE_ID_TO_LETTER.items()}
ZONE_NAME_TO_ID: Final[dict[str, int]] = {v.lower(): k for k, v in ZONE_ID_TO_NAME.items()}


def normalize_delivery_zone(raw_zone: object) -> int:
    """Normalize zone to canonical int id (Depot=0, delivery zones 1..5).

    Accepts:
    - int-like 0..5
    - letters A..E (case-insensitive)
    - "Depot" (case-insensitive)
    - canonical names Riverside/Harbor/Uptown/Westgate/Northgate (case-insensitive)
    """
    if isinstance(raw_zone, str):
        cleaned = raw_zone.strip()
        upper = cleaned.upper()
        if upper in ZONE_LETTER_TO_ID:
            return ZONE_LETTER_TO_ID[upper]
        lowered = cleaned.lower()
        if lowered in ZONE_NAME_TO_ID:
            return ZONE_NAME_TO_ID[lowered]
    return int(raw_zone)

