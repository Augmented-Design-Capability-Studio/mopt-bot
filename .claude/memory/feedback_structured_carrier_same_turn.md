---
name: Structured goal-term carriers must populate on the introducing turn
description: When the visible reply commits to a rule whose goal_terms entry has a properties shape (e.g. worker_preference→driver_preferences, shift_limit→max_shift_hours), populate the structured carrier in the same turn — not just a prose items[] row
type: feedback
---

For VRPTW (and any future port whose goal terms expose a
`properties` sub-schema), the brief-update LLM must populate the
structured carrier in the **same turn** the rule is introduced. Writing
only a prose `items[]` row about the rule causes:

1. The panel never receives the structured rule (panels read from
   `goal_terms[key].properties`, not from prose rows).
2. The deterministic synthesizer (`synthesize_brief_items_from_goal_
   terms`) skips the row because it reads from `goal_terms.worker_
   preference.properties.driver_preferences`, which is empty.
3. The anchor filter may drop the goal_terms entry entirely
   (`is_goal_term_self_anchored` requires the rule list to be non-
   empty for self-anchoring).
4. On a later turn, the LLM re-reads the brief, sees the surviving
   prose row, and finally emits the structured carrier — making the
   rule "flicker in" only after a delay. Two unrelated terms can then
   appear in the same later turn, which the user perceives as
   instability.

**Why:** observed during VRPTW agile session — *"can you add something
for Alice who doesn't like zone D?"* produced a prose row but no
`worker_preference` carrier. The next turn's request ("add a max shift
limit") landed both `worker_preference` AND `shift_limit` together.

**How to apply:**
- VRPTW carrier paths live in
  `vrptw_problem/study_prompts.py::DRIVER_PREFERENCES_BRIEF_CONTRACT`.
- The brief-update prompt in
  `backend/app/services/llm.py::_build_brief_update_system_instruction`
  carries a generic "structured carrier → populate same turn" rule in
  the visible-reply check; problem-specific carrier paths come from
  the per-problem appendix.
- When adding a new goal-term key with `properties` for a port,
  document the carrier path in that port's `study_prompts.py` and
  reinforce same-turn emission. Don't rely solely on the prose
  `items[]` row — that's a downstream artifact of the structured
  carrier, never a substitute for it.
