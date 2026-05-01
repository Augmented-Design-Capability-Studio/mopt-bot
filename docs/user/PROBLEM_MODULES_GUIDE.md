# Problem Modules Guide

This guide explains how optimization problem modules are organized and how configuration choices map to solver behavior.

## 1) What Is a Problem Module?

A problem module is a packaged domain implementation that provides:

- Problem metadata for UI rendering
- Config validation and normalization
- Solver translation from user settings to executable optimization runs
- Prompt/schema support for structured AI-assisted configuration

At runtime, the backend loads registered modules and selects the active one for each session.

## 2) Core Concepts Users Should Know

- **Goal terms**: weighted components that encode what to optimize.
- **Constraint emphasis**: indicates whether a term is treated more strictly or as a softer preference.
- **Search strategy**: algorithm and hyperparameters controlling exploration.
- **Run snapshot**: the exact config state captured with each run result.

These concepts are shared across modules, even when domain vocabulary differs.

## 3) How User Inputs Become Runs

The high-level translation path is:

1. User asks or edits in chat/panel.
2. System maintains a structured problem definition.
3. Definition maps to a problem configuration JSON.
4. Active module validates and sanitizes that configuration.
5. Solver runs with selected strategy and parameters.
6. Results are returned with metrics and artifacts for comparison.

## 4) Why This Matters for Explanations

When users ask "what did you program?", useful answers should reference:

- Which goal terms were prioritized
- Which constraints were made stricter/softer
- Which search strategy and parameters were selected
- What changed relative to prior run snapshots

This gives a concrete operational explanation without requiring users to read source code.

## 5) Module-Oriented Vocabulary (Searchable)

Use these terms when searching docs or asking the assistant:

- "study port"
- "panel schema"
- "sanitize config"
- "parse config"
- "solve request"
- "weight aliases"
- "algorithm params"
- "run snapshot"

## 6) Practical Questions to Ask the Assistant

- "Explain the current module settings in engineer-ready terms."
- "Show how my goal terms map to optimization penalties."
- "What did you change in search strategy between the last two runs?"
- "Which config values are likely causing this violation pattern?"
- "If we keep constraints fixed, what single parameter should we tune next?"

## 7) Advanced: Change Discipline

For reliable improvement:

- Keep one baseline run as a reference.
- Apply small, explicit config changes.
- Compare with a short written hypothesis ("this should reduce lateness at some travel-time cost").
- Confirm whether outcomes matched the hypothesis before expanding scope.
