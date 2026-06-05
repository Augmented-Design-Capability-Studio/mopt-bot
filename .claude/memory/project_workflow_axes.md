---
name: Agile vs Waterfall — the 4 canonical differences
description: The four axes along which agile and waterfall MUST differ; everything else MUST be symmetric
type: project
---

The 2×2 study (workflow × user-expertise) treats workflow mode as a
controlled variable. The two workflow modes (`agile` and `waterfall`)
differ along EXACTLY FOUR axes — these are the experimental
manipulation. Every other behaviour, rule, or code path MUST be
symmetric.

When auditing prompts or code:
- A rule that fits one mode but not the other AND isn't one of these
  four axes is asymmetric drift — move it to a shared block.
- A rule that's identical in both modes is redundant — extract it to
  the shared layer (master system prompt, items/grounding discipline,
  run-ack base, etc.).

| # | Axis | Waterfall | Agile |
|---|---|---|---|
| 1 | **OQ policy** | Primary elicitation mechanism. Cap 3 active. Phase order: scope → trade-offs → algorithm. Add ≤1/turn. | Sparingly — uploads or true must-choose forks only. Zero OQs is fine. |
| 2 | **Assumption policy** | NONE. No `kind: "assumption"` rows. Provisional content goes in `open_questions`; add to `gathered` only after explicit confirmation. | Default for filling gaps. Commit same-turn with `evidence_item_ids` cite. Cap 1 new/turn, ~3–5 active. Promote to gathered only on explicit user confirm. |
| 3 | **Run gate (server-enforced)** | Symmetric requirements **plus** zero open-status OQs. | Symmetric requirements only. |
| 4 | **Search-strategy default** | Ask via OQ; never silently set. | Commit `algorithm: "GA"` same turn as a `kind: "assumption"` items[] row that NAMES the algorithm. |

**Symmetric requirements (shared, NOT in workflow addendums):**
- `gate_engaged` + `has_uploaded_data` + qualifying goal-term + algorithm on panel.
- Upload-before-run-invite (master prompt's "Upload warm-up behavior").
- Claim-implies-patch invariant (`visible_reply_consistency_block` for brief LLM; pre-release probe enforces deterministically).
- Provenance follows origin, not phrasing (`STUDY_CHAT_HIDDEN_BRIEF_ITEMS_RULES`).
- A USER-stated fact (esp. a clearly-stated primary objective, "minimize travel time") is `gathered` in BOTH modes and must commit SAME turn — it is NOT "provisional content". Waterfall's "confirm before gathered" gate is ONLY for AGENT-proposed content; deferring a user-stated goal into an OQ strands the brief with no goal_term and leaves the server goal-monitor OQ (`oq-monitor-goal`, drops only on non-empty `goal_terms`) up "as if the user said nothing" (P_0602 — fixed in `STUDY_CHAT_WORKFLOW_WATERFALL` assumption-policy block, NOT via any keyword/seed). Agile already committed, so the bug was waterfall-only.
- Concept-only turns emit `null` problem_brief_patch (master system prompt).
- After-run: relate to stated goals; ≤2 config-linked refinements; lead with operational impact (`STUDY_CHAT_RUN_ACK_BASE`).
- No brief items describing the agent's role / capabilities (`STUDY_CHAT_ITEMS_DISCIPLINE`).
- Gate-driven elicitation: act on `## Run-gate status` block — mode dispatches the action (waterfall asks, agile commits). The trigger is the same; only the response differs.

**Demo mode** is a third variant primarily for screen recordings: behaves like waterfall on OQs (no cap) but assumptions are essentially absent (closer to waterfall on axis 2). Demo is workflow-neutral in framing — never explain "agile vs waterfall" to demo participants.

**Where the 4 axes show up in code (current):**
- `optimization_gate.py:can_run_optimization`: axis 3 (waterfall blocks runs while any OQ has `status: "open"`).
- `problem_brief.py:coerce_problem_brief_for_workflow`: axis 2 (waterfall converts assumption→OQ; demo drops assumptions).
- `routers/sessions/derivation.py:_enforce_session_monitors` (monitor 3 branch): axis 4 (agile/demo emit `item-monitor-algorithm-default` assumption row; waterfall emits `oq-monitor-algorithm` OQ).
- `services/goal_term_anchoring.py:evidence_kinds_for_workflow`: axis 2 (waterfall: `gathered` only; agile/demo: `gathered + assumption`).
- `services/pipeline_verification.py:verify_brief_consistency`: axis 2 (waterfall flags any `kind: "assumption"` row) + axis 1/2 run-ack invariants (agile must ADD OR UPDATE an assumption row — re-tuning an existing one counts, see `_agile_assumption_added_or_updated`; waterfall must add an OQ). These are best-effort: they drive S2 retries but are NON-blocking after exhaustion (`chat_pipeline_runner.py` `NON_BLOCKING_CATEGORIES`), because the deterministic run summary (`derivation.consolidate_runs` → `brief.runs`) lives in S3 — pausing over a missing assumption used to silently drop the run's summary entry AND corrupt `_detect_run_plateau`'s window (P_0603, post-run #7).
- `prompts/study_chat.py:STUDY_CHAT_WORKFLOW_{WATERFALL,AGILE,DEMO}`: each addendum covers all 4 axes for its mode; nothing else.
- `prompts/study_chat.py:STUDY_CHAT_RUN_ACK_{WATERFALL,AGILE,DEMO}`: post-run delta discipline per axis 2.
- `prompts/study_chat.py:STUDY_CHAT_OQ_CLASSIFY_TASK` workflow gating: axis 2 (waterfall: hedged→new OQ; agile: hedged→assumption; demo: like waterfall).

**Plateau intervention is SYMMETRIC (researcher decision, June 2026).** Monitor 4 in `_enforce_session_monitors`: when the last 2 completed runs stall on the same algorithm, BOTH modes now raise the same `oq-monitor-plateau` OQ on the run-ack turn (`topic: search_strategy`). Agile used to silently auto-switch the carrier (fait accompli via the now-removed `_next_search_algorithm`); the researcher chose symmetry so the participant owns the call in both modes. NOT one of the 4 axes — keep it symmetric. SUPPRESSED entirely while the tutorial is active (`is_tutorial_active`, threaded through `apply_brief_patch_with_cleanup`/`_apply_stage`/retry-context) — tutorial runs are too similar to justify it. Note this is distinct from axis 4 (the *initial* search-strategy default, which stays asymmetric: agile assumption row vs waterfall OQ).

**Not mode-branched (intentionally symmetric):** OQ ownership (server owns foundational topics via `merge_problem_brief_patch` foundational-topic strip + `_enforce_session_monitors`), brief↔panel drift detection, pipeline shape, retry budget, failure UX.

**Why this matters:** the study's whole point is comparing the two modes. Drift that collapses or scrambles the axes invalidates the comparison. Don't add mode-specific code paths or prompt rules for anything other than these four — and when you must, document which axis you're implementing.
