# QuickBite Fleet Scheduling — VRPTW Problem Description

This document describes the **QuickBite Fleet Scheduling** problem: a Vehicle Routing Problem with Time Windows (VRPTW) used for delivery fleet optimization. It covers the problem variables, constraints, and objective, and explains how the solver, evaluator, and reporter work.

---

## 1. Problem Description

### 1.1 Overview

QuickBite operates a delivery fleet that must serve 30 orders across five zones. Each order has a time window during which it should be delivered. The goal is to assign orders to vehicles and sequence each vehicle’s route to minimize a composite cost that includes travel time, fuel, time-window violations, capacity overflow, workload imbalance, driver preferences, and express-order lateness.

### 1.2 Geography and Zones

The city has **one depot** and **five delivery zones**:

| Index | Zone Name | Description |
|-------|-----------|-------------|
| 0 | Depot (Central) | Starting/ending point for most vehicles |
| 1 | A (Riverside) | Delivery zone |
| 2 | B (Harbor) | Delivery zone |
| 3 | C (Uptown) | Delivery zone |
| 4 | D (Westgate) | Delivery zone (has roadworks 08:00–12:00) |
| 5 | E (Northgate) | Delivery zone |

**Base travel time matrix** (minutes, symmetric):

```
         Depot   A     B     C     D     E
Depot  [  0,    12,   18,   25,   30,   22  ]
A      [ 12,     0,    8,   15,   20,   14  ]
B      [ 18,     8,    0,   10,   18,   12  ]
C      [ 25,    15,   10,    0,    9,   11  ]
D      [ 30,    20,   18,    9,    0,    7   ]
E      [ 22,    14,   12,   11,    7,    0   ]
```

### 1.3 Traffic and Travel Time

Travel times vary by time of day and conditions:

- **Traffic multipliers** (applied to base matrix):
  - Period 1 (07:00–09:30): 1.4× (morning peak)
  - Period 2 (09:30–11:30): 1.0× (normal)
  - Period 3 (11:30–13:00): 1.3× (lunch surge)
  - Period 4 (13:00–16:00): 1.0× (normal)
  - Period 5 (16:00–18:00): 1.5× (evening peak)

- **Zone D roadworks** (08:00–12:00): add 5 minutes to any trip involving Zone D, regardless of traffic period.

- **Stochastic noise**: final travel time multiplied by Uniform(0.9, 1.1), using a seeded RNG for reproducibility.

`get_travel_time(from_zone, to_zone, current_time_minutes, rng)` in `traffic_api.py` implements this logic.

### 1.4 Vehicles

Five vehicles with different capacities, start locations, and shift start times:

| ID | Name | Capacity | Start Zone | Shift Start | Max Hours |
|----|------|----------|------------|-------------|-----------|
| 0 | Alice | 22 | Depot (0) | 08:00 | 8h |
| 1 | Bob | 20 | Depot (0) | 08:00 | 8h |
| 2 | Carol | 20 | Depot (0) | 09:00 | 8h |
| 3 | Dave | 22 | Depot (0) | 08:00 | 8h |
| 4 | Eve | 20 | Zone E (5) | 09:30 | 8h |

- **Capacity** is in units; total load per route must not exceed it (soft constraint via penalty).
- **Shift start**: vehicle cannot depart before this time.
- **Max hours**: shift cannot exceed 8 hours (hard penalty if violated).
- **Compensation and fairness**: drivers are assumed to be salaried (or compensated under a pooled/guaranteed-hours scheme), so the scheduler aims to keep routes operationally efficient while maintaining fair workloads across drivers.
- **Driver preferences**: some vehicles have soft preferences (see §1.6), such as Alice disliking Zone D stops, Carol disliking many express orders, and Dave disliking very long shifts.

### 1.5 Orders

30 orders are generated deterministically with `generate_orders(seed=0)`. Each order has:

