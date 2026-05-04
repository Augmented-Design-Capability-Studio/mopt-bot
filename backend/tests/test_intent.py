"""Tests for intent detection (intent.py)."""

from app.routers.sessions import intent


def test_is_run_acknowledgement_message():
    """Run-ack detection matches the frontend auto-posted context message."""
    assert intent.is_run_acknowledgement_message(
        "Run #1 just completed - cost 123.45 (5 time-window stops late). Please interpret these results, compare to any previous runs, and suggest what to adjust next."
    )
    assert intent.is_run_acknowledgement_message(
        "Run #2 just completed - cost 99.0 (no violations). Please interpret these results, compare to any previous runs, and suggest what to adjust next."
    )
    assert intent.is_run_acknowledgement_message("Run #3 finished with cost 150.")
    assert intent.is_run_acknowledgement_message("Please interpret these results and suggest next steps.")
    assert not intent.is_run_acknowledgement_message("I ran the optimizer and got good results.")
    assert not intent.is_run_acknowledgement_message("")
    assert not intent.is_run_acknowledgement_message("Can you help me refine the problem definition?")


def test_sanitize_visible_assistant_reply_strips_problem_brief_patch_tail():
    """The model occasionally tacks a `problem_brief_patch:` heading + lines onto an
    otherwise-clean friendly summary; the sanitizer must strip from that heading to
    end-of-message so the user never sees the schema dump."""
    leaked = (
        "I have solidified travel efficiency as your primary objective.\n"
        "\n"
        "Changes I made:\n"
        "\n"
        "Formally set travel time efficiency as your primary objective.\n"
        "Maintained the 6.6 weight to keep consistent pressure on minimizing total route duration.\n"
        "problem_brief_patch:\n"
        "\n"
        "Updated: \"Travel time efficiency\" to primary objective status with weight 6.6."
    )
    cleaned = intent.sanitize_visible_assistant_reply(leaked)
    assert "problem_brief_patch" not in cleaned.lower()
    assert "Updated:" not in cleaned
    # Friendly summary survives intact.
    assert "Changes I made:" in cleaned
    assert "Formally set travel time efficiency" in cleaned
    assert "Maintained the 6.6 weight" in cleaned


def test_sanitize_visible_assistant_reply_strips_markdown_decorated_heading():
    """Same protection for markdown bullet/emphasis decoration like `- **panel_patch:**`."""
    leaked = (
        "Bumped travel-time emphasis.\n"
        "\n"
        "- **panel_patch:** updated weights map.\n"
    )
    cleaned = intent.sanitize_visible_assistant_reply(leaked)
    assert "panel_patch" not in cleaned.lower()
    assert cleaned.startswith("Bumped travel-time emphasis.")


def test_sanitize_visible_assistant_reply_keeps_legitimate_text():
    """Legitimate text that mentions schema names *only* in prose (not as a heading) must
    pass through untouched. We only strip dedicated heading lines."""
    text = (
        "Reminder: the hidden brief carries a problem_brief_patch internally — you don't see it.\n"
        "Anything else you want me to adjust?"
    )
    cleaned = intent.sanitize_visible_assistant_reply(text)
    assert cleaned == text
