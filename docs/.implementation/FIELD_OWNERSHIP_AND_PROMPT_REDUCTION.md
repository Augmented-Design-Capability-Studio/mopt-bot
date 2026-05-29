# Field ownership & prompt reduction — design plan

> Status: **proposal** (not yet implemented). Captures the structural-fix
> strategy that came out of the P_0529 investigation. The P_0529 bug fix
> itself (waterfall search-strategy gate + first-turn warmth) is already
> merged; see `gate_unauthorized_search_strategy_commit` in
> `routers/sessions/derivation.py` and the foundational-OQ warmth flip in
> `problem_brief.merge_problem_brief_patch`. This doc is about preventing
> the *class* of bug, not the single instance.

## The recurring failure shape

P_0529 (waterfall, vrptw): on the upload turn the agent claimed it had
"configured GA," wrote `goal_terms.search_strategy.properties.algorithm
= "GA"`, added a `source: user` row, and dropped the still-open
search-strategy question — all without the participant ever choosing an
algorithm.

The prompt *explicitly* forbade this ("Do NOT silently set a default
algorithm"). The LLM ignored it, and nothing structural caught it. That
is the pattern:

> **A prose rule tells the LLM what to do; the LLM doesn't comply; no
> code enforces it; the bad state ships.**

We already have a pipeline and self-verification feedback loops, yet
errors persist. Two reasons:

1. **Self-verification shares the drafter's blind spots.** S2/S5 re-ask
   the same model family; when the drafter rationalizes a bad write, the
   verifier often rationalizes it the same way.
2. **Verifiers only catch invariants we wrote.** No invariant existed for
   "algorithm carrier requires an answered OQ," so nothing fired.

Adding more prose to the prompt is a bandage (see
`[[feedback_no_prompt_bandages]]`): every block we add dilutes attention
on the blocks already there, raising the error floor everywhere else.

## The model: input channels + precedence (NOT "single writer")

An earlier framing of this plan said "single-writer-per-slot," which was
misleading. The participant must **always** be able to override anything
the agent produces — that's the entire point of the editable Definition
and Config panels. We are not restricting who can change a value.

Two separate concepts must stay distinct:

### 1. Input channels — who is allowed to express intent

Three legitimate channels, none restricted:

- **Participant via chat** — typing an answer or request.
- **Participant via panel** — editing the Definition / Config surface directly.
- **Agent proposal** — the LLM suggesting/committing a change.

### 2. Code paths — which server code mechanically writes a field per turn

For a single brief field there can be several *code paths* that each try
to set it on one pipeline turn. For `goal_terms.search_strategy` there
were **four**: the LLM-patch merge, panel→brief sync, the monitor state
machine, and the canonical-row synthesizer. Bugs live in their
disagreements. P_0529 was exactly this — the LLM-patch path wrote "GA"
while the monitor went silent, and they disagreed about whether the user
had chosen.

### The rule we enforce: precedence, not lockout

```
explicit user action (panel edit / clear chat answer)
        >  agent proposal
        >  server default
```

Per field, per turn, **honor the highest-precedence channel that
actually fired.** Consequences:

- User edits algorithm in the panel → wins, unconditionally.
- User answers in chat → wins.
- Agent proposes with a user behind it (chat answer, prior panel answer)
  → flows through untouched.
- Agent *invents* intent with no user signal → blocked. This is the only
  thing the gate stops, because there is no user intent to honor.

This directly answers the "can't the user change what the agent spits
out?" concern: **yes, always.** The gate never blocks a user; it blocks
the agent from *fabricating* that a user acted. The P_0529 gate already
embodies this — the instant any user signal exists (algorithm present in
the base brief from a prior answer, or a chat answer this turn), the
write passes through.

## Workstreams

### W1 — Field ownership & precedence map (read-only first)

For every brief field, document:

| Field | Input channels that target it | Precedence resolver (the per-turn authority code path) | Notes |
|---|---|---|---|
| `goal_terms.<weight key>` | chat, panel, agent | merge + anchor filter | user retunes always win |
| `goal_terms.search_strategy` | chat, panel, agent | **gated** (`gate_unauthorized_search_strategy_commit`) | waterfall: needs user answer |
| `goal_summary` | chat, panel, agent | merge (non-empty wins) + autofill fallback | empty patch must not wipe |
| `priority_line` | — | server-derived only | already single-source |
| `open_questions` (foundational) | server | monitor state machine | LLM copies stripped at merge |
| `open_questions` (other) | chat, panel, agent | merge + oq_actions | |
| `items[].source` (provenance) | derived | **TODO: server-derive** (see W2) | LLM currently self-reports |
| `unmodeled_requests` | agent | append-only merge | |

Deliverable: a table like the above, complete, plus a flag on every row
where **more than one code path** can write **and** there is no explicit
precedence resolver. Those rows are the next P_0529-class bugs. This
step touches no code.

### W2 — Server-derived provenance

The LLM tagged a forged row `source: user`. The LLM should not be the
authority on provenance. Derive `source` from origin context: was there
a user message / upload this turn that motivates the row, or is this an
agent-proactive addition? This kills the "fait-accompli with fake user
attribution" class and lets us delete the provenance prose rules (see
`[[feedback_provenance_origin_not_phrasing]]`,
`[[feedback_agile_proactive_assumptions]]`).

