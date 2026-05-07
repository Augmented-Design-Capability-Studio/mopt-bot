# User Action → Effects Catalog

> Catalog of every participant-side action that crosses the chat / definition / config boundary, with the outputs each action requires and the LLM / embedding / schema work needed to produce them safely. Use this when deciding whether a Gemini call is necessary, can be consolidated, or can be replaced by an embedding lookup or a deterministic transform.
>
> Scope: participant client (`frontend/src/client/...`). Researcher actions (steering injection, simulated upload, tutorial overrides) are out of scope here — they enter the same pipelines via the participant message endpoint.

## How to read this document

Every row of "Required outputs" is something that must end up in DB / UI by the time the action settles. Every row of "Inference" is a decision — by an LLM, an embedding lookup, a deterministic rule, or a schema check — that is needed to produce those outputs.

For each Inference we record:
- **Kind**: `LLM` (free-form chat reply), `LLM-structured` (JSON-schema-conditioned), `embedding`, `deterministic`, `schema-check`.
- **Why it's needed**: the question being answered.
- **Failure mode**: what goes wrong on the user side if the inference is bad.
- **Consolidation note**: whether this can share a call with another inference for the same action.

## Glossary

- **Brief**: `ProblemBrief` = goal_summary, items (gathered/assumption rows), open_questions, run_summary, goal_terms. Visible to the participant in the Definition tab. The brief's `goal_terms` is the structured carrier mirrored bidirectionally with the panel — both LLM patches and panel→brief sync write to it.
- **Panel / Config**: `panel_config.problem` = goal_terms (with weight + type), algorithm, epochs, pop_size, algorithm_params, plus port-specific extras. Visible in the Problem Config tab.
- **Goal terms**: the closed key set that drives the cost function (per problem port). Each term has `{weight, type, properties?, rank?, locked?}`; type ∈ {objective, soft, hard, custom}. `properties` carries problem-specific structured metadata — e.g. VRPTW puts driver-preference rules at `goal_terms.worker_preference.properties.driver_preferences` and the shift-hour cap at `goal_terms.shift_limit.properties.max_shift_hours`. The `properties` schema is owned by each port (`StudyProblemPort.goal_term_properties_schema()`), slotted into the shared `goal_terms_schema(...)` factory in `backend/app/problems/schema_shared.py`.
- **Run-button gate**: `can_run_optimization(...)` — agile (≥1 weight + algorithm), waterfall (gate-engaged + no open OQs).
- **Synthetic chat message**: a participant-role message the frontend posts on the user's behalf (e.g. `"I just manually updated the problem configuration. ..."`) to drive the chat acknowledgement loop after a panel/brief edit.
- **Background derivation**: the threaded post-chat job that re-runs brief-update + config-derivation; observed by clients via `processing.brief_status` / `processing.config_status`.

---

## A. Chat-tab actions

### A1. Send a chat message about the problem

**UI**: types in the chat composer, presses send (`useClientSessionActions.sendChat`).
**Wire**: `POST /sessions/{id}/messages { content, invoke_model: true, skip_hidden_brief_update: false }`.

#### Required outputs
- One visible assistant message appended to the transcript.
- Possibly: brief patch (gathered / assumption / OQ edits) reflected in the Definition.
- Possibly: panel patch (weights / type / algorithm) reflected in Problem Config.
- Possibly: run-trigger flag → frontend may auto-launch the run (agile) or queue an invitation (waterfall).
- `processing` state (`brief_status`, `config_status`) updated so the spinner UI is honest.

#### Inferences

