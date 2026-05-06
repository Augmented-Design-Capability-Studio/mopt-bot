"""Test-suite-wide fixtures, markers, and reporting hooks.

Two responsibilities:

1. **Default-stub the Gemini classifier helpers.** Production code calls
   ``classify_definition_intents`` and ``classify_chat_temperature`` ahead of
   the mocked ``generate_chat_turn`` whenever a test posts a message with
   ``invoke_model=True`` and a non-empty (mocked) decrypted key. Without a
   default stub, every such test silently dispatches a real Gemini request
   that 401s and falls back. This file installs deterministic stubs for all
   tests; individual tests can still override.

2. **Live-Gemini key plumbing** for ``backend/tests/test_live_gemini.py``.
   Provides the ``gemini_api_key`` fixture, registers the ``live_gemini``
   marker, and prints a setup banner when the key is missing. Once a live
   test fails for an authentication or connection reason, the rest of the
   live tests in the same session auto-skip to avoid burning quota.

See ``backend/.secrets/README.md`` for setup instructions.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from _pytest.config import Config
from _pytest.terminal import TerminalReporter

# ---------------------------------------------------------------------------
# Default classifier stubs (autouse) — keeps the suite offline by default.
# ---------------------------------------------------------------------------

_LIVE_MARKER = "live_gemini"


@pytest.fixture(autouse=True)
def _stub_gemini_helpers(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Stub Gemini helpers so non-live tests never touch the network.

    Defaults mirror the production fallback path each helper uses when its
    own ``except`` branch trips, so test outcomes are equivalent to the
    "no API key configured" runtime — without the ~1s round-trip and the
    misleading ``API_KEY_INVALID`` warning in the test log.

    Live tests (marked ``live_gemini``) opt out so they can hit the real API.
    Individual tests can still ``monkeypatch.setattr`` over these defaults.
    """
    if request.node.get_closest_marker(_LIVE_MARKER) is not None:
        yield
        return

    from app.services import llm as _llm
    from app.routers.sessions import intent as _intent

    # Mirror production fallbacks (regex-based intent detection, deterministic
    # heuristic temperature) so tests that depend on those paths still work.
    monkeypatch.setattr(
        _llm,
        "classify_definition_intents",
        lambda content, *_a, **_k: (
            _intent.is_definition_cleanup_request(content),
            _intent.is_definition_clear_request(content),
            _intent.is_change_intent_fallback(content),
        ),
    )
    monkeypatch.setattr(_llm, "classify_chat_temperature", lambda *a, **k: "warm")
    monkeypatch.setattr(_llm, "classify_assistant_run_invitation", lambda *a, **k: False)
    # The hidden brief/config derivation helpers normally run in background
    # threads and silently fall back when they fail — null them out so tests
    # don't dispatch real network calls just to log a 401.
    monkeypatch.setattr(_llm, "generate_problem_brief_update", lambda *a, **k: None)
    monkeypatch.setattr(_llm, "generate_config_from_brief", lambda *a, **k: None)
    yield


# ---------------------------------------------------------------------------
# Live-Gemini support
# ---------------------------------------------------------------------------

_KEY_FILE = Path(__file__).resolve().parent.parent / ".secrets" / "gemini_api_key"
_ENV_VAR = "GEMINI_API_KEY"

_BANNER_LINES = (
    "Live Gemini tests were skipped — no API key found.",
    f"  - Expected file: {_KEY_FILE}",
    f"  - Or env var:    {_ENV_VAR}",
    "  See backend/.secrets/README.md for full setup.",
)

# Session-scoped state. Pytest re-imports this module per process, so these
# globals reset between invocations — no persistence across runs.
_skipped_for_missing_key: list[str] = []
_blocked_reason: str | None = None


def pytest_configure(config: Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{_LIVE_MARKER}: requires a real Gemini API key; auto-skips when none is configured.",
    )


def _read_api_key() -> str | None:
    if _KEY_FILE.exists():
        try:
            content = _KEY_FILE.read_text(encoding="utf-8").strip()
        except OSError as exc:
            pytest.fail(f"Cannot read {_KEY_FILE}: {exc}", pytrace=False)
        if not content:
            pytest.fail(
                f"{_KEY_FILE} exists but is empty. Either delete it or paste a real key.",
                pytrace=False,
            )
        return content
    env = os.environ.get(_ENV_VAR, "").strip()
    return env or None


@pytest.fixture
def gemini_api_key(request: pytest.FixtureRequest) -> str:
    """Return a Gemini API key for live tests, or skip with a clear message."""
    if _blocked_reason is not None:
        pytest.skip(
            f"Earlier live API call failed ({_blocked_reason}); "
            "skipping the rest of this session to save quota."
        )
    key = _read_api_key()
    if not key:
        _skipped_for_missing_key.append(request.node.nodeid)
        pytest.skip(
            "Gemini API key not configured. "
            f"Place the key at {_KEY_FILE} or export {_ENV_VAR}=... — "
            "see backend/.secrets/README.md."
        )
    return key


# ---------------------------------------------------------------------------
# Fail-fast: once one live test trips on auth or connectivity, skip the rest.
# ---------------------------------------------------------------------------

_AUTH_HINTS = (
    "401",
    "403",
    "permissiondenied",
    "permission_denied",
    "unauthenticated",
    "api key not valid",
    "invalid api key",
)
_CONNECTION_HINTS = (
    "connecterror",
    "connectionerror",
    "connect_error",
    "timeouterror",
    "timeout",
    "name or service not known",
    "temporary failure in name resolution",
    "failed to establish a new connection",
)


def _classify_failure(reason_text: str) -> str | None:
    lowered = reason_text.lower()
    if any(h in lowered for h in _AUTH_HINTS):
        return "Gemini rejected the supplied key"
    if any(h in lowered for h in _CONNECTION_HINTS):
        return "network connection problem"
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or report.outcome != "failed":
        return
    if item.get_closest_marker(_LIVE_MARKER) is None:
        return

    global _blocked_reason
    if _blocked_reason is not None:
        return  # Already blocked by an earlier failure.
    reason_text = ""
    if call.excinfo is not None:
        reason_text = f"{call.excinfo.type.__name__}: {call.excinfo.value}"
    classified = _classify_failure(reason_text)
    if classified is None:
        # Treat any failure in a live test as a session-level blocker — even
        # an assertion-only failure is more useful than running 4 more tests
        # that will all fail the same way.
        classified = "earlier live test failed"
    _blocked_reason = classified


# ---------------------------------------------------------------------------
# Terminal summary banner — surfaces missing-key skips visibly.
# ---------------------------------------------------------------------------


def pytest_terminal_summary(terminalreporter: TerminalReporter, exitstatus: int, config: Config) -> None:
    del exitstatus, config
    if not _skipped_for_missing_key:
        return
    tr = terminalreporter
    tr.write_sep("=", "live Gemini tests skipped", yellow=True, bold=True)
    for line in _BANNER_LINES:
        tr.write_line(line)
    tr.write_line(f"  Skipped tests: {len(_skipped_for_missing_key)}")
