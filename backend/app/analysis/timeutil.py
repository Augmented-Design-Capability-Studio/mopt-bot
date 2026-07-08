"""Timestamp parsing for the analysis tool.

Source rows arrive either as SQLite datetime strings (``2026-07-02 19:35:32.386931``,
usually tz-naive → treated as UTC) or as ISO strings from the JSON export
(``serialize_utc_datetime``). We keep the original string verbatim for display
and derive an epoch-seconds float for time math and sorting.
"""

from __future__ import annotations

from datetime import datetime, timezone


def to_epoch(value: str | datetime | None) -> float | None:
    """Best-effort epoch seconds. Naive timestamps are assumed UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # Last resort: drop fractional seconds / trailing junk.
            try:
                dt = datetime.fromisoformat(s.split(".")[0])
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def iso_and_epoch(value: str | datetime | None) -> tuple[str | None, float | None]:
    """Return (original-string-form, epoch) for storage on a copied row."""
    if value is None:
        return None, None
    iso = value.isoformat() if isinstance(value, datetime) else str(value)
    return iso, to_epoch(value)
