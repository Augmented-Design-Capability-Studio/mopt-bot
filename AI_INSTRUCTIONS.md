# AI build instructions

Use this document as the source of truth for implementers and for pasting into Cursor. Do not commit real secrets, API keys, or participant identifiers.

---

## 1. Non-negotiables

- **`vrptw-problem/`** is primarily **reference** for the domain solver. Prefer integrating via `backend/app/adapter.py`. Changes inside `vrptw-problem/` (e.g. cooperative cancel hooks, richer visit records) require **explicit maintainer approval**; do not refactor it casually.
- **Integration** is by **importing** or **calling** the existing Python API from `backend/` (e.g. a thin adapter module). Do not fork or duplicate solver logic under `backend/` unless the human maintainer explicitly approves; prefer importing the package as-is.
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
- **`backend/`** — FastAPI app, SQLite access, session and logging logic, **`run_server.py`** (Uvicorn entry with optional `--host` / `--port` / `--reload`; defaults from `.env`), editable **LLM system prompts** under **`backend/app/prompts/`** (e.g. participant chat persona), and a **thin adapter** that imports from **`vrptw-problem`** (no copies of that tree inside `backend/` unless explicitly approved). Sessions API lives in **`backend/app/routers/sessions/`** as a package: `router.py` (routes), `helpers.py`, `intent.py`, `context.py`, `sync.py`, `derivation.py`.
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
- **Persist** interactions the researcher needs: chat transcripts, panel state / edits, the editable **problem brief** middle layer (gathered info, assumptions, open questions, system facts), run requests and results, workflow mode, and timestamps. **Session snapshots** (`SessionSnapshot` model) store brief+panel state before runs and on manual saves; kept per session (last 10) for continuity. **`GET /sessions/:id/snapshots`** returns snapshot summaries for the Load-from-snapshot UI; restore posts to PATCH panel or PATCH problem-brief with chat acknowledgement.

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
- **Weight aliases:** `backend/app/adapter.py` defines `WEIGHT_ALIASES` mapping human-readable keys (`travel_time`, `fuel_cost`, `deadline_penalty`, `capacity_penalty`, `workload_balance`, `worker_preference`, `priority_penalty`) to the internal `w1`–`w7` keys expected by the solver. `translate_weights()` is called inside `parse_problem_config` so both alias names and `w1`–`w7` keys are accepted; alias names are preferred for all new panel configs and agent-generated patches.
- **Driver preference semantics:** participant-facing solve/evaluate flows treat `driver_preferences` as explicit-only input. If omitted, default to an empty list (no implicit driver-trait penalties). `parse_problem_config` validates each rule (`vehicle_idx` 0–4, known `condition`, nonnegative `penalty`, optional `zone` / `order_priority` / `limit_minutes` / `aggregation` / legacy `hours`). **`locked_assignments`** must map task indices **0–29** to vehicles **0–4** with no duplicate tasks. Run metrics expose **`driver_preference_units`** (alias `driver_preference_penalty`) as raw preference cost units before w6 — not minutes of travel time.
- **Reproducibility:** document and fix **RNG seeds** (and any time-dependent behavior) so the same configuration yields the same result when that is a study requirement.
- **Violation consistency:** the adapter uses the optimizer's `visits` from its final `evaluate_solution` (not a re-simulation) so the violation block and timeline per-stop data share the same underlying evaluation. Cost and violations reflect the user's configured objectives. Visit payloads may include **`preference_penalty_units`** / **`preference_conflict`** for per-stop driver-preference cost (per-visit rules only).
- **Timeouts and cancellation:** long runs use a server timeout (`solve_timeout_sec`). **Cooperative cancel:** while `POST /sessions/{id}/runs` (optimize) is executing, `POST /sessions/{id}/runs/cancel` or **`POST /sessions/{id}/optimization/cancel`** (same behavior) sets a per-session flag; the MEALpy objective checks it and stops early (`OptimizationCancelled` → stored run with “Optimization cancelled”). The participant **Cancel run** button calls **`/optimization/cancel`** so strict proxies are less likely to mishandle `/runs/cancel`.

### 6.4 Environment & config

