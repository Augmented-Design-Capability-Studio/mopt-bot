---
name: project_session_coding_scheme
description: The faceted tagging scheme + deterministic auto-suggestions in the analyzer Session-coding tab
metadata:
  type: project
---

The analyzer **Session coding** tab codes each information-exchange as ONE
**composite change** = {origin, type, goal term, effect}, and a row can carry
many. Stored as a `code` annotation whose `text` is that JSON on a `row_ref`
(NOT the old `facet:value` label scheme). Rendered in a single "coding" column
via `ChangeTagCell` (four inline dropdowns per change). Field vocab in
`frontend/src/analyzer/lib/facets.ts`:

- **origin** — user | agent (dropped a `prompted` idea: agent-offered-user-picked = origin agent + effect applied; rejected = effect declined)
- **type** — goal-term | **detail** (properties diff: driver_preferences, max_shift_hours) | weight | term-type | ranking | search-strategy | search-param
- **term** — dynamic goal-term keys, badged captured ✓/✗ (VRPTW = all 8 incl. `waiting_time`, via `port.weight_item_labels()`)
- **effect** — applied | **acknowledged** (recognised in brief items/OQ OR present-but-inert, at first recognition) | **removed** (a term that WAS in the config and is taken out — a retraction; AUTO from the goal_terms diff, origin = who removed it) | **dropped** (user raised but never registered — MANUAL judgment, parser no longer auto-emits it) | **declined** (agent proposed, user rejected — MANUAL). Taxonomy decision: keep effect to these; do NOT merge origin/transparency into effect (would duplicate origin + explode combinatorially). ask-vs-assume is read off the trajectory (acknowledged/OQ→applied = asked; direct applied = assumed), NOT a new origin value. transparency (silent/explicit applied) deferred — not in the researcher's report metrics.

`_canon` number-normalizes (50 == 50.0) — the stored config re-serializes ints/floats inconsistently, which was firing phantom detail + cfg-changed flags every turn.

