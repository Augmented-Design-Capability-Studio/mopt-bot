"""Server-side Gemini calls for study chat."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a concise assistant helping a participant with fleet routing and scheduling optimization.
Use short paragraphs. Do not use branded scenario names or codenames for this study.
If the user uploads files, acknowledge that the data was received and proceed.
For Waterfall-style sessions, avoid dumping long constraint lists until the user has discussed needs in chat.
"""


def generate_assistant_reply(
    user_text: str,
    history_lines: list[tuple[str, str]],
    api_key: str,
    model_name: str,
) -> str:
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise RuntimeError("Gemini client not installed") from e

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    lines = [SYSTEM_PROMPT.strip(), "---"]
    for role, text in history_lines[-24:]:
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {text}")
    lines.append(f"User: {user_text}")
    lines.append("Assistant:")

    resp = model.generate_content("\n".join(lines))
    if not resp.parts:
        raise RuntimeError("Empty model response")
    return resp.text.strip() if resp.text else ""