| Variable | Type | Description |
|----------|------|-------------|
| `order_id` | str | O00 … O29 |
| `zone` | int | 1–5 (delivery zone) |
| `size` | int | 1–5 units (from [1, 2, 3, 4, 5]) |
| `priority` | str | `"express"` or `"standard"` |
| `time_window_open` | int | Minutes since midnight (08:00–14:00, 30‑min slots) |
| `time_window_close` | int | `time_window_open` + duration in [60, 90, 120, 150] |
| `service_time` | int | 15 min (express) or 10 min (standard) |

- Express orders have higher late-delivery penalty.
- With `seed=0`, total demand is 88 units; vehicle capacities sum to 104, so feasible solutions exist.

**Canonical sample order list (seed=0)** — this exact set is used in all demos and research scripts:

```
ID     Zone   Size   Priority   Window Open    Window Close   Svc
----------------------------------------------------------------------
O00    E      1      standard   09:30          12:00          10
O01    B      4      standard   10:00          12:30          10
O02    A      1      standard   08:30          10:30          10
O03    A      2      standard   12:00          13:30          10
O04    E      4      standard   10:30          12:30          10
O05    A      3      standard   08:30          11:00          10
O06    D      4      express    08:00          09:30          15
O07    B      2      standard   13:00          14:00          10
O08    D      4      standard   14:00          16:00          10
O09    A      1      standard   10:30          12:30          10
O10    A      5      standard   10:00          11:30          10
O11    C      3      standard   08:30          10:00          10
O12    B      2      standard   11:30          14:00          10
O13    C      4      standard   09:30          11:00          10
O14    E      2      express    13:30          14:30          15
O15    E      5      express    10:00          11:00          15
O16    A      5      express    11:30          14:00          15
O17    A      2      standard   09:30          10:30          10
O18    A      2      standard   09:00          10:00          10
O19    D      3      standard   08:00          10:30          10
O20    B      1      standard   13:30          15:30          10
O21    D      3      standard   09:30          11:30          10
O22    D      4      standard   09:30          10:30          10
O23    B      3      standard   12:30          14:30          10
O24    B      5      standard   13:30          14:30          10
O25    D      3      express    08:00          10:00          15
O26    A      4      standard   09:30          10:30          10
O27    E      1      standard   12:00          13:30          10
O28    C      4      standard   13:30          15:00          10
O29    A      1      standard   12:00          14:00          10
```

Here `Svc` is the **per-stop service time in minutes**, determined by `priority`:

- Standard orders: `service_time = 10` minutes
- Express orders: `service_time = 15` minutes

In route simulation:

- Travel time comes from `get_travel_time(…)` and is added to the clock.
- If the vehicle arrives **before** `Window Open`, it waits until `Window Open`.
- Then `Svc` is added to the clock to obtain the **departure** time.
- **Time-window violations and express lateness are based on arrival vs. `Window Close` only** (not on when service finishes), but the service time contributes to shift duration and therefore to workload variance and hard shift penalties.

### 1.6 Objective Function

Cost is a weighted sum of:

| Term | Weight | Description |
|------|--------|-------------|
| w1 | 1.0 | Total travel time (minutes) |
| w2 | 0.15 | Fuel cost (proxy: travel time) |
| w3 | 50.0 | Time-window violation penalty (per minute late) |
| w4 | 1000.0 | Capacity overflow penalty (per unit) |
| w5 | 10.0 | Workload fairness penalty (shift duration variance across vehicles) |
| w6 | 1.0 | Driver preference penalties |
| w7 | 100.0 | Express lateness penalty (per late express order) |
| — | 5000 | Hard penalty per vehicle exceeding 8h shift |

**Driver preference penalties** (soft):

- Alice: +8 min per Zone D stop
- Carol: +5 min per express order
- Dave: +15 min if shift exceeds 6.5h

### 1.7 Constraints

- **Hard**: Each order served exactly once; shift ≤ 8h (heavily penalized).
- **Soft**: Capacity, time windows, express lateness, driver preferences (all penalized in cost).

---

## 2. User Study: Elicited Specifications and Official Evaluation

In the 2×2 user study (experts vs novices × agile vs waterfall workflow), participants articulate the problem via chat with a metaheuristic optimization chatbot. The chatbot maps their statements to a user config that drives the optimizer. **Official evaluation** scores both the **problem formulation** (what they specified) and the **results** (the solution they obtain).

