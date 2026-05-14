"""Integration tests for the deterministic algorithm-commit safety net and
the pre-release gate probe.

These cover the GA-bug failure mode described in the user report: agent's
visible reply commits "I've set the search strategy to genetic search (GA)"
but the brief patch doesn't carry the matching assumption row, so the
panel-derive can't pick up `algorithm=GA` and the Run button stays greyed
out.

Two layers:

1. **Layer 1 (deterministic safety net, in BG derivation).** If the visible
   reply names an algorithm but the brief patch lacks the items[] row, the
   BG pipeline synthesizes the row before merge. This test exercises the
   end-to-end path through the API.
2. **Layer 2 (pre-release probe in router).** If the visible reply invites
   the participant to click **Run optimization** but the speculative gate
   check (after layer 1's algorithm injection) shows the run button would
   still be DISABLED, the router re-calls the consolidated chat turn once
   with an audit block injected. This test mocks the consolidated helper to
   observe the retry.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.schemas import ChatModelTurn, ConsolidatedChatTurn


_AUTH_HEADER = {"Authorization": "Bearer test-gate-aware-secret"}


def _create_agile_session(client: TestClient) -> str:
    create = client.post(
        "/sessions",
        json={"workflow_mode": "agile"},
        headers=_AUTH_HEADER,
    )
    assert create.status_code == 200
    return create.json()["id"]


def test_layer1_bg_safety_net_injects_algorithm_assumption(monkeypatch: pytest.MonkeyPatch):
    """GA-bug scenario, end-to-end: agile session with a goal-term weight
    already on the panel; visible reply commits to GA but the (mocked)
    chat-turn returns NO problem_brief_patch. The BG safety net must add
    the algorithm assumption row to the brief so panel-derive picks up
    `algorithm=GA` and the gate opens.

    Note: the consolidated helper is stubbed to None (conftest default),
    so the router falls through to the multi-call `generate_chat_turn`
    path. We mock that to produce the GA visible reply with an empty
    brief patch, which is exactly the failure mode the safety net targets.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-gate-aware-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    # Chat-turn commits to GA but emits no brief patch — exactly the
    # failure pattern reported by the user.
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message=(
                "I've set the search strategy to genetic search (GA) as a starting point. "
                "Click Run optimization for a baseline."
            ),
            panel_patch=None,
            problem_brief_patch=None,
        ),
    )

    with TestClient(create_app()) as client:
        sid = _create_agile_session(client)

        # Seed the session with a goal-term weight on the panel (mimicking
        # what the participant set in earlier turns). Without this, gate
        # would block on both goal_term AND algorithm — we want to isolate
        # the algorithm-injection path.
        patch = client.patch(
            f"/sessions/{sid}/panel",
            json={
                "panel_config": {
                    "problem": {
                        "goal_terms": {
                            "lateness_penalty": {
                                "weight": 10.0,
                                "type": "soft",
                                "rank": 1,
                            }
                        },
                        "goal_term_order": ["lateness_penalty"],
                        "algorithm": "",
                    }
                }
            },
            headers=_AUTH_HEADER,
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Maybe time window?", "invoke_model": True},
            headers=_AUTH_HEADER,
        )
        assert send.status_code == 200

        # The BG safety net runs in a daemon thread launched from the chat
        # handler. Poll until the algorithm assumption row lands or we hit
        # a generous timeout (CI variance on Windows).
        import time
        algo_rows: list[dict] = []
        last_items: list[dict] = []
        deadline = time.time() + 5.0
        while time.time() < deadline:
            session = client.get(f"/sessions/{sid}", headers=_AUTH_HEADER)
            assert session.status_code == 200
            last_items = (session.json().get("problem_brief") or {}).get("items") or []
            algo_rows = [
                item for item in last_items
                if (item.get("kind") == "assumption"
                    and "ga" in str(item.get("text") or "").lower())
            ]
            if algo_rows:
                break
            time.sleep(0.1)
        assert algo_rows, (
            "Expected the BG safety net to inject an assumption row "
            f"naming GA within 5s; last items={last_items!r}"
        )


