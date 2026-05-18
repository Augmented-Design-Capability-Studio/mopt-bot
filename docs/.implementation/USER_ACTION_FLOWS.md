# User Action → Pipeline Map

> Every participant-side action that crosses the chat / definition / config
> boundary maps to one trigger of the chat pipeline (S1→S2→S3→S4→S5). The
> pipeline shape is single; the trigger flavor changes only the checklist
> labels and a small set of prompt-context flags. See
> `docs/.implementation/CHAT_PIPELINE.md` for stage internals and
> `docs/.study_plan/AGILE_VS_WATERFALL.md` for the 4 axes along which
> agile and waterfall differ — every other behavior is symmetric.

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
  assumption row; **waterfall** must emit an OQ (S2 enforces).

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
   sparingly, only true forks.
2. **Assumption policy** — waterfall: NONE (`coerce_problem_brief_for_workflow`
   promotes assumption→OQ); agile/demo: default for filling gaps,
   evidence_item_ids required.
3. **Run gate** — waterfall additionally requires zero open OQs.
4. **Search-strategy default** — waterfall asks via OQ; agile commits
   `algorithm: "GA"` same turn as an assumption row.

Pipeline shape, status checklist, retry budget, failure UX, anchoring
rules, port hook surface, and OQ ownership semantics are **identical**
across modes. Adding mode-specific content outside these four axes is
drift; lift it into a shared block instead.