| # | Question | Kind | Failure mode | Consolidation note |
|---|----------|------|--------------|---------------------|
| A1.1 | Is this an *edit-intent* message at all? (vs concept question / casual chat) | LLM-structured **or** embedding | Wasted brief+panel pipeline on every "what does GA mean?". Currently regex-fallback defaults True. | Could be one field of A1.2's structured output. Embedding-prefilter can short-circuit obvious concept questions before any LLM. |
| A1.2 | What is the visible reply? | LLM (free-form) | Bad UX, wrong tone, hallucinated changes. | Should be merged with A1.4: the same model decides what to *say* and what to *change*. |
| A1.3 | Is the user asking to start a run *now*? | LLM-structured | False-positive triggers an unwanted run; false-negative makes the user re-ask. | Same call as A1.2 — one bool field. Today fires in parallel. |
| A1.4 | What brief patch (items / open_questions / goal_terms) follows from this turn? | LLM-structured (per-problem schema) | Visible reply says "I increased X" but the brief/panel never moves. Currently real failure mode. | Must share context with A1.2 to avoid drift. The brief patch schema is built per-port (`_build_brief_update_response_schema(test_problem_id)` in `services/llm.py`); each port's `goal_term_properties_schema()` is slotted into the `goal_terms` slot so structured per-term metadata (e.g. VRPTW `driver_preferences`) is typed for Gemini structured output and the model emits real rule objects rather than empty `properties: {}`. |
| A1.5 | What panel patch (weights / types / algorithm) follows from the new brief? | LLM-structured (per-problem schema) | Goal-term keys hallucinated; weights flipped back; algorithm reset. | Keep separate from A1.2/A1.4. Different schema, doesn't need history, benefits from explicit cache. When the brief carries non-empty `goal_terms[key].properties.<field>` (e.g. driver_preferences), the config-derive prompt instructs the LLM to copy verbatim — no prose re-derivation. |
| A1.6 | Did the assistant reply just invite a run? (only relevant if A1.3 was `affirm_invite`) | LLM-structured | Run never auto-fires after the user said "yes". | Eliminate by making A1.2 emit an `is_run_invitation` field. |
| A1.7 | What docs should ground the reply? | embedding | Generic answer when a user asks about a benchmark concept. Currently TF-IDF, misses paraphrases. | Pre-LLM retrieval. Replace TF-IDF with embeddings; cache embeddings of `docs/user/*` once at startup. |
| A1.8 | (when ambiguous) Is the chat context cold/warm/hot? | LLM-structured | Slightly noisy guardrails; not user-visible. | Already gated to "warm" only. Fine as-is. |
| A1.9 | Validate every structured output's shape. | schema-check | Silent no-op patches; brief/visible divergence. | Must run on every structured response. Consider one auto-retry on schema failure. |
| A1.10 | Split a mixed-intent turn ("Yes, bump X. Also, what is Y?") into a `change_clause` + `question_clause`. | LLM-structured | Concept-question half pollutes brief patch scope; LLM expands a confirmed retune ("yes increase punctuality") into a 4-term hallucination because the question half left it room. | Lives on the consolidated chat turn (`change_clause` / `question_clause` fields). Router uses `change_clause` as the brief-update LLM's `user_text` when both halves are present; concept-only turns short-circuit the brief pipeline entirely. |
| A1.11 | Anchor every newly-introduced goal_term to a brief items[] id. | LLM-structured + deterministic filter | Hallucinated weight keys ("worker_preference", "waiting_time") sneak into the panel without any brief evidence. | LLM populates `goal_terms[key].evidence_item_ids`; `app.services.goal_term_anchoring.filter_unanchored_new_goal_terms` drops unanchored newcomers at brief-merge AND panel-derive, with embedding-cosine fallback against item text. Existing keys preserved. |

#### Notes
- `sendChat` does **not** set `skip_*` flags. Path runs the full pipeline.
- `change_intent=False` (A1.1) is the only legitimate way to skip A1.4 + A1.5. Today the regex fallback returns True for nearly everything; an embedding prefilter is the right way to make this gate actually save calls.
- The "I just answered the user with X" → "now please patch the brief consistent with X" two-step is the hottest source of inconsistency. Consolidate A1.2 + A1.3 + A1.4 + A1.6 into one structured call.
- After the brief-update LLM returns, `apply_brief_patch_with_cleanup` (`backend/app/routers/sessions/derivation.py`) calls `port.synthesize_brief_items_from_goal_terms(brief.goal_terms)` to render participant-visible prose `gathered` rows from the structured carrier (e.g. one `config-driver-pref-{vid}-{discriminator}` row per VRPTW driver-preference rule). Stale rows whose id-prefix the port owns (`prose_id_prefixes_for_goal_term`) are dropped before the new set is added — id-only filtering, no text inspection. The LLM is told (via `DRIVER_PREFERENCES_BRIEF_CONTRACT` in `vrptw_problem/study_prompts.py`) **not** to also write a parallel prose row for these rules; the synthesizer is the single producer.

---

### A2. Ask the agent to *explain* something (concepts, weights, algorithm, results, uploaded data)

**UI**: same chat composer, but the message is a question with no edit intent (e.g. "what does GA mean?", "why is travel time penalized?", "what's in the file I uploaded?").
**Wire**: same as A1.

#### Required outputs
- Visible assistant message only.
- **No** brief change.
- **No** panel change.
- `processing` state should settle to "ready" without a background job.

#### Inferences

| # | Question | Kind | Failure mode | Consolidation note |
|---|----------|------|--------------|---------------------|
| A2.1 | Is this an edit-intent message? (must answer "no" to skip the brief/panel pipelines) | LLM-structured **or** embedding | Wasted background derivation; possibly even spurious brief edits if the LLM "patches" something out of helpfulness. | Same as A1.1. Embedding prefilter is the right tool. |
| A2.2 | Doc retrieval for the answer. | embedding | Vague answer or boilerplate. Critical for UX feel of "knowing the system". | Pre-LLM. Single index for `docs/user/*` per problem port. |
| A2.3 | Visible reply. | LLM | Generic / hallucinated / leaks "VRPTW" / leaks researcher steering. | Same call as A1.2. |

#### Notes
- This is the action whose performance currently suffers most from `is_change_intent` defaulting to True. Right now this path can fire all 6–8 LLM calls of A1 even though only one is needed.
- Separating "concept question" from "edit-intent" is the single biggest LLM-call-count win available. **Embedding centroid match** against a small labeled set of exemplars per workflow mode is sufficient — the LLM classifier is overkill for the obvious cases and only needed at the boundary.

---

### A3. Ask about run results / system status / "why can't I run?"

**UI**: chat message like "why is the Run button disabled?", "what does this run mean?", "is the optimization still running?".
**Wire**: same as A1.

#### Required outputs
- Visible reply that accurately describes:
  - Whether the run button is enabled and *why not* if disabled (gate reasons differ between agile and waterfall).
  - The most recent run's cost / violations / algorithm in lay terms.
  - The current solver progress (if any).