def test_layer2_pre_release_probe_retries_when_gate_would_stay_closed(monkeypatch: pytest.MonkeyPatch):
    """Pre-release probe scenario: agile session with NO goal-term weight
    set anywhere; consolidated chat-turn returns is_run_invitation=True
    with no brief patch. Speculative gate stays closed (missing goal_term
    even after algorithm injection), so the router must re-call the
    consolidated helper once with an audit block.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-gate-aware-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    call_log: list[dict] = []

    def fake_consolidated(*args, **kwargs):
        call_log.append({"commit_audit_note": kwargs.get("commit_audit_note")})
        # First call: a run-invitation that would leave the gate closed.
        if len(call_log) == 1:
            return ConsolidatedChatTurn(
                assistant_message=(
                    "I'm starting from genetic search — click Run optimization for a baseline."
                ),
                cleanup_intent=False,
                clear_intent=False,
                is_change_intent=True,
                should_trigger_run=False,
                intent_type="none",
                confidence=0.0,
                is_run_invitation=True,
            )
        # Retry: agent softened the reply per the audit instructions.
        return ConsolidatedChatTurn(
            assistant_message=(
                "Before I can run, I still need to know what to prioritize "
                "(e.g. on-time delivery vs. travel time). Which matters more?"
            ),
            cleanup_intent=False,
            clear_intent=False,
            is_change_intent=False,
            should_trigger_run=False,
            intent_type="none",
            confidence=0.0,
            is_run_invitation=False,
        )

    monkeypatch.setattr(
        "app.services.llm.generate_consolidated_chat_turn", fake_consolidated
    )
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: None,
    )

    with TestClient(create_app()) as client:
        sid = _create_agile_session(client)
        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Can you start an optimization?", "invoke_model": True},
            headers=_AUTH_HEADER,
        )
        assert send.status_code == 200
        out = send.json()
        # The response is a session-snapshot envelope; `messages` carries
        # the newly-appended user + assistant rows.
        assistant_msgs = [
            m for m in (out.get("messages") or []) if m.get("role") == "assistant"
        ]
        assert assistant_msgs, f"no assistant message in response: {out!r}"
        # The retry message naming a clarifying ask should win.
        assert any(
            "still need to know" in (m.get("content") or "")
            for m in assistant_msgs
        ), f"expected softened reply, got assistant_msgs={assistant_msgs!r}"

    # Two calls total: original draft + one retry with the audit block.
    assert len(call_log) == 2, f"expected 2 calls, got {len(call_log)}: {call_log!r}"
    assert call_log[0]["commit_audit_note"] is None
    assert call_log[1]["commit_audit_note"] is not None
    # Audit block should name the gap explicitly so the agent has context.
    assert "DISABLED" in str(call_log[1]["commit_audit_note"])


def test_layer2_pre_release_probe_does_not_retry_when_gate_would_open(monkeypatch: pytest.MonkeyPatch):
    """Happy path: visible reply commits to GA AND the brief already carries
    a goal-term weight (panel-side). Speculative probe should find the gate
    would open after algorithm injection, so no retry fires.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-gate-aware-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    call_log: list[dict] = []

    def fake_consolidated(*args, **kwargs):
        call_log.append({"commit_audit_note": kwargs.get("commit_audit_note")})
        return ConsolidatedChatTurn(
            assistant_message=(
                "I've set the search strategy to genetic search (GA) as a starting point. "
                "Click Run optimization for a baseline."
            ),
            cleanup_intent=False,
            clear_intent=False,
            is_change_intent=True,
            should_trigger_run=False,
            intent_type="none",
            confidence=0.0,
            is_run_invitation=True,
        )

    monkeypatch.setattr(
        "app.services.llm.generate_consolidated_chat_turn", fake_consolidated
    )
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: None,
    )

    with TestClient(create_app()) as client:
        sid = _create_agile_session(client)
        # Seed a goal-term weight so layer-1 algorithm injection is
        # sufficient to open the gate speculatively.
        patch = client.patch(
            f"/sessions/{sid}/panel",
            json={
                "panel_config": {
                    "problem": {
                        "goal_terms": {
                            "lateness_penalty": {
                                "weight": 10.0,
                                "type": "soft",
                                "rank": 1,
                            }
                        },
                        "goal_term_order": ["lateness_penalty"],
                        "algorithm": "",
                    }
                }
            },
            headers=_AUTH_HEADER,
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Let's use GA", "invoke_model": True},
            headers=_AUTH_HEADER,
        )
        assert send.status_code == 200

    # Exactly one call: layer-1 injection covers the gap, no retry needed.
    assert len(call_log) == 1, (
        f"expected 1 call (no retry); got {len(call_log)}: {call_log!r}"
    )
    assert call_log[0]["commit_audit_note"] is None


