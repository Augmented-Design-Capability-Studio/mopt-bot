# Participant Interface Flow

Scope: behavior of the chat + definition + config + run loop *during* a
participant session. Project goal, study plan, and 2×2 conditions are
documented elsewhere and are not repeated here.

This doc has two parts:

- **Part 1 — Flow (natural language).** What the participant experiences
  and how the agent is expected to behave at each step.
- **Part 2 — Action → pipeline map (technical).** Every participant action
  that crosses the chat / definition / config boundary, mapped to the
  pipeline trigger and the deterministic mechanisms behind it.

For how each step maps to a concrete state/gate check and who (LLM vs.
server code) decides what, see `FLOW_CONTROL_MAP.md`. For pipeline stage
internals see `CHAT_PIPELINE.md`. For the four axes along which agile and
waterfall differ — everything else is symmetric — see
`docs/.study_plan/AGILE_VS_WATERFALL.md`.

Three workflow modes appear throughout: **waterfall** (specify first, ask
before acting), **agile** (assume a default, act, run early), and **demo**
(a workflow-neutral blend for live demonstrations / screen recordings).

---

# Part 1 — Flow (natural language)

## 1. Initial messages (cold vs warm chat)

When the participant starts chatting, classify the turn into one of three
states. The classification is per-turn — the chat can warm up mid-session.

- **Cold.** Nothing problem-relevant in the message (e.g. "hi", or a
  generic optimization question with no goal/constraint content). The
  agent stays in small-talk / orientation mode and does **not** start
  producing definition rows or invite a file upload.
- **Warm — well-aligned.** The participant talks about the overall goal
  and/or some constraints in a way that maps cleanly onto the problem
  module's expected goal terms. The agent may start producing
  definition entries (goal terms, gathered info, assumptions if agile)
  and/or invite a file upload.
- **Warm — misaligned.** The participant talks about the problem but
  what they say either (a) conflicts with how the problem is hard-coded
  / encoded, or (b) names constraints that, while valid, do not move
  the trade-off (so they're already baked into the encoding rather than
  surfaced as tunable terms). The agent should explain *how* the
  problem is coded and gently steer the user toward the meaningful
  trade-off dimensions — without dismissing the user's intent.

## 2. Status monitoring (warm only)

Once the chat is warm, the system tracks four state signals each turn:

- file upload status
- goal-term existence (any weighted goal term in the brief/config)
- search-strategy existence (algorithm set on the saved config)
- hanging open questions (waterfall mode)

…which together determine **run-button availability**.

Mode-dependent behaviour:

- If no goal term is defined or no file is uploaded: the corresponding
  open questions are kept (do not auto-resolve).
- Missing search strategy:
  - **Agile:** agent makes an assumption (proactive default) on the
    same turn and records the structural carrier so the gate updates.
  - **Waterfall:** agent files another open question; no proactive
    default.
  - **Demo:** agent sets a sane working default in the panel *and* files
    an open question naming the options, so the choice stays visible —
    but it never blocks the run.

## 3. Messaging (chat-driven updates)

As the user chats, the agent returns updates to the problem definition:
goal terms, run summary, open questions, assumptions (agile, and
possibly demo), and gathered info.

The system instruction is **assembled per turn from the current state**,
not sent whole: cold turns shed run-result, run-button, and algorithm
Q&A guidance; run-ack, config-save, upload, answered-OQ, and tutorial
turns each add only their own block. See `FLOW_CONTROL_MAP.md` for the
node→instruction table.

One retrieval stage and two follow-on LLM stages sit behind the chat
reply:

- **Documentation search.** Before the chat reply is produced, the
  system retrieves the most relevant sections from an external
  knowledge base so the agent can ground answers to participant
  questions about the problem, algorithms, or interface without that
  content living in the chat prompt. The agent does not name documents
  or quote them verbatim.

