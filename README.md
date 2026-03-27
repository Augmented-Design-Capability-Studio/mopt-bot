# MOPT study stack

Participant and researcher web apps plus a FastAPI backend for the workflow study described in `AI_INSTRUCTIONS.md`. Solver logic stays in `vrptw-problem/` (read-only for app work).

## Prerequisites

- Python 3.10+ and a venv at repo root (`venv/`)
- Node 20+ for the frontend

## Backend

Install dependencies once (repo root):

**Windows (PowerShell)**

```powershell
.\venv\Scripts\pip.exe install -r vrptw-problem\requirements.txt -r backend\requirements.txt
Copy-Item backend\.env.example .env
# Edit `.env` (real secrets). `.env.example` is only a template — the server does not read it.
# Set MOPT_CLIENT_SECRET, MOPT_RESEARCHER_SECRET, MOPT_CORS_ORIGINS, MOPT_HOST, MOPT_PORT,
# MOPT_DEFAULT_GEMINI_MODEL (defaults to gemini-3-flash-preview), etc.
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

Participant chat uses **Gemini** via **`google-genai`** (chat sessions). Prompts live under **`backend/app/prompts/`**.

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

Install **mealpy** (via `vrptw-problem/requirements.txt`) or optimization runs return a clear error.

**Participant chat (Gemini):** Python package **`google-genai`** (`pip` installs it via `backend/requirements.txt`). Prompt fragments live in `backend/app/prompts/study_chat.py`, and the LLM orchestration in `backend/app/services/llm.py` now splits the work into visible chat reply, hidden brief update, and config derivation tasks.
- **Fast chat path:** `POST /sessions/:id/messages` now returns the assistant chat reply first, then continues brief/config derivation in a background thread. Session JSON exposes `processing` state (`brief_status`, `config_status`, `processing_revision`, `processing_error`) so the frontend can show panel-level pending state without blocking chat. Optional body field **`skip_hidden_brief_update`** (with `invoke_model`): visible reply only, no background brief merge — used after participant-driven definition/config saves and snapshot restores so the model does not overwrite stored state; open-question answer flows still run full derivation.
- **Visible/hidden output separation:** participant-visible replies remain plain conversational text. Hidden structured patch keys (for example `problem_brief_patch`) are used only in backend brief-update flow and are stripped from visible chat if the model leaks them.
- **`STUDY_CHAT_SYSTEM_PROMPT`** — domain-neutral persona; stays general until the user describes the problem. When the user asks to "write code" or "implement", the agent updates the problem brief (not source code) and the backend derives solver configuration JSON from that brief. Constraints and objectives are revealed progressively — only when the user mentions related concepts. Weight keys use human-readable alias names (see below).
- **`STUDY_CHAT_WORKFLOW_WATERFALL`** / **`STUDY_CHAT_WORKFLOW_AGILE`** — injected based on `session.workflow_mode`; waterfall encourages full upfront specification, agile encourages frequent short runs. The LLM service (`backend/app/services/llm.py`) selects the right chunk from the session's `workflow_mode`.
- **Task and phase guidance** — separate prompt blocks guide visible chat, hidden brief updates, workflow-specific behavior, and phase-specific behavior (`discovery`, `structuring`, `configuration`) so `agile` and `waterfall` can diverge further later without another large prompt rewrite.
- **`STUDY_CHAT_STRUCTURED_JSON_RULES`** / hidden brief-update rules — format rules for structured brief updates plus cleanup controls. Normal turns remain additive; cleanup/reorganize turns can set `replace_editable_items` / `replace_open_questions` for holistic replacement.

The chat system instruction includes the current **problem brief** middle layer (including hidden system context for prompting), compact summaries of the last 4 runs for result-comparison context, and hidden researcher steering notes (when present). Steering notes remain invisible to participants, are treated as highest-priority guidance for the next reply/brief update, and are applied with a natural conversational transition.

After the visible reply is saved, backend derives the brief and then the `problem` panel block from the latest brief. If model-based config derivation fails (or no key is configured), backend falls back to deterministic regex parsing (`derive_problem_panel_from_brief`) so manual definition saves and sync actions still work. Cleanup requests (consolidate/remove/reorganize) are detected in backend orchestration and routed through holistic replacement mode so redundant gathered/assumption rows can be reliably removed.

**Weight aliases:** Objective weights are referenced by human-readable alias names (`travel_time`, `fuel_cost`, `deadline_penalty`, `capacity_penalty`, `workload_balance`, `worker_preference`, `priority_penalty`) in the participant panel, in agent-generated `panel_patch` objects, and in `default_config.py`. The adapter (`backend/app/adapter.py` — `WEIGHT_ALIASES` + `translate_weights`) maps these to the internal `w1`–`w7` keys before calling the solver. This avoids leaking the numbered scheme to participants and makes the panel self-explanatory.

**Driver preferences defaulting:** participant-facing runs now treat `driver_preferences` as **opt-in**. If the field is omitted from `problem`, backend solve/evaluate paths default to `[]` (no implicit driver-trait penalties). Canonical/official research scoring can still use canonical defaults when explicitly evaluated via `vrptw-problem/researcher/official_evaluator.py`.

With **Ask model (requires API key).** enabled, structured chat replies update the editable `problem_brief` middle layer, then backend derives the final `panel_config` from that updated brief. After a successful optimization run, if **Ask model** is on, the frontend automatically posts a context message asking the agent to interpret and compare results. **Run-ack rules** prevent the agent from contaminating the problem definition with run-result narrative (costs, violation counts); it may still suggest one or two targeted config refinements. Similarly, manual definition/config saves trigger a model notification with the changed fields. New sessions start without panel JSON until the researcher **Push starter problem config** or the participant flow creates one; in `waterfall`, backend keeps deriving and syncing the `problem` block from the saved brief so the config stays aligned with the participant's current definition instead of a stale starter. There is no separate automatic "test config" fallback beyond the explicit researcher-pushed starter.

The chat footer includes a simulated **`Upload file(s)...`** action. In logistics-style conversations, the assistant should request uploads for order data plus driver information/preferences, acknowledge uploads as if ingested, and may reference city-traffic API assumptions (time-of-day traffic and disruptions) while reasoning about schedules.

When the participant saves an answer to an open question, the brief-update task is prompted to close it by omitting it from `open_questions`; the merge logic preserves answered state when the model omits status/answer_text.

While background brief/config derivation is pending, **Problem Config** and **Raw JSON** show a grey overlay over the scroll area (with a **90s** client timeout that unlocks and warns if the server stays pending). New definition rows use a shared placeholder until the user saves non-placeholder text (see `frontend/src/client/problemDefinition/constants.ts`).

**Problem setup panel** now has three tabs: **Definition**, **Problem Config**, and **Raw JSON**. `frontend/src/client/problemDefinition/DefinitionPanel.tsx` renders the editable middle layer with gathered info, assumptions, and open questions. Open questions use stable objects with answer state (`{id, text, status, answer_text}`), and the Definition UI is intentionally geared toward answering/toggling status instead of freeform rewriting existing question text. Definition content editing now uses inline element-level drafts (Save/Cancel per element) and no longer requires a global **Edit definition** gate; the main Definition action row is used for persisting the accumulated brief and optional sync-to-config. This behavior is currently the same in both `agile` and `waterfall` so workflow-specific divergence can be added later without changing data shape. Hidden system context can still exist in the stored brief for prompting, but it is not shown to participants. `client/problemConfig/ProblemConfigBlocks.tsx` renders the solver config as structured natural-language blocks — *Optimization Objectives*, *Search Strategy*, and *Constraints & Preferences* — and shows an explicit empty-state message when no solver config exists yet. In `waterfall`, that empty config is expected early on, but once the brief has enough configuration signal the backend refreshes the `problem` block from the confirmed brief even if the model missed `panel_patch` on that turn. Numeric targets written into the definition, such as a workload balance weight of `50`, are carried through into the derived config. Weight objects and algorithm-parameter objects are treated as full replacements when chat updates them, so stale starter values do not linger after the participant changes objectives or switches algorithms. Sync is bidirectional: definition edits rebuild config, and config edits write stable config-derived facts back into the saved definition so later chat and definition syncs stay aligned. Config-linked definition facts such as algorithm choice, population size, epochs, weights, and algorithm parameters are now reconciled by semantic slot, so newer values replace older conflicting ones instead of accumulating duplicates. The **Raw JSON** tab is a read-only combined snapshot of both the problem definition JSON and the current problem config JSON; when no config has been saved yet it shows an empty object instead of `null`. For debugging, the Definition tab also exposes a **Sync to config** action that rebuilds the saved config from the saved definition on demand. **Definition tab** has **Save**, **Load**, and **Sync to config**; **Config tab** has **Edit** and **Load config** (drop-up with **From most recent run** and **Load from snapshot...**). The snapshot dialog lists server-stored brief+panel snapshots; restoring triggers chat acknowledgement. `GET /sessions/:id/snapshots` returns snapshot summaries for the Load-from-snapshot UI. The participant UI still does not expose an `only_active_terms` checkbox; objective scoring defaults to explicit-only when omitted. Researchers can control this via a dedicated toggle in the researcher session controls.

**Frontend:** participant and researcher chat panels share **`frontend/src/shared/chat/ChatPanel.tsx`** (`ChatPanel`, `ChatComposer`, `ChatAiPendingBubble`), and shared message-bubble rendering lives alongside it under **`frontend/src/shared/chat/`**. Enter-to-send lives in `ChatPanel.tsx`. Messages show **optimistically**; with **Ask model** on, the user message appears immediately and the assistant reply returns on the fast path, while the Problem setup panel now shows definition/config spinners from session `processing` state until background derivation settles. Chat typing performance is improved via scroll-trigger key (message-based only), memoized `MessageBubbleList`, and a stable send callback. While a participant session has no loaded chat messages yet, the composer auto-focuses with a stronger pulse and the layout stays chat-first by hiding panels 2–3 while preserving chat at its normal 3/10 panel width. Both apps now use a similar top-level shape of **`components/`**, **`hooks/`**, and **`lib/`** for readability. The participant app keeps its domain folders for **`client/chat/`**, **`client/problemDefinition/`**, **`client/problemConfig/`**, and **`client/results/`**, with shell components under **`client/components/`** and orchestration under **`client/hooks/useParticipantController.ts`**. The researcher app keeps `ResearcherApp.tsx` thin with stateful logic under **`frontend/src/researcher/hooks/useResearcherController.ts`**, shared non-React helpers under **`frontend/src/researcher/lib/`**, and presentational sections under **`frontend/src/researcher/components/`**. Shared status chips now cover both the model-key control and the backend connection control, with reusable dialog chrome under **`frontend/src/shared/components/`**. Backend targeting follows **browser user override → `VITE_API_BASE` → `http://127.0.0.1:8000`**, and both apps expose the active backend URL in the chip dialog. Panel 3 defaults to an interactive vehicle timeline built from enriched run payload data (`schedule.stops`, `vehicle_summaries`, `time_bounds`), keeps the visualization region scrollable for taller schedules, keeps the bottom action row anchored even before the first run, enables the compact **Edit** action only after a run result exists, and exposes a more prominent **Run optimization** primary action plus a **Recalculate cost** action next to the run cost. Algorithm, weights, and constraints in results come from the run snapshot only; missing keys show "not captured in this run snapshot". Run labels shown in both apps are session-local (`Run #1`, `Run #2`, ... within a session), not global database row ids.

