# Binary Knapsack Optimization — Problem Description

This document describes the **Toy Binary Knapsack** problem: a classic optimization benchmark used in the MOPT system. It covers the problem variables, constraints, objectives, and how the solver and evaluator interact.

---

## 1. Problem Overview

The knapsack problem is a fundamental challenge in combinatorial optimization. Given a set of items, each with a specific **weight** and **value**, the goal is to select a subset of items to include in a "knapsack" such that:
1. The total weight stays within a defined **capacity**.
2. The total value is **maximized**.

In this implementation, the problem is framed as a **minimization** task to align with the metaheuristic algorithms (GA, PSO, etc.) which seek to find the "lowest cost" configuration.

### 1.1 Instance Details (Suitcase Scenario)
The study uses a fixed "Suitcase" instance with the following properties:

- **Total Items**: 22
- **Capacity**: 50 units (Soft Constraint)
- **Item Generation**: Deterministic using Seed 0.
  - **Weights**: Randomly assigned between 3 and 12 units.
  - **Values**: Randomly assigned between 5 and 25 points.

---

## 2. Objective Function

The optimizer minimizes a composite **cost** function. This cost is a weighted sum of three primary terms, representing the trade-offs between value, capacity, and sparsity.

### 2.1 Optimization Terms

| Weight Key | Concept | Description |
|------------|---------|-------------|
| `value_emphasis` | **Profit Maximization** | Rewards selecting high-value items. Expressed as a negative term: `- (total_value / max_possible_value) * 100`. |
| `capacity_overflow`| **Capacity Constraint** | Penalizes any weight exceeding the 50-unit limit. |
| `selection_sparsity`| **Sparse Selection** | (Optional) Penalizes the number of items selected, encouraging a "lighter" knapsack. |

### 2.2 Cost Calculation
The total cost is calculated as:
`cost = w(value) * value_term + w(overflow) * overflow + w(sparsity) * n_selected`

- **Default Weights**:
  - `value_emphasis`: 1.0 (Primary goal)
  - `capacity_overflow`: 50.0 (Strong penalty for exceeding limit)
  - `selection_sparsity`: 0.5 (Minor tie-breaker/preference)

---

## 3. Implementation Details

### 3.1 Encoding
The problem uses a **Binary Vector Encoding** of length 22.
- `[1, 0, 1, 1, ...]` represents a selection where item 0 is IN, item 1 is OUT, item 2 is IN, etc.
- Continuous algorithms (like PSO) work with real numbers [0, 1], which are rounded to the nearest integer (0.5 threshold) during evaluation.

### 3.2 Constraints
- **Hard Constraints**: None. Every 22-bit binary string is a valid search point.
- **Soft Constraints**: The 50-unit weight limit. Feasibility is determined by whether `total_weight <= capacity`.

### 3.3 Study Context
In the 2×2 user study, participants interact with a chatbot to refine these weights (`value_emphasis`, `capacity_overflow`, etc.) and choose optimization algorithms. The chatbot translates their natural language requirements into JSON patches that update the solver's configuration.

---

## 4. File Summary

| File | Description |
|------|-------------|
| [instance.py](file:///c:/Users/whyhowie/git-repo/mopt-bot/knapsack_problem/instance.py) | Defines the items (weights/values) and the capacity constant. |
| [evaluator.py](file:///c:/Users/whyhowie/git-repo/mopt-bot/knapsack_problem/evaluator.py) | Contains the `evaluate_selection` logic and cost function. |
| [mealpy_solve.py](file:///c:/Users/whyhowie/git-repo/mopt-bot/knapsack_problem/mealpy_solve.py) | Wraps the mealpy optimization library for binary vectors. |
| [panel_schema.py](file:///c:/Users/whyhowie/git-repo/mopt-bot/knapsack_problem/panel_schema.py) | JSON schema for structured updates to the knapsack problem settings. |
| [study_prompts.py](file:///c:/Users/whyhowie/git-repo/mopt-bot/knapsack_problem/study_prompts.py) | LLM instructions for context-aware chat about knapsack optimization. |
| [brief_seed.py](file:///c:/Users/whyhowie/git-repo/mopt-bot/knapsack_problem/brief_seed.py) | Logic meant to parse a "Problem Brief" into an initial solver configuration. |