- **Validator (post-derivation compliance).** Deterministic S2/S5 checks
  verify the visible reply against the brief and the brief against the
  derived panel; on failure the turn is retried with the specific issues
  fed back, and pauses (Retry / Revert / Keep chatting) if it still fails.
  Run-button availability is *not* enforced after the fact — instead the
  current gate state ("Run optimization button: ENABLED / DISABLED —
  reason …") is injected into the system instruction every turn, so the
  agent knows before drafting whether it can legitimately invite a run.
- **Derivation (definition → config).** A separate call maps the
  definition to the problem config; alignment mechanisms keep the
  definitions and configs from drifting apart.

## 4. Run and post-run

The user can trigger a run via:

- a chat command,
- a run button inside a chat message,
- the run button on the viz panel.

After each run, the agent:

1. Acknowledges the run (run summary update).
2. Adds *one or two* new entries based on mode and what the run surfaced:
   - **Agile / demo-leaning:** an assumption (agile) — committed the same
     turn, fait accompli.
   - **Waterfall:** an open question asking the user to approve any
     proposed change.
   - **Demo:** concise interpretation plus at most one small config tweak;
     no per-run assumption/gathered rows, and unanswered open questions are
     *not* promoted just because a run used the current default. Runs are
     launched manually in demo (the agent points at the Run button rather
     than claiming to start the run).

## 5. Editing the definition panel

The user can edit the definition. Supported actions:

- answer open questions
- edit and promote assumptions (assumption → gathered info)
- edit goal summary
- edit run summary
- edit gathered info
- remove entries

These edits move a concept along its lifecycle (question → assumption →
gathered): answering or promoting confirms it as a user-owned **gathered**
fact. A user edit always wins over an agent proposal. In agile the agent may
later **demote** a gathered term back to an assumption if *it* changes the
value — never silently for a value you set. Full model: `USER_FLOW_AUDIT.md`.

On save:

- Derivation is re-triggered to update the config.
- The chat acknowledges *what specifically changed* (not a generic
  "got it").

## 6. Editing the config panel

The user can edit:

- goal-term ranks and weight types
- sub-properties of certain goal terms (see §7)
- the search strategy / algorithm
- lock / unlock a goal term
- remove goal terms

A **locked** goal term is frozen: the agent cannot change or demote it. To
change a locked term the agent must ask first and update only if you approve
(which unlocks it). Custom-type terms are locked by default.

On save:

- The agent acknowledges the change in chat.
- Corresponding definition entries are updated — especially assumptions
  and gathered info — so the two panels stay coherent. The panel is the
  source of truth this turn; the brief follows it (not the reverse).

## 7. Special goal terms with sub-properties

The definition panel is intentionally **flat** (no nested entries), but
some goal terms (e.g. VRPTW driver preferences with per-driver
properties, max shift hours, etc.) carry sub-properties on the config
side. The interface presents these as best it can on both sides; the
mapping is bridged by the problem module (`StudyProblemPort`) so the
main backend stays problem-agnostic.

## 8. Additional user actions to plan for

These are first-class in the existing backend even if not listed above:

- **Re-upload / replace file.** A second upload after a run resets the
  data-dependent parts of the definition; goal terms keyed to old
  fields may become orphaned and need to be either re-anchored or
  flagged.
- **Cancel an in-flight run.** Mid-run cancellation is supported; chat
  acknowledgement needs a distinct shape from "run completed".
- **Reset the session.** A hard reset (back to pre-warm). Definition
  and config are wiped; chat history may be preserved for the
  researcher view but the participant view starts clean.
- **Bookmark / snapshot the current state.** Participant-initiated
  snapshot bookmarks already exist server-side. They're a no-op for
  the optimization loop but the chat should not react to them as a
  brief edit.
- **Researcher-only steer / nudge messages.** Hidden injections that
  affect agent behaviour without appearing in the participant
  transcript. These must not trip the validator's "claimed a change" /
  "asked a question" intent detection.
- **Switch workflow mode (researcher action).** Treated as a clean
  cut; the post-switch turn should not inherit assumptions filed under
  the prior mode's rules (e.g. agile-style proactive defaults
  surviving into a waterfall switch).
- **Undo last edit.** Not currently a primitive, but worth deciding:
  if a definition edit triggers derivation and the user immediately
  reverts, the derivation should be cancelled-in-flight rather than
  applied then re-reverted.
- **Run an "evaluate edit" without re-solving.** Already supported on
  the backend (`post_evaluate_edit_run`); its acknowledgement differs
  from a fresh run.

---

# Part 2 — Action → pipeline map (technical)

> Every participant-side action that crosses the chat / definition / config
> boundary maps to one trigger of the chat pipeline (S1→S2→S3→S4→S5). The
> pipeline shape is single; the trigger flavor changes only the checklist
> labels and a small set of prompt-context flags.

## A. Chat-tab actions

