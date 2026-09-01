---
name: pretask-predictors-quiz-finding
description: Warm-up quiz (5 MCQs in pre-task survey) is the one significant individual-difference predictor of formulation quality; goal-description tags are null; user plans to circle back
metadata:
  type: project
---

Analysis of pre-task predictors of study outcomes (Aug 2026, n=28 valid sessions):

- **Warm-up quiz score** (5 scenario MCQs in the pre-task survey `data_json`;
  correct answers are the "No — a required constraint is violated" /
  "prioritized against each other" / "may still be improved further" /
  "randomness" / "may not fully capture" options) is the only significant
  individual-difference predictor found: quiz → final soft-preference coverage
  rho=+0.47 p=.013; → final canonical coverage rho=+0.39 p=.040. Survives
  controlling for workflow mode (OLS quiz b=+0.50 p=.029, mode b≈0).
  Self-rated expertise, confidence, experience word count, initial prompt
  length: all null. Sellable contrast: measured conceptual understanding, not
  self-report, predicts formulation completeness (esp. the discretionary soft
  side; hard constraints are captured by nearly everyone).
- Distribution: 14× 5/5, 12× 4/5, 2× 3/5 (P19, P29). Quiz imbalanced across
  modes (waterfall 10/14 perfect vs agile 4/14) — always control for mode.
- **Advisor's hypothesis is null**: the "Correct / mentioning travel time"
  goal-description tag (Miscellaneous Manual Data Tags - Pre-Task.csv) does not
  predict any outcome (all p>.3, robust to relabeling; doesn't even predict
  objective_bonus, Fisher p=1.0). Composites of quiz + goal tags DILUTE the
  quiz signal (goal_ord even trends negative on final_form_score) — report
  quiz alone, keep goal tags descriptive.
- The empty "Warm-Up Quiz Score" CSV column can be filled from scored survey
  answers; scripts + merged data live in the session scratchpad
  (build_metrics.py, analyze*.py — canonical/formulation metrics recomputed
  via VrptwStudyPort port hooks on mopt_analysis.db).
- User plans to circle back to incorporating quiz calculation into the
  analysis pipeline (likely a notebook cell in the aggregate tab).

Related: [[coverage-canonical-only]], [[session-coding-scheme]]
