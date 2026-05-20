---
name: dynamic-algorithm-options-from-port
description: Canonical search-strategy OQ + agile assumption row text must be rendered from the active port's supported_algorithm_names(), not hardcoded
metadata:
  type: feedback
---

The canonical waterfall search-strategy OQ (`oq-monitor-algorithm`) and the
agile/demo assumption row (`item-monitor-algorithm-default`) must list
algorithms via the active port's `supported_algorithm_names()` hook,
rendered through `app.algorithm_catalog.format_algorithm_choices_phrase()`.
The first-supported algorithm is the agile default that the assumption row
names.

**Why:** Previously the OQ text listed only three of the five canonical
algorithms ("genetic search (GA), particle swarm (PSO), or simulated
annealing (SA)") — drifted from the optimizer registry, and gave the wrong
impression to participants that SwarmSA and ACOR weren't available. Per-
port differentiation is also a future requirement (a problem whose encoding
rules out PSO needs to omit it).

**How to apply:**
- Don't hardcode algorithm acronyms or nicknames in monitor-row text, system
  prompts, or schemas. Pull from `algorithm_catalog.ALGORITHM_PARTICIPANT_NICKNAMES_MAP`
  or call `format_algorithm_choices_phrase()` for an Oxford-comma rendering.
- `StudyProblemPort` is a structural Protocol — concrete ports don't inherit
  default methods. Call port hooks through a `getattr(port, "...", None)`
  fallback (see `_port_supported_algorithms` in `routers/sessions/derivation.py`).
- When a port wants to restrict algorithm choices, override
  `supported_algorithm_names()` to return a subset of
  `CANONICAL_ALGORITHM_NAMES`; put the agile default **first**.

Related: [[project_workflow_axes]] (axis 4 — search-strategy default).
