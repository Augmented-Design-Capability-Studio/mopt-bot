"""LLM origin classification for the session-coding tool.

Deterministic provenance in the study data is unreliable for "who brought this
up": the brief frequently logs a user-stated constraint as an ``assumption``
(P01 does exactly this while the agent's own reply says "since you mentioned
capacity and shift"). The only faithful source is the user's own words, so we
read them — via a structured-output Gemini call, NOT keyword/regex matching
(matching the project's no-NL-parsing rule).

One batched call per session classifies every substantive user message against
the problem's canonical goal-term catalog. Results are cached (see
``models.OriginClassification``) so a timeline refresh never re-hits the API.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def _term_catalog(port: Any) -> dict[str, str]:
    """{goal_term key: label} for the classifier prompt/enum."""
    try:
        labels = port.weight_item_labels() or {}
    except Exception:
        labels = {}
    return {k: str(v) for k, v in labels.items()}


def classify_user_origins(
    messages: list[Any], port: Any, api_key: str, model: str
) -> dict[str, list[str]]:
    """``{user message source_id (str): [goal-term keys the user raised]}``.

    Only messages where the user *commits to / requests* a goal are tagged (a
    descriptive mention of a parameter is not a commitment). Returns ``{}`` (a
    harmless no-op) when there is no API key/model, no catalog, no user text, or
    the call fails — so the "dummy" button path is always safe.
    """
    if not api_key or not model:
        return {}
    catalog = _term_catalog(port)
    if not catalog:
        return {}

    user_msgs = [
        m
        for m in sorted(messages, key=lambda x: ((x.ts_epoch or 0.0), x.id))
        if getattr(m, "role", None) == "user"
        and (getattr(m, "kind", "") or "") == "chat"
        and (getattr(m, "content", "") or "").strip()
    ]
    if not user_msgs:
        return {}

    keys = list(catalog.keys())
    catalog_block = "\n".join(f"- `{k}` — {label}" for k, label in catalog.items())
    numbered = "\n\n".join(f"[{i}] {(m.content or '').strip()}" for i, m in enumerate(user_msgs))

    system_instruction = (
        "You label which canonical optimization goal terms a USER explicitly "
        "raises (requests, states as a constraint, or commits to as a goal) in "
        "each of their chat messages. Output structured JSON only.\n\n"
        f"Canonical goal terms:\n{catalog_block}\n\n"
        "Tag a term for a message ONLY when the user themselves brings it up — "
        "e.g. \"don't exceed each driver's capacity\" → capacity_penalty, "
        "\"arrive within the time window\" → lateness_penalty, \"stay under the "
        "max shift\" → shift_limit. Do NOT tag terms the user merely describes "
        "as data, nor terms only the assistant introduces. Be conservative: an "
        "empty list is correct when the message raises no goal term (e.g. "
        "\"which search is best?\", \"run it\")."
    )
    user_prompt = (
        "Classify each numbered user message. Return one entry per message index.\n\n"
        f"{numbered}"
    )

    schema = {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "terms": {"type": "array", "items": {"type": "string", "enum": keys}},
                    },
                    "required": ["index", "terms"],
                },
            }
        },
        "required": ["messages"],
    }

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_json_schema=schema,
                temperature=0.0,
            ),
        )
        parsed = resp.parsed if isinstance(resp.parsed, dict) else json.loads(resp.text or "{}")
    except Exception as exc:
        log.warning("Origin classification failed (%s)", exc)
        return {}

    out: dict[str, list[str]] = {}
    for entry in (parsed or {}).get("messages", []) or []:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        terms = entry.get("terms")
        if not isinstance(idx, int) or not (0 <= idx < len(user_msgs)) or not isinstance(terms, list):
            continue
        valid = [t for t in terms if t in catalog]
        if valid:
            out[str(user_msgs[idx].source_id)] = valid
    return out
