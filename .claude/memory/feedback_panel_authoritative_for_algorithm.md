---
name: feedback_panel_authoritative_for_algorithm
description: Algorithm changes have 3 sources (chat, brief panel, config panel); each drives the sync in its own direction and that side wins
metadata:
  type: feedback
---

The search-strategy algorithm is stored in two canonical places that must stay in lockstep: brief carrier `goal_terms.search_strategy.properties.algorithm` and `panel.problem.algorithm` (the value the solver runs). It can be changed from **three surfaces**, and authority follows whichever surface the user touched:

| Source | Endpoint | Sync function | Direction | Wins |
|---|---|---|---|---|
| **Chat** (tell the assistant "use GA") | chat pipeline | `sync_panel_from_problem_brief` | carrier→panel | brief |
| **Brief/Definition panel** | PATCH `/problem-brief` | `sync_panel_from_problem_brief` | carrier→panel | brief |
| **Config panel** (Config tab Save) | PATCH `/panel` | `sync_problem_brief_from_panel` | panel→carrier | panel |

Each direction is a DETERMINISTIC mirror, not an LLM reconciliation:
- `sync_panel_from_problem_brief`: when the carrier holds a concrete algorithm it WINS and overwrites `panel.algorithm` (also epochs/pop_size). Pre-existing.
- `sync_problem_brief_from_panel`: when the panel holds a concrete algorithm it WINS and overwrites the EXISTING carrier (re-anchoring evidence to `config-search-strategy`). This was the **missing** mirror — the carrier was preserved verbatim, so a config-panel ACOR→GA edit froze the carrier at ACOR (P_0602). Drift then resolved the WRONG way ("set panel to ACOR"), reverting the user's edit in a loop — including in the config-save retry fallback (`merge_brief_from_panel`).

**The search-strategy TRIAD (P_0602, June 2026):** the choice lives in THREE synced spots — the carrier, `panel.problem.algorithm`, AND the `config-search-strategy` items[] row (synthesized from the panel by `_brief_items_from_panel`; it's the Definition row + a `brief_mentions_search_strategy` signal). `search_strategy` is a **carrier-only goal term** (`CARRIER_ONLY_GOAL_TERM_KEYS`) so the canonical synthesizer SKIPS it (no `config-weight-search_strategy`). Two failure modes fixed together:
- **Apply drops the anchor.** `_drop_redundant_goal_term_anchors` drops a new goal-term's evidence row expecting synthesis to replace it — but for carrier-only keys nothing replaces it. Fixed: that sweep now skips `CARRIER_ONLY_GOAL_TERM_KEYS`, so `config-search-strategy` survives.
- **Waterfall gate strips an affirmed choice.** `gate_unauthorized_search_strategy_commit` authorizes a chat commit only if the USER'S OWN message names an algorithm (`classify_user_search_strategy_choice`). When the user DEFERS ("what do you suggest?"), the agent proposes GA + asks "how's that sound?", and the user AFFIRMS ("sounds good"), the affirmation names nothing → gate treated the GA carrier as forged and stripped it. Fixed: the classifier now also takes the agent's immediately-preceding visible message (`agent_prompt`, pulled from `history_lines` in `_apply_stage`) and resolves the affirmed proposal. Bare affirmation with no proposal still → None (no over-auth).

**How to apply:** Never make one global "X always wins"; the winner is the surface the user edited, enforced by which sync function that endpoint calls. `sync_problem_brief_from_panel` callers are all panel-authoritative (config save, config-save retry fallback, resync-from-panel, starter init). Only UPDATE an existing carrier from the panel — don't fabricate one from a panel default (a missing carrier is acceptable since the key is carrier-only/optional and produces no drift; creation stays owned by chat commit / monitors / the waterfall authorization gate, which distrusts the chat agent but not a user's direct panel edit). Related: [[feedback_structured_carrier_same_turn]], [[feedback_no_prompt_bandages]], [[feedback_dynamic_algorithm_oq]].