### 2.1 Elicited Specifications

| Specification | Maps to | Notes |
|---------------|---------|-------|
| **Objective priorities** | `weights` (w1–w7) | User may specify only some terms; `only_active_terms: true` zeros the rest |
| **Trade-offs** | `weights` | e.g. "prioritize on-time delivery" → higher w3, w7 |
| **Hard constraints** | `shift_hard_penalty`, `locked_assignments` | Shift limit (always enforced); locked assignments (order X → vehicle Y) |
| **Soft constraints** | `weights` + `driver_preferences` | Capacity (w4), time windows (w3), express (w7), workload (w5), driver prefs (w6) |
| **Locked assignments** | `locked_assignments` | e.g. `{"6": 0}` = order O06 must go with Alice |
| **Driver preferences** | `driver_preferences` | Rules: zone_d, express_order, shift_over_hours |
| **Algorithm** | `algorithm` | Optional: GA, PSO, SA, SwarmSA, or ACOR (default GA) |
| **Algorithm params** | `algorithm_params` | Optional: GA (pc, pm), PSO (c1, c2, w), SA (temp_init, cooling_rate), SwarmSA (max_sub_iter, t0, t1, move_count, mutation_rate, mutation_step_size, mutation_step_size_damp), ACOR (sample_count, intent_factor, zeta) |
| **Run params** | `epochs`, `pop_size` | Optional solver params |

**Not specified by the user** (fixed): Geography, zones, travel matrix, vehicles, order list.

### 2.2 User Input: What the Chatbot Produces

The chatbot writes user config as JSON (e.g. `data/user_*.json`), loaded by `load_user_input()`:

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

- **weights** + **only_active_terms**: user-defined objective terms; unspecified terms are 0 when `only_active_terms` is true.
- **hard_constraints** / **soft_constraints**: inferred from what the user specified, or set explicitly.

### 2.3 Official Evaluation: Formulation and Results

The **official evaluator** (`researcher/official_evaluator.py`) evaluates both:

**A. Problem formulation** — How well the user specified the problem:

| Metric | Description |
|--------|-------------|
| `hard_constraints_defined` | Which hard constraints the user articulated (shift_limit, locked_assignments) |
| `soft_constraints_defined` | Which soft constraints (travel_time, tw_violation, capacity, etc.) |
| Formulation completeness | Number of soft constraint terms with non-zero weight (1–7) |
| Formulation alignment | (Optional) Similarity of user weights to canonical weights |

**B. Results** — Quality of the solution obtained:

| Metric | Description |
|--------|-------------|
| **Official cost** | Score under canonical objective (full 7 terms + defaults) — lower is better |
| **User cost** | Score under user's objective — measures fit to their stated goals |
| **Hard constraint satisfaction** | All orders covered, no duplicates, shifts ≤ 8h, locked assignments obeyed |
| **Soft constraint violations** | TW violations, capacity overflow, express lateness counts |

`full_official_evaluation(routes, user_config, ...)` returns all of the above. Use `python -m researcher.run_user_comparison` from the `vrptw-problem` directory to run the optimizer for sample users and print the official report.

---

## 3. Solver (Optimizer)

