# Flow Control Map — node → state/gate → who decides

> Companion to `interface_flow.md` (what the flow *is*, plus the
> action→pipeline map in its Part 2) and `CHAT_PIPELINE.md` (stage
> internals). This doc answers one question: **at each point in the
> flow, what state are we in, what gate governs it, and who — the LLM or
> deterministic code — should be the one deciding.**

## The dividing principle

The LLM is strong at **perception and prose**: reading where a
conversation is, distilling free text into a structured candidate,
writing the visible reply. It is unreliable at **logic and invariants**:
counting, precedence, "is this allowed right now", "does this contradict
what's already saved." This matches the repo's standing guidance
(`feedback_prompt_reduction_principles`, `feedback_no_prompt_bandages`):
keep deterministic gates for logic, lean on the model for summarize/expand.

So the contract for every node below is:

- **LLM proposes** — classifies the node, emits a typed intent (a brief
  patch, an `oq_action`, an `assumption_action`, a candidate goal_term).
- **Code disposes** — maps the node to instructions, checks the gate,
  owns foundational state, applies/coerces/anchors/syncs.

"LLM picks the node, code judges what follows" is exactly the split you
proposed, and most of the system already works this way. The gaps below
are the places where a *logic* decision is still being made by a prose
rule, or where a *node* is still being detected by keyword matching.

## Node table

State is read from signals the server already holds: the brief shape
(`is_chat_cold_start`), the cold/warm/hot classifier, the synthetic
`context_kind` flags, `workflow_mode`, and the run gate.

| Flow node | Detected by | Instructions attached | Actions decided by |
|---|---|---|---|
| Cold start / small talk | `is_chat_cold_start(brief)` true | base prompt only; sandbox rules on | code (state flag) |
| Warm, well-aligned | classifier `warm`/`hot` + brief non-empty | + warm block, benchmark appendix, weights/lock blocks | code attaches; LLM distills goals |
| Warm, misaligned (hard-constraint / out-of-scope) | LLM recognizes from appendix vocab | hard-constraint + out-of-scope discipline (always loaded) | LLM proposes; code logs `unmodeled_requests` |
| Concept question | `is_change_intent=false` + empty patch + empty `change_clause` | (S2–S5 skipped, fast path) | code (settles); LLM writes reply |
| Run-result / status question | `recent_runs_summary` present | run results + run-button line injected | code (deterministic context) |
| Run completed (run-ack) | `is_run_acknowledgement` flag | `_run_ack_prompt(mode)` | LLM proposes delta; S2 enforces axis invariant |
| Brief-edit ack | `is_brief_edit_ack` flag | base; reply names the specific change | LLM (reply); code re-derives config |
| Config-save ack | `is_config_save` flag | `CONFIG_SAVE_RATIONALE`; S4 skipped | code (panel authoritative); LLM mirrors prose |
| Answered open question | `is_answered_open_question` flag | `ANSWERED_OQ_CONTEXT` | `classify_answered_open_questions` (LLM) → code buckets |
| Upload | `is_upload_context` flag | `UPLOAD_CONTEXT_GUIDANCE` | code records canonical row; LLM adds revealed facts |
| Tutorial active | `participant_tutorial_enabled and not completed` | `TUTORIAL_GUARDRAILS` | code suppresses run-ack invariant on Runs 1–2 |
| Cleanup | `cleanup_mode` flag from patch | one cleanup line | LLM full-replace; code prunes stale synth rows |

## Who should own each responsibility you listed

### 1. What instructions to attach — **code**, off a node label

