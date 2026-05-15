# User Action → Pipeline Map

> Every participant-side action that crosses the chat / definition / config
> boundary maps to one trigger of the chat pipeline (S1→S2→S3→S4→S5). The
> pipeline shape is single; trigger flavor changes only the checklist
> labels and a small set of prompt context flags. See
> `docs/.implementation/CHAT_PIPELINE.md` for stage details.

## A. Chat-tab actions

### A1. Send a chat message about the problem
- **Wire**: `POST /sessions/{id}/messages { content }`
- **Pipeline flavor**: `chat` (or `run_ack` / `brief_edit_ack` /
  `config_edit_ack` when the synthetic context_kind on the message
  matches).
- **Outputs**: visible assistant reply, brief patch (items / goal_terms /
  open_questions / goal_summary), per-port structured carriers (e.g.
  VRPTW `driver_preferences` under `goal_terms.worker_preference.properties`),
  optional `assumption_actions` (agile/demo only).
- **Verification**: deterministic S2 checks (claim/delta consistency,
  algorithm carrier consistency, workflow invariants, run-ack invariant,
  port companion). One retry with issues-feedback if any fail; second
  failure pauses with Retry / Revert / Keep chatting.

### A2. Ask a concept question
- Same wire / endpoint. Main-turn LLM emits `is_change_intent=false` +
  empty patch + no commit-phrasing → pipeline fast-path: skip S2/S3/S4/S5
  and settle.

### A3. Ask about run results / system status
- Same wire / endpoint. The main-turn LLM gets the run-button gate
  status + the latest run summary in its system instruction; the
  visible reply is grounded in that deterministic context, no
  structural deltas required.

## B. Definition-tab actions

### B1. Edit / add / remove a brief row
- **Wire**: `PATCH /sessions/{id}/problem-brief { problem_brief, acknowledgement }`,
  followed by a synthetic chat post `"I just manually updated the problem
  definition..."` with `context_kind: brief_edit_ack`.
- **Pipeline flavor**: `brief_edit_ack`. The main-turn LLM acknowledges
  the manual edit and may emit follow-up maintenance changes; S2/S3 run,
  then S4/S5 re-derive the panel.

### B2. Answer an open question
- **Wire**: `PATCH /sessions/{id}/problem-brief` — backend routes
  answered OQs through `classify_answered_open_questions` (a separate
  focused LLM that runs as a batched call on save).
- After the route, the brief change goes through the pipeline as B1.

### B3. Click "Clean up open questions"
- **Wire**: `POST /sessions/{id}/cleanup-open-questions`.
- **Pipeline**: no LLM. Deterministic dedupe + workflow coercion.
  Semantic cleanups should arrive via chat (B4).

### B4. Click "Clean up Definition"
- Posts a fixed-string chat message; goes through A1 with the cleanup
  context tagged on the main-turn LLM's system instruction.

### B5. Restore Definition from a snapshot
- Same wire as B1; the synthetic post explains the restore. Pipeline
  runs as B1.

## C. Problem-Config tab actions

### C1. Save the panel manually
- **Wire**: `PATCH /sessions/{id}/panel { panel_config, acknowledgement }`,
  followed by a synthetic chat post `"I manually updated the problem
  configuration..."` with `context_kind: config_save`.
- **Pipeline flavor**: `config_edit_ack`. The main-turn LLM acknowledges
  the saved panel and refreshes brief prose to mirror it (no panel
  changes — the saved panel is ground truth). S4 is **skipped**; S5
  verifies brief↔panel agreement.

### C2. Click "Sync to config"
- **Wire**: `POST /sessions/{id}/resync-panel-from-brief`.
- **Pipeline**: deterministic only. Calls `sync_panel_from_problem_brief`
  with the active LLM key so a fresh panel derivation runs without
  touching the brief.

### C3. Click "Recover goal terms"
- **Wire**: `POST /sessions/{id}/recover-goal-terms`.
- **Pipeline**: deterministic only. Clears broken goal_terms and
  re-derives from the brief.

### C4. Restore Config from a snapshot
- Same wire as C1.

## D. Run actions

### D1. Click "Run optimization"
- Synthetic invisible post `"I started Run #N."` (no LLM).
- `POST /sessions/{id}/runs { type: 'optimize', problem, ... }` → MEALpy.
- On success: synthetic post `"Run #N just completed..."` with
  `context_kind: run_ack` → pipeline flavor `run_ack`. Agile must emit
  an assumption row; waterfall must emit an OQ (S2 enforces).

### D2. Cancel a run
- Deterministic flag-flip. No LLM.

### D3. Click "Explain Run #N"
- Synthetic post `"Please explain Run #N..."` → pipeline runs as A1 with
  the run-context block injected.

### D4. Mark / unmark a candidate run
- Local state only. No backend call.