### A1. Send a chat message
- `POST /sessions/{id}/messages { content }`.
- Flavor: `chat` (or `run_ack` / `brief_edit_ack` / `config_edit_ack` when
  the synthetic `context_kind` matches).
- Outputs: visible reply, brief patch (`items`, `goal_terms`,
  `open_questions`, `goal_summary`, optional `run_summary`), per-port
  structured carriers, `assumption_actions` (agile/demo only).
- S2 verification deterministic; one retry with issues feedback; second
  failure pauses with **Retry / Revert / Keep chatting**.

### A2. Ask a concept question
Same wire. Main-turn returns `is_change_intent=false` + empty patch →
pipeline fast-path: skip S2–S5 and settle.

### A3. Ask about run results / system status
Same wire. Run-button gate-status block and the latest `run_summary` are
injected into the system instruction; the reply is grounded in that
deterministic context.

## B. Definition-tab actions

### B1. Edit a brief row (any field)
- `PATCH /sessions/{id}/problem-brief { problem_brief, acknowledgement }`,
  followed by a synthetic chat post with `context_kind: brief_edit_ack`.
- Flavor: `brief_edit_ack`. Reply names what specifically changed (not
  "got it"). S2→S5 run.

### B2. Answer an open question
- Same PATCH; the synthetic post uses `context_kind: open_question_answered`
  when `flippedOqIds.length > 0`. Backend routes answered OQs through
  `classify_answered_open_questions`, then the brief change goes through
  the pipeline as B1. If `answer_text` is itself a clarifying question,
  the agent explains in the visible reply and re-opens the OQ (status
  back to `open`, `answer_text` null) instead of promoting.

### B3. Click "Clean up open questions"
- `POST /sessions/{id}/cleanup-open-questions`. Deterministic only.

### B4. Click "Clean up Definition"
Posts a fixed-string chat message; goes through A1 with cleanup context.

### B5. Restore from snapshot
Same wire as B1.

## C. Config-tab actions

### C1. Save panel manually
- `PATCH /sessions/{id}/panel { panel_config, acknowledgement }`, then
  synthetic post with `context_kind: config_save`.
- Flavor: `config_edit_ack`. Panel is ground truth this turn; reply
  refreshes brief prose to mirror it. **S4 skipped**; S5 verifies
  brief↔panel agreement.

### C2. "Sync to config" / C3. "Recover goal terms" / C4. Restore from snapshot
Deterministic only — `sync_panel_from_problem_brief` for C2,
`recover_goal_terms` for C3, B1-wire for C4.

## D. Run actions

### D1. Run optimization
- Invisible post `"I started Run #N."` → `POST /runs` → MEALpy → on
  finish, synthetic post `"Run #N just completed..."` with
  `context_kind: run_ack` → flavor `run_ack`. **Agile** must emit an
  assumption row; **waterfall** must emit an OQ (S2 enforces). **Demo**
  does neither (no per-run definition rows; launched manually).

### D2. Cancel run / D4. Mark candidate / D5. Reuse past config / D6–7. Edit & re-evaluate
Deterministic; no LLM.

### D3. Explain Run #N
Synthetic post → A1 with the run-context block injected.

## E / F. Snapshots, settings, upload
- Snapshot bookmark / listing / restore: deterministic.
- Model-key save: deterministic.
- File upload (currently simulated): synthetic post sets
  `is_upload_context=true` on S1's system instruction; A1 flow.

## G. Brief fields and the primary-goal information flow

Three header fields define the "what is this problem about?" surface,
and the primary goal MUST be reflected consistently across all of them
PLUS the panel. The system has deterministic backstops when the LLM
forgets, but the LLM should populate them itself.

### Header fields

- **`goal_summary` (always shown).** One short qualitative sentence on
  the overall objective (*"Minimize total travel time."*). Populated by
  S1 when the first primary objective is committed. If S1 forgets,
  `derivation._autofill_goal_summary_from_objective` derives it from
  `goal_terms[*].type == "objective"` + the port's
  `weight_item_labels()`. Never carry weight numbers, algorithm names,
  or budget values here.
- **`run_summary` (collapsed by default).** One rolling 1–2 sentence
  paragraph maintained by `derivation.consolidate_run_summary` across
  run-ack turns: single run → goal + outcome; multiple runs → overall
  progression + most recent outcome and next open question.