- Use a **`.env`** (or equivalent) for backend: listen host/port (`MOPT_HOST`, `MOPT_PORT`), **database path**, **public URL** (`MOPT_PUBLIC_URL`) for redirects or links behind Cloudflare etc., **CORS** allowed origins, **client/researcher** auth secrets, and any **Gemini** or other provider keys if proxied server-side. **`MOPT_DEFAULT_GEMINI_MODEL`** defaults to **`gemini-3-flash-preview`** when a session has no stored model id (see `backend/app/config.py` and `backend/.env.example`). Model ids vary by API version and key; participant/researcher UIs suggest presets and allow typing any id.
- Prefer **`backend/run_server.py`** to start Uvicorn so host/port match `.env` without repeating flags; optional CLI overrides for ad-hoc runs.
- **Never** commit real `.env` values. Document variable **names** and example **placeholders** only in the repo.

### 6.5 Agent / LLM prompts

- Use the **`google-genai`** Python SDK for Gemini (`genai.Client`, **`chats.create` + `send_message`** with history and config), not deprecated `google-generativeai` or ad-hoc one-shot `generate_content` for conversational turns unless there is a clear non-chat reason.
- Store **system prompts** and reusable instruction blocks in **`backend/app/prompts/`** (e.g. `study_chat.py`); import them from services—do not embed long prompt strings in route handlers.
- **Prompt architecture** (`backend/app/prompts/study_chat.py`):
  - `STUDY_CHAT_SYSTEM_PROMPT` — base domain-neutral persona, always included. Stays general until the user describes the problem. Contains the **“coding illusion”** (when user asks for code, agent produces `panel_patch` JSON and describes it as solver setup), and **progressive disclosure** rules (only surface objective/constraint fields when the user raises related concepts). Includes the full solver config schema (using human-readable alias keys) for the agent’s internal reference.
  - `STUDY_CHAT_WORKFLOW_WATERFALL` / `STUDY_CHAT_WORKFLOW_AGILE` — workflow-specific addenda appended by `llm.py` based on `session.workflow_mode`. Waterfall encourages full upfront specification before any runs; Agile encourages frequent short cycles with incremental refinement. **Formulation style** differs: Waterfall elicits explicitly before adding (ask "Should I add X?"), adds at most one item per turn, requires user confirmation; Agile can add from clear hints with light confirmation ("Added X — run when ready"), prefers try-and-adjust. **Brevity** is enforced: 2–3 sentences per turn, one main idea, explain only when asked.
  - Task-specific prompt fragments now separate **visible chat reply**, **hidden brief update**, **workflow guidance**, and **phase guidance** (`discovery`, `structuring`, `configuration`). Keep `agile` and `waterfall` as first-class inputs across those layers.
  - `STUDY_CHAT_STRUCTURED_JSON_RULES` and the hidden brief-update task rules cover structured brief updates plus cleanup controls. Normal turns stay additive; cleanup/reorganize turns use explicit replacement flags (`replace_editable_items`, `replace_open_questions`) so omitted rows are truly removed.
  - The chat system instruction injects the current **problem brief** (compact authoritative memory for the turn), compact summaries of the last 4 optimization runs, and hidden researcher steering notes (if any). Steering stays invisible to participants, is treated as highest-priority guidance for the next participant-visible reply or hidden brief update, and should be blended in naturally with the prior conversational thread.
