---
name: feedback_plain_language_explanations
description: Explain diagnoses and designs in plain natural language, not internal identifiers
metadata:
  type: feedback
---

When explaining a bug diagnosis, plan, or design trade-off to the user, lead with
**plain natural language** — describe behavior in everyday terms ("the line that
explains a goal", "the optimizer's setup"), not a wall of code identifiers
(`config-weight-<key>`, `_apply_assumption_actions`, `goal_terms`).

**Why:** the user found a jargon-dense explanation hard to follow — "Can you
explain things in laypeople natural language? Too many variable names." They reason
about the *product behavior*, then drill into code only when needed.

**How to apply:** put the plain-English account first (what the user/participant
sees, what went wrong, the fix in one breath). Keep exact function/variable names
for the plan's implementation sections and code, where precision is required — or
in a clearly separate "technical detail" follow-up. One representative identifier
inline is fine; a paragraph of them is not. See [[feedback_no_prompt_bandages]] for
the related instinct to frame fixes as ownership/behavior, not mechanism.
