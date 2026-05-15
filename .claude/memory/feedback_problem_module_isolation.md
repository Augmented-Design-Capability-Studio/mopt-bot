---
name: Keep main backend problem-agnostic
description: All problem-specific prompts, checks, validators, normalizers, and tests live in the problem module — never in the main backend
type: feedback
---

The main backend (`backend/app/...`) MUST stay problem-agnostic. Anything that
mentions or hardcodes VRPTW / knapsack / template specifics belongs in the
matching `*_problem/` package, surfaced through `StudyProblemPort` hooks.

This includes — and is not limited to:

- Prompt text or examples that name `driver_preferences`, `worker_preference`,
  `lateness_penalty`, `time_windows`, `value_emphasis`, `capacity_overflow`,
  `selection_sparsity`, etc. → `study_prompts.py` per port, surfaced via
  `StudyProblemPort.study_prompt_appendix()` / domain-specific addenda.
- Self-anchor or evidence checks keyed on problem-specific properties (e.g.
  "anchor `worker_preference` when `driver_preferences` is non-empty") →
  port hook (`auto_anchored_goal_term_keys`, or a new
  `is_goal_term_self_anchored(key, entry)` hook). Main backend calls the hook
  generically.
- Field-mirroring rules between `goal_terms[key].properties` and top-level
  panel fields (e.g. VRPTW's `worker_preference.properties.driver_preferences`
  ↔ panel `driver_preferences`) → port hook returning the mapping.
- Managed-field lists, locked-companion fields, brief-item-slot keying
  (`weight:shift_limit`, `driver_pref:*`, `lateness_penalty`) → port hooks.
- Validators, normalizers, sanitizers for problem-specific data shapes
  (driver-preference rule schema, condition enums, aggregation enums) →
  helper module inside the port package, called via a port method.
- Run-context formatting that names violations like `time_window_stop_count`
  or `capacity_units_over` → port method (already exists for run summaries;
  extend it).
- Tests that exercise problem-specific paths → live in `*_problem/tests/`.
  `backend/tests/` is for backend-pipeline coverage that uses neutral fixtures.
- LLM-based safety nets / extractors that re-fill problem-specific structured
  carriers (e.g. detect missing `driver_preferences` and re-extract rules from
  prose) → entire LLM call lives in the port package (prompt, schema,
  vocabulary, validation, the `genai.Client` invocation), surfaced via a port
  hook like `safety_net_fill_structured_carriers(brief, *, api_key, model_name,
  user_text, visible_reply)`. The main backend only orchestrates: call the
  hook, merge the returned brief, log on exceptions. Concrete example:
  `vrptw_problem/driver_pref_safety_net.py` owns the VRPTW worker-name → idx
  table, zone-letter → int mapping, and condition enums; `derivation.py`
  invokes it via `_port_safety_net_fill_structured_carriers`.

**Why:** the study runs multiple problems (VRPTW primary, knapsack toy, future
modules from the template). Bleeding problem-specific code into the main
backend breaks the modularity contract documented in
`.claude/memory/project_architecture.md` and makes it harder to add new
benchmarks. It also risks accidentally tying study-arm logic to one domain.

**How to apply:** when editing or reviewing code in `backend/app/`, grep for
problem-specific tokens. If any exist, move them behind a port hook before
making the change. When adding a new check or validator that *seems* generic
but references one problem's vocabulary, route it through a port hook from
the start. The few defensible exceptions are: `DEFAULT_PROBLEM_ID`, the
registry's built-in dir list, the migration default in `db_maintenance.py`,
and `frontend/src/client/problemRegistry.ts` (the explicit registry).
