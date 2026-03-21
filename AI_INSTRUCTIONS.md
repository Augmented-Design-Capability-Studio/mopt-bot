# AI build instructions

Use this document as the source of truth for implementers and for pasting into Cursor. Do not commit real secrets, API keys, or participant identifiers.

---

## 1. Non-negotiables

- **`vrptw-problem/` is read-only reference.** Do not edit, move, or refactor files inside it. All new application code lives outside that directory (e.g. `backend/`, `frontend/`).
- **Integration** is by **importing** or **calling** the existing Python API from `backend/` (e.g. a thin adapter module). Do not fork or duplicate solver logic under `backend/` unless the human maintainer explicitly approves; prefer importing the package as-is.
- If a change inside `vrptw-problem/` is unavoidable, **stop** and ask the maintainer first; do not patch it as part of app work.
- **Documentation:** Changes to **workflow**, **architecture**, or **repo layout** should include concise updates to **this file** and **`README.md`** (see Cursor rule `docs-sync`).

---

## 2. Goal

Build **two browser frontends** (participant **client** and **researcher**) and **one backend** suitable for a low-cost host (e.g. Raspberry Pi) to run a **user experience study**. The study examines how **workflow** affects optimization outcomes and experience: a **2×2** design (**Novice vs Expert** participants) × (**Agile vs Waterfall** interaction with the AI). In **Agile**, the user need not fully specify the problem up front; the agent may assume missing details, propose configuration or code-like artifacts, and run optimization frequently. In **Waterfall**, the user follows agent guidance to mature the problem formulation before any **RUN**; optimization runs should be gated accordingly. The underlying task is the VRPTW scenario in `vrptw-problem/`, but the product should **present** as a general metaheuristic-style assistant where required (see §7.3).

---

## 3. Tech stack

| Layer       | Choice                         | Notes |
|-------------|--------------------------------|--------|
| Frontend    | React + Vite                   | Two React entry apps (`client`, `researcher`) plus a static **homepage** (`index.html`) in dev/build for choosing which app to open; shared components as needed. |
| Backend     | FastAPI                        | Exposed via HTTPS; Cloudflare (or similar) in front when using a public domain. Participant chat uses Google **`google-genai`** (not the deprecated `google-generativeai` package). |
| Python      | Repo **`venv/`** at project root | Use `venv` for all Python tooling (`pip`, `pytest`, server run). |
| DB / cache  | SQLite                         | One database file per deployment is sufficient for sessions, chats, runs. |
| Deploy      | Frontend Vercel; backend own domain | Configure public API base URL and CORS for the Vercel origin; Raspberry Pi or other small host for API. |

---

## 4. Repository layout (target)

- **`frontend/`** — Participant **`client/`** UI and **`researcher/`** UI (separate areas or builds); optional root **`index.html`** homepage linking to both for local dev and static hosting; shared UI and API client code colocated as appropriate.
- **`backend/`** — FastAPI app, SQLite access, session and logging logic, **`run_server.py`** (Uvicorn entry with optional `--host` / `--port` / `--reload`; defaults from `.env`), editable **LLM system prompts** under **`backend/app/prompts/`** (e.g. participant chat persona), and a **thin adapter** that imports from **`vrptw-problem`** (no copies of that tree inside `backend/` unless explicitly approved).
- **`docs/`** (outside `vrptw-problem/`) — e.g. **`RASPBERRY_PI_SETUP.txt`** for clone → venv → install → run on a Pi. Other study or deploy notes may live in repo root or `docs/` as needed.

---

## 5. Reference material (read-only)

- **Domain and solver behavior:** `vrptw-problem/` — e.g. `DESCRIPTION.md`, `optimizer.py`, `evaluator.py`, `user_input.py`, `orders.py`, `vehicles.py`, `traffic_api.py`.
- **Study framing (optional):** `vrptw-problem/docs/` (e.g. proposed study materials).

Do **not** add application routes, study-only hacks, or deployment config **inside** `vrptw-problem/`.

---

## 6. Backend specifications

### 6.1 Responsibilities

- Accept a **gathered or assumed problem configuration** (neutral DTOs / JSON on the wire) and return a **solution** suitable for the UI: schedule (or equivalent), **cost** under the user- and agent-defined objective, and **constraint violation** summaries where applicable. For analysis, support scoring with a **reference** cost model when specified by the researcher.
- Preserve the **illusion** of a **general metaheuristic** assistant in external API names, payloads exposed to the client, and default error copy — without lying in ways that break consent; internal implementation may call VRPTW-specific code.
- **Persist** interactions the researcher needs: chat transcripts, panel state / edits, run requests and results, workflow mode, and timestamps.

### 6.2 Public API (shape)

