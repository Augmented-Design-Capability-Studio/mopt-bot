---
name: Cursor Rules (Project Coding Guidelines)
description: Active instructions that govern how to work in this codebase (from previous Cursor code)
type: feedback
---
# Cursor Rules — Active Project Guidelines

---

## 1. Always sync docs on structural changes (`docs-sync.mdc`, alwaysApply)
When a change affects **app workflow, architecture, or repository layout**, update **`AI_INSTRUCTIONS.md`** and **`README.md`** in the same task. Keep edits short and scoped.
**Why:** AI_INSTRUCTIONS.md is the master implementer reference; README is user-facing. Both must reflect reality.
**How to apply:** Pure typo/comment fixes can skip this. Any architectural or workflow change = update both docs.

---

## 2. Use `google-genai` SDK, not `google-generativeai` (`gemini-google-genai.mdc`)
Import as: `from google import genai`, use `genai.Client`, `client.chats`, etc.
Prefer the **Chat API** (`client.chats.create` + `chat.send_message` with `history` and `system_instruction` / `GenerateContentConfig`) for conversational flows.
**Why:** `google-generativeai` is deprecated.
**How to apply:** Any Gemini/LLM code must use `google-genai` package. Never add `google-generativeai` as a dep.

---

## 3. Centralize prompts under `backend/app/prompts/` (`prompts-consolidation.mdc`)
New or changed LLM system prompts, instruction blocks, or reusable agent text must go in `backend/app/prompts/` (extend `study_chat.py` or add a small module there). Import from `app.prompts` in routers/services.
**Why:** Scattered prompt strings in routers/services are hard to audit and maintain.
**How to apply:** No long prompt strings in routers or service files; always import from `app.prompts`.

---

## 4. Always use the repo venv at `venv/` (`use-project-venv.mdc`, alwaysApply)
- **Windows**: `.\venv\Scripts\python.exe`, `.\venv\Scripts\pip.exe`, `.\venv\Scripts\pytest.exe`
- **Unix**: `venv/bin/python`, `venv/bin/pip`
Do NOT use system/global `python` or `pip` when working in this repo.
**Why:** Repo keeps its own isolated dependencies.
**How to apply:** All Python commands (run, test, install) use venv. If venv/ missing, tell user to create it first.

---

## 5. Preserve agile vs. waterfall workflow differences (`workflow-mode-differentiation.mdc`, alwaysApply)
`agile` and `waterfall` are intentional study variables. When changing workflow logic, prompts, UX, or session state:
- Keep `session.workflow_mode` as a first-class input
- Do NOT collapse the two modes into one generic behavior (unless user explicitly asks)
- Consider differences in: prompts, backend flow, gating, defaults, nudges, visible UI language/controls
- New workflow-related features must make a deliberate choice: same in both modes, or different — encode it explicitly
- If a change affects workflow semantics, update `README.md` and `AI_INSTRUCTIONS.md`
**Why:** Agile vs. waterfall is the primary study IV. Collapsing them would corrupt the study.
**How to apply:** Before any workflow-touching change, ask: does this treat both modes the same? Is that intentional?

---

## 6. `live_gemini` test failures may be key/network — not product bugs
Tests in `backend/tests/test_live_gemini.py` (marker `live_gemini`) call the real Gemini API. They auto-skip without a key, and once one fails for an auth or connection reason the rest of the live tests in the same session are auto-skipped to save quota. Setup: `backend/.secrets/gemini_api_key` (file, gitignored) **or** the `GEMINI_API_KEY` env var.
**Why:** Without this context, an agent debugging a `live_gemini` failure may chase phantom code bugs.
**How to apply:** When a `live_gemini` test fails, first confirm the key file exists, is non-empty, and isn't expired/revoked before assuming the production code regressed. See `backend/.secrets/README.md`.