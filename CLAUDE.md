The venv is located in the root of the repo, not in the /backend folder.

## Live Gemini tests

Tests in `backend/tests/test_live_gemini.py` (marker `live_gemini`) hit the
real Gemini API. They auto-skip without a key. **A failure there can be a
missing/invalid/expired API key — not necessarily a product bug.** Setup:
either drop the key into `backend/.secrets/gemini_api_key` (file, gitignored)
or export `GEMINI_API_KEY` in your shell. See `backend/.secrets/README.md`.

The first live-test failure auto-blocks the rest of the live tests in the
session (see `backend/tests/conftest.py`) so you don't burn quota on
repeated failures.