- No brief/panel change.

#### Inferences

| # | Question | Kind | Failure mode | Consolidation note |
|---|----------|------|--------------|---------------------|
| A3.1 | Is this an edit-intent message? | (same as A2.1) | (same as A2.1) | (same as A2.1) |
| A3.2 | Run-button state at the moment of the reply. | deterministic | Agent says "click Run now" when the gate is blocking. Currently injected into the visible-reply system instruction. | Already deterministic. Memoize per `(workflow_mode, brief shape, has_upload, gate_engaged)`. |
| A3.3 | Last 4 runs summary. | deterministic | Agent invents numbers. Currently passed in. | OK as-is. |
| A3.4 | Visible reply. | LLM | Confused / leaks problem identity. | Same as A1.2. |

#### Notes
- The `run_button_enabled` + `run_disabled_reason` injection (router.py:684–703) is the right pattern. Keep it. Do *not* let the LLM derive this — the gate is a small deterministic function.

---

## B. Definition-tab actions

The Definition tab shows the brief: `goal_summary`, gathered items, assumptions, open questions. Participants edit, add, remove, promote, and answer items directly.

### B1. Edit / add / remove a gathered item or assumption

**UI**: clicks "Save" in the Definition panel after edits (`useClientSessionActions.saveProblemBrief`).
**Wire**: `PATCH /sessions/{id}/problem-brief { problem_brief, acknowledgement }` then a synthetic chat post `"I just manually updated the problem definition..."`.

#### Required outputs
- Persisted brief (incoming brief is authoritative; only structural coercion server-side).
- Re-derived panel from the new brief (this is the brief→config side of Flow B).
- Optional: chat acknowledgement that summarizes what the participant changed and what it means.
- A snapshot row (`EVENT_MANUAL_SAVE`).

#### Inferences

