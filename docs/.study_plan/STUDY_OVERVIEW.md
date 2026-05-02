# AI-Assisted Metaheuristic Optimization — Study Overview

## Purpose

This study evaluates an AI-assisted optimization interface as a **design artifact**. Participants are positioned as the stakeholder responsible for the scheduling decisions in the scenario — they direct the AI assistant to formulate and solve the problem, but are not expected to write code or implement solutions themselves. They engage as themselves, with whatever optimization or logistics knowledge they already have. The core question is: *Does this interface let a non-implementer stakeholder do meaningful work with an optimization solver that would otherwise have to be handed off to a programmer?*

The study uses a single between-subjects factor — **workflow mode** (Agile vs Waterfall) — as the primary contrast. Optimization expertise is measured as a continuous covariate (0–5 score on a brief literacy instrument administered at screening) and reported as a moderator rather than used to assign condition.

## Participant Stance

Participants are positioned as the person responsible for the scheduling decisions in this scenario. They decide what matters (priorities, trade-offs, constraints) and direct the AI assistant to produce solutions; they are not expected to write code or implement solutions themselves. Participants engage as themselves — bringing whatever optimization or logistics knowledge they already have — rather than role-playing a fictional persona. After the session, participants are interviewed about their experience and their critique of the interface.

## System

Three panels:

1. **Chat** — Describe the problem, state priorities, request solutions.
2. **Problem Definition Panel** — Structured view of objectives, constraints, and assumptions.
3. **Optimization & Visualization Panel** — Solutions, cost breakdowns, and route visualizations.

The underlying task is a fixed logistics scenario (fleet scheduling with time windows), presented as a general optimization assistant. Participants configure weights, constraints, algorithm choice, and driver preferences; they do not modify the underlying problem instance.

## Experimental Conditions

| Variable | Role | Levels / Range |
|----------|------|----------------|
| Workflow mode | Primary between-subjects factor | Agile (iterative; runs enabled early; assumptions used as provisional stand-ins) / Waterfall (specification-first; runs gated on resolved questions; missing info tracked as open questions, not assumptions) |
| Optimization expertise | Continuous covariate | 0–5 score on the optimization literacy instrument, administered at screening |

## Data Collected

- Full interaction logs (chat, panel edits, solver runs, timestamps)
- Problem formulations (objectives, constraints, assumptions)
- Optimization metrics (cost, violations, convergence)
- Post-session interview and questionnaire (interface critique)

## Disclosure

Participants are informed at consent that they will interact with a research prototype with bounded coverage — a single fixed scheduling scenario presented through an interface that resembles a more general optimization assistant. The fictional company and scenario are framing devices, not deception. The full research questions and intended uses of the data are revisited in a post-session conversation.

## Ethics

Minimal risk study, currently under IRB review. Chat logs are the primary data artifact. No API keys or personal identifiers are stored in logs.
