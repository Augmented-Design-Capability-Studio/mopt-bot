"""Test-suite-wide fixtures, markers, and reporting hooks.

Two responsibilities:

1. **Default-stub the Gemini helpers.** Tests that exercise the chat
   pipeline default to a no-network stub: ``generate_main_turn`` and
   ``generate_config_from_brief`` both return ``None`` so the pipeline
   pauses cleanly instead of dispatching a real Gemini request. Tests
   that need specific outputs override these per-test.

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


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_database_schema() -> None:
    """Run ``ensure_database_shape`` once per test session so column-additions
    in production code (e.g. ``allow_agent_autorun``) reach the dev sqlite
    file the suite shares. Without this, schema-evolving commits break
    pipeline tests that touch the real ``sessions`` table.
    """
    from app.db_maintenance import ensure_database_shape

    ensure_database_shape()


@pytest.fixture(autouse=True)
def _stub_gemini_helpers(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Stub Gemini helpers so non-live tests never touch the network.

    Default stubs keep the chat pipeline working without an API key. Tests
    that want to drive specific main-turn outputs can override
    ``app.services.llm.generate_main_turn`` per-test.

    Live tests (marked ``live_gemini``) opt out so they can hit the real API.
    """
    if request.node.get_closest_marker(_LIVE_MARKER) is not None:
        yield
        return

    from app.services import llm as _llm

    monkeypatch.setattr(_llm, "classify_chat_temperature", lambda *a, **k: "warm")
    # generate_main_turn drives the entire chat pipeline. Default to None so
    # the runner's "transient transport/parse failure" path settles with a
    # paused stage — tests that exercise specific outputs override per-test.
    monkeypatch.setattr(_llm, "generate_main_turn", lambda *a, **k: None)
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
