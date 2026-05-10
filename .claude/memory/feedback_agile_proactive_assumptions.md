---
name: Agile assumptions are fait accompli, not requests for permission
description: In agile mode, the chatbot must add assumptions to the Definition the same turn it suggests them — never split into "shall I add X?" → "sure!" → "added X"
type: feedback
---

In agile workflow, when run feedback or stated objectives motivate a new
goal-term assumption (e.g. lateness penalty after time-window violations,
capacity penalty after overload), the agent must:

- Add the assumption rows to `problem_brief_patch` **in the same turn** it
  surfaces the idea, framed in past tense ("I've added X (weight N)…").
- Tell the user they can approve, reject, retune in Definition, or just
  hit Run — that is the consent loop in agile.

Forbidden patterns:
- "I suggest we add a lateness penalty… shall I?"
- "If you agree, I'll add Y next."
- A "sure!" turn from the user followed by a turn that finally adds the
  assumption.

**Why:** The agile arm's defining behaviour is "assume and progress."
Splitting an assumption-add into propose → confirm → apply wastes a turn,
contradicts the workflow's identity, and makes the agent feel timid. The
user observed this exact failure in a fleet-routing run where the agent
said "I suggest we add a lateness penalty and a capacity penalty…" then
only added them after the user replied "sure!".

**How to apply:** When editing `backend/app/prompts/study_chat.py` agile
sections (workflow guidance, post-run run-ack, announce-assumptions
block), keep the language strong: "SHOULD" not "MAY", explicit
anti-patterns called out, fait accompli phrasing in the example
visible-reply lines. The waterfall arm is the opposite — there, asking
before adding is correct.
