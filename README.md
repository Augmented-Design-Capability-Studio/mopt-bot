# MOPT study stack

Participant and researcher web apps plus a FastAPI backend for the workflow study described in `AI_INSTRUCTIONS.md`. **Solver domains** ship as sibling **`*_problem/`** directories — currently **`vrptw_problem/`** (fleet routing) and **`knapsack_problem/`** (toy benchmark). Each exposes a **study port** via `mopt_manifest.toml`, loaded by **`backend/app/problems/registry.py`**. Per-session **`test_problem_id`** (default `vrptw`, set by `DEFAULT_PROBLEM_ID` in `registry.py`) selects the active port. **`GET /meta/test-problems`** lists ids, labels, weight definitions, and UI extension keys for clients. Pulling new code **adds SQLite columns idempotently** on API startup (`ensure_database_shape`).

## Table of contents

- [Prerequisites](#prerequisites)
- [Backend](#backend)
- [Problem modules (adding a benchmark)](#problem-modules-adding-a-benchmark)
- [Frontend](#frontend)
- [Tests](#tests)
- [Smoke checklist (manual)](#smoke-checklist-manual)

## Prerequisites

- Python 3.10+ and a venv at repo root (`venv/`)
- Node 20+ for the frontend

## Backend

Install dependencies once (repo root):

**Windows (PowerShell)**

```powershell
.\venv\Scripts\pip.exe install -r requirements.txt
Copy-Item backend\.env.example .env
# Edit `.env` (real secrets). `.env.example` is only a template — the server does not read it.
# Set MOPT_CLIENT_SECRET, MOPT_RESEARCHER_SECRET, MOPT_CORS_ORIGINS, MOPT_HOST, MOPT_PORT,
# MOPT_DEFAULT_GEMINI_MODEL (defaults to gemini-3-flash-preview), etc.
```

**Linux / macOS**

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp backend/.env.example .env
# Edit `.env` with real secrets (same variables as above).
```

**Linux / Raspberry Pi** — see `docs/RASPBERRY_PI_SETUP.txt` for `apt`, `venv`, and `pip` commands.  
**Windows PC** — see `docs/WINDOWS_PC_SETUP.txt` for PowerShell, `venv`, backend run, and Cloudflare Tunnel setup.

### Run the API

Preferred launcher (reads `MOPT_HOST` / `MOPT_PORT` from `.env`; CLI overrides):

```powershell
cd backend
..\venv\Scripts\python.exe run_server.py
```

```bash
cd backend
../venv/bin/python run_server.py
```

Participant chat uses **Gemini** via **`google-genai`** (chat sessions). **Domain-neutral** study prompts live in **`backend/app/prompts/study_chat.py`**; each registered benchmark adds an appendix and config-derivation text from its domain tree (e.g. **`vrptw_problem/vrptw_study_prompts.py`**, **`knapsack_problem/knapsack_study_prompts.py`**), merged in **`backend/app/services/llm.py`** via **`get_study_port(...)`**. Gemini **panel patch** schemas live next to each benchmark (**`*_panel_schema.py`**) with shared algorithm-param fragments in **`backend/app/problems/schema_shared.py`**; **`gemini_schemas.py`** still exposes convenience wrappers that add the domain directory to `sys.path` when needed.

From the **repo root** (script changes into `backend/` automatically):

```powershell
.\venv\Scripts\python.exe backend\run_server.py
```

```bash
./venv/bin/python backend/run_server.py
```

Options:

- `--host ADDRESS` — bind address (overrides `MOPT_HOST`)
- `--port N` — listen port (overrides `MOPT_PORT`)
- `--reload` — auto-reload on code changes (**dev only**; avoid on a Pi in production)

You can still use Uvicorn directly if you prefer:

```powershell
..\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Default URL: `http://127.0.0.1:8000` (or your chosen port)
- Health: `GET /health`
- Auth: `Authorization: Bearer <MOPT_CLIENT_SECRET>` (participant) or `<MOPT_RESEARCHER_SECRET>` (researcher)
- **Cancel in-flight optimize:** `POST /sessions/{id}/runs/cancel` or `POST /sessions/{id}/optimization/cancel` (equivalent). The participant app uses **`/optimization/cancel`** to avoid some proxy/preflight issues with paths under `/runs/`.

Install **mealpy** (via `vrptw_problem/requirements.txt` and the knapsack package’s needs) or optimization runs return a clear error. **Troubleshooting:** If a run shows **Solver import error** mentioning `mealpy`, the API process is not using a `venv` that has `backend/requirements.txt` applied (e.g. `.\venv\Scripts\python.exe -c "import mealpy"` should succeed on the host). Failed runs log **`Optimization import error`** or **`Optimization run failed`** in the server console with a traceback.

Optional **`MOPT_PROBLEM_PATHS`** (comma-separated directories, trusted hosts only) registers extra benchmarks: if a directory contains **`mopt_manifest.toml`**, it is loaded the same way as built-ins; otherwise the backend looks for legacy **`register_ports.py`** with a `register(registry)` function — see `backend/.env.example`.

**Optimization stopping:** By default the solver uses MEALpy **early stopping** (plateau on the global best cost) together with **`epochs` as a maximum** iteration cap, so runs often finish before the cap when improvements stall. Set `early_stop` to `false` in `problem` for fixed full-epoch runs; optional `early_stop_patience` and `early_stop_epsilon` tune plateau detection (see `backend/app/adapter.py` / `vrptw_problem/optimizer.py`).

**Participant chat (Gemini):** Python package **`google-genai`** (`pip` installs it via `backend/requirements.txt`). General prompt fragments live in `backend/app/prompts/study_chat.py`; benchmark-specific appendices ship with each problem package (see server paragraph above). `backend/app/services/llm.py` splits visible chat reply, hidden brief update, and config derivation, and selects structured JSON schemas by **`test_problem_id`**.
- **Fast chat path:** `POST /sessions/:id/messages` returns the assistant chat reply first (when **Ask model** is on), then continues brief/config derivation in a background thread. The same response **always** includes a `processing` snapshot (even when `invoke_model` is `false`) so the client never keeps a stale pending overlay after a user-only message. Session JSON exposes `processing` state (`brief_status`, `config_status`, `processing_revision`, `processing_error`) so the frontend can show panel-level pending state without blocking chat. After the hidden brief pass, if the normalized brief is unchanged, the background thread **skips the config LLM** and uses heuristic `derive_problem_panel_from_brief` only (same shortcut for `agile` and `waterfall`). Optional body field **`skip_hidden_brief_update`** (with `invoke_model`): visible reply only, no background brief merge — used after participant-driven definition/config saves and snapshot restores so the model does not overwrite stored state; open-question answer flows still run full derivation.
- **Interpretation-only context guard:** synthetic participant context lines (for example, "Run #N just completed..." and "I manually updated the problem configuration...") are treated as interpretation-only and do not launch hidden brief/config derivation, preventing ghost config rewrites after manual edits.
- **Run-complete context visibility:** auto-posted run-complete context used to request interpretation is now hidden from participant chat history (still sent to the model), so participants only see the concise assistant interpretation instead of an extra synthetic user prompt line.
- **Visible/hidden output separation:** participant-visible replies remain plain conversational text. Hidden structured patch keys (for example `problem_brief_patch`) are used only in backend brief-update flow and are stripped from visible chat if the model leaks them.
- **`STUDY_CHAT_SYSTEM_PROMPT`** — domain-neutral, delivery-partner persona; stays general until the user describes the problem. When the user asks to "write code" or "implement", the agent updates the problem brief (not source code) and the backend derives solver configuration JSON from that brief. Constraints and objectives are revealed progressively — only when the user mentions related concepts. Participant-facing wording defaults to plain language (for example priorities, importance levels, and run settings) before technical optimization terms. In visible chat, internal schema key names should stay hidden unless the participant explicitly requests technical field names, and objective suggestions should avoid "activate/enable/turn on" phrasing in favor of neutral optimization language. Weight keys use human-readable alias names (see below).
- **Goal-term type discipline:** when chat/brief adds new goal terms, config derivation should also classify term type via `problem.constraint_types` (`soft`, `hard`, `custom`; objective is implicit when omitted). Keep one primary objective and classify most additional terms as soft/hard constraints; use `custom` only for explicit manual fixed-weight requests.
- **Definition phrasing + locks:** panel→brief sync now phrases goal-term rows as term type first (primary objective / soft constraint / hard constraint / custom locked value), then includes the numeric weight. Goal-term lock buttons are visible again in the Problem Config panel; custom terms stay user-owned (locked) unless manually unlocked.
- **Search strategy in gathered info:** the single `Search strategy: …` config row from panel→brief (`backend/app/problem_brief.py`) now also records **greedy initialization**, **stop early on plateau** (and **plateau patience** / **min improvement epsilon** when those keys are present on `problem`), and **random seed** when set. VRPTW deterministic brief→panel seeding (`vrptw_problem/brief_seed.py`) parses the same phrases back so those settings survive brief round-trips.
- **`STUDY_CHAT_WORKFLOW_WATERFALL`** / **`STUDY_CHAT_WORKFLOW_AGILE`** — injected based on `session.workflow_mode`; waterfall encourages full upfront specification, agile encourages frequent short runs. The LLM service (`backend/app/services/llm.py`) selects the right chunk from the session's `workflow_mode`.
- **Task and phase guidance** — separate prompt blocks guide visible chat, hidden brief updates, workflow-specific behavior, and phase-specific behavior (`discovery`, `structuring`, `configuration`) so `agile` and `waterfall` can diverge further later without another large prompt rewrite.
- **`STUDY_CHAT_STRUCTURED_JSON_RULES`** / hidden brief-update rules — format rules for structured brief updates plus cleanup controls. Normal turns remain additive; cleanup/reorganize turns can set `replace_editable_items` / `replace_open_questions` for holistic replacement.

The chat system instruction includes the current **problem brief** middle layer (including hidden system context for prompting), compact summaries of the last 4 runs for result-comparison context, and hidden researcher steering notes (when present). Steering notes remain invisible to participants, are treated as highest-priority guidance for the next reply/brief update, and are applied with a natural conversational transition.

After the visible reply is saved, backend derives the brief and then the `problem` panel block from the latest brief. If model-based config derivation fails (or no key is configured), backend falls back to deterministic seeding (`derive_problem_panel_from_brief`) that prioritizes structured config-slot rows and uses legacy text heuristics only as a secondary path. When Gemini returns a **partial** panel patch (for example weights and constraint types only), `sync_panel_from_problem_brief` backfills missing search-strategy fields from the same deterministic brief seeding so `algorithm` / `epochs` / `pop_size` / `algorithm_params` stay present for the Problem Config UI and agile gating. Cleanup requests (consolidate/remove/reorganize) are detected in backend orchestration and routed through holistic replacement mode so redundant gathered/assumption rows can be reliably removed.

**Weight aliases:** The participant panel uses seven VRPTW alias names (`travel_time`, `shift_limit`, `lateness_penalty`, `capacity_penalty`, `workload_balance`, `worker_preference`, `express_miss_penalty`), matching internal `w1`–`w7`. **`shift_limit` (w2)** penalizes total minutes past **`max_shift_hours`** (summed over vehicles); a large weight approximates a hard cap. `lateness_penalty` is overall time-window lateness (all orders), while `express_miss_penalty` is express-only SLA misses. The adapter (`backend/app/adapter.py` — re-exports **`vrptw_study_bridge`**: `WEIGHT_ALIASES` + `translate_weights`) maps aliases to `w1`–`w7`. Human-readable definitions live in **`vrptw_problem/study_meta.py`** (**`study_port.py`** re-exports). Sanitize migrates deprecated **`fuel_cost`** / legacy **`shift_overtime`** to **`shift_limit`** and normalizes legacy penalty names (`deadline_penalty`/`priority_penalty`) to canonical keys at read boundaries. Chat/LLM closed schemas list the canonical aliases; fuel/mileage language still maps to **`travel_time`** only.

**Algorithm hyperparameters:** `problem.algorithm_params` may only contain keys the MEALpy wrapper actually passes for the selected algorithm (`GA`/`PSO`/`SA`/`SwarmSA`/`ACOR`). The canonical list and defaults live in [`backend/app/algorithm_catalog.py`](backend/app/algorithm_catalog.py) (mirrored in [`frontend/src/client/problemConfig/algorithmCatalog.ts`](frontend/src/client/problemConfig/algorithmCatalog.ts) for the structured config UI). The adapter drops unknown keys with a panel note; the Definition tab only surfaces non-default parameter values so default `pc`/`pm` lines no longer clutter gathered info. The participant **Problem Config** tab exposes the same fields as editable numbers under **Search strategy**.

**Driver preferences defaulting:** participant-facing runs treat `driver_preferences` as **opt-in**. If the field is omitted from `problem`, backend solve/evaluate paths default to `[]` (no implicit driver-trait penalties). Brief→panel sync now treats `driver_preferences` as a managed field, so stale prior preferences are removed unless re-derived (or preserved via lock companion behavior). Driver-preference normalization uses canonical zones (`1..5`, `A..E`, or canonical names) and canonical conditions (`avoid_zone`, `order_priority`, `shift_over_limit`) in active UI/prompt output; legacy aliases are accepted only at the compatibility boundary and immediately rewritten to canonical forms. Canonical/official research scoring can still use canonical defaults when explicitly evaluated via `vrptw_problem/researcher/official_evaluator.py`.

With **Ask model (requires API key).** enabled, structured chat replies update the editable `problem_brief` middle layer, then backend derives the final `panel_config` from that updated brief. The **hidden** brief-update LLM pass (`generate_problem_brief_update`) receives the same **`problem_brief_patch.items` rules** as the structured JSON path (`STUDY_CHAT_HIDDEN_BRIEF_ITEMS_RULES` in `study_chat.py`), including explicit cleanup instructions: one gathered row per objective/constraint term, not bundled comma-separated lines. After a successful optimization run, if **Ask model** is on, the frontend automatically posts a context message asking the agent to interpret and compare results. **Run-ack rules** keep Definition memory as a compact rolling specification (not a per-run timeline): no upload/run bookkeeping rows and no run-by-run gathered/assumption append behavior; only durable config-slot edits and open-question curation are allowed. **`POST /sessions/:id/messages`** does **not** run chat-triggered auto-optimization when that user message is the auto-posted run-complete line (`intent.is_run_acknowledgement_message`), so it cannot spuriously start a new run in the same request. Chat system prompts include **`locked_goal_terms`** from the saved panel (`problem_brief.locked_goal_terms_prompt_section`) so the model does not suggest changing locked weights; **waterfall** run-ack prompts encourage merge-appended **open_questions** when clarification remains. Manual config-save follow-up prompts now skip hidden derivation and request very short explanations using participant-friendly setting names (for example, "Stop early on plateau" instead of `early_stop`). New sessions start without panel JSON until the researcher **Push starter problem config** or the participant flow creates one; in `waterfall`, backend keeps deriving and syncing the `problem` block from the saved brief so the config stays aligned with the participant's current definition instead of a stale starter. There is no separate automatic "test config" fallback beyond the explicit researcher-pushed starter.

The chat footer includes a simulated **`Upload file(s)...`** action with a horizontal **scrollable chip row** of file names (remove with **×** clears the chip only; chat history is unchanged). Participant-facing copy and the study agent should point users at that **Upload file(s)...** control only. For lab/testing, **`POST /sessions/{id}/researcher/simulate-participant-upload`** (researcher auth) can post the same user-visible upload line, defaulting to **`DRIVER_INFO.csv`** and **`ORDERS.csv`** when the body is empty (researcher UI: **More actions & settings**). In logistics-style conversations, the assistant should request uploads for order data plus driver information/preferences, acknowledge uploads as if ingested, and may reference city-traffic API assumptions (time-of-day traffic and disruptions) while reasoning about schedules.

When the participant saves or syncs the definition, answered open questions (non-empty answer) are **folded into Gathered Info** as one line of **literal** `Question — Answer` text (backend `_format_answered_open_question_gathered`, frontend `summary.ts`) and dropped from `open_questions`. The Definition tab action row (next to **Sync to config**, drop-up like **Snapshot**) includes **⋯** → **Clean up definition**, and immediately below it **Clean up open questions**. The open-question action calls a dedicated backend endpoint that targets only `open_questions`, while the regular cleanup-definition action remains holistic. After chat turns that mutate the brief, backend also runs an automatic open-question cleanup pass (all modes: agile/waterfall/demo) using an LLM-first prune and conservative deterministic fallback. **`merge_problem_brief_patch`** keeps existing open questions when a cleanup patch sets `replace_open_questions` but omits `open_questions` (models must send an explicit list, including `[]`, to replace). The model is instructed not to put resolved answers in `open_questions` (no `(Answered: …)` suffixes); the merge layer also moves those patterns into gathered. `merge_problem_brief_patch` still preserves answered state from the base when a patch references the same question id but omits status/answer fields, before normalization promotes answered rows.

**Brief normalization:** `normalize_problem_brief` splits long compound objective lists and lines starting with **`Constraint handling:`** (several comma- or *and*-separated penalties in one sentence) into **separate gathered rows**, one per term—parallel to compound objective splitting—so each maps cleanly to goal-term / config seeding. Promoted answered-open-question rows (`gathered-oq-*`, or any gathered/assumption line containing an em dash `—` as in `Question — Answer`) are **not** atomized, so commas inside the answer do not split the row.

**Clean up definition + panel:** After the cleanup brief merge, background derivation runs **`sync_problem_brief_from_panel`** so weight lines and other slot-backed facts match the **saved problem config** (the hidden cleanup prompt also receives the current panel JSON). That way reorganizing the definition does not strip numeric weights from the gathered list.

While background brief/config derivation is pending, **Problem Config** and **Raw JSON** show a fixed grey overlay over the scroll area (with a **90s** client timeout that unlocks and warns if the server stays pending); the overlay uses `pointer-events: none` so you can still scroll and use the scrollbar on the content underneath. The participant client also polls **`GET /sessions/:id` about every 2.5s** while `brief_status` or `config_status` is `pending` (tab visible) so the overlay clears soon after the server settles, in addition to the usual slower session poll. Spinner/shield copy is now operation-scoped (definition-save vs config-sync) instead of a single global busy flag, and long-running pending states degrade to warning UI instead of an endless spinner. Open-question cleanup shows a local loading indicator only inside the Open Questions section, so gathered/assumption editing remains available. New definition rows use a shared placeholder until the user saves non-placeholder text (see `frontend/src/client/problemDefinition/constants.ts`).

**Problem setup panel** has three tabs: **Definition**, **Problem Config**, and **Raw JSON**. `frontend/src/client/problemDefinition/DefinitionPanel.tsx` shows **Goal Summary**, **Run Summary** (single editable rolling entry), gathered info, assumptions, and open questions; the user enters **definition edit mode** by clicking a field, **+**, or **X**, then uses bottom **Save** / **Cancel** (Save glows when there are material changes; placeholder-only new rows are highlighted but not “dirty” until edited). `client/problemConfig/ProblemConfigBlocks.tsx` is read-only until deliberate interaction, then **config edit** with the same Save/Cancel pattern. Goal-term rows now include lock and remove (`X`) controls: locked goal terms are protected from chat/definition-driven config regeneration, and removing a goal term also removes its lock entry. Backend sync now canonicalizes lock entries against the saved panel (`locked_goal_terms` remains panel-source), preserving locked values for valid locked keys and dropping stale lock ids atomically. Locking **`worker_preference`** also preserves **`driver_preferences`** during that sync (and the structured UI disables editing preference rules until unlocked). Clicking lock/remove (or read-only field mimics) enters config edit mode; background panel clicks do not. Numeric fields allow temporary empty text while typing and normalize on blur/save. When not editing, **Snapshot** menus provide **Save to snapshot** (`POST /sessions/:id/snapshots`), **Load from snapshot…**, and on the config tab **From most recent run**; the definition tab keeps **Sync to config**. `GET /sessions/:id/snapshots` lists history; PATCH definition/config still creates snapshots on save. The **Raw JSON** tab is read-only combined JSON.

**Optimization run eligibility:** A participant may run when **`optimization_runs_blocked_by_researcher`** is false **and** (**`optimization_allowed`** is true via researcher permit **or** **intrinsic readiness** passes) (`backend/app/optimization_gate.py`, mirrored in `frontend/src/client/lib/optimizationGate.ts`). **Agile intrinsic:** saved `problem` must include at least one **Goal terms** weight (same display keys as the structured UI) **and** a non-empty **`algorithm`**. **Waterfall intrinsic:** session flag **`optimization_gate_engaged`** must be true (first participant-visible **user** chat message, or any saved **`open_questions`** row — backfilled for old DBs), and no **`open_questions`** entry may have **`status: "open"`** (empty list after answered/promoted is OK once engaged). **`POST /sessions/{id}/runs`** uses the same rule and returns **409** when blocked. **`helpers.sync_optimization_allowed_after_participant_mutation`** sets **`optimization_allowed`** from intrinsic after participant definition/panel saves, each **`POST /sessions/:id/messages`**, and background derivation. The researcher **“'Run' button available.”** checkbox reflects **`!optimization_runs_blocked_by_researcher && optimization_allowed`**. **Agile** autoruns the first optimize once when intrinsic readiness is first satisfied (per-session `sessionStorage` guard). **Chat-triggered run start** is backend-orchestrated: during `POST /sessions/:id/messages`, the model returns structured run intent (`none` / `affirm_invite` / `direct_request`); backend only triggers optimize when that intent is positive **and** `can_run_optimization(...)` passes. Direct run requests with a closed gate receive a concise assistant explanation of what is missing instead of silently failing. **Waterfall** hides **Assumptions** in the Definition tab; **`ConfigPanel`** shows a short **cold-start** banner until the gate is engaged, and an **open-questions** banner while any question is still open. Study prompts: **Agile** elicits search strategy while applying a same-turn **panel default**; **Waterfall** elicits strategy via **`open_questions`** (options, no silent default algorithm in config).

**Frontend:** participant and researcher chat panels share **`frontend/src/shared/chat/ChatPanel.tsx`** (`ChatPanel`, `ChatComposer`, `ChatAiPendingBubble`), and shared message-bubble rendering lives alongside it under **`frontend/src/shared/chat/`**. Enter-to-send lives in `ChatPanel.tsx`. Messages show **optimistically**; with **Ask model** on, the user message appears immediately and the assistant reply returns on the fast path, while the Problem setup panel now shows definition/config spinners from session `processing` state until background derivation settles. Chat typing performance is improved via scroll-trigger key (message-based only), memoized `MessageBubbleList`, and a stable send callback. While a participant session has no loaded chat messages yet, the composer auto-focuses with a stronger pulse and the layout stays chat-first by hiding panels 2–3 while preserving chat at its normal 3/10 panel width. Both apps now use a similar top-level shape of **`components/`**, **`hooks/`**, and **`lib/`** for readability. Tutorial progression logic is centralized under **`frontend/src/tutorial/`** (`state.ts`, `events.ts`, `transitions.ts`, `anchors.ts`) so participant/researcher views share one event-driven step model. The participant app keeps its domain folders for **`client/chat/`**, **`client/problemDefinition/`**, **`client/problemConfig/`**, and **`client/results/`**, with shell components under **`client/components/`** and orchestration under **`client/hooks/useParticipantController.ts`**. The researcher app keeps `ResearcherApp.tsx` thin with stateful logic under **`frontend/src/researcher/hooks/useResearcherController.ts`**, shared non-React helpers under **`frontend/src/researcher/lib/`**, and presentational sections under **`frontend/src/researcher/components/`**. Shared status chips now cover both the model-key control and the backend connection control, with reusable dialog chrome under **`frontend/src/shared/components/`**. Backend targeting follows **browser user override → `VITE_API_BASE` → `http://127.0.0.1:8000`**, and both apps expose the active backend URL in the chip dialog. Panel 3 defaults to an interactive vehicle timeline built from enriched run payload data (`schedule.stops`, `vehicle_summaries`, `time_bounds`), highlights per-stop driver-preference cost when preferences are configured, keeps the visualization region scrollable for taller schedules, keeps the bottom action row anchored even before the first run, enables the compact **Edit** action only after a run result exists, and exposes **Run optimization**, **Cancel run** (cooperative stop via `POST /sessions/{id}/runs/cancel` while a solve is in flight), plus short-label result helpers (**Explain**, **Revert**) with tooltips. Participants can mark multiple prior runs as **Include as candidate** seeds for the next optimization; selected run tabs show a seed badge and optimize requests carry generic `candidate_seeds` metadata (problems may consume or ignore it). Run tabs can show the same “new results” indicator when a run completes while another tab is selected; term cards summarize weighted contributions from the saved weights. Algorithm, weights, and constraints in results come from the run snapshot only; missing keys show "not captured in this run snapshot". Run labels shown in both apps are session-local (`Run #1`, `Run #2`, ... within a session), not global database row ids.

**Session lifecycle:** **Terminate** keeps the row so the participant can still **read** chat/runs; **Delete** removes the row — the client returns to the start gate (saved token) when polling detects the session is gone.

## Problem modules (adding a benchmark)

**Quick start:** copy **`template_problem/`** (repo root) and follow **`template_problem/TEMPLATE_INSTRUCTIONS.md`**. The steps below summarize what the template covers.

1. **Directory:** Create a repo-root folder named **`{name}_problem/`**. The registry adds `repo_root` to `sys.path`, so module paths are `{name}_problem.study_port` etc. — no domain-prefixed filenames needed.

2. **Manifest:** Add **`mopt_manifest.toml`** at the domain root:
   ```toml
   port_module = "{name}_problem.study_port"
   port_attr   = "STUDY_PORT"
   ```

3. **Study port:** Implement `StudyProblemPort` (see `backend/app/problems/port.py`): `meta`, `sanitize_panel_config`, `parse_problem_config`, `solve_request_to_result`, brief/prompt hooks, `panel_patch_response_json_schema`, etc. Modularity changes (prompts, panel schema, weight definitions, frontend wiring) are encouraged. Solver logic changes (optimizer, evaluator, instance data) need maintainer sign-off.

4. **Registration:** Add the directory name to **`_BUILTIN_REL_DIRS`** in **`backend/app/problems/registry.py`**, or register via **`MOPT_PROBLEM_PATHS`** without editing the registry.

5. **Frontend:** Add a `frontend/index.ts` that exports `MODULE: ProblemModule` (see `backend/app/problems/port.py` for available hooks). Register it in **`frontend/src/client/problemRegistry.ts`** (the only file that names problem folders by ID) and add a Vite path alias in `vite.config.ts`.

6. **Tests:** Add tests under **`{name}_problem/tests/`** and include that path in **`pytest.ini`**.

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open the dev server root — **http://localhost:5173/** — for a small **homepage** with links to each app. You can still open them directly:

- Homepage: [http://localhost:5173/](http://localhost:5173/)
- Participant: [http://localhost:5173/client.html](http://localhost:5173/client.html)
- Researcher: [http://localhost:5173/researcher.html](http://localhost:5173/researcher.html)
- Session archive viewer (upload exported JSON locally; **Timeline** table + **Raw JSON**): [http://localhost:5173/analyzer.html](http://localhost:5173/analyzer.html)

The frontend now uses this backend priority: browser-local backend override from the chip dialog, then `VITE_API_BASE`, then `http://127.0.0.1:8000` (see `frontend/.env.example`).

Build:

```powershell
npm run build
```

Outputs under `frontend/dist/` (`index.html`, `client.html`, `researcher.html`, `analyzer.html`, assets).

## Tests

From the **repository root** (runs backend + domain packages per `pytest.ini`):

```powershell
.\venv\Scripts\pytest.exe -q
```

## Smoke checklist (manual)

1. Researcher token: list sessions, open one, export JSON (versioned **session archive**, `export_schema_version` **2**: session row, messages with `meta`, runs, snapshots, sorted **`timeline`** for review tools; filename `session-{id}-archive.json`). Up to **2000** brief/panel **snapshots** per session are retained (older pruned). Open the export in the analyzer **Timeline** tab to align chat, snapshots, and runs by time.
2. Participant token: **Start session** (no workflow choice; optional participant number), or expand **Past sessions on this browser** to **Resume** a stored session id (same token; local list only — not IP-based). Resume entries show participant number and session start time from server (or last local snapshot). After sign-in, the participant header shows **Participant #…** when the session has a number (from the server) and a short session id prefix; workflow mode is not labeled there, only a very thin cool vs warm top accent for discreet condition identification. New sessions default to **waterfall** with **`optimization_allowed: false`** and **`participant_tutorial_enabled: false`**. When the researcher enables tutorial, participants see a replayable step-by-step bubble guide (`Show tutorial`) that follows chat → upload → definition/config review → edits → run → config tweak → run again, with mode-aware copy (agile assumptions emphasis, waterfall open-question emphasis). Tutorial progression is tracked as explicit session state (`tutorial_step_override` + tutorial tracking flags) through the shared `frontend/src/tutorial` module, so researcher and participant stay synced on the same current step. Step 3 (`inspect-definition`) advances only after an explicit participant click on the Definition tab (not on mount or programmatic tab sync). Runs still unlock when not **researcher-blocked** and **intrinsic readiness** is met and/or the researcher clears the block and permit (see optimization eligibility above). Then: chat, edit/save panel JSON, run optimization (with mealpy installed), see run tab and violations.
3. Researcher: set **workflow mode** (agile vs waterfall), the **“'Run' button available.”** control (mirrors participant Run; uncheck to hard-block runs), and **Show participant tutorial** (session-level tutorial visibility toggle; default off). When tutorial is enabled, use the compact step dropdown next to that toggle to jump the participant bubble to a specific step (persisted per session). Selecting an earlier step rewinds tutorial-tracking state only (step progress flags), without deleting chat/runs/config artifacts. If a participant dismisses the tutorial bubble, the client persists that as tutorial-off for the session, so the researcher checkbox syncs back to unchecked on refresh/poll. Participant run controls follow **`computeCanRunOptimization`**. In session detail, workflow mode drives a stronger panel accent (cool/agile, warm/waterfall) so condition is easy to spot while controlling that session.
4. Researcher session list: each row shows participant number and start time; in session detail, participant number can be edited and saved.
5. Researcher session cleanup: the session list supports per-row multi-select, a visible **Select all visible** toggle, and **Delete selected** for batch cleanup.
6. Researcher run review: each run entry is collapsed by default in the researcher Runs panel; expand to inspect JSON and delete individual runs. Deleting a run asks for confirmation and refreshes from the server so the record stays gone.
7. Terminate session; participant next sync shows “start fresh”.