| # | Question | Kind | Failure mode | Consolidation note |
|---|----------|------|--------------|---------------------|
| B1.1 | Re-derive panel goal_terms / weights / algorithm from the new brief, preserving managed fields the user didn't touch. | LLM-structured (per-problem) **+** deterministic seed fallback | Goal-term key hallucinated; weights reset; algorithm reverted. | Same as A1.5. Cached per `(problem, mode, phase)`. Skip when brief did not actually change. The deterministic fallback (`vrptw_problem/brief_seed.derive_problem_panel_from_brief`) copies `brief.goal_terms` verbatim onto the panel and lets `study_bridge._apply_goal_terms_overlay` project nested `properties.driver_preferences` to the top-level `driver_preferences` field — no prose parsing. |
| B1.2 | Validate goal_terms structurally (shape / type enum / order keys). | schema-check | 422 on save; participant blocked from saving. | Already in place. Keep. Do not re-add brief-grounding markers. |
| B1.3 | (Optional) Flag goal-term keys not anchored anywhere in the brief. | embedding-similarity | Hallucinated key sneaks into panel and lingers until user notices. | Replaces the retired marker-based check. Cosine of key string + label vs brief items; warn (don't block) below threshold. |
| B1.4 | Generate a chat acknowledgement that doesn't repeat what the participant just typed. | LLM | Robotic mirror; or contradicts the saved values. | This is the synthetic-message path → re-enters A1 fully. Today it costs the same as a real chat turn. **Skip unless `chatNote` was provided** (the no-text-supplied case can be served by a deterministic 1-line ack). |
| B1.5 | Hidden brief refresh after the chat ack. | LLM-structured | Brief LLM rewrites items the user just typed. | Already mitigated by `is_config_save=False, skip_hidden_brief_update=true` for the auto-ack path. Keep skip-default unless `chatNote`. |

#### Notes
- Backend bug-shaped risk: `patch_participant_problem_brief` validates *only* on save, then catches `GoalTermValidationError` from the panel re-derivation and surfaces a Recover banner. Good. But the brief is committed *before* the panel sync, so a corrupted-brief / clean-panel state is reachable. Worth a follow-up.

---

### B2. Answer an open question

**UI**: types into the OQ answer box, clicks Save (same `saveProblemBrief` path; the controller diffs and finds OQs that flipped to `answered`).
**Wire**: `PATCH /sessions/{id}/problem-brief` — backend invokes `_route_oq_answers_through_classifier` *before* coercion.

#### Required outputs
- Each answered OQ is either:
  - promoted to a `gathered` item (concrete answer), or
  - promoted to an `assumption` (hedged answer; agile/demo only), or
  - replaced with a re-asked simpler OQ (waterfall only).
- Panel re-derived if the answer affects goal_terms.
- Chat ack.

#### Inferences

| # | Question | Kind | Failure mode | Consolidation note |
|---|----------|------|--------------|---------------------|
| B2.1 | Per-OQ bucket routing + rephrase. | LLM-structured (`classify_answered_open_questions`) | Answered OQ stays as OQ ("did I just save?" feeling); concrete answer demoted to assumption. | Batched call — one Gemini call for N OQs. Keep. |
| B2.2 | Panel re-derivation. | (same as B1.1) | (same as B1.1) | (same as B1.1) |
| B2.3 | Chat ack. | LLM | (same as B1.4) | (same as B1.4) — skip unless `chatNote`. |

---

### B3. Click "Clean up open questions"

**UI**: dedicated button (`requestOpenQuestionCleanup`).
**Wire**: `POST /sessions/{id}/cleanup-open-questions { infer_resolved: true }`. **No chat post.**

#### Required outputs
- Pruned `open_questions` (resolved OQs removed, duplicates merged, still-ambiguous ones kept).
- Updated `processing` state.

#### Inferences

| # | Question | Kind | Failure mode | Consolidation note |
|---|----------|------|--------------|---------------------|
| B3.1 | Which OQs are still genuinely open? | LLM-structured (`generate_problem_brief_update` with `cleanup_mode=True`) | False positives delete valid OQs (waterfall gate becomes prematurely satisfied). False negatives leave noise. | This is the second LLM brief call I called out as redundant in the critique — *here* it is the right call. Deduplicate elsewhere by skipping it on the chat hot path. |
| B3.2 | Conservative deterministic backstop. | deterministic | None (only runs as a fallback). | Already in place (`cleanup_open_questions`). Keep. |

---

### B4. Click "Clean up Definition" (full cleanup; promote/dedupe gathered + assumptions)

**UI**: dedicated button → posts `DEFINITION_CLEANUP_CHAT_MESSAGE` as a chat message.
**Wire**: `POST /sessions/{id}/messages` with the cleanup phrase → A1 path with `cleanup_requested=True` (definition-intent classifier flags it, *or* a regex fallback recognizes it).

#### Required outputs
- Deduplicated, holistic `items` list.
- Same panel re-derivation as B1.

#### Inferences
- Same as A1, with `cleanup_mode=True` modifying both the visible-reply prompt and the brief-update prompt.
- **The cleanup phrase is fixed text** ("Clean up the Definition..."). Definition-intent classification on this message is a wasted call. Special-case the string client-side: pass `cleanup_requested=true` in the request body and skip A1.1.

---

### B5. Restore Definition from a snapshot

**UI**: snapshot dialog → "Restore Definition" (`restoreFromSnapshot('definition')`).
**Wire**: `PATCH /sessions/{id}/problem-brief` with the snapshot's brief, then synthetic post `"I just restored the problem definition..."` with `skip_hidden_brief_update: true`.

#### Required outputs
- Brief replaced with snapshot.
- Panel re-derived from restored brief.
- Chat ack.

#### Inferences
- B1.1 (panel re-derivation) only.
- A1.2 (chat reply). Skip A1.4/A1.5 because `skip_hidden_brief_update=true` is set — the restored brief is authoritative and we just ran B1.1.

#### Notes
- This action is intentionally minimal. Don't add LLM work here; the snapshot is ground truth.

---

## C. Problem-Config tab actions

### C1. Save the panel manually

**UI**: edits Problem Config form (or raw JSON), clicks Save (`useClientSessionActions.saveConfig`).
**Wire**: `PATCH /sessions/{id}/panel { panel_config, acknowledgement }` then synthetic post `"I manually updated the problem configuration. Changed settings: ..."` with `skip_hidden_brief_update: false` and `is_config_save=True` server-side.

#### Required outputs
- Persisted panel (sanitized by the port).
- Brief mirrored from the panel (deterministic via `merge_brief_from_panel`).
- Chat ack with rationale-preserving language.
- Updated brief rows for affected weights/types (LLM-rewritten so prior rationale is preserved).
- Snapshot.

#### Inferences

| # | Question | Kind | Failure mode | Consolidation note |
|---|----------|------|--------------|---------------------|
| C1.1 | Sanitize the submitted panel (clip weights, drop unknowns). | deterministic (port `sanitize_panel_config`) | Bad weights persisted; solver crash. | Already in place. Keep. |
| C1.2 | Validate goal_terms (only when changed). | schema-check | 422 blocks save when truly malformed. | Already conditional. Good. |
| C1.3 | Mirror brief rows from new panel values, *preserving* prior rationale text. | LLM-structured (`generate_problem_brief_update` with `is_config_save=True`) | LLM overwrites participant's typed rationale. | The current sanitization in `derivation.py` skips panel re-derivation on this path. **Do** keep the brief-update LLM call here — it's the only way the rationale text gets refreshed naturally. Independently of the LLM, `sync_problem_brief_from_panel` deterministically copies `panel.problem.goal_terms` into `brief.goal_terms` verbatim and runs the port's `synthesize_brief_items_from_goal_terms` to refresh `config-driver-pref-*` rows — so a manual UI add of a preference rule shows up in the Definition tab even with `invoke_model=false`. |
| C1.4 | Chat ack ("I increased capacity to hard, ..."). | LLM | Mirror that just dumps the diff. | Same call as C1.3 if consolidated; the human-readable ack and the brief patch can come out of one structured response. |
| C1.5 | Skip panel re-derivation. | deterministic | If accidentally enabled, the LLM-derived panel can flip the user's just-saved values back. | Already enforced by `is_config_save=True` in `derivation._run_background_derivation`. Critical. |

---

### C2. Click "Sync" (re-derive panel from current brief, no save)

**UI**: "Sync" button on the Definition tab (`useClientSessionActions.syncProblemConfig`).
**Wire**: `PATCH /sessions/{id}/problem-brief` with the current brief and ack `"Problem config synced from the saved definition."`. **No chat post.**

#### Required outputs
- Re-derived panel.
- No chat noise.

#### Inferences
- B1.1 only.

---

### C3. Click "Recover goal terms" (after a goal-term-validation banner)

**UI**: Recover banner button (`recoverGoalTerms`).
**Wire**: `POST /sessions/{id}/recover-goal-terms`.

#### Required outputs
- A clean panel re-derived from scratch (server-side: clears the broken goal_terms, re-runs panel-from-brief).
- `processing_error` cleared.

#### Inferences
- B1.1 only (the server-side recover handler internally calls `sync_panel_from_problem_brief`).
- **No chat ack expected**. Keep silent.

---

### C4. Restore Config from a snapshot

**UI**: snapshot dialog → "Restore Config" (`restoreFromSnapshot('config')`).
**Wire**: `PATCH /sessions/{id}/panel { panel_config: snapshot.panel, acknowledgement }` then synthetic post `"I just restored the problem configuration..."` with `skip_hidden_brief_update: true`.

#### Required outputs
- Panel replaced with snapshot.
- Brief mirrored from restored panel.
- Chat ack.

#### Inferences
- C1.1, C1.2 (deterministic) only on the PATCH path.
- A1.2 (visible reply) on the synthetic post. **No** A1.4/A1.5.

---

## D. Run / results actions

### D1. Click "Run optimization"

**UI**: `useClientSessionActions.runOptimize`.
**Wire**:
1. Synthetic invisible post `"I started Run #N."` (`invoke_model: false`, `skip_hidden_brief_update: true`, suppressed from UI).
2. `POST /sessions/{id}/runs { type: 'optimize', problem, candidate_seed_run_ids, candidate_seeds }` → MEALpy.
3. After success and if `invoke_model`: synthetic post `"Run #N just completed - cost X (violations Y). Give a very brief interpretation..."` (`invoke_model: true`, `skip_hidden_brief_update: true`).

#### Required outputs
- Run record persisted.
- Visible reply interpreting the run (1–2 sentences).
- Possibly: updated open questions (waterfall: 1–2 follow-up OQs after a run).
- Snapshot before run.

#### Inferences

| # | Question | Kind | Failure mode | Consolidation note |
|---|----------|------|--------------|---------------------|
| D1.1 | Solve. | deterministic (MEALpy) | Solver crashes / runs forever. | Cooperative cancel flag exists. Keep. |
| D1.2 | Interpret the run. | LLM | Generic interpretation; misreads violations. | Same call as A1.2 with `is_run_acknowledgement=true`. |
| D1.3 | Add 1–2 waterfall follow-up OQs. | LLM-structured | OQ list grows unbounded across runs (the `_sanitize_run_ack_patch_payload` exists *because* of this). | Already constrained server-side. Keep, but consolidate with D1.2. |
| D1.4 | Don't grow the brief items on every run. | deterministic (`_sanitize_run_ack_patch_payload`) | Definition tab fills with run noise. | Already in place. Critical to keep. |
| D1.5 | Run-button gate must say "yes" before this fires. | deterministic | Agile auto-runs without prerequisites. | Frontend gate (`computeCanRunOptimization`) + backend gate. Defense in depth. |

---

### D2. Cancel an in-flight run

**UI**: Cancel button.
**Wire**: `POST /sessions/{id}/optimization/cancel` → flips a flag the MEALpy objective checks.

#### Required outputs
- Solver returns "Optimization cancelled" status.
- Run record persisted with that status.
- No chat ack required.

#### Inferences
- None (deterministic).

---

### D3. "Explain Run #N" button

**UI**: per-run button in results panel (`explainRun`).
**Wire**: synthetic post `"Please explain Run #N in plain language for me. Include: ..."` with `invoke_model: true`. Goes through A1 fully.

#### Required outputs
- Visible reply only (a long-form explanation).
- No brief/panel change expected, but this turn is *not* skip-flagged → if the LLM emits a patch it will apply.

#### Inferences

| # | Question | Kind | Failure mode | Consolidation note |
|---|----------|------|--------------|---------------------|
| D3.1 | Long-form interpretation. | LLM | Generic; misuses domain terms; leaks problem identity. | Same as A1.2. |
| D3.2 | Edit-intent should be False. | (A1.1) | Spurious patches to brief/panel during an explanation. | The synthetic message has clear "explain" framing — embedding prefilter catches this confidently; treat that prefix as "force change_intent=false". |

---

### D4. Mark a run as "candidate" / unmark

**UI**: checkbox in the results panel; pure client state (`candidateRunIds` in `useClientController`).
**Wire**: **none** until next `runOptimize`, where the candidate run IDs are passed to the new run as seeds.

#### Required outputs
- Local state updated.
- (On next D1) `candidate_seed_run_ids` and `candidate_seeds` sent in the run request.

#### Inferences
- None. **Do not add an LLM call here.**

---

### D5. Reuse a run's config (button on a past run)

**UI**: "Reuse this config" → frontend hydrates the Problem Config editor from the run's `request.problem`.
**Wire**: same as C1 once the user clicks Save.

#### Required outputs
- Config editor populated from the past run; nothing persisted until Save.

#### Inferences
- None until Save → C1.

---

### D6. Edit a schedule and re-evaluate (without re-running solver)

**UI**: edit-mode → `runEvaluateEdited`.
**Wire**: `POST /sessions/{id}/runs/{run_id}/evaluate-edit { problem, routes }`.

#### Required outputs
- A new run row of type `evaluate-edit` with the edited routes' cost.
- No chat ack by default.

#### Inferences
- Deterministic (re-evaluate cost on edited routes via the port's evaluator).

---

### D7. Revert an edited run

**UI**: revert button.
**Wire**: same as D6 with the *original* routes.

#### Required outputs / Inferences
- Same as D6.

---

## E. Snapshot actions

### E1. Bookmark current state

**UI**: "Bookmark snapshot" → `createSessionSnapshotBookmark`.
**Wire**: `POST /sessions/{id}/snapshots`.

#### Required outputs
- Snapshot row with current brief + panel.

#### Inferences
- None.

### E2. Restore Definition / Config from snapshot

See B5 / C4.

### E3. Snapshot listing / preview

**Wire**: `GET /sessions/{id}/snapshots`.

#### Inferences
- None.

---

## F. Settings & lifecycle actions

### F1. Save model API key / model name

**UI**: `saveModelSettings`.
**Wire**: `PATCH /sessions/{id}/settings`.

#### Inferences
- None.

### F2. Toggle "use AI" / `invokeModel`

Pure client state — gates whether subsequent actions pass `invoke_model: true`.

### F3. Upload data file (currently simulated)

**UI**: `simulateUpload([fileNames])`.
**Wire**: synthetic post `"I'm uploading the following file(s): ..."` (goes through A1, with `is_upload_context=True`); then `POST /sessions/{id}/simulate-upload`.

#### Required outputs
- Upload-related OQs resolved server-side (`resolve_upload_open_questions_after_upload`).
- Chat ack.

#### Inferences
- A1, with `is_upload_context=True` modifying prompts.
- The upload OQ resolution itself is deterministic.

---

## G. Things that look like LLM work but are not

These are documented to prevent accidentally adding LLM calls.

| Action | Today's mechanism | Keep deterministic |
|--------|-------------------|---------------------|
| Run-button enable/disable + reason | `can_run_optimization` + `_run_gate_blocked_message` | Yes |
| Brief ↔ panel mirror after a panel save | `merge_brief_from_panel` (panel→brief copies `goal_terms` verbatim into the brief) | Yes |
| Per-rule prose synthesis from goal_terms | port `synthesize_brief_items_from_goal_terms` (VRPTW: one `config-driver-pref-*` row per rule, rendered in `vrptw_problem/brief_seed.synthesize_driver_preference_items`) | Yes |
| Stale prose-row dedupe when goal_terms change | port `prose_id_prefixes_for_goal_term` + id-prefix filter in `_synthesize_goal_term_prose_items` (no text inspection) | Yes |
| Snapshot pruning (FIFO 2000) | `session_snapshots.py` | Yes |
| Workflow phase | `resolve_workflow_phase` from brief shape | Yes |
| Sanitize panel weights / clip ranges | port `sanitize_panel_config` | Yes |
| Cancellation flag check | `solve_cancel.py` | Yes |
| Tutorial step transitions | `patchForTutorialEvent` | Yes |
| Goal-term-order validation | `validate_problem_goal_terms` (structural) | Yes |
| Project nested `properties.driver_preferences` to top-level `problem.driver_preferences` | `vrptw_problem/study_bridge._apply_goal_terms_overlay` | Yes |
| Rebuild `goal_terms` from top-level `weights` + `constraint_types` + `driver_preferences` | `vrptw_problem/study_bridge._rebuild_goal_terms_metadata` | Yes |

---

## H. `goal_terms` as the structured carrier — round-trip walk-through

This is the canonical pipeline for any structured per-goal-term metadata that has to survive the chat → brief → panel → brief loop. VRPTW's driver-preference rules and `max_shift_hours` are the live examples; new ports plug in at the same hooks without touching shared code.

### Schema (problem-agnostic shared layer + per-port slot)

- `backend/app/problems/schema_shared.py` exposes `goal_term_entry_schema(properties_schema)` and `goal_terms_schema(properties_schema)` factories. Default schema is permissive (`additionalProperties: True`).
- Each port overrides `StudyProblemPort.goal_term_properties_schema()` to return the typed shape for `goal_terms[key].properties`. VRPTW lives in `vrptw_problem/panel_schema.VRPTW_GOAL_TERM_PROPERTIES_SCHEMA` and types `driver_preferences` (vehicle_idx, condition, penalty, zone / order_priority / limit_minutes, aggregation) plus `max_shift_hours`.
- The brief-update LLM response schema is built per port at call time (`_build_brief_update_response_schema(test_problem_id)` in `services/llm.py`); the panel-patch response schema reuses the same factory in each port's `panel_schema.py`. Gemini structured output therefore sees a fully typed `properties` object and emits real rule objects rather than empty `{}`.

### Carrier (one shape on both sides)

- Brief: top-level `goal_terms` dict alongside `items`, `open_questions`, `goal_summary`, `run_summary`. `default_problem_brief()` seeds `{}`. `normalize_problem_brief` validates entries field-by-field via `_normalize_goal_term_entry` / `_normalize_driver_preference_rule` (tolerant — drops malformed rules without erroring).
- Panel: `panel.problem.goal_terms` is the canonical solver-config storage after `sanitize_panel_weights`. The legacy top-level `weights` / `constraint_types` are popped post-sanitize; `_apply_goal_terms_overlay` projects nested `properties.driver_preferences` onto the top-level `driver_preferences` field that the solver reads.

### Merge semantics (`merge_problem_brief_patch`)

- Per-key deep merge at the `goal_terms[key]` level — patching `worker_preference` does not drop `travel_time`.
- Inside an entry, `properties` is deep-merged at the property-name level — patching `driver_preferences` does not drop a sibling `max_shift_hours`.
- `properties.driver_preferences` (a list) is replaced wholesale on every patch — no rule-identity heuristic.
- A `replace_goal_terms: true` flag swaps the full map.

### Chat-turn flow (brief-update LLM)

1. `generate_problem_brief_update` runs with the per-port schema; the model emits rules under `problem_brief_patch.goal_terms.worker_preference.properties.driver_preferences`.
2. `apply_brief_patch_with_cleanup` merges the patch via `merge_problem_brief_patch`.
3. Same function then calls `_synthesize_goal_term_prose_items` (`backend/app/routers/sessions/derivation.py`):
   - Reads `port.prose_id_prefixes_for_goal_term(key)` for each goal-term key the brief touches → set of "owned" prefixes (VRPTW returns `("config-driver-pref-",)` for `worker_preference`).
   - Drops every existing brief item whose id starts with one of those prefixes (id-only filtering).
   - Calls `port.synthesize_brief_items_from_goal_terms(goal_terms)` to render fresh prose items and merges them in.
4. The brief is re-normalized through `normalize_problem_brief` so the slot reconciler dedupes any leftovers.
5. `sync_panel_from_problem_brief` derives the panel from the brief; `goal_terms.worker_preference.properties.driver_preferences` is copied verbatim into the panel (LLM and deterministic seed both honor it).

### Panel-save flow (manual UI edit)

1. `sanitize_panel_config` validates and rebuilds `panel.problem.goal_terms` from the submitted form data.
2. `sync_problem_brief_from_panel` copies `panel.problem.goal_terms` into `brief.goal_terms` verbatim, then runs the port's prose synthesizer through `_brief_items_from_panel` to refresh `config-driver-pref-*` rows.
3. `merge_brief_from_panel`'s slot reconciler keeps last-by-slot semantics; stale rows get pruned because every config-* item is replaced fresh on each panel→brief sync.

### Evidence anchoring (per-key gate against hallucinated additions)

Every `goal_terms[key]` entry can carry `evidence_item_ids: list[str]` citing the brief `items[]` rows that justify it. Both the brief-update LLM (`STUDY_CHAT_BRIEF_UPDATE_TASK`) and the panel-derive LLM (`VRPTW_CONFIG_DERIVE_SYSTEM_PROMPT`) are instructed to populate this whenever they introduce a new term.

`app.services.goal_term_anchoring.filter_unanchored_new_goal_terms` runs at two points:

1. **Brief-merge** (`apply_brief_patch_with_cleanup` in `derivation.py`) — after `merge_problem_brief_patch` and prose synthesis, before normalize.
2. **Panel-derive** (`_merge_non_destructive_managed_fields` in `sync.py`) — when the LLM-derived panel adds weight keys not in the prior panel.

The filter only drops **newly-introduced** keys (not in `base_brief.goal_terms`); existing keys are preserved unconditionally so retunes don't regress. Anchor priority:

1. **Explicit cite** — `evidence_item_ids` resolves to at least one valid items[] id. Workflow-aware: waterfall = only `gathered`; agile/demo = `gathered` + `assumption`.
2. **Self-anchored properties** — `worker_preference` with non-empty `properties.driver_preferences`, or `shift_limit` with `properties.max_shift_hours` set. The structured rule list is its own justification; no separate prose row is required.
3. **Embedding cosine fallback** — best-effort. `text-embedding-004` cosine of `(key + label)` against each item text; threshold 0.55. Silently no-ops without an API key (caller's `change_clause` short-circuit will keep most concept-only turns from reaching this code path anyway).

**Search-strategy grounding (separate gate).** Algorithm/epochs/pop_size/algorithm_params don't live under `goal_terms` so they're not covered by `evidence_item_ids`. A simpler deterministic gate runs in `_merge_non_destructive_managed_fields`: if no brief item names a known algorithm (case-insensitive substring match on canonical names + aliases via `algorithm_mentioned_in_brief`), the LLM-derived search-strategy fields are dropped and the current panel values preserved. Closed 5-algorithm vocabulary; word-boundary checks on the short aliases (`ga`, `sa`, `pso`, `acor`) prevent false positives like "garbage" or "psoriasis".

**Panel-sanitize evidence preservation.** `_rebuild_goal_terms_metadata` (`vrptw_problem/study_bridge.py`) rebuilds `goal_terms` from `weights` + `constraint_types` after every panel save. It reads the prior `goal_terms` map so that `evidence_item_ids` (and any other opaque fields the schema declares) survive the rebuild — manual retunes therefore keep their cite trail intact across saves.

### LLM contract (single source of truth)

`vrptw_problem/study_prompts.DRIVER_PREFERENCES_BRIEF_CONTRACT` is imported by both `VRPTW_STUDY_PROMPT_APPENDIX` (chat / brief-update side) and `VRPTW_CONFIG_DERIVE_SYSTEM_PROMPT` (panel-derive side). The contract names the exact path, the per-rule fields, and the no-prose-duplication rule — the two prompts can never drift because they share the same string. Future ports add their own contract constant alongside their problem module.

### What the participant sees

- Definition tab: one `gathered` row per rule, e.g. *"Alice avoids deliveries in Zone D as a soft preference (penalty 50)."* — id `config-driver-pref-0-zone-D`.
- Problem Config tab: `worker_preference` goal-term block expands to show editable rule rows (driver, condition, penalty, zone) backed by the structured `goal_terms.worker_preference.properties.driver_preferences` array.
- Removing a rule (chat or panel) drops both the structured entry and the synthesized prose row on the next turn — id-prefix filter handles staleness without text inspection.

---

## I. Cross-cutting matrix: what each action needs from each system

Legend: ● = required · ◐ = optional · — = not used

| Action | Visible chat LLM | Brief LLM | Config LLM | Embedding intent prefilter | Embedding doc retrieval | Embedding hallucination check | Schema validation |
|---|---|---|---|---|---|---|---|
| A1 chat (edit) | ● | ● | ● | ● | ◐ | ◐ | ● |
| A2 chat (concept) | ● | — | — | ● | ● | — | — |
| A3 chat (status) | ● | — | — | ● | ◐ | — | — |
| B1 brief save | ◐ | — | ● | — | — | ● | ● |
| B2 OQ answer | ◐ | ● (batch) | ● | — | — | ● | ● |
| B3 OQ cleanup | — | ● | — | — | — | — | ● |
| B4 def cleanup | ● | ● | ● | — | — | ◐ | ● |
| B5 restore def | ◐ | — | ● | — | — | — | ● |
| C1 panel save | ● | ● | — | — | — | ● | ● |
| C2 sync | — | — | ● | — | — | ● | ● |
| C3 recover | — | — | ● | — | — | — | ● |
| C4 restore cfg | ◐ | — | — | — | — | — | ● |
| D1 run | ● | ◐ | — | — | — | — | ● |
| D2 cancel | — | — | — | — | — | — | — |
| D3 explain run | ● | — | — | ● | ◐ | — | — |
| D4 mark candidate | — | — | — | — | — | — | — |
| D5 reuse cfg | — | — | — | — | — | — | — |
| D6/D7 evaluate edit | — | — | — | — | — | — | ● |
| E1 bookmark | — | — | — | — | — | — | — |
| E2 restore (see B5/C4) | — | — | — | — | — | — | — |

---

## J. Open accuracy questions (unresolved by current code)

1. **Concept-question vs edit-intent boundary.** The single highest-volume failure mode. Today: regex fallback returns True almost always; LLM classifier when available works but adds a round-trip. **Next step**: embedding-centroid prefilter with a 30–80 exemplar set per workflow mode; LLM only on ambiguous middle.

2. **Goal-term key hallucination.** ~~Schema closes the key set per problem, but a key not anchored in the brief still slips through and confuses the user.~~ **Resolved**: `goal_terms[key].evidence_item_ids` cites brief `items[]` ids; `app.services.goal_term_anchoring.filter_unanchored_new_goal_terms` drops unanchored newcomers at both brief-merge and panel-derive. Embedding-cosine fallback handles cases where the LLM forgets to cite. Existing keys preserved.

3. **Item dedup.** The retired regex-based dedup left no replacement. **Next step**: embedding cosine against existing items at brief-merge time; suppress proposed near-duplicates without keyword matching.

4. **Visible/brief consistency under consolidation.** The current band-aid (echoing visible reply into the brief prompt) is lossy. **Next step**: one structured chat call that emits both `assistant_message` and `problem_brief_patch` in the same response. Single source of truth.

5. **Doc retrieval recall.** TF-IDF misses paraphrases. **Next step**: replace `services/docs_index.py` with embeddings (e.g., `text-embedding-004` from the same `google-genai` SDK); build the index once at startup, cache on disk.

6. **Brief committed before panel sync** in `PATCH /sessions/{id}/problem-brief`. A panel-derivation failure leaves a brief on disk that's been committed but doesn't match the panel. The Recover banner papers over this; a transactional commit (or undo) would be cleaner, but lower priority — it's a data-consistency issue, not an accuracy one.

---

## K. Quick reference: which call gets consolidated and which stays separate

**Consolidate into one structured chat call (per chat turn)**
- Visible reply (A1.2)
- Edit-intent classification (A1.1) — or replaced by an embedding prefilter that runs *before* the LLM
- Brief patch (A1.4)
- Run-trigger intent + run-invitation classification (A1.3 + A1.6)
- Cleanup-intent + clear-intent flags

**Keep separate (justified by different cadence, schema, or purpose)**
- Config derivation from brief (A1.5 / B1.1) — per-problem schema, no chat history needed, big system prompt benefits from explicit caching.
- Open-question batch classifier on brief save (B2.1) — only fires on save, batched.
- Open-question cleanup pass (B3.1) — explicit user action, dedicated call.
- Chat-temperature classifier (A1.8) — only when ambiguous; cheap.

**Not LLM at all**
- Run-button gate, snapshot ops, weight sanitization, brief ↔ panel mirror after panel save, workflow phase resolution, tutorial transitions.