def test_layer2_probe_retries_on_claims_brief_change_without_run_invite(
    monkeypatch: pytest.MonkeyPatch,
):
    """Compliance trigger: agent CLAIMS a brief change ("Added X") but does
    NOT invite a run. The previous probe gated only on is_run_invitation, so
    this slipped through and surfaced only as a post-derivation compliance
    warning. The expanded probe must fire when ``claims_brief_change`` is
    true and the speculative gate stays closed, retrying once with an
    audit block that names the gap.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-gate-aware-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    call_log: list[dict] = []

    def fake_consolidated(*args, **kwargs):
        call_log.append({"commit_audit_note": kwargs.get("commit_audit_note")})
        if len(call_log) == 1:
            # Claims a change, NOT inviting a run. Patch is empty (no goal_term,
            # no algorithm injected), so speculative gate stays closed.
            return ConsolidatedChatTurn(
                assistant_message=(
                    "Changes I made: Added a travel time efficiency objective "
                    "(weight 1.0, soft constraint) to minimize total transit "
                    "duration. They will populate once you hit Run optimization."
                ),
                cleanup_intent=False,
                clear_intent=False,
                is_change_intent=True,
                should_trigger_run=False,
                intent_type="none",
                confidence=0.0,
                is_run_invitation=False,
                claims_brief_change=True,
                asks_user_question=False,
            )
        # Retry: softer reply, doesn't claim a change it can't deliver.
        return ConsolidatedChatTurn(
            assistant_message=(
                "To minimize travel time I still need an algorithm choice and "
                "a confirmed goal weight. Which would you like to start with?"
            ),
            cleanup_intent=False,
            clear_intent=False,
            is_change_intent=False,
            should_trigger_run=False,
            intent_type="none",
            confidence=0.0,
            is_run_invitation=False,
            claims_brief_change=False,
            asks_user_question=True,
        )

    monkeypatch.setattr(
        "app.services.llm.generate_consolidated_chat_turn", fake_consolidated
    )
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: None,
    )

    with TestClient(create_app()) as client:
        sid = _create_agile_session(client)
        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "yes, minimize travel time", "invoke_model": True},
            headers=_AUTH_HEADER,
        )
        assert send.status_code == 200
        out = send.json()
        assistant_msgs = [
            m for m in (out.get("messages") or []) if m.get("role") == "assistant"
        ]
        assert assistant_msgs, f"no assistant message in response: {out!r}"
        # Retry response should win.
        assert any(
            "I still need an algorithm choice" in (m.get("content") or "")
            for m in assistant_msgs
        ), f"expected softened retry reply, got {assistant_msgs!r}"
        # Verified-after-retry marker must land in meta so the frontend can
        # render the inline badge.
        assert any(
            (m.get("meta") or {}).get("verified_after_retry") is True
            for m in assistant_msgs
        ), f"expected verified_after_retry meta on retry bubble, got {assistant_msgs!r}"

    assert len(call_log) == 2, f"expected 2 calls, got {len(call_log)}: {call_log!r}"
    assert call_log[0]["commit_audit_note"] is None
    assert call_log[1]["commit_audit_note"] is not None
    # Audit lead for claim-only trigger must NOT say "invited the participant
    # to click Run" (that's the run-invite-only lead). It must name the
    # commitment gap explicitly.
    note = str(call_log[1]["commit_audit_note"])
    assert "claimed a brief change" in note
    assert "DISABLED" in note


def test_layer2_probe_does_not_retry_when_no_claim_and_no_invite(
    monkeypatch: pytest.MonkeyPatch,
):
    """Negative control: a plain informational reply (no run invite, no claim
    of a brief change) MUST NOT trigger the probe — even when the
    speculative gate is closed for unrelated reasons. The probe is meant to
    catch over-promising; it should stay quiet on pure-question turns.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-gate-aware-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    call_log: list[dict] = []

    def fake_consolidated(*args, **kwargs):
        call_log.append({"commit_audit_note": kwargs.get("commit_audit_note")})
        return ConsolidatedChatTurn(
            assistant_message="Sure — what would you like to prioritize?",
            cleanup_intent=False,
            clear_intent=False,
            is_change_intent=False,
            should_trigger_run=False,
            intent_type="none",
            confidence=0.0,
            is_run_invitation=False,
            claims_brief_change=False,
            asks_user_question=True,
        )

    monkeypatch.setattr(
        "app.services.llm.generate_consolidated_chat_turn", fake_consolidated
    )
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: None,
    )

    with TestClient(create_app()) as client:
        sid = _create_agile_session(client)
        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "hello", "invoke_model": True},
            headers=_AUTH_HEADER,
        )
        assert send.status_code == 200

    # Single call: no retry budget consumed for a pure question turn.
    assert len(call_log) == 1, (
        f"expected 1 call (no retry), got {len(call_log)}: {call_log!r}"
    )
    assert call_log[0]["commit_audit_note"] is None