- Implement **REST** with **FastAPI**. Support **local dev** and **production** behind Cloudflare (or similar) on a custom domain; document base URL and CORS for the Vercel frontend.
- **Authentication:** simple **shared-secret or password** per deployment, supplied via `.env` (separate values for **client** vs **researcher** if needed). All mutating and session-sensitive routes require auth.
- Prefer **stable, domain-neutral** resource names (examples: sessions, messages, runs, exports — e.g. `/session`, `/chat`, `/solve` or RESTful `/sessions/{id}/...`). Initial version does **not** require WebSockets; polling or short requests are fine.
- **SQLite** as system of record for sessions, chats, configurations, and run history. Provide **GET** (or equivalent) export endpoints for **JSON** logs and run configs for offline analysis.
- **Solve** endpoint: accept a **problem configuration** JSON (neutral schema on the wire), return **solution**, **cost**, and **violations** in a stable shape. Validate input; on failure return **clear, safe** errors (no raw stack traces to clients by default).
- **Responses and logs** shown to participants must not **name** VRPTW, QuickBite, or internal zone identifiers unless the **user** introduced those terms in chat.

### 6.3 Adapter to `vrptw-problem`

- The VRPTW solver is driven by a **JSON-shaped configuration** aligned with what the existing code expects; the adapter maps **neutral HTTP JSON → that structure** (and maps results back to neutral DTOs). Study the current modules to see how configuration is built and consumed (e.g. `user_input`, `optimizer`, `evaluator`).
- Enforce **validation** before calling the solver; return structured errors for invalid or incomplete configs instead of opaque 500s when possible.
- **Reproducibility:** document and fix **RNG seeds** (and any time-dependent behavior) so the same configuration yields the same result when that is a study requirement.
- **Timeouts and cancellation:** long runs must not block the process indefinitely; support **request timeouts** and **abort** where the stack allows it.

### 6.4 Environment & config

- Use a **`.env`** (or equivalent) for backend: listen host/port (`MOPT_HOST`, `MOPT_PORT`), **database path**, **public URL** (`MOPT_PUBLIC_URL`) for redirects or links behind Cloudflare etc., **CORS** allowed origins, **client/researcher** auth secrets, and any **Gemini** or other provider keys if proxied server-side. **`MOPT_DEFAULT_GEMINI_MODEL`** defaults to **`gemini-3-flash-preview`** when a session has no stored model id (see `backend/app/config.py` and `backend/.env.example`). Model ids vary by API version and key; participant/researcher UIs suggest presets and allow typing any id.
- Prefer **`backend/run_server.py`** to start Uvicorn so host/port match `.env` without repeating flags; optional CLI overrides for ad-hoc runs.
- **Never** commit real `.env` values. Document variable **names** and example **placeholders** only in the repo.

### 6.5 Agent / LLM prompts

- Use the **`google-genai`** Python SDK for Gemini (`genai.Client`, **`chats.create` + `send_message`** with history and config), not deprecated `google-generativeai` or ad-hoc one-shot `generate_content` for conversational turns unless there is a clear non-chat reason.
- Store **system prompts** and reusable instruction blocks in **`backend/app/prompts/`** (e.g. `study_chat.py`); import them from services—do not embed long prompt strings in route handlers.
- **Framing (participant-visible illusion):** The assistant should behave as a **general metaheuristic optimization** colleague (encodings, operators, objectives, parameters). The **backend** evaluates a **single hard-coded benchmark instance**; the model must **not** treat that instance as the participant’s freely chosen real-world problem or name **routing / fleet / scheduling / vehicles / deliveries** domains unless the **user** did so first. **Greetings** and small talk must stay **domain-neutral** (no fleet or route examples). The **actionable** model output for the UI is **solver configuration JSON** (`panel_patch` merged into the panel), **not** a story about generating shipping code—avoid implying the participant is building a full custom solver from scratch in chat.
- Structured replies use **`STUDY_CHAT_STRUCTURED_JSON_RULES`** in the same module; keep rules aligned with §7.3.
- Restart the API (or use `--reload` in dev) after editing prompt files.

---

## 7. Frontend specifications

### 7.1 Client / participant flows

The participant **does not** choose Agile vs Waterfall at session start; that mode is assigned by the **researcher** (see §7.2). The client offers **Start session** plus **Past sessions on this browser** (collapsible on the login gate): **localStorage** keeps a bounded list of session ids the user has started or left on this device; **Refresh list** + **Resume** use the saved **access token** and `GET /sessions/:id` (and messages/runs) to reopen. **Terminated** sessions resume in the existing read-only mode. **Forget** drops an id from local storage only. Do **not** implement “past sessions by IP” on the server for the shared participant token — that would expose other participants’ sessions.