- **Fast-path chat pipeline:** participant chat first produces the visible reply (`generate_chat_turn` / `generate_visible_chat_reply`) and returns it to the client, then backend continues hidden brief/config derivation in a background thread. Session responses expose `processing` state (`processing_revision`, `brief_status`, `config_status`, `processing_error`) so the frontend can show pending state without blocking chat. If config derivation fails, backend falls back to deterministic regex parsing (`derive_problem_panel_from_brief`). Chat cleanup intents (e.g., consolidate/remove/reorganize definition) still trigger a backend cleanup mode so the model emits a full editable-definition replacement instead of additive append behavior.
- **`MessageCreate.skip_hidden_brief_update`:** when `true` with `invoke_model`, the server returns the visible assistant reply but **does not** run `launch_background_derivation` (no hidden brief merge / panel resync from that message). Processing is settled to `ready` so the client does not stay `pending`. The participant client sets this for acknowledgement messages after **manual definition saves** (except **open-question answer** saves, which still run full derivation), **manual config saves**, and **snapshot restores**, so the model cannot overwrite authoritative participant edits. Normal chat and run-interpretation messages omit the flag (default `false`).
- **Visible vs hidden payload discipline:** participant-visible assistant text must stay plain language (no JSON payloads). Structured keys such as `problem_brief_patch`, `replace_editable_items`, and `replace_open_questions` belong only to hidden brief-update flow; backend should sanitize visible replies if such keys leak into chat text.
- **Framing (participant-visible illusion):** The assistant behaves as a **general metaheuristic optimization** colleague. The **backend** evaluates a **single hard-coded benchmark instance**; the model must **not** name **routing / fleet / scheduling / vehicles / deliveries** domains unless the **user** did so first. **Greetings** and small talk must stay **domain-neutral**. The chat model's actionable output is the **problem brief patch**; solver config JSON is derived in the follow-up config-derivation call. Weight keys in stored config and in the participant panel use **human-readable alias names** (`travel_time`, `deadline_penalty`, `workload_balance`, etc.); the adapter translates these to internal keys before calling the solver.
- **Frontend auto-context injection:** after a successful optimization run (with **Ask model** on), the frontend automatically posts a context message so the model can interpret and compare results (full hidden derivation). Manual definition/config saves post a change summary with **`skip_hidden_brief_update`** so only the visible reply runs.
- **Run-acknowledgement rules** (`STUDY_CHAT_RUN_ACK_BASE`, `STUDY_CHAT_RUN_ACK_AGILE`, `STUDY_CHAT_RUN_ACK_WATERFALL`): when the user message is the auto-posted run-complete context (detected via `intent.is_run_acknowledgement_message`), the agent must **not** add run-result narrative (costs, violation counts, run summaries) to the problem brief — that would contaminate the definition and destabilize config derivation. The agent may suggest at most one or two targeted **config-linked** refinements (e.g. a weight or population-size change). `replace_editable_items` is forced to `False` for run-ack turns. Agile vs Waterfall differ in how the agent frames those refinements (proactive vs. objective-tied).
- **Answer-save flow** (`intent.is_answered_open_question_message`): when the user saves an answer to an open question in the Definition panel, the hidden brief-update task receives a one-line addendum: omit the answered question from `open_questions` (with `replace_open_questions=true`) to close it; do not add gathered items about uploads or status. `merge_problem_brief_patch` preserves `status` and `answer_text` from the base when the agent's patch includes a question by id but omits those fields.
- Structured replies use **`STUDY_CHAT_STRUCTURED_JSON_RULES`**; keep rules aligned with §7.3.
- Restart the API (or use `--reload` in dev) after editing prompt files.
---

## 7. Frontend specifications

### 7.1 Client / participant flows

The participant **does not** choose Agile vs Waterfall at session start; that mode is assigned by the **researcher** (see §7.2). The client offers **Start session** plus **Past sessions on this browser** (collapsible on the login gate): start includes an optional **participant number** field. **localStorage** keeps a bounded list of session ids the user has started or left on this device; **Refresh list** + **Resume** use the saved **access token** and `GET /sessions/:id` (and messages/runs) to reopen. Resume entries should display participant number and session start time (server snapshot preferred; local snapshot fallback). **Terminated** sessions resume in the existing read-only mode. **Forget** drops an id from local storage only. Do **not** implement “past sessions by IP” on the server for the shared participant token — that would expose other participants’ sessions.

The **client** UI has at least **three panels:** (1) **Chat and upload**, (2) **Information and assumption / controls**, (3) **Visualization and results**.