- **No `Goal:` / `Objective:` prefixed items[] rows.** If the LLM emits
  one, `_promote_goal_prefixed_items` strips the prefix and routes the
  content to `goal_summary`.

### Primary-goal flow (must stay coherent)

Committing a primary objective like "minimize travel time" must land in
**four places at once** — the rule is structural, not a prompt request:

1. **`brief.goal_terms.travel_time = {weight: 1.0, type: "objective", ...}`** —
   the canonical structured carrier the LLM emits in `problem_brief_patch.goal_terms`.
   This is the source of truth.
2. **`brief.goal_summary = "Minimize total travel time."`** — set by
   the LLM, or deterministically derived from (1) by
   `_autofill_goal_summary_from_objective` when the LLM forgets.
3. **`brief.items[] config-weight-travel_time`** — server-synthesized
   from (1) via `_synthesize_canonical_weight_items`. Format:
   *"{Label} ({type}, weight N) — {reasoning}."* Rebuilt on every brief
   merge so it always matches the structured carrier; **stale rows are
   dropped even when the synthesizer produces no new extras** so a
   wiped `goal_terms` never leaves a misleading display row behind.
4. **`panel.problem.goal_terms.travel_time = {weight, type, rank}`** —
   produced by S4 (`generate_config_from_brief`) and mirrored by
   `sync_panel_from_problem_brief`. The workflow-legitimacy gate
   honors the structured carrier signal first
   (`brief_mentions_search_strategy`-style check).

### Protections against accidental wipe

- `merge_problem_brief_patch` honors `replace_goal_terms=true` **only
  when `cleanup_mode=true`**. An LLM patch that sets the replace flag
  mid-conversation while omitting a previously-committed key would
  otherwise silently wipe `goal_terms.travel_time` and leave the
  participant with `goal_summary` and items[] referencing a term the
  panel no longer has.
- The anchor filter only fires on **new** keys, so an existing
  `goal_terms.travel_time` carried over from a prior turn is never
  re-validated and dropped.

### Inconsistency = bug, surface immediately

If any one of the four sites disagrees, surface it as drift:

- `brief.goal_terms.travel_time` exists but `panel.problem.goal_terms.travel_time`
  doesn't → S5 verifier raises `brief_panel_mismatch`.
- `brief.items[].config-weight-travel_time` exists but
  `brief.goal_terms.travel_time` doesn't → silent inconsistency
  (previously the 26f4-session pattern); now prevented by the
  synthesizer's always-drop-stale behavior.
- `brief.goal_summary` mentions a term that isn't in `goal_terms` →
  acceptable transiently (the LLM committed `goal_summary` but the
  anchor filter dropped the term); the autofill backstop will
  re-populate or clear `goal_summary` based on the surviving
  `goal_terms`.

## H. Open-question state machine

Every OQ carries a required `topic` enum (`upload | primary_goal |
search_strategy | other`) that partitions ownership:

- **Foundational topics** (`upload`, `primary_goal`, `search_strategy`):
  server-owned. The main-turn LLM is structurally blocked from emitting
  them — `merge_problem_brief_patch` strips any incoming OQ tagged with
  a foundational topic before the merge. `_enforce_session_monitors` is
  the sole writer.
- **`other`** (free-form clarifications): LLM-owned. The main-turn LLM
  adds / drops / keeps these per turn.

### Transitions per OQ

