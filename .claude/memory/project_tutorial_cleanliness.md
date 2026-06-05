---
name: project_tutorial_cleanliness
description: The in-app tutorial must stay scripted/friction-free — deterministic suppressions of OQs/interventions while is_tutorial_active
metadata:
  type: project
---

The in-app tutorial (knapsack practice problem) must stay **scripted and
friction-free** — the participant follows bubble-driven steps and should only
ever face the guided questions, never freeform agent noise. The user is
strongly allergic to "random stuff popping up" mid-tutorial. Prompt nudges
(`STUDY_CHAT_TUTORIAL_GUARDRAILS` already says "Don't invent extra
clarifications") are NOT enough — the agent ignores them — so enforcement is
DETERMINISTIC ([[feedback_no_prompt_bandages]]), gated on `is_tutorial_active`.

`is_tutorial_active` = `participant_tutorial_enabled and not tutorial_completed`
(or demo mode). Threaded from the router through `run_chat_pipeline` →
`_apply_stage` → `apply_brief_patch_with_cleanup` → `_enforce_session_monitors`
(and the retry path via `retry_context`).

Deterministic tutorial suppressions in `_enforce_session_monitors` (June 2026):
1. **Freeform LLM clarification OQs stripped.** Keep ONLY server-owned OQs:
   canonical monitors (`oq-monitor-*`) and structural companion asks
   (`auto-oq-companion-*`). Everything else (LLM `topic:other` clarifications
   like *"should the capacity be a hard limit or a soft penalty?"*, id
   `question-1`) is swept every pass — self-heals if regenerated (P_lk).
2. **Plateau intervention suppressed entirely** (Monitor 4) — no `oq-monitor-
   plateau` in either mode during the tutorial (tutorial runs are too similar to
   justify it). See [[project_workflow_axes]] for the plateau being symmetric.
3. **Run-ack invariant relaxed** for tutorial Runs 1+2 (`suppress_runack_
   invariant`) — the bubble flow isn't blocked by a freshly-raised OQ/assumption.

Foundational monitor OQs (upload / primary_goal / search_strategy) are KEPT —
they're the guided flow (e.g. the waterfall tutorial answers the search-strategy
OQ with "Use GA"). A stripped OQ clears on the NEXT chat turn (the monitor runs
per turn), not retroactively on load.
