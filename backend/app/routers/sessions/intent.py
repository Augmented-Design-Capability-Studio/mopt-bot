"""Intent detection for chat and definition handling."""

from __future__ import annotations

import re

_CLEANUP_INTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bclean\s*up\b", re.IGNORECASE),
    re.compile(r"\bconsolidat(?:e|ion)\b", re.IGNORECASE),
    re.compile(r"\bdeduplicat(?:e|ion)\b", re.IGNORECASE),
    re.compile(r"\breorgan(?:ize|ise|ization|isation)\b", re.IGNORECASE),
    re.compile(r"\b(remove|delete|drop)\b.{0,80}\b(assumption|gathered|definition|item|fact)\b", re.IGNORECASE),
    re.compile(r"\bmerge\b.{0,60}\b(gathered|assumption)\b", re.IGNORECASE),
)
_RUN_ACK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Run\s*#\d+.*just completed", re.IGNORECASE),
    re.compile(r"Run\s*#\d+.*finished", re.IGNORECASE),
    re.compile(r"Please interpret these results", re.IGNORECASE),
)
_CLEAR_INTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bclear\b.{0,40}\b(definition|brief|gathered|assumption|open question|everything|all)\b", re.IGNORECASE),
    re.compile(r"\breset\b.{0,40}\b(definition|brief|everything|all)\b", re.IGNORECASE),
    re.compile(r"\brestart\b", re.IGNORECASE),
    re.compile(r"\bfresh slate\b", re.IGNORECASE),
)


def is_definition_cleanup_request(content: str) -> bool:
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _CLEANUP_INTENT_PATTERNS)


def is_run_acknowledgement_message(content: str) -> bool:
    """True if the message is the auto-posted run-complete context (e.g. 'Run #1 just completed...')."""
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _RUN_ACK_PATTERNS)


def is_definition_clear_request(content: str) -> bool:
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _CLEAR_INTENT_PATTERNS)


def sanitize_visible_assistant_reply(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    key_pattern = r'(?:problem_brief_patch|panel_patch|replace_editable_items|replace_open_questions|cleanup_mode)'
    cleaned = re.sub(
        rf"```(?:json)?\s*[\s\S]*?{key_pattern}[\s\S]*?```",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        rf"\{{[\s\S]*?{key_pattern}[\s\S]*?\}}\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    if not cleaned:
        return "Acknowledged. I updated the definition context in the background."
    return cleaned
