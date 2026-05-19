# In-App Participant Tutorial — Knapsack Flow

The first thing a participant does in the live session (after the orientation
video) is the **in-app tutorial**: a guided 12-step bubble overlay on the
knapsack benchmark that walks them through the chat → definition → config →
run → iterate loop before they tackle the real QuickBite VRPTW task.

This doc nails down what the agent and pipeline are expected to produce on each
of those steps so we can tell genuine bugs apart from prompt drift. The
step-by-step copy lives in
[`frontend/src/tutorial/defaultContent.ts`](../../frontend/src/tutorial/defaultContent.ts)
(generic fallbacks) and
[`knapsack_problem/frontend/tutorial.ts`](../../knapsack_problem/frontend/tutorial.ts)
(knapsack overrides). **Do not change the step content in those files when
touching this doc** — the spec here is the contract the implementation has to
meet, not a new script.

The user-facing step list is also referenced from
[`docs/.study_plan/ORIENTATION_VIDEO_SCRIPT.md`](ORIENTATION_VIDEO_SCRIPT.md);
that script covers the demo recording, not the participant tutorial.

## Mode matrix (the only axes that vary)

Tutorial guardrails (`STUDY_CHAT_TUTORIAL_GUARDRAILS` in
[`backend/app/prompts/study_chat.py`](../../backend/app/prompts/study_chat.py))
narrow the agent's output budget but do not change the four canonical
agile/waterfall differences ([`AGILE_VS_WATERFALL.md`](AGILE_VS_WATERFALL.md)):

- **Waterfall** — uses **open questions** to elicit, gates the first run on
  every OQ being answered, asks for the search strategy via a canonical OQ,
  never silently assumes a default.
- **Agile** — uses **assumptions** to fill gaps the same turn, commits genetic
  search (GA) as an assumption row, does not gate the run on open questions.

## Step 1 — Chat info (knapsack starter prompt pasted, submitted)

The participant clicks **Use starter prompt** in the bubble; the chat input
fills with the canonical knapsack framing:

> *I would like to optimize for a simple knapsack problem. I have a list of 22
> items with various values and weights to put into a bag of 50-weight
> capacity. I want to maximize the value in the bag without exceeding the
> capacity limit.*

The participant submits. After the pipeline settles, the brief and panel must
satisfy the following invariants.

### Definition tab — both modes

Canonical goal-term gathered rows appear:

- `Total packed value (objective, weight 1.0) — to push the solver toward
  higher-value selections.`
- `Knapsack capacity overflow (soft, weight ≈ 40) — to discourage exceeding
  the knapsack capacity.`

Backing this, `brief.goal_terms` carries `value_emphasis` (objective) and
`capacity_overflow` (soft). Both keys are in
`KnapsackStudyPort.auto_anchored_goal_term_keys()`, so the brief anchor filter
admits them without a separate items[] cite. If the V2 brief patch omits these
two keys but the panel-derive step puts them in `panel.problem.goal_terms`
(via the canonical concept mapping), the chat pipeline runs the
*auto-anchored backfill* (`_backfill_auto_anchored_from_panel` in
[`backend/app/services/chat_pipeline_runner.py`](../../backend/app/services/chat_pipeline_runner.py))
and mirrors them into `brief.goal_terms` before S5 verifies parity. The
backfill is cold-start only — it skips once any goal term is in the brief, so
subsequent retirements aren't reverted.

`selection_sparsity` does **not** appear unless the participant explicitly
asked for fewer items. The phrase "*items in the bag*" in the starter prompt
is not a sparsity ask.

### Open questions

- **Waterfall — exactly two canonical monitor OQs:**
  1. `oq-monitor-upload` — *Please use the Upload file(s)... button in the
     chat footer to share your data so we can set up a baseline run.*
  2. `oq-monitor-algorithm` — *Which search strategy should we use? Common
     choices: genetic search (GA), particle swarm (PSO), or simulated
     annealing (SA).*

  The `oq-monitor-goal` row **must not** appear: `brief.goal_terms` is
  non-empty after this turn, so the goal-term monitor in
  `_enforce_session_monitors` drops it. If the brief is wired correctly but
  the OQ still surfaces, the bug is in the monitor or the auto-anchored
  backfill, not in the prompts.

- **Agile — one canonical monitor OQ:**
  1. `oq-monitor-upload` — same text as above.

  Plus one canonical assumption items[] row:
  - `item-monitor-algorithm-default` — *Search strategy is set to genetic
     search (GA) as a starting point — change anytime.*

### Pipeline verification (S2 + S5)