### D5. Reuse a past run's config
- Hydrates the config editor; nothing persists until C1.

### D6 / D7. Edit + re-evaluate a schedule
- Deterministic re-evaluate via the port. No LLM.

## E. Snapshot actions

### E1. Bookmark / E3. Listing
- Deterministic. No LLM.

### E2. Restore Definition / Config
- See B5 / C4.

## F. Settings & lifecycle

### F1. Save model key / model name
- Deterministic. No LLM.

### F3. Upload data file (currently simulated)
- Synthetic post with `is_upload_context=True` flag on the main-turn
  LLM's system instruction. Same A1 flow.

## G. Things that look like LLM work but are not

| Action | Mechanism | Why deterministic |
|--------|-----------|-------------------|
| Run-button enable/disable | `can_run_optimization` + `_run_gate_blocked_message` | Pure function of brief+panel state |
| Brief ↔ panel mirror after panel save | `sync_problem_brief_from_panel` (panel→brief copies `goal_terms` verbatim) | Panel is ground truth on a save |
| Per-rule prose synthesis from `goal_terms` | port `synthesize_brief_items_from_goal_terms` | One prose row per rule, port-owned |
| Stale prose-row dedupe when `goal_terms` change | port `prose_id_prefixes_for_goal_term` + id-prefix filter | id-only, no text inspection |
| Snapshot FIFO prune | `session_snapshots.py` | Time/count gate |
| Panel sanitization | port `sanitize_panel_config` | Closed schema |
| Cancellation flag | `solve_cancel.py` | Cooperative cancel |
| Tutorial step transitions | `patchForTutorialEvent` | Stable event taxonomy |
| Goal-term order validation | `validate_problem_goal_terms` | Structural |
| Top-level mirror projection of structured properties (e.g. VRPTW `driver_preferences`) | port `goal_term_property_field_mirrors` + `study_bridge._apply_goal_terms_overlay` | Deterministic field copy |
| Rebuild `goal_terms` from top-level weights + constraint_types after panel save | `study_bridge._rebuild_goal_terms_metadata` | Port-specific reconciler |
| Open-question lifecycle (add/drop/keep/rephrase) | inside S1's main-turn LLM | One call owns the full state |
| Goal-term backing | S2 verification + `goal_term_anchoring.filter_unanchored_new_goal_terms` | Deterministic gate with embedding fallback |
| Port-specific structural carrier checks (e.g. VRPTW driver-pref structured/prose mismatch) | port `verify_brief_companion` | Deterministic surface |

## H. `goal_terms` as the structured carrier

This is the canonical pipeline for any structured per-goal-term
metadata that has to survive the chat → brief → panel → brief loop.
VRPTW's `driver_preferences`, `max_shift_hours`, and `algorithm` (under
`search_strategy`) are the live examples; new ports plug in at the same
hooks without touching shared code.

- **Schema typing**: each port overrides
  `StudyProblemPort.goal_term_properties_schema()` to return the typed
  shape for `goal_terms[key].properties`. The main-turn schema slots it
  into a shared factory in `app/problems/schema_shared.py`. Gemini
  structured output therefore sees a fully typed `properties` object.
- **Brief carrier**: top-level `goal_terms` dict alongside `items`,
  `open_questions`, `goal_summary`, `run_summary`. Normalization
  validates each port's properties via `normalize_goal_term_property`.
- **Panel carrier**: `panel.problem.goal_terms` is the canonical
  solver-config storage after `sanitize_panel_weights`. Per-port
  property mirrors project nested values onto top-level panel fields
  via `goal_term_property_field_mirrors` (e.g. VRPTW mirrors
  `worker_preference.properties.driver_preferences` ↔ top-level
  `driver_preferences`).
- **Merge semantics** (`merge_problem_brief_patch`): per-key deep merge
  at the `goal_terms[key]` level; per-property deep merge inside
  `properties`; list-typed properties replaced wholesale; a
  `replace_goal_terms: true` flag swaps the full map.

## I. Symmetry contract (agile / waterfall / demo)

Mode differences are concentrated in:
1. `_workflow_prompt(mode)` — the workflow-specific section of the main-turn system prompt.
2. `_run_ack_prompt(mode)` — agile commits an assumption row, waterfall emits an OQ.
3. Schema-enum: `assumption_actions` valid only when mode ∈ (agile, demo); waterfall ignores any emitted entries.
4. S2 invariant rules: waterfall rejects assumption rows in the brief; agile run-ack must add an assumption; waterfall run-ack must add an OQ.
5. S3 workflow coercion: waterfall promotes assumption→OQ; demo drops assumption rows.

Everything else — pipeline shape, status checklist, retry budget,
failure UX, anchoring rules, port hook surface — is identical across
modes.
