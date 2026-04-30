# AI-Assisted Metaheuristic Optimization — Study Overview

## Purpose

This study evaluates an AI-assisted optimization interface as a **design artifact**. Participants role-play as a domain expert — someone with working knowledge of optimization trade-offs who would otherwise hire a programmer to configure and run a solver — and use the interface to engage with an optimization problem from that standpoint. The core question they are implicitly answering is: *"Does this interface let me, as a domain expert, do work I would otherwise have to hand off to a programmer?"*

The study is a 2×2 between-subjects design: **optimization expertise** (novice vs expert) × **workflow mode** (Agile vs Waterfall).

## Participant Role

Participants adopt the perspective of a domain expert who understands the problem space (scheduling, routing, trade-offs) but does not write code. Both novice and expert groups take this role; the distinction is the depth of optimization knowledge they bring to it. After the session, participants are interviewed about their experience and their critique of the interface.

## System

Three panels:

1. **Chat** — Describe the problem, state priorities, request solutions.
2. **Problem Definition Panel** — Structured view of objectives, constraints, and assumptions.
3. **Optimization & Visualization Panel** — Solutions, cost breakdowns, and route visualizations.

The underlying task is a fixed logistics scenario (fleet scheduling with time windows), presented as a general optimization assistant. Participants configure weights, constraints, algorithm choice, and driver preferences; they do not modify the underlying problem instance.

## Experimental Conditions

| Factor | Levels |
|--------|--------|
| Expertise | Novice / Expert |
| Workflow | Agile (iterative; runs enabled early) / Waterfall (specification-first; runs gated on resolved questions) |

## Data Collected

- Full interaction logs (chat, panel edits, solver runs, timestamps)
- Problem formulations (objectives, constraints, assumptions)
- Optimization metrics (cost, violations, convergence)
- Post-session interview and questionnaire (interface critique)

## Deception and Debriefing

The system is presented as a general-purpose optimization assistant; it is configured around a single fixed problem instance. This is disclosed at debriefing, when participants also learn the broader research questions and how their data will be used.

## Ethics

Minimal risk study, currently under IRB review. Chat logs are the primary data artifact. No API keys or personal identifiers are stored in logs.