- **S2 brief verification** — must report zero issues. The goal-term anchoring
  service accepts `value_emphasis` and `capacity_overflow` via the
  auto-anchored opt-out, so the brief's `goal_terms` map is admitted whether
  or not the LLM added explicit `evidence_item_ids` cites.
- **S5 panel verification** — must report zero issues. `brief.goal_terms` and
  `panel.problem.goal_terms` must contain the same key set. The historical
  failure mode this doc exists to flag was *missing_in_brief* drift on
  `value_emphasis` / `capacity_overflow` — that signals the auto-anchored
  backfill didn't run or the V2 brief patch omitted both keys *and* the
  backfill couldn't find them on the panel.

### Canonical goal-term OQ wording

When the goal-term monitor OQ does fire — which it should not, on this
canonical first turn — the text comes from `_monitor_goal_oq_text` in
[`backend/app/routers/sessions/derivation.py`](../../backend/app/routers/sessions/derivation.py)
and derives its examples from the active port's `weight_item_labels()` plus
`weight_display_keys()`. For knapsack that produces "Total packed value /
Knapsack capacity overflow / Number of selected items" — not VRPTW vocabulary.
If you see *"minimize total travel time, meet customer time windows, balance
driver workload"* on a knapsack session, the helper isn't being called with
the active `test_problem_id`.

## Step 2 — Upload knapsack data

Bubble: **Upload knapsack data**. The participant uses the chat-footer
**Upload file(s)...** control and picks the bundled knapsack item file.

- A `gathered` row with id `item-gathered-upload` (source `upload`) appears in
  the Definition tab.
- The canonical `oq-monitor-upload` open question is dropped (in both modes).
- The agent's reply acknowledges the upload and may post a short rolling
  summary; no extra "Files uploaded: …" duplicate row appears (the
  `STUDY_CHAT_UPLOAD_CONTEXT_GUIDANCE` discipline forbids it).

## Step 3 — Update Definition (Save once)

Bubble copy is mode-aware (`update-definition` override in
[`knapsack_problem/frontend/tutorial.ts`](../../knapsack_problem/frontend/tutorial.ts)):

- **Waterfall** — the bubble tells the participant to answer the two OQs
  inline before the first run unlocks. Answering the algorithm OQ
  commits a `search_strategy` carrier on the brief and removes
  `oq-monitor-algorithm`. After Save, both canonical monitor OQs are gone.
- **Agile** — the bubble tells them to promote the algorithm assumption (or
  edit it) and Save. After Save, the assumption row is promoted to
  `gathered` if they ticked the ✓; otherwise it stays as an `assumption`.

## Step 4 — Set up Run 1 (intentionally weak penalty)

Bubble: **Set up Run 1**. The participant switches `capacity_overflow` to
**Custom** with weight `1`, then Saves.

- `panel.problem.goal_terms.capacity_overflow` carries `{weight: 1, type:
  "custom", locked: true}` — Custom locks the user-set weight so subsequent
  derivations don't overwrite it.
- The matching brief row text re-renders as
  `Knapsack capacity overflow (custom, weight 1.0) — …` on the next sync.

## Step 5 — First run (probably infeasible)

The participant clicks **Run optimization**. With the weak capacity penalty
the result usually packs over the 50-unit limit; that's expected — the
tutorial uses the overrun to teach what infeasibility looks like.

## Steps 5 + 10 run-ack — symmetric tutorial suppression

The post-run agent reply for Run 1 (Step 5) and Run 2 (Step 10) is
deliberately narrowed in tutorial mode:

- The chat reply is 1–2 short sentences naming what happened (feasibility,
  cost direction). No proposal, no run invitation, no follow-up question.