The **client** UI has at least **three panels:** (1) **Chat and upload**, (2) **Information and assumption / controls**, (3) **Visualization and results**.

- The user states the problem in chat and may **upload** files per agent guidance. **Upload is simulated** for the study: the backend is fixed to the canonical scenario; the agent should **acknowledge** uploads and answer **as if** data were supplied. Canonical inputs include the **travel time matrix** and **30 orders** (see `vrptw-problem` data and docs).
- **New sessions** ship with **no** problem JSON on panels 2–3: the **Start session** action must clear the configuration textarea immediately and keep it **empty** until the **researcher** uses **Push starter problem config** (mediocre default GA JSON on the server) or the participant/agent updates the panel. The participant must not see leftover JSON from a prior session when beginning a new one. Depending on **Agile vs Waterfall**, the agent surfaces **constraints and objectives** on panel 2 once that exists; the user may edit values or options. Panel 2 state must stay in sync with the **JSON configuration** sent to the solver; when the user changes controls, the **chat** should acknowledge the update.
- When an **optimization run** completes, show results in panel 3 (**tabs** if multiple runs). For this problem, include an **editable schedule** (edit mode) and **cost** for that run per the configured objective. **Manipulated** schedules should be reflected in chat. **Constraint violations** should update panel 2 when run results exist.
- Each **RUN** produces a **chat** bubble (acknowledgment); the **result summary** may follow as the next bubble.
- **Saving** edits on panels 2 and 3 posts a **chat acknowledgment**. While a panel is in **edit mode**, it is visually highlighted and the user **cannot** use other panels until **save** or **exit edit** (per your UX rules).
- **Chat responsiveness:** Outgoing messages render **immediately** (optimistic). If **Ask model** is on, show a **spinner** in the assistant area until the model reply arrives. The **Model / API key** control should reflect whether a key is configured (refresh session when opening the dialog; after save, update status from the server response).
- **Session sync races:** In-flight `GET` session / messages / runs must **not** apply after the user **Leave**s or **Start session** (another id). Use a **session id ref** (or equivalent) so stale HTTP responses cannot repopulate state from a **previous** session. **Problem panel hydration:** use an explicit mode — after **POST /sessions**, stay in **empty-until-server-panel** until `panel_config` is non-empty on the server (researcher push, etc.) or the client applies JSON from **save** / **chat** `panel_config`; then **follow** the server on each poll. While the server panel is still empty, **do not** push `""` into the textarea on every poll (that would erase in-progress edits). While the participant is in **problem configuration edit mode**, **do not** overwrite the textarea from `GET` session (polling would undo clearing the JSON); after **Save** or **Cancel**, resume mirroring from the server. The **mount** `syncSession` effect should pass **AbortSignal** + **abort on cleanup** so **React Strict Mode** does not double-fetch the same session snapshot.

### 7.2 Researcher flows

The **researcher** UI has a **left panel** for session list and management. Selecting a session shows **chat**, **runs**, and **edits**.

- **Delete session:** the participant client must detect removal (404 / gone responses on sync) and return to the **same gate as initial login** (token still in browser storage) with copy explaining the session was deleted; **Start session** creates a new UUID.
- **Terminate session:** the participant **keeps read access** to GET session, messages, and runs so they can review history; **writes** (chat, uploads, panel saves, runs, model key save) are rejected by the API. The client **greys out** chat and actions and shows an **info banner** with **Start new session** while leaving panels readable.
- **Researcher messages** in chat are **invisible** to the participant; only the researcher sees their own steering messages.
- The researcher sets **Agile vs Waterfall** mode for the agent driving that session and may **push** the canonical mediocre starter problem JSON to the participant session when the study design calls for it.

### 7.3 UX constraints

- Do **not** surface **VRPTW**, **QuickBite**, or **internal zone names** in UI copy or API-visible labels unless the **participant** used those terms first.
- **Chat UI** (participant and researcher steering): shared **`frontend/src/shared/ChatPanel.tsx`** (`ChatPanel` + `ChatComposer` + optional **`ChatAiPendingBubble`**). Enter sends, Shift+Enter newline — implemented **inside** that module (not a separate keyboard file).
- **Optimistic chat:** After send, the user’s message should **appear immediately** in the log (do not block on persistence or model latency). When the participant enables **Ask model** and a reply is pending, show a **spinner** (“Thinking…”) in the assistant area until the server returns. Researcher steering messages should also appear immediately (optimistic row, then replace with the server `MessageOut`).
- **Password** protection for both apps; secrets from `.env` (see §6.4).
- The agent should **not** dump large explanations into panel 2 **without** prior chat context — especially under **Waterfall**.
- Chat responses should stay **concise** by default.

