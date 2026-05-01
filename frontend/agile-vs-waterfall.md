# Strengthening Agile vs. Waterfall Condition Differences

## Goal

The current `Agile` and `Waterfall` conditions differ in prompt framing and run access, but the participant-facing experience can feel fairly similar. This document consolidates all recommendations — from UI copy changes to structural protocol differences — for making the manipulation more visible, behaviorally meaningful, and defensible as a research contribution.

### Design Principle

Prefer soft guidance over hard restrictions unless the restriction is central to the manipulation. Warnings, prompts, checklists, and layout emphasis are usually enough to strengthen the condition without making the system fragile.

Don't rely on the LLM alone to create the difference — back it up with at least one hard structural constraint that the user can't ignore.

---

## Part 1 — UI-Level Differences

These changes alter wording, layout emphasis, default states, and lightweight guidance. They do not change solver behavior or core session data structures.

### 1. Workflow Banner at the Top

Add a persistent workflow-specific banner in the participant shell so the condition is immediately visible throughout the session.

`Waterfall` banner:
- Emphasize defining goals, constraints, and open questions before the first run.
- Example message: "Define your objectives, constraints, and assumptions before running the optimizer."

`Agile` banner:
- Emphasize early runs and incremental refinement.
- Example message: "Start with a quick baseline run, then make one small change after each result."

Why this helps:
- Makes the manipulation continuously visible.
- Requires only small frontend changes.
- Low risk of introducing instability.

---

### 2. Different Empty-State Messaging in the Results Panel

The current results panel uses generic language. This can be made condition-specific.

`Waterfall` empty state:
- Encourage completing the definition before the first run.
- Example: "Complete your problem definition before your first optimization run."

`Agile` empty state:
- Encourage running early and learning from results.
- Example: "Try an early baseline run, then refine one thing at a time."

Why this helps:
- Reinforces workflow style at the decision point where participants choose whether to run.
- Easy to implement.
- No backend dependency.

---

### 3. Different Primary Run Button Labels

Keep the same button behavior, but change the wording.

`Waterfall`:
- "Run first complete draft"
- "Run based on current specification"

`Agile`:
- "Run quick baseline"
- "Run next iteration"

Why this helps:
- Participants repeatedly see different framings for the same action.
- Strong manipulation effect from very small code changes.

---

### 4. Waterfall Checklist / Spec-Completion Card

Add a lightweight checklist in the problem setup area for `Waterfall`.

Possible checklist items:
- Goal summary entered
- At least two gathered facts
- At least one objective or constraint identified
- Open questions reviewed

This does not need perfect scoring. A simple heuristic is enough.

Why this helps:
- Makes `Waterfall` feel structured and deliberate.
- Supports the intended "specification before action" workflow.
- Mostly frontend-only.

---

### 5. Agile Post-Run "One Small Next Change" Nudge

After each successful run in `Agile`, show a compact panel encouraging the user to make one focused adjustment before rerunning.

Possible suggestions:
- adjust one weight
- add one missing constraint
- add one preference
- test one assignment change

Example copy:
- "Pick one small next change before your next run."
- "Use this result to refine one issue at a time."

Why this helps:
- Reinforces iterative behavior after every run.
- Fits the `Agile` condition naturally.
- Simple to implement in the results panel.

---

### 6. Different Composer Placeholder Text in Chat

Use workflow-specific placeholder text in the chat input box.

`Waterfall`:
- "Describe objectives, hard limits, fairness needs, and open questions..."

`Agile`:
- "Ask for a baseline run or suggest one small next change..."

Why this helps:
- Reinforces workflow framing at the point of user input.
- Very low implementation risk.

---

### 7. Different Default Panel Emphasis

Make the initial panel emphasis differ across conditions.

`Waterfall`:
- Show the definition/setup panel prominently from the start.

`Agile`:
- Keep the current chat-first emphasis and encourage immediate interaction/run requests.

Why this helps:
- Creates a more structural difference in how the session feels.
- Helps participants naturally adopt the intended workflow.

---

### 8. Different Default Tab Behavior

The problem setup panel can default to different tabs or states depending on workflow.

`Waterfall`:
- Default strongly to the `Definition` tab.

`Agile`:
- After the first run, emphasize configuration or results-oriented views.

Why this helps:
- Supports different rhythms of work.
- Can be done with simple UI logic.

---

