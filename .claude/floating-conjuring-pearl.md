# Plan: Smarter, More Agentic Chatbot

## Context

The participant-facing Gemini chatbot today gets a single LLM call per turn with a static system instruction (current brief, last 4 runs, researcher steers, workflow addendum). It cannot:

- Cite or quote user-facing documentation (`docs/user/*.md`) — those docs are not in context at all.
- Describe its own capabilities in concrete terms — supported algorithms, what charts the user sees, how each goal term shifts the solver, etc.
- Justify weight adjustments grounded in actual goal-term definitions.

We want to fix all three **without** (a) blowing up the system prompt, (b) hurting per-turn latency, or (c) breaking the study illusion that the system is a *general-purpose optimization agent that writes solver code on the fly* (i.e., never reveal VRPTW / MEALpy / w1–w7 internals).

User decisions made during planning:
- Docs corpus stays small (~1–10 `.md` files). Lightweight in-process search, no embeddings, no new deps.
- Tool-calling loop is **out of scope for this change**. We do one cheap retrieval step + always-on static capability blocks. (Tool-calling can come later if docs grow.)
- Single chat path for everyone — no researcher A/B toggle for the agentic mode.

## Approach (high level)

Two additive layers, both flowing into the existing `_build_visible_chat_system_instruction()`:

1. **Capabilities block (static, domain-neutralized):** an always-injected section that tells the LLM what it can confidently talk about — supported algorithms (rendered from `algorithm_catalog.py`), the goal terms it can adjust with plain-language explanations and direction-of-effect (rendered from the active port's weight metadata), and the visualizations the participant sees. Built once per turn, ~few hundred tokens, neutral language only.
2. **Per-turn doc retrieval:** before the visible reply, run a tiny keyword/BM25 search over `docs/user/*.md` against the user message. If the top hit clears a threshold, inject up to 2 short section excerpts as a "Reference excerpts" block. No LLM gating — pure string matching, sub-millisecond.

Plus a **prompt-posture refresh** in `prompts/study_chat.py` that frames the agent as general-purpose, instructs plain-language explanations, and explicitly lists guardrails (don't reveal domain, don't expose internal aliases, don't name MEALpy).

No tool/function calling, no new background tasks, no DB schema changes. The only added cost per turn is the retrieval call (negligible) + a slightly larger system instruction (a few hundred tokens).

## Files to modify

### New

- `backend/app/services/docs_index.py` — module-level singleton index over `docs/user/*.md`.
  - `load_docs_index(root: Path) -> DocsIndex` — read .md files, split by `##`/`###` headings, tokenize.
  - `DocsIndex.search(query: str, k: int = 2, min_score: float = ...) -> list[DocSection]` — token-overlap + IDF (small enough that BM25 from scratch in ~40 lines is fine; do not pull in `rank_bm25`).
  - `DocSection.to_prompt_excerpt() -> str` — heading path + 80–120 word body slice.
  - Loaded lazily on first use, cached. Rebuilt on backend restart (mtime check optional).

- `backend/app/services/capabilities.py` — assembles the neutralized capability block.
  - `build_capabilities_block(test_problem_id: str | None) -> str` — concatenates:
    - `_algorithms_section()` — read `algorithm_catalog.py`, render as "Available solver families: …" with one-line plain-language description per family. **Strip MEALpy-specific names** (rename "GA / SwarmGA" → "evolutionary search", "PSO" → "swarm search", "SA / SwarmSA" → "annealing-based search", "ACOR" → "ant-colony search"). Map kept in this file.
    - `_goal_terms_section(port)` — read `port.weight_definitions()` (already exists for VRPTW via `study_meta.VRPTW_WEIGHT_DEFINITIONS`); render "Goal terms you can emphasize / de-emphasize:" with each term's user-facing label + description + direction-of-effect ("higher value → solver works harder to reduce X"). Use `port` from `get_study_port(test_problem_id)`.
    - `_visualizations_section(port)` — bullet list of what the participant sees post-run (convergence curve, violation cards, metric cards, route/schedule view). Sourced from a new `port.visualization_capabilities() -> list[str]` method (default impl in `StudyProblemPort`, override in `vrptw_problem/study_port.py` and `knapsack_problem/study_port.py`).
  - All output uses participant-facing language only. **No w1–w7, no "VRPTW", no "MEALpy", no domain identity.**

### Edited

- `backend/app/services/llm.py`
  - Extend `_build_visible_chat_system_instruction()` signature: add `capabilities_block: str | None = None` and `doc_excerpts: list[str] | None = None`. Inject after the phase prompt and before the brief JSON, each in its own clearly-labeled section.
  - Extend `generate_visible_chat_reply()` to accept and pass through the new args.
  - Do **not** modify the brief-update / intent-classification calls — they don't need this.

- `backend/app/routers/sessions/router.py` (or `helpers.py` if cleaner)
  - In `_handle_post_participant_message()` just before the `generate_chat_turn()` call: build `capabilities_block` and `doc_excerpts` and forward them. `docs_index.search()` runs against `user_text`; capabilities block runs against `session.test_problem_id`.

- `backend/app/prompts/study_chat.py`
  - Update `STUDY_CHAT_SYSTEM_PROMPT` (or add a sibling preamble that's appended in warm-context turns) to:
    - Frame the agent as a *general-purpose optimization agent* that selects algorithms and writes solver glue on the fly.
    - Require plain-language, analogy-friendly explanations; avoid jargon unless asked.
    - List the guardrails: never name the domain, never reveal internal weight aliases, never name MEALpy or specific solver libraries; refer only to neutralized solver-family names.
    - Tell the LLM that when "Capabilities" or "Reference excerpts" sections are present, prefer those facts over its training prior.

- `backend/app/problems/port.py`
  - Add `visualization_capabilities(self) -> list[str]` with a sensible default (`["Convergence curve over iterations", "Cost vs. reference run summary"]`).

- `vrptw_problem/study_port.py`, `knapsack_problem/study_port.py`
  - Override `visualization_capabilities()` with the actual list (route/schedule view, violation cards, etc. for VRPTW; item-fill view for knapsack). Neutral language.

- `template_problem/study_port.py` and `TEMPLATE_INSTRUCTIONS.md`
  - Mirror the new method so future domains pick it up.

### Tests

- `backend/tests/test_docs_index.py` — load fixtures from a temp `docs/user/`, assert section splitting, search relevance ordering, threshold gating.
- `backend/tests/test_capabilities.py` — assert neutralized strings: no "MEALpy", no "VRPTW", no "w1"…"w7", no "vehicle"/"route" leakage; structure matches expected sections.
- `backend/tests/test_llm_system_instruction.py` (or extend an existing one) — when `capabilities_block` and `doc_excerpts` are passed, they appear in the assembled instruction in the right order; when omitted, behavior is unchanged.

## Functions/utilities to reuse (don't rebuild)

- Goal-term definitions: `vrptw_problem/study_meta.py::VRPTW_WEIGHT_DEFINITIONS` (already user-facing labels/descriptions).
- Algorithm catalog: `backend/app/algorithm_catalog.py` — read existing names + params, **map** to neutral names in `capabilities.py`.
- Port lookup: `backend/app/problems/registry.py::get_study_port()`.
- Locked-weight context: existing `locked_goal_terms_prompt_section()` in `problem_brief.py` — capabilities block should not duplicate it.
- System-instruction assembly: stay inside `_build_visible_chat_system_instruction()` (llm.py:322); don't open a parallel path.

## Verification

1. **Unit tests:** `pytest backend/tests/test_docs_index.py backend/tests/test_capabilities.py backend/tests/test_llm_system_instruction.py` — all green.
2. **Domain-neutrality lint:** the capabilities-block test asserts forbidden-substring absence; run it on both VRPTW and knapsack ports.
3. **Manual smoke (backend running, frontend client SPA):**
   - Start a session, send "what algorithms can you use?" → reply names neutralized solver families, not MEALpy/GA/PSO.
   - Send "what does workload balance do?" → reply paraphrases the description from `study_meta.py` and explains direction of effect.
   - Send "what charts will I see after a run?" → reply lists items from `visualization_capabilities()`.
   - Send a message echoing a phrase from `ASKING_THE_AGENT.md` (e.g. "give me a one-paragraph rationale") → reply is consistent with the doc; spot-check via logs that an excerpt was injected.
   - Send a normal definition message ("I have 12 vehicles…") → no capabilities content leaks into the visible reply; latency feels unchanged.
4. **Latency check:** time 5 turns before/after via the network panel; budget delta < 50ms (retrieval is in-process; capabilities block is string concat).
5. **Study-integrity check:** grep the assembled system instruction (log it once at DEBUG) for "VRPTW", "MEALpy", "vehicle", "w1"–"w7" — none should appear.

## Out of scope (for follow-up if needed)

- Function/tool calling via `google-genai` `tools=[…]`. Worth revisiting if docs grow past ~20 files or if the agent needs to *take* actions (e.g., propose-and-apply weight diffs) rather than just describe them.
- Embedding/vector store. Same trigger.
- Researcher-side toggle to A/B the agentic posture (user explicitly declined).