- The user states the problem in chat and may use **`Upload file(s)...`** per agent guidance. **Upload is simulated** for the study: the backend is fixed to the canonical scenario; the agent should **acknowledge** uploads and answer **as if** data were supplied. In logistics context, the agent should ask for both **order data** and **driver info/preferences**, and may naturally mention city-traffic API assumptions (time-of-day effects, disruptions) to explain routing logic. Canonical inputs include the **travel time matrix** and **30 orders** (see `vrptw-problem` data and docs).
- **New sessions** ship with **no** problem JSON on panels 2–3: the **Start session** action must clear the configuration textarea immediately and keep it **empty** until the **researcher** uses **Push starter problem config** (a deliberately mediocre, sparse starter on the server) or the participant/agent updates the panel. The participant must not see leftover JSON from a prior session when beginning a new one, and there should be **no separate automatic fallback/test config** beyond that explicit researcher push. Panel 2 now has a middle layer: an editable **problem brief / definition** tab (gathered info, assumptions, open questions), a structured **Problem Config** tab, and a **Raw JSON** tab. Open questions should use stable objects (`id`, `text`, `status`, `answer_text`) and the participant UI should prioritize answering/toggling question status instead of freeform rewriting existing question text. Definition content edits should be inline (per-element Save/Cancel) without requiring a global **Edit definition** gate, while the tab-level Definition actions persist the overall brief and optionally sync to config. Keep this answer-state behavior explicit with respect to `workflow_mode`; current behavior is intentionally aligned across `agile` and `waterfall` unless a change explicitly introduces divergence. Hidden system context may still exist in the stored brief for prompting, but should not be shown to participants. In **Waterfall**, an empty Problem Config tab is expected early on; the agent should keep the conversation focused on clarifying the definition until a real solver config is actually created, but the backend should deterministically derive and sync the `problem` block from the saved definition whenever that definition contains enough configuration signal, even if some open questions remain. Partial chat `problem_brief_patch.items` payloads should be merged additively so a turn that only changes the algorithm does not drop earlier confirmed constraints before config derivation runs. Numeric targets stated in the definition should carry through into the derived config where possible. Config saves should also push stable config-derived facts back into the saved definition so the flow stays bidirectional: `chat -> definition -> config`, and config edits feed back into the definition before later syncs. Config-linked facts in the saved definition should reconcile by semantic slot, so newer values for the same setting (algorithm, population size, epochs, weights, algorithm params, and similar config facts) replace older conflicting entries instead of accumulating duplicates. The **Raw JSON** tab should present a read-only combined snapshot of both the problem definition JSON and the current problem config JSON, and when no config has been saved yet it should show an empty object rather than `null`. Depending on **Agile vs Waterfall**, the agent surfaces **constraints and objectives** on panel 2 once that exists; the user may edit values or options. Panel 2 state must stay in sync with the **JSON configuration** sent to the solver; when the user changes the brief or config, the **chat** should acknowledge the update. When chat updates `problem.weights` or `problem.algorithm_params`, treat those nested objects as replacements rather than additive deep merges so stale starter values do not survive after the user changes priorities or algorithms. Keep a participant-visible debug action under the Definition tab that rebuilds the saved config from the saved definition.
- When an **optimization run** completes, show results in panel 3 (**tabs** if multiple runs). Run labels shown to users must be **session-local** (`Run #1`, `Run #2`, … within that session) rather than raw database ids. While a solve is in flight, use **one** tab for that run (`Run #N` plus a spinner); do not add a separate “Running…” tab or poll the run list in a way that duplicates the in-flight run in the UI. For this problem, include an **editable schedule** (edit mode) and **cost** for that run per the configured objective. **Manipulated** schedules should be reflected in chat. **Constraint violations** should update panel 2 when run results exist. Algorithm, objective weights, and constraints shown in results are derived strictly from the run snapshot (`run.request.problem` / run result); when the snapshot lacks keys, show "not captured in this run snapshot" rather than falling back to current panel config.
- **Results visualization:** outside **results edit mode**, panel 3 should prefer a visual timeline over raw JSON. The backend run payload includes **`schedule.stops`** (arrival/departure/window/load/capacity/priority/violation fields), **`schedule.vehicle_summaries`**, and **`schedule.time_bounds`** so the frontend can render an interactive per-vehicle Gantt/timeline with inline time-window and capacity markers plus a compact violation summary. Keep the visualization area vertically scrollable for taller schedules, keep raw JSON as a secondary details/debug view, keep the bottom action row anchored even when no run exists yet, use a compact **Edit** action for schedule editing only after a run result exists, and expose **Run optimization** as the clearer primary action plus **Recalculate cost** next to the displayed run cost.
- Each **RUN** produces a **chat** bubble (acknowledgment); the **result summary** may follow as the next bubble.
- **Saving** edits on panels 2 and 3 posts a **chat acknowledgment**. While a panel is in **edit mode**, it is visually highlighted and the user **cannot** use other panels until **save** or **exit edit** (per your UX rules).
- **Chat responsiveness:** Outgoing messages render **immediately** (optimistic). If **Ask model** is on, the backend should return the participant-visible assistant reply on the fast path, then continue definition/config derivation asynchronously. The assistant area still shows pending feedback while the reply is in flight, and panel 2 should show definition/config spinners from session `processing` state while background derivation is still running. On **Problem Config** and **Raw JSON** tabs, a **grey overlay** blocks the scroll area while `brief_status` or `config_status` is pending (or a client sync is in flight); after **90s** a client watchdog clears the overlay and shows a stall hint so the user is not stuck. **Edit** / **Load config** on the config tab respect the same lock until unlock.
- **Definition UX (participant):** new gathered/assumption rows use a placeholder string (`DEFINITION_NEW_ROW_PLACEHOLDER` in `client/problemDefinition/constants.ts`) until the user saves real text; placeholder rows are **omitted** from PATCH payloads. Gathered and assumption rows are editable regardless of stored `item.editable`; per-row Type/Status dropdowns are removed (subsection implies kind). While a participant session has no loaded chat messages yet (new session or still loading history), auto-focus the chat composer, apply a visible-but-brief highlight pulse, and keep a chat-first layout (hide panels 2–3) while preserving chat at its normal 3/10 width. The **Model / API key** control should be a compact **chip** that reflects whether a key is configured (refresh session when opening the dialog; after save, update status from the server response). A matching **Backend** chip should expose the active backend URL plus connection status.
- **Session sync races:** In-flight `GET` session / messages / runs must **not** apply after the user **Leave**s or **Start session** (another id). Use a **session id ref** (or equivalent) so stale HTTP responses cannot repopulate state from a **previous** session. **Problem panel hydration:** use an explicit mode — after **POST /sessions**, stay in **empty-until-server-panel** until `panel_config` is non-empty on the server (researcher push, etc.) or the client applies JSON from **save** / **chat** `panel_config`; then **follow** the server on each poll. While the server panel is still empty, **do not** push `""` into the textarea on every poll (that would erase in-progress edits). While the participant is in **problem configuration edit mode**, **do not** overwrite the textarea from `GET` session (polling would undo clearing the JSON); after **Save** or **Cancel**, resume mirroring from the server. The **mount** `syncSession` effect should pass **AbortSignal** + **abort on cleanup** so **React Strict Mode** does not double-fetch the same session snapshot.

