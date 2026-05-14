# Plan: Unified, symmetric run-gate across agile / waterfall / demo

Status: planning only. No code yet. Companion to
`interface_flow_critique.md` items #1 and #6, and the audit produced
during the 2026-05-14 session.

## Context

Today the run gate is three separate intrinsic functions
(`intrinsic_optimization_ready_agile/_waterfall/_demo`) plus a
dispatcher, a `gate_status` snapshot, and a `can_run_optimization`
wrapper. The mode branches accumulated organically and now disagree
in three places that have nothing to do with the modes' *intended*
semantic difference (waterfall enforces open-question resolution; the
others don't):

1. **Has goal term** is computed differently. Agile uses the port's
   `weight_display_keys` filter; waterfall and demo accept any weight.
   So VRPTW's `waiting_time` weight satisfies the waterfall gate but
   not the agile gate, for reasons unrelated to mode semantics.
2. **`optimization_gate_engaged`** is required in waterfall, ignored
   in agile/demo.
3. **`has_uploaded_data`** is required in agile/demo, ignored in
   waterfall.

The desired end state is: a single function whose only mode-driven
branch is the open-questions check. Everything else is uniform.

A first attempt to do this in one session (2026-05-14) was reverted
because the strict-symmetry change cascaded into 10 integration-test
failures rooted in a fourth, hidden asymmetry: **`gate_engaged` only
flips today via paths that don't fire in many real or test scenarios**
(non-visible synthetic messages, panel PATCH without chat, run-ack
sequences). Strict symmetry without first broadening engagement
triggers blocks too many legitimate flows.

## Intended end state

One function, replacing all three intrinsic helpers:

```python
def intrinsic_optimization_ready(
    workflow_mode, panel_config, problem_brief, gate_engaged, problem_id
) -> bool:
    # Uniform across all modes:
    # 1. workflow_mode is one of {agile, waterfall, demo}
    # 2. panel has a non-empty algorithm
    # 3. has a qualifying goal term (port-driven: weight_display_keys
    #    + gate_conditional_companions with OR semantics)
    # 4. gate_engaged is True
    # Waterfall-only:
    # 5. no open-status open questions
```

And one wrapper:

```python
def can_run_optimization(...):
    # Uniform across all modes:
    # 1. has_uploaded_data
    # 2. not researcher-blocked
    # 3. researcher-allowed OR intrinsic_optimization_ready(...)
```

This subsumes critique item #6 (replace the singular
`worker_preference_key` / companion-field pair on the port with a
plural `gate_conditional_companions()` map) since the unified function
needs a single per-port accessor for the companion concept.

## Scope of change

### A. Backend gate (single source of truth)

- `backend/app/optimization_gate.py`:
  - Delete `intrinsic_optimization_ready_agile`,
    `_waterfall`, `_demo`. Replace `intrinsic_optimization_ready` (the
    dispatcher) with the new single-function body.
  - Add helper `_qualifying_goal_term_present(inner, display_keys,
    companions) -> bool` that implements the OR semantics for keys in
    the companion map.
  - Refactor `gate_status` to use the same `_qualifying_goal_term_present`
    so the snapshot and the boolean gate stop disagreeing about what
    counts as a goal term. Add `"gate_engaged"` to the `missing` list
    uniformly across modes (not waterfall-only).
  - Refactor `can_run_optimization` to require `has_uploaded_data`
    universally.

### B. Port surface (#6 — full generalization)

The protocol surface today already exposes most of the companion
concept as per-key maps (`locked_companion_fields`,
`goal_term_property_field_mirrors`, `goal_term_properties_schema`,
`prose_id_prefixes_for_goal_term`, `normalize_goal_term_property`).
The lone holdout that still names VRPTW's vocabulary on the shared
protocol is `worker_preference_key() -> str | None`. That gets
replaced; nothing else on the port changes shape.

