"""Per-session aggregate metrics for the notebook/aggregate tab."""

from __future__ import annotations

from typing import Any

# The client auto-emits this line when files are attached; it is not the
# participant's own first prompt, so it is skipped for the "initial prompt".
_UPLOAD_PREFIX = "i'm uploading"


def initial_prompt_word_count(messages: list[Any]) -> int | None:
    """Word count of the first participant message that isn't the auto upload
    notice. Messages are sorted by time here. None if there is no such message."""
    ordered = sorted(messages, key=lambda x: (x.ts_epoch or 0.0, x.id))
    for msg in ordered:
        if (msg.role or "").lower() != "user":
            continue
        content = (msg.content or "").strip()
        if not content or content.lower().startswith(_UPLOAD_PREFIX):
            continue
        return len(content.split())
    return None
