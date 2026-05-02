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

## 7) How to Surface More Information

If you want to see more detail at any time, the assistant can point you to a
specific surface in the UI. The four most useful are the Definition tab, the
Problem Config tab, the Raw JSON tab, and the Results panel — each described in
its own subsection below.

### Definition tab

The structured record of goals, gathered facts, assumptions, and open questions
the assistant is tracking. Things you can do here:

- **Add an entry**: click the `+` button in the Gathered, Assumptions, or Open
  Questions list to insert a new row, then type into it.
- **Edit an entry**: click the row to open the inline editor; press save (or click
  away) to commit.
- **Remove an entry**: click the `×` button on a row. Removed rows show a small
  restore affordance in case you change your mind.
- **Promote an assumption to gathered**: click the `⬆` button on an assumption
  row once it has been confirmed.
- **Clean up definition**: opens a chat-driven cleanup pass that consolidates
  duplicate gathered facts/assumptions and keeps unresolved items in open
  questions. Use this when the definition has grown noisy.
- **Clean up open questions**: a focused pass that drops open questions you have
  effectively already answered elsewhere in the conversation, and tidies the
  rest. Use this after a few rounds of back-and-forth.
- **Sync to config**: pushes the saved definition into the Problem Config tab so
  the numeric setup matches what's been described. The chat will acknowledge the
  sync.
- **Snapshot button**: saves a named snapshot of the current Definition + Problem
  Config together. The dropdown also lets you load a previous snapshot back, or
  load the configuration that was used by the most recent run. Snapshots are the
  fastest way to checkpoint a setup before trying a riskier change.

### Problem Config tab

The active numeric setup that drives the next run. Things you can do here:

- **Adjust goal-term emphases**: each active goal term has a weight you can edit.
  The chat usually proposes good starting values; tweak from there.
- **Choose a term type**: each goal term can be classified as **Obj** (a primary
  objective), **Soft** (a soft constraint that should usually be respected),
  **Hard** (a near-strict limit penalized heavily), or **Custom** (you set the
  exact numeric weight directly, ignoring the soft/hard preset). Custom is the
  right choice when you want full manual control over a specific term.
- **Lock a goal term**: the lock icon next to each term pins its weight in place.
  While a term is locked, neither the chat assistant nor an automatic config
  derivation will change it. Use this to anchor a value you have decided on while
  you experiment with the rest. Unlock when you want it to move again.
- **Pick a search strategy**: see the next subsection.
- **Snapshot button**: same dropdown as on the Definition tab — save a named
  snapshot, restore a previous snapshot, or pull in the configuration from the
  most recent run.

### Search strategy options (on the Problem Config tab)

The search strategy controls how the solver explores. The platform exposes five
algorithm families from the **MEALpy** library:

- **GA** (genetic algorithm) — evolutionary search with crossover and mutation.
  Robust default for most setups.
- **PSO** (particle swarm) — swarm-based search that's strong on smooth landscapes.
- **SA** (simulated annealing) — single-trajectory search that cools over time;
  good for fine-tuning around a known good region.
- **SwarmSA** — annealing-based but with a small swarm of trajectories.
- **ACOR** (continuous ant colony) — ant-colony-style sampling.

Around the algorithm choice, you can also set:

- **Max iterations** — how many search steps to run. Higher values give the search
  more chances to improve at the cost of run time.
- **Population / swarm size** — how many candidates the algorithm holds in
  parallel. Larger populations explore more broadly but each iteration costs more.
- **Algorithm-specific parameters** — for example crossover/mutation rates for GA,
  cognitive/social/inertia coefficients for PSO, initial temperature and cooling
  rate for SA. Defaults are sensible; tune only if you have a hypothesis.
- **Stop early on plateau** — toggles an early-stop rule with a "patience" window
  and a minimum improvement threshold. Saves time when the search has clearly
  converged.

You can ask the assistant for a recommendation: "which search strategy should I
try first for this setup?" or "what's a safe iteration budget for this size?"

### Raw JSON tab

The merged read-only snapshot of definition + config. Useful when you want to
compare two runs field by field, copy a setup out, or check what the solver
actually saw.

### Results panel

The convergence trend, metric cards, violation/feasibility summary, and the
module-specific visualization for the most recent run. You can:

- **Switch between runs**: each completed run is a tab in the run selector. Edited
  or candidate runs are flagged with small badges so they are easy to find.
- **Ask the agent to explain**: the **Explain** button injects a structured
  request into chat asking the assistant to describe the run's strengths, likely
  local-improvement opportunities, why a metaheuristic can still return this
  particular result under the active trade-offs, and one or two concrete next-run
  adjustments — all in plain language.
- **Reuse this config**: the **Reuse This Config** button copies the selected
  run's saved configuration back into the active Problem Config so you can launch
  a new run from exactly that starting point (and then tweak before launching).
- **Include as a candidate**: tick the **Include as candidate** checkbox on any
  run you want to seed the next optimization with. The next time you run, the
  solver does not start from scratch — it pre-loads the routes/selections from
  every checked run into its initial population, so the search begins exploring
  around those known solutions instead of from random. This is the right move
  when a previous run found a structure you like and you want the next run to
  refine around it rather than rediscover it. Multiple candidates can be checked
  at once; uncheck to remove. The candidate set is per-session and resets on
  reload.

Things you can ask the assistant directly:

- "What's currently in my Definition?"
- "Show me the active configuration in plain language."
- "What changed in Problem Config between my last two runs?"
- "Should I lock the lateness emphasis before I tune travel time?"
- "Which algorithm should I try next, and why?"
- "Should I reuse Run #3's config, or seed Run #5 as a candidate first?"
- "Where can I see the convergence chart for this run?"
- "Are there any open questions I should answer before I run again?"

## 8) Troubleshooting

- **Run button unavailable**: check whether required settings are complete in Problem Config and whether unresolved items in Definition need attention.
- **Results look unstable**: reduce simultaneous changes; use one-variable-at-a-time comparisons.
- **No clear improvement**: ask for a focused sensitivity test (for example one weight sweep or one algorithm comparison).

## 9) Useful Prompt Templates

- "Summarize my current optimization strategy in plain language."
- "List my active priorities and constraints."
- "Propose one conservative and one aggressive next run."
- "Explain this configuration as if I were handing it to an engineer."
