# User-Flow State & Conflict Spec

How participant-facing state changes, who owns each piece, and how the system
stays correct when two things try to write the same thing at once.

Companions: `interface_flow.md` (the flow), `FLOW_CONTROL_MAP.md` (node → state
→ who decides), `CHAT_PIPELINE.md` (pipeline stages).

---

## Golden rules

1. **User input always wins.** A value the participant typed in chat or set in
   a panel beats any agent proposal or default. Every rule below serves this.
2. **One owner per item, per direction.** Each piece of state has a single
   authoritative writer for a given turn. On a chat turn the brief is the
   source of truth; on a panel save the panel is.
3. **Mirrors overwrite, never fill-if-empty.** When the authoritative side has
   a value, the mirror replaces the other side — it does not only fill a blank.
   (Fill-if-empty lets a stale default block the real value — that was the
   `algorithm` and `epochs/pop_size` bug.)
4. **One decision-maker per state.** Don't let two model calls vote on the same
   thing. Prefer one structured decision, applied by deterministic code.
5. **Model proposes, code disposes.** The model suggests; deterministic gates
   enforce ownership and invariants. A prompt rule is guidance, never the
   enforcement.

## Precedence ladder (who wins a conflict)

Highest to lowest:

1. **Participant** — panel edit or chat answer. Always wins.
2. **Server gate / monitor** — deterministic invariants (run gate, foundational
   question monitors, search-strategy gate). Can veto the agent.
3. **Agent (model)** — proposals in the brief patch and config derivation.
4. **Default / seed** — fallback values (e.g. `GA`, `epochs 100`). Lowest; any
   real signal above overrides it.

---

## Concept lifecycle — state vs. pending decision

The key insight (and a correction to an earlier "one open question per concept"
rule that was too strict): a concept has two independent things attached to it.

- **State** — what the concept *currently is*. At most one of:
  *assumption* (agent decided, provisional) → *gathered* (user confirmed) →
  *locked* (user froze). These never coexist for the same concept.
- **Pending decision** — an **open question** about the concept: *should we
  add it?*, *raise its weight?*, *change its type?*. A question is a request
  awaiting an answer, **not** the concept's state — so a question can sit
  alongside an existing assumption or gathered fact. (Example: a gathered
  "lateness penalty, weight 5" with an open "raise it to 30?" question is
  perfectly valid.)

So the rule is: **at most one state per concept, but a question may coexist
with that state.** The only true duplicate is two questions both proposing to
*add the same not-yet-existing concept*.

```
   add-proposal        agent decides          user confirms
 ── QUESTION? ────────► ASSUMPTION ──────────► GATHERED ──► LOCKED
   (no state yet)      (agent's, agile)        (user's)    (frozen)
        │                   │  ▲                   │  ▲         │
        │ once a STATE      │  └─ demote (agile) ──┘  │   only user, or
        │ exists, further   │     agent changes it    │  ask→approve→unlock
        └─ questions are ───┘                         │
           change-proposals that COEXIST with the state
           (resolved when the user acts on the concept)
```

- **Question** — a pending decision; coexists with whatever state exists.
- **Assumption** — agent decided provisionally (agile only).
- **Gathered** — user stated or confirmed it; it's theirs.
- **Locked** — gathered *and* frozen by the user; strongest "hands off."

Rules:

1. **One state per concept** — never two states for the same `goal_key`. A
   question is not a state, so it doesn't count here.
2. **Dedupe only duplicate add-proposals** — two open questions that both
   propose to add the *same absent concept* collapse to one. A question about
   a concept that already exists is a change-proposal and is kept.
3. **A change-question resolves when the user acts** — answering it, or
   committing/retuning the concept, closes it (`_resolve_anchored_provisional_rows`).
4. **User input wins** — a user value is never silently overwritten. In agile
   the agent may retune, but that **demotes to an assumption** and is surfaced;
   the user can revert, re-confirm, or lock.
5. **Locked = no agent writes** (enforced, all modes) — an agent change to a
   locked term is reverted and an OQ is raised for the participant to approve
   unlock + apply (`gate_locked_goal_term_changes`). The lock is the exception
   to agile's demote-to-assumption: locked → ask, never demote.
6. **Mode picks the entry point** — waterfall enters at *question*, agile at
   *assumption*. Same lifecycle; waterfall has no assumption state (coerced to
   questions).
7. **Provenance follows origin** — user-driven → gathered/user; agent-driven →
   assumption/agent.

Boundary: free-form facts without a `goal_key` (data, scale, caveats) are just
facts — none of this lifecycle applies to them.

### Transition status (enforced vs. gap)

