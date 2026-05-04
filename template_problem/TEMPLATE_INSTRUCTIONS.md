# Adding a New Problem Module

Copy this directory, rename it (`myproblem_problem/`), and implement every `TODO`.
The registry discovers your module automatically — no changes to the core backend or frontend are needed.

## Directory structure

```
myproblem_problem/
├── mopt_manifest.toml       # tells registry where to find your port
├── __init__.py
├── study_port.py            # StudyProblemPort implementation (entry point)
├── study_bridge.py          # JSON ↔ internal translation + solver dispatch
├── optimizer.py             # MEALpy (or other) solver wrapper
├── brief_seed.py            # deterministic brief → panel derivation
├── study_prompts.py         # LLM prompt text (chat appendix + config derive)
├── panel_schema.py          # Gemini structured-output JSON schema
└── frontend/
    └── index.ts             # ProblemModule export for the React shell
```

## Step-by-step

### 1. Rename the directory
```
mv template_problem myproblem_problem
```

Update `mopt_manifest.toml`:
```toml
port_module = "myproblem_problem.study_port"
port_attr   = "STUDY_PORT"
```

### 2. Implement `study_port.py`
Set `id` and `label`, then fill in each method.
The most important are:
- `meta()` — weight definitions, visualization presets, gate keys
- `sanitize_panel_config()` — validate + clean the stored panel JSON
- `solve_request_to_result()` — call your solver, raise `RunCancelled` on cancel
- `derive_problem_panel_from_brief()` — deterministic LLM fallback
- `visualization_capabilities()` — plain-language list of participant-visible post-run views

### 3. Implement `study_bridge.py`
`parse_problem_config()` translates neutral weight aliases → internal solver keys.
`solve_request_to_result()` dispatches to `optimizer.solve()` and formats the result.

### 4. Implement `optimizer.py`
Wrap MEALpy (or your solver).  Poll `cancel_event.is_set()` in the objective
function and raise `OptimizationCancelled` to cooperatively stop early.

### 5. Implement `brief_seed.py`
Deterministic extraction of weights/algorithm from brief text.  Called as the
LLM fallback when config derivation times out or returns nothing.

### 6. Write `study_prompts.py`
`STUDY_PROMPT_APPENDIX` — injected into the chat system prompt each turn.
`CONFIG_DERIVE_SYSTEM_PROMPT` — instructions for LLM structured config derivation.
Keep both participant-safe (don't name the domain by default).

### 7. Write `panel_schema.py`
Gemini `response_json_schema` for `{ "problem": { ... } }` patches.
Import `ALGORITHM_PARAMS_SCHEMA` from `app.problems.schema_shared` for the
`algorithm_params` field (shared across all problems).

### 8. Register in `frontend/src/client/problemRegistry.ts`
```typescript
import { MODULE as MYPROBLEM_MODULE } from "@myproblem/index";
// then add to REGISTRY:
myproblem: MYPROBLEM_MODULE,
```
Add the alias to `vite.config.ts` if needed:
```typescript
"@myproblem": path.resolve(__dirname, "../../myproblem_problem/frontend"),
```

### 9. Implement `frontend/index.ts`
At minimum export `MODULE: ProblemModule = { vizTabs: [] }`.
Add `buildGoalTermsExtension`, `ViolationSummary`, `parseEvalRoutes`, and
`formatRunViolationSummary` as your problem needs them.

To ship an in-app tutorial for this problem, add a sibling `frontend/tutorial.ts`
that exports a `TutorialContent` (see `@tutorial/types`) and attach it to
`MODULE.tutorialContent`. Without it, the generic fallback bodies in
`frontend/src/tutorial/defaultContent.ts` are used when the researcher enables
the tutorial.

The canonical step list has **12 steps** plus a `tutorial-complete` wrap-up;
the IDs (`chat-info`, `upload-files`, `update-definition`, `inspect-config`,
`first-run`, `read-run-summary`, `inspect-results`, `explain-run`,
`update-config`, `second-run`, `mark-candidate`, `third-run`,
`tutorial-complete`) are stable across problems — see
`frontend/src/tutorial/defaultContent.ts` for the source of truth.

`TutorialContent` exposes two strategies; **prefer `stepOverrides`**:

```ts
// myproblem_problem/frontend/tutorial.ts
import type { TutorialContent, TutorialStepOverride } from "@tutorial/types";
import type { TutorialStepId } from "@shared/api";

function myproblemStepOverrides(
  mode: string | undefined,
): Partial<Record<TutorialStepId, TutorialStepOverride>> {
  return {
    "upload-files": { body: "Upload your problem-specific input file(s) here." },
    "inspect-config": { body: "Set the X term to ..." },
    // ...only the steps you want to customize.
  };
}

export const MYPROBLEM_TUTORIAL_CONTENT: TutorialContent = {
  stepOverrides: myproblemStepOverrides,
};
```

Each override may set `title`, `body`, and/or `actions`; unspecified fields
inherit from the default. Use `stepsForMode(mode)` (returns the full step
array) only as an escape hatch when you need structurally different content
that overrides cannot express — extra steps, reordering, etc. If both fields
are present, `stepsForMode` wins.

### 10. Test
Add tests under `myproblem_problem/tests/` following the patterns in
`backend/tests/test_vrptw_encoder.py` and `backend/tests/test_vrptw_optimizer.py`.

## What NOT to change in the core

Adding a new problem should require zero changes to:
- `backend/app/problems/port.py` — abstract interface
- `backend/app/problems/registry.py` — discovery logic
- `backend/app/routers/` — routes
- `frontend/src/client/lib/` or any shared hooks

The only core file that must be touched is `frontend/src/client/problemRegistry.ts`
(the single named registration point) and `vite.config.ts` for the path alias.