```
        ┌──────────────────────────────── transitions ───────────────────────────────┐
        │                                                                            │
        ▼                                                                            │
   (not present) ──[server: monitor activates]──→ open (foundational, server-owned) ──┐
                                                                                      │
                  ──[LLM: visible reply asks a question]──→ open (other, LLM-owned) ──┤
                                                                                      ▼
                                                                              ┌──────────────────────────┐
                                                                              │  open — visible in panel │
                                                                              └──────────────────────────┘
                                                                                      │
              ┌───────────────────────────────────────────────────────────────────────┤
              ▼                                                                       ▼
   participant answers in chat                                       participant types in answer field
   (LLM main turn sees the brief +                                   + saves brief PATCH:
   user message; promotes / drops                                    `is_answered_open_question=True`
   per OQ-lifecycle rules)                                           classifier buckets the answer
              │                                                                       │
              ▼                                                                       ▼
        ┌──────────────────────────────────────┐                  ┌──────────────────────────────────────┐
        │ bucket: substantive answer           │                  │ bucket via classify_answered_oqs:    │
        │ → goal_term commit / items[] row     │                  │ • gathered: promote (drop OQ)        │
        │   for `other`-tagged OQs             │                  │ • assumption (agile/demo): add row   │
        │ → server monitor drops               │                  │ • new_open_question (waterfall):     │
        │   `oq-monitor-*` once topic covered  │                  │   re-ask with topic INHERITED        │
        └──────────────────────────────────────┘                  │   from parent (so foundational       │
                                                                  │   re-asks get re-stripped at merge   │
                                                                  │   → canonical monitor surfaces again)│
                                                                  └──────────────────────────────────────┘
                                                                                      │
                                                                                      ▼
                                                                  main-turn LLM sees the synthetic post
                                                                  with `is_answered_open_question=True`
                                                                  + `STUDY_CHAT_ANSWERED_OQ_CONTEXT`:
                                                                    if `answer_text` is a counter-question
                                                                    → explain in `assistant_message`,
                                                                       re-open the OQ
                                                                    if substantive answer
                                                                    → standard promote / drop path
```

### Coverage triggers (foundational monitors)

The server adds/removes the canonical foundational OQs based on `brief`
state — this is the *only* path that creates them:

| Topic | OQ id | Removed when |
|---|---|---|
| `upload` | `oq-monitor-upload` | Any items[] row has `source: "upload"` |
| `primary_goal` | `oq-monitor-goal` | `goal_terms` is non-empty (any committed objective term) |
| `search_strategy` (waterfall only) | `oq-monitor-algorithm` | `brief_mentions_search_strategy` returns True (carrier set OR slot-tagged item OR algorithm name in text) |
| `search_strategy` (agile/demo) | *Replaced by `item-monitor-algorithm-default` assumption row* | Same as above (axis 4) |

The "covered" predicate is recomputed on every brief save, so the
participant supplying any of these signals — via chat, OQ answer, panel
save, or upload — drops the corresponding monitor row immediately.

### Counter-question handling (any topic)

When a participant types a clarifying question into an OQ answer field
(e.g. *"can you explain"*):

1. Frontend posts the synthetic chat note with `context_kind:
   "open_question_answered"` (because `flippedOqIds.length > 0`).
2. The PATCH endpoint runs `classify_answered_open_questions`. The
   classifier may bucket the hedged answer as `new_open_question`
   (waterfall) — the re-ask inherits the **parent OQ's topic**. If that
   topic is foundational, the re-ask is dropped at merge by the
   foundational-topic strip; the canonical monitor OQ remains as the
   single visible row.
3. The main-turn LLM sees `is_answered_open_question=True` →
   `STUDY_CHAT_ANSWERED_OQ_CONTEXT` injects the explain-vs-promote
   prompt block. The explanation lands in `assistant_message`; the
   original OQ stays open with `answer_text: null`.

### Invariants

- At most one OQ per foundational topic in any brief state (server
  enforces).
- An OQ with `topic ∈ foundational` from the LLM patch never reaches
  `open_questions[]` (merge-strip).
- Counter-questions never produce a duplicate foundational OQ (router
  inherits parent topic; classifier-generated re-asks get stripped).
- `goal_terms[key]` commits drop their corresponding monitor row on the
  same turn (monitor coverage check runs on each merge).

## I. Documentation retrieval (RAG)

Before S1 builds the system instruction, the chat-warmth classifier and
the participant's message together drive a retrieval pass against
`docs/user/*` (`docs_index.py`):

- **Indexed sections**: ≤100-word chunks parsed from headings in
  `docs/user/AGENT_CAPABILITIES.md`, `ALGORITHM_CHOICES.md`,
  `ASKING_THE_AGENT.md`, `INTERFACE_GUIDE.md`,
  `OPTIMIZATION_CONCEPTS.md`, `PROBLEM_MODULES_GUIDE.md`.
- **Retrieval**: embedding ranking (`gemini-embedding-001`, cosine ≥
  0.55) when an API key is present; **TF-IDF fallback** for tests / no
  key. Both paths share a denylist that hides researcher-only terms.
- **Use**: relevant excerpts are appended to S1's system instruction
  *only* — never to the visible reply verbatim, never with section names
  quoted to the participant. The agent answers in its own voice.