### 9. Formulation Style (Prompt-Level) — Implemented

The agent's formulation behavior now differs by workflow (see `study_chat.py`):

**Waterfall formulation:**
- Elicit before adding: ask "Should I add X?" before adding any objective/constraint.
- Add at most one per turn; wait for explicit user confirmation.
- Probe for completeness without adding until user confirms.
- Propose values, don't assume: "Do you want a moderate weight or stronger?"

**Agile formulation:**
- Add from clear hints with light confirmation: "Added on-time delivery — run when ready or tweak first."
- Prefer try-and-adjust: let the run reveal gaps.
- Focus on next step; avoid long checklists.
- Still one new item per turn.

**Brevity:** Both workflows enforce short replies (2–3 sentences, one main idea per turn).

---

### 10. Different Run History Framing

Keep the underlying run data the same, but label it differently.

`Waterfall`:
- "Draft 1", "Draft 2"

`Agile`:
- "Iteration 1", "Iteration 2"

Why this helps:
- Continually reinforces the study condition.
- Minimal technical risk.

---

### 11. Different Reflection Prompts After Runs

After each run, show workflow-specific prompts.

`Waterfall`:
- "Review this result against your stated objectives before running again."

`Agile`:
- "Choose one targeted adjustment and rerun."

Why this helps:
- Encourages different patterns of engagement without changing the solver.
- Strong conceptual separation with little code complexity.

---

## Part 2 — Prompt-Level Reinforcements

These changes are applied to the system prompt addenda in `study_chat.py` and require no code changes to the frontend or backend logic.

### 12. Differentiated Opening Messages

The first assistant turn sets the tone for the entire session. Both conditions currently start from the same blank slate. Add a workflow-specific system instruction for the first turn:

- **Waterfall first turn:** *"Before we run anything, let's map out exactly what you're trying to optimize. What's the most important objective for your problem?"* — sets a deliberate, question-driven tone.
- **Agile first turn:** *"Let's get a quick baseline! Tell me the one thing you care most about and I'll set up a minimal run so we can see where we stand."* — sets an action-oriented tone from the first second.

---

### 13. Waterfall: Explicit Open-Question Discipline

Strengthen the waterfall addendum to instruct the AI to always maintain at least 2–3 open questions in the problem brief and to reference them by name before suggesting a run ("We still haven't resolved Q2 about capacity — shall we address that before running?"). This creates a visible, auditable requirement-tracking pattern.

---

### 14. Agile: Post-Run Diagnosis Protocol

Add to the agile addendum: *"After every run result, your first sentence must identify the single biggest cost contributor or violation and propose a specific one-parameter change to address it."* This makes the agile AI's behavior structurally different — it always leads with data-driven action rather than reflection.

---

### 15. Specification-Before-Assumption Rule (Waterfall) vs. Assume-and-Move-On (Agile)

Waterfall: *"Never fill in an assumption until the user has been explicitly asked about it and declined to provide a value. Always prefer asking over assuming."*

Agile: *"When a specification is missing, state your assumption and move on — the user can correct it after seeing results."*

This creates a measurable difference in how many `kind: "assumption"` vs `kind: "gathered"` items appear in the brief.

---

### 16. Workflow-Specific Auto-Context Messages After Runs

The frontend already posts a context message after a run asking the model to interpret results. That message can differ by workflow.

`Waterfall`:
- Ask the model to compare the result against the participant's stated objectives and constraints before suggesting another run.

`Agile`:
- Ask the model to suggest exactly one small next refinement.

Why this helps:
- Strengthens the manipulation in the chat experience.
- Reuses existing infrastructure.
- More impactful than pure copy changes.

---

## Part 3 — Mechanical / Structural Enforcements

These require moderate-to-significant code changes but produce the strongest condition differentiation.

### 17. Waterfall: Automated Spec-Completion Gate

Instead of the researcher manually toggling `optimization_allowed`, automate it. Define a minimum-viable-specification threshold — e.g., at least 3 confirmed gathered facts, 0 open questions, and a non-empty goal summary. When the threshold is met, the backend flips `optimization_allowed` to `True` and the UI shows "Specification complete — optimization unlocked." This is mechanically enforceable and loggable.

---

### 18. Waterfall: Pre-Run Confirmation Dialog

