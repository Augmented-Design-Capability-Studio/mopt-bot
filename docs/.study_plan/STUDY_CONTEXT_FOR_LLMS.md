# MOPT Study — Context for LLMs

A short, paste-ready brief for chat agents that need context about this study before answering questions or giving opinions about it.

---

**MOPT (Metaheuristic Optimization Portal)** — a UX research platform evaluating an AI-assisted optimization interface as a design artifact. Primary contrast is **workflow mode** (Agile vs. Waterfall) as a between-subjects factor; optimization literacy is a continuous covariate, not a condition.

**The participant's stance.** Participants are positioned as the stakeholder responsible for scheduling decisions in a fictional scenario (QuickBite Fleet Scheduling). They direct an AI assistant in chat — they don't write code. The interface looks like a general-purpose metaheuristic optimization assistant, but the backend is hard-coded to **one fixed VRPTW instance**: 30 orders, 5 vehicles, 5 zones, a fixed travel-time matrix with traffic multipliers and a roadworks event, deterministic seed. Participants cannot change the geography, fleet, orders, or traffic model — only objective weights, constraint emphasis, driver preferences, locked assignments, and algorithm choice. The "general-purpose" appearance is honest framing (disclosed at consent as a "research prototype with bounded coverage"), not deception.

**Three panels:** Chat, Problem Definition (goal summary, gathered info, assumptions, open questions — all participant-visible and editable), and Optimization & Visualization (solver runs, cost breakdown, route visuals).

**Recruitment.** Asynchronous screener with a 5-item **scheduling-literacy** quiz set in an unrelated bookstore scenario (so candidates aren't pre-exposed to VRPTW). Must score ≥4/5 to be invited. Threshold is set at the point where role-play viability falls off, not for analytic distinction. Sourced from a university recruitment pool.

**Session steps (~70–75 min, post-screener):**
1. Consent (~3 min)
2. Optimization literacy quiz, 5 items (~2 min, before any framing — administered first so study language doesn't prime answers; used as covariate, not gate)
3. Stance framing — "you're the scheduler-stakeholder" (~3 min)
4. Orientation: short video + hands-on tutorial on the **knapsack** toy problem (~7–10 min, neutral ground before VRPTW)
5. Task briefing: QuickBite video + printed reference (data tables only). **No copy-pasteable written prompt** — participants must extract priorities and rephrase to the agent in their own words; how they translate is itself data (~10 min)
6. Pre-interaction check (~5 min)
7. Interaction phase — chat with the agent to formulate and solve (~30 min)
8. Post-task questionnaire + semi-structured interview critiquing the interface (~10–12 min). **No debrief** (IRB).

**Stack:** FastAPI + SQLite backend, React 18 + Vite + TypeScript (3 SPAs: participant, researcher, analyzer), Google Gemini via `google-genai`, MEALpy 3.0+ (GA, PSO, SA, SwarmSA, ACOR).
