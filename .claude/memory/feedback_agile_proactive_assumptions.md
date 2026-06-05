---
name: Agile assumptions — fait accompli, and provenance follows origin
description: In agile mode the agent adds assumptions the same turn it suggests them (fait accompli); but a brief row's kind/source follows who ORIGINATED the requirement, not the visible reply's phrasing
type: feedback
---

# Agile assumption behavior — two coupled rules

## Part 1 — Fait accompli, not a request for permission

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

## Part 2 — Provenance follows origin, not visible-reply phrasing

The fait-accompli phrasing above ("I've added X") is about *delivery*, not
*provenance*. A brief row's `kind` and `source` are decided by who
originated the requirement, not by whose voice the visible sentence uses.

- **User-initiated** ("add a max shift limit term", "Alice doesn't like
  zone D", "I want to penalize lateness", uploaded data) → `kind:
  "gathered"`, `source: "user"` (or `upload`). Still gathered even if
  the agent fills in a default weight, threshold, or sub-property.
  *Verbatim* phrasing of the request is **not** the test.
- **Agent-initiated** (proactive post-run additions: agent observes
  time-window violations and adds `lateness_penalty` on its own with no
  user prompt) → `kind: "assumption"`, `source: "agent"`.

**Why:** the user repeatedly observed user-stated requests being filed
as assumptions because the LLM conflated "I've added X" fait-accompli
phrasing with "I'm assuming X". The result was a Definition panel that
mislabelled user requirements as agent guesses, and required the user
to manually promote them. The fix lives in `backend/app/prompts/
study_chat.py` (agile gathered-vs-assumption block) and the brief-update
visible-reply rule in `backend/app/services/llm.py`.

**How to apply:** when editing those prompts, keep the explicit "ORIGIN
not phrasing" framing. Don't introduce per-keyword tests on the user's
text — keep it about who initiated the requirement. Both rules co-exist:
phrasing stays past-tense ownership; provenance stays user-stated.
