---
name: MOPT Project Overview
description: Purpose, study design, and technology stack of the mopt-bot project
type: project
---
# MOPT (Metaheuristic Optimization Portal) — Project Overview

**Purpose:** A UX study platform examining how workflow mode affects optimization outcomes and user experience. Participants interact with an AI assistant to define and solve optimization problems; researchers observe and can inject steering notes.

**Study Design:** 2×2 experiment — (Novice vs Expert) × (Agile vs Waterfall workflow mode)

- **Agile mode**: AI can assume missing details, propose configs, and run optimization frequently without full upfront specification
- **Waterfall mode**: Requires full problem specification upfront; explicit gates before optimization (first user chat engagement + no open questions with "open" status)

**Underlying problems (disguised from participants as generic metaheuristic optimization):**
- Primary: Vehicle Routing Problem with Time Windows (VRPTW) — `vrptw_problem/`
- Toy: 0/1 Knapsack — `knapsack_problem/`
- Problem selected per-session via `test_problem_id`; domain identity never disclosed to participant

**Tech Stack:**
| Layer | Tech |
|-------|------|
| Frontend | React 18 + Vite + TypeScript (3 SPAs: client, researcher, analyzer) |
| Backend | FastAPI + Uvicorn (Python) |
| Database | SQLite (via SQLAlchemy 2.0) |
| LLM | Google Gemini via `google-genai` SDK (NOT the deprecated `google-generativeai`) |
| Solver | MEALpy 3.0+ (GA, PSO, SA, SwarmSA, ACOR) |
| Charting | Recharts 3.8 |
| Markdown | react-markdown + remark-gfm |

**Deployment target:** Low-cost hosting (Raspberry Pi), backend on custom domain, frontend on Vercel.

**Why:** Study is investigating how specifying a problem upfront (waterfall) vs. iteratively (agile) affects optimization quality and user satisfaction.
**How to apply:** When suggesting changes, always consider the study integrity — don't accidentally collapse workflow mode differences, don't expose domain identity to the participant side.