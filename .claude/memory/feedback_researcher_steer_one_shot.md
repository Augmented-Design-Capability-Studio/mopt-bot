---
name: feedback_researcher_steer_one_shot
description: A researcher steer is a one-shot directive for the next agent reply, not a standing instruction — surface it only until the agent has replied once, then drop it.
metadata:
  type: feedback
---

Researcher steers (role="researcher", visible_to_participant=False `ChatMessage`
rows, posted via `POST /{session}/steer`) must be applied by the agent **once**
in the upcoming reply, then stop being re-raised unless the researcher sends
them again.

**Why:** they're injected into the chat system prompt as "apply the latest
steering directly in your next response" (`_build_visible_chat_system_instruction`
in `services/llm.py`). The steer is NOT a Gemini history turn — it rides in the
system instruction as a `researcher_steers: list[str]`. Originally
`context.load_turn_context` re-queried the last 4 researcher rows **every turn**
with no new-vs-old distinction, so an already-applied steer kept getting re-fed
and the agent kept re-mentioning the same point every turn (e.g. repeatedly
pushing an option a researcher asked it to mention "just once").

**How to apply:** in `load_turn_context`, surface only steers newer than the
agent's last real reply (`ChatMessage.id > last_reply_id`) — once a reply
follows a steer, it's acknowledged and drops out. Keep the return signature
(`researcher_steers`) unchanged; the filter is positional, so no pipeline
re-threading.

**Anchor on `kind == "chat"`, NOT any assistant row.** All AI responses that
matter (plain chat, run acknowledgement, config-save, definition-save) funnel
through `_handle_post_participant_message` → `load_turn_context` and are written
with the default `kind="chat"`, so a steer reaches all of them. But there are
also **canned** assistant rows that do NOT invoke the model: the run summary
(`kind="run"`, "Run #N finished") and panel/def save acks (`kind="panel"`,
"Problem definition saved"). Anchoring on any assistant row lets one of those
consume a steer sent mid-run/mid-save, dropping it before the real LLM reply.

**Retries preserve the steer.** The automatic in-process S5 retry carries it via
`retry_context["researcher_steers"]`. The participant-clicked resume-from-pause
path (`_rebuild_runner_context`) rebuilds context from the DB and used to hardcode
`researcher_steers=None` — fixed to reconstruct via the shared
`load_fresh_researcher_steers(db, session_id, last_user.id)` helper (anchored on
the triggering user message, so the paused turn's placeholder reply doesn't count
as applied). Tests: `tests/test_researcher_steer_context.py`.
