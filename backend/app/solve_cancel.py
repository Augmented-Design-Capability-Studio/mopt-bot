"""Cooperative cancellation for in-session optimization (see post_run + POST .../runs/cancel)."""

from __future__ import annotations

import threading
from typing import Optional

_lock = threading.Lock()
# One in-flight optimize per session id (participant session UUID).
_events: dict[str, threading.Event] = {}


def register_cancel_event(session_id: str) -> threading.Event:
    """Replace any prior event for this session and return a fresh Event."""
    ev = threading.Event()
    with _lock:
        _events[session_id] = ev
    return ev


def request_cancel(session_id: str) -> bool:
    """Signal the active solver for this session to stop. Returns True if a run was in progress."""
    with _lock:
        ev = _events.get(session_id)
    if ev is None:
        return False
    ev.set()
    return True


def clear_cancel_event(session_id: str) -> None:
    with _lock:
        _events.pop(session_id, None)


def peek_cancel_event(session_id: str) -> Optional[threading.Event]:
    with _lock:
        return _events.get(session_id)
