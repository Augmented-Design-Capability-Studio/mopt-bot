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

**Participant chat (Gemini):** Python package **`google-genai`** (`pip` installs it via `backend/requirements.txt`). System prompt lives in `backend/app/prompts/study_chat.py` and is composed of three parts:
- **`STUDY_CHAT_SYSTEM_PROMPT`** — domain-neutral persona; stays general until the user describes the problem. When the user asks to "write code" or "implement", the agent produces solver configuration JSON (`panel_patch`) instead of source code and describes it conversationally. Constraints and objectives are revealed progressively — only when the user mentions related concepts. Weight keys use human-readable alias names (see below).
- **`STUDY_CHAT_WORKFLOW_WATERFALL`** / **`STUDY_CHAT_WORKFLOW_AGILE`** — injected based on `session.workflow_mode`; waterfall encourages full upfront specification, agile encourages frequent short runs. The LLM service (`backend/app/services/llm.py`) selects the right chunk from the session's `workflow_mode`.
- **`STUDY_CHAT_STRUCTURED_JSON_RULES`** — format rules for the structured JSON reply (`assistant_message` + `panel_patch`), including explicit valid/invalid `panel_patch` examples and four strict rules to prevent the model from generating non-compliant JSON (e.g. array weights, invented key names, or extra top-level keys).

The system instruction also includes the current panel JSON, compact summaries of the last 4 runs for result-comparison context, and hidden researcher steering notes (when present). Steering notes remain invisible to participants, are treated as highest-priority guidance for the very next assistant reply, and are applied with a natural conversational transition.

**Weight aliases:** Objective weights are referenced by human-readable alias names (`travel_time`, `fuel_cost`, `deadline_penalty`, `capacity_penalty`, `workload_balance`, `worker_preference`, `priority_penalty`) in the participant panel, in agent-generated `panel_patch` objects, and in `default_config.py`. The adapter (`backend/app/adapter.py` — `WEIGHT_ALIASES` + `translate_weights`) maps these to the internal `w1`–`w7` keys before calling the solver. This avoids leaking the numbered scheme to participants and makes the panel self-explanatory.

With **Ask model (requires API key).** enabled, structured replies merge `panel_patch` when applicable. After a successful optimization run, if **Ask model** is on, the frontend automatically posts a context message asking the agent to interpret and compare results. Similarly, manual panel saves trigger a model notification with the changed fields. New sessions start without panel JSON until the researcher **Push starter problem config** or the model/chat supplies `panel_patch`.

**Problem configuration panel** (`panels/ConfigPanel.tsx` + `panels/ProblemConfigBlocks.tsx`): the panel shows the solver config as structured natural-language blocks rather than a raw JSON textarea. Three sections appear as the config is populated — *Optimization Objectives* (each active weight alias shown with its human-readable label, description, and an editable numeric input), *Search Strategy* (algorithm, iterations, population size, random seed), and *Constraints & Preferences* (shift limit, fixed assignments, worker preferences). A collapsible "Show raw JSON" section is available for debugging. In view mode all inputs are disabled; clicking **Edit** enables them and **Save** commits the JSON normally.

**Frontend:** participant and researcher chat panels share **`frontend/src/shared/ChatPanel.tsx`** (`ChatPanel`, `ChatComposer`, `ChatAiPendingBubble`); Enter-to-send lives in that module. Messages show **optimistically**; with **Ask model** on, a **spinner** shows until Gemini returns. The participant app is split into a small **`frontend/src/client/ClientApp.tsx`** entry plus **`useParticipantController.ts`**, **`LoginGate.tsx`**, **`ParticipantShell.tsx`**, and panel/dialog/helper modules under **`frontend/src/client/`**. Panel 3 defaults to an interactive vehicle timeline built from enriched run payload data (`schedule.stops`, `vehicle_summaries`, `time_bounds`), keeps the visualization region scrollable for taller schedules, uses a compact **Edit** action for schedule editing, and exposes a **Recalculate cost** action next to the run cost. Run labels shown in both apps are session-local (`Run #1`, `Run #2`, … within a session), not global database row ids.

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

Dev server proxies `/api` → `http://127.0.0.1:8000` (see `frontend/vite.config.ts`). For a remote API, set `VITE_API_BASE` (see `frontend/.env.example`).

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
2. Participant token: **Start session** (no workflow choice), or expand **Past sessions on this browser** to **Resume** a stored session id (same token; local list only — not IP-based). New sessions default to **waterfall** with runs gated until the researcher sets **agile** and/or **Allow optimization runs**. Then: chat, edit/save panel JSON, run optimization (with mealpy installed), see run tab and violations.
3. Researcher: toggle “allow optimization” and workflow; participant sees gated runs when disabled.
4. Researcher run review: each run entry is collapsed by default in the researcher Runs panel; expand to inspect JSON and delete individual runs. Deleting a run asks for confirmation and refreshes from the server so the record stays gone.
4. Terminate session; participant next sync shows “start fresh”.
