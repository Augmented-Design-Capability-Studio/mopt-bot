"""Tests for the typed-context discriminator on ``MessageCreate``.

The router used to detect synthetic context messages (run-ack, config save,
restore, definition cleanup, …) by regex-matching the content the frontend
happened to emit. That coupled the two halves of the codebase via free-form
strings and routinely broke when either side drifted. ``MessageCreate.
context_kind`` replaces the protocol with a typed enum; the regex helpers
stay around as the backward-compat fallback for legacy / programmatic posts.

These tests pin the typed-first behaviour: when ``context_kind`` is set, the
classifier follows it regardless of content; when ``context_kind`` is ``None``,
the regex fallback still works.
"""

from __future__ import annotations

import pytest

from app.routers.sessions import intent


# ---------------------------------------------------------------------------
# is_run_acknowledgement_message
# ---------------------------------------------------------------------------


def test_run_ack_typed_kind_wins_over_unrelated_content():
    # Content has nothing to do with a run-ack but the typed discriminator
    # still says "this is a run-ack". Classifier must follow the kind.
    assert intent.is_run_acknowledgement_message("hello", context_kind="run_ack")


def test_run_ack_typed_kind_overrides_run_ack_lookalike_content():
    # The reverse: content *looks* like a run-ack but the typed kind says
    # "this is something else" (definition_save). The classifier must trust
    # the kind so we don't accidentally take the run-ack branch on a turn
    # the frontend tagged as a different protocol message.
    assert not intent.is_run_acknowledgement_message(
        "Run #1 just completed - cost 100. Please interpret these results.",
        context_kind="definition_save",
    )


def test_run_ack_regex_fallback_when_kind_is_none():
    # No context_kind supplied (legacy poster / older session) — content
    # regex still flags this as a run-ack.
    assert intent.is_run_acknowledgement_message(
        "Run #2 just completed - cost 50.", context_kind=None
    )
    assert not intent.is_run_acknowledgement_message("a regular question?", None)


# ---------------------------------------------------------------------------
# is_interpret_only_context_message
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind", ["run_ack", "config_restore", "definition_restore"]
)
def test_interpret_only_typed_kinds(kind: str):
    # These three are interpret-only by design (state change happened
    # through a different code path; chat shouldn't re-derive the brief).
    assert intent.is_interpret_only_context_message("any content", context_kind=kind)


def test_interpret_only_does_not_fire_for_other_kinds():
    # config_save / definition_save / cleanup must NOT be classified as
    # interpret-only — they do trigger brief rewrites by design.
    for kind in (
        "config_save",
        "definition_save",
        "definition_cleanup",
        "open_question_answered",
        "simulated_upload",
    ):
        assert not intent.is_interpret_only_context_message(
            "Run #1 just completed - cost 0. Please interpret these results.",
            context_kind=kind,
        ), f"kind={kind!r} should NOT be interpret-only"


def test_interpret_only_regex_fallback_when_kind_none():
    # Legacy path still catches the canonical run-ack string when no typed
    # discriminator is supplied.
    assert intent.is_interpret_only_context_message(
        "Run #1 just completed.", context_kind=None
    )
    assert not intent.is_interpret_only_context_message("hello", None)


# ---------------------------------------------------------------------------
# is_config_save_context_message
# ---------------------------------------------------------------------------


def test_config_save_typed_kind():
    assert intent.is_config_save_context_message(
        "any content here", context_kind="config_save"
    )
    assert not intent.is_config_save_context_message(
        "I manually updated the problem configuration. Changes: foo.",
        context_kind="run_ack",
    )


def test_config_save_regex_fallback():
    assert intent.is_config_save_context_message(
        "I manually updated the problem configuration. Changes: foo.", None
    )


# ---------------------------------------------------------------------------
# is_answered_open_question_message
# ---------------------------------------------------------------------------


def test_answered_open_question_typed_kind():
    assert intent.is_answered_open_question_message(
        "free text", context_kind="open_question_answered"
    )
    assert not intent.is_answered_open_question_message(
        "I answered an open question", context_kind="run_ack"
    )


def test_answered_open_question_regex_fallback():
    assert intent.is_answered_open_question_message(
        "I answered an open question", None
    )


# ---------------------------------------------------------------------------
# is_brief_edit_context_message
# ---------------------------------------------------------------------------


def test_brief_edit_recognizes_definition_save_kind():
    """Root cause of the recurring def-panel companion failures: the frontend
    tags a definition save with ``context_kind="definition_save"``, but the
    backend only honoured ``"brief_edit_ack"`` — so every def edit was
    misclassified as a plain chat turn and the brief-edit path (acknowledgement +
    companion extractor) never ran. Both kinds must count."""
    assert intent.is_brief_edit_context_message("Definition edited: 1 fact edited.", "definition_save")
    assert intent.is_brief_edit_context_message("anything", "brief_edit_ack")
    # A different typed kind must NOT be treated as a brief edit.
    assert not intent.is_brief_edit_context_message("Definition edited: 1 fact edited.", "run_ack")


# ---------------------------------------------------------------------------
# classify_fixed_phrase_intents
# ---------------------------------------------------------------------------


def test_classify_fixed_phrase_intents_typed_kind_short_circuits_content():
    # Content is arbitrary — typed kind alone should return the cleanup
    # tuple. The original behavior required exact-phrase matching, which
    # broke whenever the frontend constant drifted.
    result = intent.classify_fixed_phrase_intents(
        "Definition cleanup please.", context_kind="definition_cleanup"
    )
    assert result == (True, False, True)


def test_classify_fixed_phrase_intents_regex_fallback_still_works():
    # Legacy exact-phrase path stays alive for callers that haven't migrated.
    # The phrase is duplicated here intentionally (mirrors the frontend
    # constant) — if either side drifts we want the test to fail loudly.
    legacy_phrase = (
        "Please clean up and consolidate my problem definition: "
        "deduplicate redundant gathered facts and assumptions, "
        "and keep unresolved items in open questions."
    )
    assert intent.classify_fixed_phrase_intents(legacy_phrase, None) == (
        True,
        False,
        True,
    )
    # Free-form chat still returns None — only the known phrase short-
    # circuits the LLM classifier.
    assert intent.classify_fixed_phrase_intents("can you clean this up?", None) is None
