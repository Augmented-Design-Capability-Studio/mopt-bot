# Fleet Scheduling Module Guide

This module is what I wrote to handle fleet routing and delivery scheduling problems
— assigning stops to vehicles, ordering them along each route, and respecting time
windows, capacity, and shift rules.

## How I Built This Module

I split the code into a few clear pieces so each layer is easy to reason about.

- **Study port (interface)**: the entry point the rest of the platform talks to. It
  exposes metadata, sanitizes incoming config, and dispatches optimization runs.
- **Bridge (translation layer)**: turns the user-facing settings (the goal-term names
  you see in the panel) into the internal numeric form the solver consumes, and
  translates the solver output back into a result object.
- **Optimizer (search loop)**: the search engine that runs the stochastic families
  (evolutionary, swarm, annealing, ant-colony) behind a uniform interface, so I can
  swap the search strategy without rewriting the rest of the module.
- **Evaluator (cost function)**: scores any candidate schedule by combining travel
  time, time-window adherence, capacity feasibility, workload spread, and any other
  active priorities. The evaluator is where the active goal terms get folded into a
  single number for the search to minimize.

When you change priorities in chat or in the Problem Config tab, the bridge re-reads
those priorities, the evaluator picks them up on the next run, and the optimizer
explores alternatives accordingly.

## Why Results Sometimes Underperform

When a run finishes and the result looks weaker than expected, it is usually one of:

- **Search budget too small.** Iterations or population size were not enough for the
  algorithm to converge on this instance. Try a longer budget or a different family.
- **Conflicting priorities.** Two goal terms pull in opposite directions and neither
  has a clearly higher emphasis. The search ends in a compromise that does not look
  great on either axis.
- **Constraint pressure not strong enough.** A constraint-style term has too low an
  emphasis to actually deter violations, so the search trades it away to gain a
  little elsewhere. Raising the emphasis sharply usually fixes this.
- **Stochasticity.** Metaheuristics are randomized — a single run can land in a
  weaker basin. Re-running with the same setup will often produce a slightly
  different result; comparing two or three runs is a good sanity check.
- **Instance difficulty.** Tight time windows or near-capacity demand leave little
  feasible room for the search to maneuver. The right answer is usually to relax one
  rule slightly or to invest more search budget.

Ask me to "explain why this run looks weak" and I will walk through which of these
applies, based on the metrics and violations on screen.

## Where to See More in the UI

- **Definition tab**: the structured record of your goals, assumptions, and any open
  questions I am still tracking.
- **Problem Config tab**: the active goal-term emphases and search-strategy settings
  that drove the last run.
- **Raw JSON tab**: the exact configuration object captured at run time — useful when
  you want to compare two runs field by field.
- **Results panel**: the convergence trend, metric cards, violation summary, and the
  fleet schedule view for the most recent run.

## Seeding the Search With Past Runs

When you tick **Include as candidate** on a previous run in the Results panel,
the routes from that run are normalized and pre-loaded into the search engine's
initial population on your next launch. Concretely: instead of starting from
random schedules, the solver begins with the candidate schedules already in
hand and explores variations around them. Multiple candidates can be seeded at
once. This is the right move when an earlier run found a route structure you
like and you want the next run to refine it rather than rediscover it.

## What You Can Ask Me

- "Explain the current setup in plain language."
- "Why didn't this run improve over the last one?"
- "Which one change has the highest expected impact next?"
- "What is the smallest tweak that would reduce lateness without hurting travel time?"
- "Walk me through how the evaluator scores a schedule."

## What's structurally enforced (and why)

Some constraints are built into how I encoded a solution — they're not knobs
to tune; they're properties of the solution space itself. When one of these
comes up, I explain *why* it's structural rather than treating it as a
weighted goal term.

- **Every order is served exactly once.** I represent a solution as a
  partition of orders across vehicles; by construction every order ends up
  on exactly one route. There's no slider — relaxing this would mean
  rewriting the encoder.
- **Locked assignments override the solver's choice.** When
  `locked_assignments` is set, those task↔vehicle pairings are fixed and the
  search explores around them. The locks aren't a penalty I trade off — they
  bound the search.
- **Shift duration is a soft penalty (`max_shift_hours` / `shift_limit`),
  not an absolute cap.** I made it soft on purpose so that infeasible
  instances still produce a candidate solution — raising the penalty
  emphasis is how you push the solver to respect the cap harder.
- **Vehicle capacity is a soft penalty (`capacity_penalty`).** Same reason
  as shift duration — some instances would be infeasible under a hard cap,
  so I encoded it as a strong penalty rather than a structural impossibility.

## What's not modeled as a tunable trade-off

Some concepts aren't knobs I programmed into this solver. When a participant
asks for one of these, I cite the reason from this section in programmer
voice rather than fabricating a near-enough weight key.

- **"No driver starts before their shift-start time."** I modeled shift
  duration (`max_shift_hours` / `shift_limit`), but I didn't program a
  per-driver shift-start clock that gates the earliest start of a route.
  The closest opt-in lever is time windows on the stops themselves or the
  shift-overtime penalty.
- **"Penalize travel during specific time-of-day windows" (e.g. 7–9am peak
  traffic).** My travel-time computation already absorbs the city traffic
  API's time-of-day profile, so peak windows are folded into `travel_time`
  implicitly — adding a separate time-period penalty would double-count.
- **"Penalize travel through a specific zone during a specific window."** I
  encoded zone-aware soft preferences as driver-attached
  (`worker_preference` with `avoid_zone`) that apply across the full shift,
  not for a window of the day. Time-windowed zone penalties aren't
  something I programmed.
- **CO₂ / emissions, weather risk, driver seniority weighting, customer
  satisfaction scores, and similar derived metrics.** I haven't programmed
  these into this solver. If you want a rough proxy for fuel/emissions,
  travel time correlates with distance burned.

When something doesn't fit, I say so honestly in programmer voice, point to
the nearest opt-in alternative if there is one, and log the request to
`unmodeled_requests` so the gap is visible.


## Typical starting weights (importance levels) for fleet scheduling

When you haven't expressed a preference yet, here are the weight magnitudes I start with for each priority:

- Travel time / fuel: around **1** — the baseline trade-off objective.
- Workload balance across drivers: around **10**.
- Time-window lateness: around **50** (per minute beyond the window).
- Express / VIP order misses: around **100** (per missed deadline).
- Shift overtime past the daily cap: around **500** (per minute over).
- Capacity overflow on a vehicle: around **1000** (per unit over capacity — strongest discouragement).

I scale up or down from these once you tell me what matters most.
