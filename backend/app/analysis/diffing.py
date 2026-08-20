"""Change-only projection of snapshot state.

The study stores a *full copy* of brief+panel on every snapshot (before each run
and on each manual save), so consecutive snapshots are frequently identical.
This helper walks snapshots in time order and reports changes only for the
snapshots where brief/panel actually moved — which is what drives the
"definition/config columns are empty except on change" behaviour.

Same presentation rules as the chat-turn derivations (coding_suggestions):
the def Δ is the STRIPPED brief (no ``goal_terms`` config mirror, no ``runs``
history) and the cfg Δ is the structured diff (chips), not a JSON dump.
"""

from __future__ import annotations

import json
from typing import Any

from app.analysis.coding_suggestions import (
    _canon,
    _problem,
    brief_for_display,
    structured_config_diff,
)


def _load(raw: str | None) -> dict:
    try:
        obj = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def compute_definition_config_changes(snapshots: list[Any]) -> dict[int, dict[str, Any]]:
    """Map loaded-snapshot id → {definition_change?: str, config_change?: dict}.

    ``snapshots`` are ``LoadedSnapshot`` rows; they are sorted here by
    ``(ts_epoch, id)`` so callers need not pre-sort. An entry is present only
    for snapshots whose (stripped) brief or panel differs from the previous
    snapshot's. The first snapshot diffs against an empty state, so its config
    diff lists every term as ``added`` (reference-only rows; acceptable).
    """
    ordered = sorted(snapshots, key=lambda s: (s.ts_epoch or 0.0, s.id))
    out: dict[int, dict[str, Any]] = {}
    prev_brief: dict = {}
    prev_panel: dict = {}
    for snap in ordered:
        brief = _load(snap.problem_brief_json)
        panel = _load(snap.panel_config_json)
        entry: dict[str, Any] = {}
        stripped = brief_for_display(brief)
        if stripped and _canon(stripped) != _canon(brief_for_display(prev_brief)):
            entry["definition_change"] = json.dumps(stripped, indent=2, ensure_ascii=False)
        if panel and _canon(panel) != _canon(prev_panel):
            cfg_diff = structured_config_diff(_problem(prev_panel), _problem(panel))
            entry["config_change"] = cfg_diff if cfg_diff is not None else {"other": True}
        if entry:
            out[snap.id] = entry
        prev_brief = brief
        prev_panel = panel
    return out
