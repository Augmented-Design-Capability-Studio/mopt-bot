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
`agile` and `waterfall` are the primary study IV — keep `session.workflow_mode` a first-class input and never collapse the two modes into one generic behavior (unless the user explicitly asks). The canonical axes the modes may differ on, plus the symmetry rules for everything else, live in [[project_workflow_axes]]. If a change affects workflow semantics, update `README.md` and `AI_INSTRUCTIONS.md`.

> Note: the `live_gemini` test-failure guidance that used to live here is already in `CLAUDE.md` ("Live Gemini tests") — kept there to avoid duplication.