**Session lifecycle:** **Terminate** keeps the row so the participant can still **read** chat/runs; **Delete** removes the row — the client returns to the start gate (saved token) when polling detects the session is gone.

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

The frontend now uses this backend priority: browser-local backend override from the chip dialog, then `VITE_API_BASE`, then `http://127.0.0.1:8000` (see `frontend/.env.example`).

Build:

```powershell
npm run build
```

Outputs under `frontend/dist/` (`index.html`, `client.html`, `researcher.html`, assets).

## Tests

```powershell
cd backend
..\venv\Scripts\python.exe -m pytest tests\ -v
```

## Smoke checklist (manual)

1. Researcher token: list sessions, open one, export JSON.
2. Participant token: **Start session** (no workflow choice; optional participant number), or expand **Past sessions on this browser** to **Resume** a stored session id (same token; local list only — not IP-based). Resume entries show participant number and session start time from server (or last local snapshot). New sessions default to **waterfall** with runs gated until the researcher sets **agile** and/or **Allow optimization runs**. Then: chat, edit/save panel JSON, run optimization (with mealpy installed), see run tab and violations.
3. Researcher: toggle “allow optimization” and workflow; participant sees gated runs when disabled.
4. Researcher session list: each row shows participant number and start time; in session detail, participant number can be edited and saved.
5. Researcher session cleanup: the session list supports per-row multi-select, a visible **Select all visible** toggle, and **Delete selected** for batch cleanup.
6. Researcher run review: each run entry is collapsed by default in the researcher Runs panel; expand to inspect JSON and delete individual runs. Deleting a run asks for confirmation and refreshes from the server so the record stays gone.
7. Terminate session; participant next sync shows “start fresh”.
