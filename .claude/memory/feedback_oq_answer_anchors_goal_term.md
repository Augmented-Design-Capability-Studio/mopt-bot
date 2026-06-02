---
name: feedback_oq_answer_anchors_goal_term
description: A goal term the user approves by answering an OQ must survive the anchor filter — answered OQs anchor their committed key
metadata:
  type: feedback
---

When the participant **answers an OQ** (the turn's `oq_actions` drop/mark_answered it) and the main turn commits the OQ's `goal_key` in the same patch, that key must be treated as **anchored** in `filter_unanchored_new_goal_terms` (`answered_oq_keys`), NOT premature-dropped via `pending_oq_keys`.

**Why:** P_0602 — user approved two proposed penalties as hard ("yes, add them, make them hard"). The main turn correctly emitted `goal_terms` (capacity_penalty/lateness_penalty, type hard) + `oq_actions: drop`. But the anchor filter ran while the OQs were still open (drop happens a step later in `_apply_oq_actions`), saw `goal_key` matching an open OQ, and premature-dropped both terms as "the LLM is still asking". Then the OQs were dropped too → approval silently erased: OQs resolved, no goal terms, no gathered items.

**How to apply:** The discriminator between a *premature ask* and an *answer+commit* is whether THIS turn's `oq_actions` resolve the OQ. Plumb the turn's `oq_actions` into `apply_brief_patch_with_cleanup` → compute `answered_oq_keys` from resolved-OQ `goal_key`s → pass to the filter, where it takes precedence over `pending_oq_keys`. Once the term survives, `_synthesize_canonical_weight_items` makes the `config-weight-<key>` gathered row and `_resolve_anchored_provisional_rows` resolves the OQ with visible evidence. Cross-stage invariant: OQ-lifecycle and goal-term-anchoring decisions within one turn must agree. Related: [[feedback_structured_carrier_same_turn]], [[feedback_no_prompt_bandages]].
