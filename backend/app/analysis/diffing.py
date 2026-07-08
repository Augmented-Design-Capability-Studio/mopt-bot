"""Change-only projection of snapshot state.

The study stores a *full copy* of brief+panel on every snapshot (before each run
and on each manual save), so consecutive snapshots are frequently identical.
This helper walks snapshots in time order and reports the brief / panel only for
the snapshots where they actually changed — which is what drives the
"definition/config columns are empty except on change" behaviour.
"""

from __future__ import annotations

import json
from typing import Any


def _canonical(raw: str | None) -> str:
    """Normalise a JSON string so key-order / whitespace differences don't
    register as spurious changes. Falls back to the trimmed raw text."""
    if raw is None:
        return ""
    s = raw.strip()
    if not s:
        return ""
    try:
        return json.dumps(json.loads(s), sort_keys=True, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        return s


def compute_definition_config_changes(snapshots: list[Any]) -> dict[int, dict[str, str]]:
    """Map loaded-snapshot id → {definition_change?, config_change?}.

    ``snapshots`` are ``LoadedSnapshot`` rows; they are sorted here by
    ``(ts_epoch, id)`` so callers need not pre-sort. An entry is present only
    for snapshots whose brief or panel differs from the previous snapshot's.
    """
    ordered = sorted(snapshots, key=lambda s: (s.ts_epoch or 0.0, s.id))
    out: dict[int, dict[str, str]] = {}
    prev_brief: str | None = None
    prev_panel: str | None = None
    for snap in ordered:
        brief = _canonical(snap.problem_brief_json)
        panel = _canonical(snap.panel_config_json)
        entry: dict[str, str] = {}
        if brief != prev_brief and brief:
            entry["definition_change"] = snap.problem_brief_json or ""
        if panel != prev_panel and panel:
            entry["config_change"] = snap.panel_config_json or ""
        if entry:
            out[snap.id] = entry
        prev_brief = brief
        prev_panel = panel
    return out