- `backend/app/problems/port.py`:
  - Replace `worker_preference_key() -> str | None` with
    `gate_conditional_companions() -> dict[str, str]` (default `{}`).
    Maps goal-term key → companion panel-field name.
  - Add `companion_present(goal_term_key: str, value: Any) -> bool`
    with a default implementation: lists are present iff non-empty,
    everything else is `bool(value)`. Ports override per-key when
    the "is defined" predicate is more specific (VRPTW's
    `max_shift_hours` requires `> 0`).

- `vrptw_problem/study_port.py`: implement the new methods so the
  port declares **both** goal terms that have gate-relevant
  companions:
  ```python
  def gate_conditional_companions(self):
      return {
          "worker_preference": "driver_preferences",
          "shift_limit": "max_shift_hours",
      }

  def companion_present(self, goal_term_key, value):
      if goal_term_key == "shift_limit":
          return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
      # Default: list-non-empty for worker_preference, truthy otherwise.
      if isinstance(value, list):
          return len(value) > 0
      return bool(value)
  ```
  This is the *behaviour expansion*: `shift_limit` now participates in
  the gate-conditional concept the same way `worker_preference`
  always has (see §B-rules below for the semantic this implements).

- `knapsack_problem/study_port.py`, `template_problem/study_port.py`:
  remove the old override; defaults apply.

- Keep `TestProblemMeta.worker_preference_key` populated for frontend
  back-compat (see §D).

### B-rules. Gate semantic for companion-required goal terms

A goal-term key contributes to "qualifying goal term present" iff:

1. The key is in the port's `weight_display_keys`, AND
2. One of:
   - The key is **not** in `gate_conditional_companions` and its
     weight is set in the panel, OR
   - The key **is** in `gate_conditional_companions` and the panel's
     companion field is "present" per
     `port.companion_present(key, value)`. (Weight is optional in
     this case — the companion content is what carries.)

Gate opens iff at least one key contributes.

User-facing consequence (matches the new requirement): a companion-
required goal term with weight-only and an empty companion never
opens the gate by itself. A participant who sets only the
`worker_preference` weight without adding any driver preferences will
still see the run button disabled. If they add another non-companion
goal term (e.g. `travel_time`), the gate opens via that — the
companion-required term rides along without contributing to gate-
opening.

Walk-through:

| Panel state | Contributing keys | Gate |
|---|---|---|
| `travel_time` weight, no companions | `travel_time` | Open |
| `worker_preference` weight, no driver_preferences | (none) | **Closed** |
| `driver_preferences` set, no weights | `worker_preference` | Open |
| `worker_preference` weight + `travel_time` weight, no driver_preferences | `travel_time` | Open |
| `shift_limit` weight, `max_shift_hours = 0` | (none, since `0` fails the predicate) | **Closed** |
| `shift_limit` weight, `max_shift_hours = 8` | `shift_limit` | Open |

### C. Engagement-trigger broadening (the lesson from the first attempt)

Strict symmetry only works if `gate_engaged` reliably flips on every
form of participant engagement. Today it fires on:

- `derivation.append_message(role="user", visible=True)`
- `helpers.maybe_mark_optimization_gate_engaged_from_brief` when the
  brief has any `open_questions` entry
- `db_maintenance.py:284` backfill

Add these triggers so panel-only / non-visible-message flows also
engage:

- **Panel PATCH** that sets a non-empty `goal_terms`/`weights` or a
  non-empty `algorithm`. Hook into
  `sync_optimization_allowed_after_participant_mutation` (already
  called from the panel PATCH endpoint) by widening
  `maybe_mark_optimization_gate_engaged_from_brief` to also accept the
  panel and inspect it. Rename to
  `maybe_mark_optimization_gate_engaged` since "from brief" no longer
  fits.
- **Definition (brief) PATCH** with any item edit: same helper, since
  the brief is already passed.
- **Probe-time speculation**:
  `services/visible_reply_commitments.speculative_intrinsic_gate_ready`
  predicts post-commit gate state. Change its `optimization_gate_engaged`
  default to `True` (speculation assumes engagement) and have the
  router callers pass through whatever flag they already have. The
  function's docstring already says "predict whether the gate would
  pass once the patch lands" — and at "lands" time, gate_engaged is
  True for visible user turns.