- **No new `open_questions`** are added (waterfall's usual "raise a new OQ
  every run-ack" rule is suppressed).
- **No new `kind: "assumption"` rows** are added (agile's usual "commit a
  new assumption every run-ack" rule is suppressed).
- **No new `goal_terms` entries.** The bubble's next-step action carries
  the change.

This is enforced three ways, in order of load-bearing-ness:

1. **Deterministic strip (load-bearing)** —
   `_strip_runack_additions` in
   [`backend/app/routers/sessions/derivation.py`](../../backend/app/routers/sessions/derivation.py)
   runs inside `apply_brief_patch_with_cleanup` whenever
   `suppress_runack_invariant=True`. It drops any **new** OQs (ids not in
   `base.open_questions`), **new** `kind: "assumption"` items[] rows, and
   **new** `goal_terms` keys. Existing entries pass through, so answers
   to prior OQs and retunes of existing terms work normally. This is
   what actually makes the contract reliable — the LLM is free to ignore
   the prompt nudge and the strip will still catch it.
2. **Verifier** — `verify_brief_consistency`
   ([`backend/app/services/pipeline_verification.py`](../../backend/app/services/pipeline_verification.py))
   accepts a `suppress_runack_invariant` flag; both the agile
   "must-add-assumption" and waterfall "must-add-OQ" branches short-circuit
   when set, so verification doesn't fail the turn for an empty patch.
3. **Prompt** — the existing `STUDY_CHAT_TUTORIAL_GUARDRAILS` block in
   [`backend/app/prompts/study_chat.py`](../../backend/app/prompts/study_chat.py)
   carries the "post-run turns (Runs 1 + 2)" bullet. Token-saver only —
   removes the strip's workload when the LLM cooperates.

The flag is computed once at the top of `_run_chat_pipeline_thread`
([`backend/app/services/chat_pipeline_runner.py`](../../backend/app/services/chat_pipeline_runner.py))
as:

```python
is_tutorial_active AND is_run_acknowledgement AND completed_ok_runs <= 2
```

`completed_ok_runs` is a direct count of `OptimizationRun` rows with
`ok=True` for the session — more deterministic than the
`tutorial_*_run_done` flags, which the frontend flips after the result
message lands and can race the ack turn.

## Step 12 run-ack — Run 3 returns to normal

The third run's ack falls outside the suppression window
(`completed_ok_runs == 3 > 2`). The agent can — and is expected to — add
OQs or short assumptions that invite the participant to keep exploring
once the scripted loop is over.

## Steps 6 – 11 — Read, inspect, explain, retune

Steps 6 – 9 + Step 11 follow the generic 12-step copy
([`defaultContent.ts`](../../frontend/src/tutorial/defaultContent.ts)) with
knapsack-flavoured wording. They do not exercise the chat/brief/panel state
machine in the same load-bearing way as Steps 1 – 3 or the run-ack steps;
check them against the default-content file rather than re-specifying here.

## Closed-vocabulary brief goal_terms (deterministic strip)

The brief patch path strips any `goal_terms` keys outside the active
port's vocabulary — `port.weight_display_keys()` plus the carrier-only
`search_strategy`. For knapsack the allowed set is
`{value_emphasis, capacity_overflow, selection_sparsity, search_strategy}`.

This catches LLM paraphrases like `total_value` or `efficient_packing`
that previously slipped past the anchor filter and surfaced as
`missing_in_panel` drift on every chat turn (panel-derive can't admit
them, brief still carries them, S5 reports drift, retry doesn't help).
The strip is deterministic and runs in `apply_brief_patch_with_cleanup`
right after the patch merge, before any anchor or panel derivation work.
See `_strip_unknown_goal_term_keys` in
[`backend/app/routers/sessions/derivation.py`](../../backend/app/routers/sessions/derivation.py).

## When this contract is violated

Common bug shapes:

1. **`missing_in_brief` drift on `value_emphasis` or `capacity_overflow`
   after Step 1.** Cause: V2 brief patch committed only prose items, panel
   has the goal terms, but the auto-anchored backfill didn't fire or
   couldn't find them. Check the order in `_run_derive_and_verify_stages`
   in `chat_pipeline_runner.py` and confirm
   `KnapsackStudyPort.auto_anchored_goal_term_keys()` still returns all
   three keys.
2. **`oq-monitor-goal` fires on Step 1 with VRPTW-flavoured examples.**
   Cause: `brief.goal_terms` is empty after Step 1 (auto-anchored backfill
   didn't fire) **and** `_monitor_goal_oq_text` is using its fallback string
   instead of the port's labels. Pass `test_problem_id` through every call
   site of `_enforce_session_monitors`.
3. **`missing_in_panel` drift on a non-canonical key** (e.g. `total_value`,
   `efficient_packing`). Cause: the LLM paraphrased a canonical key and
   the strip in `_strip_unknown_goal_term_keys` didn't fire — either
   `test_problem_id` wasn't threaded into `apply_brief_patch_with_cleanup`,
   or the port's `weight_display_keys()` is wrong.
4. **Run 2's ack still asks for a new OQ / assumption and blocks Step 11.**
   Cause: the `completed_ok_runs <= 2` gate in `_run_chat_pipeline_thread`
   isn't seeing Run 2's `OptimizationRun` row (maybe a transactional
   timing bug) or `is_tutorial_active` is false (check
   `participant_tutorial_enabled` + `tutorial_completed`).
