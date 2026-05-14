# Interface Flow — Architectural Critique

Companion to `interface_flow.md`. Concerns are ordered by how much
structural change they imply.

## 1. Three-stage LLM pipeline accumulates back-stops

The pipeline is: chat reply → brief-update (with `visible_reply_intent`)
→ derivation (brief → config) → optimization gate evaluation. State can
desync at every boundary, so each new failure mode has earned its own
deterministic back-stop:

- `visible_reply_commitments.inject_algorithm_assumption` — chat said
  "I set GA" but didn't emit the structural carrier; we synthesize one.
- `workflow_compliance.assess_workflow_compliance` — chat asked a
  question without filing it as an OQ; we record a hidden compliance
  message.
- `goal_term_anchoring`, run-ack sanitization in `derivation.py`, the
  enforce-monitor pass — each handles a specific drift mode.

This is fine *as policing*, but every new symptom is met with another
patch in another file. One structural alternative worth considering:

- **Constrain at emission, not at validation.** The chat LLM already
  takes the gate state as context. Make it emit a structured payload
  (`structured_outputs` / JSON schema) that *contains* both the visible
  reply and the structural carriers, validated by the schema itself.
  Drop the "visible says X, carrier says Y" reconciliation entirely.

## 2. Validator-retry on run-button mismatch is a latency tax

Today: chat invites a run → validator notices the gate isn't actually
ready → re-prompt with status injected. Each retry is another LLM
round-trip. You already compute `speculative_intrinsic_gate_ready`
*before* the chat call — meaning we know, deterministically, whether
"run-invitation phrasing" is even allowed this turn. Lean on that:

- Pass `run_invitation_allowed: bool` into the chat system prompt as a
  hard slot. The model never has to guess.
- Cap retries at 1 and have a deterministic fallback: strip the run
  invitation phrase and append the missing piece. That guarantees a
  bounded turn cost.

## 3. OQ lifecycle has unclear ownership

"If no goal term is defined, keep the OQ" is a *defensive* rule layered
on top of the LLM's own resolve-OQ decisions. Right now the rules live
in at least three places: the chat prompt, the brief-update LLM
(`_patch_likely_resolves_open_questions`), and the enforcement pass
(`apply_open_question_cleanup_pass`). Each can disagree.

Make it explicit:

- An OQ is **resolved** only by a deterministic predicate over the
  brief/config state (goal-term-exists, file-uploaded, algorithm-set,
  etc.) — not by an LLM saying so.
- The LLM may *propose* a resolution; the predicate decides.
- Per-OQ resolution predicate is declared at OQ creation time, not
  inferred after the fact.

This also makes waterfall vs agile cleaner: waterfall gate becomes
"every OQ predicate is satisfied" — no more "the LLM forgot to clear
the OQ" failure mode.

## 4. Race conditions on rapid edits

Editing a definition row triggers a derivation call. If a user
edits-saves-edits-saves within a few seconds (common when promoting
several assumptions), derivation calls overlap. The codebase has
`_run_background_derivation` + `launch_background_derivation`, but I
didn't see explicit cancel-in-flight when a newer edit lands. Symptom:
the *older* derivation's result wins because it returns later. Plan
for:

- Each derivation is tied to a `brief_revision`; on completion, if the
  current revision is higher, drop the result.
- Or, debounce edits at the router level (e.g. 300ms) and coalesce.

This also covers the "undo last edit" case from spec §8.

## 5. Sub-property bridge is N×M (will get worse)

Today, VRPTW's `driver_preferences` is special-cased via the
`worker_preference_companion_field` parameter through
`intrinsic_optimization_ready_agile`, `visible_reply_commitments`, etc.
That's one bridge for one goal term. The moment a second sub-property
goal term appears (e.g. time-window-tightness with per-customer
tolerances, or vehicle-capacity with per-vehicle caps), every site that
threaded the worker-preference companion needs another parameter.

Generalize the port:

