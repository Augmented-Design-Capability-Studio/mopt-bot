# Reusable "Companion Goal-Term" pattern

## Context

Several recent bugs in P_0603 were all the same shape: a goal term that owns a
structured child carrier (VRPTW `worker_preference` → `driver_preferences`,
`shift_limit` → `max_shift_hours`). The agent kept mis-handling these — committing
a hollow parent, parking the rule in `ambiguity_note`, writing a prose row instead
of the array, or the term silently vanishing. Fixes so far were piecemeal and one
(`reconcile_companion_oqs` "always keep the term") is too blunt.

The user wants this turned into **one reusable, documented pattern** that any
problem's companion-bearing goal terms inherit, guaranteeing four behaviors:

- **B1 — vague parent** ("I want driver preferences", no specifics) → the agent
  asks for specifics; **no empty term materializes**.
- **B2 — concrete child** ("Alice avoids Zone D") → the **parent term + child**
  show up in config (child populated).
- **B3 — keep adding children** later via **chat, def panel, and config**.
- **B4 — the pipeline verifies** this and makes the agent **fix errors via retry**.

### Decisions locked with the user
- Empty parent term shows **only when a child was actually given** (B1 vs B2), not
  on a vague mention.
- Def-panel: keep the companion row a **flat normal row** + a footnote; users may
  **type rules after "Rules:"** and they get structured **by the LLM (JSON-schema
  structured output), never regex/keyword parsing** — i.e. def-typing is "chat-style
  editing inside the def row," reusing the existing brief-edit pipeline.

## The pattern (what gets documented)

A port opts in by declaring `gate_conditional_companions() -> {parent_key: field}`
(already exists), plus the existing hooks `companion_present`,
`companion_open_question_text`, `goal_term_companion_summary`,
`prose_id_prefixes_for_goal_term`. From that one declaration, the generic layer
guarantees B1–B4. No problem-specific logic lives in the generic backend; the
per-problem **shape** (field names / enums / worked example) stays in the port
appendix.

## Changes

### 1. `reconcile_companion_oqs` — keep-vs-drop by claim (B1/B2)
`backend/app/problem_brief.py` + `backend/app/services/chat_pipeline_runner.py`