When the user clicks "Run optimization" (once unlocked), show an interstitial that summarizes the current specification and asks "Does this match your intent?" with Confirm/Go Back. This forces a moment of reflection and creates a measurable "specification review" event in the logs. Agile skips this entirely — clicking Run just runs.

---

### 19. Agile: Post-Run Suggestion Banner

After each run completes, show a persistent UI banner in the results panel: *"Biggest issue: [X]. Suggested next step: [Y]. [Apply & Re-run]"*. The banner content can be derived from the violation summary (e.g., "12 time-window violations — try increasing lateness_penalty"). This nudges rapid iteration at the UI level, not just the prompt level. Waterfall doesn't get this banner.

---

### 20. Waterfall "Ready for First Run" Confirmation

Instead of only silently gating optimization, add a participant-facing moment where `Waterfall` users explicitly confirm they are ready for the first run after reviewing the checklist.

Why this helps:
- Makes the difference between workflows more concrete.
- Better aligns the participant experience with the experimental manipulation.
- Still safer than changing solver logic.

---

### 21. Run Budgets

Give waterfall sessions a limited run budget (e.g., 5 runs). Display a counter: "Runs remaining: 4/5." This mechanically incentivizes careful planning. Agile gets unlimited runs. This is a crisp, justifiable manipulation: waterfall philosophy says "get it right before you build"; a run budget operationalizes that. It also produces a clean log metric (runs used out of budget).

---

### 22. Mandatory Reflection Step Between Waterfall Runs

After each waterfall run, disable the Run button for 60 seconds (or until the user sends at least one chat message). Display: "Review the results and discuss what to change before running again." This enforces the deliberate-change-between-runs principle. Agile has no such cooldown.

---

### 23. Different Problem-Brief Seeding

Start waterfall sessions with a richer set of system-seeded open questions in the definition panel (e.g., "What are the most important objectives?", "Are there hard constraints?", "What algorithm do you prefer?"). This makes the checklist tangible and visible. Agile sessions start with zero open questions — the AI discovers needs through results.

---

### 24. Waterfall: Specification Sign-Off Events

Add a "Mark as complete" button on each definition section (Gathered Info, Assumptions, Open Questions). The user must explicitly sign off on each section before the run unlocks. Each sign-off is logged as a distinct event. Agile has no sign-off — sections are fluid and always editable.

---

## Part 4 — Data / Measurement Reinforcements

These don't change the participant experience but strengthen the analysis and defend the manipulation's validity.

### 25. Condition-Aware Logging

Tag every logged event (chat turn, brief change, run, panel edit) with the `workflow_mode`. Also log timestamps for all events so you can compute time-to-first-run, inter-run intervals, and time-in-specification-phase.

---

### 26. AI Compliance Coding

After the study, have a coder (or an LLM) label each AI turn as "compliant" or "non-compliant" with the assigned workflow. Compute a compliance rate per session. Sessions with low compliance can be excluded or analyzed separately. This is the manipulation-check equivalent at the AI-behavior level.

---

### 27. Post-Task Self-Report

Ask participants: "Which best describes your approach?" with options like "I tried to specify everything before running" vs. "I ran early and refined iteratively." If participants in the waterfall condition don't select the first option, the manipulation may not have landed.

---

## Implementation Priority

### Best first set (high impact, moderate effort)

1. Add workflow-specific banners in the participant shell (#1).
2. Add workflow-specific empty-state text and run button labels in the results panel (#2, #3).
3. Add a simple `Waterfall` checklist in the problem setup panel (#4).
4. Add an `Agile` post-run "one small next change" prompt in the results panel (#5).
5. Add differentiated opening messages in the prompt (#11).
6. Add automated spec-completion gate for waterfall (#16).
7. Add post-run suggestion banner for agile (#18).
8. Add post-task self-report as a manipulation check (#26).

### Stability Considerations

**Safe to prioritize:**
- copy changes, labels, banners, nudges, button text
- small conditional UI blocks
- workflow-specific defaults
- prompt-level additions

**Use more caution with:**
- complex blocking rules
- hidden logic that prevents actions unpredictably
- heavy heuristic scoring of definition quality
- large branching changes in panel state management

---

## Suggested Framing for the Study

These additions make the manipulation stronger and more defensible as a comparison between:

- **problem-first, specification-oriented workflow**

and

- **iterative, run-early refinement workflow**

This is a cleaner and more accurate framing than claiming a full canonical comparison of software-engineering Agile versus Waterfall.