| Transition / rule | Enforced today | Gap to close |
|---|---|---|
| One *state* per concept (assumption xor gathered) | yes (`_reconcile_problem_brief_items`, gathered beats assumption; `config-` synth rows exempt) | — |
| Change-question coexists with existing state | yes (dedup only hits add-proposals) | — |
| Dedupe duplicate add-proposals (absent concept) | yes | — |
| Question → gathered / → assumption | yes (answer classifier) | — |
| Change-question closes when user acts | yes (`_resolve_anchored_provisional_rows`) | — |
| Assumption → gathered (promote) | partly (`assumption_actions`) | promotion from a vague "yes" |
| **Locked term = no agent write (all modes → revert + OQ)** | **yes** (`gate_locked_goal_term_changes`) | frontend lock button on gathered rows |
| **Gathered → assumption (demote on agile retune)** | **no** | row stays "gathered", looks confirmed |
| **Assumption dropped once user-confirmed** | partly (promote) | auto-drop on a *user-sourced* gathered row (not the synthesized one) |
| Override of a same-session user statement (agile) | surfaced (`delta_without_claim`) | optional: ask before overriding |

Open decision: **who can unlock?** Panel only, or can a chat "yes" to the
agent's "unlock and change it?" authorize it (like the algorithm chat answer)?

---

## What can change each item

