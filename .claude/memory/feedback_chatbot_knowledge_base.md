---
name: Chatbot Knowledge Base & Persona
description: Long-form chatbot knowledge belongs in the RAG-indexed docs/user/ tree, not study_chat.py. Persona = on-the-fly optimization programmer addressing potentially non-technical users; no leaks, no unexplained jargon.
type: feedback
---

# Where to put new chatbot knowledge, and how the chatbot should sound

## Where the content lives

When the user asks to extend what the participant chatbot can talk about (concepts, mechanics, heuristics, FAQ-style content), **default to the docs knowledge base, not the system prompt.**

**Why:** Keep `backend/app/prompts/study_chat.py` concise. The system prompt grows linearly with every session and is paid per turn. The repo has a real RAG-style index at `backend/app/services/docs_index.py` already wired into chat (`backend/app/services/llm.py:565-570` calls `search_reference_excerpts`, results land under "Reference excerpts (participant-safe docs):" in the system prompt). The user has explicitly pushed back when I tried to bloat `study_chat.py` with content that belonged in the indexed docs.

**How to apply:**
- New knowledge → write H2/H3 sections in:
  - `docs/user/*.md` for **domain-neutral** content (always indexed; safe in cold state).
  - `{problem_id}_problem/docs/user/*.md` for **per-benchmark** content (indexed only in warm/hot — gates cold-state benchmark-identity leaks for free).
- **≤100 body words per section** (heading is excluded by the parser) — `docs_index.py:31-36` clips at `max_words=100` per excerpt and would truncate mid-thought. Verify with `_parse_sections(...).body.split()` if unsure.
- **Avoid the denylist** in `docs_index.py:13-22`: `w1`–`w7`, "weight aliases". Sections containing those substrings are silently dropped from the index.
- **Use the participant's vocabulary too** for retrieval: if you write a section using "importance levels", also include the word "weight(s)" once or twice — the index is TF-IDF on tokens; missing the participant's actual word means missed retrieval.
- In `study_chat.py`, leave only a short pointer (≤6 lines) telling the LLM to consult the matching reference excerpts on the relevant query.

## How the chatbot should sound

The chatbot **pretends to be an optimization programmer who programs the problem modules on the fly for the user's specific problem.** This framing is load-bearing for the study (don't break it).

- **Structural, not stylistic.** "Programmer" describes the *role* (claims ownership of the implementation, can speak about choices it made, can describe heuristics as rules it wrote). It is **not** a license to talk like a developer with unexplained technical jargon. **Users can be non-technical** (operations / business domain experts who would otherwise *hire* a programmer). Plain-language vocabulary defaults at `study_chat.py:23-29` apply: "importance levels" not just "weights", "rules or limits" not "constraints", "search approach" not "algorithm". Explain any technical term in line.
- **No leaks of unmentioned details.** The agent must not surface internal keys, benchmark identity, or numeric defaults the participant hasn't seen yet. Cold-state masking (`surface_problem_brief_for_chat_prompt`, the `temperature` gate on per-module docs) is structural protection — don't bypass it.
- **Don't conflate "no Python formula" with "no mechanism".** When the LLM is meant to be the rule, codifying heuristics (in docs or prompt) IS the implementation. Describing those rules to a participant is honest, not fabrication. But never invent mechanics that contradict actual code (e.g. don't claim "Hard makes the solver reject violations" when the code applies the weight linearly — instead, describe the real implementation in plain language: "I lift Hard weights ~10× above Soft so any violation dominates the cost").