- **Run-ack handling**: run-acks are synthetic, non-visible messages
  that today don't flip `gate_engaged`. A run-ack only happens AFTER
  at least one optimization run, which itself only happens AFTER the
  gate has been opened (i.e. `gate_engaged` must have been True at
  run launch). So in production, a run-ack always follows engagement.
  In tests, several integration tests construct sessions that go
  straight from PATCH-panel to run-ack — those tests rely on the
  panel-PATCH engagement trigger above. With that trigger in place,
  no extra run-ack handling is needed.

### D. Frontend mirror

- `frontend/src/client/lib/optimizationGate.ts`: same collapse — one
  function with one waterfall-only branch.
- `frontend/src/shared/api.ts`: `TestProblemMeta.worker_preference_key`
  stays a `string | null` field for back-compat. The frontend gate's
  companion check (currently dead code for the same reason as backend)
  becomes the OR semantics, consistent with the backend.
- `frontend/src/client/hooks/useClientController.ts` and
  `frontend/src/client/problemConfig/ProblemConfigBlocks.tsx`: keep
  the singular field consumption. If/when a second sub-property goal
  term appears, also generalize the frontend.

### E. Router prompt-injection text

- `backend/app/routers/sessions/router.py:228` — `_run_gate_blocked_message`:
  - Agile/demo: when the missing piece is `gate_engaged`, surface a
    "send your first message in chat" hint (currently this message
    never fires for agile/demo).
  - Waterfall: when `has_uploaded_data` is False, surface the upload
    hint (currently this message never fires for waterfall).
- Cross-check the messages still match the unified `missing` list
  semantics produced by `gate_status`.

### F. Tests

