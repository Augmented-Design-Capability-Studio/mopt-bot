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
