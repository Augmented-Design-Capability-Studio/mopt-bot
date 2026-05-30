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
| **Gathered facts & synthesized rows** | agent, participant (confirm/edit), synthesizer (`config-weight-*`, rule rows) | synthesizer owns the `config-*` rows | model is forbidden from emitting those ids; stale synthesized rows are pruned by id prefix |
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
- **Foundational monitors + merge strip** — the server is the only writer of
  the upload / primary-goal / search-strategy questions.
- **Anchored-question resolver + shared predicate**
  (`_resolve_anchored_provisional_rows`, `is_goal_key_oq_resolved_by_keys`) —
  closes a goal-term question when its key is committed or retuned, the same way
  on the chat and panel paths.
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

## Decided, not doing now

- **A dedicated node/intent classifier** — redundant with the flags that
  already detect most turn types; would be a layer on top of flags.
- **A structural gate for assumption promotion** — reversible and low-impact;
  revisit only if testing shows it misfiring.
