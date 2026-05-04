# Optimization Literacy Instrument

A short instrument that measures a participant's conceptual understanding of optimization. Administered at the **start of the main session, immediately after consent and before any study materials are shown** (no orientation video, no stance framing, no task briefing yet), so the participant has not been exposed to language or framing that could prime concept recognition. Takes ~2 minutes; not used as a gate.

**This is a measurement instrument, not a gate.** The score (0–5) is recorded as a continuous covariate and used as a moderator in analysis. Low scorers are not excluded — they are part of the study.

The five items test conceptual reasoning by asking the participant to **apply** the relevant idea to a short scenario, not to recognize a definition. They do not require optimization vocabulary or programming.

| Q | Concept | Why it matters for the interface |
|---|---------|----------------------------------|
| 1 | Hard requirement vs. soft goal | Understanding why a run is gated, why a result reports "violations" |
| 2 | Multi-objective trade-offs | The whole weight-tuning loop |
| 3 | Local vs. global optima | Why re-runs and tweaks matter |
| 4 | Stochasticity | Not panicking when re-runs differ |
| 5 | Model vs. reality | The basis for any meaningful critique of the artifact |

---

## Q1. Hard requirement vs. soft goal

A delivery company sets up an optimizer with two requirements:

- **Capacity rule:** No vehicle may exceed 1,000 lbs of cargo. The dispatcher marks this as a strict requirement that must never be violated.
- **Cost goal:** Minimize total fuel cost.

The optimizer returns a plan with the lowest fuel cost it could find, but one vehicle in the plan carries 1,050 lbs.

Should this plan be accepted?

- A. Yes — fuel cost was the goal, and this is the lowest the optimizer could achieve.
- B. No — a strict requirement was violated.
- C. Yes, provided the overage is small relative to capacity.

---

## Q2. Multi-objective trade-off

A scheduler compares two delivery plans for the same day:

- **Plan A:** All express orders are delivered on time, but total fuel use is 15% higher.
- **Plan B:** Total fuel use is lower, but two express orders are delivered late.

Which plan is better?

- A. Plan A — meeting express deadlines always outweighs saving fuel.
- B. Plan B — when fuel cost is lower by a clear margin, it's the better choice.
- C. It depends on how the express-order deadlines are weighted against fuel cost.

---

## Q3. Local vs. global

You run an optimizer and get cost 120. You change one search setting, run again, and get cost 118.

What can you conclude?

- A. The current setup has found the best possible answer; further runs aren't worthwhile.
- B. The improvement is small enough to be considered noise.
- C. There may still be room for a lower cost with more runs or different settings.

---

## Q4. Stochasticity

You run an optimizer twice with **identical inputs and identical settings**. The two results differ slightly in cost.

What is the most likely explanation?

- A. The implementation has a bug — identical inputs should always produce identical outputs.
- B. The search method explores possibilities in a partly random order, so different runs may take different paths.
- C. The data or settings must have changed without you noticing.

---

## Q5. Model vs. reality

An optimizer returns a delivery schedule with the lowest possible cost for the model. The dispatch team rejects it because it requires parking on a street that's almost never available in the afternoon — a detail that was not captured in the model.

Why did this happen?

- A. The optimization didn't actually find the lowest-cost schedule.
- B. The model's cost score didn't capture everything that matters in the real situation.
- C. The schedule is correct by the model's measure; the team's concern reflects a workflow problem, not a model problem.

---

## Scoring Key — do not show participants

Score is the count of correct answers, range 0–5. **Not used as a gate.**

| Q | Correct | What a wrong answer indicates |
|---|---------|-------------------------------|
| 1 | **B** | Treating a stated strict requirement as negotiable when the objective looks good (A) or as a soft penalty (C); may not understand why the interface treats some rules as run-blockers. |
| 2 | **C** | Generalizing a single domain heuristic into a universal rule (A or B); will likely struggle with weight tuning, where neither side dominates by default. |
| 3 | **C** | Confusing local progress with global optimality (A) or treating modest improvements as noise (B); may stop iterating prematurely. |
| 4 | **B** | Treating non-determinism as a bug (A) or misattributing variation to inputs that didn't change (C); may distrust the system inappropriately. |
| 5 | **B** | Defending the model when reality contradicts it (C) or blaming the optimizer's correctness (A); won't produce useful critique of the artifact. |

---

## Notes for administration

- **Single administration**, at the **start of the main session**, after consent has been obtained and **before any study materials, framing, or orientation are shown** (no stance framing, no orientation video, no task briefing yet). This protects against priming from the study's own language.
- Delivery method is flexible — a survey link the participant fills in silently, an on-screen poll, or a printed sheet — whichever fits the session format. Researcher records the score; do not show the scoring key.
- Budget ~2 minutes (5 multiple-choice items, no rationale required).
- Record raw score (0–5) per participant. Do **not** use it to exclude.
- This instrument is **not** part of the asynchronous screener; only [scheduling literacy](SCHEDULING_LITERACY.md) gates participation.

## Cross-references

- Asynchronous gate screener (separate): [`SCHEDULING_LITERACY.md`](SCHEDULING_LITERACY.md)
- Study design (where this covariate is used): [`../.study_plan/STUDY_DETAILED_PLAN.md`](../.study_plan/STUDY_DETAILED_PLAN.md)
- Session step that administers it: [`../.study_plan/SESSION_OPENING_SCRIPT.md`](../.study_plan/SESSION_OPENING_SCRIPT.md) §2
