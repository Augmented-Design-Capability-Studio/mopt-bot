"""VRPTW-specific safety net for the ``driver_preferences`` structured carrier.

Background
==========

The VRPTW brief contract (``DRIVER_PREFERENCES_BRIEF_CONTRACT`` in
``study_prompts``) requires the brief-update LLM to emit the structured rule
list at ``goal_terms.worker_preference.properties.driver_preferences``
**on the same turn** the user introduces a rule. Prose-only emission is
documented as insufficient — without the structured carrier the panel never
sees the rules and the synthesized prose row never renders.

In practice the LLM occasionally drops the structured carrier under prompt
bloat while still committing the parent ``worker_preference`` goal term and a
prose ``items[]`` row that names the rule. The participant then sees the
agent acknowledge the rules in chat but the panel stays empty.

This module is the deterministic recovery: it detects that exact gap
(worker_preference present, ``driver_preferences`` empty, prose plausibly
extractable) and re-runs a focused, narrow LLM extraction with VRPTW-specific
vocabulary (worker names, zone codes, condition kinds). The main backend
exposes the safety net through :meth:`StudyProblemPort.safety_net_fill_structured_carriers`,
so the orchestration in ``derivation.py`` stays problem-agnostic.

All VRPTW vocabulary, prompt text, and schema live here — never in
``backend/app``.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any

from google import genai
from google.genai import types


log = logging.getLogger(__name__)


# Substring hints (lowercase) that a brief items[] row is describing
# driver-preference rules with enough specificity that we should attempt
# structured extraction. Used as a cheap gate before firing the focused
# extractor LLM call — we only want to spend tokens when the prose
# plausibly carries extractable rules (named workers + zone / express /
# shift concepts).
_WORKER_NAMES: tuple[str, ...] = ("alice", "bob", "carol", "dave", "eve")
_CONDITION_HINTS: tuple[str, ...] = (
    "zone", "express", "priority", "shift", "hour", "minute",
)


_EXTRACTOR_SYSTEM_INSTRUCTION = """\
You extract structured VRPTW driver-preference rules from prose.

Inputs (in the user payload):
- ``user_message``: the participant's latest chat turn that introduced the rules.
- ``visible_reply``: the agent's response acknowledging them.
- ``prose_summary``: the brief items[] prose row(s) describing the rules.

Output one entry per rule in ``rules``. Vocabulary:

**vehicle_idx mapping (worker name -> idx):**
Alice=0, Bob=1, Carol=2, Dave=3, Eve=4. Use the FIRST mention of a worker
name; if no name is given for a rule, skip that rule (no default driver).

**condition vocabulary:**
- ``avoid_zone`` - worker dislikes / avoids stops in a zone. Set
  ``zone`` (1=A, 2=B, 3=C, 4=D, 5=E; depot index 0 is invalid).
- ``order_priority`` - worker prefers a class of orders. Set
  ``order_priority`` to exactly ``"express"`` or ``"standard"`` (never
  synonyms like ``"low"`` or ``"high"`` - those map to ``standard`` /
  ``express`` respectively, but emit the canonical string).
- ``shift_over_limit`` - worker dislikes long shifts past a limit. Set
  ``limit_minutes`` to the explicit number (e.g. 390 for 6.5 hours, 480
  for 8 hours). Convert hours -> minutes when the prose uses hours.

**penalty:** if not specified in the prose, use a reasonable soft-penalty
default of ``50`` (cost units). Never zero; that would no-op the rule.

**aggregation:** omit unless the prose explicitly says "once per route"
or "per shift only" - default ``per_stop`` is implicit.

**Failure modes to avoid:**
- Inventing rules the prose does not describe.
- Re-emitting rules that the prose says were retracted or removed.
- Guessing worker names not mentioned (e.g. do not add "Eve" as a default).
- Confusing zone letters with worker letters (Zone D is zone 4, not Dave).