### 7.2 Researcher flows

The **researcher** UI has a **left panel** for session list and management. Selecting a session shows **chat**, **runs**, and **edits**. Session rows should display participant number and session start time, and the session detail controls should allow editing/saving participant number after start.

- **Delete session:** the participant client must detect removal (404 / gone responses on sync) and return to the **same gate as initial login** (token still in browser storage) with copy explaining the session was deleted; **Start session** creates a new UUID.
- The researcher session list should support selecting multiple visible sessions and deleting them in one confirmed batch operation for fast test-session cleanup.
- **Terminate session:** the participant **keeps read access** to GET session, messages, and runs so they can review history; **writes** (chat, uploads, panel saves, runs, model key save) are rejected by the API. The client **greys out** chat and actions and shows an **info banner** with **Start new session** while leaving panels readable.
- **Researcher messages** in chat are **invisible** to the participant; only the researcher sees their own steering messages.
- The researcher sets **Agile vs Waterfall** mode for the agent driving that session and may **push** the canonical mediocre sparse starter problem JSON to the participant session when the study design calls for it.
- The researcher session detail should keep the **participant model/API key chip** and the **backend chip** in the controls area immediately above chat, not in the top header.
- The researcher Runs view should list each run as a collapsed entry by default, with actions to inspect details and delete individual runs without removing the entire session. Run deletion should require an explicit confirmation and remain deleted after refresh or reselection.

### 7.3 UX constraints