```py
class GoalTermSpec:
    key: str
    display_name: str
    weight_type_options: list[str]
    sub_properties_schema: dict | None     # JSON schema or pydantic
    companion_field: str | None            # top-level brief field name
    gate_requires_companion: bool
```

`StudyProblemPort.goal_term_specs() -> list[GoalTermSpec]`. Gate, def
panel, config panel, derivation, and the visible-reply checker all
iterate the list generically. New problems add specs; the main backend
doesn't change.

## 6. Cold→warm transition is decided per-turn but not committed

Spec §1 implies classification each turn. Two failure modes:

- **Mid-turn warm-up.** User says "hi. actually, can you help me
  minimize total route time?" — one turn, two states. Decide *once*
  per turn before any LLM call and stick to that decision for the
  full turn (system prompt + brief-update + derivation).
- **Hysteresis.** A warm session that hits a cold-sounding turn ("ok
  cool, thanks") shouldn't drop back to cold. Add a one-way latch:
  once warm, stay warm for the session unless the researcher resets.

## 7. Post-run growth is unbounded

"After each run, add one or two assumptions or OQs." Over a 30-minute
session with 6–10 runs, that's a 12–20 row drift. Today, pruning
happens implicitly through the validator and `apply_open_question_cleanup_pass`,
but the *additive* side is unbounded. Consider:

- Cap "unresolved OQs" and "active assumptions" each at N (5? 7?). If
  the LLM wants to add one when the cap is hit, it must merge or
  retire one in the same patch.
- Make this a structural constraint of the brief-update schema, not a
  prompt instruction.

## 8. Researcher steer messages and validator intent detection

The validator keys off `visible_reply_intent.{asks_user_question,
claims_brief_change}`. A researcher steer that says "please confirm
the user's max shift constraint" might cause the next agent reply to
ask a question that was *researcher-initiated*. If the validator sees
"asked a question" without an OQ row, it logs a compliance violation
that's not really a bug. Tag steer turns so the validator knows the
ask came from outside the participant flow.

## 9. RAG retrieval is upstream of temperature classification

`search_reference_excerpts` is called every turn before the chat LLM,
keyed on user text + problem id + temperature. Two concrete concerns:

- **Cold-turn cost.** Even a "hi" gets embedded + searched. The
  retrieval is cheap but non-zero, and on cold turns the excerpts
  rarely contribute (the system prompt skips sandbox rules but still
  spends prompt budget on doc context). Gate retrieval on
  `cold == False or sandbox_rules_relevant(...)` so cold small-talk
  turns skip the lookup.
- **Excerpt-vs-persona collision.** The persona forbids naming
  documents or reciting verbatim; the retrieved excerpts are
  prose-shaped and tempt the LLM to quote. Failure mode is subtle:
  the agent paraphrases an excerpt closely enough that a participant
  who later sees `docs/user/` can recognize it. Two cheap mitigations:
  (a) pass excerpts as *bulleted claims* rather than prose, generated
  at indexing time, so there's nothing to recite; (b) include a
  "compress to one sentence in your own words" instruction adjacent to
  the excerpt block.
- **Stale index after `docs/user/` edits.** Embedding cache is
  content-hashed (`_content_hash`), which is correct, but a researcher
  editing knowledge docs mid-study should know whether the re-embed
  cost is paid on the *next participant turn* or at startup. Document
  this expectation, or warm the cache on doc-file change.

## 10. "Acknowledge what specifically changed" is a recurring trap

Spec §5 and §6 both require the chat to name the specific change after
an edit. That requires the chat LLM to see a *diff* of the brief/config
across the edit, not just the latest state. If it currently only sees
the new state it will hallucinate plausible-sounding "I updated X"
phrasings. Worth a quick audit: confirm the chat context for the
post-edit acknowledgement turn includes the diff payload, not just the
current snapshot.

---

If you want to prioritize: #5 (generic goal-term spec) is the change
that pays back the most going forward; everything else can be
incremental. #1 (collapse stages / constrain at emission) is the
high-ceiling change but the most invasive.
