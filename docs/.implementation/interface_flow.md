# Participant Interface Flow — Specification (Draft)

Scope: behavior of the chat + definition + config + run loop *during* a
participant session. Project goal, study plan, and 2×2 conditions are
documented elsewhere and are not repeated here.

This document is descriptive of the intended flow only. Critique of the
architecture lives in `interface_flow_critique.md` alongside this file.

## 1. Initial messages (cold vs warm chat)

When the participant starts chatting, classify the turn into one of three
states. The classification is per-turn — the chat can warm up mid-session.

- **Cold.** Nothing problem-relevant in the message (e.g. "hi", or a
  generic optimization question with no goal/constraint content). The
  agent stays in small-talk / orientation mode and does **not** start
  producing definition rows or invite a file upload.
- **Warm — well-aligned.** The participant talks about the overall goal
  and/or some constraints in a way that maps cleanly onto the problem
  module's expected goal terms. The agent may start producing
  definition entries (goal terms, gathered info, assumptions if agile)
  and/or invite a file upload.
- **Warm — misaligned.** The participant talks about the problem but
  what they say either (a) conflicts with how the problem is hard-coded
  / encoded, or (b) names constraints that, while valid, do not move
  the trade-off (so they're already baked into the encoding rather than
  surfaced as tunable terms). The agent should explain *how* the
  problem is coded and gently steer the user toward the meaningful
  trade-off dimensions — without dismissing the user's intent.

## 2. Status monitoring (warm only)

Once the chat is warm, the system tracks four state signals each turn:

- file upload status
- goal-term existence (any weighted goal term in the brief/config)
- search-strategy existence (algorithm set on the saved config)
- hanging open questions (waterfall mode)

…which together determine **run-button availability**.

Mode-dependent behaviour:

- If no goal term is defined or no file is uploaded: the corresponding
  open questions are kept (do not auto-resolve).
- Missing search strategy:
  - **Agile:** agent makes an assumption (proactive default) on the
    same turn and records the structural carrier so the gate updates.
  - **Waterfall:** agent files another open question; no proactive
    default.

## 3. Messaging (chat-driven updates)

As the user chats, the agent returns updates to the problem definition:
goal terms, run summary, open questions, assumptions (agile, and
possibly demo), and gathered info.

One retrieval stage and two follow-on LLM stages sit behind the chat
reply:

- **Documentation search.** Before the chat reply is produced, the
  system retrieves the most relevant sections from an external
  knowledge base so the agent can ground answers to participant
  questions about the problem, algorithms, or interface without that
  content living in the chat prompt. The agent does not name documents
  or quote them verbatim.

- **Validator (post-derivation compliance).** Verifies the definition
  panel against the visible reply's intent. If the agent invites a run
  but the run button would *not* actually be available, the validator
  rejects, and the chat call is retried with system status injected so
  the agent re-phrases.
- **Derivation (definition → config).** A separate call maps the
  definition to the problem config; alignment mechanisms keep the
  definitions and configs from drifting apart.

## 4. Run and post-run

The user can trigger a run via:

- a chat command,
- a run button inside a chat message,
- the run button on the viz panel.

After each run, the agent:

1. Acknowledges the run (run summary update).
2. Adds *one or two* new entries — either assumptions (agile / demo) or
   open questions (waterfall) — based on the mode and what the run
   surfaced.

## 5. Editing the definition panel

The user can edit the definition. Supported actions:

- answer open questions
- edit and promote assumptions (assumption → gathered info)
- edit goal summary
- edit run summary
- edit gathered info
- remove entries

On save:

- Derivation is re-triggered to update the config.
- The chat acknowledges *what specifically changed* (not a generic
  "got it").

## 6. Editing the config panel

The user can edit:

- goal-term ranks and weight types
- sub-properties of certain goal terms (see §7)
- the search strategy / algorithm
- remove goal terms

On save:

- The agent acknowledges the change in chat.
- Corresponding definition entries are updated — especially assumptions
  and gathered info — so the two panels stay coherent.

## 7. Special goal terms with sub-properties

The definition panel is intentionally **flat** (no nested entries), but
some goal terms (e.g. VRPTW driver preferences with per-driver
properties, max shift hours, etc.) carry sub-properties on the config
side. The interface presents these as best it can on both sides; the
mapping is bridged by the problem module (`StudyProblemPort`) so the
main backend stays problem-agnostic.

## 8. Additional user actions to plan for

These are first-class in the existing backend even if you didn't list
them explicitly — worth covering in the same flow doc:

- **Re-upload / replace file.** A second upload after a run resets the
  data-dependent parts of the definition; goal terms keyed to old
  fields may become orphaned and need to be either re-anchored or
  flagged.
- **Cancel an in-flight run.** Mid-run cancellation is supported; chat
  acknowledgement needs a distinct shape from "run completed".
- **Reset the session.** A hard reset (back to pre-warm). Definition
  and config are wiped; chat history may be preserved for the
  researcher view but the participant view starts clean.
- **Bookmark / snapshot the current state.** Participant-initiated
  snapshot bookmarks already exist server-side. They're a no-op for
  the optimization loop but the chat should not react to them as a
  brief edit.
- **Researcher-only steer / nudge messages.** Hidden injections that
  affect agent behaviour without appearing in the participant
  transcript. Need to make sure these don't trip the validator's
  "claimed a change" / "asked a question" intent detection.
- **Switch workflow mode (researcher action).** Treated as a clean
  cut; the post-switch turn should not inherit assumptions filed under
  the prior mode's rules (e.g. agile-style proactive defaults
  surviving into a waterfall switch).
- **Undo last edit.** Not currently a primitive, but worth deciding:
  if a definition edit triggers derivation and the user immediately
  reverts, the derivation should be cancelled-in-flight rather than
  applied then re-reverted.
- **Run an "evaluate edit" without re-solving.** Already supported on
  the backend (`post_evaluate_edit_run`); the chat flow should
  describe how its acknowledgement differs from a fresh run.