The **solver** (`optimizer.py`) wraps metaheuristic algorithms from [mealpy](https://mealpy.readthedocs.io/) to search for low-cost route assignments.

### 3.1 Solution Encoding (`encoder.py`)

Solutions are represented as **permutations with vehicle separators**:

- **Position vector**: 34 real values in [0, 34] (30 order indices + 4 separators).
- **Decoding**: argsort yields a permutation; the four smallest positions act as separators, splitting the permutation into five vehicle routes.
- **Locked assignments**: `{order_idx: vehicle_idx}` can force certain orders onto certain vehicles; these override the decoded routes.

### 3.2 QuickBiteOptimizer

- **Input**: `weights`, `locked_assignments`, `seed`.
- **Methods**: `solve(algorithm, params, epochs, pop_size)`.
- **Supported algorithms**: GA (Genetic Algorithm), PSO (Particle Swarm), SA (Simulated Annealing), SwarmSA (Swarm Simulated Annealing), ACOR (Ant Colony Optimization).

For each candidate position vector, the optimizer calls the evaluator’s objective; mealpy minimizes that cost.

### 3.3 SolverConfig and SolveResult

- **SolverConfig**: JSON-serializable configuration (weights, locked assignments, algorithm, epochs, pop_size, seed).
- **SolveResult**: `best_cost`, `routes` (list of 5 lists of order indices), `metrics`, `convergence`, `runtime`, `algorithm`.

---

## 4. Evaluator

The **evaluator** (`evaluator.py`) turns a solution into a cost and metrics.

### 4.1 Route Simulation (`simulate_routes`)

For each vehicle in order:

1. Start at its `start_zone` at its `shift_start_min`.
2. For each order on the route:
   - Travel to order zone using `get_travel_time(…)` (depends on current time).
   - Arrive; wait if before `time_window_open`.
   - Add `service_time`; update load.
   - Compute time-window violation (minutes late) and capacity overflow.
   - Apply driver preference penalties.
3. Return to depot.
4. Record shift duration.

### 4.2 Cost Calculation

Cost is computed as:

```
cost = w1×travel_time + w2×fuel_cost + w3×tw_violation_min
     + w4×capacity_overflow + w5×workload_variance
     + w6×driver_penalty + w7×express_late_count
     + shift_hard_penalty
```

### 4.3 `evaluate_solution`

- Decodes the position vector into routes (via `decode_solution`).
- Runs `simulate_routes` on those routes.
- Returns `(cost, metrics_dict, visits_per_vehicle)`.

`metrics_dict` includes: `travel_time`, `fuel_cost`, `tw_violation_min`, `tw_violation_count`, `capacity_overflow`, `workload_variance`, `driver_penalty`, `express_late_count`, `shift_hard_penalty`, `shift_durations`.

---

## 5. Reporter

The **reporter** (`reporter.py`) formats results for display and downstream visualization.

### 5.1 `get_gantt_data(result, random_seed=42)`

- Re-simulates the solution’s routes with the given seed.
- Returns a list of visit records suitable for Gantt charts:
  - `vehicle_id`, `vehicle_name`, `order_id`, `zone`
  - `arrival_time`, `departure_time` (minutes since midnight)
  - `window_open`, `window_close`
  - `is_express`, `is_violation`

### 5.2 `print_report(result, random_seed=42)`

- Re-simulates routes and prints:
  - Cost breakdown (travel, fuel, TW violations, capacity overflow, etc.)
  - Per-vehicle route summary (order sequence, load, shift length, zones)
  - Workload balance (shift durations and variance)

---

## 6. File Summary

| File | Role |
|------|------|
| `traffic_api.py` | Simulated traffic/travel time API: base matrix, traffic multipliers, roadworks, `get_travel_time` |
| `vehicles.py` | Vehicle definitions (capacity, start zone, shift start) |
| `orders.py` | Order dataclass, `generate_orders`, `get_orders`, `load_default_orders`, `save_default_orders` |
| `user_input.py` | Objective weights, driver preferences, hard/soft constraints, locked_assignments |
| `encoder.py` | Position-vector encoding/decoding, locked assignments |
| `evaluator.py` | Route simulation, cost, metrics |
| `optimizer.py` | Mealpy wrapper, GA/PSO/SA/SwarmSA/ACOR |
| `reporter.py` | Gantt data, formatted report |
| `basic_demo.py` | Basic demo: run all 5 algorithms, validate, compare |
| `researcher/visualize_convergence.py` | Fair comparison: plot convergence for GA, PSO, SA, SwarmSA, ACOR |
| `researcher/official_evaluator.py` | Official evaluation: formulation + results |
| `researcher/run_user_comparison.py` | Run optimizer for sample users, print official evaluation |
| `researcher/visualize_zone_map.py` | Generate fake city map of delivery zones (demonstration) |
