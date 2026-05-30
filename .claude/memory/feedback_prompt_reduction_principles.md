---
name: feedback_prompt_reduction_principles
description: "How the user wants the chat prompt/verification reworked — state-aware loading, caching, compress-for-accuracy, keep deterministic safeguards"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c7cf2dc7-e536-4245-ba64-f781ac66937f
---

The chat system prompt is too long (~7k words/main turn) and that length itself causes the LLM to ignore rules (e.g. P_0529). When reducing it, the user wants these principles honored:

**Why:** A wall of always-on prose dilutes attention; the LLM drops rules buried in it. But cost and accuracy are different problems with different fixes.

**How to apply:**
- **State-aware prompting.** Think like a human programmer: at each chat stage/state (cold start, warm-defining, run-ack, config-save, brief-edit-ack, upload, tutorial, concept) the agent needs *different* things in mind. Load guidance by the turn-state the server already knows (the `is_*` flags + cold/warm/hot + workflow_mode) — NOT by parsing user_text (respects [[feedback_no_regex_for_nl]]).
- **Compress for accuracy, cache for cost.** Shortening what the LLM attends to helps accuracy. Context-caching the static blocks (Gemini cache, already used for config-derive via `_get_or_create_system_cache`) cuts cost/latency on redundant re-sends but does NOT help accuracy. Use both, for their separate purposes.
- **The brief is the running memory** — sent each turn as state. Don't duplicate brief facts into static prose.
- **Division of labor:** the LLM is unreliable at *logic* — keep/strengthen deterministic verification + structural gates for ownership/precedence/invariants (see [[feedback_no_prompt_bandages]], [[project_workflow_axes]]). The LLM is good at *summarizing/expanding* — lean on it for the visible reply and prose synthesis.
- **Preserve all behavioral rules** when compressing (no rule deleted unless a gate now owns it). **Keep agile/waterfall symmetric** except the 4 canonical axes. **Don't damage the tutorial** (tutorial guardrails stay loaded on tutorial turns). Keep the flow predictable in both modes.
- **Keep the single main-turn call** (reply+patch together): it makes reply and patch consistent-by-construction and the pipeline self-corrects the reply on verification failure. Reply-first splitting was rejected because it makes incorrect replies *more* likely. See [[project_architecture]].
- Method that works: compress a block in place, keep every rule, update the `test_main_turn_prompt_assembly.py` word-budget snapshot (the measured delta), run the `live_gemini` tests to confirm behavior held.
