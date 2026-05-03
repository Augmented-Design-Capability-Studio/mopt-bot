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
_ANSWERED_OPEN_QUESTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bI answered an open question\b", re.IGNORECASE),
)
_INTERPRET_ONLY_CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Run-completion turns are interpretation-only by design (the run output is
    # not a brief edit). Config-save turns USED to be in this list, but they
    # now run the hidden brief update so the LLM can refresh affected brief
    # rows in natural language and preserve any prior rationale.
    re.compile(r"\bRun\s*#\d+.*just completed\b", re.IGNORECASE),
)


_CONFIG_SAVE_CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bI manually updated the problem configuration\b", re.IGNORECASE),
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


def is_answered_open_question_message(content: str) -> bool:
    """True if the message is from the Definition panel after the user saved an answer."""
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _ANSWERED_OPEN_QUESTION_PATTERNS)


def is_definition_clear_request(content: str) -> bool:
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _CLEAR_INTENT_PATTERNS)


def is_interpret_only_context_message(content: str) -> bool:
    """True for synthetic context notes that should not trigger hidden brief/config derivation."""
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _INTERPRET_ONLY_CONTEXT_PATTERNS)


def is_config_save_context_message(content: str) -> bool:
    """True for the synthetic 'I manually updated the problem configuration' turn.

    These turns DO run the hidden brief update — the prompt assembly uses this
    helper to add a rationale-preservation fragment so the LLM rewrites the
    affected brief rows naturally instead of leaving the deterministic mirror
    boilerplate in place.
    """
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _CONFIG_SAVE_CONTEXT_PATTERNS)


_ASSISTANT_RUN_INVITATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bshould\s+i\s+(trigger|start|kick\s*off|begin|launch)\s+(a\s+)?(new\s+)?run\b", re.IGNORECASE),
    re.compile(r"\bshall\s+i\s+(trigger|start|kick\s*off|begin|launch)\s+(a\s+)?(new\s+)?run\b", re.IGNORECASE),
    re.compile(r"\b(want|would\s+you\s+like)\s+(me\s+to\s+)?(trigger|start|kick\s*off|launch)\s+(a\s+)?(new\s+)?(optimization\s+)?run\b", re.IGNORECASE),
    re.compile(r"\b(trigger|start)\s+(a\s+)?(new\s+)?run\s+(now|with\s+these).*\?", re.IGNORECASE),
    re.compile(r"\bready\s+to\s+(trigger|start|kick\s*off|launch)\s+(a\s+)?(new\s+)?run\b.*\?", re.IGNORECASE),
)


def assistant_reply_is_asking_about_run(text: str) -> bool:
    """True if the assistant reply is soliciting the user's confirmation before starting a run."""
    stripped = text.strip()
    if not stripped:
        return False
    return any(p.search(stripped) for p in _ASSISTANT_RUN_INVITATION_PATTERNS)


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
