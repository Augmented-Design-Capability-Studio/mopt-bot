# AI Build Instructions — MOPT Study Platform

Source of truth for implementers. Do not commit secrets or participant identifiers.

---

## 1. What This System Is

MOPT is a research platform for evaluating an AI-assisted optimization interface as a **design artifact**. Participants role-play as a domain expert — someone with working knowledge of optimization trade-offs who would otherwise hire a programmer to configure and run a solver — and interact with the system from that standpoint. Researchers observe behavioral patterns and conduct post-session interviews about the interface.

The study is a **2×2 between-subjects design**: expertise (novice vs expert) × workflow mode (Agile vs Waterfall).

- **Agile**: AI makes **assumptions** (`kind: "assumption"`, `source: "agent"`) for agent-originated defaults, proposes configurations, and runs optimization early and frequently; **`gathered`** is for participant-stated or **confirmed** facts (including after **↑ promote** from Assumptions in the Definition UI). Introducing a **new** solver **weight key** (goal term) requires **explicit participant consent in chat**—retuning keys already in play does not. **`open_questions`** stay sparse (none is fine); prefer assumptions for provisional gaps (qualitative ~70/30 bias, not a quota).
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

The brief is the single source of truth between chat and panel config. Config is always *derived from* the brief, never written directly. Brief structure includes `goal_summary`, a single rolling `run_summary`, `items` (`kind: "gathered"` or `kind: "assumption"`) with `source` (`user` / `agent` / `upload`), and `open_questions` (with `status`/`answer_text`). Cleanup should consolidate run/session bookkeeping noise into `run_summary` instead of leaving per-run rows in gathered/assumptions/questions. Upload turns (participant and researcher-simulated) also run deterministic open-question reconciliation: upload-related open questions are auto-resolved when upload evidence is present, via a placeholder validator hook that currently always passes and is reserved for future file-content checks.

After merging a Gemini `panel_patch`, `sync_panel_from_problem_brief` (`backend/app/routers/sessions/sync.py`) backfills any missing search-strategy keys (`algorithm`, `epochs`, `pop_size`, and `algorithm_params` when the resolved algorithm matches the seed) from deterministic `*_problem/brief_seed.py` logic. That prevents partial model output (weights-only patches) from stripping the Problem Config search strategy block or breaking agile intrinsic readiness.

Panel→brief injection for the `config-search-strategy` gathered row (`_brief_items_from_panel`) also embeds **greedy init**, **early stopping** (+ patience/epsilon when present on `problem`), and **random seed** when present; VRPTW `brief_seed` parses those subphrases back out of the same line for deterministic round-trip.

### Workflow gating

- **Agile**: saved `problem` has ≥1 goal-term weight and a non-empty algorithm.
- **Waterfall**: `optimization_gate_engaged` flag set (first participant chat or saved open question) and no open questions with `status: "open"`.
- **Researcher override**: `optimization_allowed` flag on the session.
- **Participant Run button disablement**: use run-specific blockers (gate unmet, session terminated, edit mode active, or optimize in progress), not unrelated global busy indicators.

Waterfall Definition invariant: do not persist `kind: "assumption"` rows; missing information is tracked as `open_questions` until confirmed.

### Open-question answer routing (on save)

When the participant saves the Definition, the PATCH `/sessions/{id}/problem-brief` handler diffs incoming vs persisted `open_questions` to find OQs that just transitioned to `status: "answered"`. Each such answer is sent to a dedicated batched classifier (`classify_answered_open_questions` in `backend/app/services/llm.py`, prompt `STUDY_CHAT_OQ_CLASSIFY_TASK`) which rephrases concrete answers and bucket-routes hedged ones per workflow:

- **Concrete answer** (any mode) → `gathered` item with the LLM-rephrased fact (one short sentence; no "Question — Answer" scaffolding).
- **Hedged answer** ("you decide" / "i don't know" / "not sure" / etc):
  - **Waterfall** → the original OQ is replaced with a *simpler* follow-up `open_question` carrying 2–4 concrete `choices` (rendered as radio buttons on the OQ card). Never an assumption — preserves the waterfall "no assumptions" invariant.
  - **Agile / demo** → the OQ is dropped and an `assumption` item (source `agent`) is appended; the agile-mode chat rule "announce assumptions in visible chat" still applies.

A failed/empty classifier response (network, parse, missing key) falls through to the legacy `_promote_answered_open_questions_to_gathered` path, so saves are never blocked. The `ProblemBriefQuestion` schema gained an optional `choices: list[str] | None` for follow-up cards. Per-card processing state on the frontend (`participantOps.processingOqIds`) shows a spinning shield and locks input on each just-answered card while the round-trip is in flight.

### LLM prompts