- Do **not** surface **VRPTW**, **QuickBite**, or **internal zone names** in UI copy or API-visible labels unless the **participant** used those terms first.
- **Chat UI** (participant and researcher steering): shared **`frontend/src/shared/chat/ChatPanel.tsx`** (`ChatPanel` + `ChatComposer` + optional **`ChatAiPendingBubble`**). Enter sends, Shift+Enter newline — implemented **inside** that module (not a separate keyboard file). Shared message-bubble rendering should stay under **`frontend/src/shared/chat/`** so both apps keep the same optimistic-message behavior. Chat typing performance is optimized by using a `scrollTriggerKey` for scroll-to-end (message-based only), memoizing `MessageBubbleList`, and stabilizing the send callback via a ref for chat input to avoid keystroke-triggered re-renders.
- **Participant frontend structure:** keep **`frontend/src/client/ClientApp.tsx`** thin. Session orchestration belongs in **`frontend/src/client/hooks/useParticipantController.ts`**; unauthenticated UI in **`frontend/src/client/components/LoginGate.tsx`**; authenticated layout in **`frontend/src/client/components/ParticipantShell.tsx`**; the model dialog in **`frontend/src/client/components/ModelSettingsDialog.tsx`**. Group participant-only code by feature: chat UI/helpers under **`frontend/src/client/chat/`**, the editable middle layer under **`frontend/src/client/problemDefinition/`**, problem-config UI and JSON helpers under **`frontend/src/client/problemConfig/`**, and visualization/schedule tooling under **`frontend/src/client/results/`**. Shared non-React client helpers and types belong under **`frontend/src/client/lib/`**. Avoid rebuilding a catch-all `panels/` directory full of unrelated concerns.
- **Researcher frontend structure:** keep **`frontend/src/researcher/ResearcherApp.tsx`** as a composition root only. Polling/stateful logic should live under **`frontend/src/researcher/hooks/useResearcherController.ts`**, display sections under **`frontend/src/researcher/components/`**, and shared non-React helpers under **`frontend/src/researcher/lib/`** so the top-level shape mirrors the participant app for readability.
- **Problem configuration panel (`client/problemConfig/ConfigPanel.tsx`):** instead of a raw JSON textarea, the panel renders `client/problemConfig/ProblemConfigBlocks.tsx` — a structured form under one **Goal terms** section: weight rows (objectives and soft penalties), **structural** fields (max-shift penalty, fixed task→worker locks) without a separate section heading, **Driver Preferences** weight plus a **Preference rules** `<details>` accordion, then a **Search strategy** subheading (algorithm, iterations, population, seed). In edit mode the inputs become active; on Save the serialized JSON is sent as usual. A **"Show raw JSON"** `<details>` element below the form exposes the underlying text for power users or debugging. New weight keys appear automatically as the model patches the panel — no hardcoded list of active weights is needed in the component. The participant form does **not** expose the `only_active_terms` toggle; when omitted, backend scoring defaults to explicit-only objective terms. Researcher controls include a dedicated `only_active_terms` toggle at the session level. **Definition tab** has compact **Save**, **Load**, and **Sync to config** buttons; **Config tab** has **Edit** and **Load config** (drop-up: **From most recent run**, **Load from snapshot...**). The snapshot dialog lists server-stored brief+panel snapshots; restoring triggers chat acknowledgement. **Load config** options are shown when available; **Load from snapshot...** greys out when no snapshots exist.
- **Optimistic chat:** After send, the user’s message should **appear immediately** in the log (do not block on persistence or model latency). When the participant enables **Ask model** and a reply is pending, show a **spinner** (“Thinking…”) in the assistant area until the server returns. Researcher steering messages should also appear immediately (optimistic row, then replace with the server `MessageOut`).
- **Password** protection for both apps; secrets from `.env` (see §6.4).
- The agent should **not** dump large explanations into panel 2 **without** prior chat context — especially under **Waterfall**.
- Chat responses should stay **concise** by default.

### 7.4 State & data

- **Authoritative** session history (chat, runs, configs) lives on the **server** (SQLite). The **browser** may cache a **local copy** for resilience (e.g. offline draft or re-open) and for **participant review** of their own past sessions; define **merge rules** on reconnect (server wins for conflicts unless you specify otherwise).
- The **researcher** sees **all** server-stored sessions. If a session is **deleted** or **terminated** while the client is open, the next sync should surface the UX in §7.2.

### 7.5 Shared components between researcher and client

- **Model / API key setup:** a shared **chip** opens a dialog to paste an **API key** and select **model** (start with **Google Gemini** “Flash” tier or current equivalent). **Keys** are stored **server-side** (encrypted at rest if feasible) so sessions can resume; the researcher may **push** a key to the participant flow; participants may also supply their own.
- **Backend connection setup:** a shared **Backend** chip opens a dialog showing the active backend URL and connectivity. URL resolution priority is **browser user override → `VITE_API_BASE` → `http://127.0.0.1:8000`**. Both participant and researcher can inspect or change the browser-local override from that dialog.
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
- Typical **chat** and **solve** requests: visible chat should usually return on the first model call, even if definition/config derivation continues in the background. Aim for **1–5 s** for the visible reply when warm; allow panel derivation or heavy runs to continue with explicit loading feedback up to **~30 s** when necessary.
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
