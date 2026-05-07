# Optimization Literacy Warm-up

A short conceptual warm-up administered at the **start of the main session, after consent and the background self-report, but before stance framing or any orientation material**. Takes ~2 minutes; not used as a gate.

**This is a warm-up, not a measurement instrument.** Primary expertise signal comes from the separate background self-report (years of experience, coursework, solver use, self-rated confidence). The 0–5 score here is recorded as a secondary background signal — useful as a soft check on the self-report, not as the primary covariate. Low scorers are not excluded.

Each item carries an explicit **"I'm not sure"** option so participants who don't recognize a concept can opt out rather than guess. This keeps the warm-up consistent with the broader design choice of routing conceptual questions to the in-session AI agent rather than front-loading definitions. The five items ask the participant to **apply** a concept to a short scenario, not to recognize a definition. They do not require optimization vocabulary or programming.

---

## Participant-facing framing (shown before Q1)

> Below are five short questions designed as a conceptual warm-up about computational optimization methods. Their purpose is to give us a preliminary sense of how you currently think about these problems — **your compensation is not tied to your responses**, and there's no need to worry about giving "wrong" answers. Each item also has an **"I'm not sure"** option; please pick it freely whenever a question references something you don't recognize, rather than guessing. Otherwise, choose the answer that best matches your honest intuition.

| Q | Concept | Why it matters for the interface |
|---|---------|----------------------------------|
| 1 | Hard requirement vs. soft goal | Understanding why a run is gated, why a result reports "violations" |
| 2 | Multi-objective trade-offs | The whole weight-tuning loop |
| 3 | Local vs. global optima | Why re-runs and tweaks matter |
| 4 | Stochasticity | Not panicking when re-runs differ |
| 5 | Model vs. reality | The basis for any meaningful critique of the artifact |

---

## Q1. Hard constraint

A solution is considered valid only if all required (i.e., hard) constraints are satisfied. Your program finds a solution that scores extremely well on every objective, but one required constraint is violated by a small amount.

Is the solution valid?

- A. Yes — the violation is small, and the objective scores are excellent.
- B. No — a required constraint is violated.
- C. There is not enough information to decide.
- D. I'm not sure.

---

## Q2. Multi-objective trade-off

Your program finds a new solution that improves one objective but worsens another.

What determines whether the new solution is better than the previous one?

- A. It is always better, because it improved on at least one objective.
- B. It is always worse, because it made another objective worse.
- C. It depends on how the objectives are prioritized against each other.
- D. I'm not sure.

---

## Q3. Local vs. global

You run your program and get a solution. You change one configuration setting, run it again, and the new solution is slightly better than the previous one.

What can you conclude?

- A. The overall best possible solution has now been found.
- B. The change should be rejected because the improvement is too small to trust.
- C. The solution may still be improved further by additional runs or different settings.
- D. I'm not sure.

---

## Q4. Stochasticity

You run the same optimization method multiple times with **identical inputs and identical settings**. The results are slightly different each time.

What is the best explanation?

- A. The method is incorrect — identical inputs should always produce identical outputs.
- B. The method may involve randomness or explore different search paths on different runs.
- C. The problem has no valid solution, so the method is returning arbitrary results.
- D. I'm not sure.

---

## Q5. Model vs. reality

An optimization program finds the solution with the highest score according to its scoring formula. However, in practice, this solution may still not work well.

Why?

- A. The program made a calculation error when computing the score.
- B. The scoring formula may not fully capture what matters in real life.
- C. The solution must violate a required condition; otherwise, it would work in practice.
- D. I'm not sure.

---

## Scoring Key — do not show participants

Score is the count of correct answers, range 0–5. Recorded as background context alongside the self-report. **Not used as a gate.**

**Handling "I'm not sure" (option D).** A "not sure" response is **not counted as correct** — it does not contribute to the 0–5 score. It is, however, **recorded distinctly from a wrong answer**, so post-hoc analysis can separate *honestly unfamiliar* from *confidently wrong* responses. Track this as either a per-participant "not sure" count or a per-item flag, depending on the survey tool used.

| Q | Correct | What a wrong answer indicates |
|---|---------|-------------------------------|
| 1 | **B** | Treating a stated strict requirement as negotiable when the objective looks good (A) or as a soft penalty (C); may not understand why the interface treats some rules as run-blockers. |
| 2 | **C** | Generalizing a single domain heuristic into a universal rule (A or B); will likely struggle with weight tuning, where neither side dominates by default. |
| 3 | **C** | Confusing local progress with global optimality (A) or treating modest improvements as noise (B); may stop iterating prematurely. |
| 4 | **B** | Treating non-determinism as a bug (A) or misattributing variation to inputs that didn't change (C); may distrust the system inappropriately. |
| 5 | **B** | Defending the model when reality contradicts it (C) or blaming the optimizer's correctness (A); won't produce useful critique of the artifact. |

---

## Notes for administration

- **Single administration**, at the **start of the main session**, after consent and the background self-report, and **before stance framing, orientation video, or task briefing**. The short framing paragraph at the top of this instrument is read by the participant as part of the quiz itself; no other study language should precede it.
- Delivery method is flexible — a survey link the participant fills in silently, an on-screen poll, or a printed sheet — whichever fits the session format. Researcher records the score; do not show the scoring key or discuss correct answers.
- Budget ~2 minutes (5 multiple-choice items, no rationale required).
- Record both the raw score (0–5) and the per-participant count (or per-item flags) of **"I'm not sure"** responses. Do **not** use either to exclude.
- This instrument is **not** part of the asynchronous screener; only [scheduling literacy](SCHEDULING_LITERACY.md) gates participation.

## Cross-references

- Asynchronous gate screener (separate): [`SCHEDULING_LITERACY.md`](SCHEDULING_LITERACY.md)
- Study design (where this covariate is used): [`../.study_plan/STUDY_DETAILED_PLAN.md`](../.study_plan/STUDY_DETAILED_PLAN.md)
- Session step that administers it: [`../.study_plan/SESSION_OPENING_SCRIPT.md`](../.study_plan/SESSION_OPENING_SCRIPT.md) §2