Output JSON only matching the schema. ``rules: []`` is correct when the
prose describes no concrete extractable rules.
"""


_EXTRACTION_SCHEMA: dict[str, Any] = {
    "title": "DriverPreferencesExtraction",
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "description": (
                "Structured driver-preference rules extracted from the prose. "
                "Empty when the prose describes no concrete rules (e.g. only "
                "says 'add worker preferences' without naming a worker)."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "vehicle_idx": {"type": "integer", "minimum": 0, "maximum": 4},
                    "condition": {
                        "type": "string",
                        "enum": ["avoid_zone", "order_priority", "shift_over_limit"],
                    },
                    "penalty": {"type": "number", "minimum": 0},
                    "zone": {"type": "integer", "minimum": 1, "maximum": 5},
                    "order_priority": {"type": "string", "enum": ["express", "standard"]},
                    "limit_minutes": {"type": "number", "minimum": 0},
                    "aggregation": {"type": "string", "enum": ["per_stop", "once_per_route"]},
                },
                "required": ["vehicle_idx", "condition", "penalty"],
            },
        },
    },
    "required": ["rules"],
}


def _items_describe_rules(items: list[Any]) -> str:
    """Return concatenated prose from items[] that look like they describe
    driver-preference rules - worker names plus zone/express/shift hints.
    Empty string when no such items are found, in which case the extractor
    does NOT fire (the prose is too vague to extract rules from).
    """
    chunks: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        lowered = text.lower()
        has_name = any(name in lowered for name in _WORKER_NAMES)
        has_condition = any(hint in lowered for hint in _CONDITION_HINTS)
        if has_name and has_condition:
            chunks.append(text)
    return " ".join(chunks)


def _validate_extracted_rule(entry: Any) -> dict[str, Any] | None:
    """Defensive shape check on one extracted rule. Returns ``None`` when
    the entry can't be coerced into a well-formed rule; otherwise returns
    the cleaned dict ready to drop into ``driver_preferences``.
    """
    if not isinstance(entry, dict):
        return None
    vidx = entry.get("vehicle_idx")
    cond = entry.get("condition")
    penalty = entry.get("penalty")
    if not isinstance(vidx, int) or vidx < 0 or vidx > 4:
        return None
    if cond not in ("avoid_zone", "order_priority", "shift_over_limit"):
        return None
    if not isinstance(penalty, (int, float)) or penalty < 0:
        return None
    rule: dict[str, Any] = {
        "vehicle_idx": vidx,
        "condition": cond,
        "penalty": float(penalty),
    }
    if cond == "avoid_zone":
        zone = entry.get("zone")
        if not isinstance(zone, int) or zone < 1 or zone > 5:
            return None
        rule["zone"] = zone
    elif cond == "order_priority":
        op = entry.get("order_priority")
        if op not in ("express", "standard"):
            return None
        rule["order_priority"] = op
    elif cond == "shift_over_limit":
        lim = entry.get("limit_minutes")
        if not isinstance(lim, (int, float)) or lim <= 0:
            return None
        rule["limit_minutes"] = float(lim)
    agg = entry.get("aggregation")
    if agg in ("per_stop", "once_per_route"):
        rule["aggregation"] = agg
    return rule


def _call_extractor(
    *,
    user_message: str,
    visible_reply: str | None,
    prose_summary: str,
    api_key: str,
    model_name: str,
) -> list[dict[str, Any]] | None:
    """Fire the focused Gemini extraction call. Returns ``None`` on any
    SDK / parse failure (caller treats as no-op), ``[]`` when the LLM
    decided the prose was too vague, or a list of validated rule dicts.
    """
    payload = {
        "user_message": str(user_message or ""),
        "visible_reply": str(visible_reply or ""),
        "prose_summary": prose_summary,
    }
    user_text = json.dumps(payload, ensure_ascii=False, indent=2)
    config = types.GenerateContentConfig(
        system_instruction=_EXTRACTOR_SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_json_schema=_EXTRACTION_SCHEMA,
    )
    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model_name,
            contents=user_text,
            config=config,
        )
    except Exception as exc:
        log.warning("VRPTW driver-pref extractor call failed (%s); returning None", exc)
        return None
    parsed = resp.parsed if isinstance(resp.parsed, dict) else None
    if parsed is None:
        raw = resp.text or ""
        if not raw.strip():
            return None
        try:
            parsed = json.loads(raw)
        except Exception:
            return None
    rules_raw = parsed.get("rules") if isinstance(parsed, dict) else None
    if not isinstance(rules_raw, list):
        return None
    out_rules: list[dict[str, Any]] = []
    for entry in rules_raw:
        rule = _validate_extracted_rule(entry)
        if rule is not None:
            out_rules.append(rule)
    return out_rules


def fill_driver_preferences_carrier(
    brief: dict[str, Any],
    *,
    api_key: str | None,
    model_name: str | None,
    user_text: str,
    visible_reply: str | None,
) -> dict[str, Any]:
    """Detect-and-fill safety net for VRPTW's ``driver_preferences`` carrier.

    Fires when the merged brief has ``worker_preference`` in ``goal_terms``
    but its ``properties.driver_preferences`` carrier is empty AND the
    items[] prose plausibly describes specific rules. Injects extracted
    rules into a copy of the brief and returns it; returns ``brief``
    unchanged when no fill is needed (no worker_preference, carrier
    already populated, no extractable prose, or extractor returns
    nothing).
    """
    if not isinstance(brief, dict):
        return brief
    if not api_key or not model_name:
        return brief
    goal_terms = brief.get("goal_terms")
    if not isinstance(goal_terms, dict):
        return brief
    wp = goal_terms.get("worker_preference")
    if not isinstance(wp, dict):
        return brief
    properties = wp.get("properties") if isinstance(wp.get("properties"), dict) else {}
    existing_rules = properties.get("driver_preferences")
    if isinstance(existing_rules, list) and existing_rules:
        # Brief-update LLM already populated the carrier on the same turn.
        # No safety-net call needed.
        return brief
    prose = _items_describe_rules(brief.get("items") or [])
    if not prose:
        # No specific names + conditions in the prose - nothing extractable.
        return brief
    try:
        rules = _call_extractor(
            user_message=user_text,
            visible_reply=visible_reply,
            prose_summary=prose,
            api_key=api_key,
            model_name=model_name,
        )
    except Exception:  # pragma: no cover - defensive
        log.exception("VRPTW driver-pref safety net raised; leaving brief unchanged")
        return brief
    if not rules:
        return brief
    log.info(
        "VRPTW driver-pref safety net injected %d rule(s) from prose: %s",
        len(rules),
        prose[:120],
    )
    next_brief = deepcopy(brief)
    next_goal_terms = dict(next_brief.get("goal_terms") or {})
    wp_entry = dict(next_goal_terms.get("worker_preference") or {})
    wp_properties = dict(wp_entry.get("properties") or {})
    wp_properties["driver_preferences"] = rules
    wp_entry["properties"] = wp_properties
    next_goal_terms["worker_preference"] = wp_entry
    next_brief["goal_terms"] = next_goal_terms
    return next_brief
