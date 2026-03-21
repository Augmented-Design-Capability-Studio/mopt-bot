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

**Participant chat (Gemini):** Python package **`google-genai`** (`pip` installs it via `backend/requirements.txt`). System prompt: `backend/app/prompts/study_chat.py` — frames the study as **general metaheuristic / solver-configuration** help; the run uses a **fixed benchmark** on the server; **`panel_patch`** is **solver JSON**, not source code. With **Ask model (requires API key).** enabled, structured replies merge `panel_patch` when applicable. New sessions start without panel JSON until the researcher **Push starter problem config** (see researcher UI) or the model/chat supplies `panel_patch`; the participant client uses an **empty-until-server-panel** hydration mode so polling does not overwrite the cleared textarea until the server has real panel JSON (then it follows the server).

**Frontend:** participant and researcher chat panels share **`frontend/src/shared/ChatPanel.tsx`** (`ChatPanel`, `ChatComposer`, `ChatAiPendingBubble`); Enter-to-send lives in that module. Messages show **optimistically**; with **Ask model** on, a **spinner** shows until Gemini returns.

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
4. Terminate session; participant next sync shows “start fresh”.