Today most blocks are attached by deterministic flags (good). The two
exceptions — the sandbox-rules block and the visualization block — are
gated by **substring keyword lists on `user_text`**
(`_SANDBOX_PROBE_KEYWORDS`, `_VISUALIZATION_KEYWORDS` in `study_chat.py`).
That is keyword-matching natural language, which `feedback_no_regex_for_nl`
rules out and which silently misfires on paraphrase ("can you tweak how
the routes are drawn?" misses every viz keyword).

Recommendation: have the LLM emit a small **node/intent label** (extend
the existing cold/warm/hot classifier, or add one sibling field), then
map node→blocks in code and retire the keyword lists. The model is good
at "is this a code-probe / a viz-reshape / a concept question"; code is
good at "given that label, attach exactly these blocks." This removes the
last regex-on-NL seam and keeps attachment deterministic and testable.

### 2. What action we're taking — **LLM proposes a typed intent, code disposes**

Split by how much *logic* the call needs:

- **Doc search** — code. Retrieval ranking is deterministic; the query is
  the raw user text (fine — it's a search query, not a routed decision).
- **Enable/disable run button** — code only (`can_run_optimization`).
  Never let the reply assert runnability; the gate is the single source.
- **Open questions**
  - Foundational topics (`upload`, `primary_goal`, `search_strategy`):
    **code** (`_enforce_session_monitors` is the sole writer; merge strips
    any foundational OQ the LLM emits). Keep.
  - `other` clarifications (raise / keep / drop / rephrase): **LLM
    proposes** via `oq_actions`; **code validates** (caps the count,
    inherits parent topic on re-ask, vetoes an unauthorized
    search-strategy commit). Keep.
- **Assumptions** (make / keep / promote / remove): **LLM proposes**;
  **code coerces** (waterfall assumption→OQ, demo drops). The weak spot is
  **promotion**: "did the user lock this in?" is currently a prose rule
  ("conservative promotion") the model judges. That is a logic/precedence
  call the model gets wrong (treats a bare "sure" as a lock-in). Candidate
  to harden: make promotion a typed `assumption_action` the model emits
  *only* with a quoted lock-in span, and have code reject promotions whose
  cited span doesn't name the term — same pattern as goal-term anchoring.

The general rule: the LLM answers the **perception** question ("does this
message lock in the capacity penalty?"); code answers the **authority**
question ("is promotion allowed and how is it recorded?").

### 3. What config to patch, what to feed back — **LLM distills, code reconciles**

- **Brief → config (S4)**: LLM distills the brief into a panel patch
  (good — distillation). Code then does the non-negotiable parts
  deterministically: strict-subset filter, search-strategy backfill,
  auto-anchored mirror, `sync_panel_from_problem_brief`. Keep.
- **Feedback to chat**: LLM owns the visible reply prose. Keep.
- **Feedback to definition**: structured carriers (`config-weight-*`,
  driver-pref rows) are **synthesized by code** from `goal_terms`; the LLM
  must not hand-write them. Keep — this is what keeps prose and structured
  carrier consistent-by-construction.

## What's missing / worth deciding

1. **No explicit node classifier.** State is inferred from flags + a
   cold/warm/hot label; there is no single "which flow node is this" signal.
   Adding one (LLM-emitted, code-consumed) would let block-attachment and
   action-gating share one perception pass and retire the keyword lists
   (finding above). This is the highest-leverage change and the one your
   proposal points at directly.
2. **Promotion of assumptions is logic-by-prose.** See §2 — a typed,
   span-cited promotion action with a deterministic check would close it.
3. **Keyword gates violate `feedback_no_regex_for_nl`.** `_SANDBOX_PROBE_KEYWORDS`
   and `_VISUALIZATION_KEYWORDS` should be replaced by node labels, not
   extended with more keywords.
4. **Demo mode** is a third workflow now covered in `interface_flow.md`
   (Part 1 and the §M symmetry contract). Fine as-is.
5. **Misaligned-warm steering** (hard-constraint / out-of-scope) is the one
   node with no state signal — it's recognized only by the LLM against the
   appendix vocabulary, and the disciplines are always loaded. Acceptable
   (the cost is a couple of always-on blocks), but it's the node least
   under deterministic control; worth watching if those blocks need to grow.
```

