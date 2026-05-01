# Interface Guide

This guide explains how to use the optimization interface effectively during a session.

## 1) Screen Layout

The participant app has three main panels:

- **Chat panel**: describe goals, ask questions, and request changes.
- **Problem setup panel**: define objective terms, constraints, assumptions, and run settings.
- **Results panel**: inspect run outputs, compare runs, and interpret trade-offs.

## 2) Typical Workflow

1. Describe your operational priorities in chat (for example, reduce lateness, improve workload balance, or enforce stricter constraints).
2. Review the structured definition in the **Definition** tab.
3. Review and adjust numeric settings in **Problem Config**.
4. Run optimization.
5. Compare outputs and refine.

Repeat until the solution reflects your priorities.

## 3) Problem Setup Tabs

### Definition

Use this tab to track:

- **Goal summary**: concise statement of what success means.
- **Run summary**: rolling summary of current strategy.
- **Gathered info**: confirmed facts and preferences.
- **Assumptions**: temporary choices used while information is incomplete.
- **Open questions**: unresolved items that may block or weaken decisions.

### Problem Config

Use this tab for structured controls:

- Goal-term weights
- Constraint type emphasis
- Search strategy (algorithm, iterations, population size)
- Algorithm parameters
- Optional strategy controls (such as early-stop behavior)

### Raw JSON

Read-only combined state for troubleshooting and transparency.

## 4) Writing Better Requests in Chat

Good requests are concrete, scoped, and testable. Prefer:

- "Prioritize on-time delivery over route length by about 2x."
- "Treat shift limit as strict and lower emphasis on workload variance."
- "Try GA and PSO with the same weights, then compare trade-offs."
- "Explain the top 3 reasons this run improved."

Avoid vague requests like "make it better" without priorities.

## 5) Interpreting Run Results

After each run, check:

- Total objective/cost trend vs previous run
- Violation pattern changes (what improved, what worsened)
- Workload and assignment balance
- Sensitivity to algorithm/search settings

Use comparison prompts such as:

- "What changed from Run #3 to Run #4?"
- "Which settings most likely drove this improvement?"
- "What is the next smallest change worth testing?"

## 6) High-Confidence Iteration Pattern

Use this cycle to avoid noisy trial-and-error:

1. Change one major lever at a time.
2. Keep a short rationale for each change.
3. Run and compare against the previous baseline.
4. Keep winning changes; revert weak changes.
5. Repeat with one additional lever.

## 7) Troubleshooting

- **Run button unavailable**: check whether required settings are complete in Problem Config and whether unresolved items in Definition need attention.
- **Results look unstable**: reduce simultaneous changes; use one-variable-at-a-time comparisons.
- **No clear improvement**: ask for a focused sensitivity test (for example one weight sweep or one algorithm comparison).

## 8) Useful Prompt Templates

- "Summarize my current optimization strategy in plain language."
- "List my active priorities and constraints."
- "Propose one conservative and one aggressive next run."
- "Explain this configuration as if I were handing it to an engineer."
