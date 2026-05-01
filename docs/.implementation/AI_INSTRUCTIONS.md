# AI Build Instructions — MOPT Study Platform

Source of truth for implementers. Do not commit secrets or participant identifiers.

---

## 1. What This System Is

MOPT is a research platform for evaluating an AI-assisted optimization interface as a **design artifact**. Participants role-play as a domain expert — someone with working knowledge of optimization trade-offs who would otherwise hire a programmer to configure and run a solver — and interact with the system from that standpoint. Researchers observe behavioral patterns and conduct post-session interviews about the interface.

The study is a **2×2 between-subjects design**: expertise (novice vs expert) × workflow mode (Agile vs Waterfall).

- **Agile**: AI makes assumptions, proposes configurations, and runs optimization early and frequently.
- **Waterfall**: Optimization is gated until all open questions are resolved; full specification expected upfront.
- **Demo**: Blended mode for live demonstrations (not a study condition).

The underlying task is a fixed VRPTW scenario (`vrptw_problem/`), presented to participants as a general metaheuristic optimization assistant. The domain identity is not disclosed until debriefing.

Study materials are in `docs/.study_plan/` (notably `docs/.study_plan/STUDY_DETAILED_PLAN.md` and `docs/.study_plan/AGILE_VS_WATERFALL.md`). IRB review in progress; minimal risk.
Participant-safe user docs are in `docs/user/` (`INTERFACE_GUIDE.md`, `PROBLEM_MODULES_GUIDE.md`, `ASKING_THE_AGENT.md`).

---

## 2. Tech Stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Frontend | React 18 + Vite + TypeScript | Three SPAs: `client` (participant), `researcher`, `analyzer` |
| Backend | FastAPI + Uvicorn | Python; target host is Raspberry Pi or equivalent |
| Database | SQLite via SQLAlchemy 2.0 | One file per deployment |
| LLM | Google Gemini via `google-genai` SDK | Not the deprecated `google-generativeai` package |
| Solver | MEALpy 3.0+ | GA, PSO, SA, SwarmSA, ACOR |
| Charting | Recharts 3.8 | |
| Python env | Repo `venv/` at project root | Use for all Python tooling |
| Deploy | Frontend: Vercel; Backend: own domain | Cloudflare tunnel in front of backend |

---

## 3. Repository Layout

```
frontend/           # Participant (client/), researcher, analyzer SPAs; shared components
backend/            # FastAPI app; prompts in app/prompts/; sessions API in app/routers/sessions/
vrptw_problem/      # Primary VRPTW domain package
knapsack_problem/   # Toy benchmark domain package
template_problem/   # Copy-and-fill template for adding new domains
docs/.setup/        # Deployment guides (Raspberry Pi, Windows PC setup)
docs/.study_plan/   # Study design/reference materials
docs/.implementation/# Build/implementation instructions for developers
docs/user/          # Participant-safe operational documentation
```

Domain packages expose a `StudyProblemPort` via `mopt_manifest.toml`. The backend registry (`backend/app/problems/registry.py`) discovers and loads them dynamically. `DEFAULT_PROBLEM_ID` is `"vrptw"`.

Architecture or layout changes should be reflected in both this file and `README.md`.

---

## 4. Backend Architecture

### Core data flow

1. Participant sends a chat message → LLM generates a visible reply (fast path, returned immediately).
2. Background thread: LLM updates a hidden `ProblemBrief` (gathered info, assumptions, open questions) as a compact rolling definition, then derives a structured `problem` config JSON.
3. Participant saves the definition → backend syncs brief ↔ panel config bidirectionally.
4. Optimization gate check → `POST /sessions/{id}/runs` → MEALpy solver → result stored.
5. Next chat turn acknowledges the run result (interpretation-only context messages do not trigger hidden brief/config derivation).
6. Researcher steering notes are injected into the system prompt (invisible to participant, highest priority).

### Problem brief as middle layer

The brief is the single source of truth between chat and panel config. Config is always *derived from* the brief, never written directly. Brief structure includes `goal_summary`, a single rolling `run_summary`, `gathered_info`, `assumptions`, and `open_questions` (with `status`/`answer_text`). Cleanup should consolidate run/session bookkeeping noise into `run_summary` instead of leaving per-run rows in gathered/assumptions/questions.

After merging a Gemini `panel_patch`, `sync_panel_from_problem_brief` (`backend/app/routers/sessions/sync.py`) backfills any missing search-strategy keys (`algorithm`, `epochs`, `pop_size`, and `algorithm_params` when the resolved algorithm matches the seed) from deterministic `*_problem/brief_seed.py` logic. That prevents partial model output (weights-only patches) from stripping the Problem Config search strategy block or breaking agile intrinsic readiness.

Panel→brief injection for the `config-search-strategy` gathered row (`_brief_items_from_panel`) also embeds **greedy init**, **early stopping** (+ patience/epsilon when present on `problem`), and **random seed** when present; VRPTW `brief_seed` parses those subphrases back out of the same line for deterministic round-trip.

