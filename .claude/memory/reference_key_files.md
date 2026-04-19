---
name: MOPT Key File Locations
description: Where to find important backend, frontend, and domain-specific code in mopt-bot
type: reference
---
# Key File Locations

## Master Documentation
- `AI_INSTRUCTIONS.md` — 50KB+ implementer reference (canonical source for backend/API spec)
- `README.md` — user-facing setup and usage guide

## Backend Core
- `backend/app/main.py` — FastAPI app init, middleware, lifecycle
- `backend/app/models.py` — ORM: StudySession, ChatMessage, OptimizationRun, SessionSnapshot
- `backend/app/schemas.py` — Pydantic DTOs
- `backend/app/database.py` — SQLite connection
- `backend/app/db_maintenance.py` — idempotent schema updates on startup
- `backend/app/problem_brief.py` — ProblemBrief dataclass, normalization, merging
- `backend/app/optimization_gate.py` — `can_run_optimization()` for agile/waterfall
- `backend/app/solve_cancel.py` — cooperative cancellation flag per session
- `backend/app/session_snapshots.py` — snapshot CRUD, FIFO pruning (max 2000)
- `backend/app/session_export.py` — GET /sessions/{id}/export (versioned v2)
- `backend/app/algorithm_catalog.py` — MEALpy algorithm parameter definitions
- `backend/app/config.py` — reads from .env (MOPT_HOST, MOPT_PORT, secrets)
- `backend/app/auth.py` — bearer token auth

## LLM / Prompts / Services
- `backend/app/prompts/study_chat.py` — ALL system prompts (base + workflow addenda + task rules)
- `backend/app/services/llm.py` — chat generation, brief updates, config derivation, intent classification
- `backend/app/services/panel_merge.py` — merge brief patches with validation

## Problem Registry / Interface
- `backend/app/problems/port.py` — `StudyProblemPort` abstract base
- `backend/app/problems/registry.py` — dynamic domain loader via manifests
- `backend/app/problems/types.py` — ProblemMetadata, SolveResult, etc.
- `backend/app/problems/schema_shared.py` — shared Gemini JSON schema fragments

## Session Routes
- `backend/app/routers/sessions/router.py` — REST endpoints
- `backend/app/routers/sessions/helpers.py` — DB ops, background task scheduling
- `backend/app/routers/sessions/context.py` — build LLM context (brief + last 4 runs + steering)
- `backend/app/routers/sessions/derivation.py` — brief/config derivation background tasks
- `backend/app/routers/sessions/intent.py` — run-trigger intent classification
- `backend/app/routers/sessions/sync.py` — brief ↔ panel sync

## Problem Domains (`*_problem/` pattern)
Each domain follows the same layout (see `template_problem/` for a copy-and-fill template):
- `{name}_problem/mopt_manifest.toml` — registry manifest (`port_module`, `port_attr`)
- `{name}_problem/study_port.py` — `StudyProblemPort` implementation
- `{name}_problem/study_bridge.py` — neutral JSON ↔ internal solver translation
- `{name}_problem/study_meta.py` — weight definitions, metadata, UI presets
- `{name}_problem/study_prompts.py` — domain-specific chat appendix + config derivation text
- `{name}_problem/panel_schema.py` — Gemini JSON schema for panel patches
- `{name}_problem/optimizer.py` — MEALpy wrapper
- `{name}_problem/frontend/index.ts` — `MODULE: ProblemModule` export for the React shell

Specific current domains:
- `vrptw_problem/` — fleet routing (primary study problem); `evaluator.py` = cost + violations
- `knapsack_problem/` — 0/1 knapsack (toy benchmark); solver in `mealpy_solve.py`
- `template_problem/` — copy-and-fill template; see `TEMPLATE_INSTRUCTIONS.md`

## Frontend
- `frontend/src/client/ClientApp.tsx` — participant root (chat + setup + results)
- `frontend/src/client/hooks/useParticipantController.ts` — centralized session state & API
- `frontend/src/researcher/ResearcherApp.tsx` — researcher root
- `frontend/src/researcher/hooks/useResearcherController.ts` — researcher state & API
- `frontend/src/shared/api.ts` — HTTP client wrappers
- `frontend/src/shared/types.ts` — shared TypeScript interfaces
- `frontend/src/shared/chat/ChatPanel.tsx` — shared chat UI
- `frontend/vite.config.ts` — 3 entry points (client, researcher, analyzer)

## Config / Environment
- `backend/.env.example` — environment variable template
- `backend/run_server.py` — Uvicorn entry point (reads MOPT_HOST, MOPT_PORT)
- `pytest.ini` — test paths: backend/tests, vrptw_problem/tests, knapsack_problem/tests