# AI-Assisted Metaheuristic Optimization — Detailed Study Plan

## Executive Summary

This study evaluates an AI-assisted optimization interface as a **design artifact**. Participants role-play as a domain expert — someone with working knowledge of optimization trade-offs who would otherwise hire a programmer to configure and run a solver — and interact with the interface from that standpoint. The interface is built around a fixed logistics scenario (QuickBite Fleet Scheduling, a VRPTW instance) presented as a general optimization assistant. The main research focus is on **how the interface supports or fails the domain-expert perspective**: whether it meaningfully changes what such an expert can do without handing the task to a programmer, and how that experience differs across expertise levels and workflow modes.

---

## Study Plan

### 1. High-Level Goals

- **Understand human–AI problem formulation**: How users express objectives, constraints, and trade-offs when working with an AI that configures and runs metaheuristic optimizers.
- **Compare workflows and interfaces**: How different levels of structure, automation, and visualization affect outcomes and user experience.
- **Characterize expertise effects**: How novice vs expert participants differ in how they structure the problem and interact with the AI.

### 2. System Overview (As Experienced by Participants)

Participants are asked to engage with the system from the standpoint of a **domain expert**: someone who understands the problem space (scheduling, routing, optimization trade-offs) but does not write code themselves. The reference frame given to participants is a practitioner who would otherwise hire a programmer to configure and run a solver — and who is now evaluating whether this interface changes that equation.

The system appears to be a **general-purpose metaheuristic optimization assistant** with three main components:

1. **Chat Interface** — Converse with an AI agent to describe the problem, state priorities and constraints, and request solution attempts or “what-if” experiments.
2. **Problem Definition Panel** — Structured representation of objective terms and weights, hard vs soft constraints, and qualitative assumptions.
3. **Optimization & Visualization Panel** — Runs metaheuristic solvers (GA, PSO, SA, SwarmSA, ACOR); shows cost breakdowns, route-level details, and Gantt-style timeline visualizations.

The agent interprets natural language, proposes constraint and objective interpretations, translates user intent into solver configurations, and reports solutions and diagnostics. Internally the system is fixed to a single VRPTW instance; geography, fleet, orders, and traffic model are not editable by participants.

