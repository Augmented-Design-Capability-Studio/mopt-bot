# User-Flow Audit Plan

> A repeatable checklist for keeping the participant flow stable, the
> prompts lean, and the set of anticipated user actions covered. Run it
> periodically (e.g. before a study batch, or after any prompt/pipeline
> refactor). Companion docs: `interface_flow.md` (the flow + action map),
> `FLOW_CONTROL_MAP.md` (node → state/gate → who decides),
> `CHAT_PIPELINE.md` (stage internals).
>
> Each task below is self-contained: a goal, the concrete steps, and the
> "done when" signal. Check them off; record findings inline or in a PR.

## How to use this

Work top to bottom. Tasks A–C are the standing health checks (run every
time). Tasks D–F are the backlog the audit has already surfaced (do once,
then they fold into A–C). Don't batch unrelated fixes into one PR — each
task is sized to stand alone.

---

## A. Prompt-budget health (excess prompt)

**Goal:** no block is carried on a turn that doesn't need it, and prompt
size can't grow silently.

1. Run `backend/tests/test_main_turn_prompt_assembly.py`. It pins, per
   scenario, (a) which named blocks load and (b) the exact word count.
2. If a `WORD_BUDGET` number changed, the diff **is** the measurement —
   confirm the change was intended and record the delta in the PR.
3. For each block in the `_ALWAYS` set (`llm.py`, assembled in
   `build_main_turn_system_instruction`), ask: *is there a server-known
   state where this is dead weight?* If yes, gate it on that state and
   add the gated scenario to the test.
   - Current candidates: `HARD_CONSTRAINT_DISCIPLINE` and
     `OUT_OF_SCOPE_DISCIPLINE` are always-on but only bite on
     misaligned-warm turns. Measure whether gating them off cold-start is
     safe before doing it.
4. **Done when:** the test passes, every always-on block has a one-line
   justification for being always-on, and no budget grew without a noted
   reason.

## B. Single-writer / field-ownership health (excess or conflicting code)

**Goal:** every brief/panel field has one documented owner; no field is
written by competing code paths.

1. Pick the high-churn fields: `goal_terms.<key>.weight/type`,
   `goal_terms.search_strategy.properties.algorithm`, `goal_summary`,
   `run_summary`, the foundational OQ rows.
2. Grep every assignment site for each. Confirm there's a documented
   precedence (who wins on a given turn) and that `interface_flow.md`
   Part 2 §K ("things that look like LLM work but aren't") lists the
   deterministic owner.
3. Treat §K as the single-writer registry — if a field has a
   deterministic backstop that isn't listed there, add it.
4. **Done when:** each audited field maps to exactly one owner per turn,
   and §K is complete.

## C. Dead-code sweep

**Goal:** no defined-but-uncalled symbols, no stale doc references.

1. For each public helper in `intent.py`, `derivation.py`, `llm.py`,
   grep for callers. Zero callers (outside its own definition/tests) =
   delete.
2. Grep doc filenames referenced from code/docstrings against the actual
   `docs/` tree; repoint or remove stale references.
3. **Done when:** the sweep finds nothing. (Last sweep removed the dead
   `commit_audit_note` pre-release-gate-audit path, the unused
   `assistant_reply_is_asking_about_run` regex, and stale
   `PROMPT_REDUCTION_PLAN.md` references — see git history.)

## D. Close the prompt-assembly coverage gap (one-time)

**Goal:** every turn type that loads a distinct block is pinned by a
scenario in `test_main_turn_prompt_assembly.py`.

1. The harness currently covers cold/warm × (waterfall/agile/demo),
   config-save, upload, and retry. It does **not** cover:
   - `run_ack` (loads `_run_ack_prompt(mode)`),
   - tutorial-active (loads `STUDY_CHAT_TUTORIAL_GUARDRAILS`),
   - `answered_oq` (loads `STUDY_CHAT_ANSWERED_OQ_CONTEXT`),
   - `brief_edit_ack` (loads the brief-edit ack block).
2. Add one `SCENARIOS` entry + `EXPECTED_BLOCKS` + `WORD_BUDGET` row for
   each. Add the missing block markers to `BLOCK_MARKERS`.
3. **Done when:** every conditional block in
   `build_main_turn_system_instruction` is asserted present in at least
   one scenario and absent in at least one other.

## E. Action-coverage audit (anticipating user actions) (one-time)

**Goal:** every participant action has a typed entry-point and a pinned
behavior; nothing falls through to improvisation.

1. Walk `interface_flow.md` Part 2 sections A–F as a checklist. For each
   action, confirm: (a) the frontend posts a typed `context_kind` (not
   free text the backend has to pattern-match), and (b) `intent.py` maps
   that kind to the right flavor.
2. Walk the §8 "additional actions to plan for" list (re-upload, cancel,
   reset, mode-switch, undo, evaluate-edit). For each, confirm a
   deterministic path exists rather than a generic chat fall-through.
   Prioritize **mode-switch** (must not inherit prior-mode assumptions)
   and **re-upload** (orphaned goal terms keyed to old data) — both have
   noted edge cases.
3. **Done when:** every A–F action has a `context_kind` + a test, and
   every §8 action is either implemented-with-a-test or explicitly logged
   as "not yet handled."

## F. No-regex-on-NL audit (one-time, then folds into C)

**Goal:** uphold `feedback_no_regex_for_nl` — no regex/keyword matching
that routes or classifies free-form participant text.

1. Grep for `re.compile` / `re.search` / substring keyword tuples in the
   chat path (`intent.py`, `llm.py`, `study_chat.py`).
2. Classify each: **allowed** (tokenizing machine-formatted strings or
   server-emitted ids — e.g. the `context_kind` fallbacks, the
   `config-weight-*` id checks) vs **violation** (matching human free
   text to decide behavior).
3. Known violations to resolve: the `_SANDBOX_PROBE_KEYWORDS` and
   `_VISUALIZATION_KEYWORDS` gates in `study_chat.py` (decide per
   `FLOW_CONTROL_MAP` — always-load the cheap one, or ride the existing
   cold/warm/hot classifier; do **not** add a new node-classifier layer).
4. **Done when:** every remaining regex is in the "allowed" bucket with a
   one-line note saying why.

---

## Out of scope (decided, not doing now)

These came up in the audit and were deliberately deferred — don't
re-litigate without new evidence:

- **A dedicated node/intent classifier.** Redundant with the deterministic
  flags that already detect most nodes; would be a layer on top of flags.
  See `FLOW_CONTROL_MAP.md` "what's missing" #1.
- **A structural gate for assumption promotion.** The failure (a bare
  "sure" promoting an assumption) is reversible and low-blast-radius;
  revisit only if testing shows it misfiring.
