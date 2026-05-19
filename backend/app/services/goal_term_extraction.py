"""Structured-output extraction of canonical goal-term commitments.

Used as a cold-start backstop when the V2 brief patch arrives with a
``goal_summary`` (or substantive items[] text) but leaves
``brief.goal_terms`` empty — typical of waterfall first turns where the LLM
routes the goal to the summary field and defers everything else via OQ.

Design constraints (matches the project's no-NL-parsing-in-main-code rule):

- The active port owns the closed enum of canonical goal-term keys via
  ``StudyProblemPort.goal_term_extraction_schema()``. Ports that decline
  return ``None`` and this service is a no-op for them.
- The extraction is a structured-output Gemini call against that schema —
  not a keyword or regex scan. Phrasing variation ("biggest haul",
  "minimize wasted weight", "keep the pack light") resolves naturally
  through the LLM's understanding without per-port alias maps.
- The service is a *seed*, not an override — callers gate it on cold-start
  state (``base.goal_terms`` empty AND ``merged.goal_terms`` empty) so a
  later user/agent retirement of a key is not silently reverted.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google import genai
from google.genai import types

from app.problems.registry import get_study_port

log = logging.getLogger(__name__)


def extract_canonical_goal_terms(
    *,
    merged_brief: dict[str, Any],
    user_text: str,
    api_key: str,
    model_name: str,
    test_problem_id: str | None,
) -> dict[str, dict[str, Any]]:
    """Return seed entries for canonical goal-term keys the participant has
    explicitly committed to in their stated framing.

    The shape of each value matches the brief-merge contract:
    ``{"weight": float, "type": str, "rank": int, "ambiguity_note":
    {"chosen_rationale": str}}``. The port's
    ``seed_goal_term_defaults(key)`` supplies weight/type/rank; this
    service overlays the rationale phrase the LLM produced.

    Returns ``{}`` (no seed) when:
    - the port has no extraction schema (default for non-opting ports);
    - no api_key or model_name was provided;
    - the merged brief has no text signal to extract from;
    - the LLM call fails, times out, or returns no committed concepts.

    Cold-start gating is the caller's responsibility — this function runs
    the LLM whenever invoked.
    """
    if not api_key or not model_name:
        return {}
    try:
        port = get_study_port(test_problem_id) if test_problem_id is not None else None
    except Exception:  # pragma: no cover — defensive
        return {}
    if port is None:
        return {}
    try:
        schema = port.goal_term_extraction_schema()
    except Exception:  # pragma: no cover — defensive
        return {}
    if not isinstance(schema, dict) or not schema:
        return {}

    text_evidence = _gather_text_evidence(merged_brief, user_text)
    if not text_evidence.strip():
        return {}

    try:
        labels = port.weight_item_labels() or {}
    except Exception:  # pragma: no cover — defensive
        labels = {}
    try:
        rationales = port.goal_term_rationales() or {}
    except Exception:  # pragma: no cover — defensive
        rationales = {}

    label_lines: list[str] = []
    for key, label in labels.items():
        rationale = rationales.get(key, "")
        line = f"- `{key}` — {label}"
        if rationale:
            line += f" (purpose: {rationale})"
        label_lines.append(line)
    labels_block = "\n".join(label_lines) if label_lines else "(none registered)"

    system_instruction = (
        "You extract canonical optimization concepts that a participant has "
        "EXPLICITLY committed to in their natural-language framing of the "
        "problem. Output structured JSON only.\n\n"
        f"Active benchmark's canonical concepts:\n{labels_block}\n\n"
        "For each concept set ``named: true`` ONLY when the participant has "
        "directly committed to it as an objective, constraint, or "
        "preference. Examples of commitment: \"maximize the value\", "
        "\"don't exceed capacity\", \"keep the selection small\". Examples "
        "of NON-commitment: \"each item has a value and weight\" "
        "(descriptive setup), \"capacity is 50\" (parameter, not a goal).\n\n"
        "When ``named: true``, fill ``rationale_phrase`` with one short "
        "clause (<= 12 words) paraphrasing the participant's stated reason "
        "for committing — used verbatim in the Definition tab. When "
        "``named: false``, leave ``rationale_phrase`` empty.\n\n"
        "Be conservative: when in doubt, prefer ``named: false``. The "
        "downstream flow surfaces an open question that lets the "
        "participant disambiguate."
    )

    user_prompt = (
        f"Participant framing:\n{text_evidence}\n\n"
        "Which canonical concepts has the participant explicitly committed to?"
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_json_schema=schema,
        temperature=0.0,
    )
    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config=config,
        )
        raw = resp.text or ""
        if isinstance(resp.parsed, dict):
            parsed = resp.parsed
        else:
            parsed = json.loads(raw) if raw else {}
    except Exception as exc:
        log.warning("Canonical goal-term extraction failed (%s)", exc)
        return {}

    if not isinstance(parsed, dict):
        return {}
    concepts = parsed.get("concepts")
    if not isinstance(concepts, dict):
        return {}

    seeds: dict[str, dict[str, Any]] = {}
    for key, info in concepts.items():
        if not isinstance(key, str) or not isinstance(info, dict):
            continue
        if not info.get("named"):
            continue
        try:
            defaults = port.seed_goal_term_defaults(key)
        except Exception:  # pragma: no cover — defensive
            continue
        if not isinstance(defaults, dict):
            continue
        entry = dict(defaults)
        rationale = info.get("rationale_phrase")
        if isinstance(rationale, str) and rationale.strip():
            entry["ambiguity_note"] = {"chosen_rationale": rationale.strip()}
        seeds[key] = entry
    if seeds:
        log.info(
            "Canonical goal-term extraction seeded keys: %s",
            sorted(seeds.keys()),
        )
    return seeds


def _gather_text_evidence(merged_brief: dict[str, Any], user_text: str) -> str:
    """Build the prompt's evidence block — user message + goal_summary +
    gathered/assumption items[] text.

    Excludes setup-only canonical rows (``config-weight-*``) since those
    are server-synthesized and would feed back into the extractor's input
    on retry turns.
    """
    parts: list[str] = []
    user = (user_text or "").strip()
    if user:
        parts.append(f"User message: {user}")
    if isinstance(merged_brief, dict):
        gs = str(merged_brief.get("goal_summary") or "").strip()
        if gs:
            parts.append(f"Goal summary: {gs}")
        items = merged_brief.get("items") or []
        item_texts: list[str] = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            kind = str(it.get("kind") or "").strip().lower()
            if kind not in {"gathered", "assumption"}:
                continue
            item_id = str(it.get("id") or "")
            if item_id.startswith("config-weight-"):
                continue
            text = str(it.get("text") or "").strip()
            if text:
                item_texts.append(f"- {text}")
        if item_texts:
            parts.append("Brief items:\n" + "\n".join(item_texts))
    return "\n\n".join(parts)
