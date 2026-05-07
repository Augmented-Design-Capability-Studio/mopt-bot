# Scheduling Literacy Screener

A short pre-study screener that establishes whether a candidate participant can reason about scheduling trade-offs. Used as the **gate** for participation: candidates must score ≥4/5 to be invited.

The questions deliberately use a **non-VRPTW** scenario (small-business shift scheduling) so candidates are not pre-exposed to the actual study task. They test conceptual reasoning — not optimization vocabulary, not programming. Anyone who can articulate "this trades off X against Y" can pass; nobody needs to know what a metaheuristic is.

This is the **only** instrument administered in the asynchronous screener. The [optimization literacy warm-up](OPTIMIZATION_LITERACY.md), a short conceptual warm-up administered separately at the start of the main session (post-consent, pre-materials), is not part of this screener.

## Purpose of this gate

The screener's job is **participation viability and reportable methodology** — not analytic variance. On a university recruitment pool, most candidates are expected to pass; that is by design. Specifically, the gate is doing two things:

1. **Filtering non-engagers.** A candidate who gets two or more of these five trade-off questions wrong tends to also struggle to hold the scheduler stance during a 30-minute role-play, or to produce a useful post-task critique. The **4/5 threshold is set at the point role-play viability falls off**, not at a point where any analytic distinction can be drawn.
2. **Providing a defensible inclusion criterion** for the methods section of any paper. *"All participants scored ≥4/5 on a 5-item scheduling-literacy instrument before being scheduled"* is a sentence reviewers accept without pushback; *"convenience-sample, no screener"* invites it.

The gate is **not** doing analytic work. With a hard pass threshold, screener scores are heavily range-restricted (effectively 4 vs. 5), so this score is not informative as a covariate or moderator in analysis. Optimization expertise is captured by the in-session background self-report (see study procedure), with the [optimization literacy warm-up](OPTIMIZATION_LITERACY.md) recorded as a secondary signal.

---

## Scenario (shown once at the top of the screener)

You manage a small bookstore that needs a weekly shift schedule. You have several part-time staff, each with different availability, skills (e.g., cashier, stockroom, customer-help), and shift preferences. The store is open seven days a week and busier on weekends. Below are five short questions about how you'd think about scheduling decisions in this setting.

---

## Q1. Preferences vs. capacity

Two staff members both want the Saturday morning shift, which only needs one person.

Which is true?

- A. The scheduler must pick one; the other has an unmet preference, but the schedule is still valid.
- B. The schedule needs reworking until both staff members can somehow be assigned to the shift together.
- C. No valid schedule is possible when staff preferences conflict like this.

---

## Q2. Competing goals

You can give every staff member their preferred shifts, but the result leaves all three of your most experienced staff on the same single day, with weaker coverage on other days.

What can you conclude?

- A. This is the best possible schedule because every staff member got the shifts they personally preferred.
- B. There is a trade-off between satisfying preferences and balancing skill coverage across days.
- C. The schedule needs reworking until coverage is consistent across days.

---

## Q3. Context-dependent priorities

The store has to choose between (i) keeping individual shifts short to reduce staff fatigue and (ii) covering every customer-facing slot during opening hours.

Which is true?

- A. Customer-facing coverage is always the more important priority, regardless of the toll it takes on staff.
- B. Reducing staff fatigue is always the more important priority, regardless of gaps in coverage.
- C. Which one matters more depends on what the store is currently prioritizing.

---

## Q4. Multiple dimensions of fairness

One staff member is consistently scheduled on the busiest, most demanding weekend shifts; another is consistently scheduled on the quietest. Their total weekly hours and pay are exactly equal.

What can you conclude?

- A. The schedule may still feel unfair because the workload isn't balanced, even though the hours are.
- B. The schedule is fair because the total hours and total pay are both equal.
- C. The schedule is completely fine; busy and quiet shifts are a normal part of working in retail.

---

## Q5. Rules vs. real outcomes

A proposed schedule satisfies every written rule (availability, max hours, required coverage). A staff member still says it doesn't work for them in practice.

What's the most likely explanation?

- A. The staff member is mistaken about the situation, since every written rule has been carefully satisfied.
- B. There must be an error in how the schedule was assembled.
- C. The written rules may not capture everything that matters in practice.

---

## Scoring Key — do not show participants

Pass threshold: **≥4 of 5 correct.**

| Q | Correct | What it tests |
|---|---------|---------------|
| 1 | **A** | Distinguishing capacity (hard) from preferences (soft); not every unmet preference invalidates a solution. |
| 2 | **B** | Recognizing that two desirable goals can pull against each other — the core of multi-objective reasoning. |
| 3 | **C** | Recognizing that priority weights are contextual, not universal. Maps directly to the weight-tuning behavior the interface elicits. |
| 4 | **A** | Recognizing that fairness has multiple axes; "equal hours" doesn't mean "equally fair." Maps to workload-variance and driver-preference penalties in the actual task. |
| 5 | **C** | Recognizing that the formal model is a simplification; a "valid" schedule can still fail in reality. This is the conceptual basis for any meaningful critique of the artifact. |

Candidates who select A on Q5 or B on Q4 are particularly poor fits — those answers indicate a "rules-only" view of scheduling that won't engage productively with the open-ended critique we want.

---

## Notes on what questsions test

 - Q1 tests whether they understand the constraint/preference distinction
 - Q2 tests whether they can hold competing objectives simultaneously
 - Q3 tests whether they accept that priorities are contextual, not absolute
 - Q4 tests whether they grasp that one metric (hours) doesn't capture the whole picture
 - Q5 tests whether they accept that the formal specification is incomplete

---

## Notes for administration

- Administered as a short asynchronous screener completed before the main session is scheduled. No time pressure.
- This is the **gate**: candidates scoring ≥4/5 are eligible for the study. Do **not** explain correct answers if a candidate fails; thank them and end the screening.
- Optimization literacy is **not** part of this screener. It is administered at the start of the main session, post-consent and before stance framing or any study materials, as a short conceptual warm-up (see [OPTIMIZATION_LITERACY.md](OPTIMIZATION_LITERACY.md)).
- If the candidate pool turns out to be uniformly high-scoring, consider adding one open-ended item ("Describe a trade-off you'd expect in scheduling problems") to differentiate further.
