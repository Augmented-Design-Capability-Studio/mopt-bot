# Knapsack Module Guide

This module is what I wrote to handle 0/1 knapsack-style selection problems —
choosing which items to include given limited capacity and competing priorities
between value, feasibility, and selection size.

## How I Built This Module

I kept the layout simple and consistent with the platform's other modules.

- **Study port (interface)**: the entry point the rest of the platform talks to. It
  exposes metadata, sanitizes incoming config, and dispatches optimization runs.
- **Bridge (translation layer)**: maps the user-facing goal-term names you see in the
  panel onto the internal numeric form the solver consumes, and translates results
  back the other way.
- **Optimizer (search loop)**: a thin wrapper around the **MEALpy** library. MEALpy
  gives me several stochastic search families (evolutionary, swarm, annealing,
  ant-colony) behind one API, so I can swap strategies without rewriting the rest.
- **Evaluator (objective function)**: scores any candidate selection by combining
  the active priorities into a single number the search minimizes.

When you adjust priorities in chat or in the Problem Config tab, the bridge picks
them up, the evaluator re-weights its score on the next run, and the optimizer
explores alternative selections accordingly.

## Goal Terms — the closed vocabulary

Three priorities can appear on the panel; each maps to one weight key the solver
recognises:

| Priority you can name in chat | Weight key the panel exposes | Default term type |
|---|---|---|
| Total packed value / profit | `value_emphasis` | Objective (maximize) |
| Capacity overflow penalty | `capacity_overflow` | Soft constraint |
| Selection size / sparsity | `selection_sparsity` | Soft (opt-in only) |

These three keys are *auto-anchored* on the port (`auto_anchored_goal_term_keys`
returns the full set): the brief-update step does not need a separate items[]
anchor row to admit them, because the key set is tightly scoped to the problem
and misuse is implausible. That keeps the canonical concepts available even when
the natural-language brief patch commits only prose.

When you ask the agent to keep the selection small (or use words like *fewer
items*, *lighter bag*, *sparsity*), `selection_sparsity` is committed on the
same turn. Without that explicit request it stays off the panel — the phrase
"of the selected items" is part of the value/capacity restatement, not a
sparsity ask.

## First-turn behaviour (canonical starter prompt)

The starter prompt the tutorial pastes for you states both the objective and
the capacity rule:

> *I would like to optimize for a simple knapsack problem. I have a list of 22
> items with various values and weights to put into a bag of 50-weight
> capacity. I want to maximize the value in the bag without exceeding the
> capacity limit.*

When the agent sees a first message that contains **both** the canonical
objective (*maximize the value*) and the canonical constraint (*without
exceeding capacity*), it commits both goal terms on that same turn — regardless
of whether you're in agile or waterfall mode. You should see:

- `Total packed value (objective, weight 1.0) — to push the solver toward
  higher-value selections.`
- `Knapsack capacity overflow (soft, weight 40-ish) — to discourage exceeding
  the knapsack capacity.`

as gathered rows in the Definition tab right after the first reply. No
*"what's your primary optimization goal?"* open question fires, because the
question is already answered. The two open questions you should see on the
first turn instead are:

- **Upload your data file(s).** The chat-footer **Upload file(s)...** control
  is the way in.
- **Which search strategy should we use?** (waterfall only — agile commits
  genetic search (GA) as an assumption you can override). Knapsack-relevant
  options are GA, PSO, SA, SwarmSA, and ACOR.

## Why Results Sometimes Underperform

When a run finishes and the result looks weaker than expected, it is usually one of:

- **Search budget too small.** Too few iterations or too small a population for the
  problem size. Try a longer budget or a different solver family.
- **Conflicting priorities.** Value and feasibility pull in opposite directions and
  neither dominates. The search ends in a compromise neither side likes.
- **Constraint pressure not strong enough.** If overflow penalty emphasis is too low,
  the search will accept infeasible solutions because they look cheap. Raising the
  penalty sharply usually fixes this.
- **Stochasticity.** Metaheuristics are randomized; one run can land in a worse
  basin. Comparing two or three runs is a good sanity check.
- **Instance is genuinely tight.** Capacity is so close to total demand that few
  feasible selections exist. Relaxing one rule slightly or growing the search budget
  is usually the answer.

Ask me to "explain why this run looks weak" and I will walk through which of these
applies, based on the metrics and feasibility status on screen.

## Where to See More in the UI

- **Definition tab**: structured record of your goals, assumptions, and any open
  questions.
- **Problem Config tab**: active goal-term emphases and search-strategy settings.
- **Raw JSON tab**: the exact configuration object captured at run time — useful for
  field-by-field run comparisons.
- **Results panel**: convergence trend, metric cards, feasibility summary, and the
  selected-items view for the most recent run.

## What You Can Ask Me

- "Explain the current setup in plain language."
- "Why didn't this run improve over the last one?"
- "Which single change should I try next?"
- "How do I push for higher value without breaking capacity?"
- "Walk me through how the evaluator scores a selection."

## Typical starting weights (importance levels) for knapsack

When you haven't expressed a preference yet, here are the weight magnitudes I start with for each priority:

- Value emphasis (rewarding total packed value): around **1** — the primary objective baseline.
- Capacity overflow penalty: around **50** — strong enough to discourage exceeding the limit.
- Selection sparsity (preferring fewer items): around **0.5** — light tie-breaker by default.

I scale up or down from these once you tell me what matters most.