- **Maintenance**: `docs/user/` files should stay ≤100 words per
  section so chunks fit cleanly. To add a new topic, drop a new H2/H3
  in an existing file; indexing is automatic. See
  `feedback_chatbot_knowledge_base` for tone constraints.

## J. Foundational state monitors (warm only)

When the brief is warm (any items / goal_terms / goal_summary / OQs),
`_enforce_session_monitors` tracks four signals each turn and writes
canonical rows / drops them based on coverage:

| Signal | Covered when | Server emits when uncovered |
|---|---|---|
| Upload | any items[] row has `source: "upload"` | OQ `oq-monitor-upload` |
| Primary goal | `goal_terms` non-empty | OQ `oq-monitor-goal` |
| Search strategy (waterfall) | algorithm mentioned in items[] | OQ `oq-monitor-algorithm` |
| Search strategy (agile/demo) | algorithm mentioned in items[] | **Assumption item** `item-monitor-algorithm-default` (axis 4) |

Cold turns (no items, no OQs, no goal_summary) get NO monitors — small
talk doesn't surface three OQs.

## K. Things that look like LLM work but aren't

| Action | Mechanism |
|---|---|
| Run-button enable/disable | `optimization_gate.can_run_optimization` |
| Brief ↔ panel mirror after panel save | `sync_problem_brief_from_panel` (panel is ground truth on a save) |
| Per-rule prose synthesis from `goal_terms` | port `synthesize_brief_items_from_goal_terms` |
| Canonical `config-weight-<key>` rows | `derivation._synthesize_canonical_weight_items` |
| Stale prose-row dedupe | port `prose_id_prefixes_for_goal_term` + id-prefix filter |
| `goal_summary` backstop | `derivation._autofill_goal_summary_from_objective` |
| Foundational OQ strip | `merge_problem_brief_patch` (topic-enum-driven) |
| Run-context line | `derivation._format_run_context_line` |
| Snapshot FIFO prune | `session_snapshots.py` |
| Goal-term anchoring | `goal_term_anchoring.filter_unanchored_new_goal_terms` |
| Panel sanitization | port `sanitize_panel_config` |
| Workflow coercion | `coerce_problem_brief_for_workflow` (axis 2: waterfall converts assumption→OQ; demo drops) |
| Drift detection (researcher view) | `sync.compute_brief_panel_drift` — **skipped while `processing.brief_status` or `config_status` is `"pending"`** so phantom drift doesn't surface mid-pipeline |
| Tutorial step transitions | `patchForTutorialEvent` |

## L. `goal_terms` as the structured carrier

The canonical pipeline for structured per-goal-term metadata across the
chat → brief → panel → brief loop. VRPTW's `driver_preferences`,
`max_shift_hours`, and `algorithm` (under `search_strategy`) are the live
examples.

- **Schema typing**: each port overrides
  `StudyProblemPort.goal_term_properties_schema()`; the main-turn schema
  slots it into a shared factory (`app/problems/schema_shared.py`).
- **Brief carrier**: top-level `goal_terms` dict; per-key deep merge in
  `merge_problem_brief_patch`; `replace_goal_terms: true` swaps the full
  map.
- **Panel carrier**: `panel.problem.goal_terms`; per-port
  `goal_term_property_field_mirrors` project nested values onto
  top-level panel fields (e.g. `worker_preference.properties.driver_preferences`
  ↔ panel `driver_preferences`).

## M. Symmetry contract (the only 4 mode differences)

Per `AGILE_VS_WATERFALL.md` / `[[project_workflow_axes]]`:

1. **OQ policy** — waterfall: primary mechanism, cap 3 active; agile:
   sparingly, only true forks; demo: OQ-centric (≤3), never silently
   converted to assumptions.
2. **Assumption policy** — waterfall: NONE (`coerce_problem_brief_for_workflow`
   promotes assumption→OQ); agile: default for filling gaps,
   evidence_item_ids required; demo: essentially none (drops to OQ).
3. **Run gate** — waterfall additionally requires zero open OQs; agile
   and demo do not gate on OQs.
4. **Search-strategy default** — waterfall asks via OQ; agile commits
   `algorithm: "GA"` same turn as an assumption row; demo sets the panel
   default *and* keeps a visible OQ.

Pipeline shape, status checklist, retry budget, failure UX, anchoring
rules, port hook surface, and OQ ownership semantics are **identical**
across modes. Adding mode-specific content outside these four axes is
drift; lift it into a shared block instead.
```
