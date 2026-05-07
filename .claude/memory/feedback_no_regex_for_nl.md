---
name: No regex/keyword matching for natural-language interaction
description: Avoid regex and keyword/substring matching for parsing or routing natural-language input. Prefer structured LLM output and explicit JSON schemas.
type: feedback
---

Do not use regex or keyword/substring matching to parse, classify, or route natural-language interaction (chat input, brief prose, free-form rationale). Prefer structured LLM output: extend the response JSON schema or the prompt contract so the model emits typed JSON, then operate on that JSON in code.

**Why:** The user is explicit and repeats it: *"I really hate regexes. In NL interaction, they have been found to be very unreliable."* The repo's recent `29e12b4` commit ("stability fixes - relying more on llm instead of regex and keyword matching") gutted ~1500 lines of `_SIGNAL_PATTERNS`, fuzzy keyword maps, and difflib-based matchers from `vrptw_problem/brief_seed.py` and `study_bridge.py` for the same reason. Every fix to those layers added a new exception (negation, novel phrasing, …) without ever closing the fundamental ambiguity of NLP-by-substring.

**How to apply:**
- Adding a new field that travels via chat → backend? Add it to the LLM response schema, not to a parser. The brief patch schema and panel patch schema are the right places.
- Need to map prose to structured fields? Extend the prompt with a worked example and the schema; do not write a regex.
- Keyword/substring detection of intent (e.g. "did the user mention X?") is also off-limits unless the input is known-structured (a stable id like `config-weight-*`, a system-emitted sentinel, etc.). For id-based dispatch, use `str.split` / equality / `str.startswith` — never `re.compile`.
- Acceptable regex use: tokenizing known-machine-formatted strings (timestamps, version strings, structured ids that we ourselves emit). Anything that came from a human typing free text → structured LLM output instead.
- When refactoring, prefer deleting regex/keyword matchers over patching them.
