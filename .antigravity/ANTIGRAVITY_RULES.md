# Antigravity (AI) Working Rules for MOPT-BOT

Derived from `.cursor` rules, `docs/AI_INSTRUCTIONS.md`, and `README.md`. These rules govern how AI (Antigravity) should approach changes, particularly regarding the modularity of problem instances (`*_problem`), frontend/backend sync, and LLM boundaries.

## 1. Problem Modularity Standard (`*_problem`)

When creating a new benchmark or modularizing an existing problem domain (e.g., cautiously modifying `vrptw_problem`):
- **Decoupled Packages**: The `backend/` must not duplicate problem-specific logic. Each problem domain lives as a sibling to `backend/` (e.g., `vrptw_problem/`, `knapsack_problem/`).
- **Manifest Requirement**: A `mopt_manifest.toml` must exist at the root of the problem package specifying `port_module` and `port_attr` (e.g., `port_attr = "STUDY_PORT"`). This powers dynamic discovery without bloating main backend logic.
- **Study Port Implementation**: You must implement `StudyProblemPort` (`backend/app/problems/port.py`), handling:
  - `meta()` for config and ui presets
  - `sanitize_panel_config()` for migrating legacy states
  - `parse_problem_config()` for validating user-input JSON config
  - `solve_request_to_result()` for evaluating/running the backend optimization
  - Prompts/briefing schemas (`panel_patch_response_json_schema()`)
- **Standard Python Package Namespaces**: Do NOT use file-prefixing to prevent namespace collisions. Instead, treat problem directories as native Python packages (e.g., ensure an `__init__.py` exists). All internal imports must be standard relative imports (`from .evaluator import ...`) or fully qualified absolute package imports (`from vrptw_problem.evaluator import ...`). This idiomatic approach guarantees `sys.modules` isolation without messy filename prefixes.
- **Maintainer Approval Exception**: While AI_INSTRUCTIONS state "changes inside domain packages require explicit maintainer approval", I am explicitly authorized to cautiously refactor `vrptw_problem` to fit this modular architecture.

## 2. LLM & Prompt Engineering Practices

- **Use SDK**: Rely on `google-genai` (via `genai.Client`), **never** use the deprecated `google-generativeai`.
- **Chat APIs**: Default to `client.chats.create` + `send_message` with histories over one-off `generate_content`.
- **System Prompts Path**: System prompts and instruction templates must live centrally in `backend/app/prompts/` (e.g., `study_chat.py`), never hardcoded inside route definitions or business services.
- **Progressive Disclosure**: Maintain the illusion of a domain-neutral assistant for the user experience. Do not expose `vrptw` specifics unless introduced by the user.

## 3. Study Variable Integrity (Agile vs Waterfall)

- Treat `workflow_mode` as a strict, first-class configuration variable.
- **Waterfall**: Elicit complete upfront specifications. Enforce strict `optimization_gate_engaged` readiness where open questions must be resolved before runs are cleared.
- **Agile**: Encourage incremental exploration. Accept partial assumptions, run frequently, and populate panels with sensible defaults automatically.
- Do not blur or unify the two modes into a single baseline flow.

## 4. Environment & Tooling

- Always use the in-project Python virtual environment:
  - `.\venv\Scripts\python.exe` or `.\venv\Scripts\pip.exe` (Windows)
  - `venv/bin/python` (macOS/Unix)
- Do not run bare `pip` or global `python/pytest` invocations.

## 5. Documentation Discipline

When architectural changes, workflow branches, or repo structures shift:
- Simultaneously update `README.md` and `docs/AI_INSTRUCTIONS.md`.
- Keep modifications brief and immediately synchronized to prevent documentation drift.

## 6. Testing & Validation

- **Always verify changes:** Before concluding a task, you must run the project's test suite to ensure no regressions were introduced.
- **Run Command:** Run `.\venv\Scripts\pytest.exe -q` from the repository root.
- **Smoke Tests:** If applicable, perform the manual smoke checklist described in `README.md` (e.g., verifying frontend/backend connectivity, basic runs).

## 7. Extending These Rules

**To add persistent rules for me (Antigravity) to always refer to in this project:**
1. **Edit this file (`docs/ANTIGRAVITY_RULES.md`)** or **`docs/AI_INSTRUCTIONS.md`** with any new instructions.
2. In future chats, you can simply mention: *"Remember our rules in ANTIGRAVITY_RULES.md"* or *"Check AI_INSTRUCTIONS"* and I will rigorously abide by them.
3. For project-agnostic rules across all your workspaces, I can also create "Knowledge Items" (KIs) inside your local AppData directory (`.gemini/antigravity/knowledge`), which I automatically check before every session!
