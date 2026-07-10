---
name: feedback_algorithm_change_after_oq
description: A waterfall user request to CHANGE the search algorithm after the initial choice (OQ closed) had no deterministic carrier commit — the model wrote prose but forgot properties.algorithm, so the panel never changed.
metadata:
  type: feedback
---

Search-strategy / algorithm lives in the brief carrier
`goal_terms.search_strategy.properties.algorithm`; the panel mirrors FROM it. In
waterfall the deterministic committer is `classify_user_search_strategy_choice`
(reads the participant's own message) → `gate_unauthorized_search_strategy_commit`
→ `_set_search_strategy_algorithm`, so the choice never depends on the model
populating the carrier.

**The gap (session 7d4b9eaf):** that classifier only ran when a search-strategy
OQ was OPEN (`_has_open_search_strategy_oq`) — i.e. the INITIAL choice. After the
algorithm was decided (GA committed, OQ closed), a later "try swarm search"
request had no deterministic path: the main-turn model wrote the prose row
(`config-search-strategy` = "PSO"), the rationale ("switched to PSO"), and the
visible reply, but omitted the carrier `properties.algorithm` — so it stayed GA
and the panel algorithm never moved (Run #8 still ran GA). Classic
[[feedback_structured_carrier_same_turn]]: prose committed, structured carrier
not. The gate returned early because base was already `brief_mentions_search_strategy`
(GA authorized), leaving the model's patch untouched.

**Fix:** also run the classifier when THIS turn's patch touches
`goal_terms.search_strategy` (`_turn_touches_search_strategy` in
chat_pipeline_runner) — a participant-driven CHANGE, not only an open OQ. The
classifier pins the real algorithm from the user's message and the gate's
`user_choice` branch commits it.

**Symmetry (agile == waterfall for user-initiated changes).** A user-initiated
search-strategy change must behave the same in both modes — only the INITIAL
default policy and the forgery guard are waterfall axes ([[project_workflow_axes]]).
So: (a) the classifier now runs in BOTH modes on a search-strategy-touching turn
(dropped the `workflow_mode=="waterfall"` guard at the call site); (b) in
`gate_unauthorized_search_strategy_commit` the explicit-user-choice commit moved
ABOVE the waterfall-only early-return, so it fires in agile/demo too, while the
forgery-strip below stays waterfall-only. Agile with NO user choice still keeps
the model's fait-accompli carrier (axis preserved).

**Parameters (epochs/pop_size/algorithm_params).** No deterministic extraction
from the user message in either mode — the classifier returns algorithm only
(`llm.py`) — so an explicit numeric change rides the model-populated carrier.
Key facts that bound the risk: (1) BOTH solvers start from
`default_algorithm_params(algo)` and `.update(explicit)` at solve time
(`vrptw_problem/optimizer.py`, `knapsack_problem/mealpy_solve.py`), so a
missing/partial param set is completed at run time — a partial set is cosmetic,
not a run bug. (2) `sanitize_panel_config` already drops stale keys on an
algorithm switch and fills full defaults when params are empty. So the ONLY
functional gap was: an explicitly-committed `algorithm_params` value in the
carrier never reached the panel (epochs/pop_size were mirrored, params weren't),
so a chat "set inertia to 0.6" could be dropped before the solver saw it.

**Fix (silent, backend-only, mid-recruitment safe):** added `algorithm_params`
to the carrier→panel mirror in `sync.py` (same safety net as epochs/pop_size).
Explicit param wins; stale keys are filtered by sanitize; the solver defaults
the rest. Did NOT touch the sanitizer's partial-set completion (cosmetic only)
or the prompt (would change visible behavior). A deterministic user-message
param classifier (epochs/pop_size) is a possible follow-up, not built.
Test: `test_sync.py::test_carrier_algorithm_params_mirror_reaches_panel`.
Related: [[feedback_panel_authoritative_for_algorithm]],
[[feedback_structured_carrier_same_turn]].
