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
- **term** — dynamic goal-term keys (VRPTW = all 8 incl. `waiting_time`, via `port.weight_item_labels()`). Card badge = EFFECT glyph (researcher request, replaced the old captured-✓/✗): ✓ applied, ? mentioned, ✗ dropped/declined/removed — colored by EFFECT_COLOR.
- **effect** — applied | **mentioned** (the term appeared in someone's words while not yet active — tagged at FIRST mention, no reaction from the other side required; who mentioned it = origin) | **removed** (a term that WAS in the config and is taken out — a retraction; AUTO from the goal_terms diff, origin = who removed it) | **dropped** (user raised but never registered — MANUAL judgment, parser no longer auto-emits it) | **declined** (agent proposed, user rejected — MANUAL). Taxonomy decision: keep effect to these; do NOT merge origin/transparency into effect (would duplicate origin + explode combinatorially). ask-vs-assume is read off the trajectory (mentioned/OQ→applied = asked; direct applied = assumed), NOT a new origin value. transparency (silent/explicit applied) deferred — not in the researcher's report metrics.

**Effect rename (2026-08): `acknowledged` → `mentioned`** — researcher decision;
"acknowledged" wrongly implied the OTHER side reacted, but the tag's key use is
ignored mentions (P01 0:08). NO legacy alias: a startup migration
(`_convert_acknowledged_to_mentioned` in analysis_db.py, idempotent, runs every
boot so restored old backups get converted too) rewrote all stored annotation
JSON + `coding_llm_tags` caches (345 + 342 tags). Frontend EFFECT_VALUES/colors,
LLM `_EFFECTS` + prompts, notebook comments all renamed.

`_canon` number-normalizes (50 == 50.0) — the stored config re-serializes ints/floats inconsistently, which was firing phantom detail + cfg-changed flags every turn.

**search-param** (solver knobs) is compared via `_canon` (order- + number-insensitive: a re-serialized param dict in a different key order is NOT a change) and is SUPPRESSED when the algorithm also changed that turn (the knob delta is then just the new algorithm's defaults, already captured by the search-strategy tag — dropped 52 redundant firings, 109→57). `random_seed` is excluded from `_PARAM_FIELDS` (internal per-run seed, not a coded tuning decision). **Param key-removal churn** (`_param_field_changed`): an `algorithm_params` KEY silently VANISHING (pipeline re-serializes partial params; solver falls back to defaults) is NOT a change — only value changes / key additions count (P30 29:27 `temp_init` vanished on a pure explanation turn; 3 phantom deltas in 28 sessions, the 3 mistakenly-accepted tags surgically deleted). The `other: cfg ✎` fallback also ignores params (`panel_changed_beyond_diff`). The user-edit reconstruction also restores the top-level `locked_goal_terms` list (`_restore_locked_list`) — a "locked — → on" edit line changes it, and it leaked one exchange early otherwise.

**LLM tagging pass (2026-08 REWRITE — replaces both the mechanical goal-term
suggester AND the origin-only classifier).** Goal-term tags are judgment calls
that kept mis-firing mechanically, so `coding_llm.tag_session_changes` (one
batched Gemini call/session, structured JSON, no regex) reads EVERY codeable
exchange + deterministic evidence (structured config diff facts, captured-after
set, open goal-OQs, PANEL-EDIT/OQ-ANSWER markers) and proposes composite tags
{origin, type∈goal-term/detail/weight/term-type/ranking, term, effect, rationale}.
Primary goal: each term's FIRST-applied exchange + true origin; secondary:
mentioned-but-never-implemented (mentioned→dropped/declined). Term enum =
port catalog ∪ observed custom terms. Cached in `CodingLlmTags` (per-session
data_json = {row_ref: [changes]}; replaced `OriginClassification`; new table via
create_all, no migration). Trigger: **✨ LLM tagging** button → `LlmTagDialog` →
POST `/analysis/llm-tags`. **No api_key = PURE no-op (cache KEPT — the old
endpoint destructively overwrote); per-session failure → `failed` count, old
cache kept; locked sessions skipped.** Tags land as SUGGESTIONS (dashed cards,
rationale tooltip ℹ, ＋accept / Accept-all) — never auto-materialized. ~8k
tokens/session ≈ pennies on Flash. Prompt hardening (researcher request): an
explicit MENTION-SCAN step (semantic mentions in USER/AGENT text → `mentioned`
at first mention EVEN IF the other side ignores it — P01 0:08 user mentions time
windows, agent doesn't react; also agent-asked terms the user never engages),
a completeness cross-check (early mention BEFORE later application carries both
tags; END-OF-SESSION sweep gives never-landed terms a `dropped`), and NO
`ranking` tag on a term's ADDITION (its rank slot is part of the add; the diff
evidence deliberately omits rank on `+ term` lines). **Two-pass generate→audit**
(P01 0:00 bug: a FILE-UPLOAD exchange got travel_time origin `user` while the
tag's own rationale said the AGENT mentioned it): pass 1 is recall-oriented; a
second ADVERSARIAL AUDIT call re-reads the same evidence and keep/fix/drops each
proposed tag (cannot add tags; audit failure keeps unverified tags). Guards:
"WHAT COUNTS AS A MENTION" (uploads/data descriptions/capability talk ≠ mention;
origin = the side whose TEXT contains it) + a FILE UPLOAD exchange marker
(`I'm uploading…`). ~2 calls/session, still pennies. **FACT BACKFILL — the LLM
is judgment, NOT coverage** (P01: 19 weight-change exchanges got 0 weight tags
from a flash-lite model even with the facts in-prompt): after generation,
`_backfill_facts` adds a tag for every structurally PROVEN change the LLM missed
(`_fact_changes` from the structured diff: weight/term-type/ranking/detail/
goal-term add/removed → effect applied/removed). Origin set deterministically on
PANEL-EDIT ack turns (`user`) and OQ-ANSWER turns (`agent`), else `None` →
rendered `?`; the audit is REQUIRED to fix `?` origins and is FORBIDDEN from
dropping [FACT] tags or changing their type/term/effect (only origin+rationale).
Model choice matters: flash-lite under-tags badly — use at least flash.
**Purge & re-label** checkbox in LlmTagDialog (`purge_tags` in POST /llm-tags):
per session, ONLY after its LLM run succeeded, auto-backup ("llm-retag") then
delete `code` + `dismiss` annotations (notes/markers/pauses survive; failed run
purges nothing; no-key no-op purges nothing; locked skipped). Response carries
`purged_tags`. **Suggestion dismissal**: ✕ on a dashed suggestion card persists
an `anno_type='dismiss'` annotation ({origin,type,term,effect} JSON on row_ref);
`_timeline_payload` filters matching suggestions out (key = origin|type|term|
effect); rows.py folds dismissals (never rendered as rows/CSV); reset-tags now
clears `code` AND `dismiss`; dismissals ride along in coding backups. **Goal-term FATE** is then
computed in the notebook origins cell (from ACCEPTED tags): full box = applied at
first code, lower-right half-box = mentioned → applied later, X (origin-colored)
= mentioned never applied; plus printed fate counts by workflow/origin. Backups dump/restore `llm_tags` (restore only
when the target has no cache row). Search-strategy/search-param tags stay
DETERMINISTIC (`_search_changes`: algorithm/knob field diffs, user-origin on
manual-edit ack turns) and merge into the same suggestion list — the LLM is told
not to emit them. **Interaction→outcome notebook cells** (after the solver grid; print-only):
BREAKTHROUGH (first session-best run position + ended-on-best by arm), BIG JUMPS
(top-quartile improving transitions; reason mix; jump-window origin dominance),
FEASIBILITY flips + causal partners, RERANKING (user-origin ranking participants
by arm), WEIGHT OSCILLATION (direction reversals + reverser origin). Powered by
dataset additions: annotations rows carry `reasons` (parsed list for
anno_type='reason') and a `weight_changes` frame (per-exchange goal-term weight
from→to; origin joined in-notebook from accepted weight tags). All tallies
recompute from ACCEPTED labels on Re-fetch. **`search_changes` dataset frame** (in `/analysis/dataset` +
pyodide globals): field-level solver events from the structural diff layer —
`algorithm` + scalar knobs + `algorithm_params` expanded PER KEY (cooling_rate,
c1, pc…), with deterministic origin; drives the notebook SOLVER-CHANGE GRID
(cell-21-style: rows = change kinds, cols = ALL participants, count + origin
color, diagonal split = both) and complements the search-initiation bars. BOTH
exclude each session's first strategy event (mandatory setup, not a "change" —
this exclusion flipped strategy switching from agent-dominant to ~50/50).

**Improvement-REASON layer (2026-08)** — separate from change tags by researcher
requirement (own annotation type `reason` = ONE per row {reasons:[], note}; own
cache table `CodingLlmReasons`; own ✨ LLM reasons button/dialog/endpoint
POST /analysis/llm-reasons — running/purging one never touches the other). RUN
rows ONLY get the "reason" column (a reason attributes the outcome change
between two CONSECUTIVE runs — formulation-jump exchanges were removed by
researcher decision); once the LLM has checked a run its verdicts REPLACE the
mechanical candidates for that run (`_reason_suggestions_for`, mirroring the tag
layer; match = auto+llm green; uncovered runs fall back to mechanical): vocab (facets
REASON_VALUES == reason_llm.REASONS): new-goal-term/term-removed/weight-rebalance
/term-type-change/detail-refinement/ranking-change/algorithm-switch/search-budget
/knob-tuning/feasibility-fix/stochastic-rerun/other. Deterministic candidates =
`reasons_from_diffs` over the structured diffs BETWEEN runs; evidence =
`outcome_delta` {cost_delta, feasibility flip, movers} from **per-term canonical
contributions** (`term_contributions` added to
`canonical_evaluation_for_result`; `_canonical_eval_cached` now returns a dict).
LLM pass (verify_reasons) double-checks candidates against the conversation;
merged suggestions marked source auto/llm/auto+llm (agreement = strongest,
green). CSV gains a `reasons` column. Reset-tags/purge do NOT touch reasons;
`POST /loaded/{id}/reset-reasons` deletes ONLY the reason layer — labels AND
`dismiss-reason` rejections (auto-backup "reset-reasons"). Reason suggestions
are rejectable like tag suggestions: ✕ persists `anno_type='dismiss-reason'`
({reason} JSON on row_ref); `_filter_dismissed_reasons` drops them server-side.
Toolbar = two labeled groups: purple **tags** (✨ LLM tagging / Accept all /
Reset) vs teal **reasons** (✨ LLM reasons / Accept all / Reset). Reasons
"Accept all" became sound once LLM verdicts REPLACE mechanical candidates
(shown suggestions = judged set, or mechanical fallback on unchecked runs);
it accepts every shown suggestion on not-yet-labeled runs, dismissed excluded.
**feasibility-fix = OUTCOME QUALIFIER, never alone** (it's a result, not a
cause): mechanical layer only ever APPENDS it to found causes (skipped on
luck-flips); LLM prompt says pair it with the causal change; a standalone LLM
verdict is REJECTED in validation (run falls back to mechanical candidates);
ReasonCell shows ⚠ if an accepted label is feasibility-fix alone. **soft↔custom type change is
the panel's weight-UNLOCK mechanic, NOT a semantic type change** — excluded from
`term-type-change` reason candidates (`reasons_from_diffs`) and called out in
the reason-LLM prompt (attribute to weight-rebalance); transitions involving
hard/objective still count.
that follows it (`user_prompt` on the row; standalone user rows suppressed unless
no reply follows). Coding targets only `codeable` rows — agent chat responses +
`manual_save` snapshots — since the chat is instant. EventList shows `user ▸` /
`agent ▸` and gates `ChangeTagCell` on `row.codeable`.

**Deterministic state derivation** in `app/analysis/coding_suggestions.py` —
after the 2026-08 rewrite it emits NO goal-term tag suggestions (LLM's job);
it provides the verified state pairing, the **structured config diff**
(`structured_config_diff` → {algorithm/params/terms[field from→to]/added/removed
/other}, rendered as colored CHIPS in the cfg Δ column via `ConfigDiffChips`,
serialized as JSON in CSV), the **stripped def Δ** (`brief_for_display`: brief
minus `goal_terms` mirror + `runs` history, used for BOTH the change gate and
display — a def Δ can no longer look like a config change; same treatment for
snapshot rows in `diffing.py`), and the deterministic search tags. Every
exchange with a state is emitted (display consistency), even change-free ones.
Def/config are primarily updated through **assistant chat turns**, so derivation
anchors there (snapshots are sparse):
- `build_turn_derivations(messages, port, user_raised_by_ref)` — `pre_turn_state`
  is the state BEFORE a reply, so a reply's RESULT lives in the NEXT turn's
  pre-state. **Agent-response attribution (look-AHEAD + post-state display)**:
  pair exchange i with state i+1 (reply i's result), tag reply i's changes there,
  AND return that post-state brief/panel as `problem_def`/`problem_config` for the
  row to DISPLAY (endpoint overrides the pre-state). So the config shown reflects
  the agent's response, not the user-send state (fixed "config one step behind":
  P01 workload_balance added & shown @16:11; capacity @0:08). A term the reply
  *configures* → `applied` that exchange; a term it only *recognises* (brief, not
  config) → `mentioned`, flipping to `applied` on the later exchange that
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
  limit" = shift_limit, "Algorithm:" = search_strategy carrier + panel
  `algorithm`/`algorithm_params`, "Max iterations"/"Population size" =
  epochs/pop_size; deterministic, NOT NL) and restore each edited term to the
  AGENT's own value (`v2_turn_snapshot.problem_brief_patch.goal_terms` if the reply
  set it, else this reply's pre-state, else drop); panel search fields restore via
  `_restore_search_fields` to the row's pre-state (P30: 9:06 run-ack stays PSO, not
  the 12:36 `Algorithm: PSO→GA` edit — that switch now lands on its own 12:36 turn).
  **Manual-edit origin:** on the ack turn, any change whose term the participant
  edited (or a search-strategy/param change when a search field was edited) is
  forced `origin: user` — the participant made it by hand (P30 algorithm @12:36 =
  user; P02 1354 lateness weight edit = user, not agent). Terms the participant
  did NOT
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
  number-normalizes (50==50.0). **First-exchange baseline:** every session's
  OPENING assistant turn carries NO `pre_turn_state` (setup reply pre-dates
  state recording; 28/28 sessions), so its changes are baked into the first
  recorded pre-state — diffing the first state-carrying exchange against its
  own pre-state SWALLOWED them (9/28 sessions lost initial term adds; P07 0:32
  showed no cfg Δ for capacity+lateness). Fix: when state-less assistant chat
  turns precede the first recorded state, the baseline is EMPTY ({}), so the
  first exchange surfaces everything built so far (incl. the initial algorithm
  → a search-strategy tag, consistent with empty-pre-state sessions).
- **Origin principles (now encoded in the LLM prompt, not mechanical code —
  the consume-on-apply/`_origin_for`/`_pending` machinery was REMOVED with the
  2026-08 rewrite):** origin = who INITIATED that specific change, not who first
  raised the term (agent post-run re-tunes of a user's term = `agent`, P01
  16:46/20:15); a term configured because the user ANSWERED the agent's OQ =
  `agent` (P02 workload @8:03); a "Config edited"/"Definition edited" panel edit
  = `user`. `_post_run_refs`/`_oq_answer_refs` survive only to gate the
  search-tag provenance fallback (`suppress_fallback`) and the result-state
  pairing.
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
is deliberately UN-guarded (only way to unlock). `/llm-tags` **skips** locked
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

**Aggregate notebook uses the MANUAL codes.** The `/dataset` `annotations` frame
now carries the parsed coded-change facets `{origin, type, term, effect}` (via
`_parse_change(a.text, a.label)`; null for note/marker rows — raw `text` is NOT
exported, so no free-text leak). Re-parsed live each dataset load ⇒ re-code +
Reload data + re-run refreshes. Notebook **goal-term ORIGINS matrix** (browser_cells,
was the hand-coding placeholder): "who INITIATED each term" = the origin of the
EARLIEST coded change per (session, term), timed by joining `row_ref` ("message:<id>")
→ `messages.ts_epoch`. NOTE the initiator view differs from all-changes counts: on
this data agile 37% vs waterfall 40% agent-INITIATED (near-equal), while ALL changes
were agile 70% vs waterfall 51% agent — agile's agent-share is post-init tweaks, not
initiations. Also a **runs-per-time** agile/waterfall cell (part.runs_per_min /
runs_per_active_min, estimation style: d + 95% CI + MW).

Video coding is **paused by default** (toggle in the tab); a video-independent
`t` column (first message = 0) drives wall-clock coding. See
[[project_architecture]] and [[feedback_dynamic_algorithm_oq]] (port-driven
dynamic values). Message-level (non-snapshot) origin/type stays manual for now —
LLM-assisted classification was explicitly deferred.