Risk: medium — provenance currently feeds gating (`is_chat_cold_start`
excludes `source: agent`) and display. Must preserve those semantics.

### W3 — Convert prompt rules → state gates, then delete the prose

Highest leverage, most invasive. Walk `prompts/study_chat.py`; for each
*"do/don't X when Y"* rule ask: **can a post-merge function enforce this
from brief state?** If yes, add the gate and delete the block. Each
deletion shrinks the prompt, which improves compliance on what remains.

Already done as the template for this: the waterfall search-strategy
block shrank from a 5-line enforcement-by-prose rule (with a hardcoded
acronym list, violating `[[feedback_dynamic_algorithm_oq]]`) to a
3-line behavioral nudge, because
`gate_unauthorized_search_strategy_commit` now enforces it.

Candidate rules to convert (audit W1 will surface more):
- claim-implies-patch invariant (partly structural already)
- foundational-OQ ownership (already structural; prose can shrink)
- assumption numeric-carrier requirement (`[[feedback_structured_carrier_same_turn]]`)
- replace-flag-without-list guardrail (already a verifier check)

Goal metric: net prompt token reduction per fix, not growth.

### W4 — Make verification independent

Self-verification has a ceiling. Options to evaluate (pick per check):

- **Prefer deterministic/structural checks** with no LLM (most S2/S5
  checks already are — extend coverage).
- **When an LLM check is unavoidable**, give it *only* the invariant +
  the artifact to judge, NOT the drafting conversation/context, so it
  can't inherit the drafter's rationalization.
- **Maintain an invariant coverage list** so we know what is actually
  checked vs. assumed. P_0529 had no invariant; a coverage list makes
  such gaps visible.

Depends on W1–W3 (what they made deterministic informs what's left for
the LLM).

## Sequencing

1. **W1 audit** — read-only, lowest risk, tells us where real risk is.
2. **W2 + W3 in tandem** — each gate added lets prose be deleted.
3. **W4 last** — informed by what 1–3 turned deterministic.

## Non-goals / guardrails

- **Never reduce the participant's ability to edit.** Precedence always
  ranks explicit user action highest.
- **Preserve the 4 canonical workflow axes** (`[[project_workflow_axes]]`)
  — gates must stay symmetric except on those axes.
- **Keep the main backend problem-agnostic**
  (`[[feedback_problem_module_isolation]]`) — gates live in main backend,
  problem specifics behind `StudyProblemPort`.
- **Test minimalism** (`[[feedback_test_minimalism]]`) — one focused
  test per gate; prefer replaying a real session turn shape.
