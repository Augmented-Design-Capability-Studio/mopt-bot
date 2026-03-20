# MOPT study stack

Participant and researcher web apps plus a FastAPI backend for the workflow study described in `AI_INSTRUCTIONS.md`. Solver logic stays in `vrptw-problem/` (read-only for app work).

## Prerequisites

- Python 3.10+ and a venv at repo root (`venv/`)
- Node 20+ for the frontend

## Backend

From the repo root (PowerShell):

```powershell
.\venv\Scripts\pip.exe install -r vrptw-problem\requirements.txt -r backend\requirements.txt
Copy-Item backend\.env.example .env
# Edit .env: MOPT_CLIENT_SECRET, MOPT_RESEARCHER_SECRET, MOPT_CORS_ORIGINS, etc.
cd backend
..\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API: `http://127.0.0.1:8000`
- Health: `GET /health`
- Auth: `Authorization: Bearer <MOPT_CLIENT_SECRET>` (participant) or `<MOPT_RESEARCHER_SECRET>` (researcher)

Install **mealpy** (via `vrptw-problem/requirements.txt`) or optimization runs return a clear error.

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
2. Participant token: create session, send chat, edit/save panel JSON, run optimization (with mealpy installed), see run tab and violations.
3. Researcher: toggle “allow optimization” and workflow; participant sees gated runs when disabled.
4. Terminate session; participant next sync shows “start fresh”.