For the concrete task instance and all fixed parameters, see [QuickBite Fleet Scheduling Problem (VRPTW)](#quickbite-fleet-scheduling-problem-vrptw) below.

### 3. Experimental Conditions and Factors

Possible between-/within-subject factors:

- **Workflow style**
  - **Waterfall**: structured; emphasize up-front articulation of objectives/constraints before long optimization runs. Run gated until all open questions are resolved.
  - **Agile**: iterative; frequent runs with lightweight updates to objectives or constraints. Run enabled as soon as ≥1 goal weight and an algorithm are set.
  - **Demo**: blended; freely generates both assumptions and open questions to showcase the full discovery experience, but uses the same lightweight run gate as agile. No open-questions warning banner. Intended for live demonstrations rather than study sessions.
- **User agency**
  - **Manual execution**: user explicitly approves key steps (e.g., solver runs, major objective changes).
  - **More automated**: agent takes more initiative in proposing and executing runs once goals are inferred.
- **Visualization design**
  - **Static**: pre-rendered tables and plots.
  - **Interactive**: hover, zoom, or filter to explore routes, violations, and workloads.
- **Expertise level**
  - **Novice**: limited prior experience with optimization or logistics problem formulation.
  - **Expert**: strong background in optimization, operations research, or logistics. Both groups adopt the domain-expert role-play regardless of actual programming ability — the distinction is the depth of optimization knowledge they bring to that role.

The primary 2×2 design is **expertise (novice vs expert) × workflow (agile vs waterfall)**, with other factors held constant or used as secondary manipulations.

### 4. Data Collected

- **Interaction logs**
  - Full chat history and all actions taken in the interface.
  - System state transitions (e.g., configuration changes, solver runs).
- **Problem formulations**
  - The evolving set of objectives, constraints, assumptions, and locked assignments.
  - Final user-specific configuration objects used to run the optimizer.
- **Optimization performance**
  - Cost values under both user-defined and canonical objectives.
  - Counts of violations and workload statistics.
  - Convergence curves over solver iterations/epochs.
- **Process measures**
  - Completion time, number and spacing of solver runs.
  - Number of reformulations/major specification changes.
- **Subjective measures**
  - Post-task ratings of trust, confidence, perceived control, workload, and usability.
  - Semi-structured interview eliciting critique of the interface as an artifact: what it enabled, what it didn't, and whether it changed the nature of the participant's involvement compared to handing the task to a programmer.
- **Optional recordings**
  - Screen, audio, and/or video recordings of the session (if allowed by protocol).

### 5. User Study Procedure

Participants complete the study remotely or in a controlled lab setting using a computer-based interface.

1. **Introduction and consent**
   - Participants review and sign a consent form and receive a brief overview of the study.
2. **Task briefing and role framing**
   - Participants are presented with the optimization problem and the system interface.
   - Participants are asked to take the perspective of a domain expert who understands the problem space but would otherwise hire a programmer to run the solver. They are encouraged to engage with the system from that standpoint and to notice where the interface does or does not serve that perspective.
3. **Pre-interaction assessment**
   - Participants complete a short questionnaire or brief discussion to confirm task understanding and provide background information (e.g., prior experience with optimization, programming, or related domains).
4. **Interaction phase**
   - Participants interact with an AI agent through a chat-based interface to formulate and solve the problem.
   - The AI agent may gather information, make assumptions, and generate executable optimization procedures.
   - Participants review results, modify specifications, and iteratively refine solutions.
5. **Time constraint**
   - Participants work on the task for a fixed duration (e.g., 30–40 minutes) or until they reach a satisfactory solution.
6. **Post-task questionnaire and interview**
   - Participants complete a survey covering perceptions of the system, confidence in their solution, and overall usability.
   - A semi-structured interview elicits critique of the interface as an artifact: what it enabled, what it didn’t, and whether it changed the nature of their involvement compared to handing the task to a programmer.
7. **Debriefing**
   - Participants receive a full explanation of the study purpose, the system’s actual capabilities and limitations, how their data will be used, and the broader research questions.

### 6. Deception, Risks, and Mitigation

- **Deception**
  - The system is presented as more general-purpose than it actually is; only a single VRPTW instance is truly supported.
  - This is necessary to elicit natural problem formulation behavior and realistic expectations about AI capabilities.
- **Debriefing**
  - At the end of the study, participants are explicitly informed of:
    - The true scope and configuration of the system.
    - How their data will be used.
    - The broader research questions.
- **Risks**
  - Minimal risk study.
  - Primary risk is mild confusion or frustration related to system limitations.
  - Mitigations:
    - Availability of experimenters for clarification.
    - Clear debrief and opportunity to withdraw data if desired (subject to IRB/protocol).

### 7. Intended Uses of This Document

- As **context** for AI agents that assist with:
  - Designing experiments or variants.
  - Analyzing logs and outcomes.
  - Generating new study materials (instructions, prompts, questionnaires).
- As a **reference** for human collaborators (researchers, developers, reviewers).

---

## QuickBite Fleet Scheduling Problem (VRPTW)

This section defines the fixed test problem that underlies all optimization runs. Users experience it as a flexible logistics scenario, but the instance itself is not changed during the study.

### 1. Problem Overview

QuickBite is a fictional delivery service that must serve **30 orders** across **five delivery zones** using a fleet of **five vehicles**. Each order has:

- A delivery zone.
- A time window during which service should occur.
- A size (load units).
- A priority (express vs standard).

The goal is to assign orders to vehicles and sequence their routes to minimize a **composite cost** that trades off:

- Total travel time and fuel.
- Time-window violations.
- Capacity overflow.
- Workload imbalance.
- Driver preference penalties.
- Express-order lateness.

### 2. Geography, Zones, and Travel Time

- **Zones**
  - One central **depot** (index 0).
  - Five delivery zones: A (Riverside), B (Harbor), C (Uptown), D (Westgate), E (Northgate), indices 1–5.
- **Base travel time matrix** (symmetric, in minutes):

  - Depot–A: 12, Depot–B: 18, Depot–C: 25, Depot–D: 30, Depot–E: 22
  - A–B: 8, A–C: 15, A–D: 20, A–E: 14
  - B–C: 10, B–D: 18, B–E: 12
  - C–D: 9, C–E: 11
  - D–E: 7

- **Traffic and variability**
  - Time-of-day traffic multipliers applied to base times:
    - 07:00–09:30: 1.4× (morning peak)
    - 09:30–11:30: 1.0× (normal)
    - 11:30–13:00: 1.3× (lunch surge)
    - 13:00–16:00: 1.0× (normal)
    - 16:00–18:00: 1.5× (evening peak)
  - **Zone D roadworks** (08:00–12:00): add 5 minutes to any trip involving Zone D.
  - **Stochastic noise**: multiply final travel time by Uniform(0.9, 1.1) with a seeded RNG.
  - Implemented by `get_travel_time(from_zone, to_zone, current_time_minutes, rng)` in `traffic_api.py`.

### 3. Vehicles

There are five vehicles with heterogeneous capacities and start times:

- Alice (ID 0): capacity 22, starts at depot at 08:00, max shift 8h.
- Bob (ID 1): capacity 20, starts at depot at 08:00, max shift 8h.
- Carol (ID 2): capacity 20, starts at depot at 09:00, max shift 8h.
- Dave (ID 3): capacity 22, starts at depot at 08:00, max shift 8h.
- Eve (ID 4): capacity 20, starts in Zone E at 09:30, max shift 8h.

Additional assumptions:

- Vehicles cannot depart before their shift start.
- Shift length above 8h incurs a large penalty (treated as a hard constraint in evaluation).
- Drivers are assumed to be salaried (or compensated under a pooled/guaranteed-hours scheme), so the scheduler aims to keep routes operationally efficient while maintaining fair workloads across drivers.
- Drivers have **soft preferences** (penalized in cost), e.g.:
  - Alice dislikes Zone D stops.
  - Carol dislikes many express orders.
  - Dave dislikes very long shifts.

### 4. Orders

Thirty orders are generated deterministically by `generate_orders(seed=0)`:

- Order IDs: `O00`–`O29`.
- Zone: integer 1–5 (delivery zone).
- Size: 1–5 units.
- Priority: `"express"` or `"standard"`.
- Time windows:
  - `time_window_open`: between 08:00 and 14:00 (in 30‑minute increments).
  - `time_window_close`: `open + duration`, duration in {60, 90, 120, 150} minutes.
- Service times:
  - Standard: 10 minutes.
  - Express: 15 minutes.

With `seed=0`, **total demand is 88 units** and total vehicle capacity is 104 units, so feasible solutions exist.

In simulation:

- Travel time from `get_travel_time` is added to the vehicle’s current clock.
- If arrival is **before** `time_window_open`, the vehicle waits until window open.
- Service time is added to compute departure time.
- **Time-window violations and express-order lateness** are measured on **arrival vs `time_window_close`**.
- Service time affects shift duration and workload variance but not lateness directly.

### 5. Objective Function and Constraints

The cost function is a weighted sum:

- Route / travel minutes (**w1**) and shift overtime minutes past the 8h cap (**w2**, fleet total).
- Time-window violation minutes and counts.
- Capacity overflow.
- Workload fairness penalty (shift duration variance across vehicles).
- Driver preference penalties.
- Express-order lateness count.
- Driver early-arrival excess — minutes a driver arrives more than `early_arrival_threshold_min` (default 30 min) before the time window opens (**w8**, off by default; arrivals within the grace period are free).
- Hard shift-violation penalties.

Conceptually:

```text
cost = w1×travel_time + w2×shift_overtime_minutes + w3×tw_violation_min
     + w4×capacity_overflow + w5×workload_variance
     + w6×driver_penalty + w7×express_late_count
     + w8×max(0, wait_minutes − early_arrival_threshold_min)   [summed over all stops]
     + shift_hard_penalty
```

Constraints:

- **Hard**
  - Every order must be served exactly once.
  - Shift duration ≤ 8h per vehicle (heavily penalized if violated).
  - Locked assignments (if specified) must be respected.
- **Soft**
  - Travel time, shift overtime past the cap (w2), capacity, time windows, express lateness, workload balance, driver preferences, driver early-arrival excess (w8, optional), etc., are encoded as penalties in the cost (alongside the separate `shift_hard_penalty` lump field).

### 6. What Users Can and Cannot Change

During the study, **participants do not modify the underlying instance** (zones, vehicles, orders, traffic model). Instead, via chat they influence:

- **Objective weights** (`w1`–`w7`) and whether only specified terms are active.
- **Soft and hard constraint emphasis**, including:
  - Which constraints count as “hard” in the user’s configuration.
  - How strongly to penalize different soft violations.
- **Driver preferences** (e.g., avoid certain zones, avoid long shifts, avoid many express orders).
- **Locked assignments** (e.g., order O06 must go to Alice).
- **Algorithm choice and parameters**
  - Algorithm: GA, PSO, SA, SwarmSA, ACOR.
  - Parameters: e.g. population size, epochs, crossover/mutation rates, cooling schedule, etc.

Internally, the chatbot maps these choices into a JSON configuration (see below) that the optimizer uses.

---

## Codebase and Implementation Notes

This section frames QuickBite as a **test problem for a candidate AI-assisted optimization interface**. It’s meant to help AI agents and developers understand how the prototype is wired end-to-end (chat → structured config → solver → evaluation/reporting), and to support iteration on the interface and study instrumentation **without changing the fixed underlying instance**.

### 1. Core Components

- `traffic_api.py`: Base travel matrix, traffic multipliers, roadworks logic, and `get_travel_time`.
- `vehicles.py`: Vehicle definitions (capacity, start zone, shift start).
- `orders.py`: Order dataclass, order generation (`generate_orders`), and helpers to load/save the canonical order list.
- `user_input.py`: Data structures for objective weights, driver preferences, hard/soft constraints, locked assignments, and user configs.
- `encoder.py`: Encodes/decodes candidate solutions as position vectors with vehicle separators and supports locked assignments.
- `evaluator.py`: Route simulation, cost computation, and metrics (`simulate_routes`, `evaluate_solution`).
- `optimizer.py`: Wraps metaheuristics from `mealpy` and exposes a unified `QuickBiteOptimizer`.
- `reporter.py`: Produces human-readable route summaries and Gantt-ready data for visualizations.

### 2. Solver Interface

- `QuickBiteOptimizer` (in `optimizer.py`):
  - Inputs: weights, locked assignments, seed, and algorithm-specific parameters.
  - Method: `solve(algorithm, params, epochs, pop_size)` returns:
    - Best cost.
    - Routes (list of 5 lists of order indices).
    - Metrics and convergence history.
    - Runtime and algorithm metadata.

### 3. Evaluation and Study Scripts

- `researcher/official_evaluator.py`:
  - Provides **official evaluation** for both:
    - **Problem formulation** (what the user specified).
    - **Solution quality** under canonical objective terms.
- `researcher/run_user_comparison.py`:
  - Loads sample user configurations.
  - Runs the optimizer and prints the official evaluation report.
- `researcher/visualize_convergence.py`:
  - Compares convergence curves for GA, PSO, SA, SwarmSA, and ACOR.
- `researcher/visualize_zone_map.py`:
  - Generates a simple zone map for illustrative purposes.

### 4. Example User Configuration

A typical user configuration (produced by the chatbot and stored under `data/user_*.json`) includes:

```json
{
  "weights": {"w1": 1.0, "w3": 80.0, "w5": 10.0},
  "only_active_terms": true,
  "driver_preferences": [
    {"vehicle_idx": 0, "condition": "zone_d", "penalty": 8}
  ],
  "shift_hard_penalty": 5000,
  "locked_assignments": {"6": 0},
  "algorithm": "GA",
  "algorithm_params": {"pc": 0.9, "pm": 0.05},
  "epochs": 500,
  "pop_size": 100,
  "hard_constraints": ["shift_limit", "locked_assignments"],
  "soft_constraints": ["travel_time", "tw_violation", "workload"]
}
```

AI agents can treat this document as the single source of truth for:

- The **study design and interaction goals**.
- The **QuickBite VRPTW problem definition**.
- The **code-level entry points** for running experiments and analyses.