| Item | Can be changed by | Authoritative owner | Conflict defense |
|---|---|---|---|
| **Goal summary** | agent (on first objective), participant (Definition edit) | brief `goal_summary` | backstop fills it from goal terms only when empty; never holds numbers |
| **Goal-term weight / type / rank** | participant (Config panel), agent (chat patch, config derive) | brief on chat turns; panel on config-save | scalar mirror forces panel to match brief on chat turns; config-save strips goal terms from the model patch so the panel wins; anchoring drops unproven new terms |
| **Search algorithm** | participant (chat answer or panel), agent (proposal; agile commits a default) | brief carrier `goal_terms.search_strategy.properties.algorithm` | waterfall gate blocks an algorithm the user never chose; a user's chat answer is detected by a classifier and committed by the server; carrier→panel mirror overwrites |
| **Epochs / pop size** | participant (panel), agent (carrier/derive), seed default | carrier when set, else default | carrier→panel mirror overwrites with the carrier's real value |
| **Foundational questions** (upload, primary goal, search strategy) | server monitors only | `_enforce_session_monitors` | merge strips any foundational question the model emits; monitors are the sole writer |
| **Goal-term questions** (proposal/tuning, tagged `goal_key`) | agent (raises), participant (chat answer or panel), server resolver (closes) | server resolver `_resolve_anchored_provisional_rows` | one shared predicate decides closure for both chat and panel paths; closes when the key is committed or retuned; the model's drop is ignored on answer turns so a counter-question isn't lost |
| **Free-form questions** (`other`, no `goal_key`) | agent (`oq_actions`), participant (answer) | model | waterfall caps at 3 active; verifier requires a question row when the reply asks one |
| **Assumptions** (agile/demo) | agent (adds), participant (promote/edit/remove), workflow coercion | model proposes, participant promotes | promotion needs an explicit lock-in; waterfall converts assumptions to questions, demo drops them |
| **Gathered facts & synthesized rows** | agent, participant (confirm/edit/**lock**), synthesizer (`config-weight-*`, rule rows) | synthesizer owns the `config-*` rows; user owns the lock | model is forbidden from emitting those ids; stale synthesized rows pruned by id prefix; **a locked term's change is reverted + raises an OQ** (`gate_locked_goal_term_changes`) |
| **Goal-term lock** | participant (Config lock button, or gathered-row lock — synced) | participant only | the lock is the same state in both surfaces (`goal_terms[key].locked` ↔ panel `locked_goal_terms`); the agent never sets it |
| **Run summary / run records** | server only | server (`consolidate_run_summary`, run store) | anything the model writes here is overwritten |
| **Uploaded-file fact** | participant upload event | server (one canonical row) | model must not duplicate the upload row; the upload question auto-resolves |

---

## Defense mechanisms (and the conflict each prevents)

- **Run gate** (`optimization_gate.can_run_optimization`) — stops the agent
  claiming a run when prerequisites aren't met. The button state is the single
  truth, injected into every prompt.
- **Search-strategy gate** (`gate_unauthorized_search_strategy_commit`) — drops
  an algorithm the user never chose; commits the user's chat answer
  deterministically (read from the user's own message by a classifier).
- **Locked-term gate** (`gate_locked_goal_term_changes`) — all modes: an agent
  change to a *locked* goal term is reverted to the locked value and surfaced as
  an `oq-locked-change-<key>` open question for the participant to approve
  (unlock + apply). Reads the lock from either surface (brief
  `goal_terms[key].locked` or panel `locked_goal_terms`).
- **One state per concept** (`_reconcile_problem_brief_items`) — a concept can't
  be both gathered and assumption at once; gathered (user-confirmed) wins.
  Server-synthesized `config-` rows are exempt (companion rules legitimately
  have many).
- **Foundational monitors + merge strip** — the server is the only writer of
  the upload / primary-goal / search-strategy questions.
- **Anchored-question resolver + shared predicate**
  (`_resolve_anchored_provisional_rows`, `is_goal_key_oq_resolved_by_keys`) —
  closes a goal-term question when its key is committed or retuned, the same way
  on the chat and panel paths.
- **Dedupe duplicate add-proposals** (`_dedupe_add_questions_for_absent_concepts`) —
  collapses two OPEN questions that both propose to add the *same not-yet-existing*
  concept (`goal_key` absent from `goal_terms`), keyed on the concept not the text.
  A change/tuning question about a concept that already exists is a pending
  decision and is kept — it coexists with the concept's state.
- **Carrier→panel overwrite mirror** (`sync_panel_from_problem_brief`) — the
  brief carrier wins over panel defaults for algorithm / epochs / pop size.
- **Scalar mirror** (`_mirror_canonical_scalars_from_brief`) — brief
  weight/type/rank wins over a drifting model-derived panel on chat turns.
- **Answered-question classifier** (`classify_answered_open_questions`) — turns
  a panel answer into a resolution or a simpler re-ask before the chat turn runs.
- **Anchoring filter** (`filter_unanchored_new_goal_terms`) — drops a new goal
  term that has no supporting evidence.
- **Verifier** (S2/S5, `pipeline_verification`) — catches reply↔brief and
  brief↔panel disagreement; retries with feedback, then pauses with Retry /
  Revert / Keep-chatting. Never silently commits, never auto-reverts.

---

## Adding a new shared field — checklist

1. Name **one authoritative owner per direction** (chat turn vs. panel save).
2. If it mirrors between brief and panel, make the mirror **overwrite**, not
   fill-if-empty.
3. If both the model and code can write it, give **code the final say** (a gate
   or mirror); the model only proposes.
4. Add it to the table above and to `interface_flow.md` §K (the "looks like
   model work but isn't" list).
5. If a disagreement would be a bug, add a **verifier check** for it.

---

## Standing audit routines

- **Prompt budget** — `tests/test_main_turn_prompt_assembly.py` pins which
  blocks load per turn type and a word ceiling. Every prompt change updates it;
  growth must be reviewed.
- **Dead code / stale refs** — grep public helpers for callers; grep doc names
  referenced from code against the real tree.
- **No keyword-matching of free text** — grep the chat path for substring/regex
  matching of participant text; the only known offenders are the sandbox and
  visualization prompt-load gates (`study_chat.py`). Use a structured model
  classifier instead.
- **Action coverage** — every participant action has a typed `context_kind`
  and a test; nothing falls through to improvisation.

---

## Watch list (not broken, but the next likely conflicts)

- **Goal-term scalars across directions** — brief-authoritative on chat,
  panel-authoritative on config-save. The scalar mirror handles the known case;
  watch the direction race if a new write path appears.
- **Assumption promotion from a vague "yes/sure"** — promotion is decided by
  the model from soft confirmation. Same split-decision shape that bit the
  questions; harden with a quoted lock-in if it misfires (see
  `FLOW_CONTROL_MAP.md`).

## Done this round

- **Gathered-row lock button (frontend).** Gathered rows that carry a
  `goal_key` now show a lock toggle (`DefinitionPanel.tsx`) — the assumption
  **↑ promote** control stays on assumption rows; lock is its gathered-row
  parallel. The toggle reads/writes `brief.goal_terms[key].locked`, the *same*
  lock the Problem Config goal-term button sets; `sync._mirror_locked_from_brief`
  unions the brief flag into `panel.locked_goal_terms` (and drops it on explicit
  unlock), so the two controls reflect one shared state — one lock per concept.
  Companion rows (`config-driver-pref-*`, goal_key `worker_preference`) lock at
  the term level; per-companion-row locking is intentionally not offered.

## Pending implementation (spec ready)

- **Gathered → assumption demote on agile retune.** When the agent changes an
  *unlocked* gathered term in agile, swap its kind to `assumption` (provenance
  follows origin) instead of leaving it looking user-confirmed. Locked terms
  are the exception — already handled by the lock gate (revert + OQ).

## Decided, not doing now

- **A dedicated node/intent classifier** — redundant with the flags that
  already detect most turn types; would be a layer on top of flags.
- **A structural gate for assumption promotion** — reversible and low-impact;
  revisit only if testing shows it misfiring.
