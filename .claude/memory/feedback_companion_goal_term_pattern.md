---
name: feedback_companion_goal_term_pattern
description: The reusable "companion goal term" pattern (parent term + structured child) and its 4 guaranteed behaviors
metadata:
  type: feedback
---

A **companion goal term** is a goal term that owns a structured child carrier — a
list of rules (VRPTW `worker_preference` → `driver_preferences`) or a scalar
(`shift_limit` → `max_shift_hours`). The user asked for this to be ONE reusable
pattern any problem inherits, not per-term hacks.

**Why:** repeated P_0603 bugs were all the same shape — hollow parent committed,
rule parked in `ambiguity_note`, prose row instead of the array, term silently
vanishing. The fix is structural, declared once via the port.

**How to apply:** a port opts in with `gate_conditional_companions() ->
{parent_key: companion_field}` (plus `companion_present`,
`companion_open_question_text`, `goal_term_companion_summary`,
`prose_id_prefixes_for_goal_term`). The generic layer then guarantees:
- **B1** vague mention → agent asks, no empty term (reconcile drops a new hollow
  term when the turn made NO claim — `turn_claimed_change=False`).
- **B2** concrete child → parent term + child appear; if the LLM fumbles the
  carrier the term is KEPT (claim turn) with an OQ, never silently lost.
- **B3** add more children via chat / def panel (type a rule in plain language →
  LLM structures it, NOT regex) / config panel's structured editor.
- **B4** `port_companion` over-claim check (new hollow commit AND pre-existing
  prose-row leak) → one+ retry → graceful deferral to the OQ floor (never pauses).

**The main agent is unreliable at populating list companions** (acknowledges the
rule in prose, omits the array — failed across new-term, chat-append, def-edit;
P_0603). The backstop is a **deterministic extractor**: in
`apply_brief_patch_with_cleanup`, when a turn committed a companion term + claimed
a change but the array didn't move, `_extract_missing_companion_rules` runs a
focused structured-output Gemini call (`llm.extract_companion_rules`, schema from
`goal_term_properties_schema`, instructions from the new port hook
`companion_extraction_instructions`) on the participant's wording + the companion
row prose → returns the complete rule list → populates the carrier BEFORE
reconcile/synthesize. Fail-safe (None leaves the brief untouched), generic, opt-in
per port. Don't rely on prompt nudges to make the agent populate — they don't stick.

**Def-panel saves: `context_kind="definition_save"`.** The frontend tags a
definition save with this kind (NOT `"brief_edit_ack"`). `is_brief_edit_context_message`
must accept it — for a long time it only honoured `"brief_edit_ack"`, so every def
edit was misclassified as plain `chat`, the brief-edit path never ran, and def
companion edits silently failed (P_0603, many cycles). **Def-edit companion rules
are structured deterministically AT THE SAVE** in `router._structure_companion_rule_edits`
(PATCH handler): if a `config-weight-<key>` row's text differs from what the carrier
would synthesize, run `llm.extract_companion_rules` on it → populate the carrier +
drop the stale `ambiguity_note`. Don't rely on the follow-up chat turn for this.
The S2 `port_companion` over-claim check is SUPPRESSED for terms with an extractor
(`companion_extraction_instructions`) — the extractor populates reliably, so the
retry was just noise ("failed a bunch of times"). Synthesized companion rows use
the port's `goal_term_rationales` (not the agent's `ambiguity_note` narration).

Keep-vs-drop hinges on `change_clause`: it's threaded from the runner →
`apply_brief_patch_with_cleanup(change_clause=...)` →
`reconcile_companion_oqs(turn_claimed_change=...)`. Frontend: parent-"X" clears
children via `WeightRow` `extraRemovePatch`/`extraRestorePatch` (or a `keySlot`'s
copies for generic rows); `ProblemModule.definitionRowFootnote` hints the def row.
Decision with user: empty parent shows ONLY when a child was actually given (B1
vs B2). See [[feedback_structured_carrier_same_turn]], [[feedback_no_regex_for_nl]],
[[feedback_no_prompt_bandages]].