My last change made it *always* keep a hollow term. Refine to:
- **Companion empty + the turn CLAIMED a companion change** (concrete child given,
  or term pre-exists) → **KEEP** the term + park the OQ (so config/def can complete
  it; never silently lost — the user's earlier "no term showing up" complaint).
- **Companion empty + a pure question / no claim** (vague parent) + term is **new
  this turn** → **DROP** the term; the OQ/agent question carries the ask (B1).

Add an optional `turn_claimed_change: bool = True` param to `reconcile_companion_oqs`
(default True preserves the panel-save caller). The runner's apply-stage call passes
`turn_claimed_change=bool(turn.change_clause)`. This is the only signal needed and is
already available where reconcile is invoked.

### 2. Pipeline verification + retry (B4) — mostly in place, confirm generic
`backend/app/services/pipeline_verification.py`, `chat_pipeline_runner.py`

Already built and port-driven: the `port_companion` over-claim check (new hollow
commit **and** pre-existing prose-row leak) + one+ retry + graceful deferral to the
OQ floor (doesn't pause). Keep. Confirm it also fires on **def-edit turns** that
claim a rule (change_clause set), so def-typing is verified the same as chat.

### 3. Generalize prompt guidance (B1/B2/B3)
`backend/app/prompts/study_chat.py` (neutral) + `vrptw_problem/study_prompts.py` (shape)

Today the whole companion contract is VRPTW-specific. Extract a **neutral
"companion goal-term contract"** describing the behavior generically: vague→ask,
concrete→populate the structured carrier **same turn**, list is **atomic** (resend
full list), **no prose rows** for rules, additions **append**. Keep the per-port
**shape** (the `driver_preferences` fields, enums, worked example) in
`DRIVER_PREFERENCES_BRIEF_CONTRACT`. Future ports supply only their shape.

### 4. Def panel "type rules after Rules:" (B3-def)
`vrptw_problem/frontend/VrptwExtras.tsx` (+ tiny backend nudge only if needed)

- The companion parent row stays a **flat normal row**. Add a **footnote/hint**:
  *"Add a rule by typing after 'Rules:' (e.g. 'Dave avoids shifts over 6.5h') and
  saving — it'll be structured automatically. You can also edit rules in the Config
  panel."*
- Mechanism reuses the existing **brief-edit-ack** pipeline: the edited row text
  reaches the drafting LLM, which structures the rule into the carrier; the
  verify/retry pattern (#2) covers compliance; `_synthesize_canonical_weight_items`
  regenerates the row **afterward** (apply stage) so it reflects the structured
  rule. Confirmed ordering — no clobber. **No regex; LLM structured output only.**
- Verify a def edit that adds a rule sets `change_clause` so #2 applies; nudge the
  prompt if def-edit turns need to know a companion row may carry new NL rules.

### 5. Config panel (B3-config) — done, add parity
Already working: visible block, "+ Add preference rule", and the parent-"X" now
clears child rules + restores them (`GoalTermsSection.tsx` / `ProblemConfigBlocks.tsx`,
`VrptwExtras.tsx`). Extend the same parent-X-clears-child to `shift_limit`.

### 6. Prove reuse on a second term — `shift_limit` / `max_shift_hours`
Apply identically: keep-vs-drop, parent-X clears `max_shift_hours`, def footnote.
This is the "yes, generalize it" the user already approved and the regression guard
that the pattern is truly generic, not worker_preference-special.

### 7. Tests
`backend/tests/test_pipeline_smoke.py` (+ a focused pattern test file)
- B1: vague/no-claim hollow new term → dropped + OQ.
- B2: concrete child → term + child kept; hollow-but-claimed → kept + OQ (not dropped).
- B4: over-claim (new hollow + pre-existing prose leak) fires → retry → graceful proceed.
- Reuse: run the same assertions for `shift_limit` to prove genericity.
- Def path: a brief-edit turn carrying an NL rule structures it (or fires verify).

### 8. Docs / memory
Add the pattern to `template_problem/TEMPLATE_INSTRUCTIONS.md` (companion section)
and a `.claude/memory` note so future ports/sessions reuse it.

## Files (representative)
- `backend/app/problem_brief.py` — `reconcile_companion_oqs` keep-vs-drop by claim.
- `backend/app/services/chat_pipeline_runner.py` — pass `turn_claimed_change`.
- `backend/app/services/pipeline_verification.py` — confirm generic (done).
- `backend/app/prompts/study_chat.py` — neutral companion contract.
- `vrptw_problem/study_prompts.py` — keep shape; trim behavior now covered neutrally.
- `vrptw_problem/frontend/VrptwExtras.tsx` — def footnote; `shift_limit` parent-X parity.
- `vrptw_problem/study_port.py` — (only if a footnote-text/label hook is cleaner than inline).
- Tests + `TEMPLATE_INSTRUCTIONS.md` + memory.

## Verification
- `./venv/Scripts/python.exe -m pytest backend/tests vrptw_problem/tests -q -m "not live_gemini"`
  plus the new pattern tests; `cd frontend && npx tsc --noEmit`.
- Manual on a fresh VRPTW session: (a) "I want driver preferences" → agent asks,
  **no** term; (b) "Alice avoids Zone D" → term + rule appear; (c) add another rule
  via **chat**, via **def** (type after Rules:), via **config** (+ Add rule) — all
  land in the carrier and the companion OQ auto-clears; (d) repeat (a)–(c) for the
  shift-limit term to confirm identical behavior; (e) parent-"X" in config removes
  the whole term and restores it.

## Risk / scope notes
- **Def-typing (#4)** is the newest path. It reuses existing machinery, but the LLM
  must reliably structure the typed rule — same compliance risk as chat, mitigated by
  the verify/retry pattern. If the user prefers, #4 can ship after #1–#3,#5–#6.
- No natural-language regex anywhere; all NL→structured goes through LLM JSON-schema
  output.