- `backend/tests/test_optimization_gate.py`: rewrite the test calls
  against the unified `intrinsic_optimization_ready(mode, ...)` API.
  Add explicit coverage:
  - All modes block without `gate_engaged`.
  - All modes block without `has_uploaded_data` (via
    `can_run_optimization`).
  - Only waterfall blocks on open questions.
  - `_qualifying_goal_term_present` with multi-entry companion map
    (the N>1 regression anchor for #6).
- `backend/tests/test_gate_aware_chat_turn.py`: 5 tests in this file
  go session-create → PATCH-panel → message. Expect them to continue
  passing once the panel-PATCH engagement trigger is in place; verify
  no extra fixture changes are needed.
- `backend/tests/test_sessions.py`: 5 tests follow the same pattern
  (`test_run_ack_agile_allows_one_assumption_patch_item`,
  `test_inline_sync_failure_marks_processing_failed`,
  `test_chat_brief_patch_replaces_conflicting_population_size_fact`,
  `test_cleanup_request_replaces_editable_brief_items`,
  `test_visible_assistant_reply_strips_hidden_patch_json`). Same
  expectation. If any still fails after the engagement-trigger
  broadening, update the fixture explicitly.
- `backend/tests/test_visible_reply_commitments.py`: update the
  `speculative_intrinsic_gate_ready` call to pass
  `optimization_gate_engaged=True` (or rely on the new default).

## Behaviour-change inventory (user-visible)

| Change | Affects | User-visible effect |
|---|---|---|
| Waterfall requires uploaded data | All waterfall sessions | Run button disabled until simulated upload completes. Same gating as agile/demo today. |
| All modes require gate_engaged | Brand-new sessions only | Run button disabled until participant sends first message OR edits panel non-trivially. Panel-PATCH engagement trigger (§C) means this is rarely observed in practice. |
| `worker_preference` weight alone no longer opens the gate | All modes + VRPTW | A participant who sets only the worker_preference weight without adding any driver preferences will see the run button stay disabled. Today the gate opens (the companion check is dead code per the audit). New semantic matches the docstring's intent and the user's "require a defined property" rule. |
| `driver_preferences` alone (no weight) now opens the gate | All modes + VRPTW | Seeded preferences from a parser enable the gate even without an explicit worker_preference weight. |
| `shift_limit` weight alone no longer opens the gate | All modes + VRPTW | Same rule applied to the second companion-required goal term: a participant who sets only the shift_limit weight without specifying `max_shift_hours` will see the run button stay disabled. Today this opens the gate (shift_limit was never gate-conditional). |
| `max_shift_hours = 0` no longer counts as defined | All modes + VRPTW | `companion_present` for `shift_limit` requires strictly positive. Participants who explicitly enter 0 (currently rare) see the gate stay closed and a "set a positive shift limit" hint. |
| Waterfall gate filters by weight_display_keys | Waterfall + VRPTW | `waiting_time` weight alone no longer satisfies the waterfall gate (matches agile). |

## Rollout sequence

The unified function and engagement-broadening must land in the same
PR; landing one without the other reproduces the 10-test cascade from
the first attempt.

Recommended commit order within the PR:

1. Broaden `maybe_mark_optimization_gate_engaged` to accept the panel
   and check it; update the one caller. (No behaviour change yet
   since today's gates don't consult `gate_engaged` in agile/demo.)
2. Update `speculative_intrinsic_gate_ready` default. (No behaviour
   change yet for the same reason.)
3. Backend port: rename method + dict semantics. Backend gate:
   collapse to one function + add the symmetric requirements.
4. Backend test rewrite.
5. Frontend mirror.
6. Router prompt-injection text updates.

Each commit should keep the test suite green so bisecting later stays
useful.

## Critical files

- `backend/app/optimization_gate.py` — primary rewrite.
- `backend/app/problems/port.py` — protocol surface.
- `backend/app/routers/sessions/helpers.py` —
  `maybe_mark_optimization_gate_engaged*` widening.
- `backend/app/services/visible_reply_commitments.py` —
  `speculative_intrinsic_gate_ready` default.
- `backend/app/routers/sessions/router.py:228` —
  `_run_gate_blocked_message` text.
- `vrptw_problem/study_port.py`, `knapsack_problem/study_port.py`,
  `template_problem/study_port.py` — port implementations.
- `frontend/src/client/lib/optimizationGate.ts` and the three
  consumers in `useClientController.ts`,
  `problemConfig/ProblemConfigBlocks.tsx`, `vrptw_problem/frontend/VrptwExtras.tsx`.
- Tests: `test_optimization_gate.py`, `test_gate_aware_chat_turn.py`,
  `test_sessions.py`, `test_visible_reply_commitments.py`.

## Out of scope (separate plans)

- Frontend generalization to support multi-entry
  `gate_conditional_companions` (critique #6, frontend half). Defer
  until a second sub-property goal term appears.
- Collapsing the chat / brief-update / derivation LLM pipeline
  (critique #1). Independent.
- OQ resolution via deterministic predicates (critique #4). Touches
  the same waterfall path but is a separate concern.

## Open questions

1. Do you want the engagement trigger to fire on **any** panel PATCH
   or only ones that meaningfully change state (goal_terms/algorithm
   present after the save)? The plan above assumes "meaningful state
   present" — empty panel saves don't engage.
2. Should `_run_gate_blocked_message` for agile/demo's new
   `gate_engaged` missing state suggest "send a chat message" or
   "interact with the panel"? Either is honest; the framing affects
   which path participants discover first.
3. If a waterfall session has gate_engaged True but never uploaded
   (e.g. researcher pre-set everything), should the wrapper let it
   run? The plan says no — uniform `has_uploaded_data` requirement.
   Confirm.

## Verification

After implementation:
1. Full backend suite: 123+ tests pass, including the new symmetry
   tests added in §F.
2. Frontend type-check and existing component tests pass.
3. Manual smoke: agile session, no upload → run blocked, message →
   no help, upload → run available. Waterfall session, no upload →
   run blocked. Agile session, panel-only flow (no chat) → engagement
   trigger fires, run enabled after upload.
4. Grep: `worker_preference_key(` is gone outside the
   `vrptw_problem/study_meta.py` constant and the
   `TestProblemMeta` field. `worker_preference_companion_field` is
   gone entirely.
5. Grep: `intrinsic_optimization_ready_agile/_waterfall/_demo` is
   gone entirely.
