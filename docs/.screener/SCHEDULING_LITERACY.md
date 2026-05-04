# Scheduling Literacy Screener

A short pre-study screener that establishes whether a candidate participant can reason about scheduling trade-offs. Used as the **gate** for participation: candidates must score ≥4/5 to be invited.

The questions deliberately use a **non-VRPTW** scenario (small-business shift scheduling) so candidates are not pre-exposed to the actual study task. They test conceptual reasoning — not optimization vocabulary, not programming. Anyone who can articulate "this trades off X against Y" can pass; nobody needs to know what a metaheuristic is.

This is the **only** instrument administered in the asynchronous screener. The [optimization literacy instrument](OPTIMIZATION_LITERACY.md), which measures conceptual optimization understanding for use as a covariate, is administered separately at the start of the main session (post-consent, pre-materials) — not here.

---

## Scenario (shown once at the top of the screener)

You manage a small bookstore that needs a weekly shift schedule. You have several part-time staff, each with different availability, skills (e.g., cashier, stockroom, customer-help), and shift preferences. The store is open seven days a week and busier on weekends. Below are five short questions about how you'd think about scheduling decisions in this kind of setting.

---

## Q1. Preferences vs. capacity

Two staff members both want the Saturday morning shift, which only needs one person.

Which is true?

- A. The schedule is invalid until both are given the shift.
- B. The scheduler must pick one; the other has an unmet preference, but the schedule is still valid.
- C. The schedule cannot be made.

---

## Q2. Competing goals

You can give every staff member their preferred shifts, but the result leaves all three of your most experienced staff on the same single day, with weaker coverage on other days.

What can you conclude?

- A. This is the best possible schedule because everyone got their preference.
- B. There is a trade-off between satisfying preferences and balancing skill coverage across days.
- C. The schedule is invalid.

---

## Q3. Context-dependent priorities

The store has to choose between (i) keeping individual shifts short to reduce staff fatigue and (ii) covering every customer-facing slot during opening hours.

Which is true?

- A. Coverage is always more important than fatigue.
- B. Staff fatigue is always more important than coverage.
- C. Which one matters more depends on what the store is currently prioritizing.

---

## Q4. Multiple dimensions of fairness

One staff member is consistently scheduled on the busiest, most demanding shifts; another is consistently scheduled on the quietest. Their total weekly hours are exactly equal.

What can you conclude?

- A. The schedule is fair because hours are equal.
- B. The schedule may still feel unfair, because workload intensity isn't balanced even though hours are.
- C. The schedule is invalid.

---

## Q5. Rules vs. real outcomes

A proposed schedule satisfies every written rule (availability, max hours, required coverage). A staff member still says it doesn't work for them in practice.

What's the most likely explanation?

- A. The staff member is wrong; the schedule is fine.
- B. The written rules may not capture everything that matters in practice (e.g., commute, child-care timing, energy across shifts).
- C. The schedule must contain a hidden error somewhere.

---

## Scoring Key — do not show participants

Pass threshold: **≥4 of 5 correct.**

| Q | Correct | What it tests |
|---|---------|---------------|
| 1 | **B** | Distinguishing capacity (hard) from preferences (soft); not every unmet preference invalidates a solution. |
| 2 | **B** | Recognizing that two desirable goals can pull against each other — the core of multi-objective reasoning. |
| 3 | **C** | Recognizing that priority weights are contextual, not universal. Maps directly to the weight-tuning behavior the interface elicits. |
| 4 | **B** | Recognizing that fairness has multiple axes; "equal hours" doesn't mean "equally fair." Maps to workload-variance and driver-preference penalties in the actual task. |
| 5 | **B** | Recognizing that the formal model is a simplification; a "valid" schedule can still fail in reality. This is the conceptual basis for any meaningful critique of the artifact. |

Candidates who select A on Q5 or A on Q4 are particularly poor fits — those answers indicate a "rules-only" view of scheduling that won't engage productively with the open-ended critique we want.

---

## Notes for administration

- Administered as a short asynchronous screener completed before the main session is scheduled. No time pressure.
- This is the **gate**: candidates scoring ≥4/5 are eligible for the study. Do **not** explain correct answers if a candidate fails; thank them and end the screening.
- Optimization literacy is **not** part of this screener. It is administered at the start of the main session, post-consent and before any study materials, as a covariate (see [OPTIMIZATION_LITERACY.md](OPTIMIZATION_LITERACY.md)).
- If the candidate pool turns out to be uniformly high-scoring, consider adding one open-ended item ("Describe a trade-off you'd expect in scheduling problems") to differentiate further.
