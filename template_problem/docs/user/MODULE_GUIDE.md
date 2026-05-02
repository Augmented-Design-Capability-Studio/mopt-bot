# Module Guide (Template)

Copy this file when you create a new problem module under
`yourproblem_problem/docs/user/MODULE_GUIDE.md`. Keep the structure — the chat agent
retrieves these sections by heading when the conversation warms up.

## How I Built This Module

Describe the code in four short bullets. Use plain, business-friendly language but
keep a programmer's voice.

- **Study port (interface)**: one-line description.
- **Bridge (translation layer)**: one-line description.
- **Optimizer (search loop)**: thin wrapper around **MEALpy** (or whatever solver you
  used). Mention MEALpy explicitly when applicable — the agent is allowed to.
- **Evaluator (objective function)**: how candidate solutions get scored.

Optionally: one paragraph on how user changes flow through the layers into a run.

## Why Results Sometimes Underperform

List the common failure modes for *this* problem family. Reuse and adapt the
patterns the other module guides use:

- Search budget too small.
- Conflicting priorities.
- Constraint pressure not strong enough.
- Stochasticity.
- Instance difficulty (problem-specific phrasing).

## Where to See More in the UI

Always include this section. Reference the four standard surfaces:

- Definition tab
- Problem Config tab
- Raw JSON tab
- Results panel (mention the visualization specific to your module)

## What You Can Ask Me

A short list of useful prompts. Keep them generic enough to retrieve well.

## Authoring rules (do not delete this section while editing — drop it before merge)

- **Do not list specific goal terms by name** in this guide. The agent should only
  talk about goal terms that already appear in the user's chat, Definition, or
  Config — listing them here causes leakage at warm-up.
- **Do not name internal keys** (snake_case parameter names, weight aliases). Use
  user-facing labels only.
- **Mention MEALpy** when describing the optimizer; that is allowed.
- **Maintain the illusion that the agent wrote this module.** Use first person ("I
  built", "I wrote") consistent with the chat style.
