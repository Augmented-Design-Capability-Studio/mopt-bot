# Agile vs Waterfall (Study Manipulation)

This study keeps the workflow manipulation intentionally small and controlled.

## Four primary differences

1. **Run availability**
   - **Agile:** Run button is available early once intrinsic readiness is met.
   - **Waterfall:** Runs are gated until open questions are resolved.

2. **Definition emphasis**
   - **Agile:** Assumptions are emphasized as a practical way to move forward.
   - **Waterfall:** Open questions are emphasized and expected to be resolved before running. The Definition should store **no assumption rows** in Waterfall (uncertainty is tracked as open questions until confirmed).

3. **Post-run focus**
   - **Agile:** After each run, the assistant focuses on one assumption-driven next refinement.
   - **Waterfall:** After each run, the assistant focuses on clarifying unresolved questions and specification quality.

4. **Formulation behavior**
   - **Agile:** Assume-and-adjust pattern (state a reasonable assumption, then refine after results).
   - **Waterfall:** Ask-before-assume pattern (confirm missing values before adding new terms).

## Minimal analysis support (concise)

- **Condition-aware logging:** keep `workflow_mode` on all key events (message, brief update, run, config save) with timestamps for time-to-first-run and inter-run timing.
- **Manipulation check:** include one post-task item asking whether the participant used a specification-first or run-early iterative strategy.
