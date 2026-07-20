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
steering directly in your next response" (built by `_researcher_steer_block` and
appended last in `build_main_turn_system_instruction`, `services/llm.py`). The
steer is NOT a Gemini history turn — it rides in the
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

**Steer must outrank conservative standing defaults.** The steer wording lost to
strongly-repeated waterfall guardrails like "don't add a search-strategy question
yourself — that one's handled for you" (study_chat.py). Symptom (session 7d4b9eaf):
a steer asking the agent to *suggest search-strategy / iteration changes* was
delivered on the right turns (verified via `load_fresh_researcher_steers`) but the
agent ignored it, while it happily answered the same topic when the participant
asked directly. Fix: the steer block explicitly states it outranks the agent's
proactivity defaults — including topics it would treat as "handled for you"
(algorithm / plateau) — while still forbidding fact-invention. The "handled for
you" rule stays the DEFAULT (deterministic study control); the steer is the
deliberate researcher override.

**Placement = recency: the steer block must be the LAST block in the full
main-turn prompt.** It USED to be appended inside `_build_visible_chat_system_instruction`,
whose "appended last" only meant last within `base_system` — but `base_system` is
just the FIRST of ~9 blocks `build_main_turn_system_instruction` stacks (brief-update,
items, grounding, hard-constraint, ambiguity, out-of-scope, output rules, retry
feedback…). So the steer landed ~60% into a ~46k-char prompt with ~17k chars of
conservative disciplines AFTER it, and the model ignored it. Symptom (session
910b3236, agile): two steers "invite the participant to look at the config panel"
were both loaded correctly yet neither reply complied. Fix: extracted the block
into `_researcher_steer_block(researcher_steers)` and append it as the FINAL part
of `build_main_turn_system_instruction` (after the retry-feedback block too), so
its "outranks your standing defaults" claim is backed by genuine last-position
recency. Block is workflow-agnostic (no mode arg) → never perturbs the four
canonical agile/waterfall differences. Guarded by
`tests/test_main_turn_prompt_assembly.py::test_researcher_steer_block_is_the_final_block`.

**Retries preserve the steer.** The automatic in-process S5 retry carries it via
`retry_context["researcher_steers"]`. The participant-clicked resume-from-pause
path (`_rebuild_runner_context`) rebuilds context from the DB and used to hardcode
`researcher_steers=None` — fixed to reconstruct via the shared
`load_fresh_researcher_steers(db, session_id, last_user.id)` helper (anchored on
the triggering user message, so the paused turn's placeholder reply doesn't count
as applied). Tests: `tests/test_researcher_steer_context.py`.
