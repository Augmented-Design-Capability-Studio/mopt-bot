---
name: MOPT Architecture Patterns
description: Key architectural patterns, data flow, and design decisions in mopt-bot
type: project
---
# MOPT Architecture Patterns

## Core Data Flow
1. Participant chats → LLM generates visible reply (fast path)
2. Background task: LLM updates hidden `ProblemBrief` + derives config JSON
3. Frontend polls snapshot; shows panel spinners while derivation proceeds
4. Participant saves definition → backend syncs brief ↔ panel
5. Optimization gate check → POST /sessions/{id}/runs → MEALpy solver
6. Result stored; chat turn acknowledges run result
7. Researcher can inject steering notes (invisible to participant, highest LLM priority)

## Problem Modularity (StudyProblemPort)
- Each domain (vrptw, knapsack) is a standalone package with `mopt_manifest.toml`
- `backend/app/problems/registry.py` dynamically discovers domains
- Abstract interface in `port.py`: metadata, sanitization, parsing, solving, panel schemas
- Domain packages are **black boxes** — backend should not import internals directly

## Problem Brief as Middle Layer
- Single source of truth between chat and panel config
- Structure: gathered_info, assumptions, open_questions (with status/answer)
- Chat → Brief (LLM) → Config (deterministic derivation or LLM structured output)
- Fallback: regex-based brief-to-config derivation if LLM structured output fails

## Workflow Mode Gating
- **Agile intrinsic gate**: saved problem has ≥1 goal-term weight + non-empty algorithm
- **Waterfall intrinsic gate**: `optimization_gate_engaged` flag (first user chat) + no open questions with status "open"
- **Researcher override**: `optimization_allowed` flag on session
- Returns 409 with friendly guidance if blocked

## LLM Prompt Architecture
- All prompts centralized in `backend/app/prompts/` (primarily `study_chat.py`)
- System instruction injects: current brief, last 4 run summaries, steering notes
- Workflow-specific addenda appended based on `session.workflow_mode`
- Intent classification separates run-trigger intent from general chat
- Background derivation: hidden brief update + config derivation after visible reply

## Snapshots & Export
- Snapshot before each run + on manual panel saves
- Keep max 2000 snapshots per session (FIFO prune)
- Export: versioned (schema v2), full timeline (messages + snapshots + runs, sorted by time)
- Idempotent `db_maintenance.ensure_database_shape()` runs on startup

## Cooperative Cancellation
- Flag-based per-session cancel (`solve_cancel.py`)
- MEALpy objective function checks flag → raises `OptimizationCancelled`
- Run record stored with "Optimization cancelled" status

## Frontend Structure
- Three SPAs: `client.html` (participant), `researcher.html`, `analyzer.html`
- Centralized state via hooks: `useParticipantController.ts`, `useResearcherController.ts`
- Shared: `ChatPanel.tsx`, `api.ts`, `types.ts`, `backendConfig.ts`
- Backend URL: override (VITE_API_BASE env) → env → default

## Why this matters for code changes:
- Never import `*_problem/` internals from backend or generic frontend — go through `get_study_port()` / `getProblemModule(id)`. The one exception is `frontend/src/client/problemRegistry.ts`, which is the explicit registry.
- Modularity changes *within* a problem package (prompts, panel schema, frontend module, weights) are encouraged. Solver/evaluator/instance-data changes need maintainer approval.
- Chat fast-path = visible reply first, derivation in background (preserve this latency optimization)
- Brief is authoritative; config is always derived from brief (don't write config directly)
- Workflow mode must remain a first-class session variable (not collapsed to one behavior)