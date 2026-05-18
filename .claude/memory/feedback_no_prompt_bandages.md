---
name: feedback-no-prompt-bandages
description: When server state has multiple writers producing inconsistent state, fix the architecture (remove a writer, add a structural gate). Don't keep adding prompt blocks to teach the LLM to compensate.
metadata:
  type: feedback
---

When two or more components can write to the same piece of state (e.g.
the LLM and a server-side enforcer both authoring OQs for the same
topic), the resulting inconsistency is an **ownership bug**, not a
behavior bug. Fixing it with more prompt instructions only suppresses
symptoms — the next prompt edit cycle revives the same class of failure
under a slightly different shape.

**The rule:** when the same kind of bug reappears after a prompt-only
fix, treat that as evidence the architecture is wrong. The fix is one
of:

- **Remove a writer.** Decide which component owns the state and make
  the other one structurally unable to write it (schema constraint,
  pre-merge strip, deterministic-only flow).
- **Add a structural gate.** A required enum field, a typed channel,
  a transactional read snapshot — anything that turns "could two
  writers disagree?" into "can the data be in this shape at all?"

**Concrete patterns to prefer over more prompt text:**

- Make optional discriminators required (e.g. `topic?: ...` →
  `topic: "a" | "b" | "c" | "other"`) so the LLM can't abstain and
  let untagged content slip past dedup.
- Strip / coerce LLM-emitted state at the merge boundary when an
  authoritative server-side path owns the same field.
- Skip diagnostics during in-flight pipeline windows
  (`processing.*_status == "pending"`) instead of teaching the LLM to
  fix phantom-state-induced false positives.

**Why this matters specifically here:** prompt edits are seductive
because they're fast and feel safe. But every edit makes the prompt
longer, every new edge case earns another paragraph, and the LLM has
to consistently follow a growing rulebook with non-uniform priority.
Cyclic regressions are the cost. The user explicitly flagged this as
lazy work — they're right.

**How to apply:** before adding any new prompt block, ask: *"Is there
a state-ownership problem here that a schema constraint or a server
strip could solve more reliably than instructing the LLM?"* If yes,
do that instead. The prompt should be shorter after most bug fixes,
not longer. Related: [[feedback-no-regex-for-nl]] is the analogous
rule for participant input — both flow from the same principle:
trust structure, not free-form text rules.
