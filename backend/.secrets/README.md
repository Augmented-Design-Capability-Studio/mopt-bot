# Local test secrets

This directory holds developer-local secrets used by the test suite.
**Everything in this directory except this README is gitignored**
(see the `backend/.secrets/*` rule in the repo root `.gitignore`).
Never commit anything else here.

## Gemini API key for live tests

Tests in `backend/tests/test_live_gemini.py` (marked `live_gemini`) make
real calls to the Gemini API. They auto-skip without a key, so the rest of
the suite still runs fine offline.

To enable them locally, create a one-line file with your key:

```
backend/.secrets/gemini_api_key
```

Just the raw key on the first line — no `KEY=` prefix, no quotes, no
trailing newline matters.

The fixture also accepts a `GEMINI_API_KEY` environment variable as a
fallback, so if you already export the key in your shell profile or
`direnv`, the file is optional.

## Running live tests

```bash
# All live tests
pytest backend/tests -m live_gemini -v

# Only the live-tests file
pytest backend/tests/test_live_gemini.py -v

# Everything except live tests (safe offline / in CI)
pytest backend/tests -m "not live_gemini"
```

If the key is missing, every `live_gemini` test skips with an explicit
banner pointing back here. If the key is present but rejected by Gemini,
the first test fails with a clear "key was rejected" message, and the rest
of the live tests are auto-skipped to avoid burning quota — re-run after
fixing the key.

## What lives here vs. `backend/.env`

`backend/.env` is loaded by the **server** (`pydantic-settings` reads it on
startup) and configures runtime things like ports, CORS, and the default
Gemini model id. It's deliberately not the place for the test API key —
keeping the test secret in `.secrets/` keeps it out of the server config
surface and makes it obvious that nothing in production reads it.
