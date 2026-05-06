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


# Conservative regex fallback for the LLM-based change-intent classifier in
# `classify_definition_intents`.  Only returns False for messages that are
# unambiguously concept-questions / casual chat (no edit verb, no constraint
# language, no obvious goal-term mention); everything else stays True so the
# brief+panel pipelines run.  When the LLM is available it overrides this.
_OBVIOUS_CONCEPT_QUESTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(?:what|why|how|when|who|where|which)\s+(?:is|are|does|do|did)\b.{0,200}\?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:can\s+you\s+)?(?:explain|describe|define|clarify)\b.{0,200}\?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:thanks|thank you|thx|got it|cool|ok|okay|noted)\b.{0,40}$", re.IGNORECASE),
)
_CHANGE_INTENT_KEYWORDS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:add|remove|delete|drop|change|set|update|increase|decrease|raise|lower|switch|use)\b", re.IGNORECASE),
    re.compile(r"\b(?:weight|penalty|priority|constraint|hard|soft|limit|cap|maximum|minimum|target)\b", re.IGNORECASE),
    re.compile(r"\b(?:algorithm|epochs?|iterations?|population|swarm)\b", re.IGNORECASE),
)


def is_change_intent_fallback(content: str) -> bool:
    """Conservative regex fallback used when the LLM intent classifier is unavailable.

    Returns True by default — better to redundantly run the brief/panel pipelines
    than to silently drop a real edit.  Only returns False when the message
    matches a clear concept-question/casual-chat shape AND contains no edit-verb
    or constraint-language keywords.
    """
    text = content.strip()
    if not text:
        return False
    if any(p.search(text) for p in _CHANGE_INTENT_KEYWORDS):
        return True
    return not any(p.search(text) for p in _OBVIOUS_CONCEPT_QUESTION_PATTERNS)


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
    # Strip a plain-text schema-key heading (and everything after it, up to end of message)
    # that the model occasionally tacks on after a friendly "Changes I made:" summary, e.g.:
    #     problem_brief_patch:
    #
    #     Updated: "Travel time" to primary objective status with weight 6.6.
    # The prompt already forbids this, but treat it as defense-in-depth — once we see the
    # heading line, everything from there is a schema dump and should not reach the user.
    # Tolerates optional bullet/markdown decoration (e.g. `- **problem_brief_patch:**`) and
    # both forms of inline content ("schema_key:\n<content>" and "schema_key: <inline>\n…").
    cleaned = re.sub(
        rf"(?:\n|^)[ \t]*(?:[-*][ \t]+)?[`*_]*{key_pattern}[`*_]*[ \t]*:.*(?:\n.*)*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    if not cleaned:
        return "Acknowledged. I updated the definition context in the background."
    return cleaned