### Workflow gating

- **Agile**: saved `problem` has ≥1 goal-term weight and a non-empty algorithm.
- **Waterfall**: `optimization_gate_engaged` flag set (first participant chat or saved open question) and no open questions with `status: "open"`.
- **Researcher override**: `optimization_allowed` flag on the session.

Waterfall Definition invariant: do not persist editable `kind: "assumption"` rows; missing information is tracked as `open_questions` until confirmed.

### LLM prompts

All prompts live in `backend/app/prompts/` (primarily `study_chat.py`). The system instruction injects the current brief, last 4 run summaries, and researcher steering notes. Workflow-specific addenda (`STUDY_CHAT_WORKFLOW_WATERFALL` / `STUDY_CHAT_WORKFLOW_AGILE`) are appended based on `session.workflow_mode`. Domain-specific appendices come from each problem package (`*_study_prompts.py`), merged in `backend/app/services/llm.py`. Run-ack turns are constrained to avoid run-by-run memory growth: brief updates should stay condensed, avoid upload/run bookkeeping rows, and favor durable config-slot updates over new assumptions. Participant-facing replies should stay very short by default, use plain operational wording first (for example priorities and importance levels), and only introduce technical optimization terms when needed for precision. In visible chat across all modes, internal schema/config key names should stay hidden unless the participant explicitly asks for field-level names, and wording should avoid "activate/enable/turn on" framing in favor of neutral optimization phrasing ("increase emphasis", "prioritize more", "adjust toward").
When new goal terms are introduced, config derivation should also assign term types in `problem.constraint_types` (`soft`, `hard`, `custom`; objective is implicit by omission): keep one main objective and classify most additional terms as soft/hard constraints, with `custom` reserved for explicit manual fixed-weight asks.
Definition rows synced from panel config should describe goal-term type first (objective/soft/hard/custom-locked) before numeric value details. In participant Problem Config, goal-term lock controls should remain available; custom terms are treated as user-owned locked values unless manually unlocked.

### Domain packages

Each domain owns: weight definitions (`study_meta.py`), Gemini panel schema (`panel_schema.py`), chat prompt appendix (`study_prompts.py`), brief seeding (`brief_seed.py`), and neutral JSON bridge (`study_bridge.py`). Generic backend code accesses all domain behavior through `get_study_port()` from the registry. For VRPTW, canonical punctuality keys are `lateness_penalty` (all-order lateness) and `express_miss_penalty` (express-only misses); legacy `deadline_penalty` / `priority_penalty` are compatibility aliases normalized at read boundaries only.

### API shape

REST with FastAPI. Separate bearer token secrets for participant and researcher (from `.env`).

- Sessions, messages, runs, snapshots at `/sessions/{id}/...`
- `GET /meta/test-problems` — registered problem metadata for frontends
- `POST /sessions/{id}/runs` — solve; returns solution, cost, violations
- `GET /sessions/{id}/export` — versioned archive (`export_schema_version: 2`) with full timeline

---

## 5. Frontend Architecture

Three SPAs share common components from `frontend/src/shared/`:

- **`client.html`** (participant) — Three panels: (1) Chat + upload, (2) Problem definition/config, (3) Results/visualization. Session orchestration in `useParticipantController.ts`.
- **`researcher.html`** — Session list + detail (chat, runs, mode controls, tutorial controls). Orchestration in `useResearcherController.ts`.
- **`analyzer.html`** — Local session archive viewer (upload exported JSON; timeline + raw JSON).

Problem modules register in `frontend/src/client/problemRegistry.ts` — the single named point for domain-specific frontend code. All generic frontend code calls `getProblemModule(id)`.

### Participant UI

The participant UI presents as a domain-neutral metaheuristic assistant. The workflow mode is not labeled in the participant header; a thin color accent provides a discreet observer cue.

Panel 2 has three tabs: **Definition** (gathered info, assumptions, open questions), **Problem Config** (structured goal-term weights, algorithm, params), and **Raw JSON** (read-only combined view). Config edits feed back into the brief; both directions of the chat → brief → config pipeline are kept in sync.

Panel 3 defaults to an interactive Gantt-style vehicle timeline built from run payload data. Run tabs use session-local labels (`Run #1`, `Run #2`, …).

Chat messages render optimistically. The visible reply returns on the fast path; panel spinners from `session.processing` state reflect background brief/config derivation.
Auto-posted run-complete interpretation context remains hidden from participant-visible chat (it is still passed to the model), so run feedback appears as one concise assistant insight rather than a synthetic user prompt plus reply.

### Researcher UI

The researcher sets workflow mode (agile/waterfall), the run-button availability, and the participant tutorial visibility. Steering messages are injected into the participant's session and remain invisible to them. The researcher can push a sparse starter problem config and batch-delete sessions.

---

## 6. Ethics and Logging

Chat logs are the primary data artifact. API keys and participant identifiers must not appear in application logs. Real `.env` values must not be committed — document variable names and placeholders only.
