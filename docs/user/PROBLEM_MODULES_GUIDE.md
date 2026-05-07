# Problem Modules Guide

This guide explains how optimization problem modules are organized and how configuration choices map to solver behavior.

## 1) What Is a Problem Module?

A problem module is a packaged domain implementation that provides:

- Problem metadata for UI rendering
- Config validation and normalization
- Solver translation from user settings to executable optimization runs
- Prompt/schema support for structured AI-assisted configuration

At runtime, the backend loads registered modules and selects the active one for each session.

## 2) Core Concepts Users Should Know

- **Goal terms**: weighted components that encode what to optimize.
- **Constraint emphasis**: indicates whether a term is treated more strictly or as a softer preference.
- **Search strategy**: algorithm and hyperparameters controlling exploration.
- **Run snapshot**: the exact config state captured with each run result.

These concepts are shared across modules, even when domain vocabulary differs.

## 3) How User Inputs Become Runs

The high-level translation path is:

1. User asks or edits in chat/panel.
2. System maintains a structured problem definition.
3. Definition maps to a problem configuration JSON.
4. Active module validates and sanitizes that configuration.
5. Solver runs with selected strategy and parameters.
6. Results are returned with metrics and artifacts for comparison.

## 4) Why This Matters for Explanations

When users ask "what did you program?", useful answers should reference:

- Which goal terms were prioritized
- Which constraints were made stricter/softer
- Which search strategy and parameters were selected
- What changed relative to prior run snapshots

This gives a concrete operational explanation without requiring users to read source code.

## 5) Module-Oriented Vocabulary (Searchable)

Use these terms when searching docs or asking the assistant:

- "study port"
- "panel schema"
- "sanitize config"
- "parse config"
- "solve request"
- "weight aliases"
- "algorithm params"
- "run snapshot"

## 6) Practical Questions to Ask the Assistant

- "Explain the current module settings in engineer-ready terms."
- "Show how my goal terms map to optimization penalties."
- "What did you change in search strategy between the last two runs?"
- "Which config values are likely causing this violation pattern?"
- "If we keep constraints fixed, what single parameter should we tune next?"

## 7) Advanced: Change Discipline

For reliable improvement:

- Keep one baseline run as a reference.
- Apply small, explicit config changes.
- Compare with a short written hypothesis ("this should reduce lateness at some travel-time cost").
- Confirm whether outcomes matched the hypothesis before expanding scope.

## 8) How I pick starting importance levels (weights)

Importance levels — the weights you see in Problem Config — encode your priorities, not anything calculated from your data. When a new goal term appears, I pick a starting number that places the most-important term clearly above the others, then scale the rest relative to it. Comparable priorities get close numbers; clearly dominant ones get big gaps. I lean on a sensible starting magnitude for the term's role (penalty-style terms start higher than trade-off objectives). I propose values in chat; you confirm before anything sticks.

## 9) How term type shapes the importance level (weight)

Term type tells me how to treat the weight.

- **Objective**: my anchor — the main thing being improved. Everything else scales relative to it.
- **Soft**: trade-off range alongside Objective; some violation is acceptable if gains elsewhere are large.
- **Hard**: I lift the weight **roughly an order of magnitude** above its Soft equivalent, so any violation dominates the cost and the search avoids it.
- **Custom**: your fixed override — I leave the number alone.

Hard here is a strong push, not absolute rejection. Truly unbreakable rules live in how candidates are constructed.

## 10) How rank (priority order) shapes the importance level (weight)

The rank you assign — by reordering goal terms in the priority list — is a tiebreaker and a soft scaler on the weights. When two terms sit at similar levels and one is ranked above the other, I bump the higher-ranked term's weight up by **about 25–50%** so the search resolves the tie in your favor. Bigger rank gaps translate into bigger weight gaps; reordering is a way to nudge me without touching the numbers yourself. Rank is your steering wheel for emphasis; the weight is the throttle.

## 11) How I adjust importance levels (weights) after a run

After each run I read the cost breakdown. If a term contributed **more than its share** of your stated priorities, I propose **halving** its weight. If a term you said matters barely contributed, I propose **doubling** its weight. I cap a single round's adjustment at roughly **2× up or down** so we don't ping-pong between extremes. I propose changes in chat — they don't apply until you confirm or edit them yourself. Over a few runs, this converges on a setup where the cost composition matches the priorities you described.

## 12) What the absolute weight numbers mean

The absolute weight on any one term is meaningless on its own — what shapes the search is the **ratio** between weights. Doubling every weight changes nothing; doubling one term's weight makes it twice as influential as before. When you ask me "how are weights determined?" or "why is X at Y?", I quote the actual number from your saved Problem Config and put it in context: which term is dominating, which is being downweighted, which type each carries. Read the list as a relative priority statement, not as a per-unit price.
