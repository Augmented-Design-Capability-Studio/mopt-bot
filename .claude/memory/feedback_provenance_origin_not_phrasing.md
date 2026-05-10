---
name: Brief-row provenance follows origin, not visible-reply phrasing
description: User-asked changes are kind=gathered/source=user even when the agent's reply uses fait-accompli phrasing; only agent-proactive (post-run, no user request) additions are kind=assumption/source=agent
type: feedback
---

In agile mode the chatbot uses fait-accompli phrasing in the visible
reply ("I've added X") to avoid permission round-trips. That phrasing is
about *delivery*, not *provenance*. The brief row's `kind` and `source`
are decided by who originated the requirement, not by whose voice the
visible sentence uses.

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
text — keep it about who initiated the requirement.

**Related:** the agile arm's "fait accompli, not permission-asking"
feedback is unchanged — both rules co-exist. Phrasing stays past-tense
ownership; provenance stays user-stated.
