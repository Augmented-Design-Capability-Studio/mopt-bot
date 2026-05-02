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
