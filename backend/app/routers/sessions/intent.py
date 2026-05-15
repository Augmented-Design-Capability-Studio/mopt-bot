"""Intent detection for chat and definition handling."""

from __future__ import annotations

import re


# Fixed strings the frontend posts on behalf of dedicated buttons. Matching the
# exact text lets us skip the intent-classifier LLM entirely. Update both ends
# in lockstep — see frontend/src/client/problemDefinition/constants.ts.
_FIXED_CLEANUP_PHRASE = (
    "Please clean up and consolidate my problem definition: "
    "deduplicate redundant gathered facts and assumptions, "
    "and keep unresolved items in open questions."
)


def classify_fixed_phrase_intents(
    content: str, context_kind: str | None = None
) -> tuple[bool, bool, bool] | None:
    """Return (cleanup, clear, change) for messages whose text is a known
    button-posted phrase. Returns ``None`` for free-form user input so callers
    fall through to the LLM classifier.

    Prefers the typed ``context_kind`` from ``MessageCreate`` when set; a
    set kind that isn't a known fixed-phrase kind returns ``None`` (caller
    falls through to LLM classification). Falls back to content matching only
    when no kind is supplied.
    """
    if context_kind is not None:
        if context_kind == "definition_cleanup":
            return (True, False, True)
        return None
    text = (content or "").strip()
    if not text:
        return None
    if text == _FIXED_CLEANUP_PHRASE:
        # Cleanup button: cleanup_intent=True, no clear, treat as a change so
        # the brief/panel pipelines run on the rewrite.
        return (True, False, True)
    return None

_RUN_ACK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Run\s*#\d+.*just completed", re.IGNORECASE),
    re.compile(r"Run\s*#\d+.*finished", re.IGNORECASE),
    re.compile(r"Please interpret these results", re.IGNORECASE),
)
_ANSWERED_OPEN_QUESTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bI answered an open question\b", re.IGNORECASE),
)
_INTERPRET_ONLY_CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bRun\s*#\d+.*just completed\b", re.IGNORECASE),
)
_CONFIG_SAVE_CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bI manually updated the problem configuration\b", re.IGNORECASE),
)


def is_run_acknowledgement_message(
    content: str, context_kind: str | None = None
) -> bool:
    """True if the message is the auto-posted run-complete context.

    ``context_kind`` is the typed discriminator from ``MessageCreate``: when
    set, it short-circuits the regex entirely so we no longer have to match
    content strings the frontend happens to emit (and a turn tagged as
    something else can't accidentally trigger the run-ack branch even if its
    content looks run-ack-shaped). Regex stays as the backward-compatible
    fallback for legacy callers (older sessions, ad-hoc programmatic posts,
    server-side replays).
    """
    if context_kind is not None:
        return context_kind == "run_ack"
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _RUN_ACK_PATTERNS)


def is_answered_open_question_message(
    content: str, context_kind: str | None = None
) -> bool:
    """True if the message is from the Definition panel after the user saved an answer."""
    if context_kind is not None:
        return context_kind == "open_question_answered"
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _ANSWERED_OPEN_QUESTION_PATTERNS)


_INTERPRET_ONLY_CONTEXT_KINDS = frozenset(
    {
        # Run-completion turns and snapshot-restore turns are interpretation-
        # only by design — their content is not a brief edit, just a synthetic
        # context note asking the agent to react to a state change that
        # already happened in the panel/brief through a different code path.
        "run_ack",
        "config_restore",
        "definition_restore",
    }
)


def is_interpret_only_context_message(
    content: str, context_kind: str | None = None
) -> bool:
    """True for synthetic context notes that should not trigger hidden brief/config derivation."""
    if context_kind is not None:
        return context_kind in _INTERPRET_ONLY_CONTEXT_KINDS
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _INTERPRET_ONLY_CONTEXT_PATTERNS)


def is_config_save_context_message(
    content: str, context_kind: str | None = None
) -> bool:
    """True for the synthetic 'I manually updated the problem configuration' turn.

    These turns DO run the hidden brief update — the prompt assembly uses this
    helper to add a rationale-preservation fragment so the LLM rewrites the
    affected brief rows naturally instead of leaving the deterministic mirror
    boilerplate in place.
    """
    if context_kind is not None:
        return context_kind == "config_save"
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _CONFIG_SAVE_CONTEXT_PATTERNS)


_BRIEF_EDIT_CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bi\s+just\s+manually\s+updated\s+the\s+problem\s+definition\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bproblem\s+definition\s+saved\b",
        re.IGNORECASE,
    ),
)


def is_brief_edit_context_message(
    content: str, context_kind: str | None = None
) -> bool:
    """True for the synthetic 'I just manually updated the problem definition' turn.

    The chat pipeline routes these through ``run_chat_pipeline`` with
    ``is_brief_edit_ack=True`` so the main-turn LLM produces an
    acknowledgement + any implied maintenance updates rather than
    fighting with the user's typed edit.
    """
    if context_kind is not None:
        return context_kind == "brief_edit_ack"
    text = content.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _BRIEF_EDIT_CONTEXT_PATTERNS)


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
