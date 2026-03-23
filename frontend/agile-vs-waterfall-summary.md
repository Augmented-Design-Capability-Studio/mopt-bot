# Agile vs. Waterfall — Strategy Summary (26 Items)

1. **Workflow banner at the top** — Show a persistent condition-specific banner: Waterfall emphasizes spec-first, Agile emphasizes run-early. `[High]`
2. **Different empty-state messaging in the results panel** — Waterfall: "Complete your definition first." Agile: "Try an early baseline run." `[High]`
3. **Different primary run button labels** — Waterfall: "Run based on current specification." Agile: "Run next iteration." `[High]`
4. **Waterfall checklist / spec-completion card** — Show a lightweight checklist (goal summary, gathered facts, constraints, open questions) that must be addressed before running. `[High]`
5. **Agile post-run "one small next change" nudge** — After each run, prompt the user to make one focused adjustment before rerunning. `[High]`
6. **Different composer placeholder text in chat** — Waterfall: "Describe objectives, hard limits, fairness needs…" Agile: "Ask for a baseline run or suggest one small next change…" `[Medium]`
7. **Different default panel emphasis** — Waterfall: foreground the definition panel. Agile: foreground chat and results. `[Medium]`
8. **Different default tab behavior** — Waterfall defaults to the Definition tab. Agile emphasizes configuration or results after the first run. `[Medium]`
9. **Different run history framing** — Waterfall labels runs "Draft 1, Draft 2." Agile labels them "Iteration 1, Iteration 2." `[Medium]`
10. **Different reflection prompts after runs** — Waterfall: "Review results against your objectives." Agile: "Choose one targeted adjustment and rerun." `[Medium]`
11. **Differentiated opening messages** — Waterfall AI opens with a deliberate, question-driven greeting. Agile AI opens with an action-oriented "let's get a baseline" greeting. `[High]`
12. **Waterfall: explicit open-question discipline** — AI must maintain 2–3 open questions and reference them before suggesting a run. `[Medium]`
13. **Agile: post-run diagnosis protocol** — After every run, the AI's first sentence must identify the biggest cost contributor and propose a one-parameter fix. `[Medium]`
14. **Specification-before-assumption (Waterfall) vs. assume-and-move-on (Agile)** — Waterfall AI always asks before assuming; Agile AI states assumptions and moves on. Creates a measurable difference in gathered vs. assumption items. `[Medium]`
15. **Workflow-specific auto-context messages after runs** — Waterfall: model compares results to stated objectives. Agile: model suggests one small next refinement. `[Medium]`
16. **Waterfall: automated spec-completion gate** — Automatically unlock `optimization_allowed` once the brief meets a minimum threshold (e.g., 3 gathered facts, 0 open questions, non-empty goal). `[High]`
17. **Waterfall: pre-run confirmation dialog** — Show an interstitial summarizing the spec and asking "Does this match your intent?" before running. Agile skips this. `[Medium]`
18. **Agile: post-run suggestion banner** — Display a banner after each run identifying the biggest violation and suggesting a next step, with an optional "Apply & Re-run" action. `[High]`
19. **Waterfall "ready for first run" confirmation** — Add a participant-facing moment where Waterfall users explicitly confirm readiness before the first run. `[Medium]`
20. **Run budgets** — Give Waterfall a limited run budget (e.g., 5 runs) with a visible counter. Agile gets unlimited runs. `[Lower — may confound]`
21. **Mandatory reflection step between Waterfall runs** — Disable the Run button for 60 seconds or until a chat message is sent. `[Lower — may frustrate]`
22. **Different problem-brief seeding** — Waterfall starts with system-seeded open questions (objectives, constraints, algorithm). Agile starts with zero open questions. `[Medium]`
23. **Waterfall: specification sign-off events** — Add "Mark as complete" buttons on each definition section; all must be signed off before running. Each sign-off is a logged event. `[Lower — adds complexity]`
24. **Condition-aware logging** — Tag every event with `workflow_mode` and log timestamps to compute time-to-first-run, inter-run intervals, and time-in-specification-phase. `[High]`
25. **AI compliance coding** — Post-study, label each AI turn as compliant or non-compliant with the assigned workflow. Use as a manipulation check at the AI-behavior level. `[High]`
26. **Post-task self-report** — Ask participants to describe their approach ("specified everything first" vs. "ran early and refined"). Validates whether the manipulation landed. `[High]`
