# Optimization Literacy Instrument

A short instrument that measures a participant's conceptual understanding of optimization. Administered alongside the [scheduling literacy screener](SCHEDULING_LITERACY.md) as part of a single screening survey, completed by candidates before the main session is scheduled. The two instruments share a survey but serve different roles: scheduling literacy gates participation; optimization literacy is recorded for everyone who completes both sections and used as a covariate.

**This is a measurement instrument, not a gate.** The score (0–5) is recorded as a continuous covariate and used as a moderator in analysis. Low scorers are not excluded — they are part of the study. One of the questions the study can answer is whether (and how) the interface and a brief pre-session orientation together carry low-literacy stakeholders through a meaningful task.

The five items test conceptual reasoning, not vocabulary or programming:

| Q | Concept | Why it matters for the interface |
|---|---------|----------------------------------|
| 1 | Hard constraints | Understanding why a run is gated, why a result reports "violations" |
| 2 | Multi-objective trade-offs | The whole weight-tuning loop |
| 3 | Local vs. global optima | Why re-runs and tweaks matter |
| 4 | Stochasticity | Not panicking when re-runs differ |
| 5 | Model vs. reality | The basis for any meaningful critique of the artifact |

---

## Q1. Hard Constraint

A solution is considered valid only if all required (i.e., hard) constraints are satisfied.

Your program finds a solution, but one required constraint is violated.

Is the solution valid?

- A. Yes
- B. No
- C. There is not enough information

---

## Q2. Multi-Objective Trade-off

Your program finds a solution that improves one objective but worsens another.

What determines whether it is better?

- A. It is always better
- B. It is always worse
- C. It depends on how the objectives are prioritized

---

## Q3. Local vs. Global

A change in the program configuration slightly improves the solution.

What can you conclude?

- A. The overall best solution has been found
- B. The change should be rejected
- C. The solution may still be improved further

---

## Q4. Optimization Results

You run the same optimization method multiple times with the same settings. The results are slightly different each time.

What is the best explanation?

- A. The method is incorrect
- B. The method may involve randomness or different search paths
- C. The problem has no valid solution

---

## Q5. Model vs. Reality

An optimization program finds the solution with the highest score according to its scoring formula. However, in practice, this solution may still not work well.

Why?

- A. The program made a calculation error
- B. The scoring formula may not fully capture what matters in real life
- C. The solution violates a required condition

---

## Scoring Key — do not show participants

Score is the count of correct answers, range 0–5. **Not used as a gate.**

| Q | Correct | What a wrong answer indicates |
|---|---------|-------------------------------|
| 1 | **B** | Confusing hard constraints with soft penalties; may not understand why the AI sometimes refuses to run. |
| 2 | **C** | Treating "improvement" as absolute; will likely struggle with weight tuning. |
| 3 | **C** | Confusing local progress with global optimality; may stop iterating prematurely. |
| 4 | **B** | Treating randomness as a bug; may distrust the system inappropriately. |
| 5 | **B** | Treating the model as ground truth; will not produce useful critique of the artifact. |

---

## Notes for administration

- Administered as part of a single screening survey alongside the scheduling literacy screener; both sections are completed in one sitting before the main session is scheduled.
- Record raw score (0–5) per participant. Do **not** use it to exclude.
- Optionally re-administer **after the optimization-orientation step** in the main session, so the post-onboarding score is captured as well — closer to the condition real users would be in. The pre/post pair lets you measure the orientation's effect on conceptual literacy.
- Optionally re-administer at the end of the session as well, to measure delta from baseline across the whole experience — a non-trivial increase would be evidence that the interface itself communicates optimization concepts to participants.

## Cross-references

- Gate screener: [`SCHEDULING_LITERACY.md`](SCHEDULING_LITERACY.md)
- Study design (where this covariate is used): [`../.study_plan/STUDY_DETAILED_PLAN.md`](../.study_plan/STUDY_DETAILED_PLAN.md)