**Origin** — brief provenance is UNRELIABLE (P01: the agent says "since you
mentioned capacity and shift" yet the brief logs those terms `assumption`). So
the authoritative signal is the user's own words via an **LLM pass**
(`origin_llm.classify_user_origins`, one batched Gemini call/session, structured
JSON, no regex). Cached in `OriginClassification` (data_json = {user msg
source_id: [terms raised]}) so a refresh never re-hits the API. `_timeline_payload`
folds it onto the prompting agent turn (`_user_raised_by_turn`) and passes
`user_raised_by_ref` into `build_turn_derivations`; `_change` prefers it over the
brief provenance fallback (`_term_origins_from_brief`: gathered→user,
assumption→agent). Trigger: **✨ Auto-detect origin (LLM)** button →
`OriginClassifyDialog` (model + API-key inputs, DialogShell) → POST
`/analysis/classify-origin` (no key = safe no-op). Cost ≈ pennies for all 28
sessions on Flash. Effect: active→applied, present-but-inactive→acknowledged,
gone→dropped. `_unapplied_user_requests` flags a user term (LLM or gathered) that
never became captured → {user, goal-term, term, acknowledged}, first-recognition
only.

**Exchange rows**: each user chat message is folded into the agent chat reply
that follows it (`user_prompt` on the row; standalone user rows suppressed unless
no reply follows). Coding targets only `codeable` rows — agent chat responses +
`manual_save` snapshots — since the chat is instant. EventList shows `user ▸` /
`agent ▸` and gates `ChangeTagCell` on `row.codeable`.

**Deterministic-only** auto-suggestion (researcher chose no LLM), in
`app/analysis/coding_suggestions.py`. Def/config are primarily updated through
**assistant chat turns**, so derivation anchors there (snapshots are sparse):
- `build_turn_derivations(messages, port, user_raised_by_ref)` — `pre_turn_state`
  is the state BEFORE a reply, so a reply's RESULT lives in the NEXT turn's
  pre-state. **Agent-response attribution (look-AHEAD + post-state display)**:
  pair exchange i with state i+1 (reply i's result), tag reply i's changes there,
  AND return that post-state brief/panel as `problem_def`/`problem_config` for the
  row to DISPLAY (endpoint overrides the pre-state). So the config shown reflects
  the agent's response, not the user-send state (fixed "config one step behind":
  P01 workload_balance added & shown @16:11; capacity @0:08). A term the reply
  *configures* → `applied` that exchange; a term it only *recognises* (brief, not
  config) → `acknowledged`, flipping to `applied` on the later exchange that
  configures it (P02 express_miss @12:07→@20:50). The displayed `problem_def`/`config` JSON and the effect labels come from the
  SAME result-state `R_i`, so they can't disagree (critical — effect is labeled
  off the shown config). `R_i` = next turn's pre-state EXCEPT when that pre-state
  carries a USER action that belongs to the NEXT exchange, not this reply — then
  keep this exchange's OWN pre-state so a later edit can't surface early. TWO such
  triggers: (a) the next turn ANSWERS an open question (`_oq_answer_refs`, user
  msg "Answered …") — keeps the open question visible (P02 7:25); (b) the next
  turn was preceded by a participant panel edit (`_user_edit_info`, user msg
  "Config edited …"/"Definition edited …") — that edit was applied to the panel
  before the turn, so its change belongs to the exchange it folds into (fixed P02
  lateness 80→160 @13:33 leaking onto 13:06 → now lands on 1354; P01 25:25 ranking
  edit leaking onto 24:21). For a user-edit boundary the exchange is
  **RECONSTRUCTED** (`_reconstruct_after_edit`): base = the VERIFIED next-state
  (the real post-pipeline config), then UNDO ONLY the goal terms the edit named —
  parse the structured audit msg (`_parse_config_edit`: "goal term X: field",
  "Priority order" = all ranks, "Driver preferences" = worker_preference, "Shift
  limit" = shift_limit; deterministic, NOT NL) and restore each edited term to the
  AGENT's own value (`v2_turn_snapshot.problem_brief_patch.goal_terms` if the reply
  set it, else this reply's pre-state, else drop). Terms the participant did NOT
  touch stay as the verified next-state had them — so **pipeline-added companion
  details** survive on the right turn: P04 `worker_preference.driver_preferences`
  (the agent structured them @3:57; the raw patch lacked them, so the OLD "pre +
  patch" reconstruction wrongly deferred the detail to the 5:45 edit — see the
  key lesson below). The patch is used ONLY to restore edited terms (next-pre
  carries the edit on those fields; e.g. P01's 25:25 `type→custom` bumped the same
  weight to 100, but the patch has the agent's 20). **KEY: `v2_turn_snapshot` is
  the LLM's PROPOSED patch, captured before the verify/sync pipeline — NOT the
  verified config.** The pipeline clamps weights (hard→min), drops invalid terms
  (waiting_time w/o evidence), re-ranks, coerces types → patch matches the settled
  panel only ~53%. So the VERIFIED config lives ONLY in the next turn's
  `pre_turn_state`; that's the display source (never a snapshot; user's rule).
  Clean turns (no user action next) use the next pre-state directly. `_canon`
  number-normalizes (50==50.0).
- **Origin = who initiated THAT change, not who first raised the term**
  (`_origin_for` + consume-on-apply). A user request stays "active" from when the
  LLM says the user raised a term until the config reflects it; then it's consumed
  (`active_requests -= captured`). So agent post-run tweaks (agile) to a
  user-introduced term read `agent`. `user` only if the term is an active request,
  or (goal-term INTRODUCTION only) brief provenance is `gathered`; else `agent`.
  CUMULATIVE user-raised was REVERTED — it made every later tweak `user` (P01
  22:09/22:46 post-run weight edits were wrongly `user`). Plus a **post-run
  signal** (`_post_run_refs`: assistant chat turns that follow a `kind='run'`
  message): on those exchanges the provenance/search fallback is dropped, so the
  agent's proactive re-tunes read `agent` unless the user re-asked that turn
  (active request). P01 agile: workload @16:11 stays `user` (msg1228 asked), but
  @16:46/20:15 post-run re-tunes are `agent`. LLM detection only seeds which
  terms the user RAISED; it does NOT decide agent-vs-user tweaks — that's this
  consume + post-run logic, so re-running the LLM does not fix over-attribution.
- **OQ answers are agent-originated.** A user "Answered … open questions" message
  is the user RESPONDING to an agent OQ → the term was agent-ASKED. Two guards:
  (1) `_user_raised_by_turn` skips "Answered " messages so they don't seed
  user active-requests; (2) `_oq_answer_refs` marks the answering turn and sets
  `suppress_fallback` so the brief's (misleading) `gathered` provenance is
  dropped → origin agent (P02 workload applied @8:03 = agent, not user). Direct
  "Config edited"/"Definition edited" panel edits stay USER (not skipped).
  `suppress_fallback = post_run OR oq_answer` (renamed from `post_run`).
- `build_manual_save_suggestions(snapshots, port)` — a `manual_save` snapshot =
  user edited the panel directly ⇒ deterministic **origin: user** (the only
  auto-origin signal). `before_run` snapshots get no suggestions (redundant).
Captured ✓/✗ from `port.formulation_quality_for_config(...)["captured_terms"]`;
term dropdown from `port.weight_display_keys()`. Suggestions are UI aids —
click-to-accept (or "Accept all") materializes editable annotations; CSV export
carries only accepted codes, one column per facet. Message rows also expose the
full pre-turn def+config via the summary **expand** button.

**Per-session "coding done" lock** (🔒/🔓 toggle beside the ✕ in the loaded
list). `LoadedSession.locked` bool (migrated via `_ensure_loaded_sessions_locked_column`
in analysis_db.py; server_default 0). Enforced in TWO places, and any NEW edit
path must touch both: (1) front-end single chokepoint — `blockedByLock()` in
`useAnalysisController` gates every mutating method; a blocked attempt opens the
DialogShell unlock prompt instead of editing; (2) backend backstop — `_require_unlocked(loaded)`
raises **423** on all coding mutations. The toggle endpoint `POST /loaded/{id}/lock`
is deliberately UN-guarded (only way to unlock). `classify-origin` **skips** locked
sessions (`skipped_locked` in the response), never 423s the batch. Lock is NOT
in coding backups (workflow state, not coding data). Distinct from the study's
goal-term lock ([[feedback_lock_two_stores_reconcile]]).

**Best-result highlight** (in `_timeline_payload` → `_attach_scores_and_bests`):
run rows carry `canonical_cost`/`canonical_feasible` (port
`canonical_evaluation_for_result`, seed-averaged, lower=better) and message
(exchange) rows carry `formulation_score` (0–11, port
`formulation_quality_for_config`, higher=better). `best_canonical` stars the
lowest-cost run but a FEASIBLE run always outranks an infeasible one (a star
lands on an infeasible run only if none are feasible); `best_formulation` stars
EVERY exchange at the session peak (a plateau — "each exchange that achieved
it"). Both scored off the immutable result/config JSON via module-level
`lru_cache` (the timeline is re-fetched after every coding edit, so only the
first load pays the canonical cost). Rendered as `★`-tinted pills in EventList
(`ScoreBadges`, gold=canonical, green=formulation); NOT in the CSV export.

Video coding is **paused by default** (toggle in the tab); a video-independent
`t` column (first message = 0) drives wall-clock coding. See
[[project_architecture]] and [[feedback_dynamic_algorithm_oq]] (port-driven
dynamic values). Message-level (non-snapshot) origin/type stays manual for now —
LLM-assisted classification was explicitly deferred.