All prompts live in `backend/app/prompts/` (primarily `study_chat.py`). The system instruction injects the current brief, last 4 run summaries, and researcher steering notes, plus temperature-aware context policy. Temperature is resolved model-first in `backend/app/services/llm.py` (cold/warm/hot classifier), with deterministic fallback from `backend/app/services/chat_context_policy.py` when classifier output is unavailable (session evidence only: brief/panel/runs; no keyword/regex matching):
- **cold**: problem-agnostic, no module-specific details;
- **warm/hot**: can use active-module participant-safe docs and visible run/config context, still hiding internal aliases.
Workflow-specific addenda (`STUDY_CHAT_WORKFLOW_WATERFALL` / `STUDY_CHAT_WORKFLOW_AGILE`) remain selected from `session.workflow_mode`. Domain-specific appendices come from each problem package (`*_study_prompts.py`), merged in `backend/app/services/llm.py`. Run-ack turns are constrained to avoid run-by-run memory growth: brief updates should stay condensed, avoid upload/run bookkeeping rows, and favor durable config-slot updates over new assumptions. Participant-facing replies should stay very short by default, use plain operational wording first (for example priorities and importance levels), and only introduce technical optimization terms when needed for precision. In visible chat across all modes, internal schema/config key names should stay hidden unless the participant explicitly asks for field-level names, and wording should avoid "activate/enable/turn on" framing in favor of neutral optimization phrasing ("increase emphasis", "prioritize more", "adjust toward").
Visible chat also receives a capabilities block and per-turn participant-safe doc excerpts from `docs/user/*.md` (and active `*_problem/docs/user/*.md` for warm/hot turns) via `backend/app/services/capabilities.py` and `backend/app/services/docs_index.py`. In cold turns, capabilities remain domain-agnostic; module goal-term and visualization detail is reserved for warm/hot context. Mentioning **MEALpy** is allowed when asked directly or when clarifying the solver-library stack. Execution capability copy is centralized behind an extensible mode contract (`read_only_simulated`, `propose_patch`, `apply_patch`) while current study execution remains configuration-only.
When new goal terms are introduced, config derivation should also assign term types in `problem.constraint_types` (`soft`, `hard`, `custom`; objective is implicit by omission): keep one main objective and classify most additional terms as soft/hard constraints, with `custom` reserved for explicit manual fixed-weight asks.
Legacy `hard_constraints` / `soft_constraints` arrays are deprecated and should not be emitted; goal-term meaning is represented through `weights` + `constraint_types` (+ optional `goal_terms` metadata and lock state).
Definition rows synced from panel config should describe goal-term type first (objective/soft/hard/custom-locked) before numeric value details. In participant Problem Config, goal-term lock controls should remain available; custom terms are treated as user-owned locked values unless manually unlocked.
Goal-term validity is enforced strictly at save/sync boundaries: every `goal_terms` entry needs an explicit valid `type`, `goal_term_order` cannot reference missing terms, and derived terms must be grounded in Definition `items` (assumption/gathered evidence). Invalid/hallucinated term sets are rejected (422 for direct participant save/sync), background derivation stores a structured `processing_error` and posts a brief participant-visible retry prompt.

### Domain packages

Each domain owns: weight definitions (`study_meta.py`), Gemini panel schema (`panel_schema.py`), chat prompt appendix (`study_prompts.py`), brief seeding (`brief_seed.py`), and neutral JSON bridge (`study_bridge.py`). Generic backend code accesses all domain behavior through `get_study_port()` from the registry. For VRPTW, canonical punctuality keys are `lateness_penalty` (all-order lateness) and `express_miss_penalty` (express-only misses); legacy `deadline_penalty` / `priority_penalty` are compatibility aliases normalized at read boundaries only. VRPTW **`study_prompts.py`** instructs config derivation **not** to emit `express_miss_penalty` unless the brief explicitly references express / VIP / SLA / **priority-order tier** language (generic “priority” or on-time emphasis maps to **`lateness_penalty`** only).

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

Chat messages render optimistically. The visible reply returns on the fast path; panel spinners from `session.processing` state reflect background brief/config derivation. Backend marks `processing.brief_status` / `config_status` as `"pending"` *before* invoking the model on `POST /sessions/:id/messages` (and the researcher `simulate-participant-upload` shim), so a participant polling during the model call window sees a chat pending-bubble even when the message originated from another actor (researcher push, simulated upload). Final state is settled by the same patch / skip / else branches as before; the per-turn `processing_revision` is reused (not double-incremented) by the else branch. The participant `syncMessages` poll also kicks an immediate session sync when new messages arrive so the spinner appears on the next message-poll tick rather than waiting for the slower session cadence.
Auto-posted run-complete interpretation context remains hidden from participant-visible chat (it is still passed to the model), so run feedback appears as one concise assistant insight rather than a synthetic user prompt plus reply.

### Researcher UI

The researcher sets workflow mode (agile/waterfall), the run-button availability, and the participant tutorial visibility. Steering messages are injected into the participant's session and remain invisible to them. The researcher can push a sparse starter problem config and batch-delete sessions.

**Tutorial bubbles are off by default.** New sessions are created with `participant_tutorial_enabled = False`; toggle the checkbox in the researcher detail view to enable in-app step bubbles for that session. Per-problem step content (titles, bodies, action buttons such as "Use starter prompt") lives in each problem module's `frontend/tutorial.ts`; problems without their own content fall back to the generic bodies in `frontend/src/tutorial/defaultContent.ts`.

---

## 6. Ethics and Logging

Chat logs are the primary data artifact. API keys and participant identifiers must not appear in application logs. Real `.env` values must not be committed — document variable names and placeholders only.

---

## 7. Tests

The non-live suite is fully offline. `backend/tests/conftest.py` autouse-stubs the Gemini classifier helpers (`classify_definition_intents`, `classify_chat_temperature`, `classify_assistant_run_invitation`) and the background-thread helpers (`generate_problem_brief_update`, `generate_config_from_brief`) using each function's production fallback path. Individual tests can `monkeypatch.setattr` over those defaults.

`backend/tests/test_live_gemini.py` (marker `live_gemini`) calls the real Gemini API. It auto-skips without a key. Setup: drop the key into `backend/.secrets/gemini_api_key` (file, gitignored) **or** export `GEMINI_API_KEY`. The first failure for an auth/connection reason auto-blocks the rest of that session's live tests to save quota. **A `live_gemini` failure can be a missing/invalid/expired key — verify the key before assuming a product regression.** See `backend/.secrets/README.md`.