### 7.4 State & data

- **Authoritative** session history (chat, runs, configs) lives on the **server** (SQLite). The **browser** may cache a **local copy** for resilience (e.g. offline draft or re-open) and for **participant review** of their own past sessions; define **merge rules** on reconnect (server wins for conflicts unless you specify otherwise).
- The **researcher** sees **all** server-stored sessions. If a session is **deleted** or **terminated** while the client is open, the next sync should surface the UX in §7.2.

### 7.5 Shared components between researcher and client

- **Model / API key setup:** a **chip** (or control) opens a dialog to paste an **API key** and select **model** (start with **Google Gemini** “Flash” tier or current equivalent). Prefer **Vercel AI SDK** if it fits the stack. **Keys** are stored **server-side** (encrypted at rest if feasible) so sessions can resume; the researcher may **push** a key to the participant flow; participants may also supply their own.
- Structure the codebase so **other providers** can be added without rewriting the whole chat layer.
- **Chat + model calls** originate from the **participant client**; the researcher **interferes** (steering messages) through the researcher UI without exposing those lines to the participant.

### 7.6 Look and feel

- The interface design should **avoid high-saturation colors**. Use **moderate or muted palettes** to minimize eye fatigue during long study sessions.
- It is acceptable—and even preferable for this phase—to keep the **visual design “retro”** or reminiscent of classical **engineering/scientific software** (think understated, functional interfaces: clear panels, plain backgrounds, minimal visual distractions).
- Avoid glossy, hyper-modern, or overly animated elements. Favor classic typographic hierarchy, static icons, and clear, separated regions.
- When in doubt, prefer **simplicity and readability** over flash or trendiness. The visual hierarchy should reinforce workflows rather than obscure them.
- Maintain **strong accessibility** in color choices—ensure sufficient contrast for those with color vision differences, but stay within the muted/retro theme.
- The overall aesthetic should evoke reliability and clarity; playful or “modern consumer app” motifs are discouraged for now.


---

## 8. Logging, study, and ethics

- **Chat logs** are the primary artifact; additional events (timestamps, run IDs, mode changes, exports) may be added later.
- **Do not** persist **API keys** or passwords in application logs; redact or hash identifiers if logs are shared.
- The study materials are under IRB review. Overall, this study presents minimal risk. 

---

## 9. Quality bar

- **Tests:** core adapter and API handlers should have **unit tests** where practical; at least a **manual smoke checklist** for client, researcher, and solve path before demos.
- **Accessibility:** keyboard access to the three client panels and dialogs; visible focus; reasonable contrast (target **WCAG-oriented** behavior without blocking on a full audit unless required).
- **Browsers:** latest **Chrome** and **Edge** for the study; note if Safari/Firefox are best-effort.
- The backend should support **one** active study session with **1–3** concurrent users without noticeable UI lag.
- **Cold start** under **30 seconds** on the target Pi-class host.
- Typical **chat** and **solve** requests: **1–5 s** when the model and solver are warm; allow up to **~30 s** for occasional heavy runs with **loading** feedback.
- **Storage** writes should be **durable** and **bounded**; recover cleanly from abrupt shutdown where SQLite allows.
- **Memory** steady-state **under ~1 GB** on the server; avoid leaks across long sessions.
- **CPU-heavy** work: **timeouts**, **cancellation**, and user-visible **timeout** messages.
- **Disk:** avoid chatty logging on **SD cards**; rotate or buffer logs if needed.
- **No** long-lived WebSockets required initially; **HTTP polling** or short requests are acceptable on low bandwidth.
- On overload, **fail gracefully** (clear errors, retry guidance) rather than wedging the process.

---

## 10. Out of scope (explicit)

- **No** edits or new features **inside** `vrptw-problem/`.
- **No** production multi-tenant billing, full OAuth identity platform, or mobile native apps unless later specified.
- **No** requirement for real file ingestion that changes the canonical problem data **without** maintainer approval (simulated upload only for v1).

---

## 11. Definition of done

- [ ] `vrptw-problem/` **unchanged** (`git status` clean under that path).
- [ ] **Backend** starts locally with documented **`.env.example`** (no secrets in repo); **`backend/run_server.py`** (or equivalent) documented for host/port.
- [ ] **Client** and **researcher** frontends **build** and run locally against the API.
- [ ] **Auth** enforced on API; CORS correct for Vercel + local dev.
- [ ] At least one **end-to-end path**: session → chat → panel edits → solve → result + cost + violations.
- [ ] **Export** of session JSON available for the researcher.

---

## 12. Open questions

- *(Add bullets here as decisions land — e.g. exact neutral JSON schema, debrief wording, encryption for stored keys.)*